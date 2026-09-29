# Fuentes de datos de altura / pisos de edificios para Zona Tec

Investigación realizada el 2026-09-28 para el proyecto PINN Zona Tec (CFD + PINN de viento
peatonal, Tecnológico de Monterrey Campus Monterrey y Distrito Tec). Bbox de trabajo usado
para las consultas automatizadas (coincide con el bbox ya usado por el agente de geometría
para Overpass, en `E:\PINN\v2\data\raw\osm\overpass_query.txt`):

`25.635,-100.315,25.670,-100.270` (lat_min, lon_min, lat_max, lon_max)

Este bbox es más amplio que el polígono real de "Zona Tec" (campus + Distrito Tec + anillo
de 1-2 manzanas, ver P17 de `grill-me.txt`, opción B recomendada por Hermann): incluye, por
ejemplo, el Macroplaza/Barrio Antiguo (~2 km al norte), fuera del dominio de interés. Todas
las tablas de este proyecto están indexadas por `osm_id` para que el equipo de geometría
pueda unir (join) solo los edificios que finalmente caigan dentro del polígono de Zona Tec.

Todos los scripts y datos crudos están en `E:\PINN\datos\alturas\raw\`. No se modificó nada
en `E:\PINN\v2\geometry\` ni en `E:\PINN\v2\data\raw\osm\` (solo lectura).

---

## 1. OpenStreetMap (tags height, building:levels, roof:levels, building:part, min_height)

- **URL**: https://www.openstreetmap.org/ , consultado vía Overpass API (dato ya cacheado
  por el agente de geometría en `E:\PINN\v2\data\raw\osm\osm_zonatec_raw.json`, mismo bbox).
- **Licencia**: ODbL 1.0 (Open Database License) — atribuir como "© OpenStreetMap
  contributors".
- **Fecha de acceso**: 2026-09-28.
- **Qué contiene para esta zona** (2,942 elementos `building`/`building:part` en el bbox):
  - `height` (medición/estimación explícita en metros): **53 elementos (1.8%)**.
  - `building:levels`: **1,947 elementos (66.2%)**.
  - `height` o `building:levels` (al menos uno): **1,967 elementos (66.9%)**.
  - `roof:levels`: **0 elementos**. `min_height`: **0 elementos**.
  - `building:part`: **11 elementos** (masificación LOD1.3 parcial, ninguno core-campus
    salvo un pequeño grupo cerca de CETEC/Aulas con levels 1-7; dos partes sueltas de 30 y
    40 m están cerca del Congreso del Estado, ~2 km del campus, fuera de Zona Tec).
  - 364 elementos tienen `name`.
- **Usable**: **Sí, es la fuente primaria** (como recomienda Hermann en P18: método A). Es
  trazable, citable, y cubre 2 de cada 3 edificios con algún dato de altura/pisos — pero
  ese dato es casi siempre `building:levels` estimado por un mapeador voluntario, no una
  medición. El caso de CETEC (ver sección 5) muestra que `building:levels` puede estar muy
  equivocado (8 niveles tageados vs. 11 reales, y un edificio con geometría inclinada que
  además no se refleja bien en un multiplicador simple de 3 m/piso).
- **Referencia (estilo APA)**: OpenStreetMap contributors. (2026). *Datos de edificios de
  Monterrey y Distrito Tec* [Conjunto de datos]. OpenStreetMap Foundation.
  https://www.openstreetmap.org/copyright

## 2. Overture Maps Foundation — tema `buildings`

- **URL**: https://overturemaps.org/ ; descarga vía `overturemaps` CLI de Python (bbox
  filtrado del release `2026-09-23.1`, catálogo STAC en https://stac.overturemaps.org/).
- **Licencia**: mixta por registro — porciones derivadas de OpenStreetMap son ODbL 1.0;
  porciones derivadas de Microsoft/Google Open Buildings son CDLA-Permissive-2.0 (Overture
  Maps Foundation, ver `docs.overturemaps.org`). El campo `sources[].dataset` de cada
  feature indica el origen exacto.
- **Fecha de acceso**: 2026-09-28.
- **Qué contiene para esta zona** (26,507 features `building` en el bbox):
  - Footprints por origen: **Microsoft ML Buildings: 16,550**; **Google Open Buildings:
    7,026**; **OpenStreetMap: 2,931**.
  - `height`: solo **20 features (0.08%)** — **el 100% de esos 20 valores provienen de
    OpenStreetMap** (verificado directamente en el JSON: `sources[].dataset ==
    ["OpenStreetMap"]` en cada uno).
  - `num_floors`: solo **1,938 features (7.3%)** — **el 100% también proviene de
    OpenStreetMap** (mismo chequeo).
- **Conclusión importante**: para esta zona, **Overture Maps NO aporta ninguna altura ni
  conteo de pisos independiente de OSM**. Los ~24,000 footprints adicionales que trae
  (de Microsoft y Google) son solo geometría, sin altura. Overture es útil para el equipo
  de geometría (más footprints que OSM solo), pero es redundante como fuente de altura —
  por eso no se generaron filas separadas de "Overture" en `alturas_investigadas.csv`
  (serían duplicados exactos de las filas de OSM).
- **Usable**: Sí para footprints (no es nuestro entregable), **no aporta nada nuevo para
  alturas** en esta zona específica.
- **Referencia (estilo APA)**: Overture Maps Foundation. (2026). *Overture Maps buildings
  theme, release 2026-09-23.1* [Conjunto de datos]. https://overturemaps.org/

## 3a. Google Open Buildings 2.5D Temporal (v1)

- **URL**: https://sites.research.google/gr/open-buildings/temporal/ ; datos descargados
  directamente vía Google Cloud Storage pública y anónima (sin cuenta de Earth Engine):
  `gs://open-buildings-temporal-data/v1/` (manifiestos por celda S2 nivel 2 + zona UTM;
  para Zona Tec: celda `87`, `EPSG:32614`, manifiesto `2023-06-30`).
