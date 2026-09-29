# PLAN — PINN Zona Tec v2

Líder: claude-culiacan (PC Culiacán). Base: `DECISIONES.md` (respuestas vinculantes P1-P29) y `v2/docs/DATA_CONTRACT.md` (marco de coordenadas, convención de dirección y formato de datos).
Estado: **v1.0 del 28-sep-2026**. Las cifras marcadas [estimado] se recalculan con las mediciones piloto (benchmark de OpenFOAM, malla piloto) y quedan registradas en la sección 7.

## 1. Qué se construye (una frase)
Un modelo 3D del viento medio en Zona Tec: con OpenFOAM RANS se hacen unas 40 simulaciones (16 direcciones, 2 o 3 variantes de geometría, velocidades extra) con un perfil log de capa límite en la entrada, validado contra el caso AIJ A y con un estudio de malla GCI. Con esos datos se entrena una PINN híbrida (datos + continuidad + RANS) que responde en cualquier punto (x, y, z), dirección y variante. Se compara con DeepONet y con referencias simples en casos retenidos, se combina con la rosa de vientos de Monterrey para obtener el confort (Lawson y NEN 8100) y se sirve en una web donde se elige un punto.

## 2. Arquitectura del proyecto
```
E:\PINN\
  DECISIONES.md  PLAN.md  STATUS.md (bitácora)      admin\ (scripts que requieren a Hermann)
  datos\  FUENTES.md, alturas\, viento\             (investigación de fuentes, con licencias)
  tools\  openfoam, of_run.ps1, OPENFOAM_SETUP.md   runs\ (casos OpenFOAM grandes; no versionados)
  inbox\wind-pinn\  (v1 recibido, solo lectura)     logs\
  v2\  geometry\ climate\ cfd\{aij,zonatec}\ data\{raw,processed,synthetic}\ ml\ validation\ web\ docs\ scripts\
```
Principios, heredados de PLAN-EQUIPO v1 y ampliados:
1. Ninguna cifra escrita a mano: informe, web y video leen archivos generados.
2. Fuentes primarias con licencia registrada en `datos\FUENTES.md`. Lo no verificado lleva la marca [no verificado].
3. Evaluación independiente con partición sellada (hash).
4. Se reportan también las derrotas.

## 3. Fases, entregables y criterios de aceptación

**Calendario ajustado (Hermann, 28-sep 16:44: «quedan unas semanas», todo en esta PC).** El plan apunta a ~5 semanas. Las «semanas» de abajo son el orden ideal; lo que cuenta es la **prioridad**. La CPU corre CFD las 24 horas en cuanto el piloto queda aprobado, y el ML arranca con los primeros casos, sin esperar al lote completo.

Prioridades (se recorta desde abajo si falta tiempo):
1. AIJ validado + homogeneidad + GCI → 16 direcciones base → PINN etapas A/B + referencias + evaluación sellada → web con K, confort NEN 8100/Lawson.
2. Velocidades extra (independencia de Re, P27-D) → variante 1 × 8 direcciones → etapa C (RANS) → DeepONet.
3. Variante 2 × 8 direcciones (prueba retenida P27-C).
4. Extensiones: LES, árboles, FNO.

Si la variante 2 no alcanza, la prueba de geometría retenida (P27-C) se hace con la variante 1 retenida en 4 direcciones.

**Puertas de revisión:** antes de cerrar F1, F2, F3 y F4, un revisor **Opus** independiente revisa física, numérica y validación (P7 → autorrevisión). Sus hallazgos se atienden o se documentan en `v2/docs/revisiones/`.

### F0. Arranque (28-sep, hecho hoy)
Entregables: DECISIONES.md, PLAN.md, contrato de datos, entorno Python (venv en E:), investigación de fuentes en marcha.

