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
- [x] build/export_model.py (checkpoint smoke stageC_fixed -> model.json, 215.7 KB)
- [x] build/build_geometry_assets.py (buildings.geojson 315 huellas/1.29 MB;
      sdf_fine.bin 1.86 MB + sdf_coarse.bin 0.49 MB + height_grid.bin 0.58 MB,
      re-muestreados del sdf_grid_base.npz/height_raster_smooth_s5.npy reales)
- [x] build/build_climate_assets.py (climate.json: 16 sectores, windrose_16.csv +
      roughness_16sectors_overture.csv metodo macdonald)
- [x] build/build_scene.py (scene.json: H_ref real 87.75 m, rangos UI)
- [x] JS: model.js, features.js, climate.js, geo.js, core.js (puertos)
- [x] worker.js (heatmap en background, module Web Worker)
- [x] map.js + ui.js + index.html + styles.css (MapLibre 6.11.2 via CDN,
      OSM raster + atribucion, extrusion 3D por altura, panel lateral,
      chart polar K de 16 sectores, tablas NEN8100/Lawson, banner sintetico,
      panel Acerca de/Fuentes)
- [x] tests/ (gen_reference.py + test_model.mjs, test_features.mjs,
      test_climate.mjs, run_all.mjs) -- TODAS PASAN:
      modelo max|diff|=1.06e-15 (tol 1e-5), features max|diff|=3.6e-3 m SDF /
      4.0e-3 m altura (tol cuantizacion 5e-3 m), clima max|diff|=2.2e-16 +
      0 mismatches de clase + transfer.py exacto en los 16 sectores.
- [x] Servir con http.server y verificar las 19 rutas (HTML/CSS/JS/data) con 200,
      node --check en los 9 modulos + app.js sin errores de sintaxis.
      (No se pudo abrir un navegador real en este entorno -- brecha
      declarada en README.md seccion 8.)
- [x] README.md (espanol): build, run, swap de modelo, resultados de
      pruebas, tamano del paquete (~4.5 MB), brechas conocidas.
- [x] Reporte final a Hermann/usuario.

Sesion cerrada, sin pendientes de esta lista. Ver README.md seccion 8 para
brechas conocidas (banco de trabajo futuro).

## Como continuar si esta sesion se interrumpe
1. Revisar la lista de arriba, retomar en el primer `[ ]`.
2. Los scripts de build son idempotentes (leen de `v2/geometry`, `v2/ml`,
   `v2/climate`, escriben solo en `v2/web/public/data`).
3. `E:\PINN\.venv\Scripts\python.exe` es el interprete con todas las deps
   (numpy, scipy, shapely, pyproj, torch, pandas). No hay skimage.
