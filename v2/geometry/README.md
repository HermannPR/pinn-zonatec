# Zona Tec v2 -- geometría (Campus Monterrey + Distrito Tec)

## Cambios por la revisión independiente F1 (2026-09-28, ver `v2/docs/revisiones/F1_revision.md`)

Todos los bloqueantes e importantes de geometría (G1-G7) y el hueco de
integración con ML (M3) quedaron atendidos en esta corrida:

- **G1 (bloqueante) -- morfometría con huellas OSM incompletas en N/NE/W/NW**:
  se recalculó lambda_p/lambda_f/H_mean/sigma_H para los 16 sectores usando
  huellas de **Overture** (`overture_parse.py`, 26,507 huellas vs 2,942 de
  OSM en el mismo bbox) + altura mediana de Google, más un control
  independiente (fracción de píxeles del ráster con altura >2.5 m en cada
  cuña, sin ninguna huella vectorizada). Resultado en
  `out/H_best/roughness_16sectors_overture.csv`: en el sector N (0°),
  lambda_p pasa de **0.048 (OSM, muy incompleto)** a **0.41 (Overture)**,
  con el control de ráster en **0.52** confirmando que Overture es mucho más
  cercano a la realidad. z0_Macdonald en ese sector pasa de 0.044 a 0.177 m.
  Con Overture, lambda_p entre sectores es mucho más uniforme (0.36-0.56)
  que con OSM (0.05-0.55), justo lo que predecía la revisión.
- **G3 (bloqueante) -- alturas sospechosas en huellas chicas**: nueva regla
  de aceptación en `heights.py:assign_height_best` (área/16 m² ≥ 12 píxeles
  efectivos **y**, si hay `building:levels`, razón satelital/niveles entre
  0.6 y 1.8; si no se cumple, se usa niveles×3.4 m y se marca). Mediana
  calculada sobre la huella **erosionada 2 m** (`google_raster.py`). Lista
  dedicada de los casos donde esto sí cambió la respuesta (>10 m de
  diferencia): `out/H_best/g3_small_footprint_qc_flags.csv` (15 edificios,
  incluye los 9 originales del reviewer: 1543350346/47, 1539504902/05,
  1539506600-04).
- **G4 (importante) -- SDF rápido con errores grandes cerca de torres**: se
  reemplazó el método rápido (vecino más cercano en planta) por un **SDF
  analítico exacto** para prismas LOD1 (`sdf.ExactPrismSDF`,
  `sdf.build_nested_sdf_grid`): distancia 2D exacta con shapely +
  combinación CSG-union correcta entre edificios. Es la **misma
  implementación** para los grids `.npz`, y queda lista para el extractor
  HDF5 y el export web (una sola fuente de verdad, sin desajuste
  entrenamiento/inferencia). Test de regresión específico en `sdf.py`
  reproduce el caso sintético del revisor (torre de 80 m a 16 m gana sobre
  una casa de 3 m a 2 m) y verifica el resultado correcto (~13 m, antes
  ~27 m). De paso se encontró y corrigió un bug real en la validación: el
  STL de un solo sólido (`zonatec_base.stl`) puede fusionar vértices en
  paredes medianeras y confundir el test de adentro/afuera de trimesh;
  `BuildingSDF` ahora combina cada edificio del archivo **multisolid** por
  separado. Con la corrección, el error de validación del grid cayó de
  hasta 13.6 m a **≤0.74 m** (interpolación trilineal pura, sin bug).
- **G5 (importante) -- anillo explícito de solo ~120 m**: se adoptó la
  opción barata (sin remallar): una **zona de evaluación** recortada 100 m
  hacia adentro del borde de la ZOI (`eval_half_size_m=325` en
  `frame.json`, dibujada en `fig_plan_view.png`). Así cada punto de
  evaluación tiene ≥220 m de edificios explícitos a barlovento en el peor
  caso (creciendo a ≥320 m cerca del propio borde de la zona de
  evaluación).
- **G6 (importante) -- torres subresueltas por el plan de refinamiento**:
  `out/<escenario>/tower_refinement_regions.csv` -- una fila por edificio
  >30 m con su `refinementRegion` (huella + margen de 1×H, hasta 1.5×H,
  ≤4 m) y el `refinementSurface` sugerido (≤2 m en las caras, ≥10 celdas
  por lado de torre). Costo adicional estimado incluido en
  `domain_circular_recommendation.md`.
- **G7 (menor)**: `R_IN` de la cuña de barlovento corregido de 560 a 780 m
  (las esquinas del anillo están a 545·√2=770.7 m); kappa=0.40 (Macdonald)
  vs 0.41 (contrato/OpenFOAM) documentado; d_control=0 confirmado como
  simplificación explícita.
