# Climatología de viento -- PINN Zona Tec

Insumo climático para el confort peatonal por viento en el Tecnológico de
Monterrey (Monterrey, N.L.). Todo lo generado aquí alimenta el módulo de
confort (Lawson LDDC / NEN 8100, P10=C) una vez que éste calcule el factor
de amplificación K(theta) = U_local(theta) / U10(theta) a partir del CFD.

## Estaciones

Verificadas contra `isd-history.csv` de NOAA (descargado 2026-09-28,
guardado en `E:\PINN\v2\data\raw\climate\isd-history.csv`):

| Rol | ICAO | Nombre | USAF-WBAN | id combinado | lat | lon | elev [m] |
|---|---|---|---|---|---|---|---|
| **Primaria** | MMMY | Gen. Mariano Escobedo Intl / Monterrey Intl | 763943-99999 | `76394399999` | 25.7785 | -100.1069 | 389.5 |
| Secundaria | MMAN | Del Norte Intl | 763940-99999 | `76394099999` | 25.8660 | -100.2370 | 449.9 |

MMMY se usa como estación de referencia porque (a) es el aeropuerto
internacional OMM/OACI de la ciudad, consistente con la convención P14=A
(U_ref = U10 = viento medio a 10 m en terreno abierto/aeropuerto), y (b) su
registro METAR 2010-2024 está prácticamente completo (ver abajo). MMAN se
descargó como estación secundaria de contraste (mismo valle, exposición
distinta) pero su cobertura horaria es estructuralmente incompleta -- ver
"Limitaciones".

No se encontraron datos SMN/CONAGUA de EMA abiertos y descargables
directamente para esta tarea (requieren portal/registro); no se usaron.

Fuente: NOAA NCEI ISD / Global Hourly,
`https://www.ncei.noaa.gov/data/global-hourly/access/<año>/<id>.csv`.
Datos crudos en `E:\PINN\v2\data\raw\climate\MMMY_76394399999\<año>.csv` y
`...\MMAN_76394099999\<año>.csv`, años 2010-2025 (2025 parcial, hasta el
2025-08-24, excluido de la climatología principal).

## Años usados y completitud

Climatología principal: **15 años completos, 2010-2024**, estación MMMY.

- Completitud media anual (horas QC-válidas / horas esperadas): **97.4 %**
  (rango 93.3 % en 2021 a 99.3 % en 2015; tabla completa en
  `completeness_mmmy.csv`).
- MMAN (secundaria): completitud media ~74 %, pero **no aleatoria**: faltan
  sistemáticamente las horas ~00-05 hora local (aprox. 06-11 UTC), es decir
  la estación no opera de noche. No se usa para ninguna estadística nocturna
  ni como fuente primaria; solo como comparación de direcciones dominantes
  diurnas (`completeness_mman.csv`).

## Control de calidad (QC) aplicado

Campo `WND` del ISD: `dirección,calidad_dir,tipo,velocidad,calidad_vel`.
- Se conservan solo registros con código de calidad en `{0,1,4,5,9}`
  (se descartan `2,3,6,7` = sospechoso/erróneo). Para MMMY el rechazo es
  marginal: <60 horas de 15 años por mala calidad de velocidad, ~15 horas
  por dirección faltante/errónea.
- Calma: `tipo='C'` (dirección indefinida, velocidad forzada a 0).
- Dirección variable: `tipo='V'` (prácticamente inexistente en MMMY:
  1 hora en 15 años) -- se excluye del reparto direccional, se cuenta
  aparte (`variable_fraction`).
- Un registro por hora: se trunca el timestamp a la hora (las observaciones
  caen siempre entre :40 y :56), y si coexisten METAR (FM-15) y SPECI
  (FM-16) en la misma hora se conserva el FM-15.
- Altura del anemómetro: **asumida 10 m AGL** (estándar OMM/OACI para
  aeropuertos) -- **no verificada** en los metadatos ISD de estas dos
  estaciones específicamente (bandera de incertidumbre).
