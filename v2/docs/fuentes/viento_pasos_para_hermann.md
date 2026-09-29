# Pasos que requieren acción humana (Hermann) — datos de viento y capa límite

Generado el 28 de septiembre de 2026 como parte de la investigación de fuentes de viento para el
proyecto PINN Zona Tec. Ninguno de estos pasos fue ejecutado por el agente (requieren
registro/cuenta, navegador interactivo, o contacto humano). Ver `fuentes_viento.md` y
`estudios_previos.md` para el contexto completo de cada fuente.

---

## 1. SMN/CONAGUA — lista y descarga de EMA cercanas a Monterrey

**Por qué se necesita acción manual:** los enlaces de descarga ("KMZ de estaciones", "lista de
estaciones") en https://smn.conagua.gob.mx/es/observando-el-tiempo/estaciones-meteorologicas-automaticas-ema-s
están implementados con componentes JavaScript/Joomla; no se pudo extraer una URL directa de
archivo con herramientas automatizadas (`curl`/fetch de texto).

**Pasos:**
1. Abrir la página en un navegador normal.
2. Descargar el KMZ o la lista de texto de estaciones.
3. Filtrar por Nuevo León / área metropolitana de Monterrey y anotar coordenadas y claves.
4. Si se requiere el histórico horario de alguna EMA específica, escribir a
   ventanillaunica.smn@conagua.gob.mx solicitando el histórico (indicar clave de estación,
   periodo y variables: velocidad/dirección de viento).

## 2. SIMA Nuevo León — series horarias crudas de viento (estación Preparatoria ITESM Garza Lagüera y otras)

**Por qué se necesita acción manual:** el portal público (aire.nl.gob.mx) sólo publica reportes
mensuales/anuales en PDF; el subportal con datos en vivo/históricos (aire.nl.gob.mx/sima/,
"Nuevo León v8 | Respira") requiere **inicio de sesión** (cuenta), y no se encontró una API pública
documentada durante esta investigación.

**Pasos sugeridos:**
1. Crear/solicitar una cuenta en http://aire.nl.gob.mx/sima/ si el sistema lo permite de forma
   abierta (verificar si es auto-registro o requiere aprobación).
2. Si no es posible obtener acceso vía el portal, enviar una solicitud formal (puede ser una
   solicitud de transparencia/acceso a la información pública, ya que Nuevo León tiene ley de
   transparencia estatal) a la Secretaría de Medio Ambiente de Nuevo León, solicitando:
   - Series horarias de velocidad y dirección de viento 2014–2026 (o el periodo disponible) de la
     estación **"Preparatoria ITESM Eugenio Garza Lagüera (SUR)"** — es la más cercana al Campus
     Monterrey (~4.1 km).
   - Adicionalmente, de ser posible, series de las estaciones **Obispado (CE)**, **San Bernabé
     (NO)** y **San Pedro (SO2)**, que junto con Garza Lagüera rodean el campus.
   - Metadatos exactos del sensor: marca/modelo del anemómetro, altura exacta sobre el techo del
     edificio y sobre el nivel de calle, frecuencia de muestreo, y si hay registros de
     calibración/interrupciones.
3. Alternativa: explorar el catálogo completo de datos abiertos del estado en
   https://catalogodatos.nl.gob.mx/dataset/ (no se navegó exhaustivamente en esta sesión) por si
   ya existe un dataset publicado de calidad del aire/meteorología.

## 3. CFE — Manual de Diseño de Obras Civiles, Diseño por Viento (2020), copia oficial completa

**Por qué se necesita acción manual:** el manual no está disponible como descarga gratuita
oficial verificada; existen copias en repositorios de terceros (Scribd, Academia.edu, Studylib)
cuya fidelidad al documento oficial 2020 no se pudo confirmar completamente, y algunos requieren
cuenta/pago para descarga completa.

**Pasos:**
1. Verificar si el Tec de Monterrey (biblioteca o alguna escuela de ingeniería civil) tiene acceso
   institucional al manual completo o a una copia física.
2. Alternativamente, el manual puede solicitarse/comprarse a través del LAPEM/CFE
   (https://lapem.cfe.gob.mx/normas/) — revisar si tienen venta de normas o acceso a consulta.
3. Con el PDF oficial en mano, extraer específicamente:
   - Tabla de velocidades regionales (VR) por periodo de retorno para el municipio de Monterrey /
     estado de Nuevo León (mapa de isotacas).
   - Confirmar los valores de α, δ y c por categoría de terreno para la edición 2020 exacta (los
     valores reportados en `fuentes_viento.md` provienen de motores de búsqueda sobre copias de
     terceros y deben tratarse como no verificados hasta cotejarlos con el original).
4. También se puede intentar de nuevo la descarga del informe complementario del CENAPRED
   (falló por error de DNS en esta sesión, puede ser temporal):
   https://www1.cenapred.unam.mx/DIR_INVESTIGACION/2020/1er_Trimestre/FRACCION_XLI/RH/200305_RE-RH_lnforme_VientoVF_orig.pdf

## 4. ERA5 completo vía Copernicus CDS (si se desea más resolución/variables que Open-Meteo)

**Por qué se necesita acción manual:** el Copernicus Climate Data Store (CDS) requiere registro y
una API key personal; por instrucción del proyecto, este agente no debía registrarse ni generar
credenciales.

**Pasos para Hermann:**
1. Crear una cuenta gratuita en https://cds.climate.copernicus.eu/.
2. Aceptar los términos de licencia del conjunto de datos ERA5 (Copernicus License, gratuita, uso
   abierto con atribución).
3. Generar una API key personal desde el panel de usuario (https://cds.climate.copernicus.eu/api-how-to).
4. Instalar el cliente `cdsapi` en el entorno del proyecto (`E:\PINN\.venv\Scripts\pip install
   cdsapi`) y guardar la key en `~/.cdsapirc` (NO en un archivo del repositorio del proyecto).
5. Solicitar el dataset `reanalysis-era5-single-levels` (variables `10m_u_component_of_wind`,
   `10m_v_component_of_wind`, `100m_u_component_of_wind`, `100m_v_component_of_wind`) en el punto
   de rejilla más cercano a 25.651 N, -100.290 O, para tener acceso a los componentes u/v nativos
   (en vez de la velocidad/dirección ya derivada que entrega Open-Meteo) y, si se requiere, niveles
   de presión adicionales para perfil vertical.
6. Nota: esto es opcional — los datos ya descargados vía Open-Meteo (ver `fuentes_viento.md`,
   sección A.4) son ERA5 auténtico y ya cubren 2014–2025 sin necesidad de este paso, así que sólo
   se justifica si se necesita mayor control sobre el reanálisis (p. ej. niveles de presión,
   componentes u/v crudos, o ERA5-Land de mayor resolución ~9 km).

## 5. Contacto con investigadores del Tec de Monterrey

**Por qué se necesita acción manual:** requiere contacto humano directo, no accesible por
búsqueda web.

**Pasos:**
1. Contactar al **Dr. Oliver Probst** (Escuela de Ingeniería y Ciencias, física / energía eólica)
   para preguntar:
   - Si el "Wind Energy Group" (antes en fisica.mty.itesm.mx/fisica/WEG/, dominio caído) tiene
     datos de viento medidos en el campus o en la región que puedan compartirse.
   - Si conoce tesis de titulación (no necesariamente publicadas en RITEC) sobre viento
     urbano/peatonal en el campus o Distrito Tec.
2. Contactar a la biblioteca del Tec (biblioteca.tec.mx) o al equipo de RITEC para pedir ayuda de
   búsqueda avanzada en el repositorio institucional (el acceso automatizado externo a
   repositorio.tec.mx/discover devolvió 403 Forbidden en esta sesión).
3. Preguntar en Facilities/Campus Sustentable del Tec si existe alguna estación meteorológica
   propia del Campus Monterrey (por ejemplo asociada a paneles solares, jardines o algún proyecto
   de sustentabilidad) con datos históricos, aunque no sean públicos.

## 6. Radiosondeos de la estación 76394 (Monterrey)

**Por qué se necesita acción manual:** la consulta automatizada por URL al archivo de la
Universidad de Wyoming devolvió error 404 con el formato de URL construido por el agente; el sitio
usa un formulario interactivo.

**Pasos:**
1. Ir a https://weather.uwyo.edu/upperair/sounding.shtml
2. Seleccionar región "North America", estación 76394 (Monterrey/Mariano Escobedo) y el rango de
   fechas deseado.
3. Confirmar si la estación sigue reportando activamente o sólo tiene histórico limitado, y
   descargar los sondeos de interés (formato texto) para extraer el perfil vertical de viento.
