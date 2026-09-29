# Revisión independiente F1: física, numérica y metodología

Proyecto: PINN Zona Tec (fase 2). Revisor: subagente Opus independiente (no escribió el código revisado). Fecha: 2026-09-28.
Alcance: `DECISIONES.md`, `PLAN.md`, `v2/docs/DATA_CONTRACT.md`, `v2/geometry`, `v2/climate`, `v2/cfd/aij` y `runs/aij/*`, `v2/ml` y `runs/smoke`, `datos/alturas/fuentes_alturas.md`, `datos/viento/fuentes_viento.md`.
No se modificó ningún archivo del proyecto. Las verificaciones numéricas propias están en la §7 (scripts de solo lectura en el scratchpad del revisor; no se usó la GPU ni se corrió CFD).

Severidad:
- **BLOQUEANTE**: hay que resolverlo antes del hito que protege. En geometría, clima y CFD ese hito es el arranque de la campaña CFD de Zona Tec (F2/F3). En ML es entrenar con datos reales o sellar la partición (F4). Ningún bloqueante de ML frena la CFD, salvo lo que cambia qué se guarda en el HDF5.
- **IMPORTANTE**: afecta la validez o la defensa ante un sinodal. Se resuelve en la fase en curso o se documenta con una cifra.
- **MENOR**: de forma, de claridad o de bajo impacto.

---

## 0. Veredicto

**NO-GO para arrancar la campaña CFD de Zona Tec hoy. GO inmediato para las corridas AIJ con edificio (`bld_*_M`) y para el trabajo de F2.**
Por qué:
1. Los tres casos de homogeneidad con **perfil log de entrada**, que es justo la configuración de la campaña (P12), fallaron: k-ε estándar diverge, k-ω SST no converge y hace flujo inverso junto al suelo, y k-ε realizable no converge y hace crecer k entre 135 y 187 %. El README de AIJ todavía dice «pendiente», así que el fallo no está reportado.
2. La transferencia de dos capas P14-A (U10 del aeropuerto → entrada) no está implementada en ningún lado, y la fórmula de `ml/export.py` sobrestima K entre 5 y 31 % según z0.
3. El z0 de la entrada sale de huellas OSM **incompletas** en los sectores N, NW y W (λp de 0.16 a 0.29 con OSM contra 0.44 a 0.53 medidos en el ráster de Google).
4. Todavía no hay diseño ni plantilla de malla de Zona Tec (`v2/cfd/zonatec/` está vacío). El presupuesto de celdas propuesto deja 1.75 m dentro de la **primera** celda y celdas de 16 m sobre los 40 m alrededor de torres de 77 y 85 m.
5. No hay benchmark de OpenFOAM (criterio de F1 sin cumplir; `tools/OPENFOAM_SETUP.md` no existe y la tabla §7 del PLAN está vacía).
6. Hay nueve huellas chicas (63 a 188 m²) con alturas de 27 a 41 m, cinco de ellas a menos de 25 m del centro de la ZOI. Es muy probable que sean contaminación del ráster, y la geometría se congela para más de 40 corridas.

Nada de esto exige rediseñar el proyecto. Estimo de 3 a 5 días de trabajo para cerrar los bloqueantes de CFD. Lo que sí está bien hecho: las fórmulas de Macdonald y Kanda (reproducidas a 1e-14), el dominio circular, la corrección del alias de sectores de 10° a 22.5°, la definición de las métricas AIJ, la malla hexaédrica conforme del caso AIJ y la convención de presión del residuo RANS.

---

## 1. Geometría y rugosidad

### BLOQUEANTE G1: la morfometría de barlovento usa huellas OSM incompletas en 8 de 16 sectores
- Evidencia: `out/H_best/roughness_16sectors.csv`. Comparé λp contra la fracción de píxeles construidos (h > 2.5 m) del ráster de Google 2.5D en la misma cuña (§7.3):

| θ | λp OSM | λp Google | H_mean OSM / Google |
|---|---|---|---|
| 0 | 0.156 | 0.530 | 4.8 / 4.8 |
| 45 | 0.215 | 0.439 | 7.7 / 6.3 |
| 90 | 0.422 | 0.424 | 6.0 / 6.2 |
| 112.5 | 0.498 | 0.490 | 5.3 / 5.4 |
| 135 | 0.496 | 0.463 | 5.5 / 5.7 |
| 270 | 0.261 | 0.464 | 3.9 / 4.7 |
| 315 | 0.294 | 0.451 | 5.4 / 5.8 |

  En los sectores dominantes (E-SE) coinciden, lo que da confianza en el método. En N, NE, W y NW (los «nortes», de 4.5 a 6.5 % de las horas y las U10 medias más altas, de 4.1 a 4.5 m/s) OSM se queda con un tercio o la mitad de las huellas. `fuentes_alturas.md` ya lo anticipaba: 2,942 edificios en OSM contra 26,507 en Overture dentro del mismo bbox.
- Corrección: recalcular λp, λf, H_mean y σH en `build_geometry.py` (carga de `load_all_buildings`, línea 83) con las huellas de **Overture** (`datos/alturas/raw/overture_buildings_all.csv`, fuentes Microsoft + Google + OSM, sin duplicar) y las alturas de la mediana de Google. Como control independiente, λp = fracción de píxeles de `building_presence` (o de h > 2.5 m) en cada cuña. Reportar las dos cosas.

### IMPORTANTE G2: el z0 de Macdonald es la incertidumbre dominante del perfil de entrada y hay que tratarlo así
- Evidencia: z0/H_mean va de 0.011 a 0.042 y d/H_mean de 0.33 a 0.78 (§7.1). En los sectores dominantes E-SE, z0 queda entre 0.075 y 0.087 m para barrios densos de 1 o 2 pisos (λp ≈ 0.5). El control de tabla es z0 = 1.0 m (EN 1991-1-4 cat. IV), 12 veces más. Macdonald con λp ≈ 0.5 está en régimen de «skimming» (1 − d/H ≈ 0.24) y se sabe que subestima z0 cuando hay heterogeneidad de alturas. La clasificación de Davenport-Wieringa (Wieringa 1992) le daría a esta zona de 0.5 a 1.0 m.
- Impacto: con la transferencia de la §2 (I2), U(10 m) en la entrada pasa de 0.956·U10 (z0 = 0.08) a 0.766·U10 (z0 = 1.0), un 25 % de diferencia en K antes de llegar a los edificios. El número de horas de excedencia con Weibull k ≈ 2.5 es muy sensible a eso.
- Corrección: (a) mantener Macdonald como primario (P13-B es vinculante), pero con Overture (G1); (b) volver **obligatorias**, no opcionales, dos corridas de sensibilidad en la dirección piloto (112.5°): z0 = 0.5 m (Wieringa, «very rough») y z0 = 1.0 m (control), con la misma malla, y propagar el efecto a K a 1.75 m y a la clase NEN 8100; (c) reportar z0 como banda por sector. `z0_macdonald_pert_±1floor` no sirve como sensibilidad porque solo mueve alturas «estimated» y en H_best casi no hay (el CSV muestra valores iguales en los sectores 0 a 45 y 180 a 247.5).

