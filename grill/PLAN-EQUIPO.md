# Plan del equipo de subagentes (fase 2)

> Estado: **propuesta**. La fase 2 no empieza hasta que el equipo humano responda `grill-me-pinn-zonatec.pdf`.
> Las referencias `P#` apuntan a las preguntas de ese documento. Si cambia una respuesta, cambia el trabajo del agente que depende de ella.

## Principios

1. **Un dueño humano por especialidad** (P7). Cada subagente reporta a su dueño; el líder integra.
2. **Fuentes fiables solamente**: revistas, libros, normas, documentación oficial y datos institucionales. Nada de Wikipedia. Todo lo no verificado se marca `[no verificado]`.
3. **Ninguna cifra escrita a mano.** Informe, web y video leen sus números de archivos generados, como hace `video/hechos.mjs` en v1.
4. **Evaluación independiente.** El agente evaluador no ve el código de entrenamiento y recibe los casos retenidos sellados.
5. **Sin trailer de coautoría de Claude** en commits del repo compartido con Oscar.
6. v2 vive en `v2/` dentro de este repo; v1 queda intacto como prueba de concepto (P29 = B).

## Roles

| # | Agente | Entradas | Salidas | Depende de |
|---|---|---|---|---|
| 0 | **Líder / integrador** | Respuestas del grill, reportes de todos | `v2/PLAN.md` congelado, revisiones de interfaz entre agentes, informe de avance semanal | Todas |
| 1 | **Geo-SIG** | Polígono de Zona Tec (P17), OSM (Overpass), levantamiento de pisos del equipo, planos del Tec o LiDAR de INEGI si existen (P18) | `v2/geo/zonatec.geojson` (huella, altura, fuente de la altura), `zonatec.stl` LOD1, variantes (P4), SDF en rejilla, parámetros morfométricos (λp, λf, H̄, σH) | P4, P17, P18, P19 |
| 2 | **Clima y capa límite** | SMN/CONAGUA (EMA), NOAA ISD del aeropuerto (P14), salidas de Geo-SIG | Rosa de vientos de 16 sectores con probabilidades de U₁₀; $z_0$ y $d$ por sector (Macdonald / Kanda, P13); parámetros $u_*$, $z_0$ del perfil de entrada (P12); nota de limitaciones (estabilidad P15, valle T8) | P12–P15 |
| 3 | **CFD** | STL (1), perfiles (2), hardware (P6) | Caso OpenFOAM plantilla (`simpleFoam`, `snappyHexMesh`, `atmBoundaryLayerInlet`); **validación AIJ o CEDVAL** (P22); estudio de malla con GCI; script de lotes para N corridas (P21); registro de convergencia por corrida | P6, P16, P20–P22; espera a 1 y 2 |
| 4 | **Datos** | Resultados de OpenFOAM | `v2/data/*.h5`: campos (u, v, w, p, k, ν_t) en celdas y en rejilla peatonal a z = 1.75 m, normalizados por $U_{ref}$; partición entrenamiento/prueba **sellada** (direcciones, variante y velocidad retenidas, P27); tarjeta de datos | P5, P21, P27; espera a 3 |
| 5 | **ML / PINN** | Datos (4), SDF (1) | `v2/train/`: PyTorch (evolución de `train/pinn.py`), por etapas: datos → +continuidad → +RANS (P23); fronteras P24; arquitectura P25; pesos adaptativos P26; referencias de comparación (misma red sin física, interpolación); `model.json` exportable a JS | P3, P9, P23–P26; espera a 4 |
| 6 | **Evaluador independiente** | Modelo congelado (5), casos sellados (4), mediciones (P28) | `v2/eval/report.json`: L2, MAE de K, tasa de acierto VDI 3783-9, error por zona, comparación con referencias; lista de afirmaciones del informe que **no** se sostienen | P27, P28; no ve el código de 5 |
| 7 | **Confort y posprocesado** | Modelo (5), rosa de vientos (2) | K por punto y dirección → probabilidad de excedencia → clase NEN 8100 o Lawson (P10); mapas de confort | P8, P10 |
| 8 | **Web** | `model.json`, capas de confort (7), geojson (1) | `v2/public/`: la web de v1 ampliada con mapa de Zona Tec (MapLibre y OSM), selector de dirección y altura, panel del punto (P8, P11); despliegue en Vercel (con aprobación de Hermann) | P8, P9, P11 |
| 9 | **Redacción y fuentes** | Todo lo anterior | Informe (métodos, validación, limitaciones), referencias en APA revisadas una por una (DOI resuelve, sin Wikipedia), guion de la presentación | P1, P2 |
| 10 | **Video** (opcional) | `eval/report.json`, `hechos` | Película v2 con el pipeline Node y ffmpeg de v1; cifras leídas de archivos | P1 (entregables) |

