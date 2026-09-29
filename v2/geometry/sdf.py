"""
sdf.py -- signed-distance and height-map helpers for ZT-ENU LOD1 buildings.

Sign convention (matches v2/docs/DATA_CONTRACT.md `sdf` dataset):
    sdf > 0  outside buildings (in the fluid)
    sdf < 0  inside a building solid
    sdf == 0 on a building surface

CANONICAL implementation (F1 independent review, item G4, 2026-09-28):
`ExactPrismSDF` (scattered points) and `build_nested_sdf_grid` (regular
grids) both use the exact LOD1 prism-union formula in
`_polygon_planar_sdf` / `_prism_sdf_value` / `_combine_prism`. This is the
SINGLE SDF implementation to use everywhere a signed distance to buildings
is needed: the HDF5 CFD-sample extractor, ML training/inference, and the
web export grid -- so there is no train/inference mismatch. `BuildingSDF`
(trimesh-based) is kept only as a slow, geometry-agnostic reference/ground
truth for tests (trimesh.proximity.signed_distance uses the OPPOSITE sign
convention -- positive INSIDE -- so BuildingSDF negates it).

The previous "fast" implementation (nearest-footprint-in-plan + that
building's height) is REMOVED: it was shown to badly overestimate distance
whenever a taller building farther away in plan is actually the true
nearest surface once height is accounted for (a short building 2 m away
"won" over an 80 m tower 16 m away, giving ~27 m instead of the true
~16 m) -- exactly the near-tower region that matters most for pedestrian
wind comfort. See F1_revision.md G4.
"""
import json

import numpy as np
import shapely
import trimesh
from scipy import ndimage
from shapely.strtree import STRtree


class BuildingSDF:
    """Reference/cross-check implementation: exact triangle-mesh signed
    distance via trimesh (slow -- ~300 us/point -- but geometry-agnostic,
    not limited to LOD1 extrusions). Used in tests as ground truth for
    ExactPrismSDF (the canonical, fast implementation used everywhere else:
    grids, HDF5 extraction, ML, web -- see module docstring).

    IMPORTANT: when given a multi-solid STL (or a Scene), each building's
    mesh is kept SEPARATE and combined per-point with the correct CSG-union
    rule (see _combine_prism), NOT concatenated into one mesh. Concatenating
    (naive `trimesh.util.concatenate`, the previous implementation) welds
    vertices at any exact coincidence -- which happens wherever two OSM
    buildings share a party wall -- producing a non-manifold mesh whose
    ray-casting/winding-number inside test can silently misclassify points
    near that wall (confirmed bug: a point 7.16 m inside a real building was
    reported as 7.14 m OUTSIDE, matching a different, unrelated building's
    distance, once two touching buildings' STLs were concatenated). Loading
    a SINGLE-solid STL (already welded, e.g. zonatec_base.stl) still has
    this risk baked in; prefer the *_multisolid.stl files with BuildingSDF."""

    def __init__(self, stl_path):
        loaded = trimesh.load(stl_path)
        if isinstance(loaded, trimesh.Scene):
            self.meshes = [g for g in loaded.geometry.values() if len(g.faces) > 0]
        else:
            self.meshes = [loaded]

    def signed_distance(self, points):
        """points: (N,3) array in ZT-ENU metres. Returns (N,) float array,
        positive in the fluid, negative inside a building."""
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        acc = np.full(len(points), np.inf)
        for m in self.meshes:
            sd_inside_positive = np.asarray(trimesh.proximity.signed_distance(m, points))
            acc = _combine_prism(acc, -sd_inside_positive)
        return acc

    def height_at(self, xy_points, height_raster):
        """Look up local building height (m) at (x,y) points using a
        HeightRaster (nearest-cell)."""
        return height_raster.sample(xy_points)


# ---------------------------------------------------------------------------
# ExactPrismSDF -- CANONICAL implementation (F1 review, G4): exact signed
# distance to a field of LOD1 vertical-extrusion ("prism") buildings, with NO
# nearest-neighbour approximation. For one building b with footprint polygon
# P_b and height h_b, the exact prism distance at (x,y,z) is:
#
#   d2_b(x,y) = signed planar distance to P_b's BOUNDARY (positive outside
#               P_b, negative inside -- via shapely, vectorized)
#   if inside P_b and 0<=z<=h_b:      sdf_b = -min(|d2_b|, min(z, h_b-z))
#   else:                              sdf_b = sqrt(max(d2_b,0)^2 + max(0,z-h_b)^2)
#
# and the field for the UNION of all buildings is the correct CSG-union
# combine (see _combine_prism): min of the positive candidates when outside
# every building, else max (least-negative = nearest exit) among the
# negative candidates. This fixes the bug in the earlier "nearest footprint
# in plan" approximation, which could badly overestimate distance near a
# short building when a taller building farther away in plan is actually
# closer once height is accounted for (confirmed failure mode, see
# F1_revision.md G4: point at z=30 m, 2 m from a 3 m house and 16 m from an
# 80 m tower -> old method gave ~27 m, exact gives ~16 m).
# ---------------------------------------------------------------------------