### BLOQUEANTE G3: alturas sospechosas en huellas chicas del centro de la ZOI
- Evidencia: `out/H_best/buildings.csv`. Nueve edificios de la ZOI con huella de 63 a 188 m² y altura de 27 a 41 m, todos con `google_discrepancy=True`: 1543350346 (62.6 m², 37.1 m), 1543350347 (104 m², 38.5 m), 1539504902/05, y **1539506600-06 (66 a 129 m², 26 a 31 m, a 9-23 m del centro de la ZOI)**. La resolución efectiva de Google 2.5D es de unos 4 m (`fuentes_alturas.md` §3a), así que una huella de 63 a 188 m² cubre solo de 4 a 12 píxeles efectivos. Una mediana sobre tan pocos píxeles borrosos **no** filtra la contaminación de una torre vecina, que es lo que asume `google_raster.py:1-9`.
- Hay dos defectos más en el control de calidad (QC): `build_geometry.py:155` fija `google_confidence = "medium"` para todo, así que el QC de `heights.py:280-284` solo verifica 2 ≤ h ≤ 250 m. Y la bandera de discrepancia (56 % de los edificios) no cambia ninguna decisión.
- Corrección, antes de mallar:
  1. Regla de aceptación de Google: `n_pixels_efectivos = área/16 m² ≥ 12` **y** (sin `building:levels`, **o** razón Google/(niveles × 3.4) entre 0.6 y 1.8). Si no se cumple, usar niveles × 3.4 m y marcar el edificio.
  2. Mediana sobre la huella **erosionada** 2 m (quita los píxeles de borde mezclados). En torres (h > 30 m), reportar también el p75.
  3. Verificar en campo o en fotos los 15 más altos y el grupo 1539506600-06. Hermann está en el campus y le toma minutos. Anotarlos en `heights_manual.csv`.
  4. Revisar si hay torres construidas **después de 2023** (la época del ráster es 2023-06-30) en Distrito Tec. Una torre nueva de más de 85 m cambia H_max, el dominio y la estela.

### IMPORTANTE G4: el SDF rápido tiene errores grandes justo donde importa, y hay riesgo de desajuste entre entrenamiento e inferencia
- Mecanismo (`sdf.py:119-146`): fuera de las huellas usa la altura del píxel **más cercano en planta**. Si ese vecino es bajo y hay una torre un poco más lejos, sobrestima la distancia. Caso sintético (§7.8): un punto a z = 30 m, a 2 m de una casa de 3 m y a 16 m de una torre de 80 m, da SDF rápido = 27.1 m contra 15.5 m exacto. Por eso el máximo de 13.6 m cae **alrededor de las torres**, la zona más relevante para el confort. El error medio de 0.5 m viene de medir la EDT sobre centros de píxel.
- Impacto en el ML: (i) el SDF entra como rasgo de la red, tanh(sdf/H_ref), y sus saltos (|∇sdf| ≠ 1 donde cambia el «vecino en planta») contaminan las derivadas de autograd por la regla de la cadena; (ii) si el HDF5 guarda el SDF exacto de trimesh y la web usa la rejilla, hay un desajuste sistemático entre entrenamiento e inferencia; (iii) el etiquetado de zonas y la selección de puntos de pared dependen del SDF.
- Corrección (exacta y barata para LOD1): la distancia a un prisma b es d_b(x,y,z) = sqrt(d2_b(x,y)² + max(0, z − h_b)²), y SDF = min_b d_b. Calcular d2_b con shapely o con EDT por edificio (445 edificios; prefiltrar con STRtree a los k = 20 más cercanos) y tomar el mínimo por nivel z. Se usa **el mismo** SDF en el HDF5, en el entrenamiento y en la rejilla de la web. Para autograd de segundo orden, ver M3.

### IMPORTANTE G5: el anillo explícito de 120 m equivale a una manzana
- Evidencia: `frame.json` (zoi_half 425, ring_half 545). Los puntos cercanos al borde de la ZOI solo tienen 120 m de edificios explícitos a barlovento; más allá, solo z0. La guía de la AIJ (Tominaga et al., 2008) pide modelar explícitamente los edificios dentro de 1 a 2 H del objetivo, y para los edificios bajos del borde eso se cumple por poco. Las torres (a 214-240 m del borde) sí quedan bien rodeadas.
- Corrección: (a) reportar confort y métricas en una ZOI de evaluación recortada 100 m hacia adentro, o (b) ampliar el anillo a ≥ 200 m, que es barato con celdas de 4 m (unas 0.3 M celdas más). Documentarlo.

### IMPORTANTE G6: las torres de 77 y 85 m quedan subresueltas con el plan de refinamiento
- Evidencia: `domain_circular_recommendation.md`: 2 m hasta 20 m en la ZOI, 4 m hasta 40 m en el anillo y 16 m por encima. Arriba de 40 m, las torres de ~28-35 m de lado quedan con 2 a 3 celdas de ancho. El «downwash» que produce las velocidades peatonales altas en las esquinas nace del punto de estancamiento a ~0.7 H y de la separación en el techo.
- Corrección: `refinementSurfaces` sobre el STL de edificios con un nivel que dé ≤ 2 m en las caras (≥ 10 celdas por lado de torre, Tominaga 2008) y una `refinementRegion` de ≤ 4 m alrededor de cada edificio con h > 30 m, hasta 1.5 H y con 1 H de margen. Recalcular el presupuesto de celdas con esto y con las capas de suelo (C4).

### MENOR G7
- `morphometry.py:55`: R_IN = 560 m, pero las esquinas del anillo están a 545·√2 = 771 m. En los sectores diagonales, la cuña de 560 a 771 m cuenta edificios que ya están explícitos. Usar R_IN = 780 m o excluir por pertenencia al anillo y no por radio.
- κ = 0.40 en la morfometría (`morphometry.py:47`, fiel a Macdonald 1998) y 0.41 en el contrato y en OpenFOAM. Está bien, pero hay que decirlo en el informe.
- El control de tabla usa d = 0 (`morphometry.py:53`). Para la cat. IV, lo usual es d ≈ 0.7·H_mean; está bien documentarlo como simplificación.
- `PLAN.md` §4 todavía describe un dominio de 2.0 × 1.4 × 0.4 km. Ya no aplica (ahora es circular, R = 2049 m, altura 511 m).

### Lo que está bien
- Macdonald (1998): d/H = 1 + α^(−λp)(λp − 1) y z0/H = (1 − d/H)·exp{−[0.5 β (C_D/κ²)(1 − d/H) λf]^(−1/2)}, con α = 4.43 y β = 1.0 (arreglo escalonado), C_D = 1.2 y κ = 0.4. Todo es correcto (`morphometry.py:136-150`). λf se define por dirección con la proyección de cada huella sobre el eje transversal al viento × h, dividida entre el área de la cuña, sin sombreado. Es la definición de Macdonald.
- Kanda et al. (2013): X = (σH + Havg)/Hmax, d/Hmax = c0X² + (a0λp^b0 − c0)X; Y = λpσH/Havg, z0/z0_mac = b1Y² + c1Y + a1, con (a0, b0, c0, a1, b1, c1) = (1.29, 0.36, −0.17, 0.71, 20.21, −0.77). Coincide con lo que recuerdo del artículo. Aun así, hay que confirmarlo contra el original, como dice el README.
- Dominio circular: 15 H en todas direcciones sobrecumple el 5 H de barlovento y laterales. La altura de 6 H cumple ≥ 5 H sobre el edificio más alto. El bloqueo en el peor caso es de 1.55 % (< 3 %). Es una elección defendible. Consecuencia: el fetch vacío a barlovento mide ~1.3 km, así que la prueba de homogeneidad debe cubrir esa misma distancia (C1).

