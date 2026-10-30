"""Entregable: interpolacion lineal en theta sobre la CFD densa (base m1 U050, 32 direcciones a 11.25 grados).

Campos adimensionales (u,v,w)/u_h y p/u_h^2 se interpolan entre las dos direcciones vecinas; u_h tambien se interpola en theta.
La velocidad escala lineal con U10 y la presion con U10^2 (similitud de Reynolds, validada contra el CFD a 10 m/s).

  consulta: python -I interp_denso.py consulta <V2> <theta_deg> <U10> <salida.h5>
  evaluar:  python -I interp_denso.py evaluar  <V2> [N_puntos] [salida.json]
"""
import csv, json, math, sys, pathlib
import numpy as np, h5py

CAMPOS = "uvwp"


def malla(V2, variant="base"):
    """Casos (theta, ruta, split) base m1 U050 ordenados por theta; un caso por direccion."""
    filas = [r for r in csv.DictReader(open(V2 / "data/processed/manifest.csv"))
             if r["variant"] == variant and r["mesh_id"] == "m1" and float(r["U10"]) == 5.0
             and not r["case_id"].endswith("_rs")]
    vistos = {}
    for r in filas:
        vistos.setdefault(float(r["theta_deg"]), (V2 / r["path"], r["split"], r["flag"]))
    return sorted((t, *v) for t, v in vistos.items())


def vecinos(ths, t):
    """Indices y pesos de las dos direcciones que encierran t (periodico en 360)."""
    ths = np.asarray(ths); d = (t - ths) % 360
    a = int(np.argmin(d))                       # vecina a la izquierda (o igual)
    if np.isclose(d[a], 0):
        return [(a, 1.0)]
    b = int(np.argmin((ths - t) % 360))         # vecina a la derecha
    da, db = d[a], (ths[b] - t) % 360
    return [(a, db / (da + db)), (b, da / (da + db))]


def leer(ruta, idx=None):
    with h5py.File(ruta) as f:
        uh = float(f.attrs["u_h"])
        F = np.stack([f[c][...] if idx is None else f[c][...][idx] for c in CAMPOS], 1)
    F[:, :3] /= uh; F[:, 3] /= uh**2
    return F, uh


def consulta(V2, theta, U10, salida):
    casos = malla(V2); ths = [c[0] for c in casos]
    w = vecinos(ths, theta % 360)
    F = 0; uh = 0
    for i, wi in w:
        Fi, uhi = leer(casos[i][1]); F = F + wi * Fi; uh += wi * uhi
    uh *= U10 / 5.0
    F[:, :3] *= uh; F[:, 3] *= uh**2
    with h5py.File(casos[w[0][0]][1]) as g, h5py.File(salida, "w") as f:
        for c in ("x", "y", "z", "cell_id", "vol", "is_wall_adjacent"):
            f[c] = g[c][...]
        for j, c in enumerate(CAMPOS):
            f[c] = F[:, j].astype(np.float32)
        f.attrs.update(theta_deg=theta, U10=U10, u_h=uh, metodo="interp lineal en theta, CFD base m1 a 11.25 grados",
                       vecinos=json.dumps([(ths[i], wi) for i, wi in w]), frame=g.attrs["frame"])
    return w, uh


def err(P, F, peat):
    dv = P[:, :3] - F[:, :3]; sp, sr = np.linalg.norm(P[:, :3], axis=1), np.linalg.norm(F[:, :3], axis=1)
    return float(np.sqrt((dv**2).sum() / (F[:, :3] ** 2).sum())), float(np.abs(sp - sr)[peat].mean())


def evaluar(V2, N=300_000, salida="interp_denso.json"):
    casos = malla(V2)
    with h5py.File(casos[0][1]) as f:
        n = f["z"].shape[0]; z = f["z"][...]
    idx = np.sort(np.random.default_rng(1).choice(n, min(N, n), replace=False)); peat = z[idx] <= 3.0
    datos = [leer(c[1], idx)[0] for c in casos]; ths = [c[0] for c in casos]
    res = {}
    for k, (t, ruta, split, flag) in enumerate(casos):
        resto = [j for j in range(len(casos)) if j != k]
        w = vecinos([ths[j] for j in resto], t)
        P = sum(wi * datos[resto[i]] for i, wi in w)
        hueco = (ths[resto[w[1][0]]] - ths[resto[w[0][0]]]) % 360   # separacion entre las dos vecinas
        e, ep = err(P, datos[k], peat)
        res[ruta.stem] = dict(theta=t, split=split, flag=flag, hueco=hueco, l2=e, peaton=ep)
    print(f"{'theta':>7} {'split':<20} {'hueco':>5} {'L2':>6} {'peaton':>7}")
    for r in res.values():
        print(f"{r['theta']:7.2f} {r['split']:<20} {r['hueco']:5.1f} {r['l2']:6.3f} {r['peaton']:7.3f} {r['flag']}")
    grupos = {"LOO32": list(res.values())}
    for s in ("train", "test-direction", "test-direction-fino"):
        grupos[f"LOO32/{s}"] = [r for r in res.values() if r["split"] == s]
    resumen = {g: dict(n=len(v), l2=float(np.mean([r["l2"] for r in v])), l2_max=float(np.max([r["l2"] for r in v])),
                       peaton=float(np.mean([r["peaton"] for r in v]))) for g, v in grupos.items() if v}
    for g, s in resumen.items():
        print(f"MEDIA {g:<28} n={s['n']:2d} L2 {s['l2']:.3f} (max {s['l2_max']:.3f}) peaton {s['peaton']:.3f} m/s/u_h")
    json.dump(dict(casos=res, resumen=resumen, n_puntos=int(len(idx))), open(salida, "w"), indent=1)


if __name__ == "__main__":
    modo, V2 = sys.argv[1], pathlib.Path(sys.argv[2])
    if modo == "consulta":
        w, uh = consulta(V2, float(sys.argv[3]), float(sys.argv[4]), sys.argv[5])
        print("pesos por theta", [(malla(V2)[i][0], round(wi, 3)) for i, wi in w], "u_h", round(uh, 3))
    else:
        evaluar(V2, int(sys.argv[3]) if len(sys.argv) > 3 else 300_000, sys.argv[4] if len(sys.argv) > 4 else "interp_denso.json")
