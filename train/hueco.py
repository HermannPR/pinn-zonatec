import sys, pathlib, numpy as np, h5py
sys.path.insert(0, sys.argv[2]); import interp_denso as I
V2 = pathlib.Path(sys.argv[1]); casos = I.malla(V2)
with h5py.File(casos[0][1]) as f: n = f["z"].shape[0]; z = f["z"][...]
idx = np.sort(np.random.default_rng(1).choice(n, 300_000, replace=False)); peat = z[idx] <= 3.0
D = [I.leer(c[1], idx)[0] for c in casos]; m = len(D)
for s in (1, 2, 4):   # vecinas a +-s pasos de 11.25: hueco 22.5, 45, 90
    E = [I.err(0.5 * D[(k - s) % m] + 0.5 * D[(k + s) % m], D[k], peat)[0] for k in range(m)]
    print(f"hueco {22.5*s:5.1f}: L2 medio {np.mean(E):.3f} max {np.max(E):.3f}")
