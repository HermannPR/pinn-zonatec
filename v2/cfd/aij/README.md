# Validación CFD: AIJ Caso A (edificio aislado 1:1:2)

Estado: **preparado, sin correr todavía** (se espera la instalación de OpenFOAM, ver `E:\PINN\tools\OPENFOAM_SETUP.md`).
Todo lo de abajo marcado *pendiente* se llena con los resultados reales; aquí no hay ninguna cifra de CFD todavía.

## 1. Datos (P22-C)
- Fuente usada: publicación oficial AIJ en Zenodo, **CC BY 4.0**, DOI 10.5281/zenodo.15050147 (Ishihara, Hibi, Tominaga, Kikumoto, Okaze, 2025). Detalle, sumas MD5 y lo que falló (la página de la AIJ está detrás de un reto JavaScript de AWS WAF) en `data/raw/SOURCE.md`. Se verificó que coincide con el xls histórico de la AIJ (copia del Internet Archive, 2013).
- Verificado: b = 0.08 m, H = 2b = 0.16 m, Re_H ≈ 24 000, U_H = 4.491 m/s (perfil de entrada a z = H). 186 puntos de hilo caliente (U, V, W, k): plano vertical y = 0 (66) y planos horizontales z/b = 0.125 (z = 0.01 m, 60) y z/b = 1.25 (60), todos en y ≤ 0.
- Perfil de entrada: 24 alturas de 0.005 a 0.60 m (capa límite δ ≈ 0.6 m). Ajuste por mínimos cuadrados (`scripts/prepare_data.py` → `data/processed/inflow_fit.json`):
  - Ley de potencia con U_H fijo: α = 0.267 sobre toda la capa (z ≤ 0.6 m), lo que confirma el α = 0.27 nominal (categoría IV de la AIJ); con z ≤ 0.16 m sale α = 0.16.
  - Ley logarítmica: u* = 0.13 a 0.28 m/s y z0 = 0.0007 a 0.18 mm según el rango de ajuste (z ≤ 0.02 a 0.35 m). El k de equilibrio que implica, k = u*²/√Cμ = 0.05 a 0.26 m²/s², es **2.5 a 7 veces menor** que el k medido (0.37 a 0.66). El perfil del túnel **no** es una capa superficial de equilibrio de Richards y Hoxey: la turbulencia la generan agujas y vallas.
- Longitudes de readherencia experimentales: X_R/b = 0.52 (techo, desde el borde de barlovento) y X_F/b = 1.42 (estela, desde la fachada de sotavento), según Tominaga et al. (2004, JAABE 3:63-70, tabla 1, que cita a Ishihara y Hibi, 1998). Es la misma comparación cruzada del grupo de trabajo de la AIJ que resume Tominaga et al. (2008). No se pudo leer el texto completo de Tominaga et al. (2008, JWEIA 96:1749) ni de Tominaga et al. (2008, JWEIA 96:389) porque son de pago; el manuscrito de la guía que sí se leyó no trae la tabla del Caso A. Las cifras de los datos crudos no permiten estimar X_R (no hay puntos dentro de la burbuja del techo). X_F se puede acotar con los puntos a z/b = 0.125: U cambia de signo entre x/b = 1.25 y 2.0, así que X_F/b ≈ 1.3 por interpolación lineal, lo que es consistente con 1.42.