## Orden y paralelismo

```
Semana 1   [1 Geo-SIG] ──┐      [2 Clima/ABL] ──┐      [3 CFD: caso AIJ en paralelo]
                         └───────────┬──────────┘
Semana 2                     [3 CFD: malla Zona Tec + GCI]
Semanas 3–4                  [3 CFD: lote de N corridas] ──> [4 Datos]      (humanos: campaña con anemómetro, P28)
Semanas 4–6                                     [5 ML/PINN: etapas] <──> [6 Evaluador: casos sellados]
Semanas 6–7                  [7 Confort] ──> [8 Web]
Semana 8                     [9 Redacción]  [10 Video]
```

- Arrancan en paralelo: **1**, **2** y **3** (la validación AIJ no necesita Zona Tec).
- **5** puede empezar antes con los primeros casos que salgan de 4 (por ejemplo, 4 direcciones) para depurar la tubería.
- **6** se crea con la partición sellada desde el día en que 4 la produce, y no recibe nada más de 5 que el modelo congelado.

## Qué respuestas bloquean a quién

| Respuesta | Bloquea | Si cambia... |
|---|---|---|
| P1 plazo, P2 rúbrica | Todos (alcance) | Con ≤ 4 semanas: 8 direcciones, sin variantes, sin campaña, sin 7 avanzado |
| P3 ¿PINN estricta? | 5 | Si C (operador): 5 cambia a DeepONet o FNO y 4 exporta rejillas |
| P4 geometrías | 1, 3, 4, 5 | Si C: 1 genera ciudades sintéticas y 5 usa un codificador de mapa de alturas (P25-B) |
| P5 parámetros de entrada | 3, 4 | Define la matriz de corridas |
| P6 hardware | 3, 5 | Define las corridas por noche y el tamaño de malla |
| P12–P15 ABL | 2, 3 | Cambian las condiciones de frontera de todas las corridas: decidir **antes** del lote |
| P16, P20–P22 CFD | 3 | Cambiar el solver después del lote obliga a rehacerlo |
| P17–P19 dominio | 1, 3 | Cambiar el polígono después de mallar obliga a rehacer la malla |
| P23–P26 PINN | 5 | Se puede iterar sin tocar datos |
| P27–P28 validación | 4, 6 | La partición se sella una vez; cambiarla después invalida la evaluación |
| P8–P11 entregable | 7, 8 | Se puede iterar al final |

## Criterio de «terminado» por agente

- **1**: el STL es cerrado (sin agujeros), cada altura tiene fuente y hay una tabla de incertidumbre.
- **2**: la rosa de vientos cita la estación y el periodo, y $z_0$ y $d$ se reportan con rango.
- **3**: AIJ o CEDVAL reproducido con métricas publicadas; GCI < 5 % en K a nivel peatonal **[meta, a acordar]**; residuos < 1e-4 o estancados documentados.
- **4**: la partición está sellada con hash y la tarjeta de datos está completa.
- **5**: supera o iguala a las referencias en los casos retenidos, o documenta dónde no.
- **6**: informe que incluya las derrotas.
- **8**: funciona en móvil y en escritorio, sin servidor, y el despliegue está aprobado por Hermann.
- **9**: cero Wikipedia; cada DOI resuelve.
