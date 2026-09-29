"""
google_raster.py -- zonal (per-footprint) statistics from the Google Open
Buildings 2.5D Temporal height raster, used as the primary height source in
the H_best scenario (Hermann's decision: trust the satellite over OSM
levels). Using the MEDIAN height over each footprint (rather than a single
point sample or the max) is deliberate: it is robust to a minority of
"parallax bleed" pixels spilling over from a taller neighbouring building,
since by construction more than half the footprint's pixels must agree with
whatever the median reports.
"""
import os

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds, transform as window_transform

GOOGLE_TIF = r"E:\PINN\datos\alturas\raw\google_25d\zoi_height_piece0.tif"

_CACHE = {}


def _load(path=GOOGLE_TIF):
    if path not in _CACHE:
        with rasterio.open(path) as src:
            arr = src.read(1)
            _CACHE[path] = (arr, src.transform, src.crs, src.bounds)
    return _CACHE[path]


def zonal_stats(polygon_utm, path=GOOGLE_TIF):
    """Return {median, mean, max, n_pixels, frac_above_30} for the raster
    pixels whose centre falls inside `polygon_utm` (UTM14N, matches the
    raster CRS), or None if the polygon doesn't overlap the raster / has no
    valid pixels."""
    arr, full_transform, crs, bounds = _load(path)
    minx, miny, maxx, maxy = polygon_utm.bounds
    if maxx < bounds.left or minx > bounds.right or maxy < bounds.bottom or miny > bounds.top:
        return None
    win = from_bounds(minx, miny, maxx, maxy, transform=full_transform).round_offsets().round_lengths(pixel_precision=0)
    row_off = max(0, int(win.row_off))
    col_off = max(0, int(win.col_off))
    row_end = min(arr.shape[0], row_off + max(1, int(win.height)))
    col_end = min(arr.shape[1], col_off + max(1, int(win.width)))
    if row_end <= row_off or col_end <= col_off:
        return None
    sub = arr[row_off:row_end, col_off:col_end]
    if sub.size == 0:
        return None
    from rasterio.windows import Window
    sub_transform = window_transform(Window(col_off, row_off, col_end - col_off, row_end - row_off), full_transform)
    try:
        mask = geometry_mask([polygon_utm], out_shape=sub.shape, transform=sub_transform, invert=True)
    except Exception:
        return None
    vals = sub[mask]
    vals = vals[np.isfinite(vals)]
    if len(vals) == 0:
        return None
    return {
        "median": float(np.median(vals)),
        "mean": float(np.mean(vals)),
        "max": float(np.max(vals)),
        "n_pixels": int(len(vals)),
        "frac_above_30": float(np.mean(vals > 30.0)),
    }


def compute_all_zonal_stats(records, geom_key="geom"):
    """records: list of dicts with a shapely polygon at `geom_key` (UTM) and
    'osm_id'. Returns dict osm_id(str) -> zonal_stats dict, skipping
    buildings outside the raster coverage or with no valid pixels."""
    out = {}
    for r in records:
        g = r.get(geom_key)
        if g is None or g.is_empty:
            continue
        stats = zonal_stats(g)
        if stats is not None:
            out[str(r["osm_id"])] = stats
    return out
