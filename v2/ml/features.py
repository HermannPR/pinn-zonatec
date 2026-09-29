"""Input feature construction (P25=A): Fourier features (Tancik et al. 2020)
over non-dimensional (x,y,z), plus (sin theta, cos theta), SDF and local
building height (no variant embedding -- design review M4, see models.py).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Tuple

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


def scale_sdf(sdf: torch.Tensor, wall_scale: float = 10.0) -> torch.Tensor:
    """Bounded, smooth SDF feature: tanh(sdf / wall_scale).

    M13 (design review): using H_ref as the length scale here (e.g. 85 m for
    the real campus) compresses the first ~10 m of SDF -- exactly the
    near-wall region where gradients matter most for wind comfort -- into
    tanh(10/85)=0.12 of the output range. `wall_scale` is instead a small,
    fixed length (default 10 m, independent of H_ref) so the near-wall
    region keeps useful resolution regardless of how large the domain is.
    """
    return torch.tanh(sdf / wall_scale)


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


def _point_segment_distance(px: torch.Tensor, py: torch.Tensor,
                             x1: float, y1: float, x2: float, y2: float) -> torch.Tensor:
    ex, ey = x2 - x1, y2 - y1
    denom = ex * ex + ey * ey
    if denom <= 0:
        dx, dy = px - x1, py - y1
        return torch.sqrt(dx * dx + dy * dy + 1e-12)
    t = torch.clamp(((px - x1) * ex + (py - y1) * ey) / denom, 0.0, 1.0)
    projx, projy = x1 + t * ex, y1 + t * ey
    dx, dy = px - projx, py - projy
    return torch.sqrt(dx * dx + dy * dy + 1e-12)


def _polygon_horizontal_sdf(x: torch.Tensor, y: torch.Tensor,
                             vertices: List[Tuple[float, float]]) -> torch.Tensor:
    """Signed horizontal distance to a simple polygon boundary (negative
    inside, per the SDF convention), exact for any simple (non-self-
    intersecting) polygon: unsigned distance = min over edges of the
    point-to-segment distance (differentiable w.r.t. x,y); sign = standard
    ray-casting crossing-number inside test (not differentiable, but SDF
    conventionally uses discrete in/out branches -- see box_sdf/AnalyticBoxGeometry
    for the same pattern; the VALUE stays continuous across the boundary)."""
    n = len(vertices)
    d = None
    inside = torch.zeros_like(x, dtype=torch.bool)
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        di = _point_segment_distance(x, y, x1, y1, x2, y2)
        d = di if d is None else torch.minimum(d, di)
        with torch.no_grad():
            cond = (y1 > y) != (y2 > y)
            dy_edge = (y2 - y1) or 1e-30
            x_int = x1 + (y - y1) * (x2 - x1) / dy_edge
            inside = inside ^ (cond & (x < x_int))
    return torch.where(inside, -d, d)


class PolygonPrismGeometry(GeometrySource):
    """Analytic, smooth SDF/height for a set of arbitrary-footprint LOD1
    building prisms (design review M3(b)): each building's exact SDF is the
    polygon-extrusion formula used by `geometry/sdf.py`'s
    `_fast_extrusion_sdf_level` (same convention, evaluated per-point/
    analytically instead of on a raster), and multiple buildings are
    combined with a smooth minimum (log-sum-exp, smoothing length `k_smooth`,
    default 1 m) instead of a hard `min` -- unlike a piecewise-linear grid
    (`GridGeometry`), this keeps SECOND derivatives finite, non-zero and
    well-defined everywhere, which the momentum residual's viscous term
    (grad(nut * grad(u))) needs; a trilinear/bilinear-interpolated grid has
    a piecewise-CONSTANT gradient and zero (or singular, at cell faces)
    second derivatives, so composing the network through it silently drops
    curvature information from that path everywhere, not just near
    corners. Use this whenever building footprints (polygons + heights) are
    available; fall back to `GridGeometry` only if a differentiable
    analytic source truly isn't an option.

    `buildings`: list of (vertices, height) where vertices is a list of
    (x, y) tuples (closed polygon, >= 3 points, ZT-ENU metres).
    """

    def __init__(self, buildings: List[Tuple[List[Tuple[float, float]], float]],
                 k_smooth: float = 1.0, n_nearest: int = 20, height_smooth_width: float = 2.0):
        self.buildings = buildings
        self.k_smooth = k_smooth
        self.n_nearest = n_nearest
        self.height_smooth_width = height_smooth_width
        self._centers = [
            (sum(v[0] for v in verts) / len(verts), sum(v[1] for v in verts) / len(verts))
            for verts, _ in buildings
        ]

    def _nearest_buildings(self, x: torch.Tensor, y: torch.Tensor):
        if len(self.buildings) <= self.n_nearest:
            return list(range(len(self.buildings)))
        # cheap, non-differentiable pre-filter on the BATCH's centroid: fine
        # since collocation batches are spatially local; for a single global
        # call spanning the whole domain, all buildings are used instead.
        with torch.no_grad():
            cx, cy = float(x.mean()), float(y.mean())
        d2 = [(cx - bx) ** 2 + (cy - by) ** 2 for bx, by in self._centers]
        order = sorted(range(len(self.buildings)), key=lambda i: d2[i])
        return order[: self.n_nearest]

    def _single_prism_sdf(self, x, y, z, vertices, H):
        hd = _polygon_horizontal_sdf(x, y, vertices)  # signed horizontal (neg inside)
        d_unsigned = torch.abs(hd)
        inside = hd < 0

        b_out = torch.clamp(z - H, min=0.0)
        outside_val = torch.sqrt(d_unsigned ** 2 + b_out ** 2 + 1e-12)

        depth_z = torch.minimum(z, H - z)
        within = (z >= 0) & (z <= H)
        inside_within_val = -torch.minimum(d_unsigned, depth_z)
        inside_above_val = z - H

        inside_val = torch.where(within, inside_within_val, inside_above_val)
        return torch.where(inside, inside_val, outside_val)

    def sdf_and_height(self, x: torch.Tensor, y: torch.Tensor, z: torch.Tensor):
        idxs = self._nearest_buildings(x, y)
        sdfs = [self._single_prism_sdf(x, y, z, self.buildings[i][0], self.buildings[i][1]) for i in idxs]
        stacked = torch.stack(sdfs, dim=0)  # [B, N]
        # smooth min: -k * logsumexp(-sdf_i / k)
        sdf = -self.k_smooth * torch.logsumexp(-stacked / self.k_smooth, dim=0)

        # smooth height: logistic soft-box per building, summed (footprints
        # don't overlap), same construction as ml.synthetic.torch_local_height_smooth
        h = torch.zeros_like(x)
        for i in idxs:
            verts, H = self.buildings[i]
            n = len(verts)
            # smooth footprint indicator via signed horizontal distance
            hd = _polygon_horizontal_sdf(x, y, verts)
            indicator = torch.sigmoid(-hd / self.height_smooth_width)
            h = h + H * indicator
        return sdf, h


def _trilinear_nonuniform_z(vol: torch.Tensor, x0: float, y0: float, res_xy: float,
                             z_levels: torch.Tensor, x: torch.Tensor, y: torch.Tensor,
                             z: torch.Tensor) -> torch.Tensor:
    """Differentiable trilinear interpolation of a [nz,ny,nx] volume with
    UNIFORM x,y spacing but a possibly NON-uniform per-level `z_levels`
    array (as produced by geometry/sdf.py's `build_nested_sdf_grid` /
    `trilinear_sample`) -- `torch.nn.functional.grid_sample` assumes a
    uniform grid in every dimension, so it can't be used directly for this
    format; this mirrors `geometry.sdf.trilinear_sample`'s numpy logic with
    torch ops so gradients flow w.r.t. (x,y,z). Only the integer cell
    indices are non-differentiable (standard for any grid method -- see
    GridGeometry / PolygonPrismGeometry docstrings)."""
    nz, ny, nx = vol.shape
    fx = (x - x0) / res_xy
    fy = (y - y0) / res_xy
    with torch.no_grad():
        ix0 = torch.clamp(torch.floor(fx).long(), 0, nx - 2)
        iy0 = torch.clamp(torch.floor(fy).long(), 0, ny - 2)
        iz0 = torch.clamp(torch.searchsorted(z_levels, z, right=True) - 1, 0, nz - 2)
    tx = torch.clamp(fx - ix0.to(fx.dtype), 0.0, 1.0)
    ty = torch.clamp(fy - iy0.to(fy.dtype), 0.0, 1.0)
    z0v, z1v = z_levels[iz0], z_levels[iz0 + 1]
    tz = torch.clamp((z - z0v) / torch.clamp(z1v - z0v, min=1e-6), 0.0, 1.0)

    def gather(iz, iy, ix):
        return vol[iz, iy, ix]

    c000 = gather(iz0, iy0, ix0); c001 = gather(iz0, iy0, ix0 + 1)
    c010 = gather(iz0, iy0 + 1, ix0); c011 = gather(iz0, iy0 + 1, ix0 + 1)
    c100 = gather(iz0 + 1, iy0, ix0); c101 = gather(iz0 + 1, iy0, ix0 + 1)
    c110 = gather(iz0 + 1, iy0 + 1, ix0); c111 = gather(iz0 + 1, iy0 + 1, ix0 + 1)
    c00 = c000 * (1 - tx) + c001 * tx
    c01 = c010 * (1 - tx) + c011 * tx
    c10 = c100 * (1 - tx) + c101 * tx
    c11 = c110 * (1 - tx) + c111 * tx
    c0 = c00 * (1 - ty) + c01 * ty
    c1 = c10 * (1 - ty) + c11 * ty
    return c0 * (1 - tz) + c1 * tz


def _bilinear_uniform(raster: torch.Tensor, x0: float, y0: float, res: float,
                       x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
    ny, nx = raster.shape
    fx = torch.clamp((x - x0) / res, 0.0, nx - 1.0)
    fy = torch.clamp((y - y0) / res, 0.0, ny - 1.0)
    with torch.no_grad():
        ix0 = torch.clamp(torch.floor(fx).long(), 0, nx - 2)
        iy0 = torch.clamp(torch.floor(fy).long(), 0, ny - 2)
    tx = fx - ix0.to(fx.dtype)
    ty = fy - iy0.to(fy.dtype)
    c00 = raster[iy0, ix0]; c01 = raster[iy0, ix0 + 1]
    c10 = raster[iy0 + 1, ix0]; c11 = raster[iy0 + 1, ix0 + 1]
    c0 = c00 * (1 - tx) + c01 * tx
    c1 = c10 * (1 - tx) + c11 * tx
    return c0 * (1 - ty) + c1 * ty


class NestedSDFGridGeometry(GeometrySource):
    """Reads the ACTUAL geometry-pipeline output (design review M3: an
    earlier version of this module guessed a `<variant>_sdf.npz` filename
    and flat {sdf,origin,spacing,height} keys that don't match what
    `geometry/sdf.py: build_nested_sdf_grid` really writes -- fine/coarse
    nested grids with a non-uniform per-level `fine_z`/`coarse_z` array --
    so `resolve_geometry_source` silently fell back to non-differentiable
    constants for every real case, everywhere, not just near walls).

    Reads `geometry/out/<scenario>/sdf_grid_<variant>.npz` (fine grid used
    up to its z-top, coarse grid above) and a separate smoothed height
    raster (`height_raster_smooth_s5.npy` + its `_meta.json`, M7: using the
    *smoothed* raster per DATA_CONTRACT's local_height definition choice).
    Trilinear/bilinear (custom torch, since z spacing is non-uniform --
    see `_trilinear_nonuniform_z`), differentiable w.r.t. (x,y,z), with the
    same piecewise-linear-second-derivative caveat as any grid method
    (prefer `PolygonPrismGeometry` once building footprint polygons are
    available -- see its docstring).
    """

    def __init__(self, sdf_npz_path, height_npy_path, height_meta_path):
        import json
        import numpy as np
        d = np.load(sdf_npz_path)
        self.fine_sdf = torch.as_tensor(d["fine_sdf"], dtype=torch.float32)
        self.fine_x0, self.fine_y0 = float(d["fine_x0"]), float(d["fine_y0"])
        self.fine_res = float(d["fine_res_xy"])
        self.fine_z = torch.as_tensor(d["fine_z"], dtype=torch.float32)
        self.coarse_sdf = torch.as_tensor(d["coarse_sdf"], dtype=torch.float32)
        self.coarse_x0, self.coarse_y0 = float(d["coarse_x0"]), float(d["coarse_y0"])
        self.coarse_res = float(d["coarse_res"])
        self.coarse_z = torch.as_tensor(d["coarse_z"], dtype=torch.float32)

        self.height = torch.as_tensor(np.load(height_npy_path), dtype=torch.float32)
        meta = json.loads(Path(height_meta_path).read_text(encoding="utf-8"))
        self.h_x0, self.h_y0, self.h_res = meta["x0"], meta["y0"], meta["resolution"]

    def sdf_and_height(self, x: torch.Tensor, y: torch.Tensor, z: torch.Tensor):
        device = x.device
        fine_top = float(self.fine_z[-1])
        z_clamped_fine = torch.clamp(z, max=fine_top)
        sdf_fine = _trilinear_nonuniform_z(self.fine_sdf.to(device), self.fine_x0, self.fine_y0,
                                            self.fine_res, self.fine_z.to(device), x, y, z_clamped_fine)
        sdf_coarse = _trilinear_nonuniform_z(self.coarse_sdf.to(device), self.coarse_x0, self.coarse_y0,
                                              self.coarse_res, self.coarse_z.to(device), x, y, z)
        sdf = torch.where(z <= fine_top, sdf_fine, sdf_coarse)
        h = _bilinear_uniform(self.height.to(device), self.h_x0, self.h_y0, self.h_res, x, y)
        return sdf, h


_GEOMETRY_WARNED = set()


def resolve_geometry_source(variant: str, geometry_dir: Optional[str] = None,
                             scenario: str = "H_best") -> Optional[GeometrySource]:
    """Pick a GeometrySource for `variant`:
      1. an exact AnalyticBoxGeometry if ml.synthetic recognises the variant
         (every synthetic smoke-test case);
      2. else the real geometry-pipeline output, if present:
         `<geometry_dir>/<scenario>/sdf_grid_<variant>.npz` +
         `height_raster_smooth_s5.npy` (NestedSDFGridGeometry, M3/M7);
      3. else None -- caller falls back to precomputed, non-differentiable
         sdf/height constants, and PRINTS A WARNING (once per variant) so
         this never fails silently (M3: an earlier version returned None
         silently whenever the (wrong) expected filename wasn't found).
    """
    from . import synthetic
    buildings = synthetic.VARIANTS.get(variant)
    if buildings is not None:
        return AnalyticBoxGeometry(buildings)

    geometry_dir = geometry_dir or str(Path(r"E:\PINN\v2\geometry\out"))
    scenario_dir = Path(geometry_dir) / scenario
    npz_path = scenario_dir / f"sdf_grid_{variant}.npz"
    height_path = scenario_dir / "height_raster_smooth_s5.npy"
    height_meta_path = scenario_dir / "height_raster_smooth_s5_meta.json"
    if npz_path.exists() and height_path.exists() and height_meta_path.exists():
        return NestedSDFGridGeometry(str(npz_path), str(height_path), str(height_meta_path))

    if variant not in _GEOMETRY_WARNED:
        _GEOMETRY_WARNED.add(variant)
        print(f"[features] WARNING: no differentiable geometry source found for variant "
              f"'{variant}' (looked for {npz_path}); stage B/C residuals for this variant "
              f"will use precomputed, non-differentiable sdf/local_height everywhere "
              f"(not just near walls) -- see EpochSampler.differentiable_geometry docstring.")
    return None
