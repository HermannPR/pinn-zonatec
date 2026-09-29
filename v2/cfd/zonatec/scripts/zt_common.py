"""Shared constants and helpers for the Zona Tec CFD pipeline (v2/cfd/zonatec).

Single place for: domain size (from geometry/out/<scenario>/frame.json), mesh levels (GCI), refinement boxes,
wind-direction conventions (DATA_CONTRACT), inflow (climate/transfer.py) and OpenFOAM dictionary helpers.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np

V2 = Path(r"E:\PINN\v2")
GEOM = V2 / "geometry" / "out"
ZT = V2 / "cfd" / "zonatec"
RUNS = Path(r"E:\PINN\runs\zonatec")
PY = r"E:\PINN\.venv\Scripts\python.exe"
PY_UNIX = "/e/PINN/.venv/Scripts/python.exe"
SCRIPTS_UNIX = "/e/PINN/v2/cfd/zonatec/scripts"

KAPPA = 0.41
CMU = 0.09
N_SEG = 32                     # lateral boundary segments (11.25 deg each), see README §3
Z0_ZOI_DEFAULT = 0.05          # m, local ground roughness between explicit buildings (README §4)

sys.path.insert(0, str(V2 / "climate"))
sys.path.insert(0, str(V2 / "geometry"))


def frame(scenario: str = "H_best") -> dict:
    return json.loads((GEOM / scenario / "frame.json").read_text())


def domain(scenario: str = "H_best") -> dict:
    """Circular domain (geometry/out/<sc>/domain_circular_recommendation.md): R = ring_half*sqrt2 + 15 H_max,
    height = 6 H_max."""
    f = frame(scenario)
    H = f["H_max"]
    R = f["ring_half_size_m"] * math.sqrt(2) + 15 * H
    return {"R": R, "Htop": 6 * H, "H_max": H, "H_ref": f["H_ref"], "zoi_half": f["zoi_half_size_m"],
            "ring_half": f["ring_half_size_m"], "eval_half": f["eval_half_size_m"]}


# ---------------------------------------------------------------------------------------------------------------
# Mesh levels. The central O-grid block is a square of half-side S_CORE; its ground is patch ground_zoi.
# n_core cells across it define the background size D0 = 2 S_CORE / n_core; snappy levels 1..4 give D0/2..D0/16.
# Refinement ratio between levels r = D0_coarser / D0_finer (Celik et al. 2008 recommend r > 1.3).
S_CORE = 576.0                 # m: covers every explicit building (ring buildings reach |x|,|y| = 575 m)
LEVELS = {
    "fine":    {"n_core": 36},  # D0 = 32.0 m -> 2.00 m at level 4   (campaign mesh = GCI fine)
    "medium":  {"n_core": 27},  # D0 = 42.7 m -> 2.67 m              r21 = 1.333
    "coarse":  {"n_core": 20},  # D0 = 57.6 m -> 3.60 m              r32 = 1.350
    "xcoarse": {"n_core": 9},   # D0 = 128 m -> 8 m   (pipeline smoke test only, not for results)
}


def level_info(level: str) -> dict:
    n = LEVELS[level]["n_core"]
    D0 = 2 * S_CORE / n
    return {"level": level, "n_core": n, "D0": D0, "d4": D0 / 16, "d3": D0 / 8, "d2": D0 / 4, "d1": D0 / 2}


# Refinement regions (physical size identical for all levels; ZT-ENU metres). Level numbers relative to D0.
def refinement_boxes(scenario: str = "H_best") -> dict:
    d = domain(scenario)
    return {
        # level 4 (2 m on the fine mesh): pedestrian layer over the whole ZOI (+margin; ZOI buildings reach 455 m)
        "L4_zoi": {"level": 4, "min": (-460, -460, -1), "max": (460, 460, 8.0)},
        # level 3 (4 m): ZOI + ring, up to 32 m (ring buildings <= 47.6 m also get surface level 3)
        "L3_ring": {"level": 3, "min": (-600, -600, -1), "max": (600, 600, 32.0)},
        # level 2 (8 m): around ZOI+ring up to ~1.5 H_max
        "L2_box": {"level": 2, "min": (-720, -720, -1), "max": (720, 720, 1.5 * d["H_max"])},
        # level 1 (16 m): approach-flow cylinder
        "L1_cyl": {"level": 1, "cylinder": True, "radius": 1300.0, "z": (-1, 3 * d["H_max"])},
    }


def tower_regions(scenario: str = "H_best") -> list[dict]:
    import pandas as pd
    t = pd.read_csv(GEOM / scenario / "tower_refinement_regions.csv")
    out = []
    for _, r in t.iterrows():
        out.append({"name": f"tower_{int(r.osm_id)}", "level": 3, "min": (r.region_xmin, r.region_ymin, -1.0),
                    "max": (r.region_xmax, r.region_ymax, r.region_z_top_m), "h": r.height_m,
                    "fp": (r.footprint_xmin, r.footprint_ymin, r.footprint_xmax, r.footprint_ymax)})
    return out


# ---------------------------------------------------------------------------------------------------------------
# Wind direction (DATA_CONTRACT): theta = direction the wind comes FROM, clockwise from North.
def flow_dir(theta_deg: float) -> np.ndarray:
    t = math.radians(theta_deg)
    return np.array([-math.sin(t), -math.cos(t), 0.0])


def segment_angles(n: int = N_SEG):
    """math angle (ccw from +x) of the outward normal: segment k spans [k, k+1) * 360/n degrees"""
    w = 360.0 / n
    return [(k * w, (k + 1) * w) for k in range(n)]


def segment_roles(theta_deg: float, n: int = N_SEG, tol: float = 0.2) -> list[str]:
    """'inlet' if the segment-averaged U.n/|U| < tol, else 'outlet'.
    Segment-average of cos over [a,b]: (sin(b-phi_e) - sin(a-phi_e)) / (b-a). tol=0.2 puts the two segments
    adjoining the U.n = 0 line on the outflow side (mean U.n/|U| = +0.098) also on the Dirichlet inlet profile
    (README §3): the undisturbed far-field profile is imposed there instead of an inletOutlet switch."""
    e = flow_dir(theta_deg)
    phi_e = math.atan2(e[1], e[0])
    roles = []
    for a, b in segment_angles(n):
        a, b = math.radians(a), math.radians(b)
        mean_cos = (math.sin(b - phi_e) - math.sin(a - phi_e)) / (b - a)
        roles.append("inlet" if mean_cos < tol else "outlet")
    return roles


# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Inflow:
    theta_deg: float
    U10: float
    z0: float           # fetch (inlet + ground_outer) roughness
    u_star: float
    T: float
    z0_method: str
    d_inlet: float = 0.0    # P12: d = 0 at the inlet
    d_morph: float = 0.0    # Macdonald d of the sector (reported only)

    def U(self, z):
        return self.u_star / KAPPA * np.log((np.asarray(z) + self.z0) / self.z0)

    @property
    def k(self):
        return self.u_star ** 2 / math.sqrt(CMU)

    def eps(self, z):
        return self.u_star ** 3 / (KAPPA * (np.asarray(z) + self.z0))

    def omega(self, z):
        return self.eps(z) / (CMU * self.k)


def inflow(theta_deg: float, U10: float, z0_method: str = "macdonald", z0_override: float | None = None) -> Inflow:
    import transfer as tr
    if z0_override is not None:
        z0, d = z0_override, 0.0
        method = f"override_{z0_override:g}"
    else:
        tab = tr.load_roughness_table()
        row = tab.loc[float(theta_deg)]
        res = tr.inflow_for_sector(theta_deg, U10, row, z0_method=z0_method)
        z0, d, method = res.z0, res.d, z0_method
    T = float(tr.transfer_factor(z0))
    return Inflow(theta_deg=theta_deg, U10=U10, z0=float(z0), u_star=T * U10, T=T, z0_method=method, d_morph=float(d))


def case_id(variant: str, theta: float, U10: float, level: str, model: str | None = None, tag: str = "") -> str:
    mesh = {"fine": "m1", "medium": "m2", "coarse": "m3", "xcoarse": "mx"}[level]
    s = f"zt_{variant}_th{int(round(theta * 10)):04d}_U{int(round(U10 * 10)):03d}_{mesh}"
    if model and model != "realizableKE":
        s += "_" + {"kEpsilon": "ske", "kOmegaSST": "sst", "realizableKE": "rke"}[model]
    return s + (f"_{tag}" if tag else "")


# ---------------------------------------------------------------------------------------------------------------
HDR = """/*--------------------------------*- C++ -*----------------------------------*\\
  PINN Zona Tec - generated by v2/cfd/zonatec/scripts ({gen})
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    version     2.0;
    format      ascii;
    class       {cls};
    {loc}object      {obj};
}}
"""


def foam(path: Path, cls: str, obj: str, body: str, gen: str = "", loc: str = ""):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    l = f'location    "{loc}";\n    ' if loc else ""
    path.write_text(HDR.format(cls=cls, obj=obj, gen=gen, loc=l) + body.strip() + "\n", newline="\n")


def write_text(path: Path, txt: str, exe: bool = False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(txt, newline="\n")


def to_unix(p) -> str:
    p = str(Path(p).resolve())
    return "/" + p[0].lower() + p[2:].replace("\\", "/")


def dump_json(path: Path, obj):
    def conv(o):
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if hasattr(o, "__dataclass_fields__"):
            return asdict(o)
        raise TypeError(type(o))
    Path(path).write_text(json.dumps(obj, indent=2, default=conv))
