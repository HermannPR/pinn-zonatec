"""F4 etapa A: PINN hibrida 3D parametrica en la direccion del viento, sobre la campana RANS de Zona Tec.

Red: (x, y, z, cos th, sin th) -> (u, v, w, p) adimensionales con u_h (viento a h_ref) y u_h^2.
Similitud de Reynolds: el campo dimensional es u_h * red, asi que la velocidad no es entrada; el caso
test-speed (U10 = 10) mide si esa hipotesis aguanta.

Perdida etapa A:
  * datos: celdas CFD de los casos train (manifest.csv, split == train, converged == True);
  * continuidad: div(U) = 0 en centros de celda con direccion AL AZAR en [0, 360), para que la fisica
    regularice entre direcciones (lo que la interpolacion no hace);
  * no deslizamiento: U = 0 en caras de pared (suelo y edificios).
La etapa B agrega momento RANS con nut del CFD (pendiente).

Evaluacion contra test-direction, test-speed y gci (m2, m3) y contra dos referencias sin red:
  * interp: interpolacion lineal celda a celda entre las dos direcciones train vecinas (misma malla);
  * escala: el caso train de la misma direccion escalado por u_h (para test-speed).

Cede y guarda: cada --check iters revisa la bandera CEDER del gestor, ~/pinn-control/PAUSA_ENTRENO,
renders (ffmpeg, DaVinci Resolve), corridas CFD (simpleFoam, snappyHexMesh, mpirun) y memoria libre
< --mem-min %. Si toca ceder, guarda checkpoint y sale con codigo 75; train/correr.sh reintenta.

  train/.venv/bin/python train/f4.py --run a1            # reanuda solo si existe train/runs/a1/ckpt.pt
"""
import argparse
import csv
import json
import math
import os
import pathlib
import subprocess
import sys
import time

import h5py
import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
V2 = ROOT / "f3/paquete/pinn/v2"
CEDER = pathlib.Path.home() / "Library/Application Support/hivemind/gestor/CEDER"
PAUSA = pathlib.Path.home() / "pinn-control/PAUSA_ENTRENO"
EXIT_CEDE = 75
# Dominio de la region extraida (attrs "region" de los HDF5).
LX, LY, ZMAX = 425.0, 425.0, 175.5

p = argparse.ArgumentParser()
p.add_argument("--run", required=True)
p.add_argument("--iters", type=int, default=40000)
p.add_argument("--batch", type=int, default=8192, help="celdas de datos por iteracion")
p.add_argument("--ncol", type=int, default=4096, help="puntos de continuidad por iteracion")
p.add_argument("--nwall", type=int, default=2048)
p.add_argument("--pts-caso", type=int, default=400_000, help="celdas por caso train en memoria")
p.add_argument("--eval-pts", type=int, default=100_000)
p.add_argument("--width", type=int, default=256)
p.add_argument("--depth", type=int, default=6)
p.add_argument("--ff", type=int, default=128, help="Fourier features por escala")
p.add_argument("--ff-sigma", type=str, default="1,4,16", help="escalas de las Fourier features")
p.add_argument("--lr", type=float, default=1e-3)
p.add_argument("--w-p", type=float, default=0.5)
p.add_argument("--w-div", type=float, default=0.1)
p.add_argument("--w-wall", type=float, default=0.1)
p.add_argument("--rampa", type=int, default=5000, help="iters para subir la fisica de 0 a su peso")
p.add_argument("--incluir-no-convergidos", action="store_true")
p.add_argument("--w-meseta", type=float, default=0.5,
               help="peso de datos de casos en meseta (C7 por oscilacion de estela; 0 = fuera)")
p.add_argument("--ckpt-cada", type=int, default=500)
p.add_argument("--eval-cada", type=int, default=4000)
p.add_argument("--check", type=int, default=50)
p.add_argument("--mem-min", type=int, default=25)
p.add_argument("--threads", type=int, default=4)
p.add_argument("--device", default="mps" if torch.backends.mps.is_available() else "cpu")
p.add_argument("--seed", type=int, default=0)
p.add_argument("--sin-ceder", action="store_true", help="solo pruebas cortas")
args = p.parse_args()

try:
    os.nice(19)
except OSError:
    pass
torch.set_num_threads(args.threads)
RUN = ROOT / "train/runs" / args.run
RUN.mkdir(parents=True, exist_ok=True)
dev = torch.device(args.device)


def log(msg, **kv):
    linea = {"t": time.strftime("%m-%d %H:%M:%S"), "msg": msg, **kv}
    with open(RUN / "log.jsonl", "a") as f:
        f.write(json.dumps(linea) + "\n")
    print(json.dumps(linea), flush=True)


# ---------------------------------------------------------------- ceder

