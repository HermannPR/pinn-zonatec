"""Data loading, non-dimensionalisation and per-step sampling.

Scale note (per the task brief): real datasets are ~40 cases x 0.5-2M points
(float32) each, too big to sit on an 8 GB shared GPU. The sampler here is
built around **per-case random-index sampling of a bounded number of points
per step**, never materialising a full case on the GPU and never
concatenating all cases into one big in-RAM array. For the synthetic smoke
test (a few 10s of thousands of points per case) each case's arrays are
small enough to keep resident in host RAM (loaded once, lazily, and cached)
so sampling is just fast numpy fancy-indexing; the same `CaseData` /
`EpochSampler` interface is what you would back with `h5py` file handles
opened in SWMR/read mode (no full read) or with pre-sampled `.npy` shards
for the real ~40-case dataset -- only `CaseData._load` would change.

Differentiable geometry features (fix, found in review)
----------------------------------------------------------
`sdf` and `local_height` are network *inputs* but are themselves functions
of (x, y, z). For collocation batches (`requires_grad=True`, used by the
continuity/momentum residuals in physics.py), `EpochSampler` recomputes
them from the same leaf (x, y, z) tensor via the exact analytic torch SDF
in `ml.synthetic` (see its docstring) instead of feeding in precomputed
HDF5 constants -- otherwise `torch.autograd.grad` silently drops the
d(output)/d(sdf) * d(sdf)/d(x,y,z) chain-rule term, which is largest right
next to walls. This only works for variants `ml.synthetic` recognises
(every synthetic smoke-test case); for a real case (unknown geometry) it
falls back to the precomputed, non-differentiable sdf/height, and stage
B/C residuals near walls for that case are then only approximate until a
differentiable SDF/height source (e.g. a precomputed grid + grid_sample,
from the geometry pipeline -- out of this package's scope) is wired in
here. Plain data-loss and wall-BC batches never differentiate w.r.t.
(x,y,z), so they are unaffected and keep using the precomputed constants
for speed.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Dict, List, Optional

import h5py
import numpy as np
import pandas as pd
import torch

from .config import KAPPA, CMU

FIELD_NAMES = ["x", "y", "z", "u", "v", "w", "p", "k", "nut", "sdf", "wall_dist", "local_height"]

# Reference speed used to build the DeepONet branch input U10/Uref (P25=A
# spec). Shared as a constant so training (EpochSampler) and evaluation
# (train.py._predict_case_physical) never drift apart.
U10_REF = 8.0


def read_manifest(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df


class VariantVocab:
    def __init__(self, variants: List[str]):
        self.variants = sorted(set(variants))
        self.to_id = {v: i for i, v in enumerate(self.variants)}

    def __len__(self):
        return len(self.variants)

    def id_of(self, name: str) -> int:
        return self.to_id[name]


@dataclasses.dataclass
class CaseData:
    case_id: str
    variant: str
    variant_id: int
    theta_deg: float
    u10: float
    u_star: float
    z0: float
    d: float
    h_ref: float
    u_h: float
    split: str
    arrays: Dict[str, np.ndarray]
    wall: Dict[str, np.ndarray]

    @property
    def n_points(self) -> int:
        return self.arrays["x"].shape[0]

    @property
    def n_wall(self) -> int:
        return self.wall["x"].shape[0] if self.wall else 0

    def sincos(self):
        th = np.deg2rad(self.theta_deg)
        return np.float32(np.sin(th)), np.float32(np.cos(th))


def _load_case(path: str, variant_id: int) -> CaseData:
    with h5py.File(path, "r") as f:
        arrays = {name: f[name][...].astype(np.float32) for name in FIELD_NAMES}
        wall = {}
        if "wall_faces" in f:
            g = f["wall_faces"]
            wall = {k: g[k][...].astype(np.float32) for k in ["x", "y", "z", "nx", "ny", "nz"]}
        attrs = dict(f.attrs)
    return CaseData(
        case_id=Path(path).stem,
        variant=str(attrs["variant"]),
        variant_id=variant_id,
        theta_deg=float(attrs["theta_deg"]),
        u10=float(attrs["U10"]),
        u_star=float(attrs["u_star"]),
        z0=float(attrs["z0"]),
        d=float(attrs["d"]),
        h_ref=float(attrs["h_ref"]),
        u_h=float(attrs["u_h"]),
        split=str(attrs.get("split", "unknown")),
        arrays=arrays,
        wall=wall,
    )


class CaseStore:
    """Loads and caches all cases referenced by a manifest, non-dimensionalises
    them, and exposes them keyed by case_id / split."""

    def __init__(self, manifest_path: str):
        self.manifest_path = manifest_path
        self.df = read_manifest(manifest_path)
        self.vocab = VariantVocab(self.df["variant"].tolist())
        self.cases: Dict[str, CaseData] = {}
        for _, row in self.df.iterrows():
            vid = self.vocab.id_of(row["variant"])
            self.cases[row["case_id"]] = _load_case(row["path"], vid)

    def ids_for_split(self, split: str) -> List[str]:
        return [cid for cid, c in self.cases.items() if c.split == split]

    def nearest_train_cases(self, target: CaseData, k: int = 1, same_variant: bool = True,
                             match_axis: str = "theta") -> List[CaseData]:
        """Nearest simulated cases along one axis, holding the other fixed:
        match_axis='theta' -> same U10, sorted by angular distance in theta
        (used for the held-out-direction baselines); match_axis='u10' ->
        same theta, sorted by |U10 - target.U10| (held-out-speed baseline).
        Falls back to an empty list if nothing matches (caller decides the
        further fallback, e.g. relaxing same_variant)."""
        def base_filter(c):
            return c.case_id != target.case_id and c.split in ("train", "val") and \
                (c.variant == target.variant if same_variant else True)

        if match_axis == "theta":
            candidates = [c for c in self.cases.values() if base_filter(c) and abs(c.u10 - target.u10) < 1e-6]
            def dist(c):
                return abs((c.theta_deg - target.theta_deg + 180.0) % 360.0 - 180.0)
        elif match_axis == "u10":
            candidates = [c for c in self.cases.values() if base_filter(c)
                          and abs((c.theta_deg - target.theta_deg + 180.0) % 360.0 - 180.0) < 1e-6]
            def dist(c):
                return abs(c.u10 - target.u10)
        else:
            raise ValueError(match_axis)
        candidates.sort(key=dist)
        return candidates[:k]


def nondim_fields(case: CaseData) -> Dict[str, np.ndarray]:
    """Return a dict of non-dimensional fields per the contract:
    lengths/H_ref, velocities/U_H, p,k/U_H^2, nut/(U_H*H_ref)."""
    Href, Uh = case.h_ref, case.u_h
    a = case.arrays
    return dict(
        x=a["x"] / Href, y=a["y"] / Href, z=a["z"] / Href,
        u=a["u"] / Uh, v=a["v"] / Uh, w=a["w"] / Uh,
        p=a["p"] / (Uh ** 2), k=a["k"] / (Uh ** 2), nut=a["nut"] / (Uh * Href),
        sdf=a["sdf"] / Href, wall_dist=a["wall_dist"] / Href, local_height=a["local_height"] / Href,
        # kept in metres too (models scale sdf/height internally by h_ref already)
        sdf_m=a["sdf"], local_height_m=a["local_height"],
    )


@dataclasses.dataclass
class Batch:
    xyz: torch.Tensor          # [N,3] non-dim
    sincos: torch.Tensor       # [N,2]
    variant_id: torch.Tensor   # [N] long
    sdf_m: torch.Tensor        # [N,1] metres (raw)
    height_m: torch.Tensor     # [N,1] metres (raw)
    target: Dict[str, torch.Tensor]  # non-dim u,v,w,p,k,nut
    u10_over_uref: torch.Tensor      # [N,1]


class EpochSampler:
    """Randomly samples supervised points, collocation points (fluid,
    sdf>0 -- true of every stored point already) and wall-face points per
    case, per step. Sampling is without replacement within a case when the
    request is <= n available, else with replacement (small synthetic
    cases)."""

    def __init__(self, store: CaseStore, device: torch.device, seed: int = 0,
                 u10_ref: float = U10_REF):
        self.store = store
        self.device = device
        self.rng = np.random.default_rng(seed)
        self.u10_ref = u10_ref

    def _sample_idx(self, n_available: int, n_want: int) -> np.ndarray:
        replace = n_want > n_available
        return self.rng.choice(n_available, size=n_want, replace=replace)

    def sample_supervised(self, case_ids: List[str], n_per_case: int, requires_grad: bool = False) -> Batch:
        xs, ys, zs, sins, coss, vids, sdfs, hts, u10s = ([] for _ in range(9))
        targets = {k: [] for k in ["u", "v", "w", "p", "k", "nut"]}
        for cid in case_ids:
            case = self.store.cases[cid]
            nd = nondim_fields(case)
            idx = self._sample_idx(case.n_points, n_per_case)
            s, c = case.sincos()
            xs.append(nd["x"][idx]); ys.append(nd["y"][idx]); zs.append(nd["z"][idx])
            sins.append(np.full(n_per_case, s, np.float32)); coss.append(np.full(n_per_case, c, np.float32))
            vids.append(np.full(n_per_case, case.variant_id, np.int64))
            sdfs.append(nd["sdf_m"][idx]); hts.append(nd["local_height_m"][idx])
            u10s.append(np.full(n_per_case, case.u10 / self.u10_ref, np.float32))
            for k in targets:
                targets[k].append(nd[k][idx])
        xyz = torch.tensor(np.stack([np.concatenate(xs), np.concatenate(ys), np.concatenate(zs)], axis=1),
                            dtype=torch.float32, device=self.device)
        sincos = torch.tensor(np.stack([np.concatenate(sins), np.concatenate(coss)], axis=1),
                               dtype=torch.float32, device=self.device)
        variant_id = torch.tensor(np.concatenate(vids), dtype=torch.long, device=self.device)
        sdf_m = torch.tensor(np.concatenate(sdfs), dtype=torch.float32, device=self.device).view(-1, 1)
        height_m = torch.tensor(np.concatenate(hts), dtype=torch.float32, device=self.device).view(-1, 1)
        u10_over_uref = torch.tensor(np.concatenate(u10s), dtype=torch.float32, device=self.device).view(-1, 1)
        target = {k: torch.tensor(np.concatenate(v), dtype=torch.float32, device=self.device)
                  for k, v in targets.items()}
        if requires_grad:
            xyz.requires_grad_(True)
            sdf_m, height_m = self.differentiable_geometry(case_ids, n_per_case, xyz, sdf_m, height_m)
        return Batch(xyz, sincos, variant_id, sdf_m, height_m, target, u10_over_uref)

    def differentiable_geometry(self, case_ids: List[str], n_per_case: int, xyz: torch.Tensor,
                                  fallback_sdf: torch.Tensor, fallback_height: torch.Tensor):
        """Recompute sdf/height from the leaf `xyz` tensor (see module
        docstring) via `features.resolve_geometry_source`, which picks the
        exact analytic geometry for synthetic variants or a precomputed
        GridGeometry (grid_sample) once a real one exists under
        E:\\PINN\\v2\\geometry\\out\\*.npz; falls back to the precomputed,
        non-differentiable constants per-case if neither is available.
        Callers never need to change when real geometry lands -- only
        `resolve_geometry_source` does."""
        from . import features  # lazy: keeps features.py's torch use optional at import time
        sdf_parts, h_parts = [], []
        # geometry sources are cheap to construct but re-fetch per case (a
        # case's variant rarely repeats within one batch at smoke-test scale)
        for i, cid in enumerate(case_ids):
            case = self.store.cases[cid]
            sl = slice(i * n_per_case, (i + 1) * n_per_case)
            source = features.resolve_geometry_source(case.variant)
            if source is not None:
                xp = xyz[sl, 0] * case.h_ref
                yp = xyz[sl, 1] * case.h_ref
                zp = xyz[sl, 2] * case.h_ref
                sdf_c, h_c = source.sdf_and_height(xp, yp, zp)
                sdf_parts.append(sdf_c.view(-1, 1))
                h_parts.append(h_c.view(-1, 1))
            else:
                sdf_parts.append(fallback_sdf[sl])
                h_parts.append(fallback_height[sl])
        return torch.cat(sdf_parts, dim=0), torch.cat(h_parts, dim=0)

    def sample_wall(self, case_ids: List[str], n_per_case: int) -> Optional[Batch]:
        xs, ys, zs, nxs, nys, nzs, sins, coss, vids, sdfm, htm, u10s = ([] for _ in range(12))
        any_wall = False
        for cid in case_ids:
            case = self.store.cases[cid]
            if case.n_wall == 0:
                continue
            any_wall = True
            idx = self._sample_idx(case.n_wall, n_per_case)
            s, c = case.sincos()
            Href = case.h_ref
            xs.append(case.wall["x"][idx] / Href); ys.append(case.wall["y"][idx] / Href)
            zs.append(case.wall["z"][idx] / Href)
            nxs.append(case.wall["nx"][idx]); nys.append(case.wall["ny"][idx]); nzs.append(case.wall["nz"][idx])
            sins.append(np.full(n_per_case, s, np.float32)); coss.append(np.full(n_per_case, c, np.float32))
            vids.append(np.full(n_per_case, case.variant_id, np.int64))
            sdfm.append(np.zeros(n_per_case, np.float32))  # on-wall: sdf ~ 0 by construction
            htm.append(np.zeros(n_per_case, np.float32))
            u10s.append(np.full(n_per_case, case.u10 / self.u10_ref, np.float32))
        if not any_wall:
            return None
        xyz = torch.tensor(np.stack([np.concatenate(xs), np.concatenate(ys), np.concatenate(zs)], axis=1),
                            dtype=torch.float32, device=self.device)
        sincos = torch.tensor(np.stack([np.concatenate(sins), np.concatenate(coss)], axis=1),
                               dtype=torch.float32, device=self.device)
        variant_id = torch.tensor(np.concatenate(vids), dtype=torch.long, device=self.device)
        sdf_m = torch.tensor(np.concatenate(sdfm), dtype=torch.float32, device=self.device).view(-1, 1)
        height_m = torch.tensor(np.concatenate(htm), dtype=torch.float32, device=self.device).view(-1, 1)
        u10_over_uref = torch.tensor(np.concatenate(u10s), dtype=torch.float32, device=self.device).view(-1, 1)
        normal = dict(nx=torch.tensor(np.concatenate(nxs), dtype=torch.float32, device=self.device),
                      ny=torch.tensor(np.concatenate(nys), dtype=torch.float32, device=self.device),
                      nz=torch.tensor(np.concatenate(nzs), dtype=torch.float32, device=self.device))
        b = Batch(xyz, sincos, variant_id, sdf_m, height_m, {}, u10_over_uref)
        b.target = normal  # reuse target slot to carry normals for wall batches
        return b
