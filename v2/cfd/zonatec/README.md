# CFD Zona Tec: plantilla, malla, piloto y costo

Simulaciones RANS estacionarias de viento neutro (capa límite atmosférica) sobre los edificios LOD1 explícitos del Campus Monterrey y Distrito Tec. Los resultados alimentan la PINN híbrida.
OpenFOAM v2306 (ESI, compilación MinGW para Windows) y MS-MPI con 6 procesos.
Aquí solo va texto versionado: scripts, plantillas y documentos. Los casos corren en `E:\PINN\runs\zonatec\` y los HDF5 quedan en `E:\PINN\v2\data\processed\`.

Estado: **ver §7 (resultados del piloto)**. Toda cifra de este documento sale de un archivo generado por una corrida; se cita el archivo junto a la cifra.

---

## 1. Qué hay y cómo se usa

| Script (`scripts/`) | Qué hace |
|---|---|
| `gen_mesh.py` | Crea un **caso de malla** por variante de geometría y nivel de malla (`fine`/`medium`/`coarse`; `xcoarse` solo para pruebas): O-grid de blockMesh, división de la frontera lateral en 32 segmentos, snappyHexMesh con capas de suelo, checkMesh y estadísticas. Una sola malla sirve para las 16 direcciones. |
| `gen_case.py` | Crea un **caso de dirección** (θ, U10, modelo de turbulencia, z0) sobre una malla existente. El modelo es un parámetro: `realizableKE` / `kOmegaSST` / `kEpsilon`. |
| `campaign.py` | Planea (y con `--create --enqueue` crea y encola) las 16 direcciones con arranque en caliente encadenado. Las direcciones retenidas arrancan en frío. |
| `make_jobs.py` | Escribe el JSON de un trabajo para la cola (`E:\PINN\cola\jobs\1xx_zt_*.json`). |
| `split_lateral.py` | Divide el parche lateral del fondo en 32 `faceSet` por ángulo, que después usa `createPatch`. |
| `memwatch.ps1` | Muestrea la RAM de snappyHexMesh cada 5 s y registra el pico. **Guarda de RAM:** si la memoria disponible del sistema baja de 1.5 GB durante 3 muestras, mata snappy. |
| `mesh_stats.py` | Genera `mesh_stats.json`: celdas, calidad, cobertura de capas, altura de la primera celda, celda que contiene 1.75 m, tiempo y RAM pico. |
| `convcheck.py` | Criterio operativo de convergencia (revisión C7; ver §5.3). Lo usan el Allrun (para parar) y `verify_case.py`. |
| `warmstart.py` | Arranque en caliente desde la dirección vecina (§5.4). |
| `extract_h5.py` | Extrae el caso al HDF5 del contrato de datos (§6). |
| `homogeneity_zt.py` | Prueba de homogeneidad en el dominio vacío (§7.1). |
| `verify_mesh.py`, `verify_case.py` | Verificación independiente que exige la cola (exit 0 solo si todo está bien). |
| `timing.py` | Genera `timing.json` con s/iteración (mediana de las últimas 200 iteraciones), iteraciones y tiempo de reloj. |
| `ofio.py`, `zt_common.py`, `buildings.py` | Lectura y escritura de archivos OpenFOAM (ascii/binario), constantes, convención de dirección, entrada y SDF exacto. |

Uso típico:
```
python scripts/gen_mesh.py --variant base --level fine                      # -> E:\PINN\runs\zonatec\mesh_base_fine
python scripts/gen_case.py --mesh E:/PINN/runs/zonatec/mesh_base_fine --theta 112.5 --U10 5 --model realizableKE
python scripts/make_jobs.py --id 102 --kind mesh --case E:/PINN/runs/zonatec/mesh_base_fine
python scripts/make_jobs.py --id 103 --kind case --case E:/PINN/runs/zonatec/zt_base_th1125_U050_m1 --after 102_zt_mesh_base_fine
python scripts/campaign.py --mesh E:/PINN/runs/zonatec/mesh_base_fine --skip 112.5 135 --create --enqueue --start-id 110
```
Cada caso tiene un `Allrun` reanudable que cumple el contrato de la cola (`E:\PINN\cola\README.md`):
- marcas `.<paso>.ok`;
- `startFrom latestTime`, `writeInterval 200` y `purgeWrite 2`;
- al reanudar, borra un último tiempo incompleto;
- manda todo a stdout con `tee`;
- `set -e` + `pipefail`.

Los trabajos de malla siempre reinician snappy desde la malla de fondo intacta, así que un corte a media corrida no deja una malla medio refinada.

## 2. Dominio (H_best)
- `frame.json`: H_max = H_ref = 87.75 m (Fiesta Inn). Con la regla de `domain_circular_recommendation.md`, R = 545·√2 + 15·H_max = **2087 m** y la altura = 6·H_max = **526 m**.
  - El encargo decía 2049/511 m, que corresponde a una versión anterior con H_max = 85.2. Manda el archivo.
- El bloqueo en el peor caso es de 1.45 % (< 3 %; Franke et al. 2007).
- Un solo dominio circular por geometría. Da 15·H en todas las direcciones: sobrecumple los 5·H a barlovento y laterales, y los 15·H a sotavento que pide COST 732 (Franke et al. 2007).
- Edificios explícitos:
  - ZOI (246, `zonatec_<variante>_multisolid.stl`);
  - anillo (199, `zonatec_ring_multisolid.stl`), que llega hasta |x|, |y| = 575 m.
- Las bases de los edificios se hunden 1 m bajo el suelo al preparar el STL de snappy. Así ninguna cara queda coplanar con el suelo del dominio, lo que haría ambigua la intersección.
- La SDF y la altura local usan la geometría **sin** hundir, reconstruida exactamente de las tapas inferiores del STL multisólido.

## 3. Malla

### 3.1 Fondo: O-grid de blockMesh
- Bloque central cuadrado de ±576 m que cubre todos los edificios explícitos. Su suelo es el parche **`ground_zoi`**.
- 4 bloques exteriores con arcos hasta R; su suelo es **`ground_outer`**.
- Celdas de fondo cúbicas junto al suelo, de lado D0 = 1152/n_core, con gradación vertical (primera celda = D0, última ≈ 2·D0) y gradación radial en los bloques exteriores (de D0 hasta el tamaño tangencial en R).
- La primera celda vertical es exactamente D0 para que el refinamiento isótropo de snappy dé cubos de D0/2^L junto al suelo.

### 3.2 Por qué refinamiento isótropo más capas de suelo (y no un fondo anisótropo)
El octree de snappyHexMesh divide cada celda en 8, así que **conserva la relación de aspecto del fondo**.
- **Opción (b) de la revisión C4, descartada.** Graduar el fondo en vertical (p. ej., 32 × 32 × 8 m para obtener 2 × 2 × 0.5 m en el nivel 4) arrastra esa anisotropía a todo el volumen refinado. Cualquier refinamiento por superficie (edificios) o por caja por encima del suelo cuesta 4 veces más celdas.
  - Con el presupuesto de la ZOI (850 × 850 m) eso da más de 6 M de celdas solo en la ZOI y en los aislamientos alrededor de los edificios.
  - La RAM de 16 GB (de la que en la práctica quedan ~6 GB libres con los demás procesos; ver §7.2) no lo permite.
- **Elegido (opción (a) de C4).** Cubos isótropos de 2 m en la capa peatonal de la ZOI y **3 capas prismáticas** de snappy (`addLayers`) solo sobre `ground_zoi`:
  - primera capa de 0.2·Δ4 = **0.40 m**, razón de expansión 1.2 (0.40 / 0.48 / 0.58 m, 1.46 m en total);
  - así el nivel peatonal de 1.75 m cae en la **4.ª celda** desde el suelo (la AIJ pide la 3.ª o más; Tominaga et al. 2008);
  - el primer centroide queda a 0.2 m, por encima de z0 (Blocken et al. 2007).
  - `mesh_stats.py` verifica esto columna por columna en la zona de evaluación.
  - Riesgo conocido: las capas colapsan junto al pie de los edificios. La cobertura sale en el log de snappy (§7.2).
- Parámetros de capa: `nLayerIter 12` y `nRelaxedIter 6`. En la prueba xcoarse, las 50 iteraciones por defecto no llegaban nunca a 0 caras ilegales y se llevaban el 83 % del tiempo de snappy.

### 3.3 Niveles de refinamiento (malla fina, D0 = 32 m)

| Región | Nivel | Tamaño | Extensión |
|---|---|---|---|
| Fondo | 0 | 32 m (radial hasta 89 m en R) | todo el dominio |
| `L1_cyl` | 1 | 16 m | cilindro r ≤ 1300 m, z ≤ 3·H_max = 263 m (flujo de aproximación) |
| `L2_box` | 2 | 8 m | ±720 m, z ≤ 1.5·H_max = 132 m |
| `L3_ring` | 3 | 4 m | ±600 m, z ≤ 32 m (ZOI + anillo) |
| Torres (6 edificios > 30 m, `buildings.towers`) | 3 | ≤ 4 m | huella + 1·H de margen, hasta 1.5·H (revisión G6; coincide con `tower_refinement_regions.csv`, más el edificio de 47.6 m del anillo) |
| `L4_zoi` | 4 | **2 m** | ±460 m, z ≤ 8 m (capa peatonal de toda la ZOI, incluidos los edificios de la ZOI que llegan a 455 m) |
| Superficie `bld_zoi` | 4 | 2 m | todas las caras de la ZOI: ≥ 12 celdas por lado en las torres de 25-46 m (Tominaga 2008: ≥ 10) |
| Superficie `bld_ring` | 3 | 4 m | edificios del anillo |
| Capas de suelo | — | 0.40/0.48/0.58 m | `ground_zoi` |

`nCellsBetweenLevels 3`, bordes (`features`) resueltos al nivel de su superficie y `explicitFeatureSnap`. La calidad sigue `caseDicts/meshQualityDict` (no ortogonalidad ≤ 65°).
Guarda: `maxGlobalCells 9e6`.

### 3.4 Mallas del GCI (Celik et al. 2008)
Se cambia D0 con las mismas regiones físicas y los mismos niveles. Así el refinamiento es sistemático en las tres direcciones, incluidas las capas (primera capa = 0.2·Δ4).

| Nivel | n_core | D0 | Δ4 (peatonal) | r respecto a la anterior | 1.ª capa | 1.75 m en la celda |
|---|---|---|---|---|---|---|
| fine (campaña) | 36 | 32.0 m | 2.00 m | — | 0.40 m | 4.ª |
| medium | 27 | 42.7 m | 2.67 m | 1.333 | 0.53 m | 3.ª |
| coarse | 20 | 57.6 m | 3.60 m | 1.350 | 0.72 m | 3.ª |

La malla de campaña es la **fina**: una de 8 M o más no cabe en 16 GB. La malla gruesa sigue cumpliendo la regla de «1.75 m en la 3.ª celda o más».

### 3.5 Frontera lateral en 32 segmentos
- `split_lateral.py` asigna cada cara lateral a un segmento de 11.25° según el ángulo de su centro. Los bordes de los segmentos quedan en múltiplos de 11.25°.
- Para las 16 direcciones (múltiplos de 22.5°), la línea U·n = 0 (a ±90° del viento) cae **exactamente en un borde de segmento**, así que ningún segmento queda mitad entrada y mitad salida. Con caras de fondo de ~2.5°, el error de asignación es de media cara como máximo.
- Con 16 segmentos también se cumpliría, pero con 32 el borde de salida sigue la curva con la mitad de error angular. Además, admite direcciones intermedias cada 11.25° sin remallar.
- Rol por dirección (`zt_common.segment_roles`): **entrada** si el promedio de U·n/|U| sobre el segmento es < 0.2; si no, **salida**.
  - El umbral de 0.2 pone también como entrada (Dirichlet con el perfil sin perturbar) a los dos segmentos casi paralelos del lado de salida (promedio de +0.098). Así se evita que un `inletOutlet` conmute entre entrada y salida donde el flujo es casi tangencial.
  - A 15·H de los edificios, el perfil sin perturbar es la condición de campo lejano correcta.
  - Resultado: 18 segmentos de entrada y 14 de salida.

## 4. Condiciones de frontera (`gen_case.py`)

| Parche | U | p | k | ε / ω | ν_t |
|---|---|---|---|---|---|
| Segmentos de entrada | `atmBoundaryLayerInletVelocity` (flowDir = e(θ), Zref = H_ref, Uref = U_RH(H_ref), z0 = z0_fetch, d = 0) | zeroGradient | `atmBoundaryLayerInletK` | `atmBoundaryLayerInletEpsilon/Omega` | calculated |
| Segmentos de salida | inletOutlet (0) | fixedValue 0 | inletOutlet (k0) | inletOutlet | calculated |
| `top` | **fixedShearStress** τ = u*²·e(θ) | zeroGradient | zeroGradient | zeroGradient | calculated |
| `ground_outer` | noSlip | zeroGradient | kqRWallFunction | `atmEpsilonWallFunction`/`atmOmegaWallFunction`, z0 = **z0_fetch(θ)** | `atmNutkWallFunction`, z0 = z0_fetch(θ) |
| `ground_zoi` | noSlip | zeroGradient | kqRWallFunction | ídem, z0 = **z0_zoi = 0.05 m** | `atmNutkWallFunction`, z0 = 0.05 m |
| `bld_zoi`, `bld_ring` | noSlip | zeroGradient | kqRWallFunction | epsilon/omegaWallFunction | nutkWallFunction (paredes lisas) |

- **Entrada (P12, P14):**
  - u* y z0 salen de `climate/transfer.py` (dos capas con altura de mezcla de 60 m; z0 de Macdonald con huellas de Overture) para (θ, U10).
  - Se impone **d = 0**, como manda P12. El d de Macdonald se guarda solo como atributo.
  - Richards y Hoxey (1993): U = u*/κ·ln((z + z0)/z0), k = u*²/√Cμ, ε = u*³/(κ(z + z0)), con κ = 0.41 y Cμ = 0.09.
- **Techo:** es la configuración que pasó la homogeneidad en escala de túnel (agente AIJ, caso `hom_rke_rh2atm`; tutorial de v2306 `atmDownstreamDevelopment`, Hargreaves y Wright 2007): esfuerzo cortante constante τ = u*² y gradiente nulo en k, ε y ω (Richards y Hoxey 1993).
  - Con k-ε estándar se usa **σε = 1.167** = κ²/((C2 − C1)√Cμ) para κ = 0.41 (revisión C1).
  - Con realizable se dejan las constantes por defecto (σε = 1.2 frente a 1.19 consistente; revisión §7.6).
- **Suelo en dos parches (revisión C6):**
  - `ground_outer` usa la misma z0 que la entrada: es la condición de homogeneidad de Richards y Norris (2011) y Blocken et al. (2007), para que el flujo de aproximación de 1.3 km llegue sin cambios.
  - `ground_zoi` usa una z0 local de **0.05 m** entre los edificios explícitos:
    - calles y estacionamientos pavimentados dan 0.01-0.03 m y el pasto corto del campus 0.03 m (Wieringa 1992);
    - el mobiliario urbano, los autos y los árboles aislados, que no se modelan, lo suben;
    - 0.05 m es el punto medio defendible de la clase «abierta-rugosa». Los edificios, que son la rugosidad principal, están explícitos (nota de P12).
    - El salto de z0 en ±576 m es físico: forma una capa límite interna sobre los edificios del anillo.
    - Sensibilidad: `--z0-zoi 0.03` o `0.1`.
  - En los dos parches se cumple z_P > z0 (primer centroide de 0.2 m en la ZOI y de ≥ 4 m fuera; Blocken et al. 2007).
- **Sensibilidad de z0 de la entrada (revisión G2):** `--z0-fetch 0.5` o `1.0` en 112.5° sobre la misma malla.

## 5. Numérica

### 5.1 Esquemas y algoritmo
- **Etapa 1** (300 iteraciones, solo en arranque en frío): upwind acotado, SIMPLE con p 0.3, U 0.7 y turbulencia 0.7.
- **Etapa 2:**
  - `bounded Gauss linearUpwind grad(U)` para U y `limitedLinear 1` para k, ε y ω;
  - gradientes `cellLimited Gauss linear 1`;
  - `limited corrected 0.33` en laplacianos y snGrad (no ortogonalidad de snappy ≤ 65°);
  - SIMPLEC con p 1, U 0.6 y turbulencia 0.6 (ajustable con `--relax`).
- Nada de primer orden en la solución final (Franke et al. 2007; Blocken 2015).
- `residualControl` a 1e-5 como parada natural.

### 5.2 Inicialización
- **En frío:** `setExprFields` impone en todo el dominio la solución horizontalmente homogénea de Richards y Hoxey (U log en la dirección e(θ), k0, ε(z)).
  - Es la solución exacta del flujo de aproximación. potentialFoam daría un campo irrotacional sin cortante junto al suelo, así que empezar del log reduce el transitorio del campo lejano, que es la mayor parte del volumen.
- **En caliente:** §5.4.

### 5.3 Convergencia (revisión C7): `convcheck.py`
Convergido ⇔ ninguna de las 3 condiciones falla:
1. sin NaN;
2. **balance de masa** |Σφ| / Σφ_entrada < 1e-4, con los 33 parches abiertos (un `surfaceFieldValue` por parche; v2306 no acepta listas de parches);
3. **(A)** todos los residuos iniciales finales (p, Ux, Uy, Uz, k, ε/ω) < 1e-4, **o (B)** ≥ 500 iteraciones de segundo orden, cada uno de los 10 monitores a 1.75 m y 2 sobre el centro con max − min de cada componente de U en las últimas 500 iteraciones **< 1 % de U_H** (absoluto: en las estelas |U| ≈ 0), y residuo máximo < 1e-3 (estancamiento, no divergencia).

Se aplica el mismo criterio a los arranques en caliente.
El Allrun corre la etapa 2 en bloques de 500 iteraciones y evalúa el criterio entre bloques. Se detiene al cumplirlo o en 4000 iteraciones.

### 5.4 Arranque en caliente (`warmstart.py`)
- Copia celda por celda los campos convergidos de la dirección anterior: la malla es la misma, se verifica por número de celdas.
- **Rota el vector U en su sitio** por −Δθ. Como el flujo ABL sin perturbar no depende de (x, y), el campo lejano queda **exactamente** en la nueva dirección; solo el flujo alrededor de los edificios tiene que volver a desarrollarse.
- Si cambia U10, escala por u*: U·f, k·f², ε·f³, ν_t·f y p·f² (independencia de Re).
- Sin etapa de primer orden.
- Las 4 direcciones retenidas se arrancan **en frío** para que no hereden la solución vecina (revisión M9).
- El ahorro medido está en §7.4.

## 6. Extracción al contrato de datos (`extract_h5.py`)
- Salida: `v2/data/processed/<case_id>.h5` (p. ej., `zt_base_th1125_U050_m1.h5`).
- **Datos:** celdas de la caja ZOI (|x|, |y| ≤ 425 m, 0 ≤ z ≤ 2·H_max = 175.5 m).
  - Campos: `x y z u v w p k nut epsilon|omega vol wall_dist sdf is_wall_adjacent` y además `cell_id` y `local_height`.
  - `p` es cinemática.
  - `wall_dist` es la de OpenFOAM (meshWave, suelo + edificios).
  - `sdf` es la SDF **exacta** de prismas LOD1, con la misma fórmula que `geometry/sdf.ExactPrismSDF`. `buildings.exact_sdf` es la versión vectorizada; se verificó que su diferencia con `ExactPrismSDF` es 0.0 en 300 puntos.
- **Grupos:**
  - `wall_faces`: `x y z nx ny nz area kind`, con kind 0 = suelo y 1 = edificio, y la normal unitaria hacia afuera del fluido;
  - `inlet_profile`: `z u k eps omega`, tal como se impuso.
- **Atributos:** los del contrato más h_ref, u_h, T_transfer, z0_method, d_morph, z0_ground_zoi, z0_fetch, sdf_version, region, mesh_case, n_cells_mesh y convergence_report.

**Cambio propuesto al contrato:** está en el reporte final y en §9. No se editó `DATA_CONTRACT.md`.

## 7. Resultados del piloto
*(se llena con las corridas; ver `results/` y los `*.json` de cada caso)*

### 7.1 Homogeneidad a escala real (dominio vacío, malla y condiciones de campaña)
Pendiente.

### 7.2 Malla fina de la geometría base
Pendiente.

### 7.3 Dirección 112.5° (ESE), U10 = 5 m/s
Pendiente.

### 7.4 Arranque en caliente (135° desde 112.5°)
Pendiente.

## 8. Costo medido y estimación de la campaña
Pendiente.

## 9. Pendientes y limitaciones
Pendiente.

## Referencias
- Blocken, B. (2015). Computational Fluid Dynamics for urban physics: Importance, scales, possibilities, limitations and ten tips and tricks towards accurate and reliable simulations. *Building and Environment*, 91, 219-245.
- Blocken, B., Stathopoulos, T., y Carmeliet, J. (2007). CFD simulation of the atmospheric boundary layer: wall function problems. *Atmospheric Environment*, 41, 238-252.
- Celik, I. B., et al. (2008). Procedure for estimation and reporting of uncertainty due to discretization in CFD applications. *Journal of Fluids Engineering*, 130, 078001.
- Franke, J., Hellsten, A., Schlünzen, H., y Carissimo, B. (2007). *Best practice guideline for the CFD simulation of flows in the urban environment*. COST Action 732.
- Hargreaves, D. M., y Wright, N. G. (2007). On the use of the k-ε model in commercial CFD software to model the neutral atmospheric boundary layer. *JWEIA*, 95, 355-369.
- Richards, P. J., y Hoxey, R. P. (1993). Appropriate boundary conditions for computational wind engineering models using the k-ε turbulence model. *JWEIA*, 46-47, 145-153.
- Richards, P. J., y Norris, S. E. (2011). Appropriate boundary conditions for computational wind engineering models revisited. *JWEIA*, 99, 257-266.
- Tominaga, Y., Mochida, A., Yoshie, R., Kataoka, H., Nozu, T., Yoshikawa, M., y Shirasawa, T. (2008). AIJ guidelines for practical applications of CFD to pedestrian wind environment around buildings. *JWEIA*, 96, 1749-1761.
- Wieringa, J. (1992). Updating the Davenport roughness classification. *JWEIA*, 41-44, 357-368.