---

## 2. Clima

### BLOQUEANTE I2: la transferencia P14-A (U10 del aeropuerto → entrada) no está implementada ni especificada
- Evidencia: el único lugar donde aparece es `ml/export.py:93`: `u* = U10·κ/ln((10 − d + z0)/z0)`. Eso iguala U(10 m) urbano con U10 en terreno abierto, o sea, **no** hay transferencia de rugosidad, y sobrestima K. Además `export.py` guarda un solo z0 y d, cuando z0 cambia por sector.
- Método que propongo, el mismo que usa NEN 8100 (altura de mezcla de Wieringa, 60 m) y que por eso es coherente con P10:
  1. Estación: u*_s = κ·U10,s / ln(10/z0,s), con z0,s = 0.03 m (WMO), o mejor, un z0,s por sector estimado con factores de ráfaga del ISD (Verkaik, 2000).
  2. Altura de mezcla z_b = 60 m: U_b = (u*_s/κ)·ln(z_b/z0,s).
  3. Rugosidad regional del sector: u*_r(θ) = κ·U_b / ln((z_b − d_r)/z0,r(θ)), con d_r = 0 para ser consistente con P12 (el efecto de d_r a 60 m es ≤ 2 %; reportarlo).
  4. Entrada (Richards y Hoxey): U(z) = (u*_r/κ)·ln((z + z0,r)/z0,r), k = u*_r²/√Cμ, ε = u*_r³/(κ(z + z0,r)), ω = ε/(Cμ·k).
  - Factor total: T(θ) = u*_r/U10,s = κ·ln(z_b/z0,s) / [ln(10/z0,s)·ln(z_b/z0,r)].
  - K(x, θ) = (|U|/U_H)_CFD · (U_H/U10,s), con U_H/U10,s = (T/κ)·ln((H_ref + z0,r)/z0,r).
- Control, reportado como banda de incertidumbre: EN 1991-1-4, ec. 4.4-4.5: v_m(z) = k_r·ln(z/z0)·v_b, con k_r = 0.19·(z0/0.05)^0.07 y v_b = U10,s / [k_r(z0,s)·ln(10/z0,s)], lo que da u*_r = κ·k_r(z0,r)·v_b.
- Valores (§7.4):

| z0,r [m] | T mezcla 60 m | T EN 1991-1-4 | T de `export.py` | U(10 m)/U10 mezcla | sobrestimación de K en `export.py` |
|---|---|---|---|---|---|
| 0.05 | 0.0757 | 0.0731 | 0.0773 | 0.979 | +2 % |
| 0.08 | 0.0810 | 0.0756 | 0.0848 | 0.956 | +5 % |
| 0.32 | 0.1025 | 0.0833 | 0.1180 | 0.868 | +15 % |
| 1.00 | 0.1310 | 0.0902 | 0.1710 | 0.766 | +31 % |

- Por qué bloquea la CFD: gracias a la independencia de Reynolds, **la magnitud** u* se puede aplicar en el posproceso. **La forma** del perfil (z0,r por sector) y la z0 del suelo exterior, en cambio, hay que fijarlas antes de correr. Se necesita una función `inflow_for_sector(theta, U10) -> (u*, z0, d, U_H, T)` en `v2/climate` o en `v2/cfd`, usada por la generación de casos, por el HDF5 (atributos) y por `export.py` (un z0 y un T por sector).

### IMPORTANTE I3: la cola de la Weibull no sirve para el umbral de peligro, y hay una cifra inconsistente
- Evidencia: con K = 1, P(U10 > 15) da 0.0013 % con la Weibull. En el caché horario, la excedencia empírica es **0.0055 % (7 h en 15 años)**, no el 0.010 % que dice `climate/README.md:96`; corregir esa cifra. Con K = 1.5, la Weibull da 0.19 %, justo entre los umbrales de 0.05 % y 0.3 % de NEN 8100, así que un sesgo de cola cambia la clase.
- Corrección: agregarle a `windclimate.py` una ruta **empírica** por sector, P_j(U10 > u) = Σ w_ij·1[U_i > u] / N_total, con los mismos pesos fraccionales de `sector_weights`, y usarla por defecto siempre que u = umbral/K ≤ ~12 m/s (hay datos de sobra: P(U10 > 10) = 0.52 %). La Weibull queda para suavizar e interpolar. Más allá de ~12 m/s, reportar la cifra como «n < 30 h, no concluyente» en vez de extrapolar.

### IMPORTANTE I4: la API no codifica todavía los criterios de NEN 8100 ni de Lawson
- NEN 8100 (a verificar contra la norma impresa): umbral de 5 m/s de velocidad media local a 1.75 m. Clases por P(V_loc > 5 m/s): A < 2.5 %, B de 2.5 a 5 %, C de 5 a 10 %, D de 10 a 20 %, E > 20 %. Calidad por actividad: atravesar (A-C buena, D moderada, E mala), pasear (A-B buena, C moderada, D-E mala), estar sentado (A buena, B moderada, C-E mala). Peligro por P(V_loc > 15 m/s): < 0.05 % sin riesgo, de 0.05 a 0.3 % riesgo limitado, > 0.3 % peligroso. `annual_exceedance` (`windclimate.py:266-320`) calcula bien la probabilidad, pero hace falta `nen8100_class(p5, p15)` con estos cortes y con pruebas.
- Lawson LDDC usa el **máximo entre la media y el GEM** (gust-equivalent mean = ráfaga/1.85), con umbrales de 4/6/8/10 m/s excedidos < 5 % del tiempo, y de seguridad 15/20 m/s con un porcentaje anual muy bajo; fijar y citar la versión exacta. Con RANS solo hay media: estimar U_gust ≈ U + g·σ_u, con σ_u = sqrt(2k/3) y g ≈ 3.0-3.5, GEM = max(U, U_gust/1.85), y **declararlo como estimación**. Si se compara Lawson solo con la media, la comparación con NEN 8100 (P10) queda sesgada a favor de Lawson.

### IMPORTANTE I5: orografía y representatividad de la estación
- MMMY está a unos 18 km al NNE del campus. Para el sector dominante ESE, el flujo que llega al Tec pasa junto al Cerro de la Silla (unos 1,200 m sobre la ciudad, a pocos km al E-SE), y los ponientes pasan por la Loma Larga. P19-D mete la orografía «a través de la rosa», pero la rosa **del aeropuerto** no contiene el efecto local del cerro. Un sinodal va a atacar esto.
- Corrección: declararlo como limitación con una cifra: comparar la distribución direccional de MMMY con la de ERA5 en la celda del campus (`era5_openmeteo_rose16.csv` ya existe) y, cualitativamente, con estaciones SIMA-NL cercanas. Reportar la diferencia de frecuencia en los sectores E a SE.

