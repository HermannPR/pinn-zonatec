"""Physics-Informed Neural Network (PINN) for the time-averaged wind field over the synthetic city.

The network maps a position (x, y) in metres to (u, v, p): wind velocity components (m/s) and
pressure (Pa, relative to the inflow). It only sees a few hundred "sensor" cells of the
simulation. Everything else it has to infer from physics:

  * steady incompressible 2D Navier-Stokes on collocation points inside the fluid
        continuity   u_x + v_y = 0
        momentum-x   u u_x + v u_y + p_x / rho - nu (u_xx + u_yy) = 0
        momentum-y   u v_x + v v_y + p_y / rho - nu (v_xx + v_yy) = 0
  * boundary conditions: no-slip (u = v = 0) on building walls, inflow u = 5 m/s, v = 0 at x = 0,
    free-slip v = 0 on the top/bottom edges of the domain (same as the simulation).

All residuals are non-dimensionalised with U0 = 5 m/s, L0 = 20 m (typical building size) and
P0 = rho U0^2 = 30 Pa, so the terms have comparable magnitudes (see LOSS WEIGHTS below).

It also trains two baselines that use exactly the same sensors WITHOUT physics:
  * the same MLP trained on the sensor data only
  * scipy griddata linear interpolation (nearest-neighbour fill outside the convex hull)
and reports errors of all three against every fluid cell of the simulation.

Run:  python train/pinn.py            (writes public/model.json and public/field.json)
"""
import argparse
import json
import os
import pathlib
import time

# conda's numpy/scipy (MKL) and pip's torch each ship an OpenMP runtime; allow both to coexist
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np
from scipy.interpolate import griddata
import torch

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA, PUB = ROOT / "data", ROOT / "public"

p = argparse.ArgumentParser()
p.add_argument("--sensors", type=int, default=250)
p.add_argument("--iters", type=int, default=6000, help="Adam iterations")
p.add_argument("--lbfgs", type=int, default=0, help="L-BFGS iterations after Adam")
p.add_argument("--ncol", type=int, default=3000, help="collocation points per iteration")
p.add_argument("--width", type=int, default=64)
p.add_argument("--depth", type=int, default=6)
p.add_argument("--ff", type=int, default=0, help="number of random Fourier features (0 = plain MLP)")
p.add_argument("--ff_sigma", type=float, default=2.0)
p.add_argument("--w_data", type=float, default=10.0)
p.add_argument("--w_pde", type=float, default=1.0)
p.add_argument("--w_bc", type=float, default=5.0)
p.add_argument("--lr", type=float, default=2e-3)
p.add_argument("--no_baseline_mlp", action="store_true")
p.add_argument("--no_export", action="store_true")
p.add_argument("--seed", type=int, default=0)
p.add_argument("--threads", type=int, default=0)
args = p.parse_args()

if args.threads:
    torch.set_num_threads(args.threads)
torch.manual_seed(args.seed)
rng = np.random.default_rng(42)          # fixed sensor layout

# ---------------- data ----------------
d = np.load(DATA / "field.npz")
meta = json.loads((DATA / "meta.json").read_text())
U, V, P, SOLID, XC, YC = d["u"], d["v"], d["p"], d["solid"], d["x"], d["y"]
LX, LY, DX = meta["Lx"], meta["Ly"], meta["dx"]
NU, RHO, U0, L0 = meta["nu_effective"], 1.2, meta["u_inflow"], 20.0
P0 = RHO * U0 ** 2
BUILD = meta["buildings"]
GX, GY = np.meshgrid(XC, YC, indexing="ij")
FLUID = ~SOLID

# sparse sensors: random fluid cells (fixed seed)
fid = np.flatnonzero(FLUID.ravel())
sid = rng.choice(fid, args.sensors, replace=False)
SX, SY = GX.ravel()[sid], GY.ravel()[sid]
S_UVP = np.stack([U.ravel()[sid], V.ravel()[sid], P.ravel()[sid]], 1)