- **Licencia**: dual, a elección del usuario — CC BY 4.0 u ODbL 1.0.
- **Fecha de acceso**: 2026-09-28. Época del raster usado: **2023-06-30** (el dataset
  cubre años 2016-2023 anuales; se usó el más reciente).
- **Cobertura confirmada para México/Latinoamérica**: SÍ — el dataset cubre ~58 millones
  de km² incluyendo África, Asia del Sur/Sureste y **América Latina y el Caribe**
  (incluye México). Esto **contradice/actualiza la nota de "cobertura no verificada" de
  P19** en `grill-me.txt`: sí hay cobertura para Monterrey.
- **Qué contiene para esta zona**: 3 bandas ráster a **0.5 m/pixel** (resolución nativa del
  GeoTIFF publicado, aunque el modelo subyacente tiene una resolución *efectiva* de ~4 m
  derivada de Sentinel-2 según la documentación de Google): `building_presence`,
  `building_height`, `building_fractional_count`. Se recortó solo la ventana de Zona Tec
  (sin descargar los tiles completos de 25,000×25,000 px) y se muestreó `building_height`
  en el centroide de cada uno de los 2,942 edificios de OSM.
  - **2,849 de 2,942 edificios (96.8%) obtuvieron un valor de altura > 0.**
  - **Validación puntual positiva**: para CETEC (edificio icónico con dato oficial de 43 m,
    ver sección 5), Google 2.5D estimó **46.3 m** — solo 7.6% de error.
  - **ALERTA DE CALIDAD — outliers detectados**: al cruzar contra la clase OSM
    (`building=house`, etc.) y contra `building:levels`, se detectaron **43 de 2,849
    valores (1.5%)** claramente inconsistentes con el tipo de edificio. El caso más
    grave: `osm_id 870573538`, tageado `building=house` con `building:levels=2` (una casa
    de 2 pisos en Calle Alejandría), para el cual Google 2.5D estimó **87 m** de altura —
    un error evidente. Se sospecha que la causa es el efecto de paralaje/sombra: un
    edificio alto vecino "se ve" recostado sobre el suelo en la imagen de satélite
    (problema conocido de estimar altura con imagen monocular/casi-nadir en vez de
    estéreo), contaminando el pixel de una construcción baja cercana.
  - Estos 43 casos fueron detectados automáticamente (regla: `building` en clase
    típicamente baja y altura > 20 m, o altura > 2.5× lo que implicaría
    `building:levels`×3m) y, en la consolidación, se usó el respaldo de OSM en su lugar
    quedando marcados como "discrepancia > 20%" — pero **es posible que existan más
    outliers no detectados por esta regla simple** (p. ej. en edificios sin
    `building:levels` con los que comparar). **No confiar ciegamente en un valor
    individual de Google 2.5D sin cruzarlo contra otra fuente.**
