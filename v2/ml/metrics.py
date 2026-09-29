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
exploding relative error. D = 0.25 is confirmed reasonable by design review
(M10). W = 0.05*U_ref is the module's provisional default, but per M10 this
is quite permissive at the pedestrian layer (typical K = 0.2-0.6 there means
W = 0.05*U_ref is 10-25% of the *local* speed, not 5%). When the reference
is CFD rather than a repeatable measurement, W should instead be set from
the CFD's own numerical uncertainty (e.g. the 90th percentile of a grid
convergence index (GCI) times |U| at the evaluation height) -- `w_abs` and
`D` are exposed as parameters specifically so this can be substituted once
that GCI estimate exists; report a `W=0` variant alongside any nonzero-W
result so the "how permissive was W" question always has an answer (M10).
"""
from __future__ import annotations

import dataclasses
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.spatial import cKDTree


# ---------------------------------------------------------------------------
# Core accuracy metrics
# ---------------------------------------------------------------------------

def relative_l2(pred: np.ndarray, true: np.ndarray, weight: Optional[np.ndarray] = None) -> float:
    """Relative L2 error. `weight` (M10, design review -- typically cell
    volume `vol`) turns this into a volume-weighted (discrete L2(dOmega))
    norm instead of a plain per-point norm, so refined-mesh regions don't
    dominate simply because they contain more points."""
    if weight is None:
        num = np.linalg.norm(pred - true)
        den = np.linalg.norm(true)
    else:
        w = np.asarray(weight, dtype=np.float64)
        num = np.sqrt(np.sum(w * (pred - true) ** 2))
        den = np.sqrt(np.sum(w * true ** 2))
    return float(num / den) if den > 0 else float("nan")


def relative_l2_per_component(pred: Dict[str, np.ndarray], true: Dict[str, np.ndarray],
                               fields: List[str] = ("u", "v", "w", "p", "k", "nut"),
                               weight: Optional[np.ndarray] = None) -> Dict[str, float]:
    return {f: relative_l2(pred[f], true[f], weight=weight) for f in fields}


def mae_speedup_factor(u_pred, v_pred, w_pred, u_true, v_true, w_true, u10: float,
                        weight: Optional[np.ndarray] = None) -> float:
    """MAE of K = |U_local| / U10 (the amplification factor reported to
    users). Inputs must be physical (dimensional) velocity components.
    `weight` (M10) volume-weights the mean."""
    k_pred = np.sqrt(u_pred ** 2 + v_pred ** 2 + w_pred ** 2) / u10
    k_true = np.sqrt(u_true ** 2 + v_true ** 2 + w_true ** 2) / u10
    err = np.abs(k_pred - k_true)
    if weight is None:
        return float(np.mean(err))
    w = np.asarray(weight, dtype=np.float64)
    return float(np.sum(w * err) / max(np.sum(w), 1e-30))


def vdi_hit_rate(pred: np.ndarray, obs: np.ndarray, D: float = 0.25, w_abs: float = None,
                  u_ref: float = None, weight: Optional[np.ndarray] = None) -> float:
    """VDI 3783-9 style hit rate. Provide either `w_abs` directly or
    `u_ref` (then w_abs = 0.05 * u_ref is used) -- see module docstring for
    the provenance/uncertainty of these defaults. `weight` (M10) volume-
    weights the hit fraction."""
    if w_abs is None:
        if u_ref is None:
            raise ValueError("provide either w_abs or u_ref")
        w_abs = 0.05 * u_ref
    diff = np.abs(pred - obs)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(np.abs(obs) > 0, diff / np.abs(obs), np.inf)
    hit = (diff <= w_abs) | (rel <= D)
    if weight is None:
        return float(np.mean(hit))
    w = np.asarray(weight, dtype=np.float64)
    return float(np.sum(w * hit) / max(np.sum(w), 1e-30))


def pedestrian_layer_mask(z: np.ndarray, z_lo: float = 1.5, z_hi: float = 2.0) -> np.ndarray:
    """Boolean mask for the pedestrian-comfort layer (M10, design review):
    the headline K/|U| metrics should be reported at 1.5-2.0 m, not
    averaged over the whole ZOI volume (z<=2*H_max), where tall, easy,
    undisturbed points dominate a plain volume/point average."""
    return (z >= z_lo) & (z <= z_hi)


# ---------------------------------------------------------------------------
# Zone labelling (corner / wake / canyon)
#
# M8 (design review) fixes to an earlier version:
#   * The nearest-wall-point search included GROUND faces (wall_faces
#     contains both building and ground samples, per the data contract).
#     Since almost every low point's single nearest neighbour is a ground
#     face with n=(0,0,1), that broke all three labels near ground level
#     (no wake ever detected; nearly everything near a building base
#     flagged "corner" from a normal mismatch against the ground; canyon
#     over-triggered too). Ground faces (height==0, see synthetic.py /
#     data.py's wall_faces 'height' field, M7) are now excluded from the
#     KDTree used for zone labelling -- only building faces define
#     corner/wake/canyon.
#   * Radii scaled off a single global H_ref (85 m for the real campus) are
#     the wrong physical scale for a building-relative zone (a "corner" 12.8
#     m from a wall, a "wake" 425 m long): radii now scale off H_b, the
#     HEIGHT OF THE NEAREST BUILDING at each point (from the same 'height'
#     field), which is O(10-30 m) and the actually-relevant length scale.
#   * This also fixes the complexity complaint indirectly: H_b-based radii
#     are typically several times smaller than H_ref-based ones for a real
#     campus, shrinking the neighbour counts `query_ball_point` has to
#     handle at each point.
#
# Still-simplified (documented, not fully implemented -- time-boxed):
# the corner test is still "normal spread near the nearest wall point"
# rather than an exact building-footprint interior-vertex-angle test, and
# the wake test doesn't check the building's exact lateral width. Both are
# reasonable, cheap proxies but not the precise definitions M8 proposes.
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class ZoneMasks:
    corner: np.ndarray
    wake: np.ndarray
    canyon: np.ndarray
    other: np.ndarray


def label_zones(x, y, z, sdf, theta_deg: float, h_ref: float,
                 wall_x, wall_y, wall_z, wall_nx, wall_ny, wall_nz,
                 wall_height: Optional[np.ndarray] = None,
                 r_wall_factor: float = 0.5, r_wake_factor: float = 3.0,
                 r_canyon_factor: float = 2.0, corner_angle_deg: float = 30.0,
                 canyon_opposite_cos: float = -0.8,
                 z_range: Optional[Tuple[float, float]] = None) -> ZoneMasks:
    """`wall_height` (M7/M8): per-wall-point building height, 0 for ground.
    If omitted (legacy files), falls back to treating every wall point as a
    building face scaled by the global `h_ref` (the old, coarser behaviour).
    `z_range` (M10), if given, restricts labelling to a height band (e.g.
    the pedestrian layer); points outside are labelled 'other'.
    """
    pts = np.stack([x, y, z], axis=1)
    n_pts = len(x)

    if wall_height is not None:
        building_mask = wall_height > 1e-6
        if not np.any(building_mask):
            building_mask = np.ones_like(wall_height, dtype=bool)  # degenerate: no buildings at all
        b_x, b_y, b_z = wall_x[building_mask], wall_y[building_mask], wall_z[building_mask]
        b_nx, b_ny, b_nz = wall_nx[building_mask], wall_ny[building_mask], wall_nz[building_mask]
        b_h = wall_height[building_mask]
    else:
        b_x, b_y, b_z, b_nx, b_ny, b_nz = wall_x, wall_y, wall_z, wall_nx, wall_ny, wall_nz
        b_h = np.full_like(wall_x, h_ref)

    wall_pts = np.stack([b_x, b_y, b_z], axis=1)
    tree = cKDTree(wall_pts)
    n_building = len(b_x)

    d0, idx0 = tree.query(pts, k=1)
    n0 = np.stack([b_nx[idx0], b_ny[idx0], b_nz[idx0]], axis=1)
    Hb = b_h[idx0]  # nearest building's own height, per query point

    r_wall = np.maximum(r_wall_factor * Hb, 1.0)
    r_wake = np.maximum(r_wake_factor * Hb, 3.0)
    r_canyon = np.maximum(r_canyon_factor * Hb, 2.0)

    # M8 (design review, complexity): both corner and canyon detection are
    # fully vectorised fixed-k nearest-neighbour batch queries (a single
    # tree.query(pts, k=k) call each) instead of a variable-radius
    # query_ball_point + a per-point Python loop -- the latter was
    # O(N * neighbours-within-radius) with meaningful per-point Python
    # overhead, and at real-campus point counts (~1-2M) was impractically
    # slow (confirmed: a first version of this fix hung for >5 min at
    # smoke-test scale, 46k points x 5 cases, and was killed).

    # corner: among the k nearest BUILDING-face points to each query point,
    # do any two normals differ by more than corner_angle_deg (two
    # non-parallel faces meeting nearby -- a vertical edge)?
    k_corner = min(8, n_building)
    _, nn_idx = tree.query(pts, k=k_corner)
    if k_corner == 1:
        nn_idx = nn_idx[:, None]
    nb_normals = np.stack([b_nx[nn_idx], b_ny[nn_idx], b_nz[nn_idx]], axis=-1)  # [N,k,3]
    cos_sim = np.clip(np.einsum("nkd,nd->nk", nb_normals, n0), -1.0, 1.0)
    max_angle = np.degrees(np.arccos(cos_sim.min(axis=1)))
    corner = (max_angle > corner_angle_deg) & (d0 < r_wall)

    theta = np.deg2rad(theta_deg)
    ex, ey = -np.sin(theta), -np.cos(theta)
    flow = np.array([ex, ey, 0.0])
    v = pts - wall_pts[idx0]
    along = v @ flow
    leeward = n0 @ flow  # face outward normal roughly aligned with flow => leeward face
    wake = (d0 < r_wake) & (along > 0.3 * Hb) & (along < r_wake) & (leeward > 0.15)

    # canyon: among the k nearest building-face points (within r_canyon), do
    # any two point in roughly opposite directions from the query point?
    k_canyon = min(12, n_building)
    dists_c, idx_c = tree.query(pts, k=k_canyon)
    if k_canyon == 1:
        dists_c, idx_c = dists_c[:, None], idx_c[:, None]
    vecs = wall_pts[idx_c] - pts[:, None, :]  # [N,k,3]
    norms = np.linalg.norm(vecs, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    u_ = vecs / norms
    valid = dists_c <= r_canyon[:, None]  # [N,k]
    dots = np.einsum("nkd,njd->nkj", u_, u_)  # [N,k,k]
    pair_valid = valid[:, :, None] & valid[:, None, :]
    opposite = (dots < canyon_opposite_cos) & pair_valid
    canyon = opposite.any(axis=(1, 2))

    if z_range is not None:
        # points outside the band are excluded from ALL FOUR categories
        # (including 'other') -- they simply aren't part of this
        # (typically pedestrian-layer) breakdown, rather than incorrectly
        # counting as 'other'.
        in_band = pedestrian_layer_mask(z, *z_range)
        corner &= in_band
        wake &= in_band
        canyon &= in_band
        other = in_band & ~(corner | wake | canyon)
    else:
        other = ~(corner | wake | canyon)
    return ZoneMasks(corner=corner, wake=wake, canyon=canyon, other=other)


def per_zone_relative_l2(pred: Dict[str, np.ndarray], true: Dict[str, np.ndarray], zones: ZoneMasks,
                          fields: List[str] = ("u", "v", "w"),
                          weight: Optional[np.ndarray] = None) -> Dict[str, Dict[str, float]]:
    out = {}
    for zone_name in ["corner", "wake", "canyon", "other"]:
        mask = getattr(zones, zone_name)
        if mask.sum() == 0:
            out[zone_name] = {f: float("nan") for f in fields}
            continue
        w = weight[mask] if weight is not None else None
        out[zone_name] = {f: relative_l2(pred[f][mask], true[f][mask], weight=w) for f in fields}
    return out
