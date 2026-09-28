<div class="cover" markdown="1">

<p class="kicker">Proyecto PINN · Fase 1 · Interrogatorio de diseño</p>

# Viento urbano en Zona Tec con una PINN

<p class="subtitle">Preguntas que el equipo debe responder antes de construir nada: cada una trae opciones y la recomendación del líder técnico</p>

<div class="cover-meta" markdown="1">

**Para:** Hermann y equipo, Tecnológico de Monterrey

**Fecha:** 28 de septiembre de 2026

**Versión:** 1.0, en espera de respuestas

**Siguiente paso:** con las respuestas, un equipo de subagentes construye la PINN nueva (ver `PLAN-EQUIPO.md`)

</div>

<div class="prompt" markdown="1">

**Encargo original, literal:**
«Desarrolla una PINN que, al entrenarla con datos de varias simulaciones donde las geometrías urbanas y las velocidades de entrada del viento cambian, tomando en cuenta la Ley de potencia logarítmica relativa para capas límite atmosféricas y las leyes físicas más exactas, pueda predecir las características del viento en las coordenadas de mi interés. Mi objetivo es, usando la geometría urbana de Zona Tec, Tecnológico de Monterrey, pueda elegir un punto y saber las características del viento.»

</div>

<div class="howto" markdown="1">

**Cómo usar este documento.** Marquen una casilla ☐ por pregunta, o varias donde diga *(varias)*. Si aceptan la recomendación, basta con marcar la opción que dice **REC**. La página «Respuestas rápidas» describe cómo queda el proyecto si aceptan todas las recomendaciones. Lo que dice **[no verificado]** es una estimación o un dato que hay que confirmar antes de citarlo en el informe.

</div>

</div>

## Índice

1. Trampas conceptuales del encargo
2. Lo que dejó el proyecto anterior (v1)
3. Respuestas rápidas: el proyecto si se aceptan todas las recomendaciones
4. Preguntas (29), ordenadas de bloqueantes a finas
    - A. Bloqueantes: objetivo, curso, cómputo y equipo (P1–P7)
    - B. Entregable: «elijo un punto y sé el viento» (P8–P11)
    - C. Física y perfil de entrada de la capa límite (P12–P16)
    - D. Dominio y geometría de Zona Tec (P17–P19)
    - E. Generación de datos CFD (P20–P22)
    - F. Arquitectura y función de pérdida de la PINN (P23–P26)
    - G. Validación (P27–P28)
    - H. Reutilización del proyecto anterior (P29)
5. Hoja de respuestas
6. Referencias

## 1. Trampas conceptuales del encargo

Estas son las ideas del encargo que, tomadas al pie de la letra, llevan a un modelo que no se puede defender ante un profesor que sabe del tema. Ninguna invalida el proyecto; todas obligan a decidir algo.

<div class="trap" markdown="1">

**T1. «Ley de potencia logarítmica» son dos leyes distintas.**
La **ley de potencia** es empírica: $u(z) = u_{ref}\,(z/z_{ref})^{\alpha}$, con α entre 0.10 y 0.40 según la rugosidad del terreno. Es la que usan la ASCE 7 y el Manual de Diseño por Viento de la CFE (ASCE, 2022; CFE, 2020). La **ley logarítmica** sale de la teoría de semejanza de la capa superficial en condiciones neutras: $u(z) = \frac{u_*}{\kappa}\ln\frac{z-d}{z_0}$, con κ ≈ 0.40, velocidad de fricción $u_*$, longitud de rugosidad $z_0$ y altura de desplazamiento $d$ (Stull, 1988). El Eurocódigo EN 1991-1-4 usa la logarítmica (CEN, 2005). Las dos se pueden ajustar una a la otra dentro de un rango de alturas, pero no son la misma ley ni tienen el mismo sustento. **Para la CFD se usa la logarítmica**, con perfiles de k y ε consistentes con ella (Richards y Hoxey, 1993). La de potencia sirve para comparar con normas.

</div>

<div class="trap" markdown="1">

**T2. En una ciudad, la ley log solo vale lejos de los techos.**
Sobre un dosel urbano el perfil log se desplaza hacia arriba una altura $d$, que suele estar entre 0.5 y 0.8 veces la altura media de los edificios. $z_0$ y $d$ no se leen de una tabla: se estiman con métodos morfométricos a partir de la geometría (Macdonald et al., 1998; Grimmond y Oke, 1999), y el de Kanda et al. (2013) toma en cuenta la variabilidad de alturas. Además, por debajo de unas 2 a 5 veces la altura media de los edificios está la **subcapa de rugosidad**, donde el flujo depende de cada edificio y **la ley log no se cumple** (Roth, 2000; Oke et al., 2017). Justo ahí, a 1.75 m del suelo, es donde se pregunta por el viento peatonal. Conclusión: la ley log define el **viento que entra** al dominio (el terreno que está a barlovento). Dentro de Zona Tec, el viento lo calcula la CFD resolviendo los edificios.

</div>

<div class="trap" markdown="1">

**T3. Variar la velocidad de entrada casi no aporta información.**
Con flujo neutro y número de Reynolds alto (edificios de decenas de metros y viento de más de 1 m/s dan Re ≈ 10⁶–10⁷), el campo adimensional $\mathbf{u}/U_{ref}$ es prácticamente **independiente de Re**. Es el criterio clásico de independencia de Reynolds en túnel de viento (Snyder, 1981). Con funciones de pared, una simulación RANS también escala casi linealmente con $U_{ref}$. Entrenar con 3, 5 y 8 m/s le enseña a la red una multiplicación. **Lo que cambia el campo de verdad es la dirección del viento** (y, en menor medida, la rugosidad aguas arriba y la estabilidad térmica). Se recomienda variar la dirección y usar dos velocidades solo para comprobar la independencia (P5).

</div>

<div class="trap" markdown="1">

**T4. «Varias geometrías» contra «solo me importa Zona Tec».**
Un modelo que generalice a geometrías urbanas que no ha visto es un problema de investigación abierto: hace falta un codificador de geometría y cientos de simulaciones. Si el objetivo final es Zona Tec, la variación de geometría más útil son **variantes de Zona Tec** (con o sin una torre proyectada, por ejemplo). Eso cumple el encargo y responde a una pregunta real (P4).

</div>

<div class="trap" markdown="1">

**T5. «Las leyes físicas más exactas» no equivalen a Navier–Stokes completo dentro de una PINN.**
Las PINN que minimizan residuos de Navier–Stokes fallan con frecuencia a Re alto: el entrenamiento se desequilibra y la red converge a soluciones triviales o suavizadas (Wang et al., 2021; Krishnapriyan et al., 2021). Lo realista es esto: la **CFD** (RANS k-ε realizable o k-ω SST) lleva la física «exacta» y genera los datos, y la **PINN** usa esos datos más residuos físicos baratos y robustos: continuidad y, si se estabiliza, momento RANS con la viscosidad turbulenta que dio la CFD (Eivazi et al., 2022). Un LES sería más exacto que un RANS, pero cuesta de 10 a 100 veces más **[orden de magnitud, no verificado para este caso]**, y hacen falta decenas de casos.

</div>

<div class="trap" markdown="1">