## 2. Configuración del caso (`scripts/gen_case.py`)
| Aspecto | Elección | Justificación / referencia |
|---|---|---|
| Dominio | x ∈ [−0.84, 2.04] m (5H a barlovento, 12.5H a sotavento), y = ±0.84 m (5H libres), z ≤ 0.96 m (5H sobre el techo); bloqueo 0.79 % | Tominaga et al. (2008) §3.1: ≥ 5H laterales y arriba, ≥ 10H detrás, bloqueo < 3 %. La AIJ usó el túnel (21.5b × 13.75b × 11.25b). |
| Malla | hexaedros estructurados, blockMesh con 17 bloques alrededor del hueco del edificio. Media: 691 800 celdas, 20 celdas por lado de b, 30 en 0-H, celda mínima de 2 mm en aristas y suelo, razón de crecimiento ≤ 1.15. Gruesa (f = 0.77): 324 k; fina (f = 1.3): 1.55 M | El edificio es una caja alineada con los ejes, así que una malla hexa conforme da ortogonalidad perfecta, aristas exactas y ninguna capa fallida de snappy. El refinamiento sistemático (mismo reparto, N×f) es el que pide el GCI (r ≈ 1.3, Celik et al. 2008). Se cumple ≥ 10 celdas por lado y razón ≤ 1.3 (AIJ §4.1), y el punto peatonal z = 0.01 m cae en la 5.ª celda (≥ 3.ª). |
| Entrada | **tabla medida** (`fixedProfile`): U(z) y k(z) medidos; ε = Cμ^½ k dU/dz (P_k = ε, AIJ ec. 8, con dU/dz de un polinomio cúbico en ln z); ω = ε/(Cμ k). Por debajo de 5 mm, ley log por los 3 puntos inferiores; por encima de 0.5 m, escala de longitud constante | Es la práctica de la AIJ para el Caso A (Tominaga et al. 2004, ap. 1). La alternativa de Richards y Hoxey no puede reproducir a la vez U y k medidos (§1). Además, la ley log extrapolada hasta el techo del dominio daría 5 m/s a 0.6 m frente a 6.75 medidos. La variante log (u* = 0.204, z0 = 0.028 mm, ajuste z ≤ H) solo se prueba en el dominio vacío (§4). |
| Suelo | `atmNutkWallFunction` con z0 = 1.125·10⁻³ H = 0.18 mm (valor fijado por la AIJ para el Caso A) + `atmEpsilonWallFunction`/`atmOmegaWallFunction` con el mismo z0 | La AIJ usó una ley log con z0 y u* tomado del k medido junto al suelo, y verificó que el perfil se mantiene hasta la salida. Con z0 = 0.18 mm, la rugosidad de grano de arena equivalente sería ks = 9.793 z0/Cs = 3.5 mm (Cs = 0.5), mayor que la primera celda (2 mm): por eso se usa la forma en z0 (Blocken et al. 2007; Richards y Norris 2011), igual que en P12. Como sensibilidad se corre un suelo liso (`nutkWallFunction`). |
| Edificio | paredes lisas: `nutkWallFunction`, `epsilon/omegaWallFunction`, `kqRWallFunction` | AIJ ap. 1 (5). |
| Techo del dominio | `slip` con la tabla (el techo está en la corriente libre del túnel, por encima de δ ≈ 0.6 m, sin esfuerzo cortante). En la variante log se fijan U, k, ε/ω del perfil ABL en el techo | Richards y Hoxey (1993) piden imponer el esfuerzo τ = ρu*² arriba para mantener una capa log. Eso no aplica a una capa límite de espesor finito dentro de un túnel. |
| Laterales / salida | `symmetry` / p = 0 con U `inletOutlet` y gradiente nulo | AIJ §5.2-5.3. |
| Esquemas | etapa 1: upwind (300 it.); etapa 2: `linearUpwind grad(U)` para U y `limitedLinear 1` para k, ε, ω; gradientes `cellLimited` | AIJ §6.2 y COST 732: nada de primer orden en la solución final. |
| Algoritmo | SIMPLEC (`consistent yes`), relajación U 0.7, turbulencia 0.6; parada con residuos < 1e-5 o 4000 iteraciones; estabilidad de 10 monitores en las últimas 500 iteraciones | Criterio del encargo y del PLAN (F2). |
| Modelos | `realizableKE`, `kOmegaSST`, `kEpsilon` (constantes por defecto de OpenFOAM, κ = 0.41) | P16. |

## 3. Métricas (`scripts/post_aij.py`)
Todo se normaliza con U_H = 4.491 m/s.
- **Tasa de acierto** (VDI 3783-9): hay acierto si |P−O|/|O| ≤ D = 0.25 o si |P−O| ≤ W. La VDI toma W de la repetibilidad de cada conjunto de referencia, y la publicación del Caso A no la reporta. Por eso se usa **W = 0.05** (velocidad normalizada, ≈ 0.22 m/s, del orden de la incertidumbre de un hilo caliente) y se reporta también q con W = 0 y con W = 0.10. Se calcula por componente (U, V, W en los 186 puntos, como hace la VDI) y para la rapidez |U| a nivel peatonal. La meta del PLAN es q ≥ 0.66.
- FAC2, NMSE y FB (Chang y Hanna, 2004) sobre cantidades positivas: |U| y k.
- Readherencia en la primera celda sobre y = 0.

## 4. Prueba de homogeneidad (dominio vacío 2D, misma malla en x-z)
*Pendiente.* Casos `hom_<modelo>_<entrada>_<suelo>`: 3 modelos × {tabla + suelo rugoso, tabla + suelo liso, log RH + suelo rugoso}. Se reporta ΔU y Δk entre la entrada, x = 0 (posición del edificio) y la salida para z ≤ H y z ≤ 0.3 m (`results/homogeneity.csv`).

## 5. Resultados por modelo
*Pendiente.*

| Modelo | celdas | iteraciones / tiempo | q_U (W=0.05) | q_|U| peatonal | FAC2 |U| | NMSE | FB | X_R/b | X_F/b |
|---|---|---|---|---|---|---|---|---|---|
| Exp. | | | | | | | | 0.52 | 1.42 |

## 6. Cómo correr
```
python scripts/prepare_data.py                      # datos -> data/processed
powershell -File scripts/make_cases.ps1 -Set all     # genera casos en E:\PINN\runs\aij
powershell -File scripts/run_queue.ps1 -Detach -Cases hom_rke_table_rough,...   # corre en segundo plano, prioridad BelowNormal
python scripts/homogeneity.py --cases E:/PINN/runs/aij/hom_*
python scripts/post_aij.py --cases E:/PINN/runs/aij/bld_rke_M E:/PINN/runs/aij/bld_sst_M E:/PINN/runs/aij/bld_ske_M --tag M
```
Bitácoras en `E:\PINN\logs\aij_<caso>.log`; marcador `DONE`/`FAILED` en cada caso. Figuras en `E:\PINN\runs\aij\figs`.

## Referencias
Blocken, Stathopoulos y Carmeliet (2007) Atmos. Environ. 41:238 · Celik et al. (2008) J. Fluids Eng. 130:078001 · Chang y Hanna (2004) Meteorol. Atmos. Phys. 87:167 · Kikumoto et al. (2026) Jpn. Archit. Rev. 9:e70083 · Meng y Hibi (1998) J. Wind Eng. JAWE 76:55 · Richards y Hoxey (1993) JWEIA 46-47:145 · Richards y Norris (2011) JWEIA 99:257 · Tominaga et al. (2004) JAABE 3:63 · Tominaga et al. (2008) JWEIA 96:1749 · VDI 3783 Blatt 9 (2017).
