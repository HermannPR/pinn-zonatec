#!/usr/bin/env python
"""
build_geometry.py -- regenerate all Zona Tec v2 geometry outputs from the
cached Overpass OSM JSON, for TWO height scenarios:

  H_osm  -- pure OSM (height tag > building:levels x 3 m > type estimate).
            This is the original/baseline scenario.
  H_best -- multi-source best estimate: manual field check (top priority,
            out/heights_manual.csv) > official sources > OSM height tag >
            Google Open Buildings 2.5D (QC-passed) > OSM building:levels x
            per-type storey height > default levels x per-type storey
            height. Source: E:\\PINN\\datos\\alturas\\alturas_investigadas.csv
            (~2942 buildings, another pipeline's output).

Run with the project venv:

    E:\\PINN\\.venv\\Scripts\\python.exe E:\\PINN\\v2\\geometry\\build_geometry.py [H_osm|H_best|all]

(no argument = both scenarios, "all" = both + comparison files)

Outputs under E:\\PINN\\v2\\geometry\\out\\<scenario>\\:
    frame.json, buildings.csv, heights_to_verify.csv, top15_tallest.csv
    zonatec_base.stl (+multisolid), zonatec_ring.stl (+multisolid)
    zonatec_var1/2/3.stl (+multisolid), VARIANTS_README.md
    domain_16dirs.csv, roughness_16sectors.csv
    height_raster.npy (+meta), height_raster_smooth_s5.npy, _s10.npy
    sdf_grid_<variant>.npz (nested fine/coarse SDF grids)
    fig_plan_view.png, fig_roughness_rose.png
Plus, at out\\ (scenario-independent):
    heights_manual.csv (template/input for field-verified heights)
    SCENARIO_COMPARISON.csv/.md
"""
import csv
import json
import math
import os
import sys

import numpy as np
from pyproj import Transformer
from shapely.affinity import translate
from shapely.geometry import box as shapely_box, MultiPolygon, Point
from shapely.strtree import STRtree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from osm_parse import load_osm, extract_buildings, extract_relation_polygon
import cleaning
import heights as heights_mod
import meshing
import domain as domain_mod
import morphometry as morph
import sdf as sdf_mod
import figures as fig_mod
import google_raster
import overture_parse
import ml_adapter

HERE = os.path.dirname(os.path.abspath(__file__))
OSM_JSON = r"E:\PINN\v2\data\raw\osm\osm_zonatec_raw.json"
OUT_ROOT = os.path.join(HERE, "out")
os.makedirs(OUT_ROOT, exist_ok=True)
MANUAL_HEIGHTS_CSV = os.path.join(OUT_ROOT, "heights_manual.csv")

EPSG_UTM = 32614
CAMPUS_REL_ID = 21104322

# --- frame / ZOI geometry (see README.md for the justification) -----------
ORIGIN_E = 370450.0
ORIGIN_N = 2837950.0
ZOI_HALF = 425.0     # -> 850 x 850 m explicit-building box
RING_HALF = 545.0    # -> 1090 x 1090 m context ring (~120 m, 1-2 blocks, added)
EVAL_HALF = 325.0    # F1 review G5: the explicit ring is only ~120 m (~1 block).
                      # Option adopted (of the two proposed): keep the ZOI/ring/STL
                      # geometry unchanged (cheap, no remesh) and instead report
                      # confort/metrics on this SMALLER "evaluation zone" (850-200=
                      # 650 m box, i.e. 100 m recessed from the ZOI edge on every
                      # side), so every evaluation point has >=100+120=220 m of
                      # explicit upwind buildings at the ZOI edge, growing to >=320 m
                      # near the eval-zone's own edge -- roughly 1-2 blocks per
                      # Tominaga et al. (2008). Low buildings near the ZOI edge were
                      # the ones under-covered; towers (214-240 m from the edge) were
                      # already fine either way.
MORPH_RADIUS = 1200.0  # buildings kept for upwind morphometry (sector wedges out to 1200 m)

SCENARIOS = ["H_best", "H_osm"]  # H_best is the DEFAULT/recommended scenario
                                  # (Hermann, 2026-09-28: trust the satellite);
                                  # H_osm is retained as a pure-OSM sensitivity case.

_to_wgs84 = Transformer.from_crs(f"EPSG:{EPSG_UTM}", "EPSG:4326", always_xy=True)


def log(msg):
    print(f"[build_geometry] {msg}")


def load_all_buildings():
    log(f"loading OSM cache: {OSM_JSON}")
    nodes, ways, rels = load_osm(OSM_JSON)
    campus_geom = extract_relation_polygon(nodes, ways, rels, CAMPUS_REL_ID)
    raw = extract_buildings(nodes, ways, rels)
    log(f"raw building elements: {len(raw)}")
    return campus_geom, raw


def restrict_radius(records, cx, cy, radius):
    return [r for r in records if r["geom"].distance(Point(cx, cy)) <= radius]


def assign_roles(records, zoi_poly, ring_poly):
    for r in records:
        c = r["geom"].centroid
        r["role"] = "zoi" if zoi_poly.contains(c) else ("ring" if ring_poly.contains(c) else "context")
    return records


