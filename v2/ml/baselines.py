"""Reference models (P27): (1) interpolation baseline -- spatial linear
interpolation within a field, and angular linear interpolation between the
two nearest simulated directions for a held-out direction; (2) the same
network without physics (stage A, obtained simply by pointing at a stage-A
checkpoint/run, see train.py); (3) nearest simulated direction.

All predictions are returned as physical (dimensional) fields so they can be
compared directly against a case's own physical arrays with metrics.py.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree, Delaunay

from .data import CaseData, CaseStore, nondim_fields

FIELDS = ["u", "v", "w", "p", "k", "nut"]
_VEL_FIELDS = ("u", "v", "w")
# Power of U_H (and, for nut, of H_ref too) each field scales by -- matches
# the contract's non-dimensionalisation exactly (config.py / data.py
# nondim_fields): velocities / U_H, p and k / U_H^2, nut / (U_H*H_ref).
# (An earlier version of this table wrongly gave u,v,w power 0 -- i.e.
# treated velocity as already scale-invariant in U10 -- which silently
# broke the speed-rescaled baseline for exactly the fields it was written
# to fix.)
_U_H_POW = {"u": 1, "v": 1, "w": 1, "p": 2, "k": 2, "nut": 1}
_HREF_POW = {"u": 0, "v": 0, "w": 0, "p": 0, "k": 0, "nut": 1}


def _physical(case: CaseData) -> Dict[str, np.ndarray]:
    return {f: case.arrays[f] for f in FIELDS}


def spatial_interpolation_within_case(case: CaseData, holdout_frac: float = 0.2,
                                       seed: int = 0) -> Dict[str, np.ndarray]:
    """Leave-out a random subset of a case's own points, fit a linear
    (Delaunay) interpolant on the rest, and predict the held-out subset.
    Returns predictions aligned with the held-out subset only, plus the
    boolean mask used, under key '_mask'."""
    rng = np.random.default_rng(seed)
    n = case.n_points
    mask = rng.random(n) < holdout_frac
    train_xyz = np.stack([case.arrays["x"][~mask], case.arrays["y"][~mask], case.arrays["z"][~mask]], axis=1)
    query_xyz = np.stack([case.arrays["x"][mask], case.arrays["y"][mask], case.arrays["z"][mask]], axis=1)
    tri = Delaunay(train_xyz)  # triangulate once, reuse for every field
    tree = None
    out = {"_mask": mask}
    for f in FIELDS:
        interp = LinearNDInterpolator(tri, case.arrays[f][~mask], fill_value=np.nan)
        pred = interp(query_xyz)
        nan = np.isnan(pred)
        if nan.any():
            # fallback: nearest neighbour for points outside the convex hull
            if tree is None:
                tree = cKDTree(train_xyz)
            _, idx = tree.query(query_xyz[nan])
            pred[nan] = case.arrays[f][~mask][idx]
        out[f] = pred
    return out


def _match_indices(source: CaseData, target: CaseData) -> np.ndarray:
    src_xyz = np.stack([source.arrays["x"], source.arrays["y"], source.arrays["z"]], axis=1)
    tgt_xyz = np.stack([target.arrays["x"], target.arrays["y"], target.arrays["z"]], axis=1)
    tree = cKDTree(src_xyz)
    _, idx = tree.query(tgt_xyz)
    return idx


def _rescale_by_speed(src: CaseData, target: CaseData, src_fields: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """Convert `src_fields` (physical, from `src`) to non-dim via src's own
    U_H/H_ref and back to physical via `target`'s U_H/H_ref (M9, design
    review). Under the Reynolds-independence assumption the whole PINN
    pipeline relies on, this is the fair "nearest speed" reference: without
    it, comparing raw dimensional fields across different U10 just measures
    |U10_target - U10_source| (e.g. the smoke case gave rel_l2_u = 0.667 =
    |4-12|/12, an artifact of the unit mismatch, not of any real model
    failure or success)."""
    out = {}
    for f in FIELDS:
        nd = src_fields[f] / (src.u_h ** _U_H_POW[f] * src.h_ref ** _HREF_POW[f])
        out[f] = nd * (target.u_h ** _U_H_POW[f] * target.h_ref ** _HREF_POW[f])
    return out


def nearest_direction_prediction(store: CaseStore, target: CaseData, match_axis: str = "theta") -> Dict[str, np.ndarray]:
    """Reference model (3): predict with the single nearest simulated case
    along `match_axis` (same variant preferred, else any -- documented
    fallback for the held-out-geometry case, where no same-variant
    neighbour exists at all), spatially matched by nearest neighbour. For
    match_axis='u10' (held-out speed), fields are rescaled by the U_H ratio
    (M9) rather than compared as raw dimensional values."""
    neighbours = store.nearest_train_cases(target, k=1, same_variant=True, match_axis=match_axis)
    if not neighbours:
        neighbours = store.nearest_train_cases(target, k=1, same_variant=False, match_axis=match_axis)
    if not neighbours:
        raise RuntimeError(f"no candidate case found for baseline (target={target.case_id})")
    src = neighbours[0]
    idx = _match_indices(src, target)
    raw = {f: src.arrays[f][idx] for f in FIELDS}
    if match_axis == "u10" and abs(src.u10 - target.u10) > 1e-6:
        raw = _rescale_by_speed(src, target, raw)
    return raw


def angular_interpolation_prediction(store: CaseStore, target: CaseData) -> Dict[str, np.ndarray]:
    """Reference model (1b): angular linear interpolation between the
    nearest simulated direction on EACH side of the target (same variant &
    speed), spatially matched by nearest neighbour.

    M9 (design review): the earlier version just took the 2 nearest
    directions by absolute angle, with no guarantee they straddle the
    target -- if both landed on the same side, the interpolation weights
    (computed as if they bracketed it) extrapolate the wrong way. This
    version requires one neighbour with a strictly positive signed angular
    offset and one with a strictly negative one; if either side is empty it
    falls back to the single nearest direction instead of a meaningless
    two-sided blend.

    Horizontal components (u,v) are still blended as vectors (not
    magnitude+angle) for simplicity -- documented simplification of
    "angular linear interpolation" (a 45 degree gap can lose ~29% of the
    vector-averaged magnitude vs. interpolating speed and direction
    separately; flagged, not fixed here).
    """
    candidates = store.nearest_train_cases(target, k=10_000, same_variant=True, match_axis="theta")

    def signed_offset(c):
        # positive: c is ahead of target (clockwise); negative: behind.
        return ((c.theta_deg - target.theta_deg + 180.0) % 360.0) - 180.0

    ahead = [c for c in candidates if signed_offset(c) > 0]
    behind = [c for c in candidates if signed_offset(c) < 0]
    if not ahead or not behind:
        return nearest_direction_prediction(store, target, match_axis="theta")
    a = min(ahead, key=lambda c: signed_offset(c))
    b = min(behind, key=lambda c: -signed_offset(c))

    da, db = abs(signed_offset(a)), abs(signed_offset(b))
    total = da + db
    wa, wb = (db / total, da / total) if total > 0 else (0.5, 0.5)

    idx_a = _match_indices(a, target)
    idx_b = _match_indices(b, target)
    out = {}
    for f in FIELDS:
        out[f] = wa * a.arrays[f][idx_a] + wb * b.arrays[f][idx_b]
    return out


def stage_a_prediction_from_arrays(pred_dict: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """Trivial passthrough: the 'network without physics' reference model is
    just a PINNMLP trained with physics.stage == 'A'. This helper exists so
    train.py can hand its stage-A predictions to the same comparison-table
    code path as the other baselines."""
    return pred_dict