**T6. Si ya tienes la CFD, ¿para qué la PINN?**
En una geometría y una dirección ya simuladas, la CFD es la respuesta. La red solo se justifica si hace algo que la CFD no hace: responder al instante en cualquier coordenada 3D y en direcciones o variantes **no simuladas**, dar un campo continuo y consistente con la física, y correr en el navegador. Esto hay que demostrarlo con validación sobre casos retenidos (P27). Si no, el profesor lo va a preguntar.

</div>

<div class="trap" markdown="1">

**T7. Las «características del viento» que pide el usuario no salen todas de una simulación estacionaria.**
Un RANS da velocidad media, dirección, presión y energía cinética turbulenta *k*. De ahí se obtiene la intensidad de turbulencia $I = \sqrt{2k/3}/U$ (si se supone turbulencia isótropa). Las ráfagas y el confort peatonal requieren además **estadística del clima local**: una rosa de vientos del SMN/CONAGUA o de NOAA. Los criterios de confort (Lawson; NEN 8100) son probabilidades de excedencia, no un número por simulación (Blocken et al., 2012).

</div>

<div class="trap" markdown="1">

**T8. Particularidades de Monterrey.**
(a) Monterrey está en un valle rodeado de sierras (Cerro de la Silla, Sierra Madre Oriental). El perfil log «de equilibrio sobre terreno plano» es una idealización, y la canalización orográfica puede cambiar la dirección local. (b) Por la altitud (~540 m **[no verificado]**), la densidad del aire es ~1.13 kg/m³, no 1.225. Eso afecta a la presión, no a la velocidad. (c) Las tardes calurosas dan una capa límite convectiva (inestable), no neutra. (d) Las NTC de viento de la CDMX **no rigen en Nuevo León**. Para Monterrey la referencia normativa es el Manual de Diseño por Viento de la CFE (más el reglamento municipal), y las NTC-CDMX sirven solo para comparar.

</div>

<div class="trap" markdown="1">

**T9. Las condiciones de frontera de la CFD y de la PINN tienen que coincidir.**
La CFD urbana usa **funciones de pared** con rugosidad; no resuelve la subcapa viscosa. Si la PINN impone no deslizamiento ($\mathbf{u}=0$) en las paredes, contradice a sus propios datos. Tampoco basta con fijar el perfil de entrada: si la rugosidad del suelo y la función de pared no son consistentes con $z_0$, el perfil log se deforma antes de llegar a los edificios. Es el problema de la homogeneidad horizontal (Blocken et al., 2007; Hargreaves y Wright, 2007).

</div>

## 2. Lo que dejó el proyecto anterior (v1)

Se revisaron el código, los datos, el informe de entrenamiento, la web y el historial de git de `D:\vscodeprojects\wind-pinn` (rama `deploy/vercel-pinn`, publicada en wind-pinn.vercel.app, y la rama `claude-oscar/validacion-sin-sensores`).

| Aspecto | Qué hizo v1 | Veredicto para v2 |
|---|---|---|
| Datos | LBM D2Q9 BGK en 2D, ciudad sintética de 480 × 240 m, dx = 2 m, flujo uniforme de 5 m/s, promediado en el tiempo (`sim/lbm.py`) | **Descartar como física.** $\nu_{ef}$ = 2.5 m²/s (el aire tiene 1.5×10⁻⁵), así que Re ≈ 40 con L = 20 m: flujo casi laminar, sin turbulencia y sin perfil de capa límite |
| Geometría | Rectángulos aleatorios con semilla fija; un edificio se sale del dominio (y1 = 248 m > Ly = 240 m) | Descartar. En v2 la geometría es la de Zona Tec |
| Ambigüedad 2D | El código trata (x, y) como planta, pero el commit de Oscar leyó y = 0 como «suelo sin fricción» | En v2 se trabaja en 3D y los ejes quedan documentados |
| PINN | MLP 6×64 tanh con 48 rasgos de Fourier; NS 2D estacionario con la misma ν; pérdida de datos (250 sensores), PDE y fronteras; Adam 8000 iteraciones, 18 min en CPU | **Reutilizar el esqueleto** (rasgos de Fourier, adimensionalización, bucle de entrenamiento), no la física |
| Resultado | Error L2 relativo en rapidez: PINN 0.317, interpolación 0.396, MLP sin física 0.375. **En presión la PINN pierde**: MAE de 10.7 Pa contra 5.7 Pa de la interpolación | Conservar la honestidad del informe. En v2 se reportan también las derrotas |
| Validación | Oscar excluyó de las métricas las celdas usadas como sensores | **Reutilizar el principio**, ampliado a direcciones y geometrías retenidas |
| Web | Inferencia de la red en JS puro, sin servidor; sonda al hacer clic; vistas PINN, simulación, error y sensores | **Reutilizar**: es justo el «elijo un punto». Hay que agregar el mapa real, la altura z y la dirección |
| Película | Pipeline Node + ffmpeg que calcula sus propias cifras (`video/`, `hechos.mjs` en la rama de Oscar) | Reutilizable para la presentación final |

<div class="pb"></div>

## 3. Respuestas rápidas: el proyecto si se aceptan todas las recomendaciones

<div class="quick" markdown="1">

**Qué es.** Un modelo de viento peatonal y tridimensional para Zona Tec. Se generan unas **40 simulaciones RANS 3D en OpenFOAM**: 16 direcciones sobre la geometría actual, 2 variantes de geometría a 8 direcciones y 2 velocidades extra para comprobar la independencia de Reynolds. La entrada es un perfil logarítmico de capa límite con $z_0$ y $d$ morfométricos. Con esos datos se entrena una **PINN paramétrica** $f(x, y, z, \theta, \text{variante}) \to (u, v, w, p, k)$ en unidades normalizadas por $U_{ref}$. La pérdida combina datos, continuidad y momento RANS con $\nu_t$ de la CFD, con pesos adaptativos.

**Qué entrega.** Una web (la de v1, ampliada) con el mapa de Zona Tec: se elige un punto y una altura, y se ven la velocidad y la dirección para cada dirección del viento, la intensidad de turbulencia, el factor de amplificación $K = U/U_{ref}$ y la **clase de confort NEN 8100**, calculada combinando K con la rosa de vientos del SMN/NOAA.

**Cómo se defiende.** (1) La CFD se valida con el caso de referencia AIJ antes de tocar Zona Tec. (2) Se hace un estudio de malla con GCI. (3) La PINN se evalúa en **direcciones y una variante que nunca vio**, frente a la interpolación y a la misma red sin física, con la tasa de acierto de VDI 3783-9. (4) Se comparan las razones de velocidad con una campaña de 10 a 15 puntos con anemómetro portátil en el campus.

**Calendario (8 semanas; con 4 semanas se recorta lo marcado con \*):**

| Semana | Trabajo |
|---|---|
| S1 | Respuestas a este documento. Geometría de Zona Tec (OSM y levantamiento de alturas). Rosa de vientos SMN/NOAA. Caso AIJ en OpenFOAM |
| S2 | Validación AIJ. Malla de Zona Tec. Estudio de malla con GCI en una dirección. $z_0$ y $d$ morfométricos |
| S3–S4 | Campaña de 40 corridas (por la noche, en CPU). Extracción de campos. Campaña de anemómetro\* |
| S4–S6 | PINN v1 (datos + continuidad), luego v2 (+RANS). Referencias de comparación. Retenciones. Variantes\* |
| S6–S7 | Posprocesado de confort. Web con mapa. Exportación del modelo al navegador |
| S8 | Informe, presentación y película (pipeline de v1) |

