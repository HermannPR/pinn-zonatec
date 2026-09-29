"""Building geometry for a Zona Tec variant, read from the geometry agent's multisolid STLs.

Footprints are recovered exactly from each LOD1 prism's bottom cap (union of its z=0 triangles), so the SDF used by
the extractor is the canonical `sdf.ExactPrismSDF` formula on exactly the geometry that was meshed.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import shapely
import trimesh
from shapely.ops import unary_union

from zt_common import GEOM

VARIANTS = ("base", "var1", "var2", "var3", "empty")


def stl_paths(variant: str, scenario: str = "H_best") -> dict:
    d = GEOM / scenario
    if variant == "empty":
        return {}
    return {"bld_zoi": d / f"zonatec_{variant}_multisolid.stl", "bld_ring": d / "zonatec_ring_multisolid.stl"}


def _solids(path: Path):
    s = trimesh.load(path)
    if isinstance(s, trimesh.Scene):
        return [(k, g) for k, g in s.geometry.items() if len(g.faces)]
    return [(Path(path).stem, s)]


@lru_cache(maxsize=8)
def load_records(variant: str, scenario: str = "H_best") -> tuple:
    """tuple of dicts: name, group (bld_zoi|bld_ring), geom (shapely Polygon, ZT-ENU), height_m, mesh"""
    recs = []
    for group, p in stl_paths(variant, scenario).items():
        for name, m in _solids(p):
            v, f = m.vertices, m.faces
            bot = np.all(np.abs(v[f][:, :, 2]) < 1e-6, axis=1)
            tris = [shapely.Polygon(v[t][:, :2]) for t in f[bot]]
            poly = unary_union([t.buffer(0) for t in tris if t.area > 1e-9])
            if poly.geom_type != "Polygon":
                poly = max(poly.geoms, key=lambda g: g.area) if hasattr(poly, "geoms") else poly
            recs.append({"name": name, "group": group, "geom": poly, "height_m": float(v[:, 2].max()), "mesh": m})
    return tuple(recs)


def write_snappy_stls(variant: str, out_dir: Path, scenario: str = "H_best", sink: float = 1.0) -> dict:
    """One single-solid ASCII STL per group, bottom caps sunk to z = -sink so that no building face is coplanar
    with the domain ground (avoids ambiguous intersections in snappyHexMesh)."""
    out = {}
    for group, p in stl_paths(variant, scenario).items():
        meshes = []
        for name, m in _solids(p):
            m = m.copy()
            v = m.vertices.copy()
            v[np.abs(v[:, 2]) < 1e-6, 2] = -sink
            m.vertices = v
            meshes.append(m)
        allm = trimesh.util.concatenate(meshes)
        txt = trimesh.exchange.stl.export_stl_ascii(allm)
        txt = txt.replace("solid ", f"solid {group}", 1).split("\n")
        # normalise the solid names
        txt[0] = f"solid {group}"
        for i in range(len(txt) - 1, -1, -1):
            if txt[i].startswith("endsolid"):
                txt[i] = f"endsolid {group}"
                break
        (Path(out_dir) / f"{group}.stl").write_text("\n".join(txt), newline="\n")
        out[group] = {"n_buildings": len(meshes), "n_tri": int(len(allm.faces)),
                      "bounds": allm.bounds.tolist()}
    return out


def towers(variant: str, scenario: str = "H_best", h_min: float = 30.0) -> list[dict]:
    """Refinement regions for tall buildings (review G6): footprint bbox + 1 H margin, up to 1.5 H."""
    out = []
    for r in load_records(variant, scenario):
        h = r["height_m"]
        if h <= h_min:
            continue
        x0, y0, x1, y1 = r["geom"].bounds
        out.append({"name": r["name"].replace("building_", "tower_"), "h": h, "fp": (x0, y0, x1, y1),
                    "min": (x0 - h, y0 - h, -1.0), "max": (x1 + h, y1 + h, 1.5 * h)})
    return out


def exact_sdf(points: np.ndarray, variant: str, scenario: str = "H_best", chunk: int = 200000) -> np.ndarray:
    """Vectorised exact LOD1 prism-union SDF (positive in the fluid), identical formula to
    geometry/sdf.py (_polygon_planar_sdf/_prism_sdf_value/_combine_prism = sdf.ExactPrismSDF), but evaluated
    building-by-building over all points with a lower-bound prune, so millions of points are feasible."""
    import sdf as S
    recs = load_records(variant, scenario)
    pts = np.asarray(points, dtype=float)
    out = np.full(len(pts), np.inf)
    if not recs:
        return np.full(len(pts), 1e6)
    for i0 in range(0, len(pts), chunk):
        P = pts[i0:i0 + chunk]
        acc = np.full(len(P), np.inf)
        # order buildings by distance of their bbox to the chunk centre (tightens the prune early)
        for r in recs:
            g, h = r["geom"], r["height_m"]
            x0, y0, x1, y1 = g.bounds
            dx = np.maximum(np.maximum(x0 - P[:, 0], P[:, 0] - x1), 0.0)
            dy = np.maximum(np.maximum(y0 - P[:, 1], P[:, 1] - y1), 0.0)
            lb = np.sqrt(dx ** 2 + dy ** 2 + np.maximum(0.0, P[:, 2] - h) ** 2)
            # candidates: lower bound can beat current |acc| (or point may be inside: dx=dy=0)
            cand = np.where((lb < np.abs(acc)) | ((dx == 0) & (dy == 0)))[0]
            if len(cand) == 0:
                continue
            d2, inside = S._polygon_planar_sdf(g, P[cand, 0], P[cand, 1])
            val = S._prism_sdf_value(d2, inside, np.full(len(cand), h), P[cand, 2])
            acc[cand] = S._combine_prism(acc[cand], val)
        out[i0:i0 + chunk] = acc
    out[~np.isfinite(out)] = 1e6
    return out