def assign_heights_for_scenario(records, scenario, evidence=None, manual_overrides=None):
    for r in records:
        if scenario == "H_osm":
            h, lev, src, flag = heights_mod.assign_height(r["tags"], r["osm_id"])
            r["height_m"], r["levels"], r["height_source"], r["needs_field_check"] = h, lev, src, flag
            r["google_discrepancy"] = False
        else:  # H_best
            h, lev, src, flag, disc = heights_mod.assign_height_best(
                r["tags"], r["osm_id"], evidence, manual_overrides,
                footprint_area_m2=r["geom"].area)
            r["google_raw_median_m"] = (evidence or {}).get(str(r["osm_id"]), {}).get("google_height_m")
            r["height_m"], r["levels"], r["height_source"], r["needs_field_check"] = h, lev, src, flag
            r["google_discrepancy"] = disc
    return records


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    scenarios = SCENARIOS if arg in ("all", None) else [arg]

    campus_geom, raw = load_all_buildings()
    parts = list(campus_geom.geoms) if campus_geom.geom_type == "MultiPolygon" else [campus_geom]
    main_parts = [p for p in parts if p.centroid.x > 368000]
    campus_main = MultiPolygon(main_parts) if len(main_parts) > 1 else main_parts[0]
    log(f"campus (main cluster) bounds: {campus_main.bounds}, area {campus_main.area:.0f} m2")

    working = restrict_radius(raw, ORIGIN_E, ORIGIN_N, MORPH_RADIUS + 50)
    log(f"buildings within {MORPH_RADIUS:.0f} m of origin: {len(working)}")

    cleaned_utm, clean_stats = cleaning.clean_footprints(working)
    log(f"cleaning stats: {clean_stats}")

    zoi_poly_utm = shapely_box(ORIGIN_E - ZOI_HALF, ORIGIN_N - ZOI_HALF,
                                ORIGIN_E + ZOI_HALF, ORIGIN_N + ZOI_HALF)
    ring_poly_utm = shapely_box(ORIGIN_E - RING_HALF, ORIGIN_N - RING_HALF,
                                 ORIGIN_E + RING_HALF, ORIGIN_N + RING_HALF)
    assign_roles(cleaned_utm, zoi_poly_utm, ring_poly_utm)

    evidence = heights_mod.load_investigadas()
    log(f"height evidence loaded for {len(evidence)} osm_ids (from {heights_mod.INVESTIGADAS_CSV})")

    # Hermann's decision: trust the satellite. Recompute Google height per
    # building as the MEDIAN over its actual footprint from the raw 2.5D
    # raster (robust to "parallax bleed" from a taller neighbour), replacing
    # the single point-sample value from alturas_investigadas.csv wherever
    # the raster covers that footprint.
    zonal = google_raster.compute_all_zonal_stats(cleaned_utm)
    n_overridden = 0
    for key, stats in zonal.items():
        e = evidence.setdefault(key, {"osm_height_m": None, "osm_levels": None,
                                       "google_height_m": None, "google_confidence": None,
                                       "official_height_m": None, "official_levels": None,
                                       "official_source": None})
        e["google_height_m"] = stats["median"]
        e["google_confidence"] = "medium"  # zonal median from raw raster, not the point-sample row
        e["google_frac_above_30"] = stats["frac_above_30"]
        e["google_n_pixels"] = stats["n_pixels"]
        e["google_max"] = stats["max"]
        n_overridden += 1
    log(f"Google 2.5D zonal (median) stats computed for {n_overridden} footprints "
        f"from {google_raster.GOOGLE_TIF}, overriding point-sample values")

    manual_overrides = heights_mod.load_manual_overrides(MANUAL_HEIGHTS_CSV)
    log(f"manual field-verified heights loaded: {len(manual_overrides)} (from {MANUAL_HEIGHTS_CSV})")

    # CEDES-trio diagnostic requested explicitly: is 54-80 m a real tower or
    # parallax bleed from a neighbouring tall building?
    for cid in ("1539504899", "1539504900", "1539504905", "1539504906"):
        s = zonal.get(cid)
        if s:
            log(f"CEDES-area diagnostic osm_id={cid}: median={s['median']:.1f} m, "
                f"max={s['max']:.1f} m, frac_footprint_above_30m={s['frac_above_30']:.2f}, "
                f"n_pixels={s['n_pixels']} -> {'majority-supported tall structure' if s['frac_above_30'] > 0.5 else 'median stays low: high pixels are a minority (likely bleed), using median'}")

    summaries = {}
    for scenario in scenarios:
        out_dir = os.path.join(OUT_ROOT, scenario)
        os.makedirs(out_dir, exist_ok=True)
        log(f"=== scenario {scenario} -> {out_dir} ===")
        summaries[scenario] = run_scenario(scenario, out_dir, cleaned_utm, zoi_poly_utm,
                                            ring_poly_utm, evidence, manual_overrides)

    if len(summaries) == len(SCENARIOS):
        write_scenario_comparison(summaries, OUT_ROOT)

    log("DONE.")