### MENOR I6
- Filtrado del ISD: conservar los códigos {0, 1, 4, 5, 9} y descartar {2, 3, 6, 7} es correcto. Deduplicar por hora dando prioridad a FM-15 también. Calma = tipo 'C' (17.3 %, velocidad 0) y se trata bien: cuenta en el denominador y excede con probabilidad 0. Solo aparece 1 hora 'V' en 15 años. Es poco usual para METAR (VRB con viento débil); confirmar que NCEI no codifica los VRB como 'C' o 'N' con dirección 999 (en el caché no hay 'N' con dirección NaN, así que el efecto sería solo mover horas débiles a calma, sin impacto en las excedencias de 5 m/s o más).
- El METAR de la OACI da una media de 10 min por hora, y NEN 8100 usa medias horarias. La distribución de medias de 10 min es un poco más ancha, lo que sesga hacia arriba unos pocos % de las excedencias. Declararlo.
- Altura del anemómetro asumida de 10 m (ya declarada). Hora local UTC-6 sin horario de verano (ya declarada).

### Lo que está bien
- La corrección del alias de 10° a 22.5° (`windclimate.py:67-89`) es exacta: cada sector recibe la misma masa, 2.25 códigos de 10° (§7.5), y las frecuencias más la calma suman 1.
- El ajuste Weibull por máxima verosimilitud ponderada está bien planteado y reproduce P(U10 > 5) = 18.4 % contra 18.6 % empírico.

---

## 3. Validación AIJ Caso A y homogeneidad

### BLOQUEANTE C1: la homogeneidad con el perfil log (la configuración de la campaña) falló en los tres modelos
- Evidencia (`v2/cfd/aij/results/homogeneity.csv` y bitácoras):
  - `hom_ske_loglaw_rough`: **diverge** en la iteración ~404, justo al pasar a segundo orden (`log.simpleFoam.stage2`: continuidad 1e68, ε 1e109). No aparece en el CSV.
  - `hom_sst_loglaw_rough`: no converge (residuo inicial de ω = 3e-2 en la iteración 3000; 6 avisos de «bounding omega» con mínimo de −40). En la salida, U(H) vale 0.34 del medido y U(z = 0.01 m) < 0 (flujo inverso).
  - `hom_rke_loglaw_rough`: p0 = 9e-4 al final, y k crece entre +135 y +187 % en toda la altura.
  - El README (`v2/cfd/aij/README.md` §4) dice «Pendiente», así que el resultado no está reportado.
- Diagnóstico: con κ = 0.41, las constantes de SST (γ1 = 0.553 contra 5/9) y de realizable (σε consistente = 1.19 contra 1.2 por defecto; Cμ de equilibrio = 0.0905) son casi consistentes con Richards y Hoxey (§7.6). Por lo tanto, los fallos de SST y realizable **no** vienen del modelo sino del planteamiento: (i) techo con U, k y ε/ω de Dirichlet del perfil (`gen_case.py:257-261`); (ii) con k-ε estándar, σε = 1.3 por defecto cuando el valor consistente es κ²/((C2 − C1)√Cμ) = **1.167**; (iii) escala de túnel con z0+ ≈ 0.4 (suelo hidráulicamente liso) tratado con una ley rugosa.
- Corrección:
  1. Replicar la configuración verificada del tutorial de OpenFOAM v2306 `verificationAndValidation/atmosphericModels/atmDownstreamDevelopment`: techo con `fixedShearStress` τ = (u*², 0, 0) para U y `zeroGradient` para k, ε y ω; suelo con `nutkAtmRoughWallFunction`/`atmNutkWallFunction` y z0; para `kEpsilon`, `sigmaEps 1.167` (κ = 0.41), además de `Cmu 0.09`, `C1 1.44` y `C2 1.92`; laterales `symmetry`. Repetir con SST y realizable. Criterio de convergencia: residuos < 1e-5 **sin** avisos de «bounding».
  2. **Lo que de verdad importa:** repetir la prueba en **escala real** con el dominio circular vacío de Zona Tec: R = 2049 m, altura 511 m, **la misma malla de fondo y de refinamiento** (incluidas las transiciones de 16 → 4 → 2 m y las capas de suelo), el z0 del sector piloto y el modelo elegido. Medir U y k en la entrada, en el borde del anillo (x = −771 m) y en el centro de la ZOI.
  3. Definir sin ambigüedad el criterio de F2: **máximo** de |ΔU/U| ≤ 5 % y de |Δk/k| ≤ 20 % para 2 ≤ z ≤ 100 m, entre la entrada y el borde de barlovento del anillo. Con la media, un ΔU de 8-10 % pasaría inadvertido; es lo que ya se ve en los casos de tabla.

### IMPORTANTE C2: en el caso AIJ, lo que se compara con la medición debe ser el perfil **incidente**, no el de la entrada
- Evidencia: con la tabla, en x = 0 (posición del edificio, dominio vacío) el máximo de ΔU es de 8-10 % y la media de Δk va de −10 a −16 %, contra el perfil medido (`homogeneity.csv`, columnas `U_vs_meas_*`, `k_vs_meas_mean_%`). Es inevitable, porque la turbulencia de agujas y vallas no está en equilibrio con el suelo.
- Corrección: calibrar la entrada iterando (k_entrada ← k_entrada·k_medido(x = 0)/k_calculado(x = 0), 1 o 2 pasadas) hasta que |Δk| ≤ 10 % y |ΔU| ≤ 5 % en x = 0 para z ≤ H. Así lo hacen varios estudios del Caso A. Reportar el perfil incidente junto a los resultados.

### IMPORTANTE C3: el modelo que se elija en el AIJ debe pasar también la homogeneidad a escala real
- P16 elige el modelo con mejor tasa de acierto en el túnel. La selección debe condicionarse a que ese modelo pase C1.2. Si realizable gana en el túnel pero no conserva el perfil a escala real, se usa el segundo, y se documenta.

