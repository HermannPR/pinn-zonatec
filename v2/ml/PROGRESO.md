# Progreso -- ml/ (PINN Zona Tec), respuesta a la revision F1

Ultima actualizacion: 2026-09-28, sesion ML. Ver `docs/revisiones/F1_revision.md`
seccion 5 (M1-M13) para el texto completo de la revision.

## Estado de cada item (M1-M13)

| Item | Estado | Donde |
|---|---|---|
| M1 nut init + sigma + residuo | HECHO (parcial) | `models.py` (nut_scale=0.01), `train.py` (_nondim_nu, rampa+warmup), `config.py`. Normalizacion del residuo por escala de la CFD (M1.2/M1.3) NO implementada (requiere postProcess de OpenFOAM real; no aplica a datos sinteticos) |
| M2 LRA acotado | HECHO | `weighting.py` reescrito: lambda_i = sum\|grad_j\|/\|grad_i\|, EMA alpha=0.9, tope [1e-2,1e2]*lambda_i0, cada 100 pasos tras warmup |
| M3 geometria diferenciable real | HECHO | `features.py`: `NestedSDFGridGeometry` (lee el formato REAL de geometry/sdf.py, fine+coarse, z no uniforme) + `PolygonPrismGeometry` (SDF analitico suave, log-sum-exp, preferible per la revision M3(b)). `resolve_geometry_source` ya no falla en silencio (imprime warning) |
| M4 embedding de variante | HECHO | `models.py`: sin variant_id/embedding. `export.py`, `data.py`, `train.py` actualizados |
| M5 perdida por campo | HECHO | `data.py: CaseStore.field_stats`, `losses.py: data_loss(..., field_std=...)` |
| M6 residuo junto a pared | HECHO | `data.py: CaseData.fluid_idx`, `EpochSampler.sample_supervised(..., fluid_only=True)`, ponderacion por volumen en `losses.py` |
| M7 rasgos en puntos de pared | HECHO | `synthetic.py: _wall_faces` guarda `height` real; `data.py: sample_wall` la usa; muestreo 80/20 edificio/suelo |
| M8 etiquetado de zonas | HECHO (parcial) | `metrics.py: label_zones` reescrito, vectorizado (k-NN fijo, sin bucle Python), solo caras de edificio, radios por H_b. La definicion exacta de esquina/canyon sigue siendo una heuristica simplificada (no el angulo interior exacto de vertice) |
| M9 particion y referencias | HECHO (parcial) | `data.py`: split solo del manifiesto + sello SHA-256 (`ml.synthetic.seal_manifest`, `verify_manifest_seal`), `nearest_train_cases` solo split=='train'. `baselines.py`: reescala por velocidad (`_rescale_by_speed`, con bug de exponentes corregido y prueba), interpolacion angular exige vecino a cada lado, oracle etiquetado como tal. NO hecho: direcciones de validacion 67.5/202.5 (el smoke usa 8 direcciones a 45°, no el esquema real de 16 sectores a 22.5°; el punto se documenta, no se traslada 1:1) |
| M10 metricas peatonales | HECHO | `metrics.py`: `pedestrian_layer_mask`, todas las metricas aceptan `weight=vol`. `train.py: evaluate_model` reporta capa peatonal 1.5-2.0 m ademas del ZOI completo, y acepta `eval_half_size_m` (zona de evaluacion real 650x650 m, `frame.json: eval_half_size_m`) |
| M11 U10 en DeepONet | HECHO | `models.py: DeepONetPINN` -- rama = solo (sin,cos theta) |
| M12 contrato de datos | Diff propuesto (NO aplicado; docs/ fuera de mi alcance) | ver reporte final / seccion abajo |
| M13 menores | HECHO | `features.py: scale_sdf(..., wall_scale=10.0)` desacoplado de h_ref |
| transfer.py (I2) | HECHO | `export.py`: nota corregida (T(theta) del transfer P14-A, no formula sin transferencia). `ml/tests/test_transfer_consistency.py` verifica contra `climate.transfer` |
| geometria: sdf_grid real | HECHO | `NestedSDFGridGeometry` ya lee `geometry/out/H_best/sdf_grid_<variant>.npz` (fine 1m z<=20m + coarse), NO el archivo plano nuevo en `geometry/out/<variant>_sdf.npz` (ese es solo coarse) -- ya cubre el pedido de "grid de dos niveles" |
| estado.json | HECHO | `train.py: TrainConfig.heartbeat` (default False); si True, solo refresca detalle/latido, nunca corriendo/fase/caso/proceso (la cola es duena de esos campos) |

