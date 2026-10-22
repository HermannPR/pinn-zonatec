"""Interpolacion clasica en theta (lineal, spline periodico, GP periodico), en marco fijo y marco del viento.
Evalua en test-direction(-fino) base m1 y LOO sobre train. Mismas celdas en todos los casos (malla m1 compartida)."""
import csv, json, math, sys, pathlib
import numpy as np, h5py

V2 = pathlib.Path(sys.argv[1]); N = int(sys.argv[2]) if len(sys.argv) > 2 else 300_000
filas = [r for r in csv.DictReader(open(V2 / "data/processed/manifest.csv"))
         if r["variant"] == "base" and r["mesh_id"] == "m1" and float(r["U10"]) == 5.0]
rng = np.random.default_rng(1)
with h5py.File(V2 / filas[0]["path"]) as f:
    n = f["x"].shape[0]; cid0 = f["cell_id"][...]; z_all = f["z"][...]
idx = np.sort(rng.choice(n, min(N, n), replace=False)); z = z_all[idx]
peat = z <= 3.0

def cargar(r):
    with h5py.File(V2 / r["path"]) as f:
        assert np.array_equal(f["cell_id"][...], cid0), r["case_id"]
        uh = float(f.attrs["u_h"]); F = np.stack([f[c][...][idx] for c in "uvwp"], 1)
    F[:, :3] /= uh; F[:, 3] /= uh**2
    return F

casos = {r["case_id"]: (float(r["theta_deg"]), r["split"], cargar(r)) for r in filas}
train = sorted([(t, F) for k, (t, s, F) in casos.items() if s == "train"], key=lambda a: a[0])
alto = z > np.quantile(z, 0.95)

def phi(F):   # direccion del flujo (rad) con las celdas altas
    return math.atan2(F[alto, 1].mean(), F[alto, 0].mean())

def a_viento(F, ph):
    G = F.copy(); c, s = math.cos(ph), math.sin(ph)
    G[:, 0], G[:, 1] = c * F[:, 0] + s * F[:, 1], -s * F[:, 0] + c * F[:, 1]
    return G

def de_viento(G, ph):
    return a_viento(G, -ph)

def pesos_lineal(ths, t):
    d = (np.asarray(ths) - t) % 360
    a = int(np.argmax(np.where(d > 180, d - 360, -np.inf))); b = int(np.argmin(np.where(d > 0, d, np.inf)))
    if np.isclose(d[b], 0) or np.isclose(d[b], 360): w = np.zeros(len(ths)); w[b] = 1; return w
    da, db = (t - ths[a]) % 360, (ths[b] - t) % 360
    w = np.zeros(len(ths)); w[a] = db / (da + db); w[b] = da / (da + db); return w

def pesos_gp(ths, t, ell=0.6, ruido=1e-6):
    """GP con kernel periodico exp(-2 sin^2(dtheta/2)/ell^2): pesos = k*^T K^-1 (media cero sobre la media de train)."""
    th = np.radians(ths); tt = math.radians(t)
    K = np.exp(-2 * np.sin((th[:, None] - th[None]) / 2) ** 2 / ell**2) + ruido * np.eye(len(th))
    k = np.exp(-2 * np.sin((th - tt) / 2) ** 2 / ell**2)
    w = np.linalg.solve(K, k)
    m = np.ones(len(th)) / len(th)
    return w + m * (1 - w.sum())   # la parte no explicada va a la media de train

def pesos_spline(ths, t):
    """Spline cubico periodico natural en theta (no uniforme): pesos por interpolar las bases unitarias."""
    th = np.radians(np.asarray(ths)); tt = math.radians(t); m = len(th)
    h = np.diff(np.r_[th, th[0] + 2 * math.pi])
    A = np.zeros((m, m)); Bm = np.zeros((m, m))
    for i in range(m):
        hp, hn = h[i - 1], h[i]
        A[i, i - 1] += hp / 6; A[i, i] += (hp + hn) / 3; A[i, (i + 1) % m] += hn / 6
        Bm[i, (i + 1) % m] += 1 / hn; Bm[i, i] -= 1 / hn + 1 / hp; Bm[i, i - 1] += 1 / hp
    M = np.linalg.solve(A, Bm)                      # segundas derivadas = M @ y
    x = (tt - th[0]) % (2 * math.pi) + th[0]
    j = int(np.searchsorted(np.r_[th, th[0] + 2 * math.pi], x, side="right") - 1); j = min(j, m - 1)
    j2 = (j + 1) % m; hj = h[j]; a = (th[j] + hj - x) / hj; b = 1 - a
    w = np.zeros(m); w[j] += a; w[j2] += b
    w += ((a**3 - a) * M[j] + (b**3 - b) * M[j2]) * hj**2 / 6
    return w

def predecir(tr, t, metodo, marco):
    ths = [a for a, _ in tr]; Fs = [F for _, F in tr]
    w = {"lineal": pesos_lineal, "spline": pesos_spline, "gp": pesos_gp}[metodo](ths, t)
    if marco == "fijo":
        return sum(wi * F for wi, F in zip(w, Fs))
    phs = [phi(F) for F in Fs]
    # direccion del flujo destino: interpola el angulo (desenvuelto respecto a la vecina mas cercana)
    ph_t = math.atan2(sum(wi * math.sin(p) for wi, p in zip(w, phs)), sum(wi * math.cos(p) for wi, p in zip(w, phs)))
    G = sum(wi * a_viento(F, p) for wi, F, p in zip(w, Fs, phs))
    return de_viento(G, ph_t)

def err(P, F):
    dv = P[:, :3] - F[:, :3]; sp, sr = np.linalg.norm(P[:, :3], axis=1), np.linalg.norm(F[:, :3], axis=1)
    return float(np.sqrt((dv**2).sum() / (F[:, :3] ** 2).sum())), float(np.abs(sp - sr)[peat].mean())

res = {}
metodos = [(m, k) for m in ("lineal", "spline", "gp") for k in ("fijo", "viento")]
for cid, (t, s, F) in sorted(casos.items(), key=lambda a: a[1][0]):
    if s.startswith("test-direction"):
        res[cid] = {"split": s, **{f"{m}/{k}": err(predecir(train, t, m, k), F) for m, k in metodos}}
    elif s == "train":
        tr = [(a, G) for a, G in train if a != t]
        res[cid] = {"split": "loo", **{f"{m}/{k}": err(predecir(tr, t, m, k), F) for m, k in metodos}}
cols = [f"{m}/{k}" for m, k in metodos]
print("caso split " + " ".join(cols))
for cid, r in res.items():
    print(cid[8:14], r["split"][:10], " ".join(f"{r[c][0]:.3f}" for c in cols))
for g in ("test-direction", "test-direction-fino", "loo"):
    sel = [r for r in res.values() if r["split"] == g]
    print("MEDIA", g, " ".join(f"{np.mean([r[c][0] for r in sel]):.3f}" for c in cols),
          "| peaton", " ".join(f"{np.mean([r[c][1] for r in sel]):.3f}" for c in cols))
json.dump(res, open(sys.argv[3] if len(sys.argv) > 3 else "clasicos.json", "w"), indent=1)
