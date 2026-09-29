# Estudios previos — viento, CFD y confort peatonal en el Tec de Monterrey / Distrito Tec / Monterrey

Revisión de literatura y repositorios institucionales para el proyecto PINN Zona Tec. Fecha:
28 de septiembre de 2026.

## Resumen ejecutivo

No se localizó, en el tiempo disponible de esta investigación, ninguna tesis, artículo o informe
técnico publicado que reporte **mediciones de viento, un estudio CFD o un estudio de túnel de
viento específicamente para el Campus Monterrey del Tecnológico de Monterrey, Distrito Tec o el
centro/corredores urbanos de Monterrey**. Esto no significa que no exista — el repositorio
institucional del Tec (RITEC) y los repositorios de la UANL tienen buscadores internos limitados
para búsquedas exactas desde motores externos, y es razonable que trabajos de titulación (tesis de
licenciatura/maestría) sobre el tema existan pero no estén bien indexados por buscadores generales.
Se documentan a continuación los hallazgos parciales y las pistas más prometedoras para que Hermann
las siga directamente.

## 1. Repositorio institucional del Tec de Monterrey (RITEC)

- **URL:** https://repositorio.tec.mx/
- **Qué es:** repositorio institucional con más de 80,000 documentos académicos (tesis, artículos,
  reportes técnicos, pósters).
- **Búsquedas realizadas:** combinaciones de "viento", "CFD", "confort peatonal", "pedestrian",
  "wind" vía buscador externo restringido a `site:repositorio.tec.mx` y vía intento de acceso
  directo a la interfaz de búsqueda del repositorio (`/discover?query=...`), que devolvió **403
  Forbidden** al intentar acceso automatizado (el sitio probablemente bloquea scraping / requiere
  navegador con JavaScript).
- **Resultado:** no se encontraron títulos relevantes de forma concluyente. Se recomienda que
  Hermann (con acceso de navegador normal, posiblemron con su cuenta institucional) haga búsquedas
  directas en https://repositorio.tec.mx/ con términos como:
  - "viento" + "peatonal" / "confort"
  - "CFD" + "urbano" / "edificios"
  - "wind" + "pedestrian" / "urban"
  - "túnel de viento"
  - Nombres de posibles asesores: Oliver Probst (energía eólica/física), y profesores de las
    escuelas de Ingeniería Civil/Arquitectura del campus Monterrey que trabajen en simulación
    urbana o energía eólica.
- **Estado:** [no verificado — pendiente de búsqueda manual con navegador].

## 2. UANL (Universidad Autónoma de Nuevo León)

- No se realizó una búsqueda exhaustiva del repositorio de la UANL en esta sesión (fuera del
  alcance de tiempo). La Facultad de Ciencias de la Tierra y la Facultad de Ingeniería Civil de la
  UANL son candidatas razonables para tesis sobre clima urbano/viento en el AMM, dado que la
  estación SIMA "Universidad" (N2) opera dentro de instalaciones de la UANL.
- **Acción sugerida:** buscar en http://eprints.uanl.mx/ (repositorio institucional UANL) con
  términos similares a los del punto 1.
- **Estado:** [no verificado].

## 3. Grupo de energía eólica del Tec de Monterrey (Dr. Oliver Probst)

- **Quién:** Dr. Oliver Matthias Probst Oleszewski, profesor/investigador de física en el
  Tecnológico de Monterrey, Escuela de Ingeniería y Ciencias, especialista en evaluación de
  recurso eólico.
- **Publicaciones relevantes localizadas (no específicas del campus, pero sí del contexto
  regional/nacional):**
  - Toledo, V., Probst, O., et al. (2015). *A surface wind speed map for Mexico based on NARR and
    observational data*. Meteorological Applications, 22(4), 1–XX.
    https://rmets.onlinelibrary.wiley.com/doi/full/10.1002/met.1500 (acceso de pago; resumen
    disponible).
  - Romo Perea, A., Amezcua, J., & Probst, O. *Validation of three new measure-correlate-predict
    models for the long-term prospection of the wind resource*. Journal of Renewable and
    Sustainable Energy, 3(2), 023105. AIP Publishing.
  - Probst, O., & Cárdenas, D. (2010). *State of the art and trends in wind resource assessment*.
    Energies, 3(6). (Revisión general, no específica de Monterrey).