## Bugs encontrados y corregidos DURANTE esta sesion (no en la revision original)

1. `synthetic.py`: la regularizacion del doblete (r2c) no era consistente con
   su propia derivada analitica -- rompia continuidad exacta. Corregido
   (r2+Rmin^2 en vez de max(r2,Rmin^2)), verificado por diferencias finitas
   (~1e-7).
2. `physics.py`: `losses.py` re-cortaba x,y,z de `xyz` DESPUES de que el
   modelo ya habia consumido `xyz` directamente -- x,y,z quedaban como nodos
   hermanos, no ancestros, del grafo de autograd. `physics.py` ahora
   diferencia respecto a `xyz` completo y corta columnas del RESULTADO.
3. `physics.py: _grad_wrt_xyz` no toleraba una entrada cuya derivada
   verdadera es una constante (ej. v=w=0 en Poiseuille) -- ahora regresa
   ceros en vez de fallar.
4. `data.py`: L-BFGS reutilizaba `col.sdf_m` (con su propio grafo) en cada
   llamada de `closure()`; el primer `backward()` liberaba ese grafo y la
   segunda llamada fallaba. Corregido: se recalcula la geometria
   diferenciable en cada `closure()`.
5. `baselines.py: _rescale_by_speed` tenia las potencias de U_H invertidas
   (u,v,w con potencia 0 en vez de 1) -- silenciosamente rompia exactamente
   el baseline que se habia escrito para arreglar. Corregido + prueba
   (`test_baselines.py`) que usa la autosimilitud exacta del generador
   sintetico como referencia.
6. `metrics.py: label_zones` (primera reescritura para M8) usaba bucles de
   Python por punto con `query_ball_point` de radio variable -- colgo >5 min
   a escala de smoke test (46k puntos x 5 casos). Reescrito totalmente
   vectorizado (consultas k-NN fijas de scipy, sin bucle Python).
7. `synthetic.py`: la malla vertical uniforme (NZ=22 sobre 60 m) no tenia
   NINGUN punto en la banda peatonal 1.5-2.0 m, dejando vacia cualquier
   metrica peatonal (M10) en el smoke test. Corregido con niveles
   explicitos cerca del suelo; `vol` (volumen de celda) recalculado para la
   malla vertical no uniforme resultante.

## Como continuar si esta sesion se interrumpe

1. `cd E:\PINN\v2`
2. `E:\PINN\.venv\Scripts\python.exe -m pytest ml/tests -v` (18 pruebas, deben pasar)
3. Los datos sinteticos y el manifiesto sellado ya estan en
   `E:\PINN\v2\data\synthetic\` (regenerar con `python -m ml.synthetic` si
   se tocan `synthetic.py` de nuevo).
4. Corridas del smoke test en `E:\PINN\v2\ml\runs\smoke\20260928_195807\`
   (stageA, stageB, deeponet, stageC, stageC_fixed) -- todas con el codigo
   actual (post-fixes). `stageC` usa LRA (P26=A tal cual se pidio);
   `stageC_fixed` es el mismo stage con pesos fijos, mejor para leer el
   resultado dado lo corto del smoke.
5. `docs/revisiones/F1_revision.md` seccion 5 tiene el texto completo M1-M13
   si hace falta revisar el detalle de un item marcado "parcial" arriba.