- Resolución METAR: dirección codificada a 10°, velocidad en nudos enteros
  convertida a m/s. Esto genera un alias 10°->22.5° entre el grano del dato
  y los 16 sectores climáticos (centrados en 0, 22.5°, ..., 337.5°, ancho
  22.5°). Se corrige por **redistribución proporcional determinista**: cada
  observación a 10° se trata como una variable uniforme en [d-5°, d+5°) y su
  masa se reparte entre los (máx. 2-3) sectores de 22.5° que esa franja
  cruza, ponderando por la longitud de traslape. Ver docstring de
  `windclimate.sector_weights`.

## Resultados (MMMY, 2010-2024, 128 072 horas QC-válidas)

- **Fracción de calma: 17.3 %** (fracción de dirección variable: 0.0008 %,
  despreciable).
- **Sectores prevalecientes** (frecuencia sobre el total de horas, incluidas
  calmas):

  | Sector | Frecuencia | U10 media [m/s] |
  |---|---|---|
  | 112.5° (ESE) | 21.6 % | 4.08 |
  | 90.0° (E) | 14.1 % | 3.74 |
  | 135.0° (SE) | 9.4 % | 3.91 |

  Segundo máximo secundario, más débil, en el cuadrante NW-N (292.5°-337.5°,
  4.5-6.5 % cada uno, U10 media 3.4-4.5 m/s), asociado a entradas de "nortes"
  (frentes fríos). El resto de sectores (S, SW, N) son marginales (<2.5 %
  cada uno). Este patrón es consistente con el canalizamiento orográfico del
  valle de Monterrey por el corte de la Sierra Madre Oriental hacia el
  ESE/E -- efecto orográfico que entra aquí solo de forma implícita, vía la
  rosa medida (P19=D), sin modelarse por separado.
- **U10 media (horas no-calma, todas direcciones): 3.73 m/s.**
- **P(U10 > 5 m/s)**: empírica 18.56 %, Weibull agregada 18.38 %,
  empírica-primero (`method='auto'`, ver I3 abajo) 18.56 %.
- **P(U10 > 10 m/s)**: 0.52 % (666 h en 15 años), estimador empírico directo.
- **P(U10 > 15 m/s)** ("peligro"): **0.0055 % (7 h en 15 años)**, estimador
  empírico directo -- corregido tras la revisión independiente F1 (I3): una
  versión anterior de este README decía "0.010 %", que era un artefacto de
  redondeo al mostrar la fracción cruda (5.47e-5) con 4 decimales, no el
  valor real. La Weibull agregada da 0.0013 % (~18x menos): **la Weibull
  subestima la cola extrema** y no debe usarse para el criterio de "peligro".
  Ver "Excedencia empírica-primero (I3)" abajo.

### Excedencia empírica-primero (I3)

`windclimate.annual_exceedance(..., sector_speeds=windrose.sector_speeds,
method='auto')` usa, por sector, el conteo **empírico ponderado** directo
(las mismas fracciones de `sector_weights`) siempre que haya al menos una
excedencia observada en ese sector para el umbral pedido, y solo recurre a
la Weibull (extrapolación) cuando el sector no tiene ninguna excedencia
observada -- marcando esos sectores con `source='weibull'` y una nota
explícita en `per_sector`. Para P(U10>15, K=1): 4 de los 16 sectores (0°,
270°, 315°, 337.5°) tienen 1-3.5 "horas efectivas" de excedencia observada
(suman exactamente 7.0 h); los otros 12 sectores no tienen ninguna y caen a
Weibull (probabilidades ~1e-9 a 1e-26, contribución despreciable). El
resultado agregado (0.0055 %) es así una **agregación honesta de conteos
directos**, no una extrapolación. Advertencia explícita: con conteos tan
bajos (1-3.5 h en 15 años por sector) la incertidumbre muestral es grande;
tratar la cifra como orden de magnitud, no como una probabilidad precisa.
Para umbrales aún más raros (más allá de lo observado en los 15 años), la
función cae a Weibull automáticamente y lo señala en la columna `note` --
no se debe interpretar esa cifra como concluyente sin validación adicional
(GPD/Peak-Over-Threshold, fuera de alcance de esta entrega).