def mem_libre():
    try:
        out = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=20).stdout
        for l in out.splitlines():
            if "free percentage" in l:
                return int(l.split(":")[1].strip().rstrip("%"))
    except Exception:
        pass
    return 100


def corre(pat, exacto=False):
    return subprocess.run(["pgrep", "-qx" if exacto else "-qf", pat]).returncode == 0


def motivo_ceder():
    if CEDER.exists():
        return "CEDER del gestor"
    if PAUSA.exists():
        return "PAUSA_ENTRENO"
    if corre("ffmpeg", exacto=True) or corre("DaVinci Resolve"):
        return "render"
    if corre("simpleFoam") or corre("snappyHexMesh") or corre("mpirun") or corre("prterun"):
        return "CFD corriendo"
    m = mem_libre()
    if m < args.mem_min:
        return f"memoria libre {m}%"
    return None


# ---------------------------------------------------------------- datos

def manifest():
    with open(V2 / "data/processed/manifest.csv") as f:
        filas = list(csv.DictReader(f))
    return [r for r in filas if (V2 / r["path"]).exists()]


def es_meseta(r):
    """Casos que no pasan C7 solo por la oscilacion de la estela: cln los marca en el manifest (columna flag)
    o en los attrs del HDF5; traen el promedio de las ultimas 500 iteraciones."""
    if "meseta" in (r.get("flag") or "").lower():
        return True
    with h5py.File(V2 / r["path"], "r") as f:
        return "meseta" in str(f.attrs.get("flag", "")).lower()


def leer(r, idx=None, campos=("x", "y", "z", "u", "v", "w", "p")):
    with h5py.File(V2 / r["path"], "r") as f:
        uh = float(f.attrs["u_h"])
        th = float(f.attrs["theta_deg"])
        if idx is None:
            d = {c: f[c][...] for c in campos}
        else:
            d = {c: f[c][...][idx] for c in campos}
        d["cell_id"] = f["cell_id"][...] if idx is None else f["cell_id"][...][idx]
    return d, uh, th


def entrada(x, y, z, th_deg):
    th = np.radians(th_deg) if np.ndim(th_deg) else np.full_like(x, math.radians(th_deg))
    return np.stack([x / LX, y / LY, 2 * z / ZMAX - 1, np.cos(th), np.sin(th)], 1).astype(np.float32)


def salida(d, uh):
    return np.stack([d["u"] / uh, d["v"] / uh, d["w"] / uh, d["p"] / uh**2], 1).astype(np.float32)


# ---------------------------------------------------------------- red

class Red(torch.nn.Module):
    def __init__(self):
        super().__init__()
        g = torch.Generator().manual_seed(args.seed)
        sig = [float(s) for s in args.ff_sigma.split(",")]
        B = torch.cat([torch.randn(3, args.ff, generator=g) * s for s in sig], 1)
        self.register_buffer("B", B)
        n_in = 2 * B.shape[1] + 5
        capas, w = [], args.width
        for i in range(args.depth):
            capas += [torch.nn.Linear(n_in if i == 0 else w, w), torch.nn.SiLU()]
        capas.append(torch.nn.Linear(w, 4))
        self.mlp = torch.nn.Sequential(*capas)

    def forward(self, X):
        xyz = X[:, :3]
        a = 2 * math.pi * xyz @ self.B
        return self.mlp(torch.cat([torch.sin(a), torch.cos(a), X], 1))


def divergencia(red, X):
    """div(U) adimensional con h_ref ~ 87.75 m como longitud (u_h es la escala de velocidad)."""
    X = X.clone().requires_grad_(True)
    out = red(X)
    esc = (1 / LX, 1 / LY, 2 / ZMAX)   # d xhat / d x
    div = 0
    for i in range(3):
        g = torch.autograd.grad(out[:, i].sum(), X, create_graph=True)[0][:, i]
        div = div + g * esc[i] * 87.75
    return div


# ---------------------------------------------------------------- evaluacion

def metricas(pred, ref, z):
    """pred, ref: (n, 4) dimensionales (u, v, w, p)."""
    dv = pred[:, :3] - ref[:, :3]
    vel = np.sqrt((dv**2).sum(1).sum() / (ref[:, :3] ** 2).sum(1).sum())
    sp, sr = np.linalg.norm(pred[:, :3], axis=1), np.linalg.norm(ref[:, :3], axis=1)
    peat = z <= 3.0
    out = {"rel_l2_vel": float(vel), "mae_speed_ms": float(np.abs(sp - sr).mean()),
           "rel_l2_p": float(np.linalg.norm(pred[:, 3] - ref[:, 3]) / np.linalg.norm(ref[:, 3]))}
    if peat.any():
        out["peaton_mae_speed_ms"] = float(np.abs(sp[peat] - sr[peat]).mean())
        out["peaton_rel_l2_speed"] = float(np.linalg.norm(sp[peat] - sr[peat]) / np.linalg.norm(sr[peat]))
        out["n_peaton"] = int(peat.sum())
    return out


