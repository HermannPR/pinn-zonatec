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

FIELD_NAMES = ["x", "y", "z", "u", "v", "w", "p", "k", "nut", "sdf", "wall_dist", "local_height",
               "vol", "is_wall_adjacent"]

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

    @property
    def fluid_idx(self) -> np.ndarray:
        """Indices NOT in the first wall-adjacent cell layer (M6, design
        review): the momentum/continuity residual is only meaningful where
        the discretised PDE actually applies -- with wall functions, the
        first cell's stress is set by the wall law, not by resolving the
        continuum equation, so collocation points must exclude
        `is_wall_adjacent==1` cells."""
        if not hasattr(self, "_fluid_idx_cache"):
            mask = self.arrays["is_wall_adjacent"] < 0.5
            self._fluid_idx_cache = np.nonzero(mask)[0]
        return self._fluid_idx_cache

    def sincos(self):
        th = np.deg2rad(self.theta_deg)
        return np.float32(np.sin(th)), np.float32(np.cos(th))


def _load_case(path: str, variant_id: int, split: str) -> CaseData:
    """`split` must come from the sealed manifest (see CaseStore), not from
    the HDF5 file's own `split` attribute (M9, design review) -- the two
    could silently disagree if a case file is regenerated without updating
    the manifest."""
    with h5py.File(path, "r") as f:
        arrays = {name: f[name][...].astype(np.float32) for name in FIELD_NAMES}
        wall = {}
        if "wall_faces" in f:
            g = f["wall_faces"]
            keys = ["x", "y", "z", "nx", "ny", "nz"]
            if "height" in g:
                keys.append("height")
            wall = {k: g[k][...].astype(np.float32) for k in keys}
            if "height" not in wall:
                wall["height"] = np.zeros_like(wall["x"])  # legacy files without M7's fix
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
        split=split,
        arrays=arrays,
        wall=wall,
    )


class ManifestSealError(RuntimeError):
    pass


def verify_manifest_seal(manifest_path: str, strict: bool = False) -> Optional[str]:
    """Check manifest.csv against its manifest.csv.sha256 sidecar (M9,
    design review: the split must be sealed so it can't silently drift).
    Returns the verified digest, or None if no sidecar exists (older/hand-made
    manifests) -- `strict=True` raises instead of tolerating a missing seal."""
    import hashlib
    sha_path = Path(str(manifest_path) + ".sha256")
    if not sha_path.exists():
        msg = f"no {sha_path} sidecar; split is unverified (run ml.synthetic.seal_manifest)"
        if strict:
            raise ManifestSealError(msg)
        print(f"[data] WARNING: {msg}")
        return None
    expected = sha_path.read_text(encoding="utf-8").strip().split()[0]
    actual = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
    if actual != expected:
        raise ManifestSealError(
            f"{manifest_path} does not match {sha_path} (expected {expected[:12]}..., got {actual[:12]}...); "
            "the manifest was edited/regenerated without re-sealing (ml.synthetic.seal_manifest)")
    return actual


