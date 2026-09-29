"""
sdf.py -- signed-distance and height-map helpers for a ZT-ENU building STL.

Sign convention (matches v2/docs/DATA_CONTRACT.md `sdf` dataset):
    sdf > 0  outside buildings (in the fluid)
    sdf < 0  inside a building solid
    sdf == 0 on a building surface

trimesh.proximity.signed_distance returns the OPPOSITE convention
(positive INSIDE); this module negates it.
"""
import json

import numpy as np
import trimesh
from scipy import ndimage


class BuildingSDF:
    def __init__(self, stl_path):
        self.mesh = trimesh.load(stl_path)
        if isinstance(self.mesh, trimesh.Scene):
            self.mesh = trimesh.util.concatenate(
                [g for g in self.mesh.geometry.values()]
            )

    def signed_distance(self, points):
        """points: (N,3) array in ZT-ENU metres. Returns (N,) float array,
        positive in the fluid, negative inside a building."""
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        sd_inside_positive = trimesh.proximity.signed_distance(self.mesh, points)
        return -np.asarray(sd_inside_positive)

    def height_at(self, xy_points, height_raster):
        """Look up local building height (m) at (x,y) points using a
        HeightRaster (nearest-cell)."""
        return height_raster.sample(xy_points)


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


def _fast_extrusion_sdf_level(height_arr, res, z):
    """Exact-for-LOD1 analytic signed distance, at one z level, to a field of
    vertical building extrusions described by `height_arr` (2D raster, 0 =
    no building, else building height in m at that cell). Positive = fluid.

    For any (x,y) INSIDE a building's footprint, the formula is exact:
    nearest surface is either the footprint boundary (side wall, at the
    same z) or the roof/ground plane, whichever is closer.

    For (x,y) OUTSIDE every footprint, the nearest building surface is
    approximated as belonging to the building owning the geometrically
    NEAREST footprint pixel in the 2D plan raster (via a Euclidean distance
    transform); this is exact when that nearest building is also the
    nearest one once height is accounted for, which holds unless a taller
    building lies a bit farther away in plan and closer in 3D at this z --
    a documented approximation (see sdf_grids README), bounded by the
    raster resolution.
    """
    inside = height_arr > 0
    dist_out_px, nearest_idx = ndimage.distance_transform_edt(~inside, return_indices=True)
    dist_in_px = ndimage.distance_transform_edt(inside)
    dist_out_m = dist_out_px * res
    dist_in_m = dist_in_px * res
    h_near = height_arr[nearest_idx[0], nearest_idx[1]]

    sdf = np.zeros_like(height_arr, dtype=np.float32)

    out_mask = ~inside
    b_out = np.maximum(0.0, z - h_near)
    sdf[out_mask] = np.sqrt(dist_out_m[out_mask] ** 2 + b_out[out_mask] ** 2).astype(np.float32)

    within = (z >= 0) & (z <= height_arr)
    inside_within = inside & within
    depth_z = np.minimum(z, height_arr - z)
    sdf_iw = -np.minimum(dist_in_m, depth_z)
    sdf[inside_within] = sdf_iw[inside_within].astype(np.float32)

    inside_above = inside & ~within  # z > roof (z>=0 always in this domain)
    sdf[inside_above] = (z - height_arr)[inside_above].astype(np.float32)

    return sdf


def build_nested_sdf_grid(records, zoi_bounds, h_max,
                           fine_res_xy=1.0, fine_res_z=1.0, fine_z_top=20.0,
                           coarse_res=4.0, coarse_z_top_factor=2.0,
                           dtype=np.float32):
    """Build a two-level nested SDF grid over the ZOI, using the fast
    analytic per-level extrusion formula (see _fast_extrusion_sdf_level):

      - FINE grid: fine_res_xy (default 1 m) horizontal, fine_res_z
        (default 1 m, within the requested 0.5-1 m) vertical, from z=0 to
        fine_z_top (default 20 m) -- the pedestrian-to-low-rise layer where
        gradients matter most for wind-comfort ML.
      - COARSE grid: coarse_res (default 4 m) horizontal AND vertical, from
        z=0 to coarse_z_top_factor*h_max (default 2*H_max, matching the
        DATA_CONTRACT's stored CFD z-range) -- captures the full building
        wake/rooftop region cheaply.

    Both grids share the same (x0,y0) origin so a consumer can align them.
    Returns a dict ready to be passed to numpy.savez.
    """
    minx, miny, maxx, maxy = zoi_bounds

    def build_level_set(res, z_top):
        nx = int(np.ceil((maxx - minx) / res))
        ny = int(np.ceil((maxy - miny) / res))
        hr = HeightRaster.rasterize(records, (minx, miny, minx + nx * res, miny + ny * res), resolution=res)
        n_z = int(np.floor(z_top / res)) + 1
        z_levels = np.arange(n_z) * res
        vol = np.empty((n_z, hr.ny, hr.nx), dtype=dtype)
        for iz, z in enumerate(z_levels):
            vol[iz] = _fast_extrusion_sdf_level(hr.array, res, float(z)).astype(dtype)
        return vol, z_levels, hr

    fine_vol, fine_z, fine_hr = build_level_set(fine_res_xy, fine_z_top)
    # allow a distinct vertical spacing for the fine grid if requested
    if fine_res_z != fine_res_xy:
        n_z = int(np.floor(fine_z_top / fine_res_z)) + 1
        fine_z2 = np.arange(n_z) * fine_res_z
        vol2 = np.empty((n_z, fine_hr.ny, fine_hr.nx), dtype=dtype)
        for iz, z in enumerate(fine_z2):
            vol2[iz] = _fast_extrusion_sdf_level(fine_hr.array, fine_res_xy, float(z)).astype(dtype)
        fine_vol, fine_z = vol2, fine_z2

    coarse_vol, coarse_z, coarse_hr = build_level_set(coarse_res, coarse_z_top_factor * h_max)

    return {
        "fine_sdf": fine_vol, "fine_x0": minx, "fine_y0": miny,
        "fine_res_xy": fine_res_xy, "fine_res_z": fine_res_z, "fine_z": fine_z,
        "coarse_sdf": coarse_vol, "coarse_x0": minx, "coarse_y0": miny,
        "coarse_res": coarse_res, "coarse_z": coarse_z,
        "frame": "ZT-ENU", "units": "m",
        "convention": "sdf>0 fluid, sdf<0 inside building",
        "method": "fast_analytic_extrusion (see sdf._fast_extrusion_sdf_level)",
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
    """Unit test on a single 10x10x10 m box centred at (5,5) with base at z=0."""
    import tempfile, os
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

    from shapely.geometry import box as shapely_box
    rec = [{"geom": shapely_box(0, 0, 10, 10), "height_m": 10.0}]
    hr = HeightRaster.rasterize(rec, (0, 0, 10, 10), resolution=1.0)
    h_center = hr.sample(np.array([[5.0, 5.0]]))[0]
    h_outside = hr.sample(np.array([[15.0, 15.0]]))[0]
    assert h_center == 10.0, h_center
    assert h_outside == 0.0, h_outside

    os.remove(tmp)
    return True


if __name__ == "__main__":
    ok = _self_test()
    print("sdf.py self-test:", "PASS" if ok else "FAIL")
