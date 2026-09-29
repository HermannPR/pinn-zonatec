# PROGRESO — agente CFD Zona Tec (notas para reanudar)

## 2026-09-28
- Leidos: DECISIONES, PLAN, DATA_CONTRACT, F1_revision, cola/README, of_env/of_run, geometry README + H_best, transfer.py, aij/gen_case.py, tutorial atmDownstreamDevelopment.
- Datos clave: H_max = 87.75 m (frame.json) -> R = 2087 m, altura 526 m (NO 2049/511 del encargo; el archivo manda).
  STL multisolid: base (ZOI, 246 edificios, hasta +-455 m) + ring (199, hasta +-575 m). Base de edificios en z = 0.
- Benchmark autoritativo (OPENFOAM_SETUP.md): 1M celdas kEpsilon 2.77 s/it serie, 1.10 s/it 6 rangos, ~1.3 GiB.
- SST no convergio en AIJ (oscila); realizableKE AIJ OK. Modelo = parametro.
- Cola: correr 1xx despues de 022_aij_bld_ske_M. Solo pruebas directas < 2 min mientras la cola esta ocupada.

## Diseno elegido (resumen; detalle en README.md)
- blockMesh O-grid (bloque central cuadrado +-576 m = ground_zoi; 4 bloques exteriores con arcos = ground_outer).
- Fondo cubico Delta0 (fina 32 m); snappy isotropo niveles 1-4 (16/8/4/2 m); capas de suelo (3) solo en ground_zoi.
- Frontera lateral partida en 32 segmentos (bordes en multiplos de 11.25 deg -> el cambio de signo de U.n cae justo en un borde para las 16 direcciones).
- Mallas GCI: n central = 36/27/20 -> Delta0 = 32/42.7/57.6 m (r = 1.333, 1.35).

## 2026-09-28 23:58
- Escritos y probados (malla xcoarse, corridas directas < 2 min): scripts/ofio.py, zt_common.py, buildings.py (SDF exacto
  vectorizado = sdf.ExactPrismSDF, diff 0.0), gen_mesh.py, split_lateral.py, memwatch.ps1, mesh_stats.py, gen_case.py,
  convcheck.py, warmstart.py (probado 112.5 -> 135), timing.py, verify_mesh.py, verify_case.py, make_jobs.py.
- Hallazgos de las pruebas: meshQualityDict de v2306 no trae errorReduction/nSmoothScale (agregados); surfaceFieldValue
  v2306 solo acepta un parche -> un FO flux_<parche> por segmento; capas: 50 iteraciones sin 0 caras ilegales -> 83 % del
  tiempo de snappy, se limita a nLayerIter 12 / nRelaxedIter 6.
- RAM disponible real con AIJ + otros procesos: ~6.2 GB (no 11). Guardia de memwatch: 1500 MB (AvailableMBytes).
- ENCOLADO: 100_zt_mesh_empty_fine (after 022) -> 101_zt_empty_th1125_U050_m1_hom (realizableKE, z0_zoi = z0 fetch).
- Pendiente: extract_h5.py, homogeneity_zt.py, malla base fina (102) + caso 112.5 (103), README.

## 2026-09-29 00:05
- Encolados: 100 malla vacia fina -> 101 homogeneidad (rke, z0_zoi = fetch; al final corre homogeneity_zt.py);
  102 malla base fina (after 022, independiente de 101) -> 103 piloto 112.5 (frio, log-law init) -> 104 135 (caliente desde 103).
- extract_h5.py probado en xcoarse (HDF5 OK). campaign.py: plan de 16 direcciones (retenidas en frio).
- Si 022 (AIJ ske) queda FAILED, 100 y 102 quedan bloqueados por 'after': quitar el after de sus JSON.
- Siguiente: README.md; esperar resultados; llenar cifras (mesh_stats.json, homogeneity.json, timing.json, convergence.txt).