def predecir(red, X, uh):
    red.eval()
    res = []
    with torch.no_grad():
        for i in range(0, len(X), 65536):
            res.append(red(torch.from_numpy(X[i:i + 65536]).to(dev)).cpu().numpy())
    red.train()
    y = np.concatenate(res)
    y[:, :3] *= uh
    y[:, 3] *= uh**2
    return y


class Evaluador:
    def __init__(self, filas, train):
        rng = np.random.default_rng(1)
        self.casos = []
        # Las mallas m1 comparten celdas: la referencia interp se arma celda a celda por cell_id.
        self.train_m1 = sorted([r for r in train if r["mesh_id"] == "m1" and float(r["U10"]) == 5.0],
                               key=lambda r: float(r["theta_deg"]))
        for r in filas:
            if r["split"] not in ("test-direction", "test-speed", "gci"):
                continue
            with h5py.File(V2 / r["path"], "r") as f:
                n = f["x"].shape[0]
            idx = np.sort(rng.choice(n, min(n, args.eval_pts), replace=False))
            d, uh, th = leer(r, idx)
            ref = np.stack([d["u"], d["v"], d["w"], d["p"]], 1)
            caso = {"fila": r, "X": entrada(d["x"], d["y"], d["z"], th), "ref": ref, "z": d["z"], "uh": uh}
            caso["base"] = self.referencia(r, idx, d["cell_id"], th, uh)
            self.casos.append(caso)
            log("eval cargado", caso=r["case_id"], split=r["split"], n=len(idx))

    def campo_train(self, r, idx, cid):
        d, uh, _ = leer(r, idx, ("u", "v", "w", "p"))
        if not np.array_equal(d["cell_id"], cid):
            return None, uh
        return np.stack([d["u"], d["v"], d["w"], d["p"]], 1), uh

    def referencia(self, r, idx, cid, th, uh):
        if r["mesh_id"] != "m1" or not self.train_m1:
            return None
        ths = np.array([float(t["theta_deg"]) for t in self.train_m1])
        if r["split"] == "test-speed":
            j = np.where(np.isclose(ths, th))[0]
            if not len(j):
                return None
            f, uh0 = self.campo_train(self.train_m1[j[0]], idx, cid)
            if f is None:
                return None
            f = f.copy(); f[:, :3] *= uh / uh0; f[:, 3] *= (uh / uh0) ** 2
            return {"tipo": "escala", "pred": f}
        # direccion: vecinas train a cada lado (circular)
        dif = (ths - th) % 360
        a = int(np.argmax(np.where(dif > 180, dif - 360, -np.inf)))   # la mas cercana por debajo
        b = int(np.argmin(np.where(dif > 0, dif, np.inf)))            # la mas cercana por arriba
        ta, tb = ths[a], ths[b]
        da, db = (th - ta) % 360, (tb - th) % 360
        fa, ua = self.campo_train(self.train_m1[a], idx, cid)
        fb, ub = self.campo_train(self.train_m1[b], idx, cid)
        if fa is None or fb is None:
            return None
        wa = db / (da + db)
        f = wa * fa * np.array([uh / ua] * 3 + [(uh / ua) ** 2]) + (1 - wa) * fb * np.array([uh / ub] * 3 + [(uh / ub) ** 2])
        return {"tipo": f"interp {ta:g}-{tb:g}", "pred": f}

    def __call__(self, red, it):
        res = {}
        for c in self.casos:
            m = metricas(predecir(red, c["X"], c["uh"]), c["ref"], c["z"])
            if c["base"] is not None:
                m["referencia"] = c["base"]["tipo"]
                m["ref"] = metricas(c["base"]["pred"], c["ref"], c["z"])
            res[c["fila"]["case_id"]] = {"split": c["fila"]["split"], **m}
        json.dump({"iter": it, "casos": res}, open(RUN / "metricas.json", "w"), indent=1)
        log("eval", it=it, **{k: round(v["rel_l2_vel"], 4) for k, v in res.items()})
        return res


# ---------------------------------------------------------------- principal