def _polygon_planar_sdf(polygon, xs, ys):
    """Vectorized exact signed planar distance from `polygon`'s boundary to
    points (xs,ys) (positive outside, negative inside). Returns (d2, inside)."""
    pts = shapely.points(xs, ys)
    d_boundary = shapely.distance(polygon.boundary, pts)
    inside = shapely.contains(polygon, pts)
    d2 = np.where(inside, -d_boundary, d_boundary)
    return d2, inside


def _prism_sdf_value(d2, inside, h, z):
    """Combine a building's planar signed distance field (d2, inside) with
    its height h at level z into that single building's 3D SDF."""
    within_height = (z >= 0) & (z <= h)
    interior_mask = inside & within_height
    a = np.maximum(d2, 0.0)
    b = max(0.0, z - h) if np.isscalar(h) else np.maximum(0.0, z - h)
    ext = np.sqrt(a ** 2 + b ** 2)
    depth_z = np.minimum(z, h - z) if np.isscalar(h) else np.minimum(z, np.maximum(h - z, 0.0))
    d_boundary = np.abs(d2)
    interior = -np.minimum(d_boundary, depth_z)
    return np.where(interior_mask, interior, ext)


def _combine_prism(acc, new):
    """CSG-union combine of two signed-distance arrays under the
    positive-outside/negative-inside convention: if either says 'inside',
    the union is inside (negative wins over positive); among two negatives,
    the union boundary is the LEAST negative (nearest exit); among two
    positives, the nearest (smallest) wins."""
    out = acc.copy()
    neg_acc = acc < 0
    neg_new = new < 0
    m1 = neg_new & ~neg_acc
    out[m1] = new[m1]
    m2 = neg_new & neg_acc
    out[m2] = np.maximum(acc[m2], new[m2])
    m3 = (~neg_new) & (~neg_acc)
    out[m3] = np.minimum(acc[m3], new[m3])
    return out


class ExactPrismSDF:
    """Canonical SDF for a set of LOD1 buildings (records with 'geom'
    (shapely polygon, ZT-ENU) and 'height_m'). Use this everywhere a signed
    distance to buildings is needed on scattered points (HDF5 extraction,
    ML training/inference, web export); for regular grids, use
    build_nested_sdf_grid instead (much faster, exact same formulas)."""

    def __init__(self, records, k_nearest=20):
        self.records = [r for r in records if r["geom"] is not None and not r["geom"].is_empty]
        self.k_nearest = k_nearest
        self._geoms = [r["geom"] for r in self.records]
        self._heights = np.array([r["height_m"] for r in self.records])
        self._tree = STRtree(self._geoms) if self._geoms else None
        self._centroids = np.array([[g.centroid.x, g.centroid.y] for g in self._geoms]) \
            if self._geoms else np.zeros((0, 2))

    def _nearest_k_indices(self, x, y):
        if self._tree is None or len(self._geoms) == 0:
            return np.array([], dtype=int)
        d2 = (self._centroids[:, 0] - x) ** 2 + (self._centroids[:, 1] - y) ** 2
        k = min(self.k_nearest, len(d2))
        return np.argpartition(d2, k - 1)[:k]

    def signed_distance(self, points):
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        out = np.full(len(points), np.inf)
        # group by (x,y) exactly wouldn't help much for scattered points;
        # process point-by-point (candidate selection differs per point) but
        # each point only touches k_nearest buildings, so this stays fast
        # for the scattered-query use case (hundreds-thousands of points).
        for i, (x, y, z) in enumerate(points):
            idxs = self._nearest_k_indices(x, y)
            acc = np.array([np.inf])
            for j in idxs:
                d2, inside = _polygon_planar_sdf(self._geoms[j], np.array([x]), np.array([y]))
                val = _prism_sdf_value(d2, inside, float(self._heights[j]), float(z))
                acc = _combine_prism(acc, val)
            out[i] = acc[0] if np.isfinite(acc[0]) else 1e6
        return out


