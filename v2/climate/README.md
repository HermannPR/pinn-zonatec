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
- **P(U10 > 5 m/s)**: empírica 18.6 %, Weibull agregada (ver más abajo) 18.4 %.
- **P(U10 > 15 m/s)** ("peligro"): empírica 0.010 % (~13 h/año), Weibull
  agregada 0.0013 % (~0.1 h/año) -- **la Weibull subestima la cola extrema**;
  para el criterio de "peligro" (Lawson, NEN 8100 umbral alto) se recomienda
  usar directamente el conteo empírico o un ajuste de cola tipo
  Peak-Over-Threshold/GPD en vez de la Weibull global, que es adecuada solo
  hasta ~2-8 m/s (donde se valida en `test_windclimate.py`).

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

## Figuras

- `figures/windrose_mmmy.png`: rosa de vientos apilada por clase de
  velocidad (16 sectores, % de horas, calmas excluidas de las barras y
  reportadas en el título).
- `figures/weibull_check_mmmy.png`: histograma empírico (horas no-calma,
  ponderado por el reparto de sector) vs. densidad Weibull ajustada, un
  panel por sector.

## Módulo `windclimate.py` (API para el módulo de confort)

- `build_windrose(hourly) -> WindRoseResult`: construye la rosa de 16
  sectores + ajuste Weibull ponderado por MLE.
- `sector_weights(direction_deg)`: reparto fraccional 10°->22.5° (ver QC).
- `weibull_fit_weighted(x, w) -> (c, k)`: MLE ponderada, 2 parámetros, loc=0.
- `annual_exceedance(windrose_table, K, threshold_local) -> dict`: función
  que llamará el módulo de confort. Dado el factor de amplificación K(theta)
  (escalar o arreglo de 16, alineado a `sector_centre_deg` ascendente) y un
  umbral local (p. ej. 5 m/s NEN 8100, 15 m/s peligro, o umbrales Lawson),
  devuelve la probabilidad anual de excedencia (`annual_probability`), su
  equivalente en horas/año (`hours_per_year`) y el detalle por sector
  (`per_sector`). Con K=1 en todos los sectores se recupera la excedencia
  climatológica pura de U10 (caso de sanity check NEN 8100 en los tests).
- `seasonal_daynight_table(hourly, strong_wind_threshold)`: tabla
  estación x día/noche.
- `empirical_exceedance(hourly, threshold)`: solo para validar contra la
  Weibull en los tests, no la usa el módulo de confort.

## Pruebas

`test_windclimate.py` (pytest, 12 pruebas, todas corren sin red usando los
CSV crudos locales):
- las frecuencias de los 16 sectores + calma + variable suman 1;
- el reparto de sector (`sector_weights`) suma 1 por observación;
- la Weibull reproduce la excedencia empírica de 5 m/s dentro de ~4 puntos
  porcentuales en cada uno de los 16 sectores, y dentro de ~2 puntos en
  agregado;
- caso de cordura NEN 8100 con K=1 en todos los sectores (el umbral U10
  equivalente debe igualar el umbral local, y la probabilidad anual debe
  coincidir exactamente con la agregación manual de la tabla);
- monotonía de la excedencia anual en K;
- validación de forma de K (escalar vs. arreglo de longitud 16);
- recuperación de parámetros Weibull conocidos en datos sintéticos.

Ejecutar:
```
E:\PINN\.venv\Scripts\python.exe -m pytest E:\PINN\v2\climate\test_windclimate.py -v
```

## Cómo regenerar todo

```
E:\PINN\.venv\Scripts\python.exe E:\PINN\v2\climate\parse_isd.py       # QC + cache por estación (opcional, build_windrose ya lo hace)
E:\PINN\.venv\Scripts\python.exe E:\PINN\v2\climate\build_windrose.py  # windrose_16.csv, tablas, figuras
```

## Limitaciones / advertencias (resumen)

1. Altura de anemómetro asumida 10 m, no verificada en metadatos ISD.
2. Efectos orográficos/de valle **no modelados por separado**: están
   implícitos en la rosa medida en el aeropuerto (decisión P19=D), que no es
   necesariamente idéntica al viento no perturbado sobre el campus (~18 km
   al sur-suroeste de MMMY).
3. Resolución METAR (10° en dirección, nudos enteros en velocidad) corregida
   por redistribución proporcional determinista, no por muestreo aleatorio;
   documentado en `windclimate.py`.
4. Ajuste Weibull por sector es una sola población (no mixtura); reproduce
   bien la excedencia entre ~2-8 m/s pero **subestima la cola extrema**
   (>15 m/s) -- no usar para el criterio de "peligro" sin validación
   adicional (recomendado: conteo empírico directo o GPD sobre picos).
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