def inside_building(x, y, margin=0.0):
    m = np.zeros(x.shape, bool)
    for b in BUILD:
        m |= (x > b["x0"] - margin) & (x < b["x1"] + margin) & (y > b["y0"] - margin) & (y < b["y1"] + margin)
    return m


# collocation pool: uniform random points in the fluid
pool = rng.uniform([0, 0], [LX, LY], size=(200_000, 2))
pool = pool[~inside_building(pool[:, 0], pool[:, 1])]

# boundary points
def wall_points(n_per_m=1.0):
    pts = []
    for b in BUILD:
        x0, y0, x1, y1 = b["x0"], b["y0"], min(b["x1"], LX), min(b["y1"], LY)
        for (ax, ay, bx, by) in [(x0, y0, x1, y0), (x1, y0, x1, y1), (x0, y1, x1, y1), (x0, y0, x0, y1)]:
            L = np.hypot(bx - ax, by - ay)
            if L == 0 or (ay == by and ay >= LY):
                continue
            t = rng.uniform(0, 1, max(4, int(L * n_per_m)))
            pts.append(np.stack([ax + t * (bx - ax), ay + t * (by - ay)], 1))
    return np.concatenate(pts)


WALL = wall_points()
INFL = np.stack([np.zeros(400), rng.uniform(0, LY, 400)], 1)
TB = np.stack([rng.uniform(0, LX, 600), np.repeat([0.0, LY], 300)], 1)
TB = TB[~inside_building(TB[:, 0], TB[:, 1], 0.01)]

T = lambda a: torch.tensor(a, dtype=torch.float32)
s_xy, s_uvp = T(np.stack([SX, SY], 1)), T(S_UVP / np.array([U0, U0, P0]))
wall_xy, infl_xy, tb_xy, pool_t = T(WALL), T(INFL), T(TB), T(pool)


# ---------------- model ----------------
class Net(torch.nn.Module):
    def __init__(self, width, depth, n_ff=0, ff_sigma=2.0):
        super().__init__()
        self.register_buffer("lo", torch.tensor([0.0, 0.0]))
        self.register_buffer("hi", torch.tensor([LX, LY]))
        g = torch.Generator().manual_seed(1)
        self.register_buffer("B", torch.randn(2, n_ff, generator=g) * ff_sigma if n_ff else torch.zeros(2, 0))
        n_in = 2 + 2 * n_ff
        dims = [n_in] + [width] * depth + [3]
        self.layers = torch.nn.ModuleList(torch.nn.Linear(a, b) for a, b in zip(dims[:-1], dims[1:]))
        for l in self.layers:
            torch.nn.init.xavier_normal_(l.weight); torch.nn.init.zeros_(l.bias)

    def forward(self, xy):
        z = 2 * (xy - self.lo) / (self.hi - self.lo) - 1          # -> [-1, 1]
        if self.B.shape[1]:
            zb = torch.pi * z @ self.B
            z = torch.cat([z, torch.sin(zb), torch.cos(zb)], 1)
        for l in self.layers[:-1]:
            z = torch.tanh(l(z))
        return self.layers[-1](z)                                   # (u/U0, v/U0, p/P0)


def grad(f, x):
    return torch.autograd.grad(f, x, torch.ones_like(f), create_graph=True)[0]


def pde_residual(net, xy):
    xy = xy.clone().requires_grad_(True)
    o = net(xy)
    u, v, pr = o[:, 0] * U0, o[:, 1] * U0, o[:, 2] * P0
    gu, gv, gp = grad(u, xy), grad(v, xy), grad(pr, xy)
    ux, uy, vx, vy = gu[:, 0], gu[:, 1], gv[:, 0], gv[:, 1]
    uxx, uyy = grad(ux, xy)[:, 0], grad(uy, xy)[:, 1]
    vxx, vyy = grad(vx, xy)[:, 0], grad(vy, xy)[:, 1]
    cont = (ux + vy) * (L0 / U0)
    mx = (u * ux + v * uy + gp[:, 0] / RHO - NU * (uxx + uyy)) * (L0 / U0 ** 2)
    my = (u * vx + v * vy + gp[:, 1] / RHO - NU * (vxx + vyy)) * (L0 / U0 ** 2)
    return cont, mx, my