class CaseStore:
    """Loads and caches all cases referenced by a manifest, non-dimensionalises
    them, and exposes them keyed by case_id / split. The split assignment is
    read ONLY from the (SHA-256-sealed) manifest -- never from each HDF5
    file's own `split` attribute (M9, design review)."""

    def __init__(self, manifest_path: str, require_seal: bool = False):
        self.manifest_path = manifest_path
        verify_manifest_seal(manifest_path, strict=require_seal)
        self.df = read_manifest(manifest_path)
        self.vocab = VariantVocab(self.df["variant"].tolist())
        self.cases: Dict[str, CaseData] = {}
        for _, row in self.df.iterrows():
            vid = self.vocab.id_of(row["variant"])
            self.cases[row["case_id"]] = _load_case(row["path"], vid, str(row["split"]))

    def ids_for_split(self, split: str) -> List[str]:
        return [cid for cid, c in self.cases.items() if c.split == split]

    def field_stats(self, split: str = "train",
                     fields: List[str] = ("u", "v", "w", "p", "k", "nut")) -> Dict[str, float]:
        """Per-field standard deviation of the NON-DIMENSIONAL fields over a
        split (M5, design review): used to standardise the data loss so
        low-variance fields (k, w, p in the smoke data) aren't drowned out
        by high-variance ones (v) in a plain unweighted MSE sum."""
        acc = {f: [] for f in fields}
        for cid in self.ids_for_split(split):
            nd = nondim_fields(self.cases[cid])
            for f in fields:
                acc[f].append(nd[f])
        return {f: float(np.std(np.concatenate(v))) if v else 1.0 for f, v in acc.items()}

    def nearest_train_cases(self, target: CaseData, k: int = 1, same_variant: bool = True,
                             match_axis: str = "theta") -> List[CaseData]:
        """Nearest simulated cases along one axis, holding the other fixed:
        match_axis='theta' -> same U10, sorted by angular distance in theta
        (used for the held-out-direction baselines); match_axis='u10' ->
        same theta, sorted by |U10 - target.U10| (held-out-speed baseline).
        Falls back to an empty list if nothing matches (caller decides the
        further fallback, e.g. relaxing same_variant).

        M9 (design review): restricted to split=='train' only. The network
        never sees validation cases either, so a fair baseline can't either
        -- letting baselines also draw on 'val' (as an earlier version did)
        gave them strictly more information than the model they're compared
        against.
        """
        def base_filter(c):
            return c.case_id != target.case_id and c.split == "train" and \
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
    variant_id: torch.Tensor   # [N] long (unused by the models, M4; kept for bookkeeping/baselines)
    sdf_m: torch.Tensor        # [N,1] metres (raw)
    height_m: torch.Tensor     # [N,1] metres (raw)
    target: Dict[str, torch.Tensor]  # non-dim u,v,w,p,k,nut
    u10_over_uref: torch.Tensor      # [N,1] (unused by the models, M11; kept for bookkeeping)
    vol_weight: Optional[torch.Tensor] = None  # [N] cell volume / mean(vol) within the batch (M6)


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

    def sample_supervised(self, case_ids: List[str], n_per_case: int, requires_grad: bool = False,
                           fluid_only: bool = False) -> Batch:
        """`fluid_only=True` (M6, design review) restricts sampling to
        `case.fluid_idx` (excludes `is_wall_adjacent==1` cells) -- use this
        for collocation batches feeding the continuity/momentum residual,
        since the first wall-adjacent cell's stress comes from the wall
        function, not from resolving the continuum PDE there. Also returns
        `vol_weight` (cell volume normalised to a per-batch mean of 1) so the
        residual loss can be volume-weighted (M6) instead of a plain
        per-point mean that over-counts refined-mesh regions.
        """
        xs, ys, zs, sins, coss, vids, sdfs, hts, u10s, vols = ([] for _ in range(10))
        targets = {k: [] for k in ["u", "v", "w", "p", "k", "nut"]}
        for cid in case_ids:
            case = self.store.cases[cid]
            nd = nondim_fields(case)
            pool = case.fluid_idx if fluid_only else np.arange(case.n_points)
            idx = pool[self._sample_idx(len(pool), n_per_case)]
            s, c = case.sincos()
            xs.append(nd["x"][idx]); ys.append(nd["y"][idx]); zs.append(nd["z"][idx])
            sins.append(np.full(n_per_case, s, np.float32)); coss.append(np.full(n_per_case, c, np.float32))
            vids.append(np.full(n_per_case, case.variant_id, np.int64))
            sdfs.append(nd["sdf_m"][idx]); hts.append(nd["local_height_m"][idx])
            u10s.append(np.full(n_per_case, case.u10 / self.u10_ref, np.float32))
            vols.append(case.arrays["vol"][idx])
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
        vol_np = np.concatenate(vols)
        vol_weight = torch.tensor(vol_np / max(vol_np.mean(), 1e-30), dtype=torch.float32, device=self.device)
        if requires_grad:
            xyz.requires_grad_(True)
            sdf_m, height_m = self.differentiable_geometry(case_ids, n_per_case, xyz, sdf_m, height_m)
        return Batch(xyz, sincos, variant_id, sdf_m, height_m, target, u10_over_uref, vol_weight)

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
            # M7 (design review): use the TRUE building height at this face
            # (0 for ground), not a hard-coded 0 everywhere -- a fluid point
            # right next to a facade sees local_height == that building's H,
            # so the wall point representing the same wall must too, or the
            # network learns an inconsistent feature at the boundary.
            htm.append(case.wall["height"][idx])
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