### F1. Cimientos (semanas 1-2)
| Bloque | Entregable | Criterio de aceptación |
|---|---|---|
| Entorno CFD | OpenFOAM sin administrador (o script WSL2 para Hermann), `tools\of_run.ps1`, benchmark | pitzDaily converge; snappyHexMesh + checkMesh OK; prueba en paralelo o limitación documentada; s/iteración por M de celdas medido |
| Geometría | `zonatec_base.stl` + variantes, `buildings.csv` con fuente de altura, `frame.json`, dominio COST 732 por dirección, SDF | STL cerrado por edificio; cada altura con fuente; bloqueo < 3 %; pruebas `test_geometry.py` en verde |
| Alturas | `datos\alturas\alturas_consolidadas.csv`, lista de verificación de campo | cobertura por fuente reportada; discrepancias > 20 % marcadas |
| Clima | rosa de 16 sectores (NOAA ISD MMMY), Weibull por sector, `windclimate.py`; contraste con ERA5 | frecuencias suman 1; la Weibull reproduce P(U10 > 5 m/s) dentro de unos pocos % |
| Rugosidad | z0 y d por sector (Macdonald; Kanda como sensibilidad; tabla como control) | rango reportado por sector y sensibilidad ± 1 piso |
| Validación AIJ Caso A | caso OpenFOAM (edificio 1:1:2) con perfil de entrada del túnel; corridas con realizable k-ε, k-ω SST y k-ε estándar | tasa de acierto VDI 3783-9 (D = 0.25) de U/U_ref ≥ 0.66 en los puntos del túnel con el modelo elegido [meta]; recirculación en el techo y longitud de la estela comparadas con Tominaga et al. (2008) |
| Tubería ML | paquete `v2/ml` con etapas A/B/C, DeepONet, referencias, métricas VDI, exportación a JS; prueba de humo con datos sintéticos | pytest en verde; la prueba de humo corre de principio a fin (esto prueba la tubería, no la física) |

### F2. Zona Tec piloto (semanas 2-3)
- Prueba de homogeneidad horizontal: dominio vacío con el mismo perfil y la misma función de pared (`nutkAtmRoughWallFunction`). **Aceptación:** U entre la entrada y la zona de los edificios dentro de ± 5 % (z < 100 m) y k dentro de ± 20 % [meta, a documentar].
- Malla piloto de Zona Tec en 1 dirección (la dominante de la rosa): snappyHexMesh con dominio alineado al viento (una malla por dirección), primera celda de ~0.5 m cerca del suelo en la zona central y el nivel peatonal por encima de la tercera celda (AIJ).
- **GCI** con 3 mallas (razón de refinamiento ~1.3 a 1.5) en esa dirección. **Aceptación:** GCI_fina de K a 1.75 m con mediana < 5 % y percentil 90 reportado [meta].
- Convergencia: residuos < 1e-4, o estancados con los monitores de U en 10 puntos estables dentro de ± 1 % en las últimas 500 iteraciones.

### F3. Campaña CFD (semanas 3-6)
Matriz (P5-B, P21-B):
| Grupo | Casos |
|---|---|
| Base: 16 direcciones × U10 de referencia | 16 |
| Variantes 1 y 2 × 8 direcciones (0, 45, …, 315) | 16 |
| Velocidades extra (2 velocidades × 2 direcciones) | 4 |
| Mallas del GCI (media y gruesa, 1 dirección) | 2 |
| **Total Zona Tec** | **38** (+8 si se confirma una variante 3) |

La U10 de referencia se fija en una velocidad típica de viento fuerte de la rosa, ~5 a 6 m/s [por decidir con la rosa]; las extra, en ~0.5× y ~2× esa velocidad.
Extracción: muestreo a HDF5 según el contrato (zona de interés, z ≤ 2 H_max) y `manifest.csv`. Partición sellada (SHA-256 del manifiesto):
- 4 direcciones de la base retenidas: **22.5°, 157.5°, 247.5° y 337.5°**. Son no contiguas, una por cuadrante, y excluyen a propósito los sectores dominantes E-ESE-SE (90°, 112.5°, 135°; ~45 % de las horas en MMMY) para que el confort no dependa de direcciones que la red nunca vio. El piloto y el GCI se hacen en **112.5° (ESE, 21.6 %)**;
- la variante 2 completa retenida;
- una de las velocidades extra retenida.