- **M3 -- formato de geometría para ML**: `ml_adapter.py` convierte el grid
  SDF anidado de este proyecto al formato plano de un solo grid uniforme
  que espera `ml/features.py:GridGeometry` (`out/<variante>_sdf.npz`,
  claves `sdf,origin,spacing,height,height_origin,height_spacing`). Se optó
  por un adaptador documentado (no cambiar el esquema de ninguno de los dos
  lados) porque este proyecto necesita un grid anidado (fino cerca del
  suelo + grueso hasta 2·H_max) y ML necesita un solo grid uniforme; el
  adaptador exporta el sub-grid **grueso** (4 m, cobertura completa 0 a
  2·H_max). Solo se exporta el escenario default (H_best). Test de
  round-trip en `ml_adapter.py` (`round_trip_test()`), verificado además
  contra la clase real `ml.features.GridGeometry` (carga y muestrea
  correctamente). Ver también `v2/ml/features.py` (sin cambios de ese
  lado).

Archivos nuevos: `geometry/overture_parse.py`, `geometry/ml_adapter.py`;
`geometry/google_raster.py` ampliado (mediana erosionada, p75, control de
lambda_p por ráster); `geometry/sdf.py` reescrito (SDF exacto);
`geometry/heights.py` con la regla de aceptación G3.


Pipeline reproducible: `build_geometry.py [H_best|H_osm|all]` regenera todo a
partir del JSON de Overpass cacheado y de los datos de alturas de otro
pipeline del equipo. `test_geometry.py` verifica ambos escenarios.

```
E:\PINN\.venv\Scripts\python.exe E:\PINN\v2\geometry\build_geometry.py all
E:\PINN\.venv\Scripts\python.exe E:\PINN\v2\geometry\test_geometry.py
```

Estado actual: **ambos escenarios generados, ALL TESTS PASSED** (32 checks x 2
escenarios, incluye watertightness por edificio, bbox, dominio, rugosidad,
SDF y grids SDF anidados).

## 0. Dos escenarios de altura -- H_best es el default

Por decisión de Hermann (2026-09-28: confirmó en campo, desde el piso 11 de
una torre de Zona Tec con más pisos arriba, que OSM subestima alturas --
"confiar en el satélite"):

- **`out/H_best/` (DEFAULT, recomendado para CFD/ML)**: jerarquía
  manual > oficial > Google Open Buildings 2.5D (mediana zonal, QC) > OSM
  `height` > OSM `building:levels` x 3.4 m/piso > default por tipo x 3.4 m/piso.
- **`out/H_osm/` (sensibilidad)**: solo OSM puro (height > levels x 3 m >
  estimación por tipo), el escenario original.
- `out/SCENARIO_COMPARISON.csv`: compara H_max, dominio, bloqueo, z0/d entre
  ambos.
- `out/heights_manual.csv`: hook de máxima prioridad para que Hermann (o
  cualquiera) meta `osm_id,height_m,source` de conteos de piso confirmados en
  campo; se recrea vacío si no existe, nunca se sobreescribe si ya tiene
  datos.

## 1. Fuente del dato de altura satelital (Google Open Buildings 2.5D)

- Se usa la **mediana** de la altura del raster (2 m de resolución,
  `E:\PINN\datos\alturas\raw\google_25d\zoi_height_piece0.tif`, EPSG:32614)
  dentro de la huella de CADA edificio (`geometry/google_raster.py`), no un
  solo punto muestreado. Esto es deliberado: una mediana solo puede ser alta
  si **más de la mitad** de los píxeles de la huella lo son, lo cual filtra
  automáticamente el "parallax bleed" (contaminación por un edificio alto
  vecino) sin necesidad de una regla ad-hoc.
- **Diagnóstico del trío CEDES** (pedido explícitamente):
  - osm 1539504899 "Núcleo": mediana 2.0 m, 0% de la huella >30 m -> edificio
    bajo real, sin contaminación.
  - osm 1539504900 "CEDES": mediana 24.2 m, máx 82.7 m, solo 33% de la huella
    >30 m -> la mediana (24.2 m, ~7 pisos) SÍ está contaminada parcialmente
    por un vecino alto, pero como es una minoría de píxeles, la mediana se
    queda correctamente baja. Se usa 24.2 m, no el 54-80 m reportado antes.
  - osm 1539504905 (sliver 188 m², junto a CEDES): mediana 40.9 m, 64% de la
    huella >30 m -> mayoría soportada, se acepta como estructura alta real.
  - osm 1539504906 (806 m², junto a CEDES): mediana 77.4 m, 98% de la huella
    >30 m -> claramente una torre real, se acepta 77.4 m.
