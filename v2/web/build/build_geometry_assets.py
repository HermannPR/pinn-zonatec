"""Build public/data/buildings.geojson (3D-extrusion footprints, WGS84 lon/
lat + height_m) and the quantized SDF/local-height grids the browser needs
to compute the network's geometric input features (P11 geometry task).

Reuses the EXACT SDF already computed by the geometry pipeline
(`geometry/out/H_best/sdf_grid_base.npz`, the canonical
`ExactPrismSDF`/`build_nested_sdf_grid` union of LOD1 prisms -- see
`geometry/sdf.py` module docstring: "the SINGLE SDF implementation to use
everywhere ... including the web export grid") -- this script only
downsamples + quantizes it for a <10 MB download; it does NOT recompute the
SDF, so there is no new source of train/inference mismatch beyond the
downsampling itself (documented, bounded, see grid_meta.json's
`quantization_note`).

Run from E:\\PINN\\v2 with the project venv:
    E:\\PINN\\.venv\\Scripts\\python.exe web\\build\\build_geometry_assets.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage
from shapely.geometry import box, mapping
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import GEOMETRY_OUT, WEB_DATA, load_frame, enu_to_lonlat  # noqa: E402

MIN_BUILDING_AREA_M2 = 4.0
SIMPLIFY_TOL_M = 0.6

# Downsampling strides applied to geometry/out/H_best/sdf_grid_base.npz
# (fine: 1 m xy / 1 m z, 0-20 m; coarse: 4 m xy / 4 m z, 0-172 m) to keep the
# browser download small. Both grids keep their FULL z resolution (z is
# cheap: 21 and 44 levels) and are only downsampled in xy, since the
# near-ground vertical structure (pedestrian layer, 1.5-2 m) matters most
# and the xy dimensions dominate the byte count.
FINE_XY_STRIDE = 4    # 850 -> 213 (matches the coarse grid's 4 m spacing)
COARSE_XY_STRIDE = 2  # 213 -> 107 (8 m spacing)
COARSE_Z_STRIDE = 2   # 44 -> 22 levels (8 m spacing)
HEIGHT_XY_STRIDE = 2  # 1090 -> 545 (2 m spacing)

SDF_QUANT_SCALE = 0.01   # store sdf/height in centimetres as int16
HEIGHT_QUANT_SCALE = 0.01


def build_buildings_geojson(frame: dict) -> None:
    height = np.load(GEOMETRY_OUT / "height_raster.npy")
    with open(GEOMETRY_OUT / "height_raster_meta.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    x0, y0, res = meta["x0"], meta["y0"], meta["resolution"]

    mask = height > 0.5
    labels, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    print(f"[buildings] {n} connected components in the height raster")

    origin_lon, origin_lat = frame["origin_lon"], frame["origin_lat"]
    features = []
    objs = ndimage.find_objects(labels)
    kept = 0
    for lbl_idx, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        ys, xs = np.nonzero(labels[sl] == lbl_idx)
        if len(xs) == 0:
            continue
        y_off, x_off = sl[0].start, sl[1].start
        h_vals = height[sl][labels[sl] == lbl_idx]
        h_m = float(np.median(h_vals))
        area_m2 = len(xs) * res * res
        if area_m2 < MIN_BUILDING_AREA_M2:
            continue
        boxes = [
            box(x0 + (x_off + xi) * res, y0 + (y_off + yi) * res,
                x0 + (x_off + xi + 1) * res, y0 + (y_off + yi + 1) * res)
            for xi, yi in zip(xs, ys)
        ]
        poly = unary_union(boxes).simplify(SIMPLIFY_TOL_M, preserve_topology=True)
        geoms = poly.geoms if poly.geom_type == "MultiPolygon" else [poly]
        for g in geoms:
            if g.area < MIN_BUILDING_AREA_M2 or g.is_empty:
                continue
            ext_lonlat = [enu_to_lonlat(px, py, origin_lon, origin_lat) for px, py in g.exterior.coords]
            holes_lonlat = [
                [enu_to_lonlat(px, py, origin_lon, origin_lat) for px, py in ring.coords]
                for ring in g.interiors
            ]
            ring_geom = {"type": "Polygon", "coordinates": [ext_lonlat] + holes_lonlat}
            features.append({
                "type": "Feature",
                "properties": {"id": kept, "height_m": round(h_m, 2), "area_m2": round(area_m2, 1)},
                "geometry": ring_geom,
            })
            kept += 1

    fc = {"type": "FeatureCollection", "features": features}
    out_path = WEB_DATA / "buildings.geojson"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fc, f)
    print(f"[buildings] wrote {kept} footprints -> {out_path} ({out_path.stat().st_size / 1024:.1f} KB)")


def _quantize(arr: np.ndarray, scale: float) -> np.ndarray:
    q = np.round(arr / scale)
    q = np.clip(q, -32768, 32767)
    return q.astype(np.int16)


def build_sdf_grid() -> None:
    d = np.load(GEOMETRY_OUT / "sdf_grid_base.npz")

    fine_sdf = d["fine_sdf"][:, ::FINE_XY_STRIDE, ::FINE_XY_STRIDE]
    fine_res_xy = float(d["fine_res_xy"]) * FINE_XY_STRIDE
    fine_x0, fine_y0 = float(d["fine_x0"]), float(d["fine_y0"])
    fine_z = d["fine_z"].astype(np.float64).tolist()

    coarse_sdf = d["coarse_sdf"][::COARSE_Z_STRIDE, ::COARSE_XY_STRIDE, ::COARSE_XY_STRIDE]
    coarse_res_xy = float(d["coarse_res"]) * COARSE_XY_STRIDE
    coarse_x0, coarse_y0 = float(d["coarse_x0"]), float(d["coarse_y0"])
    coarse_z = d["coarse_z"][::COARSE_Z_STRIDE].astype(np.float64).tolist()

    fine_q = _quantize(fine_sdf, SDF_QUANT_SCALE)
    coarse_q = _quantize(coarse_sdf, SDF_QUANT_SCALE)

    fine_path = WEB_DATA / "sdf_fine.bin"
    coarse_path = WEB_DATA / "sdf_coarse.bin"
    fine_q.tofile(fine_path)
    coarse_q.tofile(coarse_path)

    meta = {
        "convention": "sdf>0 fluid (outside buildings), sdf<0 inside a building, metres",
        "quantization": {"dtype": "int16", "scale": SDF_QUANT_SCALE, "unit": "value*scale = metres"},
        "quantization_note": (
            f"Downsampled from geometry/out/H_best/sdf_grid_base.npz (exact "
            f"ExactPrismSDF union): fine grid xy stride {FINE_XY_STRIDE} "
            f"(1m->{fine_res_xy:.0f}m), coarse grid xy stride {COARSE_XY_STRIDE} "
            f"and z stride {COARSE_Z_STRIDE}. z kept at full resolution in "
            f"both grids. Values are bilinear/trilinear-interpolated client "
            f"side (public/js/features.js), same nested fine(near ground, "
            f"z<=20m)+coarse(above) scheme as "
            f"ml/features.py:NestedSDFGridGeometry."
        ),
        "fine": {
            "shape_zyx": list(fine_q.shape), "x0": fine_x0, "y0": fine_y0,
            "res_xy": fine_res_xy, "z_levels": fine_z, "file": "sdf_fine.bin",
        },
        "coarse": {
            "shape_zyx": list(coarse_q.shape), "x0": coarse_x0, "y0": coarse_y0,
            "res_xy": coarse_res_xy, "z_levels": coarse_z, "file": "sdf_coarse.bin",
        },
    }
    with open(WEB_DATA / "sdf_grid_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f)

    print(f"[sdf] fine {fine_q.shape} -> {fine_path.stat().st_size/1024:.1f} KB, "
          f"coarse {coarse_q.shape} -> {coarse_path.stat().st_size/1024:.1f} KB")


def build_height_grid() -> None:
    # Smoothed (sigma=5 px) raster: matches the `local_height` feature
    # definition used in training (M7, ml/PROGRESO.md: "using the smoothed
    # raster per DATA_CONTRACT's local_height definition choice").
    h = np.load(GEOMETRY_OUT / "height_raster_smooth_s5.npy")
    with open(GEOMETRY_OUT / "height_raster_smooth_s5_meta.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    h_ds = h[::HEIGHT_XY_STRIDE, ::HEIGHT_XY_STRIDE]
    q = _quantize(h_ds, HEIGHT_QUANT_SCALE)
    out_path = WEB_DATA / "height_grid.bin"
    q.tofile(out_path)
    grid_meta = {
        "source": "height_raster_smooth_s5.npy (Gaussian sigma=5 px smoothed, matches ML local_height feature)",
        "quantization": {"dtype": "int16", "scale": HEIGHT_QUANT_SCALE, "unit": "value*scale = metres"},
        "shape_yx": list(q.shape),
        "x0": meta["x0"], "y0": meta["y0"],
        "res": meta["resolution"] * HEIGHT_XY_STRIDE,
        "file": "height_grid.bin",
    }
    with open(WEB_DATA / "height_grid_meta.json", "w", encoding="utf-8") as f:
        json.dump(grid_meta, f)
    print(f"[height] {q.shape} -> {out_path.stat().st_size/1024:.1f} KB")


def main() -> None:
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    frame = load_frame()
    build_buildings_geojson(frame)
    build_sdf_grid()
    build_height_grid()


if __name__ == "__main__":
    main()