- **Sitio web del grupo:** `fisica.mty.itesm.mx/fisica/WEG/` — el dominio **ya no resuelve** (DNS
  falla), por lo que el sitio parece dado de baja o migrado sin redirección conocida.
- **Utilidad:** este grupo es la pista más sólida de investigación en viento **dentro** del Tec de
  Monterrey, aunque orientada a energía eólica (macro-escala) y no a viento peatonal/urbano.
  Recomendable contacto directo (ver `pasos_para_hermann.md`).
- **Estado:** [parcialmente verificado — publicaciones confirmadas vía búsqueda, contenido
  completo no accedido].

## 4. Túnel de viento / laboratorio de capa límite

- No se encontró evidencia de un túnel de viento (de capa límite ni aerodinámico) operado por el
  Tecnológico de Monterrey Campus Monterrey.
- Se encontró, como única referencia mexicana documentada de un túnel de capa límite atmosférica,
  el de la UNAM: *"Characteristics and calibration of the mexican boundary layer wind tunnel at
  UNAM"*, Revista/Scielo México, 2022.
  https://www.scielo.org.mx/scielo.php?pid=S1405-77432022000100107&script=sci_arttext — útil
  como referencia metodológica nacional para diseño de perfiles de entrada tipo capa límite (leyes
  de potencia/logarítmica, espectros de turbulencia), pero sin relación directa con Monterrey.
- **Estado:** [no verificado la ausencia total — investigación razonable pero no exhaustiva].

## 5. Estudios de calidad del aire / meteorología urbana con relación indirecta

- El informe **INECC (2025)**, *Diagnóstico sobre la Escala Espacial de Representatividad* (ver
  `fuentes_viento.md`, sección A.2), aunque no es un estudio de CFD ni de confort peatonal, es el
  documento técnico más relevante encontrado sobre el **comportamiento del viento a escala local en
  el AMM cerca del campus** (estación Preparatoria ITESM Garza Lagüera, rosa de viento 2021–2023,
  discusión de canalización por Sierra Madre Oriental / Cerro de la Silla, y análisis de
  obstrucciones — árboles — al flujo libre de viento en el entorno de la estación). Se recomienda
  tratarlo como el estudio previo más útil para contexto de validación cualitativa de dirección
  dominante, aunque no da campos de velocidad espacialmente resueltos ni es un estudio CFD.
- El informe de 2021 (*Estudio para el rediseño de la red de monitoreo...*) es un antecedente del
  anterior, con contenido similar sobre la red pero de fecha previa a la reubicación/actualización
  de algunas estaciones.

## 6. Nota sobre trabajo relacionado (no de Monterrey, referencia metodológica)

Durante la búsqueda por palabras clave "pedestrian-level wind prediction" se identificaron trabajos
recientes de aprendizaje automático para predicción de viento peatonal urbano (p. ej. Huang et al.,
2026, *Inpainting U-Net for seamless pedestrian-level wind prediction across urban morphologies*,
arXiv:2607.02560, Imperial College London). **No están relacionados con Monterrey ni con el Tec**,
pero son referencias metodológicas relevantes para el enfoque PINN/ML del proyecto si se desea
comparar arquitecturas. Se mencionan aquí solo como nota, no como "estudio previo" del sitio.

## Conclusión y recomendación

La revisión no encontró estudios de CFD, túnel de viento o confort peatonal específicos del Campus
Monterrey, Distrito Tec o el centro de Monterrey. El hallazgo más valioso indirecto es el informe
INECC 2025 con la rosa de viento de la estación SIMA dentro de un plantel del Tec (Garza Lagüera),
que da una validación cualitativa independiente de la dirección dominante (SE/canalización NO-SE)
cerca de la zona de estudio. Se recomienda que Hermann:
1. Busque directamente en repositorio.tec.mx y eprints.uanl.mx con un navegador normal (ver arriba).
2. Contacte al Dr. Oliver Probst o a la Escuela de Ingeniería y Ciencias del Tec para preguntar por
   trabajos de titulación no publicados en el repositorio abierto, y por si existe un túnel de
   viento o estación meteorológica de investigación en el campus.
3. Considere que la ausencia de resultados en buscadores no es prueba de inexistencia — tesis de
   licenciatura mexicanas frecuentemente tienen metadatos pobres para indexación externa.