def losses(net, physics=True):
    o = net(s_xy)
    l_data = ((o - s_uvp) ** 2).mean()
    if not physics:
        return l_data, torch.zeros(()), torch.zeros(()), l_data
    idx = torch.randint(0, pool_t.shape[0], (args.ncol,))
    c, mx, my = pde_residual(net, pool_t[idx])
    l_pde = (c ** 2).mean() + (mx ** 2).mean() + (my ** 2).mean()
    ow, oi = net(wall_xy), net(infl_xy)
    otb = net(tb_xy)
    l_bc = (ow[:, :2] ** 2).mean() + ((oi[:, 0] - 1) ** 2).mean() + (oi[:, 1] ** 2).mean() \
        + (oi[:, 2] ** 2).mean() + (otb[:, 1] ** 2).mean()       # p = 0 at inflow (gauge), v = 0 top/bottom
    total = args.w_data * l_data + args.w_pde * l_pde + args.w_bc * l_bc
    return l_data, l_pde, l_bc, total


def train(physics=True, tag="PINN"):
    net = Net(args.width, args.depth, args.ff, args.ff_sigma)
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=args.iters, pct_start=0.05,
                                                final_div_factor=100)
    t0 = time.time()
    for it in range(args.iters):
        opt.zero_grad()
        ld, lp, lb, tot = losses(net, physics)
        tot.backward()
        opt.step(); sched.step()
        if it % 500 == 0 or it == args.iters - 1:
            print(f"[{tag}] it {it:5d}  data {ld.item():.4e}  pde {lp.item():.4e}  bc {lb.item():.4e}  "
                  f"{time.time() - t0:.0f}s", flush=True)
    if args.lbfgs and physics:
        opt2 = torch.optim.LBFGS(net.parameters(), lr=1.0, max_iter=args.lbfgs, history_size=50,
                                 line_search_fn="strong_wolfe")
        torch.manual_seed(123)

        def closure():
            opt2.zero_grad()
            torch.manual_seed(123)                                     # fixed collocation set for L-BFGS
            _, _, _, tot = losses(net, physics)
            tot.backward()
            return tot
        opt2.step(closure)
        ld, lp, lb, _ = losses(net, physics)
        print(f"[{tag}] after L-BFGS  data {ld.item():.4e}  pde {lp.item():.4e}  bc {lb.item():.4e}  "
              f"{time.time() - t0:.0f}s", flush=True)
    return net, time.time() - t0


def predict(net, xy):
    with torch.no_grad():
        o = net(T(xy)).numpy()
    return o * np.array([U0, U0, P0])


def metrics(pu, pv, pp):
    """Errors on every fluid cell of the simulation."""
    su, sv, sp = U[FLUID], V[FLUID], P[FLUID]
    spd_t, spd_p = np.hypot(su, sv), np.hypot(pu, pv)
    return {
        "rel_l2_speed": float(np.linalg.norm(spd_p - spd_t) / np.linalg.norm(spd_t)),
        "rel_l2_velocity": float(np.sqrt(((pu - su) ** 2 + (pv - sv) ** 2).sum() / (su ** 2 + sv ** 2).sum())),
        "mae_speed_ms": float(np.abs(spd_p - spd_t).mean()),
        "mae_velocity_vec_ms": float(np.hypot(pu - su, pv - sv).mean()),
        "mae_pressure_pa": float(np.abs(pp - sp).mean()),
    }


GRID = np.stack([GX[FLUID], GY[FLUID]], 1)
report = {"n_sensors": args.sensors, "n_fluid_cells": int(FLUID.sum()), "config": vars(args)}