**Riesgos principales.** (1) La CFD en WSL2 tarda más de lo estimado. Mitigación: bajar a 8 direcciones y malla gruesa. (2) Las alturas de los edificios son inciertas. Mitigación: levantamiento y análisis de sensibilidad. (3) El residuo RANS vuelve inestable el entrenamiento. Mitigación: quedarse con continuidad y reportarlo. (4) La PINN no le gana a la interpolación en alguna métrica. Mitigación: reportarlo, como en v1. (5) La campaña de medición es ruidosa o el clima no coopera. Mitigación: comparar razones, no valores absolutos. (6) Las GPU y CPU no están en la PC de Hermann, que solo tiene una Intel UHD (P6).

</div>

<div class="pb"></div>

## 4. Preguntas

### A. Bloqueantes: objetivo, curso, cómputo y equipo

<div class="q" markdown="1">

### P1. ¿Cuál es la fecha de entrega y qué se entrega exactamente?

**Por qué importa.** Con 4 semanas no alcanza para validar la CFD, correr 40 casos y hacer una campaña de medición. Con 8 sí. El alcance entero depende de esta respuesta.

- [ ] **A.** Cuatro semanas o menos. Alcance mínimo: 8 direcciones, sin variantes, sin campaña de medición. Es defendible, pero menos ambicioso.
- [ ] **B.** Entre 5 y 8 semanas. Plan base de «Respuestas rápidas». **REC**
- [ ] **C.** Más de 8 semanas. Se pueden agregar LES en 1 o 2 direcciones para contrastar con RANS, o la generalización a geometrías.
- [ ] Entregables (varias): ☐ informe escrito ☐ presentación ☐ demo web ☐ código ☐ póster ☐ artículo ☐ video

<div class="rec" markdown="1">

**Recomendación: B, y además escriban la fecha exacta.** El calendario de 8 semanas está diseñado para recortar al plan A sin rehacer nada.

</div>

Fecha: ______________ Materia / grupo: ______________________________

</div>

<div class="q" markdown="1">

### P2. ¿Qué pesa más en la calificación?

**Por qué importa.** Un proyecto calificado por rigor físico prioriza la validación de la CFD. Uno calificado por ML prioriza la arquitectura y las comparaciones. Uno calificado por impacto prioriza la web y el confort.

- [ ] **A.** Rigor físico y metodológico: validación, incertidumbre, fuentes. **REC**
- [ ] **B.** Novedad en ML: arquitectura, operadores neuronales.
- [ ] **C.** Aplicación y comunicación: web, mapas, presentación.
- [ ] **D.** Hay rúbrica escrita: la comparten y se optimiza contra ella.

<div class="rec" markdown="1">

**Recomendación: D si existe la rúbrica; si no, A.** Es lo que un evaluador experto revisa primero, y en v1 fue justo lo débil (física laminar).

</div>

</div>

<div class="q" markdown="1">

### P3. ¿El profesor exige literalmente una PINN?

**Por qué importa.** «PINN» en sentido estricto (Raissi et al., 2019) es una red cuya pérdida contiene residuos de ecuaciones diferenciales. Para aprender de muchas simulaciones, los operadores neuronales (DeepONet, FNO) suelen dar mejor resultado (Lu et al., 2021a; Li et al., 2021), pero ya no serían «una PINN».

- [ ] **A.** PINN estricta: residuos de las PDE sin datos, o con muy pocos. Casi seguro que falla en flujo urbano a Re alto.
- [ ] **B.** PINN híbrida: datos de CFD más residuos físicos en la pérdida. Encaja con la definición de Raissi et al. (2019). **REC**
- [ ] **C.** Operador neuronal (DeepONet o FNO) con o sin pérdida física. Es más potente para generalizar, pero puede no contar como PINN.
- [ ] **D.** B como modelo principal y C como comparación.

<div class="rec" markdown="1">

**Recomendación: B (o D si sobra tiempo).** Cumple el nombre del encargo y es el marco estándar de *physics-informed machine learning* (Karniadakis et al., 2021).

</div>

</div>

<div class="q" markdown="1">

### P4. ¿Qué tanto debe generalizar el modelo en geometría?

**Por qué importa.** Es la trampa T4. El número de simulaciones y la arquitectura cambian un orden de magnitud entre una opción y otra.

- [ ] **A.** Solo Zona Tec actual. Lo único que varía es el viento. Es lo más sencillo, pero no cumple «varias geometrías».
- [ ] **B.** Zona Tec más 2 o 3 variantes realistas (una torre proyectada, un predio vacío, etc.). **REC**
- [ ] **C.** Geometrías arbitrarias: se entrena con decenas de ciudades sintéticas y Zona Tec queda como prueba ciega. Es un problema de investigación que requiere más de 200 casos.
- [ ] **D.** B, más un experimento pequeño de C en 2D como anexo.

<div class="rec" markdown="1">

**Recomendación: B.** Cumple el encargo con unas 40 corridas y responde a una pregunta útil: «¿qué pasa con el viento si se construye X?».

</div>

</div>

<div class="q" markdown="1">

### P5. ¿Qué parámetros del viento de entrada varían entre simulaciones?

**Por qué importa.** Es la trampa T3. El encargo dice «velocidades», pero con independencia de Reynolds la velocidad solo escala el campo, y la dirección es lo que lo transforma.

- [ ] **A.** Solo la velocidad, como dice el encargo. La red aprendería una multiplicación.
- [ ] **B.** 16 direcciones (cada 22.5°, igual que la rosa de vientos del SMN) a una velocidad, más 2 velocidades extra en 2 direcciones para demostrar la independencia de Re. **REC**
- [ ] **C.** B más $z_0$ aguas arriba como tercer parámetro (terreno abierto contra urbano). Suma unas 16 corridas.
- [ ] **D.** C más estabilidad térmica. Fuera de alcance con RANS neutro (ver P15).

<div class="rec" markdown="1">

**Recomendación: B.** Así se cumple el encargo («las velocidades cambian») y se demuestra por qué no importan tanto (Snyder, 1981), lo cual es un hallazgo defendible. La velocidad entra luego como escala: $\mathbf{u} = U_{ref}\,\hat{\mathbf{u}}(x,\theta)$.

</div>

</div>

<div class="q" markdown="1">

### P6. ¿Qué hardware hay, de quién es y dónde corre cada cosa?

**Por qué importa.** La PC donde se preparó este documento solo tiene una **Intel UHD Graphics**. La RTX 3070 y la RTX 4090 están en otro equipo. OpenFOAM corre en **CPU con MPI**, no en GPU, así que la GPU solo acelera el entrenamiento. Estimación: un RANS 3D de unos 5 millones de celdas con 8 núcleos tarda de 2 a 6 horas por caso y usa de 8 a 16 GB de RAM **[no verificado; se confirma con una corrida piloto]**.

- [ ] **A.** CFD en la CPU del equipo más potente (8 o más núcleos, 32 GB o más de RAM) con OpenFOAM en WSL2. Entrenamiento en la RTX 4090. **REC**
- [ ] **B.** Todo en la máquina de la RTX 3070 (8 GB de VRAM). Alcanza para la PINN; la CFD depende de su CPU.
- [ ] **C.** Clúster del Tec o nube. Más rápido, pero hay que tramitar el acceso.
- [ ] **D.** CFD en GPU con LBM (FluidX3D o XLB) en la 4090. Es rápido, pero LBM con capa límite y funciones de pared es menos estándar en ingeniería de viento (ver P20).