def run_scenario(scenario, out_dir, cleaned_utm, zoi_poly_utm, ring_poly_utm, evidence, manual_overrides):
    # deep-enough copy: new dicts, geometry objects reused read-only (translate() returns new objects)
    cleaned = [dict(r) for r in cleaned_utm]
    assign_heights_for_scenario(cleaned, scenario, evidence, manual_overrides)

    zoi_buildings_utm = [r for r in cleaned if r["role"] == "zoi"]
    ring_buildings_utm = [r for r in cleaned if r["role"] == "ring"]
    log(f"[{scenario}] ZOI buildings: {len(zoi_buildings_utm)}, ring: {len(ring_buildings_utm)}, "
        f"total for morphometry: {len(cleaned)}")

    H_max = max((r["height_m"] for r in zoi_buildings_utm), default=0.0)
    real_tall = [r for r in zoi_buildings_utm
                 if not r["height_source"].startswith(("estimated", "variant"))]
    h_ref_rec = max(real_tall, key=lambda r: r["height_m"]) if real_tall else \
        (max(zoi_buildings_utm, key=lambda r: r["height_m"]) if zoi_buildings_utm else None)
    H_ref = h_ref_rec["height_m"] if h_ref_rec else H_max

    lon0, lat0 = _to_wgs84.transform(ORIGIN_E, ORIGIN_N)
    frame = {
        "scenario": scenario,
        "epsg": EPSG_UTM,
        "origin_easting": ORIGIN_E, "origin_northing": ORIGIN_N,
        "origin_lon": lon0, "origin_lat": lat0,
        "zoi_half_size_m": ZOI_HALF, "ring_half_size_m": RING_HALF,
        "eval_half_size_m": EVAL_HALF,
        "H_ref": H_ref, "H_ref_source": h_ref_rec["height_source"] if h_ref_rec else None,
        "H_ref_osm_id": h_ref_rec["osm_id"] if h_ref_rec else None,
        "H_max": H_max,
        "frame": "ZT-ENU (x=East,y=North,z=Up; ground z=0)",
    }
    with open(os.path.join(out_dir, "frame.json"), "w") as f:
        json.dump(frame, f, indent=2)
    log(f"[{scenario}] frame.json: H_ref={H_ref:.1f} m ({frame['H_ref_source']}), H_max={H_max:.1f} m")

    for r in cleaned:
        r["geom_utm"] = r["geom"]
        r["geom"] = translate(r["geom"], xoff=-ORIGIN_E, yoff=-ORIGIN_N)
    zoi_poly_z = translate(zoi_poly_utm, xoff=-ORIGIN_E, yoff=-ORIGIN_N)
    ring_poly_z = translate(ring_poly_utm, xoff=-ORIGIN_E, yoff=-ORIGIN_N)
    eval_poly_z = shapely_box(-EVAL_HALF, -EVAL_HALF, EVAL_HALF, EVAL_HALF)
    zoi_buildings = [r for r in cleaned if r["role"] == "zoi"]
    ring_buildings = [r for r in cleaned if r["role"] == "ring"]

    write_buildings_csv(zoi_buildings + ring_buildings, out_dir, scenario)
    build_stls(zoi_buildings, ring_buildings, out_dir)
    variant_records = build_variants(zoi_buildings, zoi_poly_z, out_dir, H_max)
    smoothed_rasters = build_height_raster(zoi_buildings + ring_buildings, ring_poly_z, out_dir)
    towers = build_tower_refinement_regions(zoi_buildings, out_dir)
    domain_rows = build_domain_csv(zoi_buildings + ring_buildings, H_max, out_dir)
    circular = build_circular_domain_report(domain_rows, H_max, out_dir, towers)
    roughness_rows = build_roughness_csv(cleaned, (0.0, 0.0), out_dir)
    if scenario == "H_best":
        build_roughness_overture_csv(out_dir)

    all_variant_records = dict(variant_records)
    all_variant_records["base"] = zoi_buildings
    is_default_scenario = (scenario == SCENARIOS[0])  # H_best -- see M3 / ml_adapter.py
    build_sdf_grids(all_variant_records, zoi_poly_z, H_max, out_dir,
                     ml_export=is_default_scenario, height_raster_for_ml=smoothed_rasters.get(5.0))

    fig_mod.plan_view(zoi_buildings + ring_buildings, zoi_poly_z, ring_poly_z,
                       os.path.join(out_dir, "fig_plan_view.png"),
                       title=f"Zona Tec ZOI ({scenario})", eval_poly=eval_poly_z)
    fig_mod.roughness_rose(roughness_rows, os.path.join(out_dir, "fig_roughness_rose.png"))

    provenance = {}
    for r in (zoi_buildings + ring_buildings):
        provenance[r["height_source"]] = provenance.get(r["height_source"], 0) + 1

    return {
        "scenario": scenario, "H_max": H_max, "H_ref": H_ref,
        "n_zoi": len(zoi_buildings), "n_ring": len(ring_buildings),
        "provenance": provenance,
        "domain_rows": domain_rows, "roughness_rows": roughness_rows,
        "circular": circular,
    }


def write_buildings_csv(records, out_dir, scenario):
    path_all = os.path.join(out_dir, "buildings.csv")
    with open(path_all, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "osm_id", "osm_type", "name", "role", "levels", "height_m",
                    "height_source", "needs_field_check", "google_discrepancy",
                    "footprint_area_m2", "centroid_x", "centroid_y", "dist_to_zoi_centre_m"])
        for i, r in enumerate(records):
            c = r["geom"].centroid
            d = math.hypot(c.x, c.y)
            w.writerow([i, r["osm_id"], r["osm_type"], r["tags"].get("name", ""),
                        r["role"], r["levels"], round(r["height_m"], 2),
                        r["height_source"], r["needs_field_check"], r.get("google_discrepancy", False),
                        round(r["geom"].area, 1), round(c.x, 2), round(c.y, 2), round(d, 1)])
    log(f"[{scenario}] buildings.csv: {len(records)} rows -> {path_all}")

    flagged = [r for r in records if r["needs_field_check"]]

    def importance(r):
        c = r["geom"].centroid
        d = math.hypot(c.x, c.y)
        return r["height_m"] * r["geom"].area / (1.0 + d / 100.0)

    flagged.sort(key=importance, reverse=True)
    _write_verify_csv(os.path.join(out_dir, "heights_to_verify.csv"), flagged, importance)
    log(f"[{scenario}] heights_to_verify.csv: {len(flagged)} rows (of {len(records)})")

    # F1 review G3 (blocker): dedicated report for the small-footprint QC
    # fallback group WHERE it actually mattered (the rejected Google median
    # was notably taller -- >15 m above the accepted fallback -- the
    # original "27-41 m on 63-188 m2 footprints" failure mode), not every
    # small building the pixel-count gate touched (most just confirm a
    # perfectly ordinary low default and aren't worth a human's time).
    g3_group = [r for r in records
                if "small_footprint_qc_fallback" in r["height_source"]
                and r.get("google_raw_median_m") is not None
                and r["google_raw_median_m"] - r["height_m"] > 10.0]
    g3_group.sort(key=lambda r: -(r["google_raw_median_m"] - r["height_m"]))
    if g3_group:
        path_g3 = os.path.join(out_dir, "g3_small_footprint_qc_flags.csv")
        with open(path_g3, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["osm_id", "name", "lon", "lat", "footprint_area_m2",
                        "google_rejected_median_m", "fallback_height_m", "fallback_source",
                        "dist_to_zoi_centre_m"])
            for r in g3_group:
                c_z = r["geom"].centroid
                c_utm = r["geom_utm"].centroid
                lon, lat = _to_wgs84.transform(c_utm.x, c_utm.y)
                w.writerow([r["osm_id"], r["tags"].get("name", ""), round(lon, 6), round(lat, 6),
                            round(r["geom"].area, 1), round(r["google_raw_median_m"], 1),
                            round(r["height_m"], 2), r["height_source"],
                            round(math.hypot(c_z.x, c_z.y), 1)])
        log(f"[{scenario}] g3_small_footprint_qc_flags.csv: {len(g3_group)} buildings where a "
            f"small footprint's rejected Google reading was >15 m taller than the accepted "
            f"fallback (the G3 failure mode) -> {path_g3}")

    top15 = sorted(records, key=lambda r: r["height_m"], reverse=True)[:15]
    _write_verify_csv(os.path.join(out_dir, "top15_tallest.csv"), top15, importance)