Tabla completa por sector (frecuencia, U10 media, Weibull c y k por MLE
ponderada sobre horas no-calma): `windrose_16.csv`.
Resumen de calma/variable: `calm_variable_summary.csv`.
Tabla estacional/día-noche: `seasonal_daynight.csv` (ver más abajo).

### Estacional / día-noche

`seasonal_daynight.csv`: DJF/MAM/JJA/SON x día(07-19h)/noche, con fracción de
calma, U10 media (no-calma) y fracción de horas con U10 > 5 m/s. Patrón
general: **el día es más ventoso que la noche en todas las estaciones**
(menor calma, mayor U10 media y mayor frecuencia de U10 > 5 m/s de día),
consistente con mezcla convectiva diurna; JJA (verano) es la estación con
mayor frecuencia de U10 > 5 m/s de día (30.6 %). No se aplicó ninguna
clasificación de estabilidad atmosférica explícita (caveat de estabilidad
neutra): el corte día/noche es puramente horario/calendario, justificado
porque los vientos fuertes -- los relevantes para confort/peligro peatonal --
son predominantemente diurnos o asociados a frentes, no al régimen nocturno
de chorro de baja altura. La hora local usa **desfase fijo UTC-6** (no se
aplicó horario de verano, vigente aprox. 2010-2021 y abolido a nivel
nacional en 2022 excepto franja fronteriza) -- puede introducir un sesgo de
hasta ~1 h en la frontera día/noche durante esos años.

## Transferencia de dos capas P14-A: aeropuerto -> entrada CFD (I2)

**Bloqueante de la revisión F1 (I2), resuelto en `transfer.py`.** El único
lugar donde existía algo parecido a una transferencia era
`ml/export.py:93` (`u* = U10*kappa/ln((10-d+z0)/z0)`), que aplica el U10 de
la estación **directamente** a la ley logarítmica con la rugosidad urbana,
es decir, **no hace ninguna transferencia** (asume que el U10 del aeropuerto
ya fue medido dentro de la huella urbana). Eso sobrestima u* (y por tanto
K = U_local/U10) entre **+2 % y +31 %** según el z0 del sector (más en los
sectores N/NW/W, menos en los dominantes ESE/E/SE).

Método implementado (altura de mezcla de Wieringa, 60 m -- el mismo que usa
NEN 8100, coherente con P10):
1. `u*_s = kappa * U10,s / ln(10 / z0,s)`, con **z0,s = 0.03 m** (estación
   abierta, ver justificación abajo).
2. `U_mezcla = (u*_s/kappa) * ln(60 / z0,s)` (altura de mezcla z_b = 60 m).
3. `u*_regional(theta) = kappa * U_mezcla / ln(60 / z0,regional(theta))`
   (d=0 en este paso intermedio de 60 m; su efecto ahí es <=2 %, se ignora
   y se documenta -- **no** es el mismo d que usa el perfil de entrada real).
4. Perfil de entrada (Richards & Hoxey, igual que `DATA_CONTRACT.md`, **con**
   el d real de Macdonald/Kanda del sector, no cero):
   `U(z) = (u*_regional/kappa) * ln((z - d_regional + z0,regional)/z0,regional)`.
- Control cruzado: EN 1991-1-4 ec. 4.4-4.5 (`k_r(z0) = 0.19*(z0/0.05)^0.07`).
- **z0,s = 0.03 m** (terreno abierto): MMMY es una estación sinóptica
  OMM/OACI; las reglas de emplazamiento del Anexo 3 de OACI exigen que el
  anemómetro esté sobre terreno abierto sin obstrucciones representativo del
  campo aéreo (pasto/pavimento, sin edificios/árboles en su sector de
  exposición) -- la clase "terreno abierto" de la Guía OMM No. 8 /
  Wieringa (1992) da z0 ~ 0.01-0.05 m; se usa el punto medio 0.03 m,
  coincidente con `DATA_CONTRACT.md` ("z0_open ~ 0.03 m"). Es un valor
  estándar de literatura para la **clase** de exposición, **no** una
  medición del uso de suelo real alrededor de MMMY (fuera de alcance de este
  módulo) -- **[no verificado]** a nivel de sitio específico.

