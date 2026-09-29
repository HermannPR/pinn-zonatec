# Lista de verificación de campo — alturas de edificios, Zona Tec

## ADENDA (post-cruce con el dominio final del equipo de geometría)

El equipo de geometría publicó su dominio final en `E:\PINN\v2\geometry\out\buildings.csv`
(445 edificios, roles `zoi`/`ring`) y `heights_to_verify.csv` (144 marcados sin dato real,
usando el default de 2 pisos/6 m). Se cruzó por `osm_id` (sin modificar esos archivos):

- **100% de los 445 edificios finales coinciden por `osm_id`** con esta investigación.
- **142 de los 144 (98.6%) marcados como "sin dato" por el equipo de geometría SÍ tienen**
  un dato real en `alturas_consolidadas.csv` de este proyecto (sobre todo de Google Open
  Buildings 2.5D Temporal) — se recomienda hacer el join y sustituir el default de 6 m.
- **HALLAZGO CRÍTICO — clúster sospechoso de 78-80 m dentro del dominio `zoi` real**: los
  edificios `osm_id 1539504900` ("CEDES"), `1539504905` y `1539504906` (todos
  `building=yes`, **sin `building:levels`**, por lo que mi regla de QC automática NO los
  marcó como outlier) reciben de Google 2.5D **78.4 m, 53.8 m y 80.4 m** respectivamente —
  a solo ~100-200 m del centro del dominio, y a ~150 m del Fiesta Inn (92 m estimado) y de
  la torre de apartamentos sin nombre `1136003274` (90.9 m estimado). **Es muy probable que
  estos 3 valores sean el mismo artefacto de contaminación por paralaje/sombra** descrito en
  `fuentes_alturas.md` (sección 3a) — un edificio realmente alto vecino "contaminando" los
  píxeles de construcciones bajas cercanas. **Si se usa el valor de Google 2.5D sin
  verificar, se introduciría una torre de ~80 m ficticia justo en medio del campus, lo cual
  distorsionaría gravemente la estela de viento simulada.** Verificar en campo o foto ANTES
  de usar estos 3 valores; mientras tanto, se recomienda usar el default conservador (2-3
  pisos) del equipo de geometría para estos 3 IDs específicos, no el valor de Google 2.5D.
- El resto del clúster de discrepancia alta ya identificado (BiblioTEC, Rectoría, Aulas,
  Residencias III, Wellness Center, Centro de Biotecnología FEMSA — ver Prioridad 1 más
  abajo) SÍ tiene `building:levels` de OSM con el que contrastar, y sus valores de Google
  2.5D son 1.4x-2.2x el valor de niveles×3m — grandes pero no tan extremos como el clúster
  de 78-80 m; siguen mereciendo verificación pero con menor urgencia relativa.


Prioriza los edificios donde: (a) la altura es grande (domina la estela de viento), (b) hay
discrepancia > 20% entre fuentes, o (c) el dato disponible es de baja confianza (torres
privadas sin coordenada exacta). Coordenadas en WGS84 (lat, lon). Distancia medida al centro
aproximado del campus (25.6513, -100.2895).

**Cómo verificar**: contar pisos en persona o por fotos (Mapillary, Google Street View /
Google Earth solo como referencia visual — no extraer/descargar datos de Google por sus
términos de servicio), o consultar Infraestructura del Tec para planos oficiales.

## Prioridad 1 — Edificios altos con fuerte discrepancia entre fuentes (afectan la estela de viento)

| osm_id | Nombre | lat, lon | OSM levels×3m | Google 2.5D | Oficial | Qué revisar |
|---|---|---|---|---|---|---|
| 546653067 | Fiesta Inn (hotel, Av. Eugenio Garza Sada) | 25.65489, -100.29274 | 54.0 m (18 niveles) | 92.2 m | — | Discrepancia de 71%. Contar pisos reales del hotel desde la calle o buscar ficha técnica del hotel (Fiesta Inn/Grupo Posadas). Es el edificio más alto detectado en el anillo cercano al campus: si es real, domina la estela a barlovento/sotavento del extremo norte del campus. |
| 1543350343 | CETEC | 25.65054, -100.29097 | 24.0 m (8 niveles, OSM) | 46.3 m | **43.0 m / 11 niveles (Conecta Tec)** | Ya resuelto con fuente oficial (usar 43 m). Se deja aquí solo como recordatorio de que OSM está muy desactualizado/incorrecto (8 vs 11 niveles) — candidato a corregir directamente en OSM. |
| 1543350348 | BiblioTEC | 25.65035, -100.28982 | 18.0 m (6 niveles) | 39.0 m | — | Discrepancia grande (117%). Es la torre de biblioteca del campus, muy visible — fácil de verificar in situ o por foto. Prioridad alta por ubicación central en el campus. |
| 1543350347 | (sin nombre, junto a BiblioTEC) | 25.65033, -100.28986 aprox. | 21.0 m (7 niveles) | 38.8 m | — | Mismo clúster que BiblioTEC; verificar juntos. |
| 1543350346 | (sin nombre, junto a BiblioTEC) | 25.65022, -100.29002 aprox. | 21.0 m (7 niveles) | 38.4 m | — | Ídem. |
| 1543350339 | (sin nombre, campus) | ~25.6497, -100.2887 aprox. | 24.0 m (8 niveles) | 35.7 m | — | Verificar conteo de niveles. |
| 1539506605 | Residencias III | 25.65356, -100.29035 | 24.0 m (8 niveles) | 31.5 m | — | Torre de dormitorios; fácil acceso visual desde el campus. |
| 1544080718 | Rectoría del Tecnológico de Monterrey | 25.65143, -100.29086 | 12.0 m (4 niveles) | 21.2 m | — | Edificio emblemático y muy fotografiado — debería ser fácil de verificar con una sola foto o visita. |

