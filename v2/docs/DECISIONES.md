# DECISIONES — PINN Zona Tec (fase 2)

Fuente: `grill-me-pinn-zonatec.pdf` (v1.0, 28-sep-2026) y `RESPUESTAS-HERMANN.txt` (firmadas 28-sep-2026). Las respuestas de Hermann son **vinculantes**. En este documento, cada pregunta tiene la opción elegida (texto del PDF resumido), lo que implica para el trabajo y, si aplica, el conflicto con otra respuesta o con la realidad y cómo se resuelve.

Leyenda: ✅ sin conflicto · ⚠️ conflicto o dato faltante, con la resolución que propongo · ❓ pregunta abierta para Hermann

---

## A. Bloqueantes: objetivo, curso, cómputo y equipo

**P1. Plazo → C: más de 8 semanas.** ⚠️❓
- *Opción:* «Más de 8 semanas. Se pueden agregar LES en 1 o 2 direcciones para contrastar con RANS, o la generalización a geometrías».
- *Implica:* se hace el plan base completo (unas 40 corridas, variantes, validación AIJ y GCI) y quedan como extensiones planeadas (i) LES para cuantificar el error de RANS y (ii) árboles porosos (P19-B).
- **Actualización (Hermann, 28-sep 16:44):** «quedan unas semanas». Esto **acota P1-C en la práctica**: se mantiene el alcance de P21-B, pero con un orden de prioridades estricto y líneas de recorte (PLAN §3). Primero la validación AIJ y las 16 direcciones base; después las variantes; LES y árboles solo si sobra tiempo. Todavía falta la fecha exacta; mientras no llegue, se planea para ~4-5 semanas.

**P2. Qué pesa en la calificación → A y B: rigor físico y metodológico + novedad en ML.** ✅
- *Implica:* dos ejes de calidad. Rigor: validación AIJ, GCI, incertidumbre de z0, d y alturas, fuentes primarias. ML: ablaciones por etapas (datos → +continuidad → +RANS), pesos adaptativos, comparación con un operador neuronal (DeepONet) y con referencias simples.

**P3. ¿PINN estricta? → D: PINN híbrida (B) como modelo principal, operador neuronal (C) como comparación.** ✅
- *Implica:* modelo principal = MLP con rasgos de Fourier entrenado con datos CFD más residuos físicos. Comparador = **DeepONet** (la rama codifica dirección, variante y velocidad; el tronco recibe (x, y, z, SDF)). Elegí DeepONet y no FNO porque da un campo 3D continuo y se evalúa en los mismos puntos y con las mismas métricas. Un FNO/U-Net 2D a nivel peatonal queda como extra opcional (suma al eje ML de P2).

**P4. Generalización en geometría → B: Zona Tec más 2 o 3 variantes realistas.** ✅❓
- *Implica:* geometría actual + variantes (p. ej., una torre proyectada, un predio vacío). El agente de geometría propone candidatas justificadas. ❓ Hermann confirma cuáles (si hay una obra real planeada en Distrito Tec, mejor).

**P5. Parámetros del viento → B: 16 direcciones (cada 22.5°) a una velocidad, más 2 velocidades extra en 2 direcciones.** ✅
- *Implica:* la velocidad entra como escala (U = U_ref · û(x, θ)). Las velocidades extra sirven para demostrar la independencia de Reynolds (Snyder, 1981), y una de ellas se retiene como prueba (P27-D).

**P6. Hardware → A: CFD en la CPU del equipo más potente (≥ 8 núcleos, ≥ 32 GB) con OpenFOAM en WSL2; entrenamiento en la RTX 4090.** ⚠️❓ **Conflicto serio con la realidad.**
- Esta sesión corre en la PC de Culiacán: Ryzen 5 5600X (6 núcleos / 12 hilos), **16 GB de RAM**, RTX 3070 de 8 GB, disco C: lleno. **WSL no está habilitado** y no tengo permisos de administrador.
- *Resolución provisional:* la fase 1 (entorno, geometría, validación AIJ, tubería y prueba de humo) se hace aquí. El PLAN presupuesta el peor caso: toda la campaña en esta PC, con mallas de unos 3 a 4 M de celdas (limitadas por la RAM de snappyHexMesh) y corridas nocturnas, lo cual cabe en >8 semanas (P1-C). Si Hermann da acceso a la máquina de la 4090 (≥ 8 núcleos, ≥ 32 GB), se sube la resolución de la malla sin cambiar nada más.
- OpenFOAM: se busca una ruta sin administrador (compilación oficial de ESI para Windows). Como respaldo, `E:\PINN\admin\instalar_wsl2_openfoam.ps1` queda listo para que Hermann lo ejecute con un clic (pide administrador y reinicio).
- **Resuelto (Hermann, 28-sep 16:44): no hay RTX 4090.** Todo el cómputo se hace en ESTA PC: CFD en la CPU (6 núcleos, 16 GB) y entrenamiento en la RTX 3070 (8 GB, compartida). El entrenamiento se diseña para caber en < 5 GB de VRAM (lotes, redes compactas; los residuos PDE en float32). Kaggle o Colab gratis quedan como desborde **opcional**, nunca como requisito.
- Estado de OpenFOAM: la ruta sin administrador está en curso. MS-MPI extraído por usuario ya corre `mpiexec -n 4` sin administrador (verificado por el agente de entorno).

