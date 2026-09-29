# PROGRESO — AIJ Caso A (bitácora corta)

- 2026-09-28: se obtuvieron los datos (Zenodo, CC BY 4.0), se escribieron los scripts y se hicieron las pruebas de sintaxis 2D. Homogeneidad: 18 casos 2D, incluidas las correcciones C1 (techo con `fixedShearStress`, σε = 1.167) y C2 (calibración de la entrada en 1 pasada).
- 2026-09-28 20:24: cola `020_aij_bld_rke_M` → DONE y verificado.
- 2026-09-28 22:38: `021_aij_bld_sst_M` → FAILED (sin converger). Hay un ciclo límite de ~125 iteraciones; en la sonda 7 (lateral de la estela, z = 0.01 m) el rango es de 0.25 U_H.
- 2026-09-28 23:31: `022_aij_bld_ske_M` en curso.
- 2026-09-29: se prepara la continuación promediada de SST (`add_mean_sampling.py`, iteraciones 4000 → 5000, fieldAverage), trabajo `023_aij_bld_sst_M_mean` detrás de 022. `post_aij.py --mean` usa los conjuntos promediados.
