"""2D wind over a synthetic city block layout with the lattice Boltzmann method (D2Q9, BGK).

Produces the "simulation data" the PINN learns from: a time-averaged velocity and pressure
field around buildings. Physical scale: 480 m x 240 m domain, 2 m cells, 5 m/s inflow wind
from the west. Output: data/field.npz

Run:  python sim/lbm.py
"""
import json
import pathlib
import time

import numpy as np

OUT = pathlib.Path(__file__).resolve().parents[1] / "data"
OUT.mkdir(exist_ok=True)

# ---------- grid and physics ----------
NX, NY = 240, 120            # cells
DX = 2.0                     # metres per cell  -> 480 m x 240 m
U_LB = 0.08                  # inflow speed in lattice units (keeps Mach low)
U_PHYS = 5.0                 # inflow speed in m/s
TAU = 0.56                   # relaxation time -> lattice viscosity (tau - 0.5) / 3
STEPS, AVG_FROM = 16000, 8000

# D2Q9 lattice
c = np.array([[0, 0], [1, 0], [0, 1], [-1, 0], [0, -1], [1, 1], [-1, 1], [-1, -1], [1, -1]])
w = np.array([4 / 9] + [1 / 9] * 4 + [1 / 36] * 4)
opp = np.array([0, 3, 4, 1, 2, 7, 8, 5, 6])


def city_mask(seed: int = 7) -> tuple[np.ndarray, list[dict]]:
    """Blocks of buildings separated by streets; varied footprints so the flow is non-trivial."""
    rng = np.random.default_rng(seed)
    mask = np.zeros((NX, NY), dtype=bool)
    buildings = []
    x = 40
    while x < NX - 50:
        bw = int(rng.integers(8, 16))
        y = 10
        while y < NY - 14:
            bh = int(rng.integers(8, 22))
            if rng.random() < 0.8:                     # some lots stay empty (plazas)
                mask[x:x + bw, y:y + bh] = True
                buildings.append({"x0": x * DX, "y0": y * DX, "x1": (x + bw) * DX, "y1": (y + bh) * DX})
            y += bh + int(rng.integers(5, 9))           # street
        x += bw + int(rng.integers(8, 13))              # avenue
    return mask, buildings


def equilibrium(rho, ux, uy):
    cu = 3 * (c[:, 0, None, None] * ux + c[:, 1, None, None] * uy)
    usq = 1.5 * (ux ** 2 + uy ** 2)
    return rho * w[:, None, None] * (1 + cu + 0.5 * cu ** 2 - usq)


def main():
    solid, buildings = city_mask()
    rho = np.ones((NX, NY))
    ux = np.full((NX, NY), U_LB)
    uy = np.zeros((NX, NY))
    # tiny perturbation so the wake can develop naturally
    uy += 1e-4 * np.sin(np.linspace(0, 2 * np.pi, NY))[None, :]
    ux[solid] = 0.0
    f = equilibrium(rho, ux, uy)

    su = np.zeros((NX, NY)); sv = np.zeros((NX, NY)); sp = np.zeros((NX, NY)); n = 0
    t0 = time.time()
    for step in range(STEPS):
        # macroscopic fields
        rho = f.sum(axis=0)
        ux = (f * c[:, 0, None, None]).sum(axis=0) / rho
        uy = (f * c[:, 1, None, None]).sum(axis=0) / rho
        # inflow (west): fixed velocity, equilibrium populations
        ux[0, :] = U_LB; uy[0, :] = 0.0; rho[0, :] = 1.0
        ux[solid] = 0.0; uy[solid] = 0.0

        feq = equilibrium(rho, ux, uy)
        f_post = f - (f - feq) / TAU                  # BGK collision
        f_post[:, 0, :] = feq[:, 0, :]
        # bounce-back on buildings (no-slip walls)
        f_post[:, solid] = f[opp][:, solid]

        # streaming
        for i in range(9):
            f[i] = np.roll(np.roll(f_post[i], c[i, 0], axis=0), c[i, 1], axis=1)
        # outflow (east): zero gradient;  top/bottom: free slip via mirroring
        f[:, -1, :] = f[:, -2, :]
        f[[2, 5, 6], :, 0] = f[[4, 8, 7], :, 0]
        f[[4, 7, 8], :, -1] = f[[2, 6, 5], :, -1]

        if step >= AVG_FROM:
            su += ux; sv += uy; sp += rho; n += 1
        if step % 2000 == 0:
            print(f"step {step:5d}  max|u|={np.hypot(ux, uy).max():.3f}  {time.time() - t0:.0f}s", flush=True)

    scale = U_PHYS / U_LB                               # lattice -> m/s
    u = su / n * scale
    v = sv / n * scale
    # pressure relative to inflow, in Pa (air density 1.2 kg/m^3): p = rho0 * cs^2 * (rho - 1) scaled
    p = (sp / n - 1.0) / 3.0 * 1.2 * scale ** 2
    u[solid] = 0.0; v[solid] = 0.0; p[solid] = np.nan

    nu_phys = (TAU - 0.5) / 3.0 * DX * U_PHYS / U_LB   # effective viscosity in m^2/s (lattice -> physical)
    x = (np.arange(NX) + 0.5) * DX
    y = (np.arange(NY) + 0.5) * DX
    np.savez_compressed(OUT / "field.npz", u=u, v=v, p=p, solid=solid, x=x, y=y)
    (OUT / "meta.json").write_text(json.dumps({
        "nx": NX, "ny": NY, "dx": DX, "Lx": NX * DX, "Ly": NY * DX, "u_inflow": U_PHYS,
        "nu_effective": nu_phys, "steps": STEPS, "avg_from": AVG_FROM, "buildings": buildings,
    }, indent=1))
    print(f"done in {time.time() - t0:.0f}s; speed max {np.nanmax(np.hypot(u, v)):.2f} m/s; "
          f"{len(buildings)} buildings; nu_eff={nu_phys:.3f} m2/s")


if __name__ == "__main__":
    main()
