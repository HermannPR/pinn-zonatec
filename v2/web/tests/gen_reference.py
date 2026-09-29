"""Generate reference vectors (Python/torch/numpy ground truth) for the
Node test harness (test_model.mjs, test_features.mjs, test_climate.mjs) to
compare the JS ports against. Run from E:\\PINN\\v2 with the project venv:

    E:\\PINN\\.venv\\Scripts\\python.exe web\\tests\\gen_reference.py

Writes JSON fixtures under web/tests/fixtures/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

V2_ROOT = Path(r"E:\PINN\v2")
sys.path.insert(0, str(V2_ROOT))
sys.path.insert(0, str(V2_ROOT / "web" / "build"))

from ml.export import predict_from_json  # noqa: E402
from common import GEOMETRY_OUT  # noqa: E402

FIXTURES = Path(r"E:\PINN\v2\web\tests\fixtures")
WEB_DATA = Path(r"E:\PINN\v2\web\public\data")

# Must match web/build/build_geometry_assets.py exactly.
FINE_XY_STRIDE = 4
COARSE_XY_STRIDE = 2
COARSE_Z_STRIDE = 2
HEIGHT_XY_STRIDE = 2
SDF_QUANT_SCALE = 0.01
HEIGHT_QUANT_SCALE = 0.01


def gen_model_vectors(n: int = 100, seed: int = 42) -> None:
    with open(WEB_DATA / "model.json", "r", encoding="utf-8") as f:
        model_obj = json.load(f)
    h_ref = model_obj["nondim"]["h_ref"]

    rng = np.random.default_rng(seed)
    xyz = rng.uniform(-3 * h_ref, 3 * h_ref, size=(n, 3)).astype(np.float64)
    xyz[:, 2] = np.abs(xyz[:, 2])
    theta = rng.uniform(0, 360, size=n).astype(np.float64)
    sdf = rng.uniform(-20, 100, size=n).astype(np.float64)
    height = rng.uniform(0, 90, size=n).astype(np.float64)

    out = predict_from_json(model_obj, xyz, theta, sdf, height)
    cases = []
    for i in range(n):
        cases.append({
            "x": xyz[i, 0], "y": xyz[i, 1], "z": xyz[i, 2], "theta_deg": theta[i],
            "sdf": sdf[i], "height": height[i],
            "expected": {k: float(v[i]) for k, v in out.items()},
        })
    with open(FIXTURES / "model_vectors.json", "w", encoding="utf-8") as f:
        json.dump({"n": n, "cases": cases}, f)
    print(f"[model] wrote {n} cases")


def _trilinear_nonuniform_z_np(vol, x0, y0, res_xy, z_levels, x, y, z):
    nz, ny, nx = vol.shape
    fx = (x - x0) / res_xy
    fy = (y - y0) / res_xy
    ix0 = int(np.clip(np.floor(fx), 0, nx - 2))
    iy0 = int(np.clip(np.floor(fy), 0, ny - 2))
    iz0 = int(np.clip(np.searchsorted(z_levels, z, side="right") - 1, 0, nz - 2))
    tx = float(np.clip(fx - ix0, 0.0, 1.0))
    ty = float(np.clip(fy - iy0, 0.0, 1.0))
    z0v, z1v = z_levels[iz0], z_levels[iz0 + 1]
    tz = float(np.clip((z - z0v) / max(z1v - z0v, 1e-6), 0.0, 1.0))

    def g(iz, iy, ix):
        return float(vol[iz, iy, ix])

    c000, c001 = g(iz0, iy0, ix0), g(iz0, iy0, ix0 + 1)
    c010, c011 = g(iz0, iy0 + 1, ix0), g(iz0, iy0 + 1, ix0 + 1)
    c100, c101 = g(iz0 + 1, iy0, ix0), g(iz0 + 1, iy0, ix0 + 1)
    c110, c111 = g(iz0 + 1, iy0 + 1, ix0), g(iz0 + 1, iy0 + 1, ix0 + 1)
    c00 = c000 * (1 - tx) + c001 * tx
    c01 = c010 * (1 - tx) + c011 * tx
    c10 = c100 * (1 - tx) + c101 * tx
    c11 = c110 * (1 - tx) + c111 * tx
    c0 = c00 * (1 - ty) + c01 * ty
    c1 = c10 * (1 - ty) + c11 * ty
    return c0 * (1 - tz) + c1 * tz


def _bilinear_uniform_np(raster, x0, y0, res, x, y):
    ny, nx = raster.shape
    fx = float(np.clip((x - x0) / res, 0.0, nx - 1.0))
    fy = float(np.clip((y - y0) / res, 0.0, ny - 1.0))
    ix0 = int(np.clip(np.floor(fx), 0, nx - 2))
    iy0 = int(np.clip(np.floor(fy), 0, ny - 2))
    tx, ty = fx - ix0, fy - iy0
    c00, c01 = float(raster[iy0, ix0]), float(raster[iy0, ix0 + 1])
    c10, c11 = float(raster[iy0 + 1, ix0]), float(raster[iy0 + 1, ix0 + 1])
    c0 = c00 * (1 - tx) + c01 * tx
    c1 = c10 * (1 - tx) + c11 * tx
    return c0 * (1 - ty) + c1 * ty


def gen_feature_vectors(n: int = 60, seed: int = 7) -> None:
    d = np.load(GEOMETRY_OUT / "sdf_grid_base.npz")

    # Full-resolution (training-time) arrays, for the "downsampling error
    # vs. real training grid" report.
    fine_full = d["fine_sdf"]
    fine_full_meta = (float(d["fine_x0"]), float(d["fine_y0"]), float(d["fine_res_xy"]), d["fine_z"].astype(np.float64))
    coarse_full = d["coarse_sdf"]
    coarse_full_meta = (float(d["coarse_x0"]), float(d["coarse_y0"]), float(d["coarse_res"]), d["coarse_z"].astype(np.float64))

    # Downsampled (pre-quantization) arrays -- exactly what
    # build_geometry_assets.py quantizes into the web's .bin files.
    fine_ds = fine_full[:, ::FINE_XY_STRIDE, ::FINE_XY_STRIDE]
    fine_ds_meta = (fine_full_meta[0], fine_full_meta[1], fine_full_meta[2] * FINE_XY_STRIDE, fine_full_meta[3])
    coarse_ds = coarse_full[::COARSE_Z_STRIDE, ::COARSE_XY_STRIDE, ::COARSE_XY_STRIDE]
    coarse_ds_meta = (coarse_full_meta[0], coarse_full_meta[1], coarse_full_meta[2] * COARSE_XY_STRIDE, coarse_full_meta[3][::COARSE_Z_STRIDE])

    height_full = np.load(GEOMETRY_OUT / "height_raster_smooth_s5.npy")
    with open(GEOMETRY_OUT / "height_raster_smooth_s5_meta.json") as f:
        hmeta = json.load(f)
    height_ds = height_full[::HEIGHT_XY_STRIDE, ::HEIGHT_XY_STRIDE]
    height_ds_meta = (hmeta["x0"], hmeta["y0"], hmeta["resolution"] * HEIGHT_XY_STRIDE)

    rng = np.random.default_rng(seed)
    half = 300.0  # stay within both grids' coverage (eval zone is 325 half)
    xs = rng.uniform(-half, half, size=n)
    ys = rng.uniform(-half, half, size=n)
    zs = rng.uniform(0.0, 170.0, size=n)

    fine_top_ds = fine_ds_meta[3][-1]
    fine_top_full = fine_full_meta[3][-1]

    cases = []
    for x, y, z in zip(xs, ys, zs):
        # "expected" = what the WEB (downsampled, pre-quantization) grid
        # gives -- this is what the JS interpolation must reproduce (up to
        # int16 quantization, scale 0.01 m).
        if z <= fine_top_ds:
            sdf_ds = _trilinear_nonuniform_z_np(fine_ds, *fine_ds_meta, x, y, min(z, fine_top_ds))
        else:
            sdf_ds = _trilinear_nonuniform_z_np(coarse_ds, *coarse_ds_meta, x, y, z)
        height_ds_val = _bilinear_uniform_np(height_ds, *height_ds_meta, x, y)

        # "reference_full_res" = what the ORIGINAL, full-resolution training
        # grid gives -- for reporting the downsampling approximation error
        # (not required to match to 1e-5, just documented).
        if z <= fine_top_full:
            sdf_full = _trilinear_nonuniform_z_np(fine_full, *fine_full_meta, x, y, min(z, fine_top_full))
        else:
            sdf_full = _trilinear_nonuniform_z_np(coarse_full, *coarse_full_meta, x, y, z)
        height_full_val = _bilinear_uniform_np(height_full, hmeta["x0"], hmeta["y0"], hmeta["resolution"], x, y)

        cases.append({
            "x": float(x), "y": float(y), "z": float(z),
            "expected_web_grid": {"sdf": sdf_ds, "height": height_ds_val},
            "reference_full_res_grid": {"sdf": sdf_full, "height": height_full_val},
        })

    with open(FIXTURES / "feature_vectors.json", "w", encoding="utf-8") as f:
        json.dump({"n": n, "quant_scale": SDF_QUANT_SCALE, "cases": cases}, f)
    print(f"[features] wrote {n} cases")


def gen_transfer_vectors() -> None:
    sys.path.insert(0, str(V2_ROOT))
    from climate import transfer as tr  # noqa: E402

    with open(WEB_DATA / "climate.json", "r", encoding="utf-8") as f:
        climate_obj = json.load(f)
    H_REF = 87.75  # geometry/out/H_best/frame.json

    rough = tr.load_roughness_table()
    cases = []
    for sector in climate_obj["sectors"]:
        theta = sector["theta_deg"]
        row = rough.loc[theta]
        inflow = tr.inflow_for_sector(theta, U10=1.0, roughness_row=row, z0_method="macdonald")
        u_h_over_u10 = float(tr.U_H_over_U10(inflow, H_REF))
        cases.append({"theta_deg": theta, "expected_u_h_over_u10": u_h_over_u10})
    with open(FIXTURES / "transfer_vectors.json", "w", encoding="utf-8") as f:
        json.dump({"h_ref": H_REF, "cases": cases}, f)
    print(f"[transfer] wrote {len(cases)} sector cases")


def gen_climate_vectors() -> None:
    sys.path.insert(0, str(V2_ROOT))
    from climate import windclimate as wc  # noqa: E402
    import pandas as pd

    wr = pd.read_csv(V2_ROOT / "climate" / "windrose_16.csv")

    rng = np.random.default_rng(3)
    k_cases = {
        "K_ones": [1.0] * 16,
        "K_random_1": list(np.round(rng.uniform(0.3, 2.2, size=16), 4)),
        "K_random_2": list(np.round(rng.uniform(0.5, 1.5, size=16), 4)),
    }

    out_cases = []
    for name, K in k_cases.items():
        K_arr = np.array(K)
        res5 = wc.annual_exceedance(wr, K_arr, wc.NEN8100_COMFORT_THRESHOLD_MS, method="weibull")
        res15 = wc.annual_exceedance(wr, K_arr, wc.NEN8100_DANGER_THRESHOLD_MS, method="weibull")
        cls = wc.nen8100_comfort_class(res5["annual_probability"])
        danger_cls = wc.nen8100_danger_class(res15["annual_probability"])

        # Lawson: use K itself as a stand-in GEM ratio for this cross-check
        # (gust_equivalent_mean is tested on its own below).
        lawson = {"comfort": {}, "danger": {}}
        for label, thr in wc.LAWSON_LDDC_COMFORT_THRESHOLDS_MS.items():
            r = wc.annual_exceedance(wr, K_arr, thr, method="weibull")
            lawson["comfort"][label] = {"p_exceed": r["annual_probability"], "passes": bool(r["annual_probability"] < wc.LAWSON_LDDC_COMFORT_EXCEEDANCE_LIMIT)}
        for label, thr in wc.LAWSON_LDDC_DANGER_THRESHOLDS_MS.items():
            r = wc.annual_exceedance(wr, K_arr, thr, method="weibull")
            lawson["danger"][label] = {"p_exceed": r["annual_probability"]}

        out_cases.append({
            "name": name, "K": K,
            "p_gt_5": res5["annual_probability"], "p_gt_15": res15["annual_probability"],
            "nen8100_class": cls, "nen8100_danger_class": danger_cls,
            "lawson": lawson,
        })

    # gust_equivalent_mean cross-check (a few scalar cases)
    gem_cases = []
    for u_local, k_local in [(3.0, 0.5), (1.0, 2.0), (0.1, 0.01), (5.0, 0.0)]:
        gem = float(wc.gust_equivalent_mean(u_local, k_local))
        gem_cases.append({"u_local": u_local, "k_local": k_local, "expected_gem": gem})

    with open(FIXTURES / "climate_vectors.json", "w", encoding="utf-8") as f:
        json.dump({"cases": out_cases, "gem_cases": gem_cases}, f)
    print(f"[climate] wrote {len(out_cases)} K-vector cases + {len(gem_cases)} GEM cases")


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    gen_model_vectors()
    gen_feature_vectors()
    gen_climate_vectors()
    gen_transfer_vectors()


if __name__ == "__main__":
    main()