def main():
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    filas = manifest()
    peso = {}
    for r in filas:
        if r["split"] != "train":
            continue
        if r["converged"] == "True":
            peso[r["case_id"]] = 1.0
        elif es_meseta(r) and args.w_meseta > 0:
            peso[r["case_id"]] = args.w_meseta
        elif args.incluir_no_convergidos:
            peso[r["case_id"]] = 1.0
    train = [r for r in filas if r["case_id"] in peso]
    log("casos", train={r["case_id"]: peso[r["case_id"]] for r in train},
        fuera=[r["case_id"] for r in filas if r not in train])
    if not args.sin_ceder and (m := motivo_ceder()):
        log("cede antes de cargar", motivo=m)
        sys.exit(EXIT_CEDE)

    Xs, Ys, Cs, Ws, Ps, ths = [], [], [], [], [], []
    for r in train:
        with h5py.File(V2 / r["path"], "r") as f:
            n = f["x"].shape[0]
            wx = np.stack([f["wall_faces"][c][...] for c in ("x", "y", "z")], 1)
        idx = np.sort(rng.choice(n, min(n, args.pts_caso), replace=False))
        d, uh, th = leer(r, idx)
        Xs.append(entrada(d["x"], d["y"], d["z"], th)); Ys.append(salida(d, uh)); ths.append(th)
        Ps.append(np.full(len(idx), peso[r["case_id"]], np.float32))
        Cs.append(np.stack([d["x"], d["y"], d["z"]], 1).astype(np.float32))
        Ws.append(wx[rng.choice(len(wx), min(len(wx), 100_000), replace=False)].astype(np.float32))
    X = torch.from_numpy(np.concatenate(Xs)).to(dev)
    Y = torch.from_numpy(np.concatenate(Ys)).to(dev)
    P = torch.from_numpy(np.concatenate(Ps)).to(dev)
    C = np.concatenate(Cs)
    W = np.concatenate(Ws)
    del Xs, Ys, Cs, Ws, Ps
    log("datos", n=len(X), ncol=len(C), nwall=len(W), dev=str(dev))
    evaluar = Evaluador(filas, train)

    red = Red().to(dev)
    opt = torch.optim.Adam(red.parameters(), lr=args.lr)
    sch = torch.optim.lr_scheduler.LambdaLR(opt, lambda i: 0.5 * (1 + math.cos(math.pi * min(i, args.iters) / args.iters)) * 0.97 + 0.03)
    it0 = 0
    ck = RUN / "ckpt.pt"
    if ck.exists():
        s = torch.load(ck, map_location=dev)
        red.load_state_dict(s["red"]); opt.load_state_dict(s["opt"]); sch.load_state_dict(s["sch"])
        it0 = s["it"]
        log("reanuda", it=it0)
    json.dump(vars(args), open(RUN / "config.json", "w"), indent=1)

    def guardar(it):
        tmp = RUN / "ckpt.tmp"
        torch.save({"red": red.state_dict(), "opt": opt.state_dict(), "sch": sch.state_dict(), "it": it,
                    "args": vars(args)}, tmp)
        os.replace(tmp, ck)

    wy = torch.tensor([1, 1, 1, args.w_p], device=dev)
    t0, acum = time.time(), np.zeros(3)
    for it in range(it0, args.iters):
        if it % args.check == 0 and it > it0 and not args.sin_ceder and (m := motivo_ceder()):
            guardar(it)
            log("cede", it=it, motivo=m)
            sys.exit(EXIT_CEDE)
        rampa = min(1.0, it / max(1, args.rampa))
        i = torch.randint(0, len(X), (args.batch,), device=dev)
        l_dat = ((((red(X[i]) - Y[i]) ** 2) * wy).mean(1) * P[i]).sum() / P[i].sum()

        jc = rng.integers(0, len(C), args.ncol)
        thc = rng.uniform(0, 360, args.ncol)
        Xc = torch.from_numpy(entrada(C[jc, 0], C[jc, 1], C[jc, 2], thc)).to(dev)
        l_div = (divergencia(red, Xc) ** 2).mean()

        jw = rng.integers(0, len(W), args.nwall)
        thw = rng.uniform(0, 360, args.nwall)
        Xw = torch.from_numpy(entrada(W[jw, 0], W[jw, 1], W[jw, 2], thw)).to(dev)
        l_wall = (red(Xw)[:, :3] ** 2).mean()

        loss = l_dat + rampa * (args.w_div * l_div + args.w_wall * l_wall)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step(); sch.step()
        acum += [l_dat.item(), l_div.item(), l_wall.item()] if it % 50 == 0 else 0
        if (it + 1) % 500 == 0:
            log("iter", it=it + 1, datos=round(acum[0] / 10, 6), div=round(acum[1] / 10, 6),
                pared=round(acum[2] / 10, 6), lr=sch.get_last_lr()[0], s_por_100=round((time.time() - t0) / 5, 2))
            acum[:], t0 = 0, time.time()
        if (it + 1) % args.ckpt_cada == 0:
            guardar(it + 1)
        if (it + 1) % args.eval_cada == 0:
            evaluar(red, it + 1)
    guardar(args.iters)
    evaluar(red, args.iters)
    torch.save(red.state_dict(), RUN / "red.pt")
    (RUN / "DONE").touch()
    log("termina", it=args.iters)


if __name__ == "__main__":
    main()