**P7. Equipo → A: un dueño humano por especialidad; los subagentes trabajan bajo cada uno.** ⚠️❓
- **Resuelto (Hermann, 28-sep 16:44):** el revisor y dueño es Hermann, y el trabajo lo hacen agentes Opus/Sonnet. Como no hay revisores humanos por especialidad, P7-A se sustituye por **autorrevisión rigurosa**: antes de cada hito, un subagente revisor **Opus** independiente revisa física, numérica y validación, y sus observaciones se atienden o se documentan.

## B. Entregable: «elijo un punto y sé el viento»

**P8. Salidas → A + B + C + E.** ✅
- A: velocidad media (m/s) y dirección (°) para una dirección de entrada dada.
- B: factor de amplificación K = U_local / U_ref para las 16 direcciones.
- C: intensidad de turbulencia I = √(2k/3) / U, **marcada como estimación RANS** (supone isotropía).
- E: clase de confort peatonal (P10).
- No se entregan presión/Cp (D) ni ráfagas (F).

**P9. Alturas de consulta → B: 3D desde el suelo hasta ≈ 2 veces la altura del edificio más alto.** ✅
- La red recibe (x, y, z). La validación y el confort se reportan a z = 1.75 m (AIJ) y el resto del volumen se valida con las mismas métricas por capas.

**P10. Confort → C: Lawson (LDDC) y NEN 8100, para comparar.** ✅
- Los dos criterios se calculan combinando K(θ) con la rosa de vientos de 16 sectores (probabilidad de excedencia), y se reporta en qué zonas discrepan (Janssen et al., 2013).

**P11. Interfaz → A: la web de v1 ampliada, con MapLibre y teselas OSM, selector de dirección y altura, y panel con K, rosa de vientos y confort; publicada en Vercel.** ✅
- La red corre en JS en el navegador, como en v1 (`public/model.json`). El **despliegue en Vercel necesita la aprobación explícita de Hermann** (regla heredada de PLAN-EQUIPO).

## C. Física y perfil de entrada

**P12. Perfil de entrada → B: ley log neutra con u* y z0, k y ε de Richards y Hoxey (1993) (`atmBoundaryLayerInlet*`), con rugosidad del suelo consistente (Richards y Norris, 2011).** ✅ con nota técnica
- *Implica:* d = 0 en la entrada (la opción C, con d ≠ 0, no se eligió). El d morfométrico de P13 se usa solo en la transferencia de rugosidad de dos capas (P14) y en el informe.
- *Nota técnica (T9):* con z0 urbano (~0.5 a 1 m), una función de pared basada en la rugosidad de grano de arena ks ≈ 9.793·z0/Cs exigiría primeras celdas más altas que ks, lo que es incompatible con resolver el nivel peatonal. Resolución estándar (Blocken et al., 2007; Richards y Norris, 2011): en el suelo, la función de pared atmosférica en términos de z0 (`nutkAtmRoughWallFunction`) con el mismo z0 del perfil, y una prueba de homogeneidad horizontal en un dominio vacío antes de la campaña (criterio de aceptación en el PLAN). Dentro de la zona de edificios, el suelo usa un z0 local pequeño (calles y campus), documentado.
- La ley de potencia de la CFE solo se usa para comparar en el informe (T1).

**P13. z0 y d → B (Macdonald et al., 1998), con A (tablas: Davenport/Wieringa, EN 1991-1-4 cat. IV) como control y C (Kanda et al., 2013) como sensibilidad.** ✅
- *Implica:* z0 y d por sector de 16 a partir de los edificios a barlovento. Se reporta como rango. Las corridas de sensibilidad de z0 (valor Kanda) se agregan en 1 o 2 direcciones si hay presupuesto; si no, el efecto se estima con el escalamiento del perfil de entrada.