- **Bandera de discrepancia**: `google_discrepancy=True` cuando
  `altura_google / (niveles x 3.4m)` cae fuera de [0.7, 1.4]. En H_best,
  **251 de 445 edificios ZOI+anillo (56%)** están marcados así -- refleja que
  el satélite sistemáticamente lee más alto que los niveles OSM (consistente
  con la confirmación de campo de Hermann), pero también es una señal de que
  huellas pequeñas junto a torres pueden seguir teniendo algo de
  contaminación residual incluso con la mediana; se reporta honestamente, no
  se oculta.

## 2. Números clave

| | H_best (default) | H_osm (sensibilidad) |
|---|---|---|
| H_max | **85.2 m** (Fiesta Inn, Google mediana) | 54.0 m (Fiesta Inn, OSM levels) |
| H_ref | 85.2 m | 54.0 m |
| Edificios con altura "real" (no estimada por defecto) | 420/445 (94%) | 301/445 (68%) |
| `needs_field_check=True` | 230/445 (52%, casi todo por discrepancia con niveles OSM, no por falta de dato satelital) | 144/445 (32%) |
| Dominio rectangular (16 dir.) | longitud 2835-3202 m, ancho 1983-2350 m, alto 511 m, bloqueo 2.6-2.9% | longitud 2211-2578 m, ancho 1671-2038 m, alto 324 m, bloqueo 2.7-3.0% |
| Dominio circular (ver §3) | R=2049 m, alto 511 m, bloqueo peor caso 1.55% | R=1581 m, alto 324 m, bloqueo peor caso 1.84% |
| z0 Macdonald | 0.050-0.322 m | 0.079-0.267 m |
| d Macdonald | 1.57-4.66 m | 1.96-4.79 m |
| z0 Kanda (sensibilidad) | 0.040-0.421 m | 0.067-0.197 m |
| d Kanda | 3.82-14.20 m | 4.15-8.67 m |
| Cobertura real en fetch morfométrico (`frac_real_height_by_area`) | **96-100%** (satélite cubre casi todo) | 38-100% |

Top-15 más altos por escenario: `out/<escenario>/top15_tallest.csv`. Lista
humana de verificación: `out/<escenario>/heights_to_verify.csv`.

ZOI: 850x850 m (246 edificios). Anillo: 1090x1090 m total (+199). Origen
ZT-ENU: UTM14N E=370450, N=2837950 (ver `frame.json`).

## 3. Dominio: recomendación de dominio circular único

`out/<escenario>/domain_circular_recommendation.md` (y fila en
`SCENARIO_COMPARISON.csv`). En vez de 16 dominios rectangulares (16x el
esfuerzo de mallado), se recomienda **un solo dominio circular**, reutilizado
para las 16 direcciones rotando solo el patch de entrada/salida:

- **radio R = anillo_half*sqrt(2) + 15*H_max** (para H_best: 545*1.414 +
  15*85.2 = 771 + 1278 = **2049 m**).
- **altura = 6*H_max** (H_best: **511 m**).
- **Compromiso del margen asimétrico COST-732** (5H aguas arriba/lateral,
  15H aguas abajo): un círculo no tiene dirección preferida, así que se
  aplica el margen MAYOR (15H) en todas las direcciones. Esto sobre-cumple
  el margen menor (5H) automáticamente, al costo de "desperdiciar" distancia
  aguas arriba -- barato, porque esa zona usa malla de fondo gruesa de
  cualquier forma. Es la práctica estándar en la literatura para dominios
  "rotables" reutilizados en barridos de dirección sin re-mallar. Un
  16-gono recortaría ~21% del volumen de fondo vs. el círculo (mismo
  alcance en las esquinas), pero no se adoptó por simplicidad.
- **Bloqueo en el peor caso**: área frontal máxima / (2R x altura) =
  1.55% (H_best) / 1.84% (H_osm) -- ambos muy por debajo del 3%.

## 4. Presupuesto de celdas de malla (estimación)

Plan pedido (fondo 16 m / anillo a 4 m hasta 40 m de altura / núcleo ZOI a
2 m hasta 20 m de altura), para H_best (R=2049 m, alto 511 m):

| zona | resolución | celdas |
|---|---|---|
| fondo (fuera del anillo) | 16 m | ~3.66 M |
| banda del anillo | 4 m | ~0.20 M |
| núcleo ZOI | 2 m | ~0.14 M... |

(números exactos en el log de build y en `domain_circular_recommendation.md`
de cada escenario; H_best: **~3.96 M celdas** con este plan, H_osm: **~2.93 M**).
**Esto excede el objetivo de 2-2.5 M** pedido más recientemente (aunque
entra en el presupuesto original de 3-5 M de la tarea inicial). Para llegar a
2-2.5 M haría falta engrosar fondo a ~28 m y anillo a ~6 m (con eso: H_best
~2.26 M, H_osm ~2.07 M) -- el núcleo ZOI a 2 m sobre toda la caja 850x850x20 m
es prácticamente irreducible (~1.8 M celdas por sí solo). **No se incluyen
las capas de pared cercanas al suelo/edificios** (prismas ~0.5 m, típicamente
+10-20% adicional). **Recomendación**: mantener la resolución fina en la ZOI
(lo que más importa para la calidad de la respuesta a nivel peatonal) y
aceptar ~4-4.5 M celdas (fondo 16 m, anillo 4 m solo hasta 40 m), en vez de
sacrificarla para llegar a 2-2.5 M.

