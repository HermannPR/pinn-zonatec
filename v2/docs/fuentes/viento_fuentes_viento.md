# Fuentes de datos de viento y capa límite atmosférica — Zona Tec (Campus Monterrey)

Documento de investigación para el proyecto PINN Zona Tec (OpenFOAM RANS + PINN de viento a nivel
peatonal, Tecnológico de Monterrey, Campus Monterrey, 25.651 N, -100.290 O).

Fecha de investigación: 28 de septiembre de 2026. Autor: agente de investigación (Claude).

Nota: la descarga y el procesamiento de NOAA ISD (aeropuertos MMMY/MMAN) para una rosa de 16
sectores en `E:\PINN\v2\climate\` la realiza **otro agente en paralelo**; este documento no
duplica ese trabajo, solo lo referencia para comparación cuando esté disponible. Al momento de
escribir esto, `E:\PINN\v2\climate\` seguía vacío (sin `windrose_16.csv`).

---

## A. Datos climáticos

### A.1 SMN/CONAGUA — Estaciones Meteorológicas Automáticas (EMA)

- **URL:** https://smn.conagua.gob.mx/es/observando-el-tiempo/estaciones-meteorologicas-automaticas-ema-s
- **Qué hay:** Red nacional de EMA (y ESMA) que mide viento (velocidad y dirección), presión,
  temperatura, humedad relativa, radiación solar y precipitación, siguiendo estándares OMM. La
  página ofrece un mapa interactivo y dos descargas: "KMZ de estaciones" y "lista de estaciones",
  ambas servidas por componentes JavaScript/Joomla sin URL directa de archivo visible en el HTML
  estático (no se pudo extraer un enlace directo con `curl`; requiere navegación manual en el
  sitio o interacción con el mapa). **[no verificado]** la existencia/ubicación exacta de
  estaciones EMA específicas dentro del área metropolitana de Monterrey (no se encontró un listado
  textual con coordenadas para Nuevo León en esta sesión).
- **Descarga:** NO realizada (requiere navegación manual del mapa/lista; no se encontró endpoint
  de datos históricos horarios en la página pública).
- **Licencia/términos:** la página incluye el aviso: *"La presente información es publicada tal
  cual es, cada uno de las y los administradores de redes es responsable de los datos aquí
  publicados"*. No se especifica una licencia formal (ej. CC-BY). Contacto para datos:
  ventanillaunica.smn@conagua.gob.mx.
- **Altura de anemómetro:** no especificada en la página (típicamente 10 m según estándar OMM,
  pero **[no verificado]** para estaciones específicas de NL).
- **Referencia (APA):**
  Servicio Meteorológico Nacional (SMN), CONAGUA. (s.f.). *Estaciones Meteorológicas Automáticas
  (EMA's)*. Recuperado el 28 de septiembre de 2026, de
  https://smn.conagua.gob.mx/es/observando-el-tiempo/estaciones-meteorologicas-automaticas-ema-s
- **Utilidad para el proyecto:** potencialmente alta si se logra identificar una EMA cercana a la
  ZMM (p. ej. aeropuerto o alguna estación sinóptica adicional a MMMY/MMAN), pero requiere acción
  humana (ver `pasos_para_hermann.md`).

### A.2 SIMA Nuevo León (Sistema Integral de Monitoreo Ambiental / SMCA del AMM)

- **URL principal:** http://aire.nl.gob.mx/ (portal público de reportes) y
  http://aire.nl.gob.mx/sima/ (portal "Respira" con inicio de sesión — la vista pública no mostró
  datos de estaciones sin autenticarse).
- **Red:** 15 estaciones fijas + 2 unidades móviles en 11 municipios del AMM (según boletín oficial
  de modernización 2026, inversión >14 millones de pesos). El informe técnico más reciente
  encontrado y **descargado** (ver abajo) documenta 15 estaciones automáticas del "SMCA del Área
  Metropolitana de Monterrey" operado por la Secretaría de Medio Ambiente de Nuevo León:

  | Estación | Clave | Municipio | Inicio operación | Coordenadas (lat, lon) | Altura sensor meteorológico* |
  |---|---|---|---|---|---|
  | Obispado | CE | Monterrey | 1992 | no extraídas en esta sesión | no extraída |
  | San Bernabé | NO | Monterrey | 1992 | no extraídas | no extraída |
  | **Preparatoria ITESM – Garza Lagüera** | **SUR** | Monterrey (Col. Las Brisas) | 2017 | **25.616944, -100.273889** (555 msnm) | **6.6 m** sobre nivel de calle |
  | Apodaca | NE2 | Apodaca | 2012 | 25.7775, -100.1882 (432 msnm) | no extraída |
  | Escobedo | N | General Escobedo | 2009 | 25.798611, -100.32722 (503 msnm) | no extraída |
  | García | NO2 | García | 2009 | no extraídas | no extraída |
  | Misión San Juan | NO3 | García | 2022 | no extraídas | no extraída |
  | Cadereyta | SE3 | Cadereyta | 2017 | 25.6008, -99.9958 (336 msnm) | no extraída |
  | Juárez | SE2 | Juárez | 2012 | 25.6460, -100.0954 (336 msnm) | no extraída |
  | **TECNL (antes "La Pastora")** | SE | Guadalupe | 1992 | 25.665277, -100.2433 (500 msnm) | no extraída |
  | San Nicolás | NE | San Nicolás de los Garza | 1992 | no extraídas | no extraída |
  | Universidad (UANL) | N2 | San Nicolás | 2017 | 25.7454, -100.2530 (472 msnm) | no extraída |
  | San Pedro | SO2 | San Pedro Garza García | 2014 | 25.6653, -100.4129 (636 msnm) | no extraída |
  | Santa Catarina | SO | Santa Catarina | 1992 | no extraídas | no extraída |
  | Pesquería | NE3 | Pesquería | 2020 | no extraídas | no extraída |

  *Altura de sensor meteorológico tomada como referencia respecto al nivel del piso de calle
  (no es la altura sobre el techo del edificio, que puede diferir). Rango observado en el
  documento para diferentes estaciones: **6.15 a 19.40 m** — es decir, son sensores en azotea, no
  a 10 m sobre terreno abierto: están dentro de la subcapa de rugosidad urbana y su velocidad no
  debe usarse directamente como condición de frontera de entrada sin corrección por el entorno
  local (edificios, árboles, canopy urbano).

  **HALLAZGO CLAVE — estación más cercana al campus con datos de viento:** la estación
  **"Preparatoria ITESM Eugenio Garza Lagüera (SUR)"** está físicamente instalada dentro de un
  plantel de preparatoria del Tecnológico de Monterrey (campus Garza Lagüera, no el Campus
  Monterrey/Rectoría Zona Sur), en Colonia Las Brisas, a **~4.1 km al sur** del Campus Monterrey
  (25.651, -100.290). Es la estación con viento medido más próxima a la zona de estudio (aparte de
  los aeropuertos MMMY/MMAN que cubre el otro agente). Mide PM10, PM2.5, O3, SO2, NO2, CO y
  parámetros meteorológicos desde 2017.

  **Rosa de viento publicada para esta estación (periodo 2021–2023, del informe INECC 2025):**
  viento dominante con componente **sureste (33% del tiempo)**, seguido de **sur (18%)**, **norte
  (17%)** y **noroeste (14%)**. El informe atribuye las componentes NO/SE a la **canalización del
  viento por la Sierra Madre Oriental y el Cerro de la Silla**. El SE es claramente dominante en
  primavera, verano y otoño; en invierno la distribución es más homogénea entre SE/NO/S/N. La
  intensidad predomina entre 5 y 20 km/h (1.4–5.6 m/s); >20 km/h casi exclusivamente del SE.
  Esto es **consistente en dirección** con la rosa ERA5/Open-Meteo calculada en este mismo informe
  (dominante E/ESE, ver sección A.4), aunque la estación urbana capta con más nitidez el eje de
  canalización NO–SE del valle, mientras ERA5 (grilla ~31 km) sólo resuelve el flujo sinóptico de
  fondo.

  ⚠️ **No confundir** la estación "TECNL (antes La Pastora)" con el Tecnológico de Monterrey: TECNL
  es el **Instituto Tecnológico de Nuevo León** (plantel público en Guadalupe, Av. Eloy Cavazos),
  una institución distinta del Tecnológico de Monterrey/ITESM.

- **Documentos descargados y procesados (texto extraído con `pypdf`):**
  - `E:\PINN\datos\viento\raw\SMCA_Monterrey_representatividad_2025.pdf` (269 pág., 6.6 MB) →
    texto en `SMCA_representatividad_2025.txt`.
    Fuente: INECC & Secretaría de Medio Ambiente del Gobierno del Estado de Nuevo León. (2025).
    *Diagnóstico sobre la Escala Espacial de Representatividad [Red de Monitoreo de la Calidad del
    Aire del Área Metropolitana de Monterrey]*.
    https://www.gob.mx/cms/uploads/attachment/file/1078076/Reporte_SMCA_Monterrey_final_100225_rev1_Dif_110526_red_4.pdf
  - `E:\PINN\datos\viento\raw\SIMA_rediseno_red_2021.pdf` (147 pág., 8.7 MB) → texto en
    `SIMA_rediseno_2021.txt`.
    Fuente: Secretaría de Medio Ambiente de Nuevo León / consultores. (2021). *Estudio para el
    rediseño de la red de monitoreo de la calidad del aire del Área Metropolitana de Monterrey*.
    http://aire.nl.gob.mx/docs/reportes/Reporte_final_SMCA_AMM_31mar2021.pdf
  - Ambos documentos son informes públicos gubernamentales (gob.mx / aire.nl.gob.mx); no incluyen
    una licencia explícita tipo Creative Commons, pero al ser producidos con fondos públicos y
    publicados abiertamente se citan bajo uso académico/de investigación estándar. **[no
    verificado]** el estatus legal exacto de reuso comercial.
- **Datos horarios crudos de la red (series de tiempo completas):** NO descargados — el portal
  público `aire.nl.gob.mx` no expone una API pública documentada en esta sesión; el subportal
  `aire.nl.gob.mx/sima/` requiere inicio de sesión para ver datos en vivo/históricos. El portal de
  datos abiertos del estado (https://datosabiertos.nl.gob.mx/, catálogo en
  https://catalogodatos.nl.gob.mx/dataset/) fue revisado pero no se encontraron ahí conjuntos de
  datos de viento/calidad del aire en la página de inicio (no se navegó el catálogo completo por
  límite de tiempo). Ver `pasos_para_hermann.md`.
- **Utilidad para el proyecto:** ALTA — es la única fuente encontrada con una estación física
  dentro de instalaciones del Tecnológico de Monterrey (aunque el plantel Garza Lagüera, no
  Campus Monterrey) y con rosa de viento publicada y consistente con el patrón de canalización
  regional. Recomendado solicitar series horarias crudas 2017–presente a la Secretaría de Medio
  Ambiente de NL para validación adicional del inlet, siempre con la salvedad de que es un sensor
  urbano de azotea (rugosidad local alta, no representa viento "libre" a 10 m en campo abierto).

### A.3 Estación meteorológica propia del Tec de Monterrey / Weather Underground

- **Búsqueda realizada:** Weather Underground (wunderground.com) para el área del Campus Monterrey
  — el mapa de estaciones personales (PWS) mostró **"No PWS"** cerca de la Colonia Tecnológico /
  Av. Eugenio Garza Sada. Solo se identificó una estación genérica "Monterrey Station (IMONTE877)"
  sin confirmar proximidad al campus.
- **Grupo de investigación en viento del Tec:** se identificó al **Dr. Oliver Probst** (físico,
  Tecnológico de Monterrey, Escuela de Ingeniería y Ciencias), líder de "The Wind Energy Group"
  (antes en `fisica.mty.itesm.mx/fisica/WEG/`, dominio que **ya no resuelve** — DNS falla,
  probablemente sitio dado de baja). Sus publicaciones relevantes:
  - Toledo, V., Probst, O., et al. (2015). *A surface wind speed map for Mexico based on NARR and
    observational data*. Meteorological Applications, 22(4). DOI/URL:
    https://rmets.onlinelibrary.wiley.com/doi/full/10.1002/met.1500 — mapa de velocidad de viento
    superficial para México construido con NARR (reanálisis, ~32 km, similar limitación de
    resolución que ERA5) + estaciones ASOS/observacionales, 1989–2009. Útil como referencia
    cruzada regional (no específico de Monterrey/campus). **[no verificado]** si reporta un valor
    puntual para Monterrey extraíble sin acceso al artículo completo (de pago).
  - Romo Perea, A., Amezcua, J., & Probst, O. *Validation of three new measure-correlate-predict
    models for the long-term prospection of the wind resource*. Journal of Renewable and
    Sustainable Energy, 3(2), 023105.
  - No se encontró evidencia de una **estación meteorológica propia del Campus Monterrey con datos
    públicos**, ni de un dataset abierto del grupo de energía eólica. **[no verificado]** —
    recomendable contactar directamente al Dr. Probst o al departamento de Física del Tec (ver
    `pasos_para_hermann.md`).

### A.4 ERA5 / ERA5-Land vía Open-Meteo Historical Weather API — DESCARGADO

- **URL API:** https://archive-api.open-meteo.com/v1/archive (sin API key, licencia **CC BY 4.0**).
- **Punto:** 25.651 N, -100.290 O (Campus Monterrey).
- **Periodo descargado:** 2014-01-01 a 2025-09-27 (10 años y 9 meses; 102,912 registros horarios,
  sin datos faltantes) en dos llamadas (2014–2023 y 2024–2025) por límites de la API, combinadas y
  de-duplicadas.
- **Variables:** `wind_speed_10m`, `wind_direction_10m`, `wind_speed_100m`,
  `wind_direction_100m`, `temperature_2m` (unidad de viento: m/s, hora UTC, modelo `era5`).
- **Archivos generados:**
  - Crudos: `E:\PINN\datos\viento\raw\openmeteo_era5_hourly_2014_2023.json`,
    `openmeteo_era5_hourly_2024_2025.json`, combinado en
    `openmeteo_era5_hourly_2014_2025.csv` (102,912 filas).
  - Procesado: `E:\PINN\datos\viento\era5_openmeteo_rose16.csv` (rosa de 16 sectores, convención
    meteorológica "de dónde viene", sectores centrados en 0°, 22.5°, ...).
  - Figura: `E:\PINN\datos\viento\era5_openmeteo_rose16.png` (rosa apilada por bin de velocidad).
  - Tabla de cortante: `E:\PINN\datos\viento\era5_shear_ratio_by_sector.csv` (razón
    v100/v10, exponente α de ley de potencia por sector).
  - Medias mensuales: `E:\PINN\datos\viento\raw\era5_monthly_means.csv`.

- **Resultados clave de la rosa 16 sectores (10 m, 2014–2025, 102,912 h):**

  | Sector | % frecuencia | Vel. media (m/s) |
  |---|---|---|
  | ESE | **28.2%** | 2.76 |
  | E | **19.1%** | 2.13 |
  | ENE | 8.1% | 1.68 |
  | SE | 7.5% | 2.25 |
  | NE | 5.4% | 1.57 |
  | NNE | 4.0% | 1.73 |
  | N | 3.9% | 1.88 |
  | NNW | 3.3% | 2.07 |
  | W | 3.5% | 1.18 |
  | WSW | 3.2% | 1.04 |
  | NW | 3.0% | 1.92 |
  | WNW | 2.5% | 1.64 |
  | SSE | 2.5% | 1.79 |
  | SW | 2.1% | 0.76 |
  | S | 1.9% | 1.40 |
  | SSW | 1.7% | 1.00 |

  E+ESE+SE concentran **~55%** de las horas — viento dominante del **este/estesureste**,
  consistente con el eje de canalización NO–SE reportado por la estación SIMA "Preparatoria
  ITESM Garza Lagüera" (que da SE dominante 33%, aunque con más peso también en N/NO/S, reflejo de
  la geometría local del valle que ERA5 no resuelve). Fracción de calma (viento <0.5 m/s): **3.2%**.

- **Cortante 10 m → 100 m (proxy regional, ERA5 no resuelve el valle):** exponente de ley de
  potencia mediano global (α, todas las horas con v10 > 0.5 m/s) = **0.161**. Por sector, α varía
  de ~0.02 (WSW, capa poco estable/mezclada) a ~0.25 (SSW), con el rango dominante E–SE en
  α ≈ 0.12–0.21. Interpretar con cautela: ERA5 tiene ~31 km de resolución horizontal y una capa
  límite parametrizada; no resuelve la topografía de la Sierra Madre Oriental, el Cerro de la
  Silla, ni la rugosidad urbana real del AMM. Sirve solo como referencia de la cortante *regional
  de fondo* (útil para el límite superior/entrada de dominio grande, no para el perfil urbano
  cercano al piso).
- **Referencia (APA):**
  Zippenfenig, P. (2023). *Open-Meteo.com Weather API* [Software]. Zenodo.
  https://doi.org/10.5281/zenodo.7970649. Datos ERA5: Copernicus Climate Change Service (C3S)
  Climate Data Store; Hersbach, H., et al. (2020). *The ERA5 global reanalysis*. Quarterly
  Journal of the Royal Meteorological Society, 146(730), 1999–2049.
  https://doi.org/10.1002/qj.3803. Licencia de los datos servidos por Open-Meteo: **CC BY 4.0**
  (atribución requerida).
- **Comparación con la rosa NOAA ISD (`E:\PINN\v2\climate\windrose_16.csv`):** al momento de
  redactar este informe (28 sep 2026), el directorio `E:\PINN\v2\climate\` seguía **vacío** — el
  agente NOAA ISD aún no había producido su salida. No fue posible hacer la comparación
  cuantitativa solicitada. **Acción recomendada:** cuando `windrose_16.csv` esté disponible,
  comparar directamente contra `era5_openmeteo_rose16.csv` (mismos sectores/convención) — se
  espera que ISD (observaciones de superficie en MMMY/MMAN, aeropuertos con mejor exposición que
  estaciones urbanas) muestre un patrón E/ESE similar o más marcado que ERA5, dado que ERA5 tiende
  a suavizar canalización de valle.

### A.5 NASA POWER — verificación cruzada rápida

- **URL:** https://power.larc.nasa.gov/api/temporal/hourly/point (sin API key).
- Se descargó una muestra de un año (2023) de `WS10M`/`WD10M`/`WS50M`/`WD50M` en el mismo punto:
  media anual WS10M 2023 ≈ **3.29 m/s** (archivo:
  `E:\PINN\datos\viento\raw\nasapower_2023_sample.json`), frente a ERA5/Open-Meteo (mismo año,
  2023) que da un orden de magnitud similar pero algo menor en 10 m (NASA POWER usa MERRA-2, que
  tiende a reportar vientos algo más altos que ERA5 en muchos sitios; ambos son reanálisis de
  malla gruesa, ~50 km MERRA-2 vs ~31 km ERA5). Se usó solo como chequeo de orden de magnitud, no
  se generó rosa ni se procesó más a fondo (fuera de alcance del tiempo disponible). Licencia NASA
  POWER: datos de dominio público / uso libre con atribución.
- **Referencia:** NASA Langley Research Center (LaRC) POWER Project. (s.f.). *NASA POWER Data
  Access Viewer*. https://power.larc.nasa.gov/

---

## B. Inlet / capa límite atmosférica (ABL)

### B.1 CFE — Manual de Diseño de Obras Civiles, Diseño por Viento (2020)

- **Qué es:** manual normativo mexicano de referencia para diseño estructural por viento
  (Comisión Federal de Electricidad / Instituto de Investigaciones Eléctricas), ampliamente citado
  en ingeniería civil en México. Contiene: categorías de terreno (rugosidad), coeficientes de la
  ley de potencia (exponente α) y ley logarítmica, alturas de gradiente (δ), velocidades regionales
  básicas por periodo de retorno y zona del país, y factores de topografía.
- **Valores encontrados (tabla de categorías de terreno — α, δ, c):** *(fuente: agregación de
  motores de búsqueda sobre copias del manual en Scribd/Academia/Studylib; **[no verificado]**
  directamente contra el PDF oficial del MDOC 2020 — estos valores coinciden con ediciones previas
  del manual CFE, por lo que deben confirmarse contra la edición 2020 exacta):*

  | Categoría de terreno | α | δ (m) | c |
  |---|---|---|---|
  | 1 (abierto, costero, sin obstrucciones) | 0.099 | 245 | 1.137 |
  | 2 (terreno plano u ondulado con pocas obstrucciones) | 0.128 | 315 | 1.000 |
  | 3 (terreno cubierto por numerosas obstrucciones — suburbano/urbano) | 0.156 | 390 | 0.881 |
  | 4 (grandes ciudades, centros urbanos con edificios altos) | 0.170 | 455 | 0.815 |

  La categoría 3 (α≈0.156) es la más probable para el entorno del Campus Monterrey (zona
  suburbana/urbana de baja-media densidad con edificios de mediana altura); el propio campus y
  Distrito Tec podrían acercarse a categoría 4 en las zonas más densas. Para contexto, el
  exponente α "de fondo" estimado con ERA5 en este informe (~0.12–0.21 dominante E–SE) cae en un
  rango compatible con categorías 2–4, aunque no son comparables directamente (ERA5 es una
  cortante de gran escala 10–100 m sobre grilla de 31 km, no la ley de potencia de capa límite
  urbana estándar del CFE definida para <500 m).
- **Velocidades regionales para Monterrey:** NO se pudo extraer un valor puntual verificado del
  VR (velocidad regional, periodo de retorno) para el municipio de Monterrey/Nuevo León en esta
  sesión de búsqueda — requiere el PDF completo del manual y su mapa de isotacas/regionalización.
  **[no verificado]**.
- **Cómo obtenerlo:** el MDOC-Viento 2020 se distribuye por el LAPEM/CFE
  (https://lapem.cfe.gob.mx/normas/) y existen copias en repositorios académicos (Scribd,
  Academia.edu, Studylib) — ver `pasos_para_hermann.md` para instrucciones de obtención de una
  copia verificada.
- **Referencia (APA):**
  Comisión Federal de Electricidad (CFE). (2020). *Manual de Diseño de Obras Civiles: Diseño por
  Viento*. Instituto de Investigaciones Eléctricas / CFE, México.
- **Documento complementario (CENAPRED):** se localizó (no se pudo descargar por error DNS en
  esta sesión) un informe del CENAPRED: *"Velocidades de viento para evaluación de vulnerabilidad
  de la vivienda"* (2020), URL:
  https://www1.cenapred.unam.mx/DIR_INVESTIGACION/2020/1er_Trimestre/FRACCION_XLI/RH/200305_RE-RH_lnforme_VientoVF_orig.pdf
  — potencialmente contiene mapas de velocidad regional por municipio; **[no verificado]**,
  pendiente de reintentar la descarga.

### B.2 Radiosondeos — estación 76394 (Monterrey)

- **Estación OMM 76394:** confirmada como estación de radiosondeo de Monterrey (aeropuerto),
  coordenadas aproximadas 25.52 N, -100.14 O (según BADC/Met Office archive), elevación ~448 m.
  Archivo histórico: University of Wyoming, Department of Atmospheric Science —
  https://weather.uwyo.edu/upperair/sounding.shtml (interfaz de consulta por fecha/estación).
- **Estado de disponibilidad:** al intentar consultar directamente el sondeo (ej. enero 2023) el
  servidor devolvió error 404 con el formato de URL probado; **[no verificado]** si la estación
  76394 sigue activa/reporta actualmente o si solo tiene datos históricos limitados — requiere
  reintento manual desde la interfaz web (formulario), no vía URL directa construida por este
  agente.
- **Utilidad:** si hay datos, un sondeo da perfil vertical de viento (velocidad/dirección vs.
  altura) mucho más allá de 100 m, útil para validar el perfil de entrada en altura y la capa de
  mezcla — pero los sondeos son de 1-2 veces al día (00Z/12Z) y en el aeropuerto, no en el valle
  urbano cerca del campus.
- **Referencia (APA):**
  University of Wyoming, Department of Atmospheric Science. (s.f.). *Atmospheric Soundings —
  Station 76394 (Monterrey, Mexico)*. https://weather.uwyo.edu/upperair/sounding.shtml

### B.3 Canalización de viento por el valle (Sierra Madre Oriental / Cerro de la Silla)

- **Evidencia encontrada:** el informe INECC 2025 (sección A.2 arriba) documenta explícitamente,
  para la estación SIMA "Preparatoria ITESM Garza Lagüera", que las componentes de viento
  **noroeste y sureste dominan** y son atribuidas a "la canalización del viento provocado por la
  presencia de la Sierra Madre Oriental y el Cerro de la Silla" — el campus y esa estación se
  ubican en el corredor topográfico entre el Cerro de la Silla (este) y el sistema Cumbres de
  Monterrey/Sierra Madre Oriental (oeste), con orientación NO–SE del valle. Esto es la evidencia
  documental más directa y específica de la zona encontrada en esta investigación.
- **Literatura académica específica sobre canalización/corredores de viento en el AMM:** no se
  encontraron artículos académicos dedicados (revistas indexadas) sobre el tema en esta sesión de
  búsqueda; solo el informe gubernamental citado arriba. **[no verificado]** que no exista tal
  literatura — es posible que exista en tesis de posgrado de la UANL (Facultad de Ciencias de la
  Tierra, Ciencias Atmosféricas) no indexadas en buscadores generales.

---

## C. Túnel de viento / laboratorio de capa límite en México

- No se encontró evidencia de un túnel de viento de capa límite atmosférica en el Tecnológico de
  Monterrey, Campus Monterrey. **[no verificado, con búsqueda razonable]**.
- Se identificó el **túnel de viento de capa límite de la UNAM** (Instituto de Ingeniería / otro
  instituto), citado en: *"Characteristics and calibration of the mexican boundary layer wind
  tunnel at UNAM"*, Revista Mexicana de Ingeniería/Scielo:
  https://www.scielo.org.mx/scielo.php?pid=S1405-77432022000100107&script=sci_arttext — es el
  único BLWT mexicano documentado encontrado; útil como referencia metodológica nacional (no
  específico de Monterrey) si se buscara validación experimental futura.

---

## Resumen de archivos generados en esta carpeta

```
E:\PINN\datos\viento\
├── fuentes_viento.md              (este documento)
├── estudios_previos.md
├── pasos_para_hermann.md
├── era5_openmeteo_rose16.csv
├── era5_openmeteo_rose16.png
├── era5_shear_ratio_by_sector.csv
└── raw\
    ├── openmeteo_era5_hourly_2014_2023.json
    ├── openmeteo_era5_hourly_2024_2025.json
    ├── openmeteo_era5_hourly_2014_2025.csv
    ├── era5_monthly_means.csv
    ├── nasapower_2023_sample.json
    ├── SMCA_Monterrey_representatividad_2025.pdf (+ .txt extraído)
    ├── SIMA_rediseno_red_2021.pdf (+ .txt extraído)
    ├── smn_ema_page.html
    └── fetch_openmeteo.py, fetch_openmeteo_recent.py, process_openmeteo.py,
        plot_windrose.py, fetch_nasapower.py, extract_pdf.py, find_stations.py
```