Valores reproducidos exactamente contra la tabla propia de la revisión
(`test_transfer.py::test_transfer_factor_matches_review_table`, z0,s=0.03,
z_mezcla=60, kappa=0.41):

| z0,regional [m] | T mezcla 60 m | T EN 1991-1-4 | U(10m)/U10 mezcla | sobrestimación de `export.py` |
|---|---|---|---|---|
| 0.05 | 0.0757 | 0.0731 | 0.979 | +2 % |
| 0.08 | 0.0810 | 0.0756 | 0.956 | +5 % |
| 0.32 | 0.1025 | 0.0833 | 0.868 | +15 % |
| 1.00 | 0.1310 | 0.0902 | 0.766 | +31 % |

**Fuente de huellas (revisión G1, actualizado 2026-09-28):** el z0 de
Macdonald por sector ahora se calcula por defecto con huellas **Overture**
(`z0_method='macdonald'`, lee `roughness_16sectors_overture.csv`, columnas
`*_overture`), no OSM: las huellas OSM subestiman λp en los sectores
N/NE/W/NW (cobertura de edificios incompleta ahí, ver revisión G1). El z0
basado en OSM queda seleccionable como sensibilidad con
`z0_method='macdonald_osm'` (mismo archivo, columnas `*_osm`).
Reporte completo por los 16 sectores reales (Macdonald/Overture primario,
Macdonald/OSM sensibilidad, Kanda, control): `transfer_report_16sectors.csv`.
Con Overture, T = u*_regional/U10 (método de mezcla 60 m) va de **0.075 a
0.102** en los 16 sectores (antes, con OSM, 0.064 a 0.103 -- rango
agregado similar, pero redistribuido: N/NE/W suben porque Overture ve más
huella construida ahí, mientras 202.5° baja porque la respuesta de z0 de
Macdonald a λp **no es monótona** -- entra en régimen de "skimming" y z0
puede bajar al subir λp aún más, revisión G2). Para los sectores dominantes
ESE/E/SE (z0_macdonald_overture ~ 0.060-0.081 m) la sobrestimación de
`export.py` es +3.2 % a +4.9 %; para los sectores de "nortes"/poniente
(N/NE/W, z0 más alto por la cobertura Overture más completa) llega a
+10.4 % a +15.8 %.

**API para `ml/export.py`** (el agente de ML reemplaza su fórmula por
ésta -- ver docstring completo en `transfer.py`):
- `inflow_for_sector(theta_deg, U10, roughness_row, z0_method) -> InflowResult`
  con `.u_star`, `.z0`, `.d`, `.T`, y métodos `.U_H(H_ref)`, `.k()`,
  `.inlet_profile(z)`. `z0_method` en `{'macdonald' (primario, P13-B),
  'kanda' (sensibilidad), 'control'/'en1991-1-4' (tabla EN 1991-1-4)}`.
- `U_H_over_U10(inflow, H_ref)` y `K_from_cfd_normalized(u_over_UH, inflow,
  H_ref)`: convierten la salida no-dimensional del CFD (`|U|/U_H`) a
  K = U_local/U10 usando la transferencia correcta, en vez de la fórmula sin
  transferencia actual de `export.py`.
- Por Reynolds-independencia, la **magnitud** de u* se puede reaplicar en
  posproceso (no requiere recorrer CFD); pero la **forma** del perfil (z0,
  d regionales por sector) sí debe fijarse antes de correr los casos.

## NEN 8100 y Lawson LDDC (I4)

**[no verificado contra el texto impreso de NEN 8100 ni contra Lawson 1978]**
-- los cortes y umbrales de esta sección vienen del resumen de la revisión
independiente F1 (`docs/revisiones/F1_revision.md`, I4), no de una lectura
directa de las normas. Cotejar antes de citarlos ante un sinodal.