<div class="rec" markdown="1">

**Recomendación: A.** Por favor anoten el CPU (núcleos), la RAM y el disco libre de cada máquina, y quién la controla.

</div>

Máquina 1: ________________________ Máquina 2: ________________________

</div>

<div class="q" markdown="1">

### P7. ¿Quién está en el equipo y qué hace cada quien?

**Por qué importa.** El proyecto tiene cinco especialidades: SIG y geometría, CFD, ML, validación de campo, y web con redacción. Los subagentes de la fase 2 producen, pero las decisiones, las mediciones en campo y la defensa oral son humanas.

- [ ] **A.** Un dueño humano por especialidad. Los subagentes trabajan bajo cada uno. **REC**
- [ ] **B.** Hermann coordina todo y los compañeros revisan.
- [ ] **C.** Se reparte por entregable (informe, web, presentación) en vez de por especialidad.
- [ ] **D.** ¿Participa Oscar (claude-oscar), como en v1? ☐ sí ☐ no

<div class="rec" markdown="1">

**Recomendación: A.** Cada quien puede defender su parte en la presentación, y los subagentes tienen a quién preguntar.

</div>

Nombres y roles: _____________________________________________________________

</div>

### B. Entregable: «elijo un punto y sé el viento»

<div class="q" markdown="1">

### P8. ¿Qué características del viento debe devolver el punto? *(varias)*

**Por qué importa.** Es la trampa T7. Cada salida tiene un origen distinto y un nivel de confianza distinto.

- [ ] **A.** Velocidad media y dirección, en m/s y grados, para una dirección de entrada dada. Sale directo de la CFD. **REC**
- [ ] **B.** Factor de amplificación $K = U_{local}/U_{ref}$ para las 16 direcciones. **REC**
- [ ] **C.** Intensidad de turbulencia $I=\sqrt{2k/3}/U$. **REC**, marcada como estimación RANS
- [ ] **D.** Presión o coeficiente $C_p$. Tiene sentido en fachadas, no en la calle.
- [ ] **E.** Clase de confort peatonal (P10). **REC**
- [ ] **F.** Ráfaga estimada ($U + g\,\sigma_u$, con g ≈ 3). Es aproximada.

<div class="rec" markdown="1">

**Recomendación: A + B + C + E.** Son las salidas que un RANS da con fiabilidad (Blocken, 2015), más la que le importa a un peatón.

</div>

</div>

<div class="q" markdown="1">

### P9. ¿En qué alturas se puede preguntar?

**Por qué importa.** El encargo dice «coordenadas». Si solo interesa el nivel peatonal, un modelo 2D sobre un corte a 1.75 m es mucho más fácil. Si interesan azoteas (por ejemplo, para turbinas eólicas urbanas), hace falta 3D.

- [ ] **A.** Solo nivel peatonal (z = 1.75 m, la altura que usa la guía AIJ): modelo 2D sobre el corte de la CFD 3D.
- [ ] **B.** 3D desde el suelo hasta unas 2 veces la altura del edificio más alto; validación y confort a nivel peatonal. **REC**
- [ ] **C.** Nivel peatonal más azoteas únicamente.

<div class="rec" markdown="1">

**Recomendación: B.** Una red con entrada (x, y, z) cuesta casi lo mismo que una 2D, y cumple «las coordenadas de mi interés».

</div>

</div>

<div class="q" markdown="1">

### P10. ¿Qué criterio de confort peatonal se usa?

**Por qué importa.** Sin un criterio, «las características del viento» no dicen si un lugar es agradable o peligroso. Los criterios combinan K con la probabilidad anual de viento de cada dirección (Janssen et al., 2013).

- [ ] **A.** Lawson (LDDC): umbrales por actividad (sentarse, estar de pie, caminar) (Lawson, 2001).
- [ ] **B.** NEN 8100: probabilidad de superar 5 m/s, con clases A a E, más un criterio de peligro con 15 m/s (NEN, 2006). **REC**
- [ ] **C.** Los dos, para comparar.
- [ ] **D.** Ninguno; solo velocidades.

<div class="rec" markdown="1">

**Recomendación: B (C si hay tiempo).** Es una norma publicada, se aplicó a un campus universitario en Blocken et al. (2012) y exige justo la combinación de CFD y clima que da sentido al modelo.

</div>

</div>

<div class="q" markdown="1">

### P11. ¿Cómo se ve el entregable interactivo?

**Por qué importa.** La web de v1 ya hace la sonda de «toco un punto y la red responde» en el navegador. Reutilizarla ahorra una semana.

- [ ] **A.** La web v1 ampliada: mapa real de Zona Tec (MapLibre con teselas OSM), selector de dirección y altura, panel con K, rosa de vientos y clase de confort. Se publica en Vercel. **REC**
- [ ] **B.** Cuaderno de Python o Streamlit. Es más rápido de hacer, pero no queda publicado.
- [ ] **C.** Solo figuras en el informe.

<div class="rec" markdown="1">

**Recomendación: A.** Es una red pequeña (un MLP de menos de 1 MB) y corre en JS como en v1. No necesita servidor.

</div>

</div>

### C. Física y perfil de entrada de la capa límite

<div class="q" markdown="1">

### P12. ¿Qué perfil de capa límite entra al dominio?

**Por qué importa.** Es la trampa T1. Además, el perfil de entrada tiene que ser consistente con la rugosidad del suelo del dominio, o se deforma antes de llegar a los edificios (T9).

- [ ] **A.** Ley de potencia $u = u_{ref}(z/z_{ref})^\alpha$ con α de la CFE según la categoría de terreno. Es fácil, pero no tiene perfiles de k y ε consistentes.
- [ ] **B.** Ley log neutra con $u_*$ y $z_0$, más k y ε de Richards y Hoxey (1993) (`atmBoundaryLayerInlet` de OpenFOAM) y rugosidad del suelo consistente (Richards y Norris, 2011). **REC**
- [ ] **C.** B con $d$ distinta de cero, para representar el terreno urbano a barlovento como un dosel desplazado.
- [ ] **D.** Perfil de un modelo de mesoescala (WRF). Es lo más realista para Monterrey, pero está fuera de alcance.

<div class="rec" markdown="1">

**Recomendación: B (C si el terreno a barlovento es urbano denso).** Es la práctica recomendada por COST 732 y AIJ (Franke et al., 2007; Tominaga et al., 2008). La ley de potencia se usa solo para comparar con la CFE en el informe.

</div>

</div>

<div class="q" markdown="1">

### P13. ¿Cómo se obtienen $z_0$ y $d$?

**Por qué importa.** Es la trampa T2. Con un $z_0$ mal elegido, la velocidad a nivel peatonal cambia fácilmente entre un 20 % y un 30 % **[orden de magnitud, no verificado para este sitio]**.

- [ ] **A.** Tablas: Davenport y Wieringa (1993), o la categoría IV del EN 1991-1-4 ($z_0$ = 1.0 m).
- [ ] **B.** Método morfométrico de Macdonald et al. (1998) con las alturas y áreas de los edificios a barlovento. **REC**
- [ ] **C.** Kanda et al. (2013), que corrige por variabilidad de alturas. Es mejor cuando hay torres dispersas.
- [ ] **D.** Ajuste a un perfil medido. No hay torre de medición conocida **[no verificado]**.

