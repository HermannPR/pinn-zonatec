# PINN Zona Tec

Viento urbano en la Zona Tec (Monterrey) para cualquier dirección y velocidad, sin correr una CFD nueva.

El proyecto empezó como una red PINN (Physics-Informed Neural Network) que debía aprender el campo de viento de una campaña de simulaciones RANS. Al compararla con métodos clásicos, ganó una interpolación lineal en la dirección del viento. Lo que más redujo el error fue tener más CFD, no un modelo más complejo. Por eso el entregable final es esa interpolación sobre 32 simulaciones (una cada 11.25°).

## Entrega final (29 oct 2026)

- [Informe final (PDF)](docs/entrega/PINN-ZonaTec-informe-final.pdf): problema, qué se probó, resultado, uso y límites.
- [Video de 36 s](docs/entrega/PINN-ZonaTec-viento-interpolado.mp4): viento a nivel peatón mientras la dirección da la vuelta completa.
- [Informe en Markdown](docs/informe-final-pinn-2026-10-29.md), con las mismas cifras.

## Resultado

| medida | valor |
|---|---|
| Dejar uno fuera sobre las 32 direcciones (hueco de 22.5° entre vecinas) | L2 medio 0.187, máximo 0.227 |
| Error peatonal medio en esa prueba | 0.046 u_h |
| Error estimado en uso real (hueco de 11.25°, peor caso) | ~0.12 |
| Escala con la velocidad (consulta a 10 m/s contra la CFD real a 10 m/s) | L2 0.004 |

L2 es el error relativo medio de la velocidad. Crece con el hueco angular entre simulaciones vecinas (aproximadamente hueco^0.66):

| hueco | L2 medio | máximo |
|---|---|---|
| 22.5° | 0.187 | 0.227 |
| 45° | 0.290 | 0.346 |
| 90° | 0.473 | 0.508 |

Con solo 12 direcciones de entrenamiento, la PINN 3D (0.28-0.33) y los métodos clásicos (spline y proceso gaussiano periódicos) quedaron peor que la interpolación lineal. La comparación completa está en [docs/estado-pinn-2026-10-22.md](docs/estado-pinn-2026-10-22.md).

## Cómo funciona

1. Toma las dos simulaciones vecinas a la dirección pedida.
2. Interpola entre ellas los campos adimensionales: velocidad entre u_h y presión entre u_h² (u_h es el viento a la altura de referencia).
3. Escala el resultado a la velocidad pedida: velocidad lineal con U10 y presión con U10². La similitud de Reynolds se validó contra la CFD a 10 m/s.

Solo carga dos casos por consulta y responde en segundos. Cada caso tiene 1.65 millones de celdas.

## Uso

Requiere Python 3 con `numpy` y `h5py`, y la carpeta de datos CFD (ver abajo).

```bash
cd train
python -I interp_denso.py consulta <carpeta_v2> <theta_grados> <U10> salida.h5
python -I interp_denso.py evaluar  <carpeta_v2> [N_puntos] [salida.json]
```

- `consulta` escribe un HDF5 con la misma malla que los datos procesados (x, y, z, cell_id, vol, is_wall_adjacent). Incluye u, v, w en m/s y la presión cinemática p. Los atributos guardan theta, U10, u_h y las dos vecinas con sus pesos.
- `evaluar` repite la prueba de dejar uno fuera y guarda las métricas.
- `train/hueco.py <carpeta_v2> <carpeta train>` mide el error contra el hueco angular (tabla de arriba).

Alcance: caso base, malla m1. Las variantes de geometría var1 y var2 solo tienen 8 direcciones (cada 45°). El mismo script sirve cambiando `variant` en `malla()`, con un error esperado de ~0.29 o más.

## Datos

Las simulaciones CFD (OpenFOAM, `simpleFoam`, ~19 GB) no están en el repositorio. Se piden aparte y se colocan en `f3/paquete/pinn/v2/`. `data/processed/manifest.csv` lista los 57 casos:

- 32 direcciones del caso base, una cada 11.25°;
- estudio de malla (GCI);
- prueba de velocidad (10 m/s);
- variantes de geometría var1 y var2.

## Estructura

| carpeta | contenido |
|---|---|
| `train/` | `interp_denso.py` (entregable), `hueco.py` (error contra hueco), `clasicos.py` (lineal, spline y GP), `f4.py` (PINN 3D paramétrica, histórico), `correr.sh` (entrenamiento que cede y reanuda) |
| `m5/` | Scripts que corrieron la campaña CFD: cola nocturna (`noche.sh`), variantes de geometría y rescate de casos fallidos |
| `docs/` | Informe final, estado del 22 oct, informe de cierre del 18 oct (PDF) y métricas en JSON por fecha |
| `docs/entrega/` | PDF y video de la entrega final |
| `grill/` | Interrogatorio de diseño de la fase 1 (preguntas, respuestas y plan del equipo) |
| `sim/`, `public/`, `video/`, `data/` | Demo inicial en 2D (ver abajo) |

## Demo inicial en 2D

Antes de la campaña CFD se hizo una prueba de concepto con una ciudad sintética. Esta simulación no representa mediciones reales:

- `sim/lbm.py` simula el viento en 2D con Lattice Boltzmann y escribe `data/field.npz`.
- `train/pinn.py` entrena una PINN con pocos sensores (L2 0.317 contra 0.396 de la interpolación).
- `public/` es la web interactiva. Se abre con:

  ```bash
  python -m http.server 8766 --directory public
  ```

  y luego `http://localhost:8766` en el navegador.
- `video/` genera por código la película de 45 s (ver [video/README.md](video/README.md)).

## Siguientes pasos

Para bajar del ~0.12 conviene más CFD en las direcciones con más error (cada 5.625° entre 135° y 225°). Otra opción es un método que alinee las estelas entre direcciones vecinas (sPOD o interpolación en Grassmann). Una red residual suave en theta no corrige el desplazamiento de las estelas, que es el error dominante.

## Equipo

Hermann Pauwells Rivera y Oscar Cardenas.