- **NEN 8100** (`windclimate.nen8100_comfort_class`, `nen8100_activity_quality`,
  `nen8100_danger_class`): umbral de confort 5 m/s de velocidad media local a
  1.75 m. Clases por P(V_loc > 5 m/s): A < 2.5 %, B [2.5,5) %, C [5,10) %,
  D [10,20) %, E >= 20 %. Calidad por actividad: **atravesar** (A-C buena, D
  moderada, E mala), **pasear** (A-B buena, C moderada, D-E mala), **estar
  sentado** (A buena, B moderada, C-E mala). Peligro por P(V_loc > 15 m/s):
  <0.05 % sin riesgo, [0.05,0.3) % riesgo limitado, >=0.3 % peligroso.
- **Lawson LDDC** (`windclimate.lawson_lddc_assessment`, umbrales en
  `LAWSON_LDDC_COMFORT_THRESHOLDS_MS`): usa el máximo entre la media y el
  **GEM** (gust-equivalent mean = ráfaga/1.85), umbrales de comodidad 4/6/8/10
  m/s excedidos <5 % del tiempo (sentarse largo / estar de pie-pasear /
  caminar de negocios / incómodo), y umbrales de seguridad 15/20 m/s
  (riesgo limitado / peligroso) con un % anual muy bajo. Con RANS solo se
  tiene la media: `windclimate.gust_equivalent_mean(u_local, k_local)`
  estima `U_ráfaga ~= U + g*sqrt(2k/3)` (g ~ 3.0-3.5) y
  `GEM = max(U, U_ráfaga/1.85)`, **declarado explícitamente como
  estimación** (RANS estacionario no resuelve el espectro real de ráfagas).
  Si se compara Lawson usando solo la media (sin GEM) contra NEN 8100 (que sí
  usa la media), la comparación queda sesgada a favor de Lawson -- usar GEM
  para Lawson y la media pura para NEN 8100, cada uno con su propia
  definición.
- Ambas funciones reutilizan `annual_exceedance`: basta pasar
  `K = K_GEM(theta) = GEM(theta)/U10(theta)` en vez de `K = U_local/U10`
  para obtener la probabilidad anual bajo el criterio Lawson en el mismo
  punto.

## Representatividad de MMMY para el campus (I5)

MMMY está a **~18 km al NNE** del campus. Para el sector dominante ESE, el
flujo que llega al Tec pasa junto al Cerro de la Silla (~1200 m sobre la
ciudad, a pocos km al E-SE del campus) y, para los "poniente", por la Loma
Larga -- canalización orográfica local que la rosa **del aeropuerto** no
necesariamente contiene (P19=D mete la orografía "a través de la rosa", pero
es la rosa del aeropuerto, no la del campus).

Comparación cuantitativa (`build_windrose.py`, sección I5) contra dos
fuentes independientes:
- **ERA5** (reanálisis, celda más cercana al campus 25.651N/-100.290O,
  2014-2025, `E:\PINN\datos\viento\era5_openmeteo_rose16.csv`, generado por
  otro agente de este proyecto): arco ENE-SSE (67.5°-157.5°) = **65.4 %**
  contra **56.1 %** en MMMY (+9.2 puntos porcentuales); arco N-NNW-NW =
  **10.2 %** en ERA5 contra **11.4 %** en MMMY -- **MMMY y ERA5 coinciden
  entre sí** en que el componente N/NW es marginal (~7-11 %).