<div class="rec" markdown="1">

**Recomendación: B, con A como control y C como sensibilidad.** Así el valor sale de la geometría real, se puede auditar y se reporta como un rango, no como un número mágico (Grimmond y Oke, 1999).

</div>

</div>

<div class="q" markdown="1">

### P14. ¿Qué es exactamente la «velocidad de entrada» $U_{ref}$?

**Por qué importa.** Para que el modelo se combine con datos reales, la referencia tiene que ser la misma que miden las estaciones: 10 m de altura en terreno abierto, según la norma de la OMM. Las estaciones del aeropuerto y las EMA del SMN miden ahí, no en Zona Tec.

- [ ] **A.** $U_{10}$ en terreno abierto (aeropuerto), que se traslada a la entrada del dominio con un modelo de dos capas de rugosidad. **REC**
- [ ] **B.** Velocidad regional de la CFE (a 10 m, categoría 2). Sirve para diseño estructural con periodos de retorno, no para confort.
- [ ] **C.** Velocidad en lo alto del dominio. Es cómoda para la CFD, pero no conecta con datos.

<div class="rec" markdown="1">

**Recomendación: A.** Es la cadena que usan NEN 8100 y Blocken et al. (2012): del clima medido en el aeropuerto al viento a 1.75 m en el sitio.

</div>

Estación a usar: ☐ SMN/CONAGUA (EMA) ☐ NOAA ISD, aeropuerto de Monterrey **[identificador por verificar]** ☐ otra: ________

</div>

<div class="q" markdown="1">

### P15. ¿Se considera la estabilidad térmica?

**Por qué importa.** La ley log solo vale en condiciones neutras. En Monterrey, las tardes calurosas dan una capa convectiva (T8c). La teoría de Monin–Obukhov corrige el perfil, pero complica la CFD y multiplica los casos.

- [ ] **A.** Solo neutra. Se declara como limitación. Es la práctica estándar en ingeniería de viento peatonal. **REC**
- [ ] **B.** Neutra más una corrección de Monin–Obukhov en el perfil de entrada para 2 casos (estable e inestable).
- [ ] **C.** Flotabilidad completa en la CFD (`buoyantSimpleFoam`).

<div class="rec" markdown="1">

**Recomendación: A.** Los criterios de confort se definen para viento fuerte, que tiende a condiciones casi neutras (Stull, 1988).

</div>

</div>

<div class="q" markdown="1">

### P16. ¿Qué modelo de turbulencia genera los datos?

**Por qué importa.** Es la «física más exacta» que se puede pagar (T5). RANS subestima la turbulencia en las estelas y sobrestima las zonas de recirculación; LES es mejor, pero cuesta mucho más (Blocken, 2015; Tominaga et al., 2008).

- [ ] **A.** RANS k-ε estándar (Launder y Spalding, 1974). Es robusto, pero sobreproduce k en los puntos de estancamiento.
- [ ] **B.** RANS k-ε realizable o k-ω SST (Menter, 1994), estacionario. **REC**
- [ ] **C.** LES, en OpenFOAM (`pimpleFoam`) o con LBM en GPU. Es más fiel y da ráfagas, pero no alcanza para 40 casos.
- [ ] **D.** Laminar, como en v1. Hay que rechazarlo: Re real ~10⁷.

<div class="rec" markdown="1">

**Recomendación: B.** Es el estándar de las guías AIJ y COST 732 para viento peatonal. Si sobra tiempo, 1 o 2 casos LES sirven para cuantificar el error de RANS.

</div>

</div>

### D. Dominio y geometría de Zona Tec

<div class="q" markdown="1">

### P17. ¿Qué área es la «Zona Tec» del proyecto?

**Por qué importa.** El tamaño del dominio y de la malla, y por lo tanto el tiempo de cómputo, se deciden aquí. La guía COST 732 pide dejar unas 5H de distancia a la entrada, a los lados y arriba, y 15H a la salida, donde H es la altura del edificio más alto, y un bloqueo menor al 3 % (Franke et al., 2007).

- [ ] **A.** Solo el campus Monterrey.
- [ ] **B.** El campus y el polígono Distrito Tec, con los edificios explícitos en la zona de interés y un anillo de 1 o 2 manzanas alrededor. **REC**
- [ ] **C.** Un radio de 1.5 km o más alrededor del campus. La malla crece mucho.

<div class="rec" markdown="1">

**Recomendación: B.** Incluye las torres cercanas que dominan el viento en el campus y mantiene la malla en unos 5 a 10 millones de celdas **[estimación]**. Por favor dibujen el polígono en un mapa y adjúntenlo.

</div>

</div>

<div class="q" markdown="1">

### P18. ¿De dónde salen las huellas y las alturas de los edificios?

**Por qué importa.** Las huellas de OpenStreetMap suelen estar bien. Las alturas (`height`, `building:levels`) casi nunca vienen completas **[cobertura en Zona Tec no verificada]**. Un error de altura en una torre cambia el viento de toda su estela.

- [ ] **A.** Huellas de OSM y altura = pisos × 3 m, con los pisos contados en campo o en fotos (LOD1). **REC**
- [ ] **B.** A más un modelo de superficie LiDAR de INEGI, si existe cobertura para Monterrey **[no verificado]**.
- [ ] **C.** Alturas de conjuntos globales (Google Open Buildings 2.5D o Microsoft Building Footprints) **[cobertura y precisión no verificadas]**.
- [ ] **D.** Planos oficiales del campus, pidiéndolos a Infraestructura del Tec.

<div class="rec" markdown="1">

**Recomendación: A, con D si se consigue y B o C como control.** Es trazable y se puede citar (OpenStreetMap contributors). La guía AIJ considera suficiente LOD1 para viento peatonal (Tominaga et al., 2008).

</div>

</div>

<div class="q" markdown="1">

### P19. ¿Qué más va en el dominio además de los edificios? *(varias)*

**Por qué importa.** El campus tiene mucha vegetación, y Monterrey está rodeada de montañas (T8a). Los árboles reducen de manera importante el viento peatonal, y omitirlos lo sobrestima.

- [ ] **A.** Solo edificios sobre terreno plano. Se declara como limitación. **REC para la base**
- [ ] **B.** Árboles como medio poroso con fuerza de arrastre (densidad de área foliar). Es más fiel, pero hay que levantar el arbolado.
- [ ] **C.** Topografía local con el Continuo de Elevaciones Mexicano de INEGI. El desnivel dentro del dominio es pequeño **[no verificado]**.
- [ ] **D.** El efecto del valle, vía la rosa de vientos medida (no en la CFD). **REC**

<div class="rec" markdown="1">

**Recomendación: A + D, y B como extensión.** La rosa medida ya incorpora la canalización orográfica, y la vegetación se puede agregar como variante.

</div>

</div>

### E. Generación de datos CFD

<div class="q" markdown="1">

### P20. ¿Con qué software se simula?

**Por qué importa.** Define la reproducibilidad, la curva de aprendizaje y si el trabajo se puede citar.

