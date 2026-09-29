#!/usr/bin/env python
"""
test_geometry.py -- acceptance checks for the Zona Tec v2 geometry pipeline.
Run after build_geometry.py, checks BOTH scenarios (out/H_best, out/H_osm):

    E:\\PINN\\.venv\\Scripts\\python.exe E:\\PINN\\v2\\geometry\\test_geometry.py

Exits 0 and prints "ALL TESTS PASSED" iff every check in every scenario
passes; otherwise prints failures and exits 1.
"""
import csv
import json
import math
import os
import sys

import numpy as np
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.join(HERE, "out")
sys.path.insert(0, HERE)
import sdf as sdf_mod

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def load_frame(out_dir):
    with open(os.path.join(out_dir, "frame.json")) as f:
        return json.load(f)


def test_frame_consistency(out_dir):
    frame = load_frame(out_dir)
    for key in ("epsg", "origin_easting", "origin_northing", "origin_lon",
                "origin_lat", "H_ref", "H_max", "zoi_half_size_m", "ring_half_size_m"):
        check(f"frame.json has '{key}'", key in frame)
    check("frame.epsg == 32614", frame.get("epsg") == 32614)
    check("H_ref <= H_max", frame["H_ref"] <= frame["H_max"] + 1e-6,
          f"H_ref={frame['H_ref']} H_max={frame['H_max']}")
    check("H_max > 0", frame["H_max"] > 0)
    check("origin_easting is round (multiple of 10 m)", frame["origin_easting"] % 10 == 0)
    check("origin_northing is round (multiple of 10 m)", frame["origin_northing"] % 10 == 0)
    return frame


def test_watertight_stls(out_dir):
    for fname in ["zonatec_base.stl", "zonatec_ring.stl", "zonatec_var1.stl",
                  "zonatec_var2.stl", "zonatec_var3.stl"]:
        path = os.path.join(out_dir, fname)
        if not os.path.exists(path):
            check(f"{fname} exists", False, "file missing")
            continue
        mesh = trimesh.load(path)
        check(f"{fname} no zero-area faces", bool(np.all(mesh.area_faces > 1e-9)),
              f"min face area = {mesh.area_faces.min() if len(mesh.area_faces) else 'n/a'}")
        check(f"{fname} nonzero bounding volume", np.all(mesh.bounds[1] > mesh.bounds[0]))

    # the REAL acceptance check: watertight PER BUILDING, via the multi-solid
    # files (one independent "solid ... endsolid" block per building, so
    # loading never welds vertices across two different buildings). A single
    # combined "buildings" solid is NOT required to be globally watertight
    # (attached OSM row-houses sharing an exact party wall create a
    # non-manifold shared edge once a generic reader welds vertices -- see
    # module docstring history / README).
    for multi_name in ["zonatec_base_multisolid.stl", "zonatec_ring_multisolid.stl",
                        "zonatec_var1_multisolid.stl", "zonatec_var2_multisolid.stl",
                        "zonatec_var3_multisolid.stl"]:
        multi_path = os.path.join(out_dir, multi_name)
        if not os.path.exists(multi_path):
            check(f"{multi_name} exists", False, "file missing")
            continue
        scene = trimesh.load(multi_path)
        geoms = list(scene.geometry.values()) if isinstance(scene, trimesh.Scene) else [scene]
        n_bad = sum(1 for g in geoms if not g.is_watertight)
        check(f"all individual buildings watertight ({multi_name})", n_bad == 0,
              f"{n_bad} of {len(geoms)} not watertight")
        n_neg_vol = sum(1 for g in geoms if g.is_watertight and g.volume <= 0)
        check(f"all watertight buildings have positive volume ({multi_name})", n_neg_vol == 0,
              f"{n_neg_vol} with non-positive volume")