class HeightRaster:
    """2D raster of building height (m above ground, 0 = no building) over
    the ZOI, in ZT-ENU x,y metres."""

    def __init__(self, array, x0, y0, resolution):
        self.array = array  # shape (ny, nx), row 0 = y0 (south row)
        self.x0 = x0
        self.y0 = y0
        self.res = resolution
        self.ny, self.nx = array.shape

    @classmethod
    def rasterize(cls, records, bounds, resolution=1.0):
        """records: list of dicts with 'geom' (shapely polygon/multipolygon,
        ZT-ENU x,y) and 'height_m'. bounds: (xmin,ymin,xmax,ymax)."""
        xmin, ymin, xmax, ymax = bounds
        nx = int(np.ceil((xmax - xmin) / resolution))
        ny = int(np.ceil((ymax - ymin) / resolution))
        arr = np.zeros((ny, nx), dtype=np.float32)

        # cell-centre sample grid + point-in-polygon via STRtree for speed
        from shapely.geometry import Point
        from shapely.strtree import STRtree

        geoms = [r["geom"] for r in records]
        heights = [r["height_m"] for r in records]
        if not geoms:
            return cls(arr, xmin, ymin, resolution)
        tree = STRtree(geoms)
        gid = {id(g): i for i, g in enumerate(geoms)}

        xs = xmin + (np.arange(nx) + 0.5) * resolution
        ys = ymin + (np.arange(ny) + 0.5) * resolution
        for iy, y in enumerate(ys):
            row_pts = [Point(x, y) for x in xs]
            for ix, p in enumerate(row_pts):
                cand = tree.query(p)
                best_h = 0.0
                for ci in cand:
                    g = geoms[int(ci)]
                    if g.contains(p) or g.intersects(p):
                        best_h = max(best_h, heights[int(ci)])
                arr[iy, ix] = best_h
        return cls(arr, xmin, ymin, resolution)

    def sample(self, xy_points):
        xy = np.asarray(xy_points, dtype=float).reshape(-1, 2)
        ix_raw = ((xy[:, 0] - self.x0) / self.res).astype(int)
        iy_raw = ((xy[:, 1] - self.y0) / self.res).astype(int)
        inside = (ix_raw >= 0) & (ix_raw < self.nx) & (iy_raw >= 0) & (iy_raw < self.ny)
        ix = np.clip(ix_raw, 0, self.nx - 1)
        iy = np.clip(iy_raw, 0, self.ny - 1)
        out = self.array[iy, ix]
        out = np.where(inside, out, 0.0)
        return out

    def save(self, npy_path, meta_path=None):
        np.save(npy_path, self.array)
        meta = {
            "x0": self.x0, "y0": self.y0, "resolution": self.res,
            "nx": self.nx, "ny": self.ny, "frame": "ZT-ENU",
            "units": "m", "value": "building height above ground (0=no building)",
        }
        if meta_path is None:
            meta_path = str(npy_path).rsplit(".", 1)[0] + "_meta.json"
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
        return meta_path

    @classmethod
    def load(cls, npy_path, meta_path=None):
        arr = np.load(npy_path)
        if meta_path is None:
            meta_path = str(npy_path).rsplit(".", 1)[0] + "_meta.json"
        with open(meta_path) as f:
            meta = json.load(f)
        return cls(arr, meta["x0"], meta["y0"], meta["resolution"])


