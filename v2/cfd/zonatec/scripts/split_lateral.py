"""Split the O-grid 'lateral' patch of a background mesh into N_SEG angular segments (faceSets seg00..segNN)
for createPatch. Segment k holds the faces whose centre angle (ccw from +x, i.e. of the outward normal)
lies in [k, k+1) * 360/N_SEG degrees. Usage: python split_lateral.py <case>"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ofio  # noqa: E402
from zt_common import N_SEG  # noqa: E402

case = Path(sys.argv[1])
mesh = case / "constant" / "polyMesh"
bnd = ofio.read_boundary(mesh)
lat = bnd["lateral"]
pts = ofio.read_points(mesh)
off, lab = ofio.read_faces(mesh)
faces = np.arange(lat["startFace"], lat["startFace"] + lat["nFaces"])
cen, area = ofio.face_centres_normals(pts, off, lab, faces)
ang = np.degrees(np.arctan2(cen[:, 1], cen[:, 0])) % 360.0
seg = np.floor(ang / (360.0 / N_SEG)).astype(int) % N_SEG
# outward-normal sanity check
nrm = area / np.linalg.norm(area, axis=1, keepdims=True)
radial = cen[:, :2] / np.linalg.norm(cen[:, :2], axis=1, keepdims=True)
assert np.all((nrm[:, :2] * radial).sum(1) > 0.95), "lateral face normals not radial/outward"
for k in range(N_SEG):
    ofio.write_faceset(mesh / "sets" / f"seg{k:02d}", f"seg{k:02d}", faces[seg == k])
counts = np.bincount(seg, minlength=N_SEG)
print(f"lateral faces {len(faces)} -> {N_SEG} segments, faces per segment min {counts.min()} max {counts.max()}")
