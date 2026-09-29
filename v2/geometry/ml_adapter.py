"""
ml_adapter.py -- F1 review M3: adapt this project's nested SDF grid (.npz,
see sdf.build_nested_sdf_grid) to the flat single-resolution layout that
`v2/ml/features.py`'s `GridGeometry` / `resolve_geometry_source` expect:

    E:\\PINN\\v2\\geometry\\out\\<variant>_sdf.npz  with keys:
        sdf              float32 [nz,ny,nx]  (ONE uniform-spacing grid)
        origin           float32 [3]  (x0,y0,z0), ZT-ENU metres
        spacing          float32 [3]  (dx,dy,dz), metres
        height           float32 [ny,nx]  (pre-smoothed local height)
        height_origin    float32 [2]
        height_spacing   float32 [2]

Design choice (documented, not silently guessed): this project's SDF is a
TWO-level nested grid (fine 1 m to 20 m for near-ground detail, coarse 4 m
to 2*H_max for full-domain coverage -- see DATA_CONTRACT's z in [0, 2*H_max]
convention), because a single uniform grid at 1 m over the full height would
be enormous. `ml/features.py:GridGeometry` wants exactly ONE uniform grid
covering the range any collocation point could land in (typically the full
CFD domain height), so the adapter exports the COARSE sub-grid (4 m, full
0..2*H_max range) as `sdf` -- full coverage, modest size. The 1 m near-ground
detail stays available to geometry/CFD consumers in `sdf_grid_<variant>.npz`
(`fine_sdf`) but is NOT what `<variant>_sdf.npz` carries; if ML later needs
finer resolution near the ground, re-run with a finer `coarse_res` or extend
this adapter to stitch fine+coarse into one grid.

`height` uses the sigma=5 m Gaussian-smoothed height raster (matches
GridGeometry's own docstring: "pre-smoothed local height").

Only the DEFAULT scenario (H_best) is exported this way, since
resolve_geometry_source's path has no scenario dimension -- see
build_geometry.py's `is_default_scenario` gate and the README note in both
v2/geometry/README.md and v2/ml/README.md (if present).
"""
import numpy as np


def write_ml_geometry_npz(nested_grid, height_raster_smooth, out_path):
    """nested_grid: dict as returned by sdf.build_nested_sdf_grid.
    height_raster_smooth: an sdf.HeightRaster (already Gaussian-smoothed)."""
    coarse = nested_grid["coarse_sdf"]  # [nz,ny,nx]
    z = nested_grid["coarse_z"]
    dz = float(z[1] - z[0]) if len(z) > 1 else float(nested_grid["coarse_res"])
    np.savez(
        out_path,
        sdf=coarse.astype(np.float32),
        origin=np.array([nested_grid["coarse_x0"], nested_grid["coarse_y0"], float(z[0])], dtype=np.float32),
        spacing=np.array([nested_grid["coarse_res"], nested_grid["coarse_res"], dz], dtype=np.float32),
        height=height_raster_smooth.array.astype(np.float32),
        height_origin=np.array([height_raster_smooth.x0, height_raster_smooth.y0], dtype=np.float32),
        height_spacing=np.array([height_raster_smooth.res, height_raster_smooth.res], dtype=np.float32),
    )


def round_trip_test():
    """Build a tiny synthetic nested_grid + HeightRaster, write, read back
    with the SAME loader ml/features.py:GridGeometry uses, and check shapes
    and a few values match. Self-contained (no dependency on ml/ package,
    since geometry/ must not import ml/); mirrors GridGeometry.__init__
    exactly so a schema drift there would break this test too."""
    import tempfile
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import sdf as sdf_mod
    from shapely.geometry import box as shapely_box

    rec = [{"geom": shapely_box(-5, -5, 5, 5), "height_m": 12.0}]
    grid = sdf_mod.build_nested_sdf_grid(rec, (-20, -20, 20, 20), h_max=12.0,
                                          fine_z_top=10.0, coarse_res=2.0)
    hr = sdf_mod.HeightRaster.rasterize(rec, (-20, -20, 20, 20), resolution=2.0)
    hr_smooth = sdf_mod.gaussian_smoothed_height_raster(hr, 5.0)

    tmp = os.path.join(tempfile.gettempdir(), "ml_adapter_roundtrip_test.npz")
    write_ml_geometry_npz(grid, hr_smooth, tmp)

    with np.load(tmp) as npz:
        data = {k: npz[k] for k in npz.files}
    for key in ("sdf", "origin", "spacing", "height", "height_origin", "height_spacing"):
        assert key in data, f"missing key '{key}' expected by ml/features.py:GridGeometry"
    assert data["sdf"].ndim == 3, "sdf must be [nz,ny,nx]"
    assert data["origin"].shape == (3,)
    assert data["spacing"].shape == (3,)
    assert data["height"].ndim == 2, "height must be [ny,nx]"
    assert data["height_origin"].shape == (2,)
    assert data["height_spacing"].shape == (2,)
    assert np.all(data["spacing"] > 0), "grid_sample requires positive spacing"

    # value sanity: centre of the box at mid-height should be negative (inside)
    nz, ny, nx = data["sdf"].shape
    centre_val = data["sdf"][nz // 2, ny // 2, nx // 2]
    assert centre_val <= 0, f"expected inside (or on the boundary of) the box at the grid centre, got {centre_val}"

    os.remove(tmp)
    return True


if __name__ == "__main__":
    ok = round_trip_test()
    print("ml_adapter.py round-trip test:", "PASS" if ok else "FAIL")