- [ ] **A.** OpenFOAM (`simpleFoam` y `snappyHexMesh`) en WSL2. Es libre, es el estándar académico y tiene `atmBoundaryLayerInlet`. **REC**
- [ ] **B.** FluidX3D (LBM en GPU). Es muy rápido en una 4090, pero su licencia es no comercial y la capa límite con funciones de pared es menos estándar **[no verificado para ABL]**.
- [ ] **C.** Ansys Fluent con licencia académica. Es cómodo, pero la versión Student limita el tamaño de malla **[límite no verificado]**.
- [ ] **D.** Reutilizar el LBM 2D de v1. Hay que rechazarlo (laminar, 2D).

<div class="rec" markdown="1">

**Recomendación: A.** Toda la cadena queda en scripts y con documentación oficial citable (OpenCFD, 2024).

</div>

</div>

<div class="q" markdown="1">

### P21. ¿Cuántas simulaciones y con qué diseño?

**Por qué importa.** Los datos son el cuello de botella: cada corrida cuesta horas de CPU (P6).

- [ ] **A.** 8 direcciones × 1 geometría = 8 corridas. Es el mínimo.
- [ ] **B.** 16 direcciones en la geometría actual + 2 variantes × 8 direcciones + 2 velocidades × 2 direcciones ≈ **36–40 corridas**. **REC**
- [ ] **C.** Más de 100 corridas con muestreo por hipercubo latino en dirección, $z_0$ y geometría.

<div class="rec" markdown="1">

**Recomendación: B.** Con unas 4 horas por corrida son ~160 horas de CPU, unas 2 semanas de noches **[estimación]**. Las direcciones intermedias sirven de prueba.

</div>

</div>

<div class="q" markdown="1">

### P22. ¿Cómo se demuestra que la CFD es confiable?

**Por qué importa.** Si la CFD está mal, la PINN aprende un error con mucha precisión. La guía de COST 732 y el estándar VDI 3783-9 piden verificación (malla) y validación (datos experimentales).

- [ ] **A.** Nada; se confía en la CFD. Un evaluador lo va a rechazar.
- [ ] **B.** Estudio de malla con 3 mallas y GCI (Celik et al., 2008) en 1 dirección. **REC**
- [ ] **C.** B más la reproducción de un caso de referencia con datos de túnel: AIJ Case A (edificio aislado 1:1:2) o CEDVAL (Universidad de Hamburgo). **REC**
- [ ] **D.** C más la comparación con la campaña de campo (P28).

<div class="rec" markdown="1">

**Recomendación: C (D si hay campaña).** Validar la cadena en un caso con datos publicados antes de aplicarla a Zona Tec es la práctica estándar (Franke et al., 2007; Tominaga et al., 2008).

</div>

</div>

### F. Arquitectura y función de pérdida de la PINN

<div class="q" markdown="1">

### P23. ¿Qué física va en la pérdida?

**Por qué importa.** Es la trampa T5. Más ecuaciones no siempre dan un mejor modelo: los residuos de NS a Re alto desequilibran el gradiente (Wang et al., 2021).

- [ ] **A.** Solo datos. Es un sustituto puro; sirve como referencia de comparación obligatoria.
- [ ] **B.** Datos + continuidad $\nabla\cdot\mathbf{u}=0$. Es barata y robusta, y ya garantiza conservación de masa.
- [ ] **C.** Datos + continuidad + momento RANS, con $\nu_t$ como salida supervisada con la $\nu_t$ de la CFD. **REC**
- [ ] **D.** C más las ecuaciones de transporte de k y ε. Son rígidas, y es poco probable que converjan en el plazo.

<div class="rec" markdown="1">

**Recomendación: C, construida por etapas (primero B, luego C).** Eivazi et al. (2022) muestran PINN con RANS. Tener $\nu_t$ de la CFD evita cerrar la turbulencia dentro de la red. Si C no estabiliza, B es un resultado válido.

</div>

</div>

<div class="q" markdown="1">

### P24. ¿Qué condiciones de frontera impone la PINN?

**Por qué importa.** Es la trampa T9. El error de v1 sería repetir el no deslizamiento con datos generados con funciones de pared.

- [ ] **A.** No deslizamiento $\mathbf{u}=0$ en las paredes. Es inconsistente con la CFD de ingeniería de viento.
- [ ] **B.** Impermeabilidad ($\mathbf{u}\cdot\mathbf{n}=0$) en las paredes, datos de la CFD en la primera capa de celdas y perfil de entrada como condición blanda. **REC**
- [ ] **C.** Ninguna explícita; la red aprende la geometría de los datos más la distancia a la pared como entrada.

<div class="rec" markdown="1">

**Recomendación: B.** Es consistente con cómo se generaron los datos (Blocken et al., 2007).

</div>

</div>

<div class="q" markdown="1">

### P25. ¿Qué arquitectura, y cómo «ve» la red la geometría y el viento?

**Por qué importa.** Una red que recibe solo (x, y, z) no sabe dónde hay edificios. Si P4 = B, la geometría se codifica con pocas variantes; si P4 = C, hace falta un codificador.

- [ ] **A.** MLP con rasgos de Fourier (como v1; Tancik et al., 2020). Entradas: (x, y, z), $(\sin\theta,\cos\theta)$, identificador de variante, y **distancia con signo (SDF)** a los edificios más la altura local. **REC si P4 = A o B**
- [ ] **B.** DeepONet: una rama codifica geometría y dirección (mapa de alturas y CNN), y el tronco recibe (x, y, z) (Lu et al., 2021a). **REC si P4 = C**
- [ ] **C.** FNO o U-Net sobre rejillas 2D a nivel peatonal (Li et al., 2021). Es muy eficaz, pero no es una PINN en sentido estricto y no da 3D continuo.
- [ ] **D.** Red de grafos sobre la malla de la CFD. Es potente, pero es otra especialidad.

<div class="rec" markdown="1">

**Recomendación: A.** Reutiliza el código de v1, la SDF le da a la red la noción de pared (Park et al., 2019), y el seno y coseno del ángulo evitan el salto entre 0° y 360°.

</div>

</div>

<div class="q" markdown="1">

### P26. ¿Con qué herramienta y estrategia de entrenamiento?

**Por qué importa.** Con los pesos fijos de v1 (datos 10, PDE 1, fronteras 5) el equilibrio se ajustó a mano. Con más términos, eso no escala.

- [ ] **A.** PyTorch puro (el código de v1 extendido), con pesos adaptativos (Wang et al., 2021) y Adam seguido de L-BFGS. **REC**
- [ ] **B.** DeepXDE (Lu et al., 2021b). Es cómodo para PDE, pero menos flexible con datos 3D masivos.
- [ ] **C.** NVIDIA PhysicsNeMo (antes Modulus). Es potente, pero en Windows requiere Docker o WSL, y tiene una curva de aprendizaje alta.

<div class="rec" markdown="1">

**Recomendación: A.** Ya funciona en la máquina de Hermann, y la exportación a JS de v1 sigue sirviendo.

</div>

</div>

### G. Validación

<div class="q" markdown="1">

### P27. ¿Contra qué se mide el modelo?

**Por qué importa.** Es la trampa T6. En v1 los puntos de prueba estaban en el mismo campo que los datos de entrenamiento. En v2 la prueba tiene que ser una **extrapolación honesta**.