**P14. U_ref → A: U10 en terreno abierto (aeropuerto), trasladada a la entrada del dominio con un modelo de dos capas de rugosidad.** ✅⚠️
- *Estación:* Hermann no marcó ninguna. Propongo **NOAA ISD del aeropuerto internacional de Monterrey (MMMY)**, con identificador verificado por el agente de clima, y MMAN y ERA5 (vía Open-Meteo) como contraste. Si Hermann prefiere una EMA del SMN, el cambio es barato (solo cambia la rosa).

**P15. Estabilidad → A: solo neutra, declarada como limitación.** ✅

**P16. Turbulencia → B: RANS k-ε realizable o k-ω SST, estacionario.** ✅ con decisión técnica
- *Resolución:* el caso AIJ se corre con **los dos** modelos (y con k-ε estándar como referencia), y para la campaña de Zona Tec se usa el que tenga mejor tasa de acierto contra el túnel de viento. Así la elección se justifica con datos y no por preferencia. Si hay tiempo (P1-C), se corre un LES del caso AIJ o de una dirección para cuantificar el error de RANS.

## D. Dominio y geometría

**P17. Área → B: el campus y el polígono Distrito Tec, con los edificios explícitos en la zona de interés y un anillo de 1 o 2 manzanas.** ✅⚠️
- *Límite práctico:* con 16 GB de RAM, la zona con edificios explícitos debe medir del orden de 600 a 900 m de lado. Si el polígono Distrito Tec completo no cabe, el anillo exterior se simplifica (edificios más gruesos) y se reporta. ❓ Si Hermann tiene un polígono dibujado, que lo mande; si no, el agente de geometría propone uno.

**P18. Alturas → A: huellas de OSM y altura = pisos × 3 m (LOD1), con los pisos contados en campo o en fotos.** ✅❓
- Por autorización de Hermann (28-sep, 16:37) hay una investigación a fondo de fuentes de alturas: etiquetas de OSM, Overture Maps, LiDAR del INEGI, noticias oficiales del Tec. Cada altura lleva su fuente y licencia (`E:\PINN\datos\FUENTES.md`).
- **Resuelto (Hermann, 28-sep): «hagamos caso al satélite».** Hermann está en el piso 11 de una torre de Zona Tec y hay más pisos arriba, lo que confirma que OSM subestima las torres. Regla de alturas: manual/oficial > Google Open Buildings 2.5D (con control de calidad) > OSM `height` > pisos × 3.2-3.6 m > valor por defecto. Cada altura satelital se contrasta con el conteo de pisos (× 3.2-3.6 m), y las discrepancias > 30 % se marcan. La lista `datos/alturas/lista_verificacion_campo.md` queda para confirmaciones puntuales.
- *Consecuencia:* H_max sube a ~80-92 m (antes 54 m). El dominio COST 732 crece y el dominio circular único (una malla por geometría para las 16 direcciones) se vuelve más atractivo para el presupuesto de celdas.

**P19. Qué más va en el dominio → A + D, y B como extensión.** ✅
- Base: solo edificios sobre terreno plano (A), y el efecto del valle entra por la rosa de vientos medida (D). Extensión: árboles como medio poroso (B), una vez cerrada la base.

## E. Datos CFD

**P20. Software → A: OpenFOAM (simpleFoam, snappyHexMesh) en WSL2.** ⚠️
- La decisión de fondo (OpenFOAM, scripts y documentación citables) se respeta. Solo cambia la ruta de instalación si WSL2 no se puede habilitar sin administrador (ver P6). La versión exacta queda registrada en cada caso.

**P21. Corridas → B: 16 direcciones en la geometría actual + 2 variantes × 8 direcciones + 2 velocidades × 2 direcciones ≈ 36 a 40.** ✅
- Más 2 corridas del estudio de malla (P22) y las corridas de validación AIJ.

**P22. Confianza en la CFD → C: estudio de malla con 3 mallas y GCI (Celik et al., 2008) en 1 dirección + reproducción de AIJ Caso A (edificio aislado 1:1:2) o CEDVAL.** ✅
- Se usa AIJ Caso A. D (comparar con la campaña de campo) no aplica porque P28 = A.

## F. PINN

