"""Warm start of a direction case from a converged neighbouring direction on the SAME mesh.

internalField of U, p, k, eps|omega, nut are copied cell-by-cell from the source case's latest reconstructed time
(same mesh -> same cell order; checked by cell count) into <case>/0, keeping the new case's boundary conditions.
U is rotated in place about z by the change of flow direction, so the horizontally homogeneous far field is
EXACTLY the new direction's approach flow (the ABL solution does not depend on x,y); only the flow around the
buildings has to re-develop. Scalars (p, k, eps, nut) are copied unchanged.
Usage: python warmstart.py <source_case> <case>
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ofio  # noqa: E402

src, case = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
ms, mc = json.loads((src / "case.json").read_text()), json.loads((case / "case.json").read_text())
if ms["mesh_case"] != mc["mesh_case"]:
    raise SystemExit(f"different meshes: {ms['mesh_case']} vs {mc['mesh_case']}")
if (ms["model"] == "kOmegaSST") != (mc["model"] == "kOmegaSST"):
    raise SystemExit("source/target turbulence variables differ (epsilon vs omega)")
t = ofio.latest_time(src)
if t is None or float(t) == 0:
    raise SystemExit(f"source {src} has no reconstructed solution")
sd = src / t
# flow-direction math angle = 270 deg - theta  ->  rotation alpha = -(theta_new - theta_old)
alpha = -math.radians(mc["theta_deg"] - ms["theta_deg"])
c, s = math.cos(alpha), math.sin(alpha)
# speed scaling (Reynolds independence: U ~ u*, k ~ u*^2, eps ~ u*^3, nut ~ u*)
us_src, us_new = ms["inflow"]["u_star"], mc["inflow"]["u_star"]
f = us_new / us_src


def rot(U):
    U = np.asarray(U, dtype=float)
    out = U.copy()
    out[:, 0] = c * U[:, 0] - s * U[:, 1]
    out[:, 1] = s * U[:, 0] + c * U[:, 1]
    return out * f


T = "omega" if mc["model"] == "kOmegaSST" else "epsilon"
scal = {"U": rot, "p": lambda a: a * f ** 2, "k": lambda a: a * f ** 2, "nut": lambda a: a * f,
        "epsilon": lambda a: a * f ** 3, "omega": lambda a: a * f}
n_expected = None
for q in ["U", "p", "k", T, "nut"]:
    arr, _ = ofio.read_field(sd / q)
    if np.ndim(arr) == 0 or (q == "U" and np.ndim(arr) == 1):
        raise SystemExit(f"{sd / q}: uniform internalField, not a solution")
    n_expected = n_expected or len(arr)
    if len(arr) != n_expected:
        raise SystemExit("cell count mismatch between fields")
    ofio.splice_internal(sd / q, case / "0.orig" / q, case / "0" / q, transform=scal[q])
    print(f"warm start {q}: {len(arr)} cells from {sd}")
print(f"rotation {math.degrees(alpha):+.2f} deg (theta {ms['theta_deg']} -> {mc['theta_deg']}), speed factor {f:.4f}")