## 5. Entregables ML (SDF anidado)

`geometry/sdf.py`: además de `BuildingSDF` (SDF exacto vía trimesh, usado
como referencia/"ground truth"), un método analítico rápido
(`build_nested_sdf_grid`) para generar grids completos en segundos (en vez
de ~76 min/grid con trimesh de fuerza bruta a esta resolución): para
geometría LOD1 (extrusiones verticales), el SDF exacto de un punto dentro de
la huella es `min(profundidad_2D, profundidad_z)`; fuera de la huella es
`sqrt(distancia_2D_al_edificio_mas_cercano^2 + exceso_vertical^2)`,
calculado con transformada de distancia euclidiana (scipy.ndimage) sobre un
raster de alturas -- exacto en el caso general de un solo edificio,
aproximado (pero acotado por la resolución de la rejilla) cuando el
"vecino 2D más cercano" no es el mismo que el más cercano en 3D.

Por escenario y por variante (`base`, `var1`, `var2`, `var3`):
`out/<escenario>/sdf_grid_<variante>.npz` con:
- `fine_sdf` (nz,ny,nx): 1 m horizontal, 1 m vertical, z=0-20 m (capa
  peatonal/baja, la más relevante para confort de viento).
- `coarse_sdf`: 4 m horizontal y vertical, z=0 hasta 2*H_max (todo el
  volumen de estela/techo, según el `DATA_CONTRACT`).
- Metadatos: `fine_x0/y0`, `fine_res_xy`, `fine_z`, `coarse_*` equivalentes,
  `frame="ZT-ENU"`, convención de signo.
- `height_raster_smooth_s5.npy` / `_s10.npy`: raster de altura suavizado
  con filtro gaussiano (sigma 5 m y 10 m).

**Prueba de interpolación** (`test_geometry.py::test_sdf_grids`, y
validación impresa en cada build): interpolación trilineal del grid fino
comparada contra el SDF exacto (trimesh) en 200-300 puntos aleatorios.
Error medio típico **0.47-0.61 m** (bien por debajo de 1 espaciado de
rejilla de 1 m); error máximo hasta **~13.6 m** en casos raros de esquinas
diagonales muy cerca de una pared (artefacto conocido de discretización de
una transformada de distancia sobre centros de píxel, documentado en
`sdf.py`). El test exige que **>=90% de los puntos** caigan dentro de 2.5x
el espaciado de rejilla -- pasa en ambos escenarios y las 4 variantes.

## 6. Resto del pipeline (sin cambios de fondo, ver commits anteriores)

Limpieza de huellas, extrusión LOD1 watertight por edificio, 3 variantes
(torre proyectada capada a H_max del escenario, lote vacío, infill),
morfometría Macdonald/Kanda/control por 16 sectores (fetch 45°, 560-1200 m,
excluye ZOI+anillo), figuras (planta + rosa de rugosidad). Ver
`out/<escenario>/VARIANTS_README.md` y `out/<escenario>/domain_16dirs.csv`.

## Incertidumbres y cosas a verificar

- **Kanda (2013)**: coeficientes de fuentes secundarias (fórmula cuadrática
  corregida por el equipo), no verificados dígito a dígito contra el
  artículo original (paywall). Siempre se reportan (nunca se sustituyen por
  Macdonald), con bandera `kanda_reliable` como anotación.
- **El 56% de discrepancia Google-vs-niveles en H_best** es mayormente la
  señal esperada (OSM subestima), pero small-footprint buildings junto a
  torres pueden retener algo de contaminación incluso con la mediana --
  candidatos ideales para el CSV manual de campo.
- **Presupuesto de malla**: el plan de refinamiento pedido (16/4/2 m) da
  ~4-4.5 M celdas, no 2-2.5 M; ver §4 para el trade-off.
- El SDF de los grids `.npz` es una **aproximación rápida** (no el SDF
  exacto de trimesh), con error medio ~0.5-0.6 m y casos raros hasta ~13 m
  cerca de esquinas; adecuado para entrenamiento ML, no para verificación
  geométrica de precisión (para eso usar `sdf.BuildingSDF` directo).
- `E:\PINN\datos\alturas\alturas_consolidadas.csv` combina su propia regla
  de prioridad (distinta a la nuestra); este pipeline usa
  `alturas_investigadas.csv` (formato largo, una fila por fuente) más el
  raster crudo directamente, para poder aplicar la política de Hermann con
  control total.