### Configuración del caso AIJ: revisada y correcta en lo esencial
- Malla (`runs/aij/bld_rke_M/log.checkMesh`): 691,800 hexaedros, no ortogonalidad 0, sesgo ~1e-12, relación de aspecto máxima 70.5, 20 celdas por lado b (Tominaga 2008: ≥ 10), expansión ≤ 1.15 (≤ 1.3), el punto peatonal cae en la 5.ª celda. Dominio de 5H/12.5H/5H, bloqueo de 0.79 %. Refinamiento sistemático con f = 0.77/1/1.3 para el GCI. Todo cumple Tominaga et al. (2008) y Franke et al. (2007).
- Entrada: ε = Cμ^½·k·dU/dz (P_k = ε, AIJ) y ω = ε/(β*·k), con β* = Cμ = 0.09. Correcto.
- Suelo: z0 = 0.18 mm con la primera celda de 2 mm (centroide a 1 mm, y/z0 = 5.6). Como ks = 9.793·z0/Cs = 3.5 mm es mayor que la primera celda, la forma en z0 (atm) es **la elección correcta**. Advertencia (MENOR): z0+ = z0·u*/ν ≈ 2.4 es transicional y los ajustes log dan un suelo liso. La comparación con suelo liso ya está en la matriz de corridas; reportarla.
- Esquemas: primer orden en la etapa 1 y `linearUpwind` más `limitedLinear 1` en la final, SIMPLEC y parada en 1e-5 con monitores. Correcto (COST 732: nada de primer orden en la solución final).
- Paredes del edificio lisas con funciones de pared: con celdas de 2 mm, y+ ≈ 10-20 en buena parte de las caras (zona de amortiguamiento). MENOR: reportar la distribución de y+ del edificio. v2306 hace la transición en yPlusLam, así que no rompe nada, pero un sinodal lo va a preguntar.
- Métricas (`post_aij.py:78-92`): acierto con |P − O|/|O| ≤ D o |P − O| ≤ W; FAC2 = fracción con 0.5 ≤ P/O ≤ 2; NMSE = ⟨(O − P)²⟩/(⟨O⟩⟨P⟩); FB = 2(⟨O⟩ − ⟨P⟩)/(⟨O⟩ + ⟨P⟩). Las definiciones coinciden con Chang y Hanna (2004) y VDI 3783-9.
  - MENOR: en `chang_hanna`, la máscara `m` (línea 88) se calcula y no se usa.
  - MENOR: en V y W, muchos puntos tienen |O| < W y aciertan de forma trivial. Reportar también q solo con los puntos donde |O| > W, y exigir q ≥ 0.66 **para U y para |U| en el plano z/b = 0.125** (el peatonal), no solo en conjunto.
  - Comparabilidad con la literatura: hay que citar W siempre que se dé un q; muchos trabajos usan valores distintos de W. Reportar además X_R/b y X_F/b contra 0.52 y 1.42, y comparar cualitativamente con las figuras de la intercomparación de Tominaga et al. (2008). Es sabido que el RANS estacionario alarga la estela, así que no hay que venderlo como defecto propio.

---

## 4. Malla, BCs y cómputo de Zona Tec (plan)

### BLOQUEANTE C4: el diseño de malla no cumple «≥ 3 celdas bajo 1.75 m»
- Evidencia: `geometry/README.md` §4 y `domain_circular_recommendation.md`: la ZOI tiene celdas de 2 m hasta 20 m, así que 1.75 m cae en la **primera** celda, y las capas de suelo están fuera del presupuesto. El refinamiento octree de snappyHexMesh es isótropo: si el fondo se gradúa en vertical en blockMesh, cada nivel de refinamiento también divide la altura de la celda (un fondo de 0.5 m refinado 3 niveles queda en 0.06 m).
- Corrección (una de dos):
  - (a) `addLayers` en el parche de suelo dentro de la ZOI y del anillo: 4 capas con `firstLayerThickness` ≈ 0.4 m, `expansionRatio` 1.2 y `finalLayerThickness` relativo ≤ 0.6 de la celda de 2 m. Exigir cobertura de capas ≥ 95 % en la ZOI (leerla del log de snappy); el colapso junto a la base de los edificios es el modo de falla típico.
  - (b) Fondo en blockMesh con bloques que ya den 2 m horizontales en el núcleo y graduación vertical desde 0.5 m, dejando snappy **solo** para castellar los edificios. Es lo que ya se hizo, con éxito, en el caso AIJ.
  - En los dos casos hay que agregar unos 0.7 M de celdas (850² m²/4 m² × 4 capas) al presupuesto, más G6, y comprobarlo en la malla piloto: primer centroide ≤ 0.25 m y 1.75 m en la 4.ª celda.

### BLOQUEANTE C5: no hay benchmark medido
- Evidencia: `tools/OPENFOAM_SETUP.md` no existe, la tabla §7 del PLAN está vacía y los casos `bld_*_M` (3D, 0.69 M celdas, np = 6) están generados pero sin correr. De las corridas 2D de homogeneidad (7,820 celdas, 3000 iteraciones, 66 s en serie) salen ~2.8 µs por celda e iteración. Extrapolando a ~4.5-5 M de celdas en 6 núcleos con eficiencia de ~0.6 (el 5600X está limitado por el ancho de banda de memoria), da **3-4 s por iteración, ~2.5-3.5 h por caso y ~110-130 h** para 16 + 16 + 4 + GCI. Es 1.5 veces lo que dice el PLAN (70-80 h). Es factible 24/7, pero no con margen.
- Corrección: correr `bld_rke_M` con np = 1, 2, 4 y 6, y registrar s/iteración, memoria pico y eficiencia paralela. Después, mallar el piloto de Zona Tec y medir la RAM pico de snappy (sobre todo en la fase de capas). Recién con eso se fija la resolución.

### IMPORTANTE C6: condiciones de frontera del dominio circular, todavía sin especificar
- Laterales: por dirección, dividir la frontera cilíndrica con `topoSet`/`createPatch` en entrada (n·e_flujo < 0) y salida (el resto). En la entrada, `atmBoundaryLayerInlet*` con flowDir = e_flujo(θ). En la salida, p = 0 con U `inletOutlet` y k/ε/ω `inletOutlet`. Techo: `fixedShearStress` (o valores fijos del perfil) según lo que salga de C1.
- Suelo: dos parches. `ground_outer`, con z0 = z0,r(θ) del sector (el mismo de la entrada: condición de homogeneidad), y `ground_zoi` (ZOI + anillo), con z0 local de calles y explanadas (0.03 a 0.05 m, documentado). El salto de rugosidad en el borde del anillo es físico (capa límite interna) y queda sobre edificios explícitos. Con la primera celda de fondo de 16 a 28 m, el centroide en 8-14 m está por encima de z0; se cumple z_P > z0 (Blocken et al., 2007).
- Entrada con d = 0 y fetch con d de 2 a 14 m: la ley log con d = 0 sobrestima U cerca del suelo respecto a un perfil urbano con d (a 10 m, ln(10.08/0.08)/ln(6.08/0.08) = 1.12, o sea +12 % con d = 4 m). El anillo explícito amortigua parte del efecto, pero conviene documentar la diferencia de K a 1.75 m en el borde de barlovento de la ZOI en la corrida piloto, contra una variante con el anillo ampliado (G5).

### IMPORTANTE C7: el GCI y la convergencia necesitan una definición operativa
- GCI (Celik et al., 2008) en K a 1.75 m: calcularlo punto por punto solo donde la convergencia es monótona (0 < R < 1) y reportar qué fracción de puntos es oscilatoria. Excluir los puntos a menos de 1 celda de las paredes. La meta de mediana < 5 % es razonable; reportar además el p90. Con r = 1.3, la malla fina es la de la campaña y la gruesa (r² = 1.69) queda con 1.75 m en la 2.ª o 3.ª celda. Es aceptable, pero hay que decirlo.
- Convergencia: «monitores dentro de ±1 %» debe medirse **en valor absoluto respecto a U_H** (en la estela, U local ≈ 0 y ±1 % relativo nunca se cumple). Agregar el desbalance de masa global < 1e-4 y el mismo criterio para los arranques en caliente, para que una dirección no «herede» la solución de su vecina (eso afectaría las direcciones retenidas).