def test_bbox_and_no_building_outside_domain(out_dir):
    frame = load_frame(out_dir)
    half = frame["ring_half_size_m"]
    mesh = trimesh.load(os.path.join(out_dir, "zonatec_base.stl"))
    bmin, bmax = mesh.bounds
    check("base STL ground at z=0", abs(bmin[2]) < 1e-6, f"zmin={bmin[2]}")
    check("base STL bbox within ZOI half-size", max(abs(bmin[0]), abs(bmax[0])) <= half + 1.0
          and max(abs(bmin[1]), abs(bmax[1])) <= half + 1.0,
          f"bounds={mesh.bounds}, ring_half={half}")

    footprint_tolerance_m = 60.0
    ring_path = os.path.join(out_dir, "zonatec_ring.stl")
    if os.path.exists(ring_path):
        rmesh = trimesh.load(ring_path)
        rmin, rmax = rmesh.bounds
        check("ring STL bbox within ring half-size (+footprint tolerance)",
              max(abs(rmin[0]), abs(rmax[0])) <= half + footprint_tolerance_m
              and max(abs(rmin[1]), abs(rmax[1])) <= half + footprint_tolerance_m,
              f"bounds={rmesh.bounds}, ring_half={half}")

    with open(os.path.join(out_dir, "buildings.csv"), encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    outside = [r for r in rows if abs(float(r["centroid_x"])) > half + 1.0
               or abs(float(r["centroid_y"])) > half + 1.0]
    check("no building centroid outside the ring domain", len(outside) == 0,
          f"{len(outside)} outside of {len(rows)}")


def test_domain_csv(out_dir):
    path = os.path.join(out_dir, "domain_16dirs.csv")
    with open(path) as f:
        rows = list(csv.DictReader(f))
    check("domain_16dirs.csv has 16 rows", len(rows) == 16, f"got {len(rows)}")
    thetas = sorted(float(r["theta_deg"]) for r in rows)
    expected = [i * 22.5 for i in range(16)]
    check("domain_16dirs.csv covers all 16 standard sectors",
          all(abs(a - b) < 1e-6 for a, b in zip(thetas, expected)))
    bad_blockage = [r for r in rows if float(r["blockage_ratio"]) > 0.031]
    check("rectangular-domain blockage ratio <= ~3% for all directions", len(bad_blockage) == 0,
          f"{len(bad_blockage)} directions exceed target: "
          f"{[(r['theta_deg'], r['blockage_ratio']) for r in bad_blockage]}")

    circ_path = os.path.join(out_dir, "domain_circular_recommendation.md")
    check("domain_circular_recommendation.md exists", os.path.exists(circ_path))
    if os.path.exists(circ_path):
        text = open(circ_path, encoding="utf-8").read()
        check("circular domain recommendation reports blockage < 3%",
              "OK" in text and "FAILS" not in text.split("target:")[1][:10]
              if "target:" in text else "OK" in text)


def test_roughness_csv(out_dir):
    path = os.path.join(out_dir, "roughness_16sectors.csv")
    with open(path) as f:
        rows = list(csv.DictReader(f))
    check("roughness_16sectors.csv has 16 rows", len(rows) == 16)
    for r in rows:
        z0 = float(r["z0_macdonald"])
        check(f"z0_macdonald > 0 at theta={r['theta_deg']}", z0 > 0)


def test_sdf_module(out_dir):
    ok = sdf_mod._self_test()
    check("sdf.py self-test (box, positive-in-fluid convention)", ok)

    base_path = os.path.join(out_dir, "zonatec_base_multisolid.stl")
    frame = load_frame(out_dir)
    bsdf = sdf_mod.BuildingSDF(base_path)
    high_pt = np.array([[0.0, 0.0, frame["H_max"] + 100.0]])
    sd = bsdf.signed_distance(high_pt)
    check("SDF positive far above tallest building (fluid)", sd[0] > 0, f"sd={sd[0]}")


def test_sdf_grids(out_dir):
    """Nested SDF grid npz files exist, are internally consistent, and their
    trilinear interpolation matches the exact trimesh SDF (via the
    *_multisolid.stl reference -- see sdf.BuildingSDF docstring on why the
    single-solid file is not a reliable ground truth at party walls) at
    random points to within a small multiple of the grid spacing. Grid
    values now come from the EXACT prism-union method (F1 review G4), so
    remaining error is pure trilinear-interpolation discretisation (a couple
    of grid-cells' tolerance around sharp corners/edges), not an algorithmic
    approximation."""
    for vname in ("base", "var1", "var2", "var3"):
        npz_path = os.path.join(out_dir, f"sdf_grid_{vname}.npz")
        base_name = "zonatec_base" if vname == "base" else f"zonatec_{vname}"
        stl_path = os.path.join(out_dir, f"{base_name}_multisolid.stl")
        if not os.path.exists(npz_path):
            check(f"sdf_grid_{vname}.npz exists", False, "file missing")
            continue
        data = np.load(npz_path)
        for key in ("fine_sdf", "fine_x0", "fine_y0", "fine_res_xy", "fine_z",
                    "coarse_sdf", "coarse_x0", "coarse_y0", "coarse_res", "coarse_z"):
            check(f"sdf_grid_{vname}.npz has '{key}'", key in data)
        check(f"sdf_grid_{vname}.npz fine grid is 3D", data["fine_sdf"].ndim == 3)
        check(f"sdf_grid_{vname}.npz fine_z length matches fine_sdf", len(data["fine_z"]) == data["fine_sdf"].shape[0])

        if not os.path.exists(stl_path):
            continue
        frame = load_frame(out_dir)
        rng = np.random.default_rng(42)
        minx, maxx = data["fine_x0"], data["fine_x0"] + (data["fine_sdf"].shape[2] - 1) * float(data["fine_res_xy"])
        miny, maxy = data["fine_y0"], data["fine_y0"] + (data["fine_sdf"].shape[1] - 1) * float(data["fine_res_xy"])
        n = 200
        pts = np.column_stack([
            rng.uniform(minx, maxx, n), rng.uniform(miny, maxy, n),
            rng.uniform(0, min(20.0, 2 * frame["H_max"]), n),
        ])
        bsdf = sdf_mod.BuildingSDF(stl_path)
        exact = bsdf.signed_distance(pts)
        interp = sdf_mod.trilinear_sample(data["fine_sdf"], float(data["fine_x0"]), float(data["fine_y0"]),
                                           float(data["fine_res_xy"]), data["fine_z"], pts)
        err = np.abs(exact - interp)
        res = float(data["fine_res_xy"])
        tol = 1.5 * res  # exact prism-union method (F1 review G4): remaining error
                          # is pure trilinear-interpolation discretisation near
                          # corners/edges, empirically <1 grid spacing typically
                          # (max observed ~0.74 m at res=1 m); 1.5x gives headroom
        frac_ok = np.mean(err <= tol)
        check(f"sdf_grid_{vname}: trilinear interp matches exact SDF within {tol:.1f} m "
              f"for >=95% of {n} random points", frac_ok >= 0.95,
              f"only {frac_ok*100:.0f}% within tol; mean err={err.mean():.2f} m, max err={err.max():.2f} m")


def test_height_provenance(out_dir, scenario):
    path = os.path.join(out_dir, "buildings.csv")
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    check(f"[{scenario}] buildings.csv non-empty", len(rows) > 0)
    sources = {r["height_source"] for r in rows}
    check(f"[{scenario}] no empty height_source values", "" not in sources)
    heights = [float(r["height_m"]) for r in rows]
    check(f"[{scenario}] all heights positive", all(h > 0 for h in heights))


def run_scenario_tests(scenario):
    out_dir = os.path.join(OUT_ROOT, scenario)
    print(f"\n########## SCENARIO: {scenario} ({out_dir}) ##########")
    if not os.path.isdir(out_dir):
        check(f"[{scenario}] output directory exists", False, "missing -- run build_geometry.py first")
        return
    print("=== frame consistency ===")
    test_frame_consistency(out_dir)
    print("=== STL watertightness ===")
    test_watertight_stls(out_dir)
    print("=== bbox / no building outside domain ===")
    test_bbox_and_no_building_outside_domain(out_dir)
    print("=== domain sizing (COST 732 + circular recommendation) ===")
    test_domain_csv(out_dir)
    print("=== roughness ===")
    test_roughness_csv(out_dir)
    print("=== SDF ===")
    test_sdf_module(out_dir)
    print("=== SDF nested grids (ML deliverable) ===")
    test_sdf_grids(out_dir)
    print("=== height provenance ===")
    test_height_provenance(out_dir, scenario)


def main():
    for scenario in ("H_best", "H_osm"):
        run_scenario_tests(scenario)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED:")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
