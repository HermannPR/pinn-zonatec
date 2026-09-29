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

from .data import CaseData, CaseStore

FIELDS = ["u", "v", "w", "p", "k", "nut"]


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


def nearest_direction_prediction(store: CaseStore, target: CaseData, match_axis: str = "theta") -> Dict[str, np.ndarray]:
    """Reference model (3): predict with the single nearest simulated case
    along `match_axis` (same variant preferred, else any -- documented
    fallback for the held-out-geometry case, where no same-variant
    neighbour exists at all), spatially matched by nearest neighbour."""
    neighbours = store.nearest_train_cases(target, k=1, same_variant=True, match_axis=match_axis)
    if not neighbours:
        neighbours = store.nearest_train_cases(target, k=1, same_variant=False, match_axis=match_axis)
    if not neighbours:
        raise RuntimeError(f"no candidate case found for baseline (target={target.case_id})")
    src = neighbours[0]
    idx = _match_indices(src, target)
    return {f: src.arrays[f][idx] for f in FIELDS}


def angular_interpolation_prediction(store: CaseStore, target: CaseData) -> Dict[str, np.ndarray]:
    """Reference model (1b): angular linear interpolation between the two
    nearest simulated directions (same variant & speed), spatially matched
    by nearest neighbour, and horizontal components (u,v) blended as
    vectors (not magnitude+angle) for simplicity -- documented
    simplification of "angular linear interpolation"."""
    neighbours = store.nearest_train_cases(target, k=2, same_variant=True, match_axis="theta")
    if len(neighbours) < 2:
        # not enough neighbours at the same speed/variant: fall back to nearest
        return nearest_direction_prediction(store, target, match_axis="theta")
    a, b = neighbours[0], neighbours[1]

    def ang_dist(c):
        return abs((c.theta_deg - target.theta_deg + 180.0) % 360.0 - 180.0)

    da, db = ang_dist(a), ang_dist(b)
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
