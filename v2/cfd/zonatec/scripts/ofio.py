"""Minimal OpenFOAM file I/O (ascii + binary, label=32, scalar=64) for the Zona Tec pipeline.

Only what the pipeline needs: read the internalField of vol fields, read polyMesh points/faces/owner/boundary,
write faceSets, and splice a new internalField into a field file (warm start). No external dependencies
beyond numpy. Tested against OpenFOAM v2306 (ESI) output (see tests in __main__).
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

LABEL = np.int32
SCALAR = np.float64
NCOMP = {"scalar": 1, "vector": 3, "symmTensor": 6, "tensor": 9, "label": 1}


def _header_end(buf: bytes) -> int:
    """index just after the closing brace of the FoamFile header"""
    i = buf.find(b"FoamFile")
    if i < 0:
        return 0
    j = buf.find(b"}", i)
    return j + 1


def header_format(buf: bytes) -> str:
    m = re.search(rb"format\s+(\w+)\s*;", buf[: _header_end(buf) + 1])
    return m.group(1).decode() if m else "ascii"


def _read_list_at(buf: bytes, pos: int, ncomp: int, dtype, fmt: str):
    """Read a List starting at pos (pointing at the count or 'N{...}'). Returns (array, newpos)."""
    m = re.compile(rb"\s*(\d+)\s*([({])").match(buf, pos)
    if not m:
        raise ValueError(f"no list at {pos}: {buf[pos:pos+60]!r}")
    n = int(m.group(1))
    p = m.end()
    if m.group(2) == b"{":                                   # uniform list N{value}
        q = buf.index(b"}", p)
        val = np.array(buf[p:q].replace(b"(", b" ").replace(b")", b" ").split(), dtype=dtype)
        return np.tile(val, (n, 1)).squeeze() if ncomp > 1 else np.full(n, val[0], dtype=dtype), q + 1
    if fmt == "binary":
        nbytes = n * ncomp * np.dtype(dtype).itemsize
        arr = np.frombuffer(buf, dtype=dtype, count=n * ncomp, offset=p).copy()
        q = p + nbytes
        if buf[q:q + 1] != b")":
            raise ValueError(f"binary list not closed by ')' at {q}")
        return (arr.reshape(n, ncomp) if ncomp > 1 else arr), q + 1
    # ascii: find matching close paren at depth 0
    depth, q = 1, p
    L = len(buf)
    while q < L:
        c = buf[q]
        if c == 40:
            depth += 1
        elif c == 41:
            depth -= 1
            if depth == 0:
                break
        q += 1
    body = buf[p:q].replace(b"(", b" ").replace(b")", b" ")
    arr = np.array(body.split(), dtype=dtype) if n else np.zeros(0, dtype=dtype)
    return (arr.reshape(n, ncomp) if ncomp > 1 else arr), q + 1


def read_mesh_list(path: Path, ncomp: int = 1, dtype=LABEL) -> np.ndarray:
    buf = Path(path).read_bytes()
    fmt = header_format(buf)
    pos = _header_end(buf)
    # skip comments
    pos = _skip_comments(buf, pos)
    arr, _ = _read_list_at(buf, pos, ncomp, dtype, fmt)
    return arr


def _skip_comments(buf: bytes, pos: int) -> int:
    while True:
        m = re.compile(rb"\s*(//[^\n]*\n|/\*.*?\*/)", re.S).match(buf, pos)
        if not m:
            return pos
        pos = m.end()


def read_points(mesh: Path) -> np.ndarray:
    return read_mesh_list(Path(mesh) / "points", 3, SCALAR)


def read_owner(mesh: Path) -> np.ndarray:
    return read_mesh_list(Path(mesh) / "owner", 1, LABEL)


def read_faces(mesh: Path):
    """returns (offsets, labels) of a faceCompactList (or converts an ascii faceList)"""
    path = Path(mesh) / "faces"
    buf = path.read_bytes()
    fmt = header_format(buf)
    cls = re.search(rb"class\s+(\w+)\s*;", buf[: _header_end(buf) + 1]).group(1).decode()
    pos = _skip_comments(buf, _header_end(buf))
    if cls == "faceCompactList":
        off, pos = _read_list_at(buf, pos, 1, LABEL, fmt)
        pos = _skip_comments(buf, pos)
        lab, _ = _read_list_at(buf, pos, 1, LABEL, fmt)
        return off.astype(np.int64), lab
    # ascii faceList: N ( 4(a b c d) ... )
    m = re.compile(rb"\s*(\d+)\s*\(").match(buf, pos)
    n = int(m.group(1))
    body = buf[m.end():]
    items = re.findall(rb"(\d+)\(([^)]*)\)", body)[:n]
    sizes = np.array([int(a) for a, _ in items], dtype=np.int64)
    off = np.concatenate([[0], np.cumsum(sizes)])
    lab = np.array(b" ".join(b for _, b in items).split(), dtype=LABEL)
    return off, lab


def read_boundary(mesh: Path) -> dict:
    """patch name -> dict(type, nFaces, startFace)"""
    txt = (Path(mesh) / "boundary").read_text(errors="ignore")
    txt = re.sub(r"//.*", "", txt)
    txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)
    body = txt[txt.index("FoamFile"):]
    body = body[body.index("}") + 1:]
    out = {}
    for m in re.finditer(r"([A-Za-z_][\w.\-]*)\s*\{([^{}]*)\}", body):
        name, blk = m.group(1), m.group(2)
        d = dict(re.findall(r"(\w+)\s+([^;]+);", blk))
        if "nFaces" in d:
            out[name] = {"type": d.get("type", "patch"), "nFaces": int(d["nFaces"]), "startFace": int(d["startFace"])}
    return out


def face_centres_normals(points, off, lab, faces: np.ndarray):
    """approximate face centres (vertex mean) and area vectors (triangle fan about the centre) for selected faces"""
    faces = np.asarray(faces, dtype=np.int64)
    starts, ends = off[faces], off[faces + 1]
    sizes = ends - starts
    cen = np.zeros((len(faces), 3))
    area = np.zeros((len(faces), 3))
    for s in np.unique(sizes):
        sel = np.where(sizes == s)[0]
        idx = starts[sel][:, None] + np.arange(s)[None, :]
        pts = points[lab[idx]]                      # (m, s, 3)
        c = pts.mean(1)
        a = np.zeros((len(sel), 3))
        for k in range(s):
            p0, p1 = pts[:, k], pts[:, (k + 1) % s]
            a += 0.5 * np.cross(p0 - c, p1 - c)
        cen[sel], area[sel] = c, a
    return cen, area


def read_field(path: Path):
    """returns (internalField array or scalar/vector uniform value, ncomp). Handles uniform / nonuniform, ascii/binary."""
    buf = Path(path).read_bytes()
    fmt = header_format(buf)
    cls = re.search(rb"class\s+(\w+)\s*;", buf[: _header_end(buf) + 1]).group(1).decode()
    kind = "vector" if "Vector" in cls else ("scalar" if "Scalar" in cls else "tensor")
    ncomp = NCOMP[kind]
    i = buf.index(b"internalField", _header_end(buf))
    m = re.compile(rb"internalField\s+(uniform|nonuniform)\s*").match(buf, i)
    if m.group(1) == b"uniform":
        q = buf.index(b";", m.end())
        val = np.array(buf[m.end():q].replace(b"(", b" ").replace(b")", b" ").split(), dtype=SCALAR)
        return val if ncomp > 1 else float(val[0]), ncomp
    m2 = re.compile(rb"List<\w+>\s*").match(buf, m.end())
    arr, _ = _read_list_at(buf, m2.end(), ncomp, SCALAR, fmt)
    return arr, ncomp


def splice_internal(src_field: Path, template: Path, out: Path, transform=None):
    """Write `out` = template file (its header + boundaryField) with the internalField taken from `src_field`
    (optionally transformed by `transform(array)->array`). Output is written in the template's header format
    rewritten to binary. Boundary 'value' entries in the template must be uniform (not $internalField)."""
    arr, ncomp = read_field(src_field)
    if transform is not None:
        arr = transform(arr)
    tbuf = Path(template).read_bytes()
    hend = _header_end(tbuf)
    head = re.sub(rb"format\s+\w+\s*;", b"format      binary;", tbuf[:hend])
    rest = tbuf[hend:]
    i = rest.index(b"internalField")
    j = rest.index(b";", i)
    # a template internalField is always 'uniform <value>;' (short), so the first ';' closes it
    typ = b"vector" if ncomp == 3 else b"scalar"
    n = arr.shape[0]
    data = np.ascontiguousarray(arr, dtype=SCALAR).tobytes()
    new_int = b"internalField   nonuniform List<" + typ + b">\n" + str(n).encode() + b"\n(" + data + b")\n;"
    Path(out).write_bytes(head + rest[:i] + new_int + rest[j + 1:])


def write_faceset(path: Path, name: str, labels):
    labels = np.asarray(labels, dtype=np.int64)
    txt = ["FoamFile", "{", "    version     2.0;", "    format      ascii;", "    class       faceSet;",
           f"    location    \"constant/polyMesh/sets\";", f"    object      {name};", "}", "",
           f"{len(labels)}", "("] + [str(v) for v in labels] + [")", ""]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(txt), newline="\n")


def latest_time(case: Path, root: str = ".") -> str | None:
    d = Path(case) / root
    ts = []
    for p in d.iterdir() if d.exists() else []:
        if p.is_dir():
            try:
                v = float(p.name)
            except ValueError:
                continue
            ts.append((v, p.name))
    if not ts:
        return None
    return max(ts)[1]
