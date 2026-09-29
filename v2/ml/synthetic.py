"""Synthetic data generator for the PINN Zona Tec smoke test.

Writes fake "CFD" cases in *exactly* the HDF5 contract format described in
docs/DATA_CONTRACT.md, so the rest of the pipeline (data.py, train.py,
metrics.py, ...) can be developed and smoke-tested before real OpenFOAM
results exist. This module proves *plumbing*, not physics: the generated
fields are an analytically divergence-free construction, not a solution of
the RANS equations. See the module docstring sections below for exactly
which contract clauses are honoured exactly vs. approximated.

Construction of the velocity field
-----------------------------------
u = u_base(z) + sum_over_buildings( curl(A_i) )

curl(A) is divergence-free for *any* differentiable vector potential A,
identically (div(curl A) == 0). We exploit this to build a field that
satisfies continuity to floating point precision everywhere in the fluid,
while still being direction- and geometry-dependent:

  * u_base(z) is a neutral log-law profile (Richards & Hoxey 1993 constants)
    aligned with the meteorological wind direction theta (contract
    convention: flow travels along -(sin theta, cos theta)). A uniform (in
    x, y) shear flow is trivially divergence-free.
  * For each building i we add curl(A_i) with
        A_i = (0, C_i * bump_i(X,Y) * h_i(z), psi_i(X,Y,z))
    where (X, Y) are downstream/crosswind coordinates centred on the
    building, psi_i is a classic 2D potential-flow "doublet" streamfunction
    (flow around a cylinder, oriented to oppose the approach flow -> blocking
    / lateral deflection around the building), and the Ay component adds a
    vertical velocity (updraft in front / downdraft behind, decaying with
    height) that vanishes at the ground (h_i(0) = 0, consistent with an
    impermeable ground) and away from the building footprint.

  All partial derivatives are computed analytically in closed form (see
  `_building_perturbation`), not by finite differences, so continuity holds
  to numerical precision (verified in ml/tests/test_physics.py on the
  general curl construction, and can be checked directly on this module's
  output, see `max_abs_divergence` at the bottom of `generate_case`).

Simplifications vs. the real contract (documented, smoke-test only)
---------------------------------------------------------------------
  * Only 8 directions (0..315 in 45 deg steps) are generated, not the full
    16-sector convention; the convention (meteorological FROM-direction,
    ENU velocity = -U*(sin theta, cos theta)) is honoured exactly.
  * A single fixed "urban" roughness (z0=0.5 m, d=0) is used for every case
    instead of the sector-dependent Macdonald (1998) transfer from the
    open-terrain U10. u* is solved from U10 with this single z0.
  * epsilon(x,y,z) is the *inflow* profile value broadcast over the whole
    domain (buildings are not accounted for in the turbulence field);
    k is the inflow value lightly modulated by local speed-up.
  * p is a Bernoulli-consistent-ish kinematic pressure, not an actual RANS
    pressure solution, so the *momentum* residual on this synthetic data is
    expected to be non-trivial (this is fine: the momentum-residual unit
    test in ml/tests uses a real exact NS solution (plane Poiseuille), not
    this generator).
  * OpenFOAM simpleFoam p does NOT include 2/3 k explicitly (see
    physics.py docstring) -- the synthetic p follows the same convention.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import List, Tuple

import h5py
import numpy as np

KAPPA = 0.41
CMU = 0.09
Z0_URBAN = 0.5  # m, documented simplification (see module docstring)
D_DISPLACEMENT = 0.0
RHO_MTY = 1.13  # kg/m3, Monterrey air density (contract attribute)

H_REF = 25.0  # m, reference building height (tallest "base" building)


@dataclasses.dataclass
class Building:
    xc: float
    yc: float
    hx: float  # half-extent in x, m
    hy: float  # half-extent in y, m
    H: float  # height, m


VARIANTS = {
    "base": [
        Building(xc=-30.0, yc=-20.0, hx=15.0, hy=10.0, H=25.0),
        Building(xc=25.0, yc=15.0, hx=12.5, hy=12.5, H=18.0),
    ],
    "var1": [
        Building(xc=0.0, yc=0.0, hx=20.0, hy=15.0, H=30.0),
    ],
}

# domain (zone of interest box), same footprint for every case
LX, LY = 200.0, 200.0  # m, full extent centred at origin
HMAX = max(b.H for bs in VARIANTS.values() for b in bs)  # 30 m
ZTOP = 2.0 * HMAX  # contract: z from 0 to 2*H_max

# grid resolution (smoke test: small but non-trivial)
NX, NY, NZ = 46, 46, 22

CASES = [
    # (variant, theta_deg, U10, split)
    ("base", 0.0, 4.0, "train"),
    ("base", 45.0, 8.0, "train"),
    ("base", 90.0, 4.0, "train"),
    ("base", 270.0, 8.0, "val"),
    ("base", 315.0, 4.0, "val"),
    ("base", 135.0, 8.0, "test-direction"),
    ("base", 0.0, 12.0, "test-speed"),
    ("var1", 90.0, 8.0, "test-variant"),
]

MESH_ID = "m1"
TURB_MODEL = "kEpsilon"
SOLVER = "simpleFoam"


def u_star_from_u10(u10: float, z0: float = Z0_URBAN, d: float = D_DISPLACEMENT) -> float:
    """Solve u* from a log-law profile matched at z=10 m (documented
    simplification: a single urban z0 for every direction, see module
    docstring, instead of the sector-dependent Macdonald 1998 transfer)."""
    return u10 * KAPPA / np.log((10.0 - d + z0) / z0)


def log_law(z: np.ndarray, u_star: float, z0: float = Z0_URBAN, d: float = D_DISPLACEMENT) -> np.ndarray:
    zz = np.maximum(z - d, 0.0)
    return (u_star / KAPPA) * np.log((zz + z0) / z0)


def inflow_k(u_star: float) -> float:
    return (u_star ** 2) / np.sqrt(CMU)


def inflow_eps(z: np.ndarray, u_star: float, z0: float = Z0_URBAN, d: float = D_DISPLACEMENT) -> np.ndarray:
    zz = np.maximum(z - d, 0.0)
    return (u_star ** 3) / (KAPPA * (zz + z0))


def box_sdf(x, y, z, b: Building) -> np.ndarray:
    """Signed distance to an axis-aligned box [xc-hx,xc+hx] x [yc-hy,yc+hy] x
    [0,H]. Positive outside, negative inside (contract: sdf > 0 in fluid)."""
    qx = np.abs(x - b.xc) - b.hx
    qy = np.abs(y - b.yc) - b.hy
    qz = np.abs(z - b.H / 2.0) - b.H / 2.0
    ox = np.maximum(qx, 0.0)
    oy = np.maximum(qy, 0.0)
    oz = np.maximum(qz, 0.0)
    outside = np.sqrt(ox ** 2 + oy ** 2 + oz ** 2)
    inside = np.minimum(np.maximum(qx, np.maximum(qy, qz)), 0.0)
    return outside + inside


def scene_sdf(x, y, z, buildings: List[Building]) -> np.ndarray:
    sdf = None
    for b in buildings:
        s = box_sdf(x, y, z, b)
        sdf = s if sdf is None else np.minimum(sdf, s)
    return sdf


def local_height(x, y, buildings: List[Building]) -> np.ndarray:
    """Height of the building whose footprint contains (x,y); 0 outside any
    footprint. Used as a network input feature (P25=A)."""
    h = np.zeros_like(x)
    for b in buildings:
        inside = (np.abs(x - b.xc) <= b.hx) & (np.abs(y - b.yc) <= b.hy)
        h = np.where(inside, np.maximum(h, b.H), h)
    return h


# ---------------------------------------------------------------------------
# Differentiable (torch) geometry features, used ONLY for physics-residual
# collocation batches (ml/data.py EpochSampler), not for data generation.
#
# Why this exists (bug found in review): PINNMLP takes sdf and local_height
# as extra inputs (P25=A). Both are, physically, deterministic functions of
# (x, y, z) for a fixed building layout. If the residual code feeds in
# precomputed sdf/height *constants* (read from the HDF5 file, detached from
# the autograd graph) while differentiating the model output w.r.t. (x,y,z),
# torch.autograd.grad silently drops the d(output)/d(sdf) * d(sdf)/d(x,y,z)
# chain-rule term -- largest exactly near walls, since |grad(sdf)| = 1 there.
# The continuity/momentum residuals would then be evaluated against the
# wrong function.
#
# Fix: for collocation points, recompute sdf and local_height from the SAME
# leaf (x, y, z) tensor using an exact, differentiable, closed-form torch
# expression (the box SDF used to generate the data in the first place), so
# autograd sees the true composite dependency. This is only possible here
# because the synthetic geometry is a union of axis-aligned boxes with a
# closed form; real building footprints (arbitrary polygons) have no such
# closed form and would need a differentiable source instead -- e.g. a
# precomputed SDF/height grid sampled with trilinear/bilinear interpolation
# (torch.nn.functional.grid_sample). That grid is a geometry-pipeline
# artifact (E:\PINN\v2\geometry\out\*) outside this package's scope
# (E:\PINN\v2\ml\ and E:\PINN\v2\data\synthetic\ only); ml/data.py falls
# back to the precomputed (non-differentiable) HDF5 sdf/height for any case
# whose variant this module does not recognise, and documents that stage
# B/C residuals near walls are then only approximate.
#
# local_height's hard footprint indicator is additionally discontinuous at
# the footprint edge (a step function), which is not usefully differentiable
# either (zero gradient almost everywhere, hiding the real edge effect). We
# replace it with a smooth logistic-sigmoid soft box of adjustable width
# `smooth_width` (metres) for this differentiable path only; the raw hard
# indicator is still what's stored in the HDF5 file / used for plain data
# loss and plotting.

def torch_box_sdf(x, y, z, b: Building):
    import torch
    qx = torch.abs(x - b.xc) - b.hx
    qy = torch.abs(y - b.yc) - b.hy
    qz = torch.abs(z - b.H / 2.0) - b.H / 2.0
    ox = torch.clamp(qx, min=0.0)
    oy = torch.clamp(qy, min=0.0)
    oz = torch.clamp(qz, min=0.0)
    outside = torch.sqrt(ox ** 2 + oy ** 2 + oz ** 2 + 1e-12)
    inside = torch.clamp(torch.maximum(qx, torch.maximum(qy, qz)), max=0.0)
    return outside + inside


def torch_scene_sdf(x, y, z, buildings: List[Building]):
    import torch
    sdf = None
    for b in buildings:
        s = torch_box_sdf(x, y, z, b)
        sdf = s if sdf is None else torch.minimum(sdf, s)
    return sdf


def torch_local_height_smooth(x, y, buildings: List[Building], smooth_width: float = 2.0):
    import torch
    h = torch.zeros_like(x)
    for b in buildings:
        sx = torch.sigmoid((b.hx - torch.abs(x - b.xc)) / smooth_width)
        sy = torch.sigmoid((b.hy - torch.abs(y - b.yc)) / smooth_width)
        h = h + b.H * sx * sy
    return h


def _building_perturbation(x, y, z, b: Building, ex: float, ey: float, u_star: float,
                            alpha: float = 0.3):
    """Analytic curl(A_i) contribution of one building; returns (du, dv, dw).

    (ex, ey) is the unit *flow direction* (already -(sin th, cos th)).
    See module docstring for the derivation.
    """
    R = float(np.sqrt(b.hx * b.hy))
    Rmin = 0.3 * R
    Xc, Yc = x - b.xc, y - b.yc
    X = Xc * ex + Yc * ey
    Y = -Xc * ey + Yc * ex
    r2 = X ** 2 + Y ** 2
    # Smooth (everywhere-differentiable) regularisation: r2 + Rmin^2 rather
    # than max(r2, Rmin^2). The latter is a non-smooth clip whose gradient
    # w.r.t. X,Y is discontinuous exactly where the clip switches on, which
    # broke the closed-form derivatives below (they assumed d(r2c)/dX=2X,
    # d(r2c)/dY=2Y everywhere -- only true for a *smooth* softening, not a
    # hard max). Verified by finite-difference divergence check.
    r2c = r2 + Rmin ** 2

    Uz = log_law(z, u_star)

    # psi = -Uz * R^2 * Y / r2c  (doublet streamfunction, Az = psi * Hz(z)),
    # r2c = X^2 + Y^2 + Rmin^2 (see note above). Differentiating THIS r2c
    # (not the unregularised r2) correctly:
    #   d/dX = 2*Uz*R^2*X*Y / r2c^2
    #   d/dY = -Uz*R^2*(r2c - 2Y^2) / r2c^2 = -Uz*R^2*(X^2 - Y^2 + Rmin^2) / r2c^2
    # (an earlier version omitted the "+ Rmin^2" here, which broke
    # mixed-partial symmetry and made the field NOT divergence-free --
    # caught by a finite-difference check; verify with the same check if
    # this formula is ever changed again.)
    dpsidX = 2.0 * Uz * R ** 2 * X * Y / (r2c ** 2)
    dpsidY = -Uz * R ** 2 * (X ** 2 - Y ** 2 + Rmin ** 2) / (r2c ** 2)

    # vertical decay of the horizontal recirculation, ~1 near the building,
    # tapering off above ~1.5H
    Hz = 1.0 / (1.0 + (z / (0.6 * b.H)) ** 4)

    u1 = (dpsidX * ey + dpsidY * ex) * Hz
    v1 = (-dpsidX * ex + dpsidY * ey) * Hz

    # vertical velocity term: Ay = C * bump(X,Y) * h(z)
    sigma2 = (1.5 * R) ** 2
    bump = np.exp(-r2 / (2.0 * sigma2))
    C = alpha * log_law(np.array(b.H), u_star) * R
    hz = (z / b.H) * np.exp(-z / b.H)
    hz_prime = np.exp(-z / b.H) * (1.0 / b.H) * (1.0 - z / b.H)

    dbump_dx = bump * (-(X * ex - Y * ey) / sigma2)

    w1 = C * hz * dbump_dx
    extra_u = -C * bump * hz_prime

    return u1 + extra_u, v1, w1


def velocity_field(x, y, z, theta_deg: float, u_star: float, buildings: List[Building]):
    theta = np.deg2rad(theta_deg)
    ex, ey = -np.sin(theta), -np.cos(theta)  # unit flow direction (ENU)
    Uz = log_law(z, u_star)
    u = Uz * ex
    v = Uz * ey
    w = np.zeros_like(z)
    for b in buildings:
        du, dv, dw = _building_perturbation(x, y, z, b, ex, ey, u_star)
        u = u + du
        v = v + dv
        w = w + dw
    return u, v, w


def pressure_field(u, v, w, z, u_star: float) -> np.ndarray:
    """Bernoulli-consistent-ish kinematic pressure (p/rho): p0 - 0.5*(|U|^2 -
    U_base(z)^2). Not a RANS solution -- see module docstring. Kinematic
    (m^2/s^2), and does NOT include 2/3 k (same convention as physics.py /
    OpenFOAM simpleFoam)."""
    Uz = log_law(z, u_star)
    speed2 = u ** 2 + v ** 2 + w ** 2
    return -0.5 * (speed2 - Uz ** 2)


def k_field(u, v, w, z, u_star: float) -> np.ndarray:
    Uz = log_law(z, u_star)
    k_in = inflow_k(u_star)
    speed = np.sqrt(u ** 2 + v ** 2 + w ** 2)
    ratio = (speed - Uz) / np.maximum(Uz, 1e-3)
    factor = 1.0 + 0.5 * np.tanh(ratio)
    return np.maximum(k_in * factor, 1e-6)


def nut_field(k, z, u_star: float) -> np.ndarray:
    eps_in = np.maximum(inflow_eps(z, u_star), 1e-8)
    return np.maximum(CMU * k ** 2 / eps_in, 1e-8)


def _wall_faces(buildings: List[Building], n_per_face: int = 200, rng=None, ground_frac: float = 0.2):
    """Sample building + ground wall-face points.

    Returns (x,y,z,nx,ny,nz,height) -- `height` (M7, design review) is the
    TRUE height of the building that face belongs to (0 for ground), so a
    network reading `local_height` at a wall point sees the same value it
    would see for a fluid point immediately adjacent to that same wall
    (previously hard-coded to 0 everywhere, including at building facades
    and roofs -- an inconsistent feature). `height` also lets metrics.py
    scale corner/wake/canyon zones by the *nearest building's* height H_b
    instead of a single global H_ref (M8).

    `ground_frac` (M7, design review) caps the ground-plane share of wall
    points at roughly `ground_frac` (default 20%) of the total, rather than
    a fixed count independent of how many building points exist -- ground
    faces trivially satisfy u.n=0 (w=0 there), so letting them dominate the
    impermeability loss wastes most of the wall-BC batch on the easiest
    points.
    """
    rng = rng or np.random.default_rng(0)
    xs, ys, zs, nxs, nys, nzs, hs = [], [], [], [], [], [], []
    for b in buildings:
        n = n_per_face
        # 4 vertical faces
        for sign, axis in [(+1, "x"), (-1, "x"), (+1, "y"), (-1, "y")]:
            zz = rng.uniform(0.0, b.H, n)
            if axis == "x":
                yy = rng.uniform(b.yc - b.hy, b.yc + b.hy, n)
                xx = np.full(n, b.xc + sign * b.hx)
                nx_, ny_ = float(sign), 0.0
            else:
                xx = rng.uniform(b.xc - b.hx, b.xc + b.hx, n)
                yy = np.full(n, b.yc + sign * b.hy)
                nx_, ny_ = 0.0, float(sign)
            xs.append(xx); ys.append(yy); zs.append(zz)
            nxs.append(np.full(n, nx_)); nys.append(np.full(n, ny_)); nzs.append(np.zeros(n))
            hs.append(np.full(n, b.H))
        # roof
        xx = rng.uniform(b.xc - b.hx, b.xc + b.hx, n)
        yy = rng.uniform(b.yc - b.hy, b.yc + b.hy, n)
        zz = np.full(n, b.H)
        xs.append(xx); ys.append(yy); zs.append(zz)
        nxs.append(np.zeros(n)); nys.append(np.zeros(n)); nzs.append(np.ones(n))
        hs.append(np.full(n, b.H))

    n_building = sum(a.size for a in xs)
    n_ground_target = max(1, int(round(n_building * ground_frac / (1.0 - ground_frac))))
    # oversample then trim to exactly n_ground_target after excluding footprints
    gx = rng.uniform(-LX / 2, LX / 2, n_ground_target * 3)
    gy = rng.uniform(-LY / 2, LY / 2, n_ground_target * 3)
    inside_any = np.zeros(gx.shape[0], dtype=bool)
    for b in buildings:
        inside_any |= (np.abs(gx - b.xc) <= b.hx) & (np.abs(gy - b.yc) <= b.hy)
    gx, gy = gx[~inside_any][:n_ground_target], gy[~inside_any][:n_ground_target]
    gz = np.zeros_like(gx)
    xs.append(gx); ys.append(gy); zs.append(gz)
    nxs.append(np.zeros_like(gx)); nys.append(np.zeros_like(gx)); nzs.append(np.ones_like(gx))
    hs.append(np.zeros_like(gx))
    return (np.concatenate(xs).astype(np.float32), np.concatenate(ys).astype(np.float32),
            np.concatenate(zs).astype(np.float32), np.concatenate(nxs).astype(np.float32),
            np.concatenate(nys).astype(np.float32), np.concatenate(nzs).astype(np.float32),
            np.concatenate(hs).astype(np.float32))


def case_id(variant: str, theta_deg: float, u10: float, mesh_id: str = MESH_ID) -> str:
    return f"zt_{variant}_th{int(round(theta_deg * 10)):04d}_U{int(round(u10 * 10)):03d}_{mesh_id}"


def _z_levels() -> np.ndarray:
    """Vertical levels for the synthetic grid: a uniform grid (the previous
    approach, spacing ~2.9 m for NZ=22 over ZTOP=60 m) has NO points at all
    in the 1.5-2.0 m pedestrian-comfort band (design review M10 -- the
    headline metric height), silently making any pedestrian-layer metric
    empty on this smoke data. A few explicit near-ground levels (matching
    typical near-wall CFD mesh refinement practice) fix that while keeping
    the rest of the domain at roughly the original coarse spacing."""
    near_ground = np.array([0.0, 0.5, 1.0, 1.5, 1.75, 2.0, 2.5, 3.5, 5.0, 7.5, 10.0])
    n_upper = max(NZ - len(near_ground), 4)
    upper = np.linspace(near_ground[-1], ZTOP, n_upper)[1:]  # avoid duplicating 10.0
    return np.concatenate([near_ground, upper]).astype(np.float64)


def generate_case(variant: str, theta_deg: float, u10: float, split: str, out_dir: Path) -> Tuple[str, dict]:
    buildings = VARIANTS[variant]
    u_star = u_star_from_u10(u10)

    xs = np.linspace(-LX / 2, LX / 2, NX)
    ys = np.linspace(-LY / 2, LY / 2, NY)
    zs = _z_levels()
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    x, y, z = X.ravel(), Y.ravel(), Z.ravel()

    sdf = scene_sdf(x, y, z, buildings)
    fluid = sdf > 0.0  # keep only fluid points (contract: region is the ZOI, cells are fluid cells)
    x, y, z, sdf = x[fluid], y[fluid], z[fluid], sdf[fluid]

    u, v, w = velocity_field(x, y, z, theta_deg, u_star, buildings)
    p = pressure_field(u, v, w, z, u_star)
    k = k_field(u, v, w, z, u_star)
    nut = nut_field(k, z, u_star)
    eps = inflow_eps(z, u_star)

    wall_dist = np.minimum(sdf, z)
    dx = LX / (NX - 1)
    dy = LY / (NY - 1)
    first_layer = 0.75 * dx
    is_wall_adjacent = (wall_dist < first_layer).astype(np.uint8)
    lheight = local_height(x, y, buildings)
    # cell volume: dx*dy uniform, dz from the (non-uniform, M10) z levels --
    # a per-point lookup of that level's thickness (half the sum of its two
    # neighbouring gaps; a single adjacent gap at the top/bottom boundary).
    zs_sorted = np.sort(zs)
    dz_levels = np.empty_like(zs_sorted)
    dz_levels[0] = zs_sorted[1] - zs_sorted[0]
    dz_levels[-1] = zs_sorted[-1] - zs_sorted[-2]
    dz_levels[1:-1] = (zs_sorted[2:] - zs_sorted[:-2]) / 2.0
    z_to_dz = dict(zip(zs_sorted.tolist(), dz_levels.tolist()))
    dz_per_point = np.array([z_to_dz[zi] for zi in z], dtype=np.float32)
    vol = (dx * dy * dz_per_point).astype(np.float32)

    cid = case_id(variant, theta_deg, u10)
    out_path = out_dir / f"{cid}.h5"
    out_dir.mkdir(parents=True, exist_ok=True)

    u_h = float(log_law(np.array(H_REF), u_star))

    with h5py.File(out_path, "w") as f:
        for name, arr in [("x", x), ("y", y), ("z", z), ("u", u), ("v", v), ("w", w),
                           ("p", p), ("k", k), ("nut", nut), ("epsilon", eps),
                           ("vol", vol), ("wall_dist", wall_dist), ("sdf", sdf),
                           ("local_height", lheight)]:
            f.create_dataset(name, data=arr.astype(np.float32))
        f.create_dataset("is_wall_adjacent", data=is_wall_adjacent)

        wfx, wfy, wfz, wnx, wny, wnz, wfh = _wall_faces(buildings, rng=np.random.default_rng(42))
        wf = f.create_group("wall_faces")
        wf.create_dataset("x", data=wfx); wf.create_dataset("y", data=wfy); wf.create_dataset("z", data=wfz)
        wf.create_dataset("nx", data=wnx); wf.create_dataset("ny", data=wny); wf.create_dataset("nz", data=wnz)
        wf.create_dataset("height", data=wfh)  # M7: true building height at this face (0 for ground)

        zi = np.linspace(0.0, ZTOP, 64).astype(np.float32)
        ui = log_law(zi, u_star).astype(np.float32)
        ki = np.full_like(zi, inflow_k(u_star))
        epsi = inflow_eps(zi, u_star).astype(np.float32)
        ip = f.create_group("inlet_profile")
        ip.create_dataset("z", data=zi); ip.create_dataset("u", data=ui)
        ip.create_dataset("k", data=ki); ip.create_dataset("eps", data=epsi)

        f.attrs["theta_deg"] = theta_deg
        f.attrs["U10"] = u10
        f.attrs["u_star"] = u_star
        f.attrs["z0"] = Z0_URBAN
        f.attrs["d"] = D_DISPLACEMENT
        f.attrs["kappa"] = KAPPA
        f.attrs["Cmu"] = CMU
        f.attrs["variant"] = variant
        f.attrs["mesh_id"] = MESH_ID
        f.attrs["turb_model"] = TURB_MODEL
        f.attrs["solver"] = SOLVER
        f.attrs["of_version"] = "synthetic-v2"
        f.attrs["n_iter"] = 0
        f.attrs["converged"] = True
        f.attrs["final_residuals"] = json.dumps({"note": "synthetic, no solver residuals"})
        f.attrs["rho"] = RHO_MTY
        f.attrs["created"] = "synthetic.py"
        # non-contract but documented extras needed for non-dimensionalisation
        f.attrs["h_ref"] = H_REF
        f.attrs["u_h"] = u_h
        f.attrs["split"] = split

    meta = dict(case_id=cid, variant=variant, theta_deg=theta_deg, U10=u10, mesh_id=MESH_ID,
                turb_model=TURB_MODEL, split=split, n_points=int(x.size), converged=True,
                path=str(out_path.as_posix()))
    return cid, meta


def generate_all(out_dir: str = "data/synthetic") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for variant, theta, u10, split in CASES:
        cid, meta = generate_case(variant, theta, u10, split, out)
        rows.append(meta)
        print(f"wrote {meta['path']}  n_points={meta['n_points']}  split={split}")
    import csv
    manifest_path = out / "manifest.csv"
    fieldnames = ["case_id", "variant", "theta_deg", "U10", "mesh_id", "turb_model",
                  "split", "n_points", "converged", "path"]
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"wrote manifest {manifest_path}")
    seal_manifest(manifest_path)
    return manifest_path


def seal_manifest(manifest_path: Path) -> str:
    """Write a SHA-256 sidecar (M9, design review): the authoritative
    train/val/test split must come from the manifest, verified against this
    hash at load time (ml/data.py), not from each HDF5 file's own `split`
    attribute (which could silently drift from the manifest, e.g. if a case
    file is regenerated or hand-edited without updating manifest.csv)."""
    import hashlib
    digest = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    sha_path = Path(str(manifest_path) + ".sha256")
    sha_path.write_text(digest + "\n", encoding="utf-8")
    print(f"wrote {sha_path} ({digest[:12]}...)")
    return digest


if __name__ == "__main__":
    generate_all()