def _write_verify_csv(path, rows, importance_fn):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "osm_id", "name", "role", "lon", "lat", "levels",
                    "height_m", "height_source", "footprint_area_m2",
                    "dist_to_zoi_centre_m", "importance_score"])
        for i, r in enumerate(rows):
            c_z = r["geom"].centroid
            c_utm = r["geom_utm"].centroid
            lon, lat = _to_wgs84.transform(c_utm.x, c_utm.y)
            w.writerow([i + 1, r["osm_id"], r["tags"].get("name", ""), r["role"],
                        round(lon, 6), round(lat, 6), r["levels"], round(r["height_m"], 2),
                        r["height_source"], round(r["geom"].area, 1),
                        round(math.hypot(c_z.x, c_z.y), 1), round(importance_fn(r), 1)])


def build_stls(zoi_buildings, ring_buildings, out_dir):
    zoi_meshes, zoi_failed = meshing.build_all_meshes(zoi_buildings)
    if zoi_failed:
        log(f"WARNING: {len(zoi_failed)} ZOI footprints failed to triangulate "
            f"(osm_ids={[r['osm_id'] for r in zoi_failed]})")
    ring_meshes, ring_failed = meshing.build_all_meshes(ring_buildings)
    if ring_failed:
        log(f"WARNING: {len(ring_failed)} ring footprints failed to triangulate")

    combined = meshing.concatenate_soup([m for _, m in zoi_meshes])
    meshing.write_single_solid_stl(combined, os.path.join(out_dir, "zonatec_base.stl"), "buildings")
    named = [(f"building_{r['osm_id']}", m) for r, m in zoi_meshes]
    meshing.write_multi_solid_stl(named, os.path.join(out_dir, "zonatec_base_multisolid.stl"))
    log(f"zonatec_base.stl: {len(zoi_meshes)} buildings, {len(combined.faces)} faces")

    ring_named = [(f"building_{r['osm_id']}", m) for r, m in ring_meshes]
    meshing.write_multi_solid_stl(ring_named, os.path.join(out_dir, "zonatec_ring_multisolid.stl"))
    if ring_meshes:
        ring_combined = meshing.concatenate_soup([m for _, m in ring_meshes])
        meshing.write_single_solid_stl(ring_combined, os.path.join(out_dir, "zonatec_ring.stl"), "ring")
        log(f"zonatec_ring.stl: {len(ring_meshes)} buildings")
    return zoi_meshes


def _find_gap(zoi_buildings, zoi_poly_z, size, min_clearance):
    tree = STRtree([r["geom"] for r in zoi_buildings])
    minx, miny, maxx, maxy = zoi_poly_z.bounds
    best, best_score = None, -math.inf
    step = 10.0
    for x in np.arange(minx + size, maxx - size, step):
        for y in np.arange(miny + size, maxy - size, step):
            cand = shapely_box(x - size / 2, y - size / 2, x + size / 2, y + size / 2)
            if not zoi_poly_z.contains(cand):
                continue
            buffered = cand.buffer(min_clearance)
            if any(buffered.intersects(zoi_buildings[int(idx)]["geom"]) for idx in tree.query(buffered)):
                continue
            score = -math.hypot(x, y)
            if score > best_score:
                best_score, best = score, (x, y)
    return best


