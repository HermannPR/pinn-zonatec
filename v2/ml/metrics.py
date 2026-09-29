"""Evaluation metrics (P27 = B+C+D): relative L2, MAE of K=|U|/U10, VDI 3783-9
hit rate, and per-zone (corner/wake/canyon) error, all computed on physical
(dimensional) fields so they are directly comparable across cases with
different U_H.

VDI 3783 Part 9 hit rate -- source & uncertainty
--------------------------------------------------
VDI 3783 Blatt 9 ("Environmental meteorology - Prognostic microscale
windfield models - Evaluation for flow around buildings and obstacles")
defines a hit-rate quality criterion of the form

    hit_i = 1  if  |P_i - O_i| <= W   or   |P_i - O_i| / |O_i| <= D
    hit_i = 0  otherwise

combining a relative threshold D with an absolute threshold W so that
points where the observed value O_i is near zero are not penalised by an
exploding relative error. We could not access the exact numeric table of
the standard from this environment, so the commonly-cited values found in
secondary literature on VDI 3783-9 validation studies are used as
*defaults*: D = 0.25 (25% relative deviation) and W = 0.05 * U_ref (5% of
the reference/free-stream speed) for velocity components. **Both are
exposed as function parameters (`D`, `w_abs`) so they can be corrected once
the actual clause is checked against a copy of the standard -- treat the
defaults as provisional.**
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional

import numpy as np
from scipy.spatial import cKDTree


# ---------------------------------------------------------------------------
# Core accuracy metrics
# ---------------------------------------------------------------------------

def relative_l2(pred: np.ndarray, true: np.ndarray) -> float:
    num = np.linalg.norm(pred - true)
    den = np.linalg.norm(true)
    return float(num / den) if den > 0 else float("nan")


def relative_l2_per_component(pred: Dict[str, np.ndarray], true: Dict[str, np.ndarray],
                               fields: List[str] = ("u", "v", "w", "p", "k", "nut")) -> Dict[str, float]:
    return {f: relative_l2(pred[f], true[f]) for f in fields}


def mae_speedup_factor(u_pred, v_pred, w_pred, u_true, v_true, w_true, u10: float) -> float:
    """MAE of K = |U_local| / U10 (the amplification factor reported to
    users). Inputs must be physical (dimensional) velocity components."""
    k_pred = np.sqrt(u_pred ** 2 + v_pred ** 2 + w_pred ** 2) / u10
    k_true = np.sqrt(u_true ** 2 + v_true ** 2 + w_true ** 2) / u10
    return float(np.mean(np.abs(k_pred - k_true)))


def vdi_hit_rate(pred: np.ndarray, obs: np.ndarray, D: float = 0.25, w_abs: float = None,
                  u_ref: float = None) -> float:
    """VDI 3783-9 style hit rate. Provide either `w_abs` directly or
    `u_ref` (then w_abs = 0.05 * u_ref is used) -- see module docstring for
    the provenance/uncertainty of these defaults."""
    if w_abs is None:
        if u_ref is None:
            raise ValueError("provide either w_abs or u_ref")
        w_abs = 0.05 * u_ref
    diff = np.abs(pred - obs)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(np.abs(obs) > 0, diff / np.abs(obs), np.inf)
    hit = (diff <= w_abs) | (rel <= D)
    return float(np.mean(hit))


# ---------------------------------------------------------------------------
# Zone labelling (corner / wake / canyon) -- simple, documented heuristics
# built from SDF + wall-face geometry + flow direction. See module docstring
# of ml/metrics.py; kept deliberately simple per the design brief.
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ZoneMasks:
    corner: np.ndarray
    wake: np.ndarray
    canyon: np.ndarray
    other: np.ndarray


def label_zones(x, y, z, sdf, theta_deg: float, h_ref: float,
                 wall_x, wall_y, wall_z, wall_nx, wall_ny, wall_nz,
                 r_wall: Optional[float] = None, r_wake: Optional[float] = None,
                 r_canyon: Optional[float] = None, corner_angle_deg: float = 30.0,
                 canyon_opposite_cos: float = -0.5) -> ZoneMasks:
    r_wall = r_wall if r_wall is not None else 0.15 * h_ref
    r_wake = r_wake if r_wake is not None else 5.0 * h_ref
    r_canyon = r_canyon if r_canyon is not None else 2.0 * h_ref

    pts = np.stack([x, y, z], axis=1)
    wall_pts = np.stack([wall_x, wall_y, wall_z], axis=1)
    tree = cKDTree(wall_pts)

    d0, idx0 = tree.query(pts, k=1)
    n0 = np.stack([wall_nx[idx0], wall_ny[idx0], wall_nz[idx0]], axis=1)

    # corner: neighbourhood of the nearest wall point contains faces whose
    # normals differ a lot from n0 (i.e. two non-parallel faces meet nearby)
    neigh_idx = tree.query_ball_point(wall_pts[idx0], r=max(1.0, 0.3 * h_ref))
    corner = np.zeros(len(pts), dtype=bool)
    for i, nbrs in enumerate(neigh_idx):
        if len(nbrs) < 2:
            continue
        nb_normals = np.stack([wall_nx[nbrs], wall_ny[nbrs], wall_nz[nbrs]], axis=1)
        cos_sim = nb_normals @ n0[i]
        cos_sim = np.clip(cos_sim, -1.0, 1.0)
        max_angle = np.degrees(np.arccos(cos_sim.min()))
        if max_angle > corner_angle_deg:
            corner[i] = True
    corner &= d0 < r_wall

    theta = np.deg2rad(theta_deg)
    ex, ey = -np.sin(theta), -np.cos(theta)
    flow = np.array([ex, ey, 0.0])
    v = pts - wall_pts[idx0]
    along = v @ flow
    leeward = n0 @ flow  # face outward normal roughly aligned with flow => leeward face
    wake = (d0 < r_wake) & (along > 0.3 * h_ref) & (along < r_wake) & (leeward > 0.15)

    # canyon: at least two wall clusters on roughly opposite sides nearby
    canyon = np.zeros(len(pts), dtype=bool)
    neigh_c = tree.query_ball_point(pts, r=r_canyon)
    for i, nbrs in enumerate(neigh_c):
        if len(nbrs) < 2:
            continue
        vecs = wall_pts[nbrs] - pts[i]
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        u = vecs / norms
        # any pair with opposite direction?
        dots = u @ u.T
        if np.any(dots < canyon_opposite_cos):
            canyon[i] = True

    other = ~(corner | wake | canyon)
    return ZoneMasks(corner=corner, wake=wake, canyon=canyon, other=other)


def per_zone_relative_l2(pred: Dict[str, np.ndarray], true: Dict[str, np.ndarray], zones: ZoneMasks,
                          fields: List[str] = ("u", "v", "w")) -> Dict[str, Dict[str, float]]:
    out = {}
    for zone_name in ["corner", "wake", "canyon", "other"]:
        mask = getattr(zones, zone_name)
        if mask.sum() == 0:
            out[zone_name] = {f: float("nan") for f in fields}
            continue
        out[zone_name] = {f: relative_l2(pred[f][mask], true[f][mask]) for f in fields}
    return out