- **SIMA "Preparatoria ITESM Garza Lagüera"** (estación real de techo, ~4.1
  km al sur del Campus Monterrey, dentro del valle, informe INECC 2025,
  2021-2023, ver `E:\PINN\datos\viento\fuentes_viento.md` A.2): rosa de 8
  puntos con **SE dominante 33 %**, pero también **S 18 %, N 17 %, NW 14 %**
  -- el informe atribuye explícitamente las componentes NW/SE a la
  "canalización del viento por la Sierra Madre Oriental y el Cerro de la
  Silla". El bin "SE" de 8 puntos de SIMA (33 %) es comparable en magnitud a
  la suma ESE+SE+SSE de MMMY (35.4 %) y de ERA5 (38.1 %) -- **razonable
  acuerdo en el eje SE**. Pero el componente **N+NW de SIMA (31 %) es 3 veces
  mayor** que el de MMMY o ERA5 (~7-11 %) -- **ninguna de las dos fuentes de
  referencia (aeropuerto, reanálisis de 31 km) resuelve la componente
  NW/N de canalización de valle que sí ve la estación real más cercana al
  campus**. (Comparación aproximada: los bins de 8 puntos de SIMA no
  coinciden exactamente con los límites de los sectores de 16 puntos usados
  aquí; se reporta como orden de magnitud, no como una cifra exacta.)
- **Conclusión (limitación explícita):** la rosa MMMY usada en esta
  climatología es razonablemente representativa del **eje E-SE dominante**
  del campus (que es también el sector con la excedencia más alta y por
  tanto el más relevante para el confort peatonal, ver `windrose_16.csv`),
  pero **probablemente subestima la frecuencia del componente N/NW**
  ("nortes" canalizados por el valle) en un factor de ~2-3x. Un sinodal
  puede atacar este punto legítimamente; se declara aquí en vez de omitirlo.
  Cuantificación adicional (banda de incertidumbre de K, sensibilidad de
  malla en 112.5°, etc.) queda fuera de alcance de `v2/climate` y corresponde
  a `v2/geometry`/`v2/cfd` (ver revisión F1, G2).

## Figuras

- `figures/windrose_mmmy.png`: rosa de vientos apilada por clase de
  velocidad (16 sectores, % de horas, calmas excluidas de las barras y
  reportadas en el título).
- `figures/weibull_check_mmmy.png`: histograma empírico (horas no-calma,
  ponderado por el reparto de sector) vs. densidad Weibull ajustada, un
  panel por sector.

## Módulo `windclimate.py` (API para el módulo de confort)

- `build_windrose(hourly) -> WindRoseResult`: construye la rosa de 16
  sectores + ajuste Weibull ponderado por MLE. Ahora también guarda
  `.sector_speeds` (lista de 16 arreglos `(velocidades, pesos)` no-calma por
  sector), necesario para la excedencia empírica-primero (I3).
- `sector_weights(direction_deg)`: reparto fraccional 10°->22.5° (ver QC).
- `weibull_fit_weighted(x, w) -> (c, k)`: MLE ponderada, 2 parámetros, loc=0.
- `empirical_prob_exceed_sector(windrose, sector_idx, u) -> (p, n_eff_exceed)`:
  P empírica directa (no paramétrica) y "horas efectivas" de excedencia en
  un sector.
- `annual_exceedance(windrose_table, K, threshold_local, sector_speeds=None,
  method='auto') -> dict`: función que llama el módulo de confort. Dado el
  factor de amplificación K(theta) (escalar o arreglo de 16, alineado a
  `sector_centre_deg` ascendente; puede ser K de la media O K_GEM para
  Lawson, ver abajo) y un umbral local, devuelve la probabilidad anual de
  excedencia (`annual_probability`), horas/año (`hours_per_year`) y el
  detalle por sector (`per_sector`, con columnas `source` empirical/weibull
  y `note`). Con `method='auto'` (recomendado, I3) usa el conteo empírico
  ponderado por sector siempre que exista, y solo extrapola con Weibull
  donde no hay ninguna excedencia observada (marcado explícitamente). Con
  K=1 en todos los sectores se recupera la excedencia climatológica pura de
  U10 (caso de sanity check NEN 8100 en los tests).
- `gust_equivalent_mean(u_local, k_local, gust_factor=3.25) -> GEM`: entrada
  de Lawson LDDC a partir de un punto RANS (media + k), **estimación**
  declarada (I4).
- `nen8100_comfort_class(p_gt_5)`, `nen8100_activity_quality(activity,
  p_gt_5)`, `nen8100_danger_class(p_gt_15)`, `lawson_lddc_assessment(
  windrose_table, K_gem, sector_speeds=...)`: criterios NEN 8100/Lawson
  (I4, **[no verificado contra las normas impresas]**, ver sección arriba).