- **Usable**: **Sí, como fuente de control/relleno de alta cobertura** (como preveía la
  opción C de P19, ahora con cobertura confirmada) — mejor que nada para el 30% de
  edificios sin ningún tag de altura en OSM, y sorprendentemente bueno en el caso validado
  (CETEC), pero con una tasa de error detectable de ~1.5%+ que exige verificación humana
  para los edificios más altos e influyentes en el dominio (ver
  `lista_verificacion_campo.md`).
- **Referencia (estilo APA)**: Sirko, W., Kashubin, S., Ritter, M., Annkah, J. E., Bouchareb,
  Y. S. E., Dauphin, Y., Keysers, D., Neumann, M., Cisse, M., & Quinn, J. (2024).
  *Open Buildings 2.5D Temporal Dataset* [Conjunto de datos]. Google Research.
  https://sites.research.google/gr/open-buildings/temporal/

## 3b. Microsoft Global ML Building Footprints

- **URL**: https://github.com/microsoft/GlobalMLBuildingFootprints
- **Licencia**: ODbL 1.0.
- **Fecha de acceso**: 2026-09-28 (vía búsqueda web y vía el campo `sources` de Overture,
  sección 2).
- **Qué contiene para esta zona**: aporta **16,550 footprints** dentro del bbox (a través de
  Overture), la mayor parte de la "materia prima" de footprints de la zona. **NO** entrena
  un modelo de altura para México: la documentación del proyecto indica explícitamente que
  para México solo existen resultados de verificación de footprints (no un modelo de altura
  entrenado para el país), y en nuestros datos de Overture (sección 2), **cero** de los
  valores de `height`/`num_floors` provienen de Microsoft.
- **Usable**: para footprints sí (trabajo del otro agente); **para alturas, NO — confirmado
  sin datos de altura para México.**
- **Referencia (estilo APA)**: Microsoft. (2026). *GlobalMLBuildingFootprints* [Repositorio
  de software y datos]. GitHub. https://github.com/microsoft/GlobalMLBuildingFootprints

## 4. INEGI — LiDAR / Modelos Digitales de Elevación

- **URLs consultadas**:
  - https://www.inegi.org.mx/programas/mde/
  - https://www.inegi.org.mx/app/geo2/elevacionesmex/
  - https://www.inegi.org.mx/contenidos/temas/relieve/continental/doc/lidar_alta_resolucion.pdf
  - https://www.inegi.org.mx/contenidos/temas/mapas/relieve/continental/metadatos/mde.pdf
- **Licencia**: "Términos de libre uso e intercambio de datos" de INEGI (uso libre citando
  la fuente).
- **Fecha de acceso**: 2026-09-28.
- **Qué contiene, y qué NO se pudo confirmar para esta zona**:
  - INEGI produce dos familias de MDE: (a) el **Continuo Nacional fotogramétrico** de
    correlación cruzada, resolución **15 m**, exactitud ~3 m, cobertura de **todo el país**
    (incluye Monterrey con certeza) — pero **15 m de resolución horizontal no resuelve
    edificios individuales** (la mayoría de los footprints del campus miden menos de 30 m
    por lado) y es de tipo superficie/terreno agregado, no apto para extraer nDSM por
    edificio.
  - (b) El **LiDAR de alta resolución** (1-15 m de resolución, exactitud sub-métrica,
    15-90 cm), que sí resolvería edificios individuales (los ejemplos publicados de la
    Ciudad de México muestran siluetas de edificios claramente), pero su **cobertura es
    parcial por proyecto/vuelo**, no nacional.
  - **No se pudo confirmar cobertura LiDAR de alta resolución para el área urbana de
    Monterrey/Distrito Tec.** El único ejemplo de Nuevo León documentado públicamente por
    INEGI usa la clave de carta **F14A36d3**, que corresponde al municipio de **Mier y
    Noriega** (zona rural montañosa a ~200 km de Monterrey, cerca del límite con Tamaulipas/
    Coahuila), NO al área urbana (carta **G14C26 "Monterrey"**). Los ejemplos ilustrados con
    edificios claramente resueltos son de Ciudad de México, Chiapas y Tabasco — nunca de
    Nuevo León urbano.
  - La herramienta interactiva de descarga (`elevacionesmex`) es una aplicación JavaScript
    sin endpoints de API descubribles de forma estática; **no se pudo verificar
    programáticamente** si existe un tile LiDAR para la carta G14C26. Esto requiere
    verificación manual por una persona con navegador (ver `lista_verificacion_campo.md`).