# ---- PINN ----
net, t_pinn = train(True, "PINN")
pr = predict(net, GRID)
report["pinn"] = metrics(pr[:, 0], pr[:, 1], pr[:, 2]); report["pinn"]["train_seconds"] = round(t_pinn, 1)
print("PINN      ", report["pinn"], flush=True)

# ---- baseline 1: griddata ----
pts = np.stack([SX, SY], 1)
gd = []
for k in range(3):
    lin = griddata(pts, S_UVP[:, k], GRID, method="linear")
    near = griddata(pts, S_UVP[:, k], GRID, method="nearest")
    gd.append(np.where(np.isnan(lin), near, lin))
report["baseline_griddata"] = metrics(*gd)
print("griddata  ", report["baseline_griddata"], flush=True)

# ---- baseline 2: same MLP, data only ----
if not args.no_baseline_mlp:
    net_d, t_d = train(False, "DATA-ONLY")
    prd = predict(net_d, GRID)
    report["baseline_mlp_data_only"] = metrics(prd[:, 0], prd[:, 1], prd[:, 2])
    report["baseline_mlp_data_only"]["train_seconds"] = round(t_d, 1)
    print("MLP data  ", report["baseline_mlp_data_only"], flush=True)

(ROOT / "train" / "last_report.json").write_text(json.dumps(report, indent=1))

if args.no_export:
    raise SystemExit

# ---------------- export ----------------
def r5(a):
    return [float(f"{x:.5g}") for x in np.asarray(a).ravel()]


layers = []
for l in net.layers:
    W = l.weight.detach().numpy()             # (out, in)
    layers.append({"W": [r5(row) for row in W], "b": r5(l.bias.detach().numpy())})
model = {
    "layers": layers, "activation": "tanh",
    "in_norm": {"xmin": 0.0, "xmax": LX, "ymin": 0.0, "ymax": LY},
    "fourier": {"B": [r5(row) for row in net.B.numpy()]} if args.ff else None,
    "out_scale": {"u": U0, "v": U0, "p": P0},
    "physics": {"rho": RHO, "nu": NU, "U0": U0, "L0": L0,
                "weights": {"data": args.w_data, "pde": args.w_pde, "bc": args.w_bc}},
    "metrics": report,
    "sensors": [[float(a), float(b)] for a, b in zip(SX, SY)],
}
(PUB / "model.json").write_text(json.dumps(model, separators=(",", ":")))

# simulation downsampled by 2 + griddata baseline on the same grid (for the "solo sensores" view)
st = 2
sub = (slice(0, None, st), slice(0, None, st))
xs, ys = XC[::st], YC[::st]
gxs, gys = np.meshgrid(xs, ys, indexing="ij")
base = []
for k in range(3):
    lin = griddata(pts, S_UVP[:, k], (gxs, gys), method="linear")
    near = griddata(pts, S_UVP[:, k], (gxs, gys), method="nearest")
    base.append(np.where(np.isnan(lin), near, lin))
sol = SOLID[sub]
q = lambda a, nd=2: [None if (s or not np.isfinite(x)) else round(float(x), nd) for x, s in zip(a.ravel(), sol.ravel())]
field = {
    "nx": len(xs), "ny": len(ys), "dx": DX * st, "x0": float(xs[0]), "y0": float(ys[0]),
    "Lx": LX, "Ly": LY, "order": "row-major [ix][iy] flattened (index = ix*ny + iy)",
    "u": q(U[sub]), "v": q(V[sub]), "p": q(P[sub], 1),
    "solid": [int(s) for s in sol.ravel()],
    "base_u": q(base[0]), "base_v": q(base[1]),
    "buildings": BUILD, "u_inflow": U0,
}
(PUB / "field.json").write_text(json.dumps(field, separators=(",", ":")))
print("exported", (PUB / "model.json").stat().st_size // 1024, "KB model,",
      (PUB / "field.json").stat().st_size // 1024, "KB field")
