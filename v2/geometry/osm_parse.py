"""
osm_parse.py -- parse cached Overpass JSON into shapely geometries in UTM 14N.

Handles: nodes, ways (open/closed), relations (multipolygon: outer/inner ring
assembly with dangling-way stitching), tag extraction for buildings.
"""
import json
from collections import defaultdict

import numpy as np
from pyproj import Transformer
from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.ops import linemerge, unary_union, polygonize

EPSG_UTM = 32614
_to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{EPSG_UTM}", always_xy=True)


def load_osm(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    els = d["elements"]
    nodes = {}
    ways = {}
    rels = {}
    for e in els:
        if e["type"] == "node":
            nodes[e["id"]] = e
        elif e["type"] == "way":
            ways[e["id"]] = e
        elif e["type"] == "relation":
            rels[e["id"]] = e
    return nodes, ways, rels


def node_xy(nodes, nid):
    n = nodes[nid]
    x, y = _to_utm.transform(n["lon"], n["lat"])
    return x, y


def way_coords(nodes, way):
    return [node_xy(nodes, nid) for nid in way["nodes"]]


def way_polygon(nodes, way):
    """Return a Polygon if the way is closed & has >=4 coords, else None."""
    coords = way_coords(nodes, way)
    if len(coords) < 4 or coords[0] != coords[-1]:
        return None
    try:
        p = Polygon(coords)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty or p.area <= 0:
            return None
        return p
    except Exception:
        return None


def assemble_multipolygon(nodes, ways, rel):
    """Assemble a relation's outer/inner ways into a (Multi)Polygon via
    linemerge + polygonize (handles multi-way rings)."""
    outer_lines, inner_lines = [], []
    for m in rel["members"]:
        if m["type"] != "way" or m["ref"] not in ways:
            continue
        w = ways[m["ref"]]
        coords = way_coords(nodes, w)
        if len(coords) < 2:
            continue
        role = m.get("role", "outer")
        (outer_lines if role != "inner" else inner_lines).append(LineString(coords))

    def rings_from_lines(lines):
        if not lines:
            return []
        merged = linemerge(lines)
        polys = list(polygonize(merged if merged.geom_type != "LineString" else [merged]))
        return polys

    outers = rings_from_lines(outer_lines)
    inners = rings_from_lines(inner_lines)
    if not outers:
        return None
    result = unary_union(outers)
    if inners:
        holes = unary_union(inners)
        result = result.difference(holes)
    if result.is_empty:
        return None
    if not result.is_valid:
        result = result.buffer(0)
    return result


def extract_buildings(nodes, ways, rels):
    """Return list of dicts: {osm_type, osm_id, tags, geom} for every
    building / building:part way or relation."""
    out = []
    seen_way_ids_in_rel = set()

    for rid, rel in rels.items():
        tags = rel.get("tags", {})
        if "building" not in tags and "building:part" not in tags:
            continue
        geom = assemble_multipolygon(nodes, ways, rel)
        if geom is None or geom.is_empty:
            continue
        out.append({"osm_type": "relation", "osm_id": rid, "tags": tags, "geom": geom})
        for m in rel["members"]:
            if m["type"] == "way":
                seen_way_ids_in_rel.add(m["ref"])

    for wid, way in ways.items():
        tags = way.get("tags", {})
        if "building" not in tags and "building:part" not in tags:
            continue
        if wid in seen_way_ids_in_rel:
            continue  # already counted as part of a multipolygon relation
        geom = way_polygon(nodes, way)
        if geom is None:
            continue
        out.append({"osm_type": "way", "osm_id": wid, "tags": tags, "geom": geom})

    return out


def extract_relation_polygon(nodes, ways, rels, rel_id):
    rel = rels[rel_id]
    return assemble_multipolygon(nodes, ways, rel)
