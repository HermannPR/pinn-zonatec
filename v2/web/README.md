# PINN Zona Tec -- app web (v2/web)

Sitio estatico (sin servidor, sin paso de build) que deja elegir un punto en
un mapa real de Zona Tec (campus Tec de Monterrey + Distrito Tec,
Monterrey), una altura `z` y una direccion de viento, y muestra el viento
que predice la red neuronal entrenada (PINN), corriendo **100% en el
navegador** (JavaScript puro). Implementa P8 = A+B+C+E y P11 = A de
`E:\PINN\DECISIONES.md`.

**Estado actual: modelo de prueba (sintetico).** La red real de Zona Tec
todavia no existe (falta la campana CFD). El modelo cargado hoy es el
checkpoint de humo (`ml/runs/smoke/20260928_195807/stageC_fixed`), entrenado
sobre una escena sintetica de cajas solo para probar la tuberia de datos.
La app lo deja clarisimo con un banner amarillo ("MODELO DE PRUEBA
(sintetico)") leido de `model.json.metadata.synthetic`. Los valores de
viento mostrados **no son representativos de Zona Tec todavia**.

## 1. Estructura

```
v2/web/
  build/                  scripts Python que regeneran public/data/ a partir
                           de v2/ml, v2/geometry, v2/climate (idempotentes,
                           NUNCA escriben fuera de v2/web)
    common.py               helpers compartidos (frame.json, ENU<->lon/lat)
    export_model.py         checkpoint .pt -> public/data/model.json
    build_geometry_assets.py -> public/data/buildings.geojson,
                                 sdf_fine.bin/sdf_coarse.bin/sdf_grid_meta.json,
                                 height_grid.bin/height_grid_meta.json
    build_climate_assets.py -> public/data/climate.json (rosa 16 sectores +
                                 rugosidad por sector)
    build_scene.py           -> public/data/scene.json (marco, H_ref real,
                                 rangos de altura/UI)
  public/                  lo que se sirve tal cual (index.html, styles.css,
                           app.js, js/*.js, data/*)
  tests/                   gen_reference.py (Python, genera vectores de
                           referencia) + test_*.mjs (Node, compara JS vs
                           Python) + fixtures/ (generadas, no a mano)
  PROGRESO.md              bitacora de la sesion (por si se interrumpe)
```

## 2. Como reconstruir los datos (`public/data/`)

Desde `E:\PINN\v2` con el venv del proyecto:

```powershell
cd E:\PINN\v2
E:\PINN\.venv\Scripts\python.exe web\build\export_model.py
E:\PINN\.venv\Scripts\python.exe web\build\build_geometry_assets.py
E:\PINN\.venv\Scripts\python.exe web\build\build_climate_assets.py
E:\PINN\.venv\Scripts\python.exe web\build\build_scene.py
```

Cada script es independiente e idempotente; solo lee de `v2/ml`,
`v2/geometry/out/H_best` y `v2/climate`, y solo escribe en
`v2/web/public/data/`.

## 3. Como correr la app localmente

```powershell
E:\PINN\.venv\Scripts\python.exe -m http.server 8777 --directory E:\PINN\v2\web\public
```

Abrir `http://localhost:8777/index.html`. No hace falta Node ni npm para
correr la app (solo para las pruebas, seccion 6). MapLibre GL JS se carga
desde `cdn.jsdelivr.net` (version fijada `6.11.2`, comprobada contra el
registro de jsdelivr antes de fijarla).

**Teselas OSM**: la app usa `tile.openstreetmap.org` directamente (uso
ligero: una sola instancia de mapa, sin precarga masiva, atribucion
"© OpenStreetMap contributors" en el control de atribucion del mapa). Antes
de cualquier despliegue publico con trafico real, cambiar a un proveedor de
teselas de pago o autoalojado -- la politica de uso de OSM prohibe uso de
produccion sostenido sobre su servidor gratuito.

## 4. Como reemplazar el modelo de prueba por el modelo real

Cuando exista un checkpoint real entrenado sobre CFD de Zona Tec (no la
escena sintetica):

1. Editar las constantes al inicio de `build/export_model.py`
   (`CHECKPOINT`, `H_REF_TRAIN`, `NUM_FOURIER_BANDS`, `HIDDEN_LAYERS`, etc.)
   para que coincidan con el `config.yaml` del entrenamiento real. Para el
   modelo real, `H_REF_TRAIN` **debe** ser el `H_ref` real de
   `geometry/out/H_best/frame.json` (87.75 m hoy), porque el entrenamiento
   real usa la geometria real -- a diferencia del modelo de prueba actual
   (ver seccion 5).
2. Correr `export_model.py` de nuevo: sobrescribe
   `public/data/model.json` (mismo nombre de archivo -- ES ESO, un
   reemplazo de archivo, la app no cambia).
3. Poner `metadata.synthetic = False` (o quitar el bloque `metadata`, la
   app no lo requiere) para que desaparezca el banner amarillo.
4. Si el nuevo modelo usa una variante de geometria distinta de `base`,
   volver a correr `build_geometry_assets.py` apuntando a
   `sdf_grid_<variant>.npz` (cambiar la constante correspondiente).
5. Recargar la pagina. No hay que tocar `app.js`, `model.js`, `features.js`
   ni `climate.js`.

## 5. Diseno de datos (por que hay dos "H_ref" distintos)

`model.json` (formato de `ml/export.py`) trae `nondim.h_ref`: el `H_ref` **de
entrenamiento** de esa red concreta, usado para escalar las coordenadas de
entrada (`x,y,z / h_ref`, `altura_local / h_ref`) -- tiene que coincidir
EXACTO con el `h_ref` usado al entrenar para que el forward pass en JS
reproduzca el forward de PyTorch (por eso la prueba de la seccion 6 exige
1e-5). Para el modelo de prueba de hoy, ese valor es **25 m** (geometria
sintetica de cajas), sin relacion fisica con Zona Tec.

`scene.json` trae el `H_ref` **real** de Zona Tec (87.75 m,
`geometry/out/H_best/frame.json`, edificio de referencia real, fuente
Google Open Buildings 2.5D) mas la rugosidad por sector
(`climate.json`, metodo Macdonald/Overture, primario segun la revision
F1/G1). Estos son los que la app usa para convertir la salida
no-dimensional de la red (`u,v,w,k,nut` adimensionales) en unidades fisicas
reales (K, velocidad, direccion) -- ver `public/js/core.js:evaluatePoint`.

Esta separacion es deliberada mientras el modelo sea sintetico: el punto
clave (K = |U_local|/U10 solo depende de |vector no-dimensional| x
U_H(theta)/U10, y esta ultima razon es independiente de U10 y del `h_ref`
de entrenamiento de la red, ver derivacion en `core.js`) hace que, en
cuanto el modelo real se entrene sobre Zona Tec real, su propio
`nondim.h_ref` sera 87.75 y las dos rutas coincidiran solas, sin cambiar una
sola linea de `app.js`.

## 6. Pruebas (JS vs Python, obligatorias antes de cualquier entrega)

```powershell
cd E:\PINN\v2
E:\PINN\.venv\Scripts\python.exe web\tests\gen_reference.py   # regenera fixtures/
node web\tests\run_all.mjs                                    # corre las 3 pruebas
```

Resultados de la ultima corrida (ver salida completa en la sesion):

| Prueba | Que compara | Resultado |
|---|---|---|
| `test_model.mjs` | `model.js:forward()` vs `ml/export.py:predict_from_json` (torch), 100 puntos aleatorios, 6 salidas (u,v,w,p,k,nut) | **max\|diff\| = 1.06e-15** (tolerancia pedida: 1e-5) |
| `test_features.mjs` | `features.js:sdfAndHeight()` vs el MISMO grid re-muestreado/cuantizado que se descarga (60 puntos) | **max\|diff\| SDF = 3.6e-3 m, altura = 4.0e-3 m** (tolerancia = mitad del paso de cuantizacion, 5e-3 m) |
| `test_climate.mjs` | `climate.js` (Weibull, NEN 8100, Lawson LDDC, `transfer.py`) vs `windclimate.py`/`transfer.py`, 3 vectores K + 4 casos GEM + 16 sectores de transferencia | **max\|diff\| = 2.2e-16** en probabilidades, **0** en clases NEN8100/Lawson, **0** en `U_H/U10` por sector |

`test_features.mjs` tambien imprime, solo a modo informativo (no es un
criterio de aprobacion), cuanto se aleja el grid RE-MUESTREADO que se
descarga del grid ORIGINAL de entrenamiento (1 m/4 m): media 0.075 m, maximo
0.379 m sobre 60 puntos aleatorios en toda la zona de evaluacion -- ver
seccion 7.

`node --check` en los 9 modulos de `public/js/*.js` y `public/app.js` (no
hay build step: son ES modules planos, cargados tal cual por el navegador)
y una verificacion de que las 19 rutas que `index.html`/`app.js` referencian
(HTML, CSS, JS, y los 9 archivos de `data/`) responden 200 con
`python -m http.server` -- ver seccion 3. No se pudo abrir un navegador real
en este entorno (sin Chrome/Playwright instalado); esa es la brecha
declarada en la seccion 8.

## 7. Precision de la geometria en el navegador (SDF y altura)

El SDF exacto (`geometry/sdf.py: ExactPrismSDF`, union CSG de prismas LOD1,
el mismo que usa el entrenamiento real via
`ml/features.py:NestedSDFGridGeometry`) ya esta precalculado en
`geometry/out/H_best/sdf_grid_base.npz` (grid fino 1 m xy / 1 m z hasta 20 m,
grid grueso 4 m xy / 4 m z hasta 172 m). Para caber en el presupuesto de
<10 MB, `build_geometry_assets.py` NO recalcula el SDF -- solo lo
re-muestrea (fino: paso 4 en xy, mismo z; grueso: paso 2 en xy y z) y lo
cuantiza a `int16` (escala 0.01 m). La interpolacion en el navegador
(`public/js/features.js`) es una traduccion literal a JS de
`ml/features.py:_trilinear_nonuniform_z` / `_bilinear_uniform` (grid
anidado fino cerca del suelo + grueso arriba, igual que el entrenamiento).

Esto significa: la app es fiel al **grid que descarga** (error solo de
cuantizacion, <=5 mm, verificado en `test_features.mjs`), pero ese grid ya
tiene MENOS resolucion que el que ve la red durante el entrenamiento real
(error tipico 0.075 m, hasta 0.38 m en la muestra de 60 puntos). Para una
red que ya use `wall_scale=10 m` en la funcion `tanh(sdf/10)`, un error de
esa magnitud es pequeno frente al rango util (~metros), pero **si el
modelo real resulta muy sensible cerca de esquinas**, hay que subir la
resolucion del grid del navegador (a costa de mas MB) antes de publicar
resultados reales.

## 8. Brechas conocidas / cosas para revisar antes de un uso real

1. **No hay validacion en un navegador real** (Chrome/Firefox/Playwright no
   disponibles en este entorno). Se verifico exhaustivamente con
   `node --check`, resolucion de rutas HTTP, y las 3 pruebas de logica
   (seccion 6), pero falta un `console.log` limpio real, comportamiento del
   worker en un navegador de verdad, e interaccion tactil en movil.
2. **Modelo sintetico**: los valores de viento no significan nada fisico
   todavia (ver banner). Cuando llegue el modelo real, seguir la seccion 4.
3. **`buildings.geojson`** se vectorizo desde el raster de alturas
   (`height_raster.npy`, componentes conexas + union de celdas 1x1 m +
   `simplify`), no desde los poligonos originales de OSM/Overture/Google
   (que no se guardaron en un formato vectorial reutilizable en
   `geometry/out/`). El resultado (315 huellas, 264 componentes) es fiel al
   raster oficial pero puede fusionar visualmente edificios contiguos que
   comparten pared, y sus bordes estan simplificados (tolerancia 0.6 m) --
   aceptable para la vista 3D, no para medir areas con precision.
4. **Confort/excedencia solo via ajuste Weibull**: `windclimate.py` prefiere
   el estimador empirico directo (registro horario de 15 anios) cuando hay
   suficientes datos, porque el Weibull subestima la cola extrema (ver su
   docstring, revision F1/I3). Ese registro horario completo no se envia al
   navegador (seria pesado); la app usa siempre Weibull. Para umbrales muy
   raros (viento >15 m/s) esto puede subestimar la probabilidad real -- ver
   `climate.json.exceedance_method_note`.
5. **Marco de coordenadas**: ENU<->lon/lat usa una aproximacion de plano
   tangente (formula WGS84 estandar), no la proyeccion UTM 14N inversa
   exacta. El error es << 1 m en la escala de Zona Tec (<1 km), pero no es
   geodesicamente exacto -- documentado en `geo.js` / `build/common.py`.
6. **Etiquetas NEN 8100 / Lawson LDDC**: los cortes de clase y umbrales
   reproducidos vienen de un resumen secundario (revision F1), no del texto
   impreso de las normas -- ver aviso en `climate.js`/`windclimate.py` y el
   panel "Acerca de" de la app.
7. **Malla del mapa de calor**: 6 m de paso sobre la zona de evaluacion
   (650x650 m, ~110x110 celdas) -- suficiente para una vista rapida en el
   worker (miles de forward passes, milisegundos), pero es una malla
   gruesa, no apta para leer valores exactos punto a punto (para eso esta
   el clic + panel lateral, que evalua el punto exacto).
8. **Despliegue**: por instruccion explicita del proyecto, esta sesion NO
   despliega en Vercel ni en ningun otro lado -- requiere aprobacion
   explicita de Hermann (P11=A, `DECISIONES.md`).

## 9. Tamano del paquete

`public/` completo: **~4.5 MB** (sin contar MapLibre GL JS, que se sirve
desde CDN): `buildings.geojson` 1.3 MB, `sdf_fine.bin` 1.9 MB,
`height_grid.bin` 0.58 MB, `sdf_coarse.bin` 0.49 MB, `model.json` 0.21 MB,
`climate.json`/`scene.json`/`sdf_grid_meta.json`/`height_grid_meta.json`
~14 KB, HTML/CSS/JS ~80 KB. Bien dentro del presupuesto de <10 MB pedido.