- `seasonal_daynight_table(hourly, strong_wind_threshold)`: tabla
  estación x día/noche.
- `empirical_exceedance(hourly, threshold)`: agregado simple (todas las
  horas, sin separar por sector); usado para validar `annual_exceedance` en
  los tests.

## Módulo `transfer.py` (I2, transferencia de rugosidad P14-A)

Ver sección "Transferencia de dos capas" arriba para el método. Funciones
clave: `transfer_factor(z0_regional, z0_station, z_blend)`,
`ustar_regional(U10, z0_regional, ...)`, `inflow_for_sector(theta_deg, U10,
roughness_row, z0_method) -> InflowResult`, `U_H_over_U10(inflow, H_ref)`,
`K_from_cfd_normalized(u_over_UH, inflow, H_ref)`,
`report_transfer_ratios(roughness_table) -> DataFrame` (genera
`transfer_report_16sectors.csv`). `load_roughness_table()` lee por defecto
`E:\PINN\v2\geometry\out\H_best\roughness_16sectors_overture.csv`
(`ROUGHNESS_CSV_OVERTURE`, primario desde G1); el archivo previo, solo-OSM
(`ROUGHNESS_CSV_OSM_ONLY` = `...\roughness_16sectors.csv`), queda como
referencia/back-compat pero ya no es el default. `z0_method` acepta
`'macdonald'` (Overture, primario), `'macdonald_osm'` (sensibilidad),
`'kanda'` (Overture) y `'control'`/`'en1991-1-4'` (constante EN 1991-1-4,
z0=1.0 m, d=0 -- ya no se lee de ningún CSV).

## Pruebas

`test_windclimate.py` (32 pruebas) + `test_transfer.py` (17 pruebas), 49 en
total, todas corren sin red usando los CSV crudos locales y
`roughness_16sectors_overture.csv`:
- las frecuencias de los 16 sectores + calma + variable suman 1;
- el reparto de sector (`sector_weights`) suma 1 por observación;
- la Weibull reproduce la excedencia empírica de 5 m/s dentro de ~4 puntos
  porcentuales en cada uno de los 16 sectores, y dentro de ~2 puntos en
  agregado;
- `annual_exceedance(method='auto')` reproduce **exactamente** las cifras
  recalculadas por la revisión F1: P(U10>15,K=1) = 0.0055 % (7.0 h) y
  P(U10>10,K=1) = 0.52 % (I3);
- caso de cordura NEN 8100 con K=1 en todos los sectores (el umbral U10
  equivalente debe igualar el umbral local, y la probabilidad anual debe
  coincidir exactamente con la agregación manual de la tabla);
- monotonía de la excedencia anual en K; validación de forma de K;
- clases NEN 8100 (A-E, calidad por actividad, peligro) en sus cortes exactos;
- `gust_equivalent_mean` >= media, y = media cuando k=0;
- `lawson_lddc_assessment` ordena los umbrales de forma consistente
  (umbral más alto nunca excedido con más frecuencia que uno más bajo);
- recuperación de parámetros Weibull conocidos en datos sintéticos;
- **`transfer.py`**: `transfer_factor`/`transfer_factor_en1991`/
  `u10m_urban_over_u10_station` reproducen **exactamente** (4 decimales) la
  tabla de la revisión F1 (I2) para z0 = 0.05/0.08/0.32/1.00 m; la fórmula
  ingenua de `export.py` sobrestima T en todos los casos; el perfil de
  entrada falla explícitamente (en vez de dar NaN) si se evalúa por debajo
  de la altura de desplazamiento.

Ejecutar:
```
E:\PINN\.venv\Scripts\python.exe -m pytest E:\PINN\v2\climate\test_windclimate.py E:\PINN\v2\climate\test_transfer.py -v
```

## Cómo regenerar todo