**P23. Física en la pérdida → C, construida por etapas (primero B, luego C).** ✅
- Etapa A (solo datos, referencia obligatoria) → B (+ continuidad ∇·u = 0) → C (+ momento RANS estacionario, con ν_t como salida supervisada con la ν_t de la CFD). Si C no se estabiliza, B es el resultado y se reporta.

**P24. Fronteras → B: impermeabilidad u·n = 0 en paredes, datos CFD en la primera capa de celdas y perfil de entrada como condición blanda.** ✅ (nunca no deslizamiento)

**P25. Arquitectura → A: MLP con rasgos de Fourier; entradas (x, y, z), (sin θ, cos θ), identificador de variante, SDF a los edificios y altura local.** ✅ (el comparador DeepONet sale de P3-D)

**P26. Herramienta → A: PyTorch puro, pesos adaptativos (Wang et al., 2021), Adam seguido de L-BFGS.** ✅ Entrenamiento en la RTX 3070 compartida (vigilar VRAM de ComfyUI y Ollama), o en la 4090 si aparece (P6).

## G. Validación

**P27. Contra qué se mide → B + C + D, con todas las métricas y todas las referencias.** ✅
- Pruebas: direcciones retenidas (4 de 16), una variante de geometría retenida y una velocidad retenida.
- Métricas: L2 relativo, MAE de K, tasa de acierto VDI 3783-9 y error por zona (esquinas, estelas, cañones).
- Referencias: interpolación, la misma red sin física y la dirección simulada más cercana.
- La partición se **sella con hash** antes de entrenar, y la evaluación la hace un agente independiente que no ve el código de entrenamiento.

**P28. Mediciones reales → A: ninguna; solo climatología SMN/NOAA para la rosa de vientos.** ✅⚠️
- *Implica:* no hay campaña con anemómetro (el plan por defecto la traía; se sigue a Hermann). La validación física descansa en AIJ más GCI, y el informe declara la limitación de «modelo de un modelo» (T6/P28).
- La investigación de estudios previos (estaciones del Tec, SIMA-NL, tesis) puede encontrar datos existentes utilizables. Si aparecen, se usan como validación cualitativa **sin cambiar la decisión**.

## H. v1

**P29. v1 → B: el mismo repositorio, con carpeta `v2/`; v1 queda como «prueba de concepto 2D».** ⚠️❓
- **Resuelto:** el repositorio privado es `github.com/HermannPR/pinn-zonatec`. El historial completo llegó como bundle, se clonó en `E:\PINN\wind-pinn` y se trabaja en la rama **`fase2-zonatec`**, creada desde `grill/fase1-zonatec` (7852405 = v1 + grill + respuestas, que es lo que tiene `main` en GitHub; el `main` del bundle es más viejo, cc11a22).
- v2 vive en `v2/` dentro del repositorio. Solo se versionan código, configuraciones, documentación y datos pequeños. Mallas, resultados CFD y HDF5 se quedan fuera de git (en `E:\PINN\runs`, `E:\PINN\v2\data` o D:).
- Para entregar: `git bundle create E:\PINN\outbox\cambios-<fecha>.bundle fase2-zonatec` y aviso a claude-hermann, que lo sube a GitHub.
- Regla heredada de PLAN-EQUIPO: **sin trailer de coautoría de Claude** en los commits del repositorio compartido con Oscar.
- Se reutilizan de v1: la web (`public/`), la exportación a JS, el esqueleto de rasgos de Fourier y adimensionalización, la honestidad de las métricas y la película (`video/`).

---

## Resumen de preguntas abiertas para Hermann
1. **(P6, la más importante)** ¿Hay acceso a la máquina de la RTX 4090 (CPU, RAM, cómo se entra)? Si no, la campaña se hace en esta PC con mallas de unos 3 a 4 M de celdas.
2. **(P1)** Fecha exacta de entrega y lista de entregables.
3. **(P7)** Nombres y especialidad de cada dueño humano; ¿participa Oscar?
4. **(P4/P17)** ¿Qué variantes de geometría (torre proyectada real, predio) y qué polígono de Distrito Tec quieres? Si no hay preferencia, se usa la propuesta del agente.
5. **(P18)** ¿Quién puede contar pisos en campo o en fotos de la lista priorizada?
6. **(P29)** ¿Remoto de git o zip con `.git` para conservar el historial?
7. **(P6/P20)** Si la ruta de OpenFOAM sin administrador falla: ejecutar `E:\PINN\admin\instalar_wsl2_openfoam.ps1` (pide administrador y reinicio).
