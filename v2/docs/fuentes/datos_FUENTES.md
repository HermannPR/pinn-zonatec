# FUENTES — PINN Zona Tec (índice maestro)

Qué datos externos usa el proyecto, de dónde salen, con qué licencia y para qué sirven. El detalle de cada fuente, las fechas de acceso y lo que se probó y no funcionó está en:
- Alturas de edificios: `datos/alturas/fuentes_alturas.md` y `lista_verificacion_campo.md`
- Viento y capa límite: `datos/viento/fuentes_viento.md`, `estudios_previos.md` y `pasos_para_hermann.md`
- Clima NOAA: `v2/climate/README.md`
- AIJ: `v2/cfd/aij/data/raw/SOURCE.md` (con checksums MD5)

Todas las fuentes se consultaron el 28-sep-2026. **No** se extrajo contenido de Google Maps, Google Earth ni Photorealistic 3D Tiles, porque sus términos lo prohíben; solo se sugieren como verificación visual humana.

## 1. Geometría y alturas
| Fuente | URL | Licencia | Uso en el proyecto | Estado |
|---|---|---|---|---|
| OpenStreetMap (huellas, `height`, `building:levels`) | https://www.openstreetmap.org (Overpass API) | ODbL 1.0; atribución «© OpenStreetMap contributors» | Huellas LOD1 de la zona de interés y del anillo; pisos | Usado (caché en `v2/data/raw/osm/`) |
| Google Open Buildings 2.5D Temporal (2023) | https://sites.research.google/gr/open-buildings/temporal/ | CC BY 4.0 / ODbL (doble) | Alturas satelitales (96.8 % de cobertura); control e imputación | Descargado por ventanas (sin cuenta de Earth Engine) |
| Overture Maps, tema buildings | https://overturemaps.org/ | ODbL / CDLA-Permissive-2.0 según la fuente | Revisado: aquí las alturas son 100 % OSM (no aporta nada independiente) | Revisado, no se usa |
| Microsoft Global ML Building Footprints | https://github.com/microsoft/GlobalMLBuildingFootprints | ODbL | Sin alturas para México | Revisado, no se usa |
| INEGI, MDE y LiDAR | https://www.inegi.org.mx/programas/mde/ | Términos de libre uso INEGI | Sin cobertura LiDAR urbana confirmada para Monterrey | Revisado, no se usa |
| Tec de Monterrey, CONECTA (CETEC 43 m) | https://conecta.tec.mx/es/noticias/monterrey/arte-y-cultura/cetec-legado-del-arquitecto-oscar-bulnes-para-monterrey | cita de noticia institucional | Altura oficial de CETEC | Usado |
| Programa Parcial Distrito Tec | https://visorproaxis.com/docs/PPDUMtyDistritoTec.pdf ; https://www.monterrey.gob.mx/pdf/gacetas/2021/GacetaEnero2021EspecialDistritoTec.pdf | documento público municipal | Contexto del polígono y de la densificación (variantes P4) | Consultado |

## 2. Viento y clima
| Fuente | URL | Licencia | Uso | Estado |
|---|---|---|---|---|
| NOAA NCEI ISD / Global Hourly, MMMY 76394399999 (principal) y MMAN 76394099999 | https://www.ncei.noaa.gov/data/global-hourly/access/ | Datos del gobierno de EE. UU., uso libre (WMO Res. 40) | Rosa de vientos de 16 sectores, Weibull, U10 de referencia (P14-A) | Descargado 2010-2024 |
| ERA5 vía Open-Meteo Historical API | https://archive-api.open-meteo.com/v1/archive | CC BY 4.0 (Open-Meteo; ERA5 de Copernicus) | Contraste de la rosa y cizalla 10/100 m por sector | Descargado 2014-2025 |
| NASA POWER | https://power.larc.nasa.gov/ | uso libre de NASA | Comprobación del orden de magnitud | Consultado |
| SIMA Nuevo León / reportes INECC-SMCA 2021 y 2025 | http://aire.nl.gob.mx/ ; https://www.gob.mx/cms/uploads/attachment/file/1078076/Reporte_SMCA_Monterrey_final_100225_rev1_Dif_110526_red_4.pdf | documento público | Rosa urbana (estación en Prepa Tec Eugenio Garza Lagüera: SE dominante) y canalización del valle | PDF descargado; las series horarias requieren solicitud |
| SMN/CONAGUA, EMAs | https://smn.conagua.gob.mx/es/observando-el-tiempo/estaciones-meteorologicas-automaticas-ema-s | datos públicos | Alternativa a MMMY | Pendiente de descarga manual |
| Radiosondeos 76394 (U. of Wyoming) | https://weather.uwyo.edu/upperair/sounding.shtml | uso académico | Perfil vertical regional (opcional) | Pendiente de consulta manual |
| CFE, Manual de Diseño de Obras Civiles, Diseño por Viento (2020) | https://lapem.cfe.gob.mx/normas/ [edición a verificar] | norma, cita | Ley de potencia (α, δ) solo para comparar (T1) | Valores de tabla [no verificados] |

## 3. Validación CFD
| Fuente | URL | Licencia | Uso | Estado |
|---|---|---|---|---|
| AIJ UWE Benchmark, Caso A (edificio 1:1:2), Meng y Hibi (1998) | https://doi.org/10.5281/zenodo.15050147 | CC BY 4.0 | Validación de la cadena OpenFOAM (P22-C): 186 puntos con U, V, W y k | Descargado, MD5 verificado |
| Tominaga et al. (2004), JAABE (acceso abierto) | ver `v2/cfd/aij/README.md` | acceso abierto | Longitudes de readherencia medidas (X_R/b = 0.52, X_F/b = 1.42) | Usado |

## 4. Pendiente de verificar antes de citar en el informe
- Constantes de Kanda et al. (2013): tomadas de fuentes secundarias.
- Valores W y D de VDI 3783 Blatt 9: se usan D = 0.25 y W = 0.05·U_ref, a confirmar con la norma.
- Altura del anemómetro de MMMY (se supone 10 m, estándar OMM).
- Tabla α/δ de la CFE 2020.