- **Usable**: **NO confirmado / probablemente NO disponible** para uso en nDSM de edificios
  en esta zona específica. El Continuo Nacional 15 m sí está disponible para todo el país y
  podría usarse únicamente para **contexto orográfico regional** (relieve del valle de
  Monterrey, tal como ya contempla la opción D de P19 — canalización orográfica vía rosa de
  vientos, no vía CFD), nunca para alturas de edificios individuales.
- **Referencia (estilo APA)**: Instituto Nacional de Estadística y Geografía. (2026).
  *Modelos Digitales de Elevación (MDE)*. https://www.inegi.org.mx/programas/mde/

## 5. Fuentes oficiales del Tec / noticias

- **CETEC (Centro de Tecnología Avanzada para la Producción)** — **fuente de mayor
  confianza encontrada en toda la investigación**:
  - URL: https://conecta.tec.mx/es/noticias/monterrey/arte-y-cultura/cetec-legado-del-arquitecto-oscar-bulnes-para-monterrey
  - Contenido: nota editorial oficial de Conecta Tec (medio institucional del Tecnológico
    de Monterrey) sobre el arquitecto Óscar Bulnes. Indica que CETEC son **2 paralelepípedos
    de 11 niveles y 43 m de altura**, inclinados 30° de la vertical, inaugurados en 1989.
  - **Discrepancia crítica encontrada**: OSM tiene `building:levels=8` para este edificio
    (→ 24 m si se multiplica por 3 m/piso) — un error de **~44%** respecto a los 43 m
    reales, y ni siquiera el número de niveles (8 vs. 11) coincide. Este es exactamente
    el tipo de error que P18 en `grill-me.txt` advertía ("un error de altura en una torre
    cambia el viento de toda su estela").
  - Confianza: **alta**. Usar 43 m / 11 niveles para CETEC en vez del valor de OSM.
- **Torre Paragon** (privada, dentro de Distrito Tec, ~700 m del campus, NO en el campus):
  - URLs: https://www.paragonmty.mx/ ; https://investo.com.mx/propiedades/torre-paragon/
  - 10 niveles, uso mixto (34 departamentos + locales + oficinas). Altura en metros no
    publicada. Sin coordenadas exactas ni `osm_id` confirmado — pendiente de
    geocodificación y de cruce con el `buildings.csv` del equipo de geometría.
  - Confianza: media (sitio comercial, no institucional).
- **Lítica Torre 1 y Torre 2** (desarrollo "Nuevo Sur", Col. Ladrillera, Distrito Tec,
  Av. Revolución 2703-2):
  - URLs: https://litica.com.mx/ ; https://ucalli.com/project/litica/ ;
    https://monterreyskyline.com/property/departamentos-en-preventa-cerca-del-tec-de-monterrey-2/
    ; https://monterreyskyline.com/property/invierte-cerca-del-tec-de-monterrey/
  - Torre 1: **28 niveles**, 180 departamentos. Torre 2: **26 niveles**, 196 departamentos.
  - En preventa/construcción a la fecha de esta investigación (entrega de Torre 1 prevista
    para fines de 2026 según una de las fuentes) — **puede que aún no exista físicamente**
    o no esté mapeada en OSM. Si se confirma su ubicación dentro del anillo de 1-2 manzanas
    de Zona Tec, serían de los edificios más altos del dominio y deben modelarse con
    cuidado (o como variante "torre proyectada" según la opción B de P17 en
    `grill-me.txt`, que menciona exactamente ese escenario).
  - Confianza: **baja-media** (sitios comerciales/inmobiliarios, cifras de desarrollador
    sujetas a cambio, sin coordenadas exactas todavía).
- **No se consiguieron planos oficiales del campus** (Tec Infraestructura) — la opción D
  de P19 requeriría contacto directo con la universidad; queda fuera del alcance de una
  investigación web. Se recomienda que Hermann gestione esta solicitud si se requiere
  mayor precisión para los edificios ya identificados con discrepancia alta.

## 6. Wikipedia / Wikidata / SkyscraperPage / CTBUH

- Se usó una consulta SPARQL a Wikidata (https://query.wikidata.org/) acotada al bbox de
  Zona Tec (propiedades P625 coordenadas, P2048 altura, P1101 número de pisos). **Ningún
  edificio dentro de Zona Tec tiene datos de altura/pisos estructurados en Wikidata** (el
  único valor de altura devuelto, 94 m para el Museo de Historia Mexicana, es
  evidentemente erróneo/no aplicable y no se usó).
- Se revisó el Anexo:Edificios más altos de Monterrey de Wikipedia en español
  (https://es.wikipedia.org/wiki/Anexo:Edificios_m%C3%A1s_altos_de_Monterrey): los
  rascacielos más altos de Monterrey (Torre Obispado 1, 305 m; Torre KOI, 279 m; Torre
  Sohl, 268 m) están en San Pedro Garza García / Valle Oriente, **fuera de Zona Tec** (varios
  km de distancia) y no aplican a este dominio.
- **Conclusión**: Wikipedia/Wikidata no aportaron datos de altura utilizables para Zona
  Tec. Tal como indica la instrucción del proyecto, **no se cita Wikipedia como fuente
  final** en ninguna fila de `alturas_investigadas.csv`; se usó solo para orientar la
  búsqueda hacia fuentes primarias (que en este caso no aparecieron).

## 7. Mapillary / KartaView (imágenes a nivel de calle)

- Mapillary reporta cobertura creciente en México desde 2020 (campañas comunitarias de
  levantamiento para mejorar OSM), y Monterrey es una ciudad grande con probable cobertura
  razonable, pero **no se pudo verificar la cobertura pixel-a-pixel de Distrito Tec sin una
  API key** (la API v4 de Mapillary requiere un token de cliente para consultas
  programáticas; no se generó ninguna clave/secreto para este proyecto, conforme a las
  restricciones del encargo). El visor web (https://www.mapillary.com/app/) es de acceso
  público sin cuenta para inspección manual.
- **Licencia**: imágenes y datos derivados CC BY-SA 4.0 (Mapillary).
- **Usable**: como **apoyo para verificación humana de campo** (contar pisos en fotos),
  no como fuente automatizable en este entorno. Ver `lista_verificacion_campo.md` para los
  edificios donde más convendría revisar Mapillary (o Google Street View/Google Earth
  **solo como referencia visual humana** — recordatorio: no se debe extraer/scrapear datos
  de Google Maps/Earth por sus términos de servicio).

## 8. Datos abiertos municipales (IMPLAN Monterrey / datos.nl.gob.mx)

- Se localizó el **Reglamento de Zonificación y Uso de Suelo del Municipio de Monterrey**
  (https://www.monterrey.gob.mx/pdf/reglamentos/1/Reglamento_de_Zonificacion_y_Uso_de_Suelo_del_Municipio_de_Monterrey.pdf)
  y el **Programa Parcial de Desarrollo Urbano Distrito Tec**
  (https://visorproaxis.com/docs/PPDUMtyDistritoTec.pdf ; también
  https://www.monterrey.gob.mx/pdf/gacetas/2021/GacetaEnero2021EspecialDistritoTec.pdf).
  Estos documentos definen el polígono de 452 ha de Distrito Tec (24 colonias, campus de
  56 ha incluido) y probablemente contienen **alturas MÁXIMAS permitidas por zonificación**
  (no alturas reales construidas) — no se procesó el contenido completo de estos PDFs por
  límite de alcance/tiempo de esta investigación; **se recomienda como trabajo futuro**
  revisar la tabla de zonificación del Programa Parcial para usar el límite normativo como
  cota superior de verosimilitud (QA) en edificios sin otro dato.
  - Referencia (estilo APA): IMPLAN Monterrey / Municipio de Monterrey. (2015). *Programa
    Parcial de Desarrollo Urbano Distrito Tec*. https://visorproaxis.com/docs/PPDUMtyDistritoTec.pdf
- No se encontró un portal de datos abiertos de Nuevo León (`datos.nl.gob.mx`) con una
  capa descargable de alturas/pisos por predio. El CIG (Centro/Sistema de Información
  Geográfica y Geoestadística de NL, https://cig.nl.gob.mx/) existe pero no se confirmó
  contenido de alturas de edificios accesible sin trámite.
- **Usable**: no como fuente directa de alturas reales; potencialmente útil como cota
  normativa máxima (trabajo futuro).

---

## Resumen de cobertura (edificios de la Zona Tec, bbox de trabajo, 2,942 edificios OSM)

| Fuente | Edificios con dato | % del total | Independiente de OSM |
|---|---|---|---|
| OSM `height` tag | 53 | 1.8% | — |
| OSM `building:levels` tag | 1,947 | 66.2% | — |
| OSM height o levels (cualquiera) | 1,967 | 66.9% | — |
| Overture Maps (`height`/`num_floors`) | 1,956 | 7.4%* | **No** (100% redundante con OSM) |
| Google Open Buildings 2.5D Temporal | 2,849 | 96.8% | Sí (satelital, ~1.5% de outliers detectados) |
| Microsoft Global ML Buildings | 0 alturas | 0% | No aplica (sin modelo de altura para México) |
| INEGI LiDAR alta resolución | 0 (no confirmado) | — | No verificable/probablemente sin cobertura urbana |
| Oficial Tec / noticias | 1 edificio (CETEC) + 3 torres privadas cercanas (sin osm_id) | <0.1% | Sí, la de mayor confianza |
| Wikipedia/Wikidata | 0 | 0% | No aplica |

\* 7.4% de Overture aparenta ser información nueva pero es 100% un pass-through de los
mismos tags de OSM.

**Después de consolidar con la regla de prioridad (oficial > OSM height > Google 2.5D
"limpio" > OSM levels×3m > default), 2,890 de 2,942 edificios (98.2%) tienen una altura
recomendada que NO es el valor por defecto**, gracias sobre todo a la cobertura de Google
Open Buildings 2.5D Temporal. Los 52 restantes (1.8%) reciben el valor por defecto de 2
pisos × 3 m = 6 m, razonable para las colonias residenciales bajas que dominan el bbox
(1,822 de 2,942 edificios están tageados `building=house`).

## Regla de consolidación usada (`alturas_consolidadas.csv`, columna `regla_usada`)

1. **Oficial** (noticia institucional del Tec o desarrollador con nombre y URL) — máxima
   prioridad.
2. **OSM `height` tag** (medición/estimación explícita).
3. **Google Open Buildings 2.5D Temporal**, excluyendo los 43 valores marcados como
   outlier de calidad (ver sección 3a).
4. **OSM `building:levels` × 3 m** (asumido, incluye los casos donde Google 2.5D fue
   descartado por outlier).
5. Como último recurso (no ocurrió en la práctica: 0 edificios), un valor de Google 2.5D
   marcado como outlier.
6. **Default**: 2 pisos × 3 m = 6 m, para los 52 edificios sin ningún dato.

Cualquier edificio con dos o más fuentes numéricas cuya diferencia relativa supere 20% del
valor menor queda marcado `discrepancia_mayor_20pct = si` en `alturas_consolidadas.csv`,
con el detalle de cada valor por fuente en `detalle_discrepancia` — son 816 de 2,942
edificios (27.7%), reflejando sobre todo la diferencia sistemática entre
`building:levels`×3m (una convención de mapeo) y la altura satelital de Google 2.5D.