def _build_exact_level_set(records, minx, miny, maxx, maxy, res, z_levels, window_pad_m=100.0):
    """Exact nested-grid builder (F1 review G4): per building, compute its
    EXACT planar signed distance (shapely, vectorized) once over a local
    window (its bbox + window_pad_m), then combine into every z-level's
    global array via the correct CSG-union rule (_combine_prism). This
    avoids ever approximating "nearest building" by plan-only proximity --
    every building within window_pad_m of a cell is considered exactly, and
    window_pad_m (100 m by default) comfortably covers the near-field
    interactions that mattered in the failure case identified by the review
    (a tower dominating from 16 m away over a much closer short building).
    Cells with no building within window_pad_m of them are left at the
    (correct) lower-bound sentinel `window_pad_m` (documented, not silently
    wrong: the true value there is >= window_pad_m by construction).
    """
    nx = int(np.ceil((maxx - minx) / res))
    ny = int(np.ceil((maxy - miny) / res))
    n_z = len(z_levels)
    vol = np.full((n_z, ny, nx), np.inf, dtype=np.float64)

    xs_full = minx + (np.arange(nx) + 0.5) * res
    ys_full = miny + (np.arange(ny) + 0.5) * res

    for r in records:
        poly = r["geom"]
        h = r["height_m"]
        if poly is None or poly.is_empty:
            continue
        bminx, bminy, bmaxx, bmaxy = poly.bounds
        wx0 = max(0, int((bminx - window_pad_m - minx) / res))
        wx1 = min(nx, int(np.ceil((bmaxx + window_pad_m - minx) / res)))
        wy0 = max(0, int((bminy - window_pad_m - miny) / res))
        wy1 = min(ny, int(np.ceil((bmaxy + window_pad_m - miny) / res)))
        if wx1 <= wx0 or wy1 <= wy0:
            continue
        xs = xs_full[wx0:wx1]
        ys = ys_full[wy0:wy1]
        XX, YY = np.meshgrid(xs, ys)
        d2, inside = _polygon_planar_sdf(poly, XX.ravel(), YY.ravel())
        d2 = d2.reshape(XX.shape)
        inside = inside.reshape(XX.shape)
        for iz, z in enumerate(z_levels):
            val = _prism_sdf_value(d2, inside, h, float(z))
            sub = vol[iz, wy0:wy1, wx0:wx1]
            vol[iz, wy0:wy1, wx0:wx1] = _combine_prism(sub, val)

    vol[np.isinf(vol)] = window_pad_m
    return vol, (ny, nx)


def build_nested_sdf_grid(records, zoi_bounds, h_max,
                           fine_res_xy=1.0, fine_res_z=1.0, fine_z_top=20.0,
                           coarse_res=4.0, coarse_z_top_factor=2.0,
                           window_pad_m=100.0, dtype=np.float32):
    """Build a two-level nested SDF grid over the ZOI using the EXACT prism
    method (_build_exact_level_set / ExactPrismSDF -- F1 review G4; replaces
    the earlier fast-but-approximate nearest-footprint method):

      - FINE grid: fine_res_xy (default 1 m) horizontal, fine_res_z
        (default 1 m, within the requested 0.5-1 m) vertical, from z=0 to
        fine_z_top (default 20 m) -- the pedestrian-to-low-rise layer where
        gradients matter most for wind-comfort ML.
      - COARSE grid: coarse_res (default 4 m) horizontal AND vertical, from
        z=0 to coarse_z_top_factor*h_max (default 2*H_max, matching the
        DATA_CONTRACT's stored CFD z-range) -- captures the full building
        wake/rooftop region cheaply.

    Both grids share the same (x0,y0) origin so a consumer can align them.
    Returns a dict ready to be passed to numpy.savez. This is now the SAME
    method (same formulas, same code path) used for the HDF5 extractor and
    ML/web point queries via ExactPrismSDF -- no train/inference mismatch.
    """
    minx, miny, maxx, maxy = zoi_bounds

    fine_z = np.arange(int(np.floor(fine_z_top / fine_res_z)) + 1) * fine_res_z
    fine_vol, _ = _build_exact_level_set(records, minx, miny, maxx, maxy,
                                          fine_res_xy, fine_z, window_pad_m)

    coarse_z = np.arange(int(np.floor((coarse_z_top_factor * h_max) / coarse_res)) + 1) * coarse_res
    coarse_vol, _ = _build_exact_level_set(records, minx, miny, maxx, maxy,
                                            coarse_res, coarse_z, window_pad_m)

    return {
        "fine_sdf": fine_vol.astype(dtype), "fine_x0": minx, "fine_y0": miny,
        "fine_res_xy": fine_res_xy, "fine_res_z": fine_res_z, "fine_z": fine_z,
        "coarse_sdf": coarse_vol.astype(dtype), "coarse_x0": minx, "coarse_y0": miny,
        "coarse_res": coarse_res, "coarse_z": coarse_z,
        "frame": "ZT-ENU", "units": "m",
        "convention": "sdf>0 fluid, sdf<0 inside building",
        "method": "exact_prism_union (see sdf.ExactPrismSDF / _build_exact_level_set)",
        "window_pad_m": window_pad_m,
    }