### F4. PINN y comparadores (semanas 4-8)
- Etapas A → B → C (P23), fronteras P24, pesos adaptativos, Adam → L-BFGS (P26).
- DeepONet (P3-D); referencias: interpolación, la red sin física y la dirección simulada más cercana (P27).
- **Aceptación:** un evaluador independiente reporta las métricas (L2 relativo, MAE de K, tasa de acierto VDI, error por zona) en direcciones, variante y velocidad retenidas. El modelo final se elige por validación, nunca por prueba. Se publica también lo que pierde.

### F5. Confort y web (semanas 7-9)
- K(θ) por punto × rosa de vientos → probabilidades de excedencia → NEN 8100 (A-E, más peligro a 15 m/s) y Lawson; mapa de discrepancias entre los dos criterios.
- Web v1 ampliada: MapLibre con teselas OSM, selector de dirección y altura, panel con velocidad, dirección, K, I (marcada como estimación RANS) y clase de confort. **Aceptación:** funciona sin servidor en móvil y escritorio, inferencia < 50 ms por punto, modelo < 2 MB. Vercel solo con la aprobación de Hermann.

### F6. Cierre (semanas 9-10)
Informe (métodos, validación, incertidumbre, limitaciones: neutralidad, sin árboles ni topografía, alturas LOD1, sin mediciones de campo), presentación, película (pipeline de v1).
**Extensiones (P1-C), si sobra tiempo:** LES del caso AIJ o de 1 dirección de Zona Tec para cuantificar el error de RANS; árboles porosos (P19-B); FNO 2D a nivel peatonal (eje ML de P2).

## 4. Presupuesto de cómputo en ESTA PC (Ryzen 5 5600X 6c/12t, 16 GB, RTX 3070 8 GB)
- **RAM:** snappyHexMesh es lo que más memoria pide (del orden de 1 a 2 GB por millón de celdas, más un pico en la fase de capas) [estimado]. simpleFoam con k-ε usa ~1 GB por millón de celdas [estimado]. Con 16 GB y Windows más los otros procesos, el techo seguro es de **~4 M de celdas**, y el objetivo es **~3 M**.
- **Malla objetivo [estimado]:** dominio de unos 2.0 × 1.4 × 0.4 km para H_max ~ 60-70 m (COST 732: 5H / 15H). Fondo de 8 a 16 m; zona central (campus) con celdas horizontales de 2 m y graduación vertical desde ~0.5 m; anillo exterior de 4 m. Total ~2.5 a 3.5 M.
- **Tiempo [estimado, a medir]:** simpleFoam en 6 procesos, ~3 M de celdas: 3 a 6 s por iteración, con 2000 a 3000 iteraciones → **3 a 5 h por caso**, más ~0.5 a 1 h de mallado. **38 casos ≈ 150 a 230 h de CPU ≈ 7 a 10 días continuos**, o unas 3 a 4 semanas solo de noches y fines de semana. Cabe en P1-C.
- Si solo hubiera ejecución en serie (sin MPI), el tiempo se multiplica por ~4 a 5. En ese caso se reduce a ~1.5 M de celdas y se pide a Hermann habilitar WSL2 o MS-MPI.
- **Plan recortado (adoptado el 28-sep, comunicado a Hermann):** un dominio circular por geometría (3 mallas en vez de 38); ~2-2.5 M de celdas justificadas con GCI; arranque en caliente desde la dirección vecina o desde la solución base (30-60 % menos iteraciones); velocidades extra reiniciadas desde la base (~500 iteraciones); ejecución 24/7 en prioridad baja. Estimación: AIJ 6-8 h + GCI ~6 h + 16 direcciones 35-40 h + velocidades ~2 h + variantes 20-25 h ≈ **70-80 h de reloj (3-4 días 24/7)** [estimado; se recalcula con el benchmark]. No sirve: simetría (la geometría no es simétrica) ni correr 2 casos a la vez (RAM y ancho de banda). Nube gratis: Colab/Kaggle solo para entrenar; Oracle Always Free (4 núcleos ARM, 24 GB) como opción de CFD no verificada.
- **Riesgo de CPU compartida:** el trabajo de `recaps` compite por la CPU. Las corridas largas se lanzan con prioridad BelowNormal y se registran los tiempos reales.
- **No hay otra máquina** (sin RTX 4090). Kaggle o Colab gratis quedan como desborde opcional para entrenamiento, nunca en la ruta crítica. OpenFOAM se queda local.
- **GPU:** entrenamiento con < 4 a 5 GB de VRAM (por ComfyUI y Ollama). La etapa C (autograd de segundo orden) es la más cara: se estima de 1 a 4 h por entrenamiento [estimado].
- **Disco:** ~0.3 GB por caso en el paso final, más ~0.1 GB de HDF5 → ~15 GB en E:. Los casos completos terminados se archivan comprimidos en D:.