### IMPORTANTE C8: la «independencia de Reynolds» con 0.5× y 2× U es casi tautológica en RANS
- Con funciones de pared rugosas en z0 y Re_H ~ 1e6-1e7, la solución RANS es prácticamente lineal en U. Solo las paredes lisas de los edificios (y+) introducen una dependencia débil. La prueba confirma eso y nada más, y hace que la partición retenida por velocidad sea trivial (ver M9).
- Corrección: mantener P5 (es vinculante), pero reportarla como «verificación de linealidad del modelo numérico», y dedicar el presupuesto de sensibilidad a lo que sí importa: z0 de la entrada (G2) y modelo de turbulencia en 1 dirección.

### MENOR C9
- Estabilidad neutra, sin árboles y sin topografía: ya están declaradas (P15, P19). Hay que cuantificar el efecto esperado de los árboles con al menos una referencia (los árboles del campus reducen U peatonal de forma apreciable), porque el mapa de confort sin árboles es conservador.

---

## 5. ML

### BLOQUEANTE M1 (antes de F4): la escala del residuo de momento. Diagnóstico y corrección
- Diagnóstico numérico (§7.9, red de smoke con los mismos pesos iniciales, en CPU). Contribuciones al cuadrado medio del residuo:

| Caso | ν_t medio (adim.) | convectivo | ∂p/∂x | viscoso | residuo total |
|---|---|---|---|---|---|
| σ = 4, inicialización | 0.708 | 0.026 | 2.06 | **27,840** | **52,149** |
| σ = 4, ν_t fijado en 0.01 | 0.01 | 0.026 | 2.06 | 5.5 | 19.9 |
| σ = 1, inicialización | 0.749 | 0.009 | 0.16 | 260 | 476 |
| etapa A entrenada (σ = 4) | 0.051 | 0.215 | 0.020 | 31.9 | 49.2 |

  **Causa raíz:** no son las unidades. Coordenadas y salidas son adimensionales, y derivar respecto a `xyz`/H_ref es consistente. El problema es el **término viscoso**, por dos cosas: (i) `softplus(≈0) = 0.69` da ν_t/(U_H·H_ref) ≈ 0.7 al inicializar (`models.py:47`), de 14 a 100 veces más que el ν_t real (en Zona Tec, ν_t ~ κ·u*·z ≈ 5 m²/s y U_H·H_ref ≈ 600 m²/s, así que ≈ 0.008); (ii) los rasgos de Fourier con σ = 4 por H_ref amplifican cada derivada unas 2π·4 ≈ 25 veces, así que las segundas derivadas crecen unas 600 veces. Incluso la red de la etapa A **ya ajustada** tiene un término viscoso 150 veces mayor que el convectivo: ruido de alta frecuencia en ∇·(ν_t∇u).
  La viscosidad molecular se pasa en m²/s (`config.py:156`, ν = 1.5e-5) cuando en adimensional debería ser 1/Re = ν/(U_H·H_ref) ≈ 1e-7. Es despreciable, pero está mal escrito (MENOR).
- Corrección:
  1. Salida de ν_t escalada: ν_t,nd = s_ν·softplus(raw + b0), con s_ν = mediana de ν_t,nd de la CFD y b0 tal que softplus(b0) = 1; o bien predecir log(ν_t,nd). Inicializar el sesgo de la última capa en la media de cada campo.
  2. Normalizar el residuo: R̂_i = R_i / S_i, con S_i = RMS de |u·∇u_i| calculado **de la CFD** (diferencias finitas sobre el HDF5 o `postProcess` de OpenFOAM). Así el objetivo queda O(1).
  3. Medir el **piso del residuo** de la propia CFD (el campo discretizado no cumple la EDP continua punto a punto, sobre todo con celdas de 2 m y `linearUpwind`): evaluar el residuo en un modelo de etapa A que ajuste un solo caso, y no pedirle a la PINN que baje de ese piso.
  4. Etapa C como curriculum: arranque en caliente desde el checkpoint de la etapa B, rampa lineal del peso del momento de 0 a w en unas 2000 iteraciones, y σ de Fourier elegido por escala física (H_ref = 85 m pone σ = 4 en longitudes de onda de ~21 m; para resolver 2-5 m a nivel peatonal, usar Fourier multiescala o coordenadas escaladas con una longitud local de ~10 m).