- [ ] **A.** Puntos aleatorios retenidos del mismo campo. Es débil y equivale a interpolar.
- [ ] **B.** Direcciones retenidas (por ejemplo, 4 de 16 nunca vistas). **REC**
- [ ] **C.** Una variante de geometría retenida. **REC**
- [ ] **D.** Una velocidad retenida (comprueba la independencia de Re). **REC**
- [ ] Métricas (varias): ☐ L2 relativo ☐ MAE de K ☐ tasa de acierto VDI 3783-9 ☐ error por zona (esquinas, estelas, cañones)
- [ ] Referencias de comparación (varias): ☐ interpolación ☐ la misma red sin física ☐ la dirección simulada más cercana

<div class="rec" markdown="1">

**Recomendación: B + C + D, con todas las métricas y todas las referencias.** La tasa de acierto es la métrica estándar de evaluación de modelos de viento urbano (VDI, 2017), y comparar contra otros métodos evita presumir sin sustento.

</div>

</div>

<div class="q" markdown="1">

### P28. ¿Habrá mediciones reales?

**Por qué importa.** Sin ninguna medición, todo es «un modelo de un modelo». Una campaña pequeña cuesta poco y da mucha credibilidad. Comparar **razones** (sitio contra referencia) cancela la variación del viento de fondo.

- [ ] **A.** Ninguna; solo climatología SMN/NOAA para la rosa de vientos.
- [ ] **B.** A más una campaña con anemómetros portátiles en 10 a 15 puntos del campus, con un punto de referencia en azotea o abierto, en 2 o 3 días de viento. **REC**
- [ ] **C.** Túnel de viento con maqueta, si el Tec tiene uno disponible **[no verificado]**.
- [ ] **D.** Estación meteorológica del campus, si existe y publica datos **[no verificado]**.

<div class="rec" markdown="1">

**Recomendación: B (y D si existe).** Es el único contacto con la realidad que cabe en el plazo. Se reporta como validación cualitativa y semicuantitativa, no como verdad absoluta.

</div>

</div>

### H. Reutilización del proyecto anterior

<div class="q" markdown="1">

### P29. ¿Qué se hace con v1?

**Por qué importa.** v1 está en Vercel y tiene una película. Borrarlo pierde trabajo que funciona; mezclarlo confunde lo sintético con lo real.

- [ ] **A.** Un repositorio nuevo; v1 queda archivado.
- [ ] **B.** El mismo repositorio, con carpeta `v2/`. v1 queda como «prueba de concepto 2D» en la narrativa: primero se demostró el método y después se escaló a física real. Se reutilizan la web, la exportación a JS, la honestidad de las métricas y la película. **REC**
- [ ] **C.** Reemplazar v1 en su lugar.

<div class="rec" markdown="1">

**Recomendación: B.** Cuenta una historia de progreso y conserva el historial de git, incluidas las correcciones de Oscar.

</div>

</div>

<div class="pb"></div>

## 5. Hoja de respuestas

Marquen la letra elegida; entre corchetes está la recomendación.

| # | Tema | Respuesta | # | Tema | Respuesta |
|---|---|---|---|---|---|
| P1 | Plazo | A B C [B] | P16 | Turbulencia | A B C D [B] |
| P2 | Calificación | A B C D [D/A] | P17 | Área | A B C [B] |
| P3 | ¿PINN estricta? | A B C D [B] | P18 | Alturas | A B C D [A] |
| P4 | Geometrías | A B C D [B] | P19 | Extras | A B C D [A+D] |
| P5 | Parámetros de entrada | A B C D [B] | P20 | Software CFD | A B C D [A] |
| P6 | Hardware | A B C D [A] | P21 | Número de corridas | A B C [B] |
| P7 | Equipo | A B C D [A] | P22 | Confianza en la CFD | A B C D [C] |
| P8 | Salidas | A B C D E F [A+B+C+E] | P23 | Física en la pérdida | A B C D [C] |
| P9 | Alturas de consulta | A B C [B] | P24 | Fronteras | A B C [B] |
| P10 | Confort | A B C D [B] | P25 | Arquitectura | A B C D [A] |
| P11 | Interfaz | A B C [A] | P26 | Herramienta | A B C [A] |
| P12 | Perfil de entrada | A B C D [B] | P27 | Validación | A B C D [B+C+D] |
| P13 | $z_0$ y $d$ | A B C D [B] | P28 | Mediciones | A B C D [B] |
| P14 | $U_{ref}$ | A B C [A] | P29 | v1 | A B C [B] |
| P15 | Estabilidad | A B C [A] | | | |

Comentarios generales:

<div class="lines"></div>

<div class="pb"></div>

## 6. Referencias

Solo fuentes primarias, normas, documentación oficial y datos institucionales. Lo marcado **[no verificado]** debe confirmarse (edición, año o URL) antes de citarlo en el informe.

<div class="refs" markdown="1">

American Society of Civil Engineers. (2022). *Minimum design loads and associated criteria for buildings and other structures* (ASCE/SEI 7-22). ASCE.

Blocken, B. (2015). Computational fluid dynamics for urban physics: Importance, scales, possibilities, limitations and ten tips and tricks towards accurate and reliable simulations. *Building and Environment, 91*, 219–245. https://doi.org/10.1016/j.buildenv.2015.02.015

Blocken, B., Janssen, W. D., & van Hooff, T. (2012). CFD simulation for pedestrian wind comfort and wind safety in urban areas: General decision framework and case study for the Eindhoven University campus. *Environmental Modelling & Software, 30*, 15–34. https://doi.org/10.1016/j.envsoft.2011.11.009

Blocken, B., Stathopoulos, T., & Carmeliet, J. (2007). CFD simulation of the atmospheric boundary layer: Wall function problems. *Atmospheric Environment, 41*(2), 238–252. https://doi.org/10.1016/j.atmosenv.2006.08.019

Celik, I. B., Ghia, U., Roache, P. J., Freitas, C. J., Coleman, H., & Raad, P. E. (2008). Procedure for estimation and reporting of uncertainty due to discretization in CFD applications. *Journal of Fluids Engineering, 130*(7), 078001. https://doi.org/10.1115/1.2960953

Comisión Federal de Electricidad. (2020). *Manual de diseño de obras civiles: Diseño por viento*. CFE / INEEL. **[edición y año a verificar]**

Comité Européen de Normalisation. (2005). *EN 1991-1-4: Eurocode 1: Actions on structures – Part 1-4: General actions – Wind actions*. CEN.

Eivazi, H., Tahani, M., Schlatter, P., & Vinuesa, R. (2022). Physics-informed neural networks for solving Reynolds-averaged Navier–Stokes equations. *Physics of Fluids, 34*(7), 075117. https://doi.org/10.1063/5.0095270

Franke, J., Hellsten, A., Schlünzen, H., & Carissimo, B. (Eds.). (2007). *Best practice guideline for the CFD simulation of flows in the urban environment* (COST Action 732). University of Hamburg, Meteorological Institute.

Gobierno de la Ciudad de México. (2017). *Normas técnicas complementarias para diseño por viento*. Gaceta Oficial de la Ciudad de México. **[edición vigente a verificar; solo de referencia, no aplica en Nuevo León]**

Grimmond, C. S. B., & Oke, T. R. (1999). Aerodynamic properties of urban areas derived from analysis of surface form. *Journal of Applied Meteorology, 38*(9), 1262–1292. https://doi.org/10.1175/1520-0450(1999)038<1262:APOUAD>2.0.CO;2

Hargreaves, D. M., & Wright, N. G. (2007). On the use of the k–ε model in commercial CFD software to model the neutral atmospheric boundary layer. *Journal of Wind Engineering and Industrial Aerodynamics, 95*(5), 355–369. https://doi.org/10.1016/j.jweia.2006.08.002

