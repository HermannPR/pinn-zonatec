"""Input feature construction (P25=A): Fourier features (Tancik et al. 2020)
over non-dimensional (x,y,z), plus (sin theta, cos theta), a learned variant
embedding, SDF and local building height.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn


class FourierFeatures(nn.Module):
    """gamma(v) = [sin(2 pi B v), cos(2 pi B v)], B ~ N(0, sigma^2) fixed
    (not trained), per Tancik et al. 2020 ("Fourier Features Let Networks
    Learn High Frequency Functions in Low Dimensional Domains")."""

    def __init__(self, in_dim: int, num_bands: int, sigma: float, seed: int = 0):
        super().__init__()
        g = torch.Generator().manual_seed(seed)
        B = torch.randn(in_dim, num_bands, generator=g) * sigma
        self.register_buffer("B", B)
        self.out_dim = 2 * num_bands

    def forward(self, v: torch.Tensor) -> torch.Tensor:
        proj = 2.0 * math.pi * (v @ self.B)
        return torch.cat([torch.sin(proj), torch.cos(proj)], dim=-1)


def scale_sdf(sdf: torch.Tensor, h_ref: float) -> torch.Tensor:
    """Bounded, smooth SDF feature: tanh(sdf / h_ref)."""
    return torch.tanh(sdf / h_ref)


def scale_height(h: torch.Tensor, h_ref: float) -> torch.Tensor:
    return h / h_ref


# ---------------------------------------------------------------------------
# Differentiable geometry sources: given physical (x, y, z) torch tensors
# (which may require_grad, e.g. collocation points), return (sdf, height)
# torch tensors of the same shape that are themselves differentiable w.r.t.
# x, y, z. See ml/data.py's EpochSampler docstring for *why* this needs to
# be differentiable (chain-rule bug found in review). Two implementations
# share this one interface so callers (ml/data.py) never need to change when
# real geometry becomes available:
#
#   AnalyticBoxGeometry  -- exact closed form, synthetic smoke-test boxes.
#   GridGeometry         -- precomputed SDF volume + height raster, sampled
#                           with torch.nn.functional.grid_sample (trilinear
#                           / bilinear, align_corners=True). This is what
#                           real building geometry (arbitrary polygons, no
#                           closed-form SDF) needs: a differentiable *source*
#                           built once (offline, by the geometry pipeline,
#                           E:\PINN\v2\geometry\out\*.npz -- reading that
#                           directory is fine, writing to it is outside this
#                           package's scope) and then *queried* differentiably
#                           here via interpolation.
# ---------------------------------------------------------------------------

class GeometrySource:
    """sdf_and_height(x, y, z) -> (sdf, height), same shape as x, both
    differentiable w.r.t. x, y, z (1-D tensors, physical units: metres)."""

    def sdf_and_height(self, x: torch.Tensor, y: torch.Tensor, z: torch.Tensor):
        raise NotImplementedError


class AnalyticBoxGeometry(GeometrySource):
    """Exact closed-form SDF/height for the synthetic smoke-test geometry
    (a union of axis-aligned boxes) -- see ml/synthetic.py."""

    def __init__(self, buildings, smooth_width: float = 2.0):
        self.buildings = buildings
        self.smooth_width = smooth_width

    def sdf_and_height(self, x: torch.Tensor, y: torch.Tensor, z: torch.Tensor):
        from . import synthetic  # lazy: keeps synthetic.py's torch use optional
        sdf = synthetic.torch_scene_sdf(x, y, z, self.buildings)
        h = synthetic.torch_local_height_smooth(x, y, self.buildings, self.smooth_width)
        return sdf, h


class GridGeometry(GeometrySource):
    """Precomputed, differentiable SDF (3D volume) + smoothed local-height
    (2D raster), queried with grid_sample.

    Expected .npz layout (one file per variant):
        sdf              float32 [nz, ny, nx]   (a regular grid; axis order
                                                  z, y, x to match a natural
                                                  numpy meshgrid('ij') dump)
        origin           float32 [3]            (x0, y0, z0), metres, ZT-ENU
        spacing          float32 [3]            (dx, dy, dz), metres
        height           float32 [ny, nx]       (pre-smoothed local height)
        height_origin    float32 [2]            (x0, y0), metres
        height_spacing   float32 [2]            (dx, dy), metres

    grid_sample interpolates linearly (bilinear/trilinear) between grid
    nodes and is differentiable w.r.t. the *query coordinates*, which is
    exactly what's needed here: coordinates flow in from the leaf `xyz`
    tensor, through the normalisation below, into `grid_sample`, and its
    backward correctly propagates d(sdf)/d(x,y,z).
    """

    def __init__(self, npz_path):
        import numpy as np
        data = np.load(npz_path)
        self.sdf_vol = torch.as_tensor(data["sdf"], dtype=torch.float32)            # [nz,ny,nx]
        self.origin = torch.as_tensor(data["origin"], dtype=torch.float32)          # [3] xyz
        self.spacing = torch.as_tensor(data["spacing"], dtype=torch.float32)        # [3] xyz
        self.height_raster = torch.as_tensor(data["height"], dtype=torch.float32)   # [ny,nx]
        self.h_origin = torch.as_tensor(data["height_origin"], dtype=torch.float32)  # [2] xy
        self.h_spacing = torch.as_tensor(data["height_spacing"], dtype=torch.float32)  # [2] xy

    @staticmethod
    def _to_ndc(coord: torch.Tensor, origin: torch.Tensor, spacing: torch.Tensor, size: int) -> torch.Tensor:
        """Physical coordinate -> grid_sample's [-1, 1] normalised device
        coordinate (align_corners=True convention: -1 and 1 sit exactly on
        the first/last grid node)."""
        idx = (coord - origin) / spacing
        return 2.0 * idx / max(size - 1, 1) - 1.0

    def sdf_and_height(self, x: torch.Tensor, y: torch.Tensor, z: torch.Tensor):
        import torch.nn.functional as F
        device = x.device
        vol = self.sdf_vol.to(device)[None, None]  # [1,1,nz,ny,nx]
        nz, ny, nx = vol.shape[-3:]
        origin, spacing = self.origin.to(device), self.spacing.to(device)
        gx = self._to_ndc(x, origin[0], spacing[0], nx)
        gy = self._to_ndc(y, origin[1], spacing[1], ny)
        gz = self._to_ndc(z, origin[2], spacing[2], nz)
        # grid_sample (5D) expects grid[..., :] = (x, y, z) matching (W, H, D)
        grid = torch.stack([gx, gy, gz], dim=-1).view(1, 1, 1, -1, 3)
        sdf = F.grid_sample(vol, grid, mode="bilinear", align_corners=True, padding_mode="border")
        sdf = sdf.reshape(-1)

        hraster = self.height_raster.to(device)[None, None]  # [1,1,ny,nx]
        hny, hnx = hraster.shape[-2:]
        h_origin, h_spacing = self.h_origin.to(device), self.h_spacing.to(device)
        hgx = self._to_ndc(x, h_origin[0], h_spacing[0], hnx)
        hgy = self._to_ndc(y, h_origin[1], h_spacing[1], hny)
        hgrid = torch.stack([hgx, hgy], dim=-1).view(1, 1, -1, 2)
        h = F.grid_sample(hraster, hgrid, mode="bilinear", align_corners=True, padding_mode="border")
        h = h.reshape(-1)
        return sdf, h

    @staticmethod
    def build_from_analytic(buildings, out_path, bounds, spacing_m: float = 1.0,
                             smooth_width: float = 2.0):
        """Helper (test/dev use): sample an AnalyticBoxGeometry onto a
        regular grid and save it in the .npz layout above -- used to build a
        GridGeometry test fixture from the synthetic boxes, and to sanity
        check that the two implementations of GeometrySource agree with
        each other to within grid resolution."""
        import numpy as np
        (x0, x1), (y0, y1), (z0, z1) = bounds
        xs = np.arange(x0, x1 + 1e-6, spacing_m)
        ys = np.arange(y0, y1 + 1e-6, spacing_m)
        zs = np.arange(z0, z1 + 1e-6, spacing_m)
        Xg, Yg, Zg = np.meshgrid(xs, ys, zs, indexing="ij")  # [nx,ny,nz]
        geo = AnalyticBoxGeometry(buildings, smooth_width=smooth_width)
        xt = torch.as_tensor(Xg.ravel(), dtype=torch.float32)
        yt = torch.as_tensor(Yg.ravel(), dtype=torch.float32)
        zt = torch.as_tensor(Zg.ravel(), dtype=torch.float32)
        with torch.no_grad():
            sdf, _ = geo.sdf_and_height(xt, yt, zt)
        sdf_vol = sdf.numpy().reshape(Xg.shape).transpose(2, 1, 0)  # -> [nz,ny,nx]

        Xh, Yh = np.meshgrid(xs, ys, indexing="ij")
        with torch.no_grad():
            _, h = geo.sdf_and_height(torch.as_tensor(Xh.ravel(), dtype=torch.float32),
                                       torch.as_tensor(Yh.ravel(), dtype=torch.float32),
                                       torch.zeros(Xh.size, dtype=torch.float32))
        h_raster = h.numpy().reshape(Xh.shape).T  # -> [ny,nx]

        np.savez(out_path,
                 sdf=sdf_vol.astype(np.float32),
                 origin=np.array([xs[0], ys[0], zs[0]], dtype=np.float32),
                 spacing=np.array([spacing_m, spacing_m, spacing_m], dtype=np.float32),
                 height=h_raster.astype(np.float32),
                 height_origin=np.array([xs[0], ys[0]], dtype=np.float32),
                 height_spacing=np.array([spacing_m, spacing_m], dtype=np.float32))


def resolve_geometry_source(variant: str, geometry_dir: Optional[str] = None) -> Optional[GeometrySource]:
    """Pick a GeometrySource for `variant`: an exact AnalyticBoxGeometry if
    ml.synthetic recognises the variant (every synthetic smoke-test case),
    else a GridGeometry loaded from `<geometry_dir>/<variant>_sdf.npz` if
    that file exists (the real-geometry integration point -- see
    GridGeometry's docstring), else None (caller falls back to precomputed,
    non-differentiable sdf/height constants)."""
    from . import synthetic
    buildings = synthetic.VARIANTS.get(variant)
    if buildings is not None:
        return AnalyticBoxGeometry(buildings)
    geometry_dir = geometry_dir or str(Path(r"E:\PINN\v2\geometry\out"))
    npz_path = Path(geometry_dir) / f"{variant}_sdf.npz"
    if npz_path.exists():
        return GridGeometry(str(npz_path))
    return None
