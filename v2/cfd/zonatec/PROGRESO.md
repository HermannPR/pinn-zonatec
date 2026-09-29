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