```
E:\PINN\.venv\Scripts\python.exe E:\PINN\v2\climate\parse_isd.py       # QC + cache por estación (opcional, build_windrose ya lo hace)
E:\PINN\.venv\Scripts\python.exe E:\PINN\v2\climate\build_windrose.py  # windrose_16.csv, tablas, figuras, transfer_report_16sectors.csv, I5
E:\PINN\.venv\Scripts\python.exe E:\PINN\v2\climate\transfer.py        # solo el reporte de transferencia (I2), si no se corrió build_windrose
```

## Limitaciones / advertencias (resumen)

1. Altura de anemómetro asumida 10 m, no verificada en metadatos ISD.
2. Efectos orográficos/de valle **no modelados por separado dentro del
   dominio CFD** (siguen entrando "a través de la rosa" medida, P19=D). Su
   representatividad para el campus SÍ se cuantificó (I5): el eje E-SE
   dominante concuerda razonablemente entre MMMY, ERA5 y la estación SIMA
   real más cercana al campus, pero el componente N/NW ("nortes"
   canalizados por el valle) está probablemente subestimado ~2-3x en MMMY
   frente a la estación real dentro del valle -- ver sección "Representatividad
   de MMMY para el campus (I5)".
3. Resolución METAR (10° en dirección, nudos enteros en velocidad) corregida
   por redistribución proporcional determinista, no por muestreo aleatorio;
   documentado en `windclimate.py`.
4. Ajuste Weibull por sector es una sola población (no mixtura); reproduce
   bien la excedencia entre ~2-8 m/s pero **subestima la cola extrema**
   (>15 m/s). Desde la revisión F1 (I3), `annual_exceedance` ya NO depende
   de la Weibull para el rango con datos (usa el conteo empírico ponderado
   por defecto); la Weibull queda solo como respaldo para sectores/umbrales
   sin ninguna excedencia observada, y se marca explícitamente cuando eso
   ocurre (columna `note`). Más allá de lo observado, sigue sin validarse
   con GPD/Peak-Over-Threshold (fuera de alcance de esta entrega).
5. Partición día/noche y estacional usa hora local con **desfase fijo
   UTC-6** (sin horario de verano) y sin clasificación de estabilidad
   atmosférica (caveat de estabilidad neutra pedido en la tarea): es una
   estratificación climatológica simple, no meteorológica.
6. MMAN (secundaria) tiene cobertura nocturna estructuralmente ausente; no
   se usa para ninguna estadística horaria completa, solo como referencia
   diurna cruzada (misma prevalencia ESE/E/SE que MMMY, calma 18.1 %).
7. Datos 2025 (hasta 2025-08-24) descargados pero excluidos de la
   climatología de 15 años por estar incompletos.
8. No se localizaron datos SMN/CONAGUA EMA de descarga abierta directa para
   esta tarea; no se incluyeron.
9. **z0,estación = 0.03 m** (I2) es un valor estándar de literatura para la
   clase de exposición "terreno abierto" de MMMY (avalado por las reglas de
   emplazamiento OACI), **no** una medición del uso de suelo real alrededor
   del aeropuerto -- **[no verificado]** a nivel de sitio específico; el
   refinamiento opcional (z0 de estación por sector, factores de ráfaga
   Verkaik 2000) no se implementó en esta entrega.
10. La inconsistencia de kappa entre la morfometría (Macdonald, 0.40) y el
    resto del proyecto/OpenFOAM (0.41) es una simplificación documentada
    (revisión F1, G7), no corregida aquí.
11. Los criterios NEN 8100 y Lawson LDDC (I4) están **[no verificados contra
    el texto impreso de las normas]**; el GEM de Lawson es una estimación a
    partir de RANS estacionario (media + k), no un espectro de ráfagas real.
12. `transfer.py::InflowResult.inlet_profile` describe la condición de
    frontera de entrada (flujo no perturbado aguas arriba), no el campo cerca
    del suelo dentro del canopy urbano; falla explícitamente si se evalúa en
    o por debajo de la altura de desplazamiento d (que supera 1.75 m -- la
    altura peatonal de NEN 8100 -- en varios sectores, d_macdonald ~ 4-4.7 m).
