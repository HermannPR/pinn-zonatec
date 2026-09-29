"""
cleaning.py -- footprint cleaning for LOD1 extrusion / snappyHexMesh friendliness.

Steps (in order), each counted and reported:
  1. fix invalid polygons (buffer(0))
  2. drop tiny footprints (< MIN_AREA_M2)
  3. building:part vs building resolution (parts take precedence over the
     portion of the parent footprint they cover)
  4. merge overlapping/duplicate same-category footprints
  5. simplify short edges (Douglas-Peucker, tolerance ~0.25 m so that no
     surviving edge segment is spuriously < ~0.5 m)
"""
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

MIN_AREA_M2 = 15.0
SIMPLIFY_TOL_M = 0.25


def _as_polygons(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    return []


def fix_invalid(records, stats):
    n_fixed = 0
    out = []
    for r in records:
        g = r["geom"]
        if g is None or g.is_empty:
            continue
        if not g.is_valid:
            g = g.buffer(0)
            n_fixed += 1
        if g.is_empty:
            continue
        r = dict(r, geom=g)
        out.append(r)
    stats["n_invalid_fixed"] = n_fixed
    return out


def drop_tiny(records, stats, min_area=MIN_AREA_M2):
    kept, dropped = [], 0
    for r in records:
        # for multipolygon, drop tiny sub-parts, keep the rest
        parts = [p for p in _as_polygons(r["geom"]) if p.area >= min_area]
        if not parts:
            dropped += 1
            continue
        g = parts[0] if len(parts) == 1 else MultiPolygon(parts)
        kept.append(dict(r, geom=g))
    stats["n_dropped_tiny"] = dropped
    return kept


def resolve_parts_vs_buildings(records, stats):
    """building:part footprints take precedence; subtract their footprint
    from any parent 'building' footprint they overlap so we don't double
    up volume when both are extruded independently."""
    parts = [r for r in records if "building:part" in r["tags"]]
    buildings = [r for r in records if "building:part" not in r["tags"]]
    if not parts:
        stats["n_parts_resolved"] = 0
        return records

    n_resolved = 0
    part_union = unary_union([p["geom"] for p in parts]) if parts else None
    new_buildings = []
    for b in buildings:
        g = b["geom"]
        if part_union is not None and g.intersects(part_union):
            inter_area = g.intersection(part_union).area
            if inter_area / max(g.area, 1e-9) > 0.5:
                # building is (mostly) represented by its parts -> drop parent
                n_resolved += 1
                continue
            elif inter_area > 0:
                newg = g.difference(part_union)
                if not newg.is_empty and newg.area >= MIN_AREA_M2:
                    b = dict(b, geom=newg)
                    n_resolved += 1
        new_buildings.append(b)
    stats["n_parts_resolved"] = n_resolved
    return parts + new_buildings


def merge_overlaps(records, stats, iou_thresh=0.5):
    """Merge pairs of footprints (typically duplicate digitisations) whose
    intersection area exceeds `iou_thresh` * min(area). Uses simple spatial
    index via shapely STRtree."""
    from shapely.strtree import STRtree
    import numpy as np

    geoms = [r["geom"] for r in records]
    tree = STRtree(geoms)
    n = len(records)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i, g in enumerate(geoms):
        cand_idx = tree.query(g)
        for j in cand_idx:
            j = int(j)
            if j <= i:
                continue
            g2 = geoms[j]
            if not g.intersects(g2):
                continue
            inter = g.intersection(g2).area
            if inter <= 0:
                continue
            if inter / max(min(g.area, g2.area), 1e-9) > iou_thresh:
                union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    n_merged_groups = sum(1 for v in groups.values() if len(v) > 1)
    out = []
    for root, idxs in groups.items():
        if len(idxs) == 1:
            out.append(records[idxs[0]])
            continue
        merged_geom = unary_union([records[k]["geom"] for k in idxs])
        merged_geom = merged_geom.buffer(0)
        # keep the record with max reported height/levels as representative tags
        rep = max(
            (records[k] for k in idxs),
            key=lambda r: (
                _height_hint(r["tags"])
            ),
        )
        rec = dict(rep, geom=merged_geom)
        rec["_merged_from"] = [records[k]["osm_id"] for k in idxs]
        out.append(rec)
    stats["n_overlap_groups_merged"] = n_merged_groups
    return out


def _height_hint(tags):
    try:
        if "height" in tags:
            return float(str(tags["height"]).split()[0])
    except Exception:
        pass
    try:
        if "building:levels" in tags:
            return float(tags["building:levels"]) * 3.0
    except Exception:
        pass
    return 0.0


def simplify_edges(records, stats, tol=SIMPLIFY_TOL_M):
    n_changed = 0
    out = []
    for r in records:
        g = r["geom"]
        g2 = g.simplify(tol, preserve_topology=True)
        if g2.is_empty or g2.area < MIN_AREA_M2:
            g2 = g
        if not g2.equals(g):
            n_changed += 1
        out.append(dict(r, geom=g2))
    stats["n_simplified"] = n_changed
    return out


def clean_footprints(records):
    stats = {}
    stats["n_input"] = len(records)
    r = fix_invalid(records, stats)
    r = drop_tiny(r, stats)
    r = resolve_parts_vs_buildings(r, stats)
    r = merge_overlaps(r, stats)
    r = simplify_edges(r, stats)
    stats["n_output"] = len(r)
    return r, stats