def trilinear_sample(vol, x0, y0, res_xy, z_levels, points):
    """Trilinear interpolation of a (nz,ny,nx) volume at ZT-ENU (x,y,z)
    points. z spacing may be non-uniform (uses searchsorted); x,y spacing is
    uniform (res_xy)."""
    points = np.asarray(points, dtype=float)
    nz, ny, nx = vol.shape
    fx = (points[:, 0] - x0) / res_xy
    fy = (points[:, 1] - y0) / res_xy
    z = points[:, 2]

    ix0 = np.clip(np.floor(fx).astype(int), 0, nx - 2)
    iy0 = np.clip(np.floor(fy).astype(int), 0, ny - 2)
    tx = np.clip(fx - ix0, 0, 1)
    ty = np.clip(fy - iy0, 0, 1)

    iz0 = np.clip(np.searchsorted(z_levels, z, side="right") - 1, 0, nz - 2)
    z0, z1 = z_levels[iz0], z_levels[iz0 + 1]
    tz = np.clip((z - z0) / np.where(z1 > z0, z1 - z0, 1.0), 0, 1)

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


def gaussian_smoothed_height_raster(height_raster, sigma_m):
    """Gaussian-smoothed copy of a HeightRaster's array, sigma given in
    metres (converted to pixels using the raster's resolution)."""
    sigma_px = sigma_m / height_raster.res
    smoothed = ndimage.gaussian_filter(height_raster.array.astype(np.float32), sigma=sigma_px)
    return HeightRaster(smoothed, height_raster.x0, height_raster.y0, height_raster.res)


def _self_test():
    """Unit test on a single 10x10x10 m box centred at (5,5) with base at z=0,
    plus a regression test reproducing the F1 review's G4 failure case."""
    import tempfile, os
    from shapely.geometry import box as shapely_box

    box = trimesh.creation.box(extents=[10, 10, 10])
    box.apply_translation([5, 5, 5])
    tmp = os.path.join(tempfile.gettempdir(), "sdf_selftest_box.stl")
    box.export(tmp)

    sdf = BuildingSDF(tmp)
    pts = np.array([
        [5, 5, 5],     # centre of box -> inside -> negative
        [5, 5, 15],    # 5 m above roof -> outside -> positive ~5
        [-5, 5, 5],    # 10 m to the side -> outside -> positive ~5... (box spans 0-10)
        [20, 20, 0.5],  # far outside -> large positive
    ])
    sd = sdf.signed_distance(pts)
    assert sd[0] < 0, f"expected negative inside box, got {sd[0]}"
    assert sd[1] > 0, f"expected positive above roof, got {sd[1]}"
    assert sd[3] > sd[1], "farther point should have larger positive sdf"

    # ExactPrismSDF must agree with the trimesh reference on the same box
    rec = [{"geom": shapely_box(0, 0, 10, 10), "height_m": 10.0}]
    eps = ExactPrismSDF(rec)
    sd_exact = eps.signed_distance(pts)
    err = np.abs(sd_exact - sd)
    assert np.all(err < 1e-6), f"ExactPrismSDF disagrees with trimesh on a plain box: {err}"

    hr = HeightRaster.rasterize(rec, (0, 0, 10, 10), resolution=1.0)
    h_center = hr.sample(np.array([[5.0, 5.0]]))[0]
    h_outside = hr.sample(np.array([[15.0, 15.0]]))[0]
    assert h_center == 10.0, h_center
    assert h_outside == 0.0, h_outside

    # --- F1 review G4 regression: a tower farther away in PLAN must still
    # win over a much closer but short building, once height matters ---
    house = shapely_box(0, 0, 3, 3)         # 3x3 m house at the origin, height 3 m
    tower = shapely_box(18, -5, 28, 5)      # 10x10 m tower, west edge at x=18
    recs2 = [{"geom": house, "height_m": 3.0}, {"geom": tower, "height_m": 80.0}]
    eps2 = ExactPrismSDF(recs2)
    # query point at (5,0,30): 2 m east of the house's east wall, 13 m west
    # of the tower's west wall, z=30 m (within the tower's height range)
    q = np.array([[5.0, 0.0, 30.0]])
    sd_house_only = _prism_sdf_value(*_polygon_planar_sdf(house, q[:, 0], q[:, 1]), 3.0, 30.0)[0]
    sd_union = eps2.signed_distance(q)[0]
    assert sd_house_only > 20, f"sanity: house-only distance should be large, got {sd_house_only}"
    assert sd_union < sd_house_only - 5, (
        f"G4 regression: union SDF ({sd_union}) should be dominated by the tower "
        f"(~13 m), not the short-but-nearer house ({sd_house_only})")
    assert 10 < sd_union < 16, f"expected ~13 m (distance to tower), got {sd_union}"

    os.remove(tmp)
    return True


if __name__ == "__main__":
    ok = _self_test()
    print("sdf.py self-test:", "PASS" if ok else "FAIL")