## 5. Equipo de agentes (modelo elegido por tarea)
| Rol | Modelo | Estado |
|---|---|---|
| Entorno OpenFOAM (instalación sin administrador, benchmark, script WSL2) | sonnet | en curso (F1) |
| Geometría / SIG (OSM → STL, dominio, morfometría, SDF) | sonnet | en curso (F1) |
| Investigación de alturas (OSM, Overture, INEGI LiDAR, fuentes Tec) | sonnet | en curso (F1) |
| Clima (NOAA ISD → rosa, Weibull, excedencias) | sonnet | en curso (F1) |
| Investigación de viento (SMN, SIMA-NL, ERA5, estudios previos) | sonnet | en curso (F1) |
| ML (paquete PINN, DeepONet, métricas, prueba de humo) | sonnet | en curso (F1) |
| CFD: caso AIJ A + plantilla Zona Tec | opus | F1, cuando OpenFOAM esté listo |
| Revisión física y metodológica (CFD, pérdidas, métricas) | opus | después de cada entregable crítico |
| Evaluador independiente (casos sellados) | opus | F4 |
| Confort + web | sonnet | F5 |
| Tareas mecánicas (conversiones, archivado) | haiku | según se necesite |

## 6. Riesgos principales y mitigación
| Riesgo | Prob. | Mitigación |
|---|---|---|
| OpenFOAM en Windows sin administrador no corre en paralelo | media | benchmark hoy; script WSL2 listo para Hermann; mallas más chicas |
| RAM de 16 GB limita la malla | alta | objetivo de 3 M de celdas, graduación anisótropa, anillo exterior simplificado; si aparece la máquina de 32 GB, se refina |
| Alturas inciertas (LOD1 estimado) | alta | investigación multifuente, lista de campo, sensibilidad ± 1 piso en z0 y d, y 1 corrida de sensibilidad |
| Perfil de entrada no homogéneo (T9) | media | función de pared atmosférica con z0 y prueba en dominio vacío antes de la campaña |
| El residuo RANS desestabiliza la PINN | media | etapas, pesos adaptativos; si C falla, se reporta B |
| La PINN no le gana a la interpolación | media | se reporta con honestidad (como en v1); el valor agregado es la consulta continua en 3D y en direcciones no vistas |
| Sin mediciones de campo (P28-A) | cierta | AIJ + GCI + declaración explícita; si aparecen datos existentes (SIMA, Tec), validación cualitativa |
| CPU compartida con otros trabajos | media | prioridad baja, ejecución nocturna, bitácora de tiempos |
| Valle de Monterrey y estabilidad no neutra | cierta | rosa medida (P19-D), neutralidad declarada (P15-A) |

## 7. Registro de mediciones de cómputo (se llena con datos reales)
| Fecha | Qué | Resultado |
|---|---|---|
| — | benchmark simpleFoam de 1 M de celdas | pendiente (agente del entorno OpenFOAM) |

## 8. Cómo retomar
- `STATUS.md` en la raíz tiene el estado vivo: qué corre en segundo plano, con qué PID y en qué log.
- Las corridas CFD largas se lanzan desacopladas (`Start-Process`), escriben en `E:\PINN\logs\` y cada caso tiene su `Allrun` y un archivo `DONE`/`FAILED` al terminar.