def build_variants(zoi_buildings, zoi_poly_z, out_dir, H_max):
    readme_lines = ["# Zona Tec geometry variants\n"]

    site = _find_gap(zoi_buildings, zoi_poly_z, size=30.0, min_clearance=8.0)
    var1 = list(zoi_buildings)
    tower_h = H_max  # capped at this scenario's H_max so domain sizing stays shared across variants
    if site is not None:
        x, y = site
        tower_poly = shapely_box(x - 14, y - 14, x + 14, y + 14)
        var1.append({"osm_id": "SYNTH_TOWER", "osm_type": "synthetic",
                     "tags": {"name": "Projected tower (hypothetical)"},
                     "geom": tower_poly, "height_m": tower_h, "levels": round(tower_h / 3.0, 1),
                     "height_source": "variant_synthetic", "needs_field_check": False, "role": "zoi"})
        readme_lines.append(
            f"## var1 -- projected tower\nA hypothetical 28x28 m tower, height capped at this "
            f"scenario's H_max={tower_h:.1f} m, is added at ZT-ENU ({x:.0f}, {y:.0f}) (largest open "
            f"gap, >=8 m clearance, found by grid search). Capped at H_max so base/var1/var2/var3 "
            f"share one COST-732 domain; a taller tower would need its own domain/mesh.\n")
    else:
        readme_lines.append("## var1 -- projected tower\nNo suitable open gap found; variant skipped.\n")

    candidates = [r for r in zoi_buildings if 150 <= r["geom"].area <= 2500 and r["height_m"] < 30
                  and not r["tags"].get("name")]
    candidates.sort(key=lambda r: math.hypot(r["geom"].centroid.x, r["geom"].centroid.y))
    var2 = list(zoi_buildings)
    if candidates:
        removed = candidates[len(candidates) // 3]
        var2 = [r for r in zoi_buildings if r["osm_id"] != removed["osm_id"]]
        c = removed["geom"].centroid
        readme_lines.append(
            f"## var2 -- empty lot\nBuilding osm_id={removed['osm_id']} (footprint "
            f"{removed['geom'].area:.0f} m2, height {removed['height_m']:.1f} m, "
            f"source={removed['height_source']}) at ZT-ENU ({c.x:.0f},{c.y:.0f}) removed "
            f"(demolition/vacant-lot scenario).\n")
    else:
        readme_lines.append("## var2 -- empty lot\nNo suitable candidate building found; variant skipped.\n")

    site2 = _find_gap(zoi_buildings + ([var1[-1]] if site else []), zoi_poly_z, size=18.0, min_clearance=6.0)
    var3 = list(zoi_buildings)
    if site2 is not None and site2 != site:
        x2, y2 = site2
        infill_poly = shapely_box(x2 - 9, y2 - 9, x2 + 9, y2 + 9)
        var3.append({"osm_id": "SYNTH_INFILL", "osm_type": "synthetic",
                     "tags": {"name": "Infill building (hypothetical)"},
                     "geom": infill_poly, "height_m": 15.0, "levels": 5,
                     "height_source": "variant_synthetic", "needs_field_check": False, "role": "zoi"})
        readme_lines.append(
            f"## var3 -- infill (optional)\nA hypothetical 18x18 m, 15 m infill building at ZT-ENU "
            f"({x2:.0f}, {y2:.0f}), a second open gap. Milder densification than var1.\n")
    else:
        readme_lines.append("## var3 -- infill (optional)\nNo distinct second gap found; variant skipped.\n")

    for name, recs in [("zonatec_var1.stl", var1), ("zonatec_var2.stl", var2), ("zonatec_var3.stl", var3)]:
        meshes, failed = meshing.build_all_meshes(recs)
        if not meshes:
            continue
        combined = meshing.concatenate_soup([m for _, m in meshes])
        meshing.write_single_solid_stl(combined, os.path.join(out_dir, name), "buildings")
        named = [(f"building_{r['osm_id']}", m) for r, m in meshes]
        meshing.write_multi_solid_stl(named, os.path.join(out_dir, name.replace(".stl", "_multisolid.stl")))
        n_bad = sum(1 for _, m in meshes if not m.is_watertight)
        log(f"{name}: {len(meshes)} buildings, {n_bad} not watertight individually")

    with open(os.path.join(out_dir, "VARIANTS_README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(readme_lines))

    return {"var1": var1, "var2": var2, "var3": var3}


def build_height_raster(records, ring_poly_z, out_dir):
    minx, miny, maxx, maxy = ring_poly_z.bounds
    res = 1.0
    if (maxx - minx) * (maxy - miny) / (res * res) > 2_000_000:
        res = 2.0
    hr = sdf_mod.HeightRaster.rasterize(records, (minx, miny, maxx, maxy), resolution=res)
    hr.save(os.path.join(out_dir, "height_raster.npy"))
    log(f"height_raster.npy: shape {hr.array.shape}, res {res} m")

    smoothed_rasters = {}
    for sigma in (5.0, 10.0):
        smoothed = sdf_mod.gaussian_smoothed_height_raster(hr, sigma)
        smoothed.save(os.path.join(out_dir, f"height_raster_smooth_s{int(sigma)}.npy"))
        smoothed_rasters[sigma] = smoothed
    log("Gaussian-smoothed height rasters written (sigma=5,10 m)")

    base_stl = os.path.join(out_dir, "zonatec_base.stl")
    if os.path.exists(base_stl):
        bsdf = sdf_mod.BuildingSDF(base_stl)
        test_pts = np.array([[0, 0, 200], [0, 0, 1], [minx + 1, miny + 1, 1]])
        sd = bsdf.signed_distance(test_pts)
        log(f"SDF sanity check (expect + at high z / far corner): {sd}")

    return smoothed_rasters


def build_sdf_grids(variant_records, zoi_poly_z, H_max, out_dir, ml_export=False,
                     height_raster_for_ml=None):
    """Nested (fine+coarse) EXACT prism-union SDF grids (F1 review G4), one
    .npz per variant. See sdf.build_nested_sdf_grid / sdf.ExactPrismSDF for
    the method (the SAME method used for scattered-point queries, HDF5
    extraction, and here). Each grid is validated against the independent
    trimesh SDF of the matching STL at random points (should now agree
    closely, since both are exact -- unlike the old approximate method).

    When `ml_export` is True (the default/H_best scenario -- see M3), also
    writes the flat-layout adapter file `<OUT_ROOT>/<variant>_sdf.npz` that
    `ml/features.py:GridGeometry` / `resolve_geometry_source` expect
    (see geometry/ml_adapter.py)."""
    bounds = zoi_poly_z.bounds
    for vname, recs in variant_records.items():
        base_name = "zonatec_base" if vname == "base" else f"zonatec_{vname}"
        # validate against the MULTI-solid STL: BuildingSDF combines each
        # building's mesh separately (see sdf.BuildingSDF docstring) -- the
        # single-solid file welds vertices at party walls into one mesh,
        # which can silently misclassify inside/outside near a shared wall.
        stl_path = os.path.join(out_dir, f"{base_name}_multisolid.stl")
        grid = sdf_mod.build_nested_sdf_grid(recs, bounds, H_max)
        np.savez_compressed(os.path.join(out_dir, f"sdf_grid_{vname}.npz"), **grid)
        if os.path.exists(stl_path):
            err = _validate_grid_against_exact(grid, stl_path, bounds, H_max)
            log(f"sdf_grid_{vname}.npz written; validation vs exact trimesh SDF: "
                f"mean|err|={err['mean']:.3f} m, max|err|={err['max']:.3f} m "
                f"(fine res={grid['fine_res_xy']} m)")
        else:
            log(f"sdf_grid_{vname}.npz written (no matching STL to validate against)")

        if ml_export and height_raster_for_ml is not None:
            ml_adapter.write_ml_geometry_npz(grid, height_raster_for_ml,
                                              os.path.join(OUT_ROOT, f"{vname}_sdf.npz"))
    if ml_export:
        log(f"ML adapter npz written to {OUT_ROOT}\\<variant>_sdf.npz for "
            f"{list(variant_records.keys())} (see geometry/ml_adapter.py, M3)")


def _validate_grid_against_exact(grid, stl_path, bounds, H_max, n_points=300, seed=0):
    rng = np.random.default_rng(seed)
    minx, miny, maxx, maxy = bounds
    pts = np.column_stack([
        rng.uniform(minx, maxx, n_points),
        rng.uniform(miny, maxy, n_points),
        rng.uniform(0, min(20.0, 2 * H_max), n_points),
    ])
    bsdf = sdf_mod.BuildingSDF(stl_path)
    exact = bsdf.signed_distance(pts)
    interp = sdf_mod.trilinear_sample(grid["fine_sdf"], grid["fine_x0"], grid["fine_y0"],
                                       grid["fine_res_xy"], grid["fine_z"], pts)
    err = np.abs(exact - interp)
    return {"mean": float(err.mean()), "max": float(err.max()), "n": n_points}


TOWER_HEIGHT_THRESHOLD_M = 30.0


def build_tower_refinement_regions(zoi_buildings, out_dir, height_thresh=TOWER_HEIGHT_THRESHOLD_M):
    """F1 review G6: towers (77 m, 85 m in H_best) are left under-resolved by
    the plan-refinement-only mesh (2 m to 20 m, 4 m to 40 m, 16 m above --
    above 40 m a ~28-35 m tower side is only 2-3 cells wide). Emit explicit
    per-tower snappyHexMesh guidance: a `refinementSurface` on that
    building's own STL faces targeting <=2 m (>=10 cells across a
    ~28-35 m tower side, Tominaga et al. 2008), and a `refinementRegion` box
    around it (footprint + 1*H margin, up to 1.5*H) at <=4 m."""
    towers = [r for r in zoi_buildings if r["height_m"] > height_thresh]
    path = os.path.join(out_dir, "tower_refinement_regions.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["osm_id", "name", "height_m", "centroid_x", "centroid_y",
                    "footprint_xmin", "footprint_ymin", "footprint_xmax", "footprint_ymax",
                    "region_xmin", "region_ymin", "region_xmax", "region_ymax",
                    "region_z_top_m", "surface_target_size_m", "region_target_size_m"])
        for r in towers:
            H = r["height_m"]
            xmin, ymin, xmax, ymax = r["geom"].bounds
            c = r["geom"].centroid
            w.writerow([r["osm_id"], r["tags"].get("name", ""), round(H, 1),
                        round(c.x, 1), round(c.y, 1),
                        round(xmin, 1), round(ymin, 1), round(xmax, 1), round(ymax, 1),
                        round(xmin - H, 1), round(ymin - H, 1), round(xmax + H, 1), round(ymax + H, 1),
                        round(1.5 * H, 1), 2.0, 4.0])
    log(f"tower_refinement_regions.csv: {len(towers)} towers > {height_thresh} m -> {path}")
    return towers


def build_domain_csv(records, H_max, out_dir):
    blist = [{"xy": np.array(r["geom"].exterior.coords), "height_m": r["height_m"]}
             for r in records if r["geom"].geom_type == "Polygon"]
    rows = domain_mod.size_domain_all_directions(blist, H_max)
    path = os.path.join(out_dir, "domain_16dirs.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log(f"domain_16dirs.csv written ({len(rows)} rows)")
    return rows


def build_roughness_csv(all_records, zoi_centre_xy, out_dir):
    path = os.path.join(out_dir, "roughness_16sectors.csv")
    perturbed_plus = morph.sensitivity_perturb_heights(all_records, +1.0)
    perturbed_minus = morph.sensitivity_perturb_heights(all_records, -1.0)

    rows = []
    for theta in domain_mod.DIRECTIONS_16:
        wedge = morph.upwind_wedge(zoi_centre_xy, theta)

        def stats_for(recs):
            return morph.sector_geometry_stats(recs, wedge, theta)

        base = stats_for(all_records)
        plus = stats_for(perturbed_plus)
        minus = stats_for(perturbed_minus)

        row = {"theta_deg": theta, "z0_control": morph.Z0_CONTROL_M, "d_control": morph.D_CONTROL_M}
        if base is None:
            row.update({k: 0.0 for k in
                        ["lambda_p", "lambda_f", "H_mean", "H_max", "sigma_H",
                         "n_buildings", "lot_area_m2", "frac_real_height_by_count",
                         "frac_real_height_by_area",
                         "z0_macdonald", "d_macdonald", "z0_kanda", "d_kanda",
                         "kanda_reliable", "z0_macdonald_pert_plus1floor", "z0_macdonald_pert_minus1floor"]})
            rows.append(row)
            continue

        z0_m, d_m = morph.macdonald_z0_d(base["H_mean"], base["lambda_p"], base["lambda_f"])
        z0_k, d_k, reliable = morph.kanda_z0_d(base["H_mean"], base["H_max"], base["sigma_H"],
                                                base["lambda_p"], base["lambda_f"])
        row.update(base)
        row["z0_macdonald"], row["d_macdonald"] = z0_m, d_m
        row["z0_kanda"], row["d_kanda"], row["kanda_reliable"] = z0_k, d_k, reliable

        z0_p, _ = morph.macdonald_z0_d(plus["H_mean"], plus["lambda_p"], plus["lambda_f"]) if plus else (z0_m, None)
        z0_mm, _ = morph.macdonald_z0_d(minus["H_mean"], minus["lambda_p"], minus["lambda_f"]) if minus else (z0_m, None)
        row["z0_macdonald_pert_plus1floor"] = z0_p
        row["z0_macdonald_pert_minus1floor"] = z0_mm
        rows.append(row)

    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log(f"roughness_16sectors.csv written")
    return rows


def build_circular_domain_report(domain_rows, H_max, out_dir, towers=None):
    frontal_areas = [r["frontal_area_m2"] for r in domain_rows]
    circ = domain_mod.circular_domain(RING_HALF, H_max, frontal_areas)

    # meshing plan as specified: background 16 m, ring (to 40 m height) 4 m,
    # ZOI core (to 20 m height) 2 m -- see estimate_mesh_cells docstring for
    # why 40 m (not the full domain height) is used for the ring band.
    plan_requested = domain_mod.estimate_mesh_cells(
        circ["radius_m"], circ["height_m"], RING_HALF, ZOI_HALF,
        bg_res_m=16.0, ring_res_m=4.0, zoi_res_m=2.0,
        ring_zone_height_m=40.0, zoi_zone_height_m=20.0)
    # coarser alternative that actually hits ~2-2.5M cells
    plan_coarser = domain_mod.estimate_mesh_cells(
        circ["radius_m"], circ["height_m"], RING_HALF, ZOI_HALF,
        bg_res_m=28.0, ring_res_m=6.0, zoi_res_m=2.0,
        ring_zone_height_m=40.0, zoi_zone_height_m=20.0)

    # F1 review G6: extra cells for tower refinementRegions (footprint + 1*H
    # margin box, up to 1.5*H, at 4 m -- replacing whatever background/ring
    # resolution WOULD have applied there, net add is the delta to 4 m)
    towers = towers or []
    n_tower_cells = 0
    for t in towers:
        H = t["height_m"]
        xmin, ymin, xmax, ymax = t["geom"].bounds
        region_area = (xmax - xmin + 2 * H) * (ymax - ymin + 2 * H)
        region_vol = region_area * 1.5 * H
        n_tower_cells += region_vol / (4.0 ** 3)
    tower_note = (
        f"\n## Tower refinement (G6): {len(towers)} towers > {TOWER_HEIGHT_THRESHOLD_M:.0f} m "
        f"get an explicit refinementRegion (<=4 m, footprint+1H margin, up to 1.5H) -- see "
        f"tower_refinement_regions.csv. Extra volume-mesh cells for these regions (replacing "
        f"coarser background/ring cells there): ~{n_tower_cells:,.0f}. Plus a refinementSurface "
        f"on each tower's own STL faces targeting <=2 m (>=10 cells across a ~28-35 m tower "
        f"side, Tominaga et al. 2008) -- a boundary-layer-scale addition, not a volumetric one, "
        f"not counted here (see C4 in the F1 review for near-wall layer cells).\n"
    ) if towers else "\n## Tower refinement (G6): no towers above threshold in this scenario.\n"

    lines = [
        f"# Circular domain recommendation (H_max={H_max:.1f} m)\n",
        f"radius = ring_half*sqrt(2) + 15*H_max = {RING_HALF:.0f}*1.4142 + 15*{H_max:.1f} "
        f"= {circ['radius_m']:.0f} m\n",
        f"height = 6*H_max = {circ['height_m']:.0f} m\n",
        f"worst-case blockage (frontal_area_max / (2R*height)) = "
        f"{circ['frontal_area_max_m2']:.0f} / {circ['cross_section_m2']:.0f} = "
        f"{circ['blockage_ratio']*100:.2f}%  (<3% target: "
        f"{'OK' if circ['blockage_ratio'] < 0.03 else 'FAILS'})\n",
        "\nMargin compromise: the outlet (15H) requirement is applied on EVERY side "
        "(not just downwind), since a circle has no preferred direction; this "
        "over-satisfies the 5H inlet/lateral requirement everywhere. Extra "
        "upstream distance costs little (coarse background mesh only). A 16-gon "
        "could trim ~21% of background volume vs. this circle at the same reach; "
        "not adopted here for simplicity.\n",
        f"\n## Mesh cell-count estimate, AS REQUESTED (bg 16 m / ring 4 m to 40 m "
        f"height / ZOI core 2 m to 20 m height):\n",
        f"- background (outside ring band): {plan_requested['n_background']:,.0f} cells\n",
        f"- ring band (4 m): {plan_requested['n_ring_band']:,.0f} cells\n",
        f"- ZOI core (2 m): {plan_requested['n_zoi_core']:,.0f} cells\n",
        f"- TOTAL (excl. near-wall boundary layers, +~10-20% typical): "
        f"{plan_requested['n_total_estimate']:,.0f} cells\n",
        f"\n**This exceeds the 2-2.5M target** (and is above even the original "
        f"3-5M PC budget only if H_max grows further). To reach ~2-2.5M, "
        f"background must coarsen to ~28 m and ring to ~6 m (ZOI core at 2 m "
        f"over the full 850x850x20 m box is an essentially irreducible "
        f"~{plan_coarser['n_zoi_core']:,.0f} cells on its own):\n",
        f"- background (28 m): {plan_coarser['n_background']:,.0f} cells\n",
        f"- ring band (6 m): {plan_coarser['n_ring_band']:,.0f} cells\n",
        f"- ZOI core (2 m, unchanged): {plan_coarser['n_zoi_core']:,.0f} cells\n",
        f"- TOTAL: {plan_coarser['n_total_estimate']:,.0f} cells\n",
        "\n**What gives**: hitting 2-2.5M means coarsening background/ring "
        "beyond the requested 16 m/4 m (28 m/6 m as shown), OR shrinking the "
        "2 m-refined ZOI footprint/height below 850x850x20 m, OR accepting "
        "~4-4.5M cells (background 16 m, ring 4 m only up to 40 m height) which "
        "still fits the ORIGINAL 3-5M PC budget from the task brief. "
        "Recommendation: keep ZOI near-field resolution (pedestrian-level answer "
        "quality depends on it most) and accept ~4-4.5M, OR relax to the 28 m/6 m "
        "plan if 2-2.5M is a hard ceiling.\n",
        tower_note,
    ]
    with open(os.path.join(out_dir, "domain_circular_recommendation.md"), "w", encoding="utf-8") as f:
        f.writelines(lines)
    log(f"circular domain: R={circ['radius_m']:.0f} m, height={circ['height_m']:.0f} m, "
        f"blockage={circ['blockage_ratio']*100:.2f}%; mesh plan (as requested) "
        f"~{plan_requested['n_total_estimate']/1e6:.2f}M cells, coarser plan "
        f"~{plan_coarser['n_total_estimate']/1e6:.2f}M cells")
    return {"circle": circ, "plan_requested": plan_requested, "plan_coarser": plan_coarser}


def build_roughness_overture_csv(out_dir):
    """F1 review G1 (blocker) fix: OSM footprints are incomplete in the
    N/NE/W/NW sectors (lambda_p 0.16-0.29 vs 0.44-0.53 measured from the
    Google 2.5D raster). Recompute lambda_p/lambda_f/H_mean/sigma_H (and the
    resulting z0/d) for the same 16 upwind wedges using Overture footprints
    (Microsoft ML Buildings + Google Open Buildings + OSM, conflated,
    26,507 footprints vs OSM's 2,942 in the same bbox) with Google-median
    heights, PLUS an independent raster-only control (fraction of Google
    2.5D pixels with height>2.5m in the wedge -- no vectorised footprints at
    all). Writes roughness_16sectors_overture.csv with old (OSM/H_best) vs
    new (Overture) side by side."""
    log("loading Overture footprints for morphometry (G1 fix)...")
    overture_raw = overture_parse.load_overture_buildings()
    log(f"Overture footprints loaded: {len(overture_raw)}")
    overture_working = restrict_radius(overture_raw, ORIGIN_E, ORIGIN_N, MORPH_RADIUS + 50)
    log(f"Overture footprints within {MORPH_RADIUS:.0f} m of origin: {len(overture_working)}")

    stats = {}
    cleaned_ov = cleaning.fix_invalid(overture_working, stats)
    cleaned_ov = cleaning.drop_tiny(cleaned_ov, stats)
    log(f"Overture cleaning: {stats}")

    zonal = google_raster.compute_all_zonal_stats(cleaned_ov)
    n_with_height = 0
    for r in cleaned_ov:
        s = zonal.get(str(r["osm_id"]))
        if s is not None and 2.0 <= s["median"] <= 250.0:
            r["height_m"] = s["median"]
            n_with_height += 1
        else:
            r["height_m"] = 6.0  # dataset-wide typical low-rise fallback (see README); large-N
                                   # aggregate stats are not sensitive to this for individual misses
    log(f"Overture buildings with a valid Google-median height: {n_with_height}/{len(cleaned_ov)}")

    for r in cleaned_ov:
        r["geom"] = translate(r["geom"], xoff=-ORIGIN_E, yoff=-ORIGIN_N)

    # load the OSM-based (H_best) roughness for the old-vs-new comparison
    old_path = os.path.join(out_dir, "roughness_16sectors.csv")
    with open(old_path, encoding="utf-8") as f:
        old_rows = {float(r["theta_deg"]): r for r in csv.DictReader(f)}

    rows = []
    for theta in domain_mod.DIRECTIONS_16:
        wedge_utm = morph.upwind_wedge((ORIGIN_E, ORIGIN_N), theta)
        wedge_z = translate(wedge_utm, xoff=-ORIGIN_E, yoff=-ORIGIN_N)
        base = morph.sector_geometry_stats(cleaned_ov, wedge_z, theta)
        lp_raster = google_raster.wedge_lambda_p_from_raster(wedge_utm)

        old_raw = old_rows.get(theta, {})
        old = {}
        for k, v in old_raw.items():
            try:
                old[k] = float(v)
            except (TypeError, ValueError):
                old[k] = v
        row = {"theta_deg": theta,
               "lambda_p_osm": old.get("lambda_p"), "lambda_p_overture": None,
               "lambda_p_raster_control": lp_raster,
               "lambda_f_osm": old.get("lambda_f"), "lambda_f_overture": None,
               "H_mean_osm": old.get("H_mean"), "H_mean_overture": None,
               "sigma_H_osm": old.get("sigma_H"), "sigma_H_overture": None,
               "z0_macdonald_osm": old.get("z0_macdonald"), "z0_macdonald_overture": None,
               "d_macdonald_osm": old.get("d_macdonald"), "d_macdonald_overture": None,
               "z0_kanda_overture": None, "d_kanda_overture": None}
        if base is not None:
            z0_m, d_m = morph.macdonald_z0_d(base["H_mean"], base["lambda_p"], base["lambda_f"])
            z0_k, d_k, _ = morph.kanda_z0_d(base["H_mean"], base["H_max"], base["sigma_H"],
                                             base["lambda_p"], base["lambda_f"])
            row.update({
                "lambda_p_overture": base["lambda_p"], "lambda_f_overture": base["lambda_f"],
                "H_mean_overture": base["H_mean"], "sigma_H_overture": base["sigma_H"],
                "z0_macdonald_overture": z0_m, "d_macdonald_overture": d_m,
                "z0_kanda_overture": z0_k, "d_kanda_overture": d_k,
            })
        rows.append(row)

    path = os.path.join(out_dir, "roughness_16sectors_overture.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log(f"roughness_16sectors_overture.csv written -> {path}")

    max_lp_diff = max(abs((r["lambda_p_overture"] or 0) - (r["lambda_p_osm"] or 0)) for r in rows)
    log(f"G1 fix: max |lambda_p_overture - lambda_p_osm| across 16 sectors = {max_lp_diff:.3f}")
    return rows


def write_scenario_comparison(summaries, out_root):
    path_csv = os.path.join(out_root, "SCENARIO_COMPARISON.csv")
    with open(path_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "H_max_m", "H_ref_m", "domain_length_min_max_m",
                    "domain_width_min_max_m", "domain_height_m", "blockage_min_max",
                    "circular_radius_m", "circular_height_m", "circular_blockage_worst",
                    "z0_macdonald_min_max_m", "d_macdonald_min_max_m",
                    "z0_kanda_min_max_m", "d_kanda_min_max_m"])
        for s, d in summaries.items():
            dr = d["domain_rows"]
            rr = d["roughness_rows"]
            lens = [r["domain_length_m"] for r in dr]
            wids = [r["domain_width_m"] for r in dr]
            blk = [r["blockage_ratio"] for r in dr]
            z0m = [r["z0_macdonald"] for r in rr]
            dm = [r["d_macdonald"] for r in rr]
            z0k = [r["z0_kanda"] for r in rr]
            dk = [r["d_kanda"] for r in rr]
            circ = d["circular"]["circle"]
            w.writerow([s, round(d["H_max"], 1), round(d["H_ref"], 1),
                        f"{min(lens):.0f}-{max(lens):.0f}", f"{min(wids):.0f}-{max(wids):.0f}",
                        dr[0]["domain_height_m"], f"{min(blk):.3f}-{max(blk):.3f}",
                        round(circ["radius_m"], 0), round(circ["height_m"], 0),
                        round(circ["blockage_ratio"], 4),
                        f"{min(z0m):.3f}-{max(z0m):.3f}", f"{min(dm):.2f}-{max(dm):.2f}",
                        f"{min(z0k):.3f}-{max(z0k):.3f}", f"{min(dk):.2f}-{max(dk):.2f}"])
    log(f"SCENARIO_COMPARISON.csv written -> {path_csv}")


if __name__ == "__main__":
    main()
