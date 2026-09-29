# Progreso -- v2/web (PINN Zona Tec, ingeniero web)

Ultima actualizacion: 2026-09-28 (sesion web). Este archivo se actualiza en
cada hito grande para poder retomar el trabajo desde disco si la sesion se
interrumpe (API rate limit, etc.).

## Contexto leido antes de empezar
- `DECISIONES.md` P8-P11 (salidas A+B+C+E, altura B, confort C, interfaz A).
- `v2/docs/DATA_CONTRACT.md`: frame ZT-ENU, origin en `frame.json`, theta
  meteorologico (FROM), U_ref=U10, eval_half_size_m=325 (zona de evaluacion
  real 650x650 m).
- `v2/ml/export.py` + `v2/ml/README.md` + `v2/ml/PROGRESO.md` (sesion ML,
  post F1 review M1-M13): SIN embedding de variante; geometria entra solo
  por sdf/local_height; K real viene de `climate/transfer.py` (T(theta)),
  NO del `nondim.z0/d` horneado en el JSON exportado (eso es solo para el
  caso concreto exportado -- el disenio correcto es un archivo aparte de
  16 sectores, ver nota en `export.py`).
- `v2/geometry/sdf.py`: SDF canonico = `ExactPrismSDF` / `build_nested_sdf_grid`
  (union CSG exacta de prismas LOD1, sin aproximacion de "edificio mas
  cercano en planta"). `geometry/out/H_best/sdf_grid_base.npz` (y var1/2/3)
  ya tiene el grid fino (1 m, z 0-20 m, 850x850) + grueso (4 m, z 0-172 m,
  213x213) -- exactamente lo que `NestedSDFGridGeometry` (ml/features.py)
  lee para entrenar. El plan es REUSAR este grid (no recalcular el SDF),
  solo re-cuantizarlo/der-muestrearlo para el navegador.
- `v2/climate/windclimate.py` + `transfer.py` + `windrose_16.csv`: rosa de
  16 sectores (frecuencia, U10 medio, Weibull c/k) + transferencia de dos
  capas (T(theta) desde `roughness_16sectors_overture.csv`, metodo
  'macdonald' primario) + NEN 8100 / Lawson LDDC.
- Modelo de prueba: `ml/runs/smoke/20260928_195807/stageC_fixed/checkpoint.pt`
  (hibrido con fisica, pesos fijos, converge razonablemente en el smoke
  test). Config: h_ref=25.0, hidden=[64,64,64], num_fourier_bands=8,
  sigma=4.0, sdf_wall_scale=10.0, nut_scale=0.01, k_scale=1.0, tanh.

## Nota de sesion concurrente
Otra sesion (ml) esta trabajando en paralelo sobre `E:\PINN\v2\ml` /
`geometry` / `climate` en este mismo arbol. Este trabajo toca UNICAMENTE
`E:\PINN\v2\web\` (lee de las otras carpetas, nunca escribe en ellas), por
lo que no deberia haber colision. `E:\PINN\estado.json` no se toca.

## Diseno de datos para el navegador (decisiones)
- `model.json`: export directo de `ml.export.export_pinn_mlp` sobre el
  checkpoint smoke stageC_fixed de arriba. `nondim.h_ref=25.0` (el h_ref DE
  ENTRENAMIENTO del smoke -- necesario para que el forward pass en JS
  reproduzca el forward de torch a 1e-5). Marcado
  `metadata.synthetic=true` a mano tras exportar (bandera para el banner
  "MODELO DE PRUEBA").
- El H_ref REAL de Zona Tec (87.75 m, `geometry/out/H_best/frame.json`) y
  el z0/d por sector (`roughness_16sectors_overture.csv`, metodo
  macdonald) se usan por SEPARADO, en `scene.json` + `climate.json`, para
  calcular U_H(U10,theta) fisico (formula de `transfer.py`). Esto es
  deliberado: el modelo smoke fue entrenado con geometria sintetica
  pequena (h_ref=25) y no tiene relacion fisica real con Zona Tec; cuando
  se reemplace por el modelo real entrenado sobre Zona Tec, su propio
  `nondim.h_ref` sera 87.75 y las dos rutas coincidiran solas. Documentado
  tambien en README.md como brecha conocida del modelo de prueba.
- SDF/altura para el navegador: RE-CUANTIZACION del `sdf_grid_base.npz`
  real (fino 1 m z=0-20m + grueso 4 m z=0-172m) a un grid mas grueso
  (fino->4 m xy conservando 21 niveles z; grueso->8 m xy, 22 niveles z),
  quantizado int16 (cm), <10 MB en total. Interpolacion trilineal con
  z no uniforme en JS, replicando
  `ml/features.py: _trilinear_nonuniform_z`.
- `buildings.geojson`: vectorizado desde `height_raster.npy` (446
  edificios de `buildings.csv`) por componentes conexas + union de
  cuadritos de 1 m (shapely) + simplify, reproyectado UTM14N->lon/lat con
  pyproj usando `frame.json`.

## Estado (ir marcando)
- [x] Exploracion / lectura de contrato y codigo existente.
- [ ] build/export_model.py
- [ ] build/build_geometry_assets.py (buildings.geojson + grids SDF/altura)
- [ ] build/build_climate_assets.py (windrose_16.json + roughness sectors)
- [ ] build/build_scene.py (frame/escena)
- [ ] JS: model.js, features.js, climate.js (puertos)
- [ ] worker.js (heatmap en background)
- [ ] map.js + ui.js + index.html + styles.css (UI, reusa v1 donde aplica)
- [ ] tests/ (Python genera vectores de referencia; Node verifica JS)
- [ ] Servir con http.server 8777 y verificar carga sin errores
- [ ] README.md (espanol)
- [ ] Reporte final a Hermann/usuario

## Como continuar si esta sesion se interrumpe
1. Revisar la lista de arriba, retomar en el primer `[ ]`.
2. Los scripts de build son idempotentes (leen de `v2/geometry`, `v2/ml`,
   `v2/climate`, escriben solo en `v2/web/public/data`).
3. `E:\PINN\.venv\Scripts\python.exe` es el interprete con todas las deps
   (numpy, scipy, shapely, pyproj, torch, pandas). No hay skimage.