### BLOQUEANTE M2 (antes de F4): la variante de LRA implementada tiende a desbocarse
- Evidencia: `weighting.py:79-88` usa λ̂ = max|∇L_data| / mean|∇L_r|, anclado en los datos, sin tope y aplicado a los términos de física. En `runs/smoke/.../stageC` los pesos llegan a continuidad 1687, pared 29,024 y momento 642, y el error de datos se queda en 0.999 (la red predice la media).
- Mecanismo: (i) la razón max/mean sobre unos 10⁴ parámetros vale ≫ 1 aunque los gradientes sean comparables, así que la física queda sobrepesada por construcción; (ii) cuando la red cae en la solución trivial (campo casi constante, que cumple continuidad y u·n = 0), ∇L_física → 0 y λ → ∞. Es una retroalimentación positiva. El `clip_grad_norm_ = 1.0` (`train.py:139`) con un total de ~8,500 hace que el paso lo dicte el término dominante.
- Corrección: normalización por norma de gradiente (Wang et al., 2023, «An expert's guide to training PINNs»): λ_i = (Σ_j ‖∇L_j‖)/‖∇L_i‖, aplicada a **todos** los términos, incluidos los datos, con media móvil α = 0.9, tope λ_i ∈ [1e-2, 1e2]·λ_i⁰ y actualización cada 100 pasos después de un calentamiento de 1000 pasos con la física en rampa. Probarlo con un caso sintético donde se conozca el equilibrio.

### BLOQUEANTE M3 (antes de F4): con datos reales, la geometría no es diferenciable y las derivadas quedan mal en **todo** el dominio
- Evidencia: `features.py:321-324` busca `<variante>_sdf.npz` con las claves `sdf`, `origin`, `spacing` y `height`. Geometría escribe `out/H_best/sdf_grid_<variante>.npz` con `fine_sdf`, `coarse_sdf`, `fine_x0`, etc. (`sdf.py:209-214`). Por eso `resolve_geometry_source` devuelve `None` para los casos reales y `data.py:268-270` usa constantes. Como |∇sdf| = 1 en todas partes, falta el término ∂salida/∂sdf·∇sdf **en todos los puntos**, no solo junto a las paredes, como sugiere el docstring. La continuidad y el momento quedan mal calculados.
- Además, una rejilla con interpolación trilineal tiene gradiente constante por tramos y segundas derivadas nulas o singulares, así que el término viscoso a través de ese camino queda mal aunque se arregle el nombre.
- Corrección: (a) quitar sdf y altura local de las entradas de la red de la etapa C (dejar la geometría en la pérdida de pared); o (b) SDF analítico suave en torch: distancia exacta a prismas LOD1 (G4) combinada con un mínimo suave (log-sum-exp con k ≈ 1 m) sobre los ~20 edificios más cercanos. Es diferenciable a cualquier orden. En cualquier caso, unificar el formato del `.npz` entre `geometry` y `ml` y agregar una prueba que falle si `resolve_geometry_source` devuelve `None` para una variante real.

### BLOQUEANTE M4 (antes de sellar la partición): la variante retenida recibe un embedding sin entrenar
- Evidencia: `data.py:133` arma el vocabulario con **todas** las filas del manifiesto, así que var2 tiene una fila de `nn.Embedding` inicializada al azar que nunca recibe gradiente. La predicción de la prueba de variante depende de ese ruido. En el smoke se nota en `test-variant`: rel_l2_v = 15.7.
- Corrección: quitar el embedding de variante (la geometría entra solo por SDF/altura, que es lo único que puede generalizar a una geometría nueva). Si se conserva, asignar a la variante retenida el embedding de `base` y declararlo.

### IMPORTANTE M5: pérdida de datos desbalanceada entre campos
- Evidencia (datos sintéticos adimensionales): desviación estándar de k = 0.003, de w = 0.008, de p = 0.018 y de v = 0.28. `losses.data_loss` suma MSE sin normalizar, así que k, w y p quedan prácticamente sin supervisión, y ν_t (que entra al residuo) se ajusta mal.
- Corrección: estandarizar cada campo con la media y la desviación estándar del conjunto de entrenamiento (guardarlas en el checkpoint y en el JSON de la web), o ponderar cada MSE por 1/Var(campo).

### IMPORTANTE M6: los residuos en celdas junto a la pared no son válidos
- Con funciones de pared, la primera celda no cumple la EDP continua (el esfuerzo lo pone la ley de pared). `train.py:118` toma colocación entre todos los puntos de datos.
- Corrección: excluir `is_wall_adjacent == 1` (o `wall_dist` < 2 alturas de primera celda) del residuo de momento, y ponderar la colocación por volumen de celda (`vol`) para no sobremuestrear las zonas refinadas.

### IMPORTANTE M7: los puntos de pared tienen rasgos incoherentes
- `data.py:290`: `local_height = 0` en todos los puntos de pared. En techos y fachadas, la red ve una altura local distinta de la que ve en el fluido junto a esa misma pared. Es un error de rasgo; usar la altura del raster en (x, y). Además, las caras del suelo dominan el muestreo de pared y ahí u·n = w = 0 es trivial: muestrear edificios y suelo por separado (p. ej., 80/20).

### IMPORTANTE M8: el etiquetado de zonas no funciona a la escala de Zona Tec
- Evidencia (`metrics.py:93-141`): los radios escalan con H_ref = 85 m (esquina a 12.8 m de la pared con vecindad de 25 m, estela de 426 m y cañón de 170 m). Además `wall_faces` incluye el suelo (contrato): el vecino más cercano de casi todos los puntos bajos es una cara de suelo con n = (0, 0, 1), así que no se detecta ninguna estela, casi cualquier punto cerca de la base de un edificio se marca como esquina y casi cualquier punto se marca como cañón. El costo, O(N·k²) con `query_ball_point` a 170 m, es inviable con ~2 M de puntos.
- Corrección: usar solo caras de edificios y escalar con la altura del edificio más cercano, H_b. Definir **esquina** como d < 0.5·H_b de una arista vertical (vértice de huella con ángulo interior < 150°). **Estela**: detrás de la fachada de sotavento, 0 < s < 3·H_b en la dirección del flujo y dentro del ancho del edificio (o, con la CFD, u·e_flujo < 0 más K < 0.5). **Cañón**: dos fachadas con normales opuestas (coseno < −0.8) a distancia horizontal W ≤ 2·H_b. Calcularlo solo a 1.5-2 m de altura (capa peatonal).

### IMPORTANTE M9: el diseño de la partición retenida y la justicia de las referencias
- Direcciones retenidas 22.5/157.5/247.5/337.5: son buenas (una por cuadrante, a 22.5° de sus vecinas). Pero hay que elegir la **validación** fuera de las vecinas de las retenidas (0, 45, 135, 180, 225, 270 y 315 son vecinas). El smoke usa 270 y 315 como validación, lo que deja a 247.5 y 337.5 con huecos de 45°. Propongo validación = {67.5°, 202.5°} y, tras elegir el modelo, **reentrenar con entrenamiento + validación**.
- Asimetría de información: `data.py:151` deja que las referencias (dirección más cercana e interpolación angular) usen casos de entrenamiento **y validación**, mientras que la red solo ve los de entrenamiento. Hay que igualar el conjunto disponible.
- `test-speed`: la referencia de la velocidad más cercana usa los campos dimensionales **sin reescalar** (`baselines.py:218-230`; rel_l2_u = 0.667 = |4 − 12|/12). Con independencia de Reynolds, la referencia justa es la del caso vecino multiplicada por U10_objetivo/U10_fuente, que será casi perfecta. Por eso esta prueba mide la linealidad de la CFD, no la generalización del modelo, y hay que reportarlo así.
- Interpolación angular (`baselines.py:239-250`): no garantiza vecinos a ambos lados. Si las dos más cercanas quedan del mismo lado, los pesos de interpolación extrapolan hacia el lado equivocado. Exigir una vecina a cada lado; si no las hay, usar la más cercana. Interpolar además rapidez y ángulo (o K y dirección del flujo) en vez de mezclar u y v, que pierde magnitud (a 45° de separación, el promedio vectorial resta 29 %).
- La interpolación espacial dentro del mismo caso usa el 80 % de la verdad del caso de validación: es un **oráculo** (cota superior) y así debe aparecer en la tabla.
- Variante retenida var2: quita un edificio de 6.5 m a 93 m del borde de la ZOI. Las métricas sobre toda la ZOI serán casi iguales a las de la base, así que la prueba es trivial. Evaluarla solo en un radio de 5·H_b alrededor del cambio (≈ 50-100 m) y declarar que, con dos geometrías de entrenamiento, el reclamo de «generalización a geometría» se limita a perturbaciones pequeñas.
- Fuga por arranque en caliente de la CFD: si una dirección retenida se inicializa desde su vecina y se detiene con convergencia laxa, conserva memoria de ella. Para las 4 retenidas, arrancar desde la solución base de otra dirección no vecina, o exigir el criterio C7 estricto.
- La partición se lee del atributo `split` del HDF5 (`data.py:120`), no del manifiesto sellado, y el sellado con SHA-256 todavía no existe en el código. Leerla **solo** del manifiesto, con su hash verificado al cargar.

### IMPORTANTE M10: métricas que no miden lo que importa
- El L2 relativo y el acierto VDI se calculan sobre todo el volumen (z ≤ 2·H_max), donde dominan puntos altos y fáciles. Reportar como métrica principal la capa peatonal (1.5 ≤ z ≤ 2.0 m, o interpolado a 1.75 m) para K y |U|, y por capas el resto.
- VDI 3783-9: D = 0.25 está bien. Cuando la «verdad» es CFD, no hay repetibilidad de medición: fijar W con la incertidumbre numérica de la CFD (p. ej., el p90 de GCI·|U| a 1.75 m) y reportar siempre q con W = 0. W = 0.05·U10 (`metrics.py:66`) a nivel peatonal, con K típico de 0.2-0.6, equivale a un 10-25 % de la velocidad local: es muy permisivo.
- Métricas ponderadas por volumen de celda (`vol`), para que no dominen las zonas refinadas.

### IMPORTANTE M11: el DeepONet recibe U10 aunque sus salidas ya son adimensionales
- `models.py:104`: la rama incluye U10/Uref. Con salidas adimensionales por U_H, la dependencia en U10 es espuria y se extrapola mal (smoke: rel_l2_u = 17 en `test-speed`). Quitarla o sustituirla por log(Re).

### IMPORTANTE M12: el contrato de datos no coincide con lo que lee el ML
- `data.py:47` y `:114-120` requieren `local_height` y los atributos `h_ref`, `u_h` y `split`, que `DATA_CONTRACT.md` no lista. El contrato pide `vol` e `is_wall_adjacent`, que el ML no usa. Actualizar el contrato **antes** de escribir el extractor de la CFD: agregar `local_height` (definición: raster sin suavizar o suavizado s5; elegir uno), `h_ref`, `u_h`, `T_transfer` (I2), `z0_ground_zoi` y la versión del SDF. La partición sale del manifiesto, no del HDF5.

### MENOR M13
- tanh(sdf/H_ref) con H_ref = 85 m comprime los primeros 10 m de SDF en 0-0.12. Usar tanh(sdf/10 m), o sdf/H_ref más log(1 + sdf/1 m).
- `physics.py`: la convención de presión es correcta. `simpleFoam` resuelve con `divDevReff`, que omite la parte isótropa 2/3 k, así que el p escrito es p + 2/3 k. No hace falta agregar ∇(2/3 k). La pérdida de impermeabilidad u·n = 0 sin no deslizamiento es coherente con P24 y con las funciones de pared.
- El dominio del sintético alcanza z = 60 m con H_ref = 25; con datos reales, z ≤ 170 m y H_ref = 85. Revisar σ de Fourier y los rangos al cambiar de datos (ver M1.4).

---

## 6. Plan: criterios de aceptación y huecos

| Criterio del PLAN | Juicio | Ajuste propuesto |
|---|---|---|
| Homogeneidad ±5 % U, ±20 % k | Adecuado | Máximo (no media), 2 ≤ z ≤ 100 m, entrada → borde del anillo, malla y dominio de la campaña (C1) |
| GCI de K a 1.75 m, mediana < 5 % | Adecuado | Solo puntos con convergencia monótona; reportar la fracción oscilatoria y el p90 (C7) |
| Residuos < 1e-4 o monitores ±1 % en 500 iteraciones | Casi | ±1 % **de U_H**, desbalance de masa < 1e-4, mismo criterio para arranques en caliente (C7) |
| AIJ: q ≥ 0.66 (D = 0.25) | Adecuado | Citar W; exigir q para U y para |U| en z/b = 0.125; perfil incidente calibrado (C2) |
| Bloqueo < 3 % | Cumple | — |
| «s/iteración por M de celdas medido» | **No cumplido** | C5 |
| La Weibull reproduce P(U10 > 5 m/s) | Cumple (18.4 % contra 18.6 %) | Agregar la ruta empírica para la cola (I3) |

Huecos que un sinodal atacaría, por prioridad: (1) de dónde sale z0 de la entrada y por qué es 12 veces menor que la tabla (G1, G2); (2) cómo se pasa del aeropuerto a la entrada (I2); (3) la homogeneidad del perfil (C1); (4) la resolución peatonal (C4); (5) la representatividad de la estación frente al Cerro de la Silla (I5); (6) la independencia de Re «tautológica» y la partición por velocidad trivial (C8, M9); (7) que la PINN no le gane a la dirección más cercana. Esto último es aceptable si se reporta con honestidad, como prevé el PLAN.

---

## 7. Qué verifiqué numéricamente

Scripts de solo lectura en el scratchpad del revisor (`checks.py`, `diag_mom.py`); CPU, sin GPU.
1. **Macdonald y Kanda:** los reimplementé desde las fórmulas publicadas y reproducen las 16 filas de `roughness_16sectors.csv` con una diferencia máxima de 7e-15. z0/H_mean = 0.011-0.042 y d/H_mean = 0.33-0.78.
2. **Revisión de OSM:** λp y H_mean por cuña contra el ráster de Google 2.5D (tabla de G1).
3. **Alturas:** 9 edificios de la ZOI con huella < 200 m² y h > 20 m (lista en G3). Equivalen a 3.9-11.8 píxeles efectivos de 4 m.
4. **Transferencia de dos capas:** T = u*/U10 con altura de mezcla de 60 m, con EN 1991-1-4 y con la fórmula de `export.py` (tabla de I2).
5. **Clima:** con K = 1, la Weibull da P(>5) = 18.38 % y P(>15) = 0.00131 %; el caché horario da P(>15) empírica = 0.0055 % (7 h) y P(>10) = 0.52 %. Con K = 0.8/1.2/1.5, P(>5) = 7.0/30.6/45.7 % y P(>15) = 0.0000/0.018/0.19 %. Masa por sector de los 36 códigos METAR = 2.25 en todos (el alias queda corregido). Frecuencias más calma = 1 (calma = 17.35 %).
6. **Consistencia con Richards y Hoxey (κ = 0.41):** σε de k-ε consistente = 1.167 (OpenFOAM por defecto 1.3); realizable con Cμ de equilibrio = 0.0905 y σε consistente = 1.188 (por defecto 1.2); SST con γ1 consistente = 0.553 (OpenFOAM 0.5556).
7. **Homogeneidad y convergencia:** leí `homogeneity.csv`, `log.simpleFoam.stage2` y `timing.txt` de los 9 casos (estado de cada uno en C1) y el `checkMesh` de `bld_rke_M`.
8. **SDF:** el caso sintético de casa baja junto a una torre reproduce el modo de falla (27.07 m el método rápido contra 15.50 m el exacto).
9. **Residuo de momento:** el desglose por términos al inicializar, con ν_t fijado, con σ = 1 y en la etapa A entrenada (tabla de M1). Escalas de los campos sintéticos adimensionales (desviaciones estándar de M5). Historial de pesos de LRA del smoke (M2).

No verifiqué: los coeficientes de Kanda contra el artículo original (de pago), el texto exacto de VDI 3783-9, NEN 8100 ni de la versión de Lawson (las cifras de I4 hay que cotejarlas contra las normas), ni el tiempo real en 3D o en paralelo de OpenFOAM (no corrí CFD, por instrucción).

---

## 8. Orden de trabajo sugerido (camino crítico a F3)
1. Hoy: correr `bld_*_M` (AIJ) y el benchmark de np (C5). En paralelo, verificar en campo las alturas de G3.
2. Arreglar la homogeneidad en escala de túnel siguiendo el tutorial de OpenFOAM (C1.1). Huellas de Overture en la morfometría (G1). Función de transferencia (I2).
3. Plantilla de Zona Tec con capas de suelo y refinamiento de torres (C4, G6, C6). Malla piloto en 112.5°. Homogeneidad a escala real (C1.2).
4. GCI con 3 mallas más las sensibilidades de z0 en 112.5° (G2). Recién entonces, la campaña.
5. En paralelo, sin frenar la CFD: M12 (contrato) antes del extractor; después M1 a M4 y el resto del ML.
