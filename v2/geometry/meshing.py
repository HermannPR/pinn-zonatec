"""
meshing.py -- LOD1 extrusion of building footprints to watertight per-building
solids, and ASCII STL export (single named solid, or one named solid per
building).
"""
import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon


def polygon_to_mesh(polygon, height, z0=0.0):
    """Extrude a shapely (multi)polygon from z0 to z0+height. Returns a single
    trimesh.Trimesh (possibly the union of sub-parts for a MultiPolygon)."""
    polys = list(polygon.geoms) if polygon.geom_type == "MultiPolygon" else [polygon]
    meshes = []
    for p in polys:
        if p.is_empty or p.area <= 0:
            continue
        p2 = p if p.exterior.is_ccw else Polygon(list(p.exterior.coords)[::-1],
                                                    [list(i.coords)[::-1] for i in p.interiors])
        try:
            m = trimesh.creation.extrude_polygon(p2, height)
        except Exception:
            # retry with a tiny buffer(0) cleanup if triangulation failed
            p3 = p2.buffer(0)
            if p3.is_empty:
                continue
            m = trimesh.creation.extrude_polygon(p3, height)
        if z0 != 0.0:
            m.apply_translation([0, 0, z0])
        meshes.append(m)
    if not meshes:
        return None
    if len(meshes) == 1:
        return meshes[0]
    return trimesh.util.concatenate(meshes)


def build_all_meshes(records):
    """records: list of dicts with 'geom' (shapely, in ZT-ENU x,y) and
    'height_m'. Returns list of (record, mesh) for those that triangulated
    successfully; failures are reported separately."""
    out, failed = [], []
    for r in records:
        m = polygon_to_mesh(r["geom"], max(r["height_m"], 0.5))
        if m is None or len(m.faces) == 0:
            failed.append(r)
            continue
        out.append((r, m))
    return out, failed


def concatenate_soup(meshes):
    """Concatenate meshes WITHOUT merging coincident vertices across bodies,
    so each building's watertightness (edge/face adjacency by vertex index)
    stays independent even if two buildings touch/share a wall in space."""
    all_v, all_f = [], []
    offset = 0
    for m in meshes:
        all_v.append(m.vertices)
        all_f.append(m.faces + offset)
        offset += len(m.vertices)
    V = np.vstack(all_v)
    F = np.vstack(all_f)
    return trimesh.Trimesh(vertices=V, faces=F, process=False)


def _facet_block(name, vertices, faces):
    lines = [f"solid {name}"]
    v = vertices
    for f in faces:
        p0, p1, p2 = v[f[0]], v[f[1]], v[f[2]]
        n = np.cross(p1 - p0, p2 - p0)
        norm = np.linalg.norm(n)
        n = n / norm if norm > 1e-12 else np.array([0.0, 0.0, 1.0])
        lines.append(f"  facet normal {n[0]:.6e} {n[1]:.6e} {n[2]:.6e}")
        lines.append("    outer loop")
        for p in (p0, p1, p2):
            lines.append(f"      vertex {p[0]:.6e} {p[1]:.6e} {p[2]:.6e}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {name}")
    return "\n".join(lines)


def write_single_solid_stl(mesh, path, solid_name="buildings"):
    text = _facet_block(solid_name, mesh.vertices, mesh.faces)
    with open(path, "w") as f:
        f.write(text + "\n")


def write_multi_solid_stl(named_meshes, path):
    """named_meshes: list of (name, mesh)."""
    blocks = [_facet_block(name, m.vertices, m.faces) for name, m in named_meshes]
    with open(path, "w") as f:
        f.write("\n".join(blocks) + "\n")