Instituto Nacional de Estadística y Geografía. (s. f.). *Continuo de Elevaciones Mexicano (CEM)* y *Modelos digitales de elevación LiDAR*. INEGI. https://www.inegi.org.mx **[cobertura LiDAR de Monterrey no verificada]**

Janssen, W. D., Blocken, B., & van Hooff, T. (2013). Pedestrian wind comfort around buildings: Comparison of wind comfort criteria based on whole-flow field data for a complex case study. *Building and Environment, 59*, 547–562. https://doi.org/10.1016/j.buildenv.2012.10.012

Kanda, M., Inagaki, A., Miyamoto, T., Gryschka, M., & Raasch, S. (2013). A new aerodynamic parametrization for real urban surfaces. *Boundary-Layer Meteorology, 148*(2), 357–377. https://doi.org/10.1007/s10546-013-9818-x

Karniadakis, G. E., Kevrekidis, I. G., Lu, L., Perdikaris, P., Wang, S., & Yang, L. (2021). Physics-informed machine learning. *Nature Reviews Physics, 3*(6), 422–440. https://doi.org/10.1038/s42254-021-00314-5

Krishnapriyan, A., Gholami, A., Zhe, S., Kirby, R., & Mahoney, M. W. (2021). Characterizing possible failure modes in physics-informed neural networks. *Advances in Neural Information Processing Systems, 34*, 26548–26560.

Launder, B. E., & Spalding, D. B. (1974). The numerical computation of turbulent flows. *Computer Methods in Applied Mechanics and Engineering, 3*(2), 269–289. https://doi.org/10.1016/0045-7825(74)90029-2

Lawson, T. V. (2001). *Building aerodynamics*. Imperial College Press.

Li, Z., Kovachki, N., Azizzadenesheli, K., Liu, B., Bhattacharya, K., Stuart, A., & Anandkumar, A. (2021). Fourier neural operator for parametric partial differential equations. *International Conference on Learning Representations (ICLR 2021)*.

Lu, L., Jin, P., Pang, G., Zhang, Z., & Karniadakis, G. E. (2021a). Learning nonlinear operators via DeepONet based on the universal approximation theorem of operators. *Nature Machine Intelligence, 3*(3), 218–229. https://doi.org/10.1038/s42256-021-00302-5

Lu, L., Meng, X., Mao, Z., & Karniadakis, G. E. (2021b). DeepXDE: A deep learning library for solving differential equations. *SIAM Review, 63*(1), 208–228. https://doi.org/10.1137/19M1274067

Macdonald, R. W., Griffiths, R. F., & Hall, D. J. (1998). An improved method for the estimation of surface roughness of obstacle arrays. *Atmospheric Environment, 32*(11), 1857–1864. https://doi.org/10.1016/S1352-2310(97)00403-2

Menter, F. R. (1994). Two-equation eddy-viscosity turbulence models for engineering applications. *AIAA Journal, 32*(8), 1598–1605. https://doi.org/10.2514/3.12149

NEN. (2006). *NEN 8100: Windhinder en windgevaar in de gebouwde omgeving* [Wind comfort and wind danger in the built environment]. Nederlands Normalisatie-instituut.

NOAA National Centers for Environmental Information. (s. f.). *Integrated Surface Database (ISD)*. https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database **[estación de Monterrey por verificar]**

NVIDIA. (s. f.). *NVIDIA PhysicsNeMo documentation*. https://docs.nvidia.com/physicsnemo/ **[URL por verificar]**

Oke, T. R., Mills, G., Christen, A., & Voogt, J. A. (2017). *Urban climates*. Cambridge University Press. https://doi.org/10.1017/9781139016476

OpenCFD Ltd. (2024). *OpenFOAM user guide* (v2406) y *Extended code guide: atmBoundaryLayerInlet*. https://www.openfoam.com/documentation

OpenStreetMap contributors. (2026). *OpenStreetMap* [base de datos geográfica]. https://www.openstreetmap.org (licencia ODbL).

Park, J. J., Florence, P., Straub, J., Newcombe, R., & Lovegrove, S. (2019). DeepSDF: Learning continuous signed distance functions for shape representation. *Proceedings of the IEEE/CVF Conference on Computer Vision and Pattern Recognition*, 165–174.

Raissi, M., Perdikaris, P., & Karniadakis, G. E. (2019). Physics-informed neural networks: A deep learning framework for solving forward and inverse problems involving nonlinear partial differential equations. *Journal of Computational Physics, 378*, 686–707. https://doi.org/10.1016/j.jcp.2018.10.045

Richards, P. J., & Hoxey, R. P. (1993). Appropriate boundary conditions for computational wind engineering models using the k-ε turbulence model. *Journal of Wind Engineering and Industrial Aerodynamics, 46–47*, 145–153. https://doi.org/10.1016/0167-6105(93)90124-7

Richards, P. J., & Norris, S. E. (2011). Appropriate boundary conditions for computational wind engineering models revisited. *Journal of Wind Engineering and Industrial Aerodynamics, 99*(4), 257–266. https://doi.org/10.1016/j.jweia.2010.12.008

Roth, M. (2000). Review of atmospheric turbulence over cities. *Quarterly Journal of the Royal Meteorological Society, 126*(564), 941–990. https://doi.org/10.1002/qj.49712656409

Servicio Meteorológico Nacional / CONAGUA. (s. f.). *Estaciones Meteorológicas Automáticas (EMAs)* y *Normales climatológicas*. https://smn.conagua.gob.mx

Snyder, W. H. (1981). *Guideline for fluid modeling of atmospheric diffusion* (EPA-600/8-81-009). U.S. Environmental Protection Agency.

Stull, R. B. (1988). *An introduction to boundary layer meteorology*. Kluwer Academic Publishers. https://doi.org/10.1007/978-94-009-3027-8

Tancik, M., Srinivasan, P. P., Mildenhall, B., Fridovich-Keil, S., Raghavan, N., Singhal, U., Ramamoorthi, R., Barron, J. T., & Ng, R. (2020). Fourier features let networks learn high frequency functions in low dimensional domains. *Advances in Neural Information Processing Systems, 33*, 7537–7547.

Tominaga, Y., Mochida, A., Yoshie, R., Kataoka, H., Nozu, T., Yoshikawa, M., & Shirasawa, T. (2008). AIJ guidelines for practical applications of CFD to pedestrian wind environment around buildings. *Journal of Wind Engineering and Industrial Aerodynamics, 96*(10–11), 1749–1761. https://doi.org/10.1016/j.jweia.2008.02.058

Verein Deutscher Ingenieure. (2017). *VDI 3783 Blatt 9: Umweltmeteorologie – Prognostische mikroskalige Windfeldmodelle – Evaluierung für Gebäude- und Hindernisumströmung*. Beuth.

Wang, S., Teng, Y., & Perdikaris, P. (2021). Understanding and mitigating gradient flow pathologies in physics-informed neural networks. *SIAM Journal on Scientific Computing, 43*(5), A3055–A3081. https://doi.org/10.1137/20M1318043

Wieringa, J. (1993). Representative roughness parameters for homogeneous terrain. *Boundary-Layer Meteorology, 63*(4), 323–363. https://doi.org/10.1007/BF00705357

</div>