## Prioridad 2 — Edificios altos sin discrepancia detectada pero SIN nombre en OSM (posible edificio importante no identificado, o posible artefacto de Google 2.5D)

| osm_id | lat, lon | Google 2.5D | Qué revisar |
|---|---|---|---|
| 1136003274 (`building=apartments`) | 25.64815, -100.29090 | 90.9 m | Sin dato de OSM para contrastar (sin `building:levels`). A ~380 m al sur del campus. Si es real, sería la segunda torre más alta del entorno inmediato — **prioridad alta** para verificar en persona o por foto; en Google 2.5D no se detectó como outlier porque no hay `building:levels` con qué compararlo, pero eso no garantiza que el valor sea correcto (recordar el caso de la "casa de 87 m", sección 3a de `fuentes_alturas.md`). |
| 1539504906 (`building=yes`) | 25.65364, -100.29254 | 80.4 m | Junto a CEDES (ver abajo). Verificar si en realidad es una sola construcción o el pixel está mezclando dos edificios adyacentes (Fiesta Inn está a ~150 m). |
| 1539504900 "CEDES" | 25.65361, -100.29253 | 78.4 m | Nombre presente en OSM pero sin `building:levels` para contrastar. Confirmar qué es "CEDES" físicamente (¿centro estudiantil/deportivo de baja altura, o realmente una torre?) — es el caso más urgente de re-verificar porque el nombre sugiere baja altura pero el valor satelital sugiere lo contrario. |
| 507363669 "Banorte" | 25.65231, -100.27750 | 72.7 m | A 1.2 km del campus (fuera del anillo de 1-2 manzanas, posiblemente fuera del dominio CFD final) — de baja prioridad salvo que el polígono final de Zona Tec lo incluya. |

## Prioridad 3 — Torres privadas cercanas sin coordenadas exactas ni osm_id (verificar ubicación primero)

| Nombre | Pisos (fuente) | Dirección aproximada | Qué revisar |
|---|---|---|---|
| Torre Paragon | 10 niveles (paragonmty.mx) | ~1 cuadra de Av. Eugenio Garza Sada, Distrito Tec, ~700 m del campus | Geocodificar la dirección exacta; confirmar si cae dentro del anillo de 1-2 manzanas de Zona Tec (P17-B) o solo dentro del polígono amplio de Distrito Tec. Buscar si ya existe en el `buildings.csv` del equipo de geometría (probablemente SÍ, ya que 10 niveles la harían visible en imagen satelital reciente); si existe, cruzar por proximidad geográfica en vez de por nombre. |
| Lítica Torre 1 | 28 niveles (litica.com.mx) | Av. Revolución 2703-2, Col. Ladrillera, Distrito Tec | **Verificar primero si ya existe físicamente**: las fuentes indican entrega prevista para fines de 2026 (puede que aún esté en construcción y no aparezca en imagen satelital ni en OSM). Si existe, sería posiblemente el edificio más alto de todo Distrito Tec dentro del anillo cercano — prioridad máxima de confirmación. |
| Lítica Torre 2 | 26 niveles (monterreyskyline.com) | Misma zona que Torre 1 | Igual que Torre 1: confirmar existencia física y etapa de construcción antes de incluir en la geometría LOD1 (o modelarla como "variante con torre proyectada", que es justamente la opción B de P17 en `grill-me.txt`). |

## Prioridad 4 — Cobertura LiDAR de INEGI (verificación puntual, no requiere ir a campo)

- Abrir https://www.inegi.org.mx/app/geo2/elevacionesmex/ en un navegador con JavaScript
  (no se pudo automatizar), seleccionar **Nuevo León → escala 1:10,000 → tipo Superficie →
  fuente LiDAR**, y buscar si existe un tile que cubra la carta **G14C26 "Monterrey"** (o el
  punto 25.651, -100.290). Esta investigación solo pudo confirmar públicamente un tile LiDAR
  de Nuevo León (clave F14A36d3, municipio de Mier y Noriega, ~200 km de Monterrey) — no se
  encontró evidencia de que exista cobertura LiDAR de alta resolución para el área urbana de
  Monterrey. Si una persona confirma que SÍ existe un tile para G14C26, sería la mejor fuente
  posible (mejor que Google 2.5D) y debería descargarse y reprocesarse como nDSM.

## Nota general sobre confiabilidad de Google Open Buildings 2.5D Temporal

Esta fuente cubre 96.8% de los edificios de la zona y en el único caso con dato oficial
(CETEC) tuvo solo 7.6% de error — pero también tiene errores groseros ocasionales (~1.5%
detectados automáticamente, posiblemente más sin detectar), como una "casa" de 2 pisos
(`osm_id 870573538`, Calle Alejandría, 25.65635, -100.29474) a la que le estimó 87 m de
altura. La causa más probable es contaminación del pixel por un edificio alto vecino
(paralaje/sombra en la imagen de satélite). **Cualquier edificio de esta lista con altura
Google 2.5D > 25 m y sin dato de contraste (OSM levels, oficial) debe tratarse como
sospechoso hasta verificarse.**
