"""Mesh statistics for a Zona Tec mesh case -> mesh_stats.json (read by the README/report).

* cell count and checkMesh quality summary (log.checkMesh)
* ground-layer coverage per patch (snappyHexMesh layer table)
* vertical resolution in the evaluation zone (|x|,|y| <= eval_half, >= 3 m from any building): for every
  vertical column of cells (same x-y centroid) the ground-up face heights are reconstructed from the cell
  centroids (prismatic columns: top_i = 2 z_i - top_{i-1}); reports first-centroid height, horizontal size
  sqrt(V/dz) and the index of the cell that contains z = 1.75 m (AIJ: must be >= 3)
* snappy wall time and peak RAM (timing.txt / mem_snappy_peak.txt)
Usage: python mesh_stats.py <mesh_case>
"""
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ofio  # noqa: E402

case = Path(sys.argv[1]).resolve()
meta = json.loads((case / "mesh.json").read_text())
out = {"case": case.name, "variant": meta["variant"], "level": meta["level"]["level"]}

cm = (case / "log.checkMesh").read_text(errors="ignore") if (case / "log.checkMesh").exists() else ""
m = re.search(r"^\s*cells:\s+(\d+)", cm, re.M)
out["cells"] = int(m.group(1)) if m else None
for key, pat in {"max_nonortho": r"Mesh non-orthogonality Max:\s*([\d.eE+-]+)",
                 "avg_nonortho": r"Mesh non-orthogonality Max:\s*[\d.eE+-]+\s+average:\s*([\d.eE+-]+)",
                 "max_skewness": r"Max skewness = ([\d.eE+-]+)",
                 "max_aspect": r"Max aspect ratio = ([\d.eE+-]+)"}.items():
    mm = re.search(pat, cm)
    out[key] = float(mm.group(1)) if mm else None
mm = re.search(r"cells:\s*\n?.*?hexahedra:\s+(\d+)", cm, re.S)
out["hexahedra"] = int(mm.group(1)) if mm else None
mm = re.search(r"polyhedra:\s+(\d+)", cm)
out["polyhedra"] = int(mm.group(1)) if mm else None
out["checkMesh_ok"] = "Mesh OK" in cm
fails = re.findall(r"\*\*\*(.*)", cm)
out["checkMesh_failures"] = [f.strip() for f in fails]

sn = (case / "log.snappyHexMesh").read_text(errors="ignore") if (case / "log.snappyHexMesh").exists() else ""
lay = {}
for mm in re.finditer(r"^(ground_zoi)\s+(\d+)\s+([\d.]+)\s+([\d.eE+-]+)\s+([\d.]+)", sn, re.M):
    lay[mm.group(1)] = {"faces": int(mm.group(2)), "avg_layers": float(mm.group(3)),
                        "thickness_m": float(mm.group(4)), "thickness_pct": float(mm.group(5))}
out["layers"] = lay
if lay.get("ground_zoi"):
    out["layer_coverage_avg_layers_over_target"] = lay["ground_zoi"]["avg_layers"] / meta["layers"]["n"]
mm = re.search(r"Finished meshing in = ([\d.]+) s", sn)
out["snappy_internal_s"] = float(mm.group(1)) if mm else None
tt = (case / "timing.txt").read_text() if (case / "timing.txt").exists() else ""
mm = re.findall(r"snappy_wall_s (\d+)", tt)
out["snappy_wall_s"] = int(mm[-1]) if mm else None
pk = (case / "mem_snappy_peak.txt")
if pk.exists():
    v = dict(re.findall(r"(\w+)\s+([\d.]+)", pk.read_text()))
    out["snappy_peak_ws_MB"] = float(v.get("peak_ws_MB", "nan"))
    out["snappy_peak_private_MB"] = float(v.get("peak_private_MB", "nan"))
    out["snappy_min_system_avail_MB"] = float(v.get("min_avail_MB", "nan"))

# ---- vertical resolution in the evaluation zone
t0 = case / "0"
if (t0 / "C").exists() and (t0 / "V").exists() or (t0 / "cellVolume").exists():
    C, _ = ofio.read_field(t0 / "C")
    V, _ = ofio.read_field(t0 / ("V" if (t0 / "V").exists() else "cellVolume"))
    eh = meta["domain"]["eval_half"]
    sel = (np.abs(C[:, 0]) <= eh) & (np.abs(C[:, 1]) <= eh) & (C[:, 2] < 12.0)
    idx = np.where(sel)[0]
    Cs, Vs = C[idx], V[idx]
    if meta["variant"] != "empty":
        import buildings as B
        d = B.exact_sdf(np.c_[Cs[:, 0], Cs[:, 1], np.zeros(len(Cs))], meta["variant"], meta["scenario"])
        keep = d > 3.0
        Cs, Vs = Cs[keep], Vs[keep]
    key = np.round(Cs[:, 0], 2) * 1e5 + np.round(Cs[:, 1], 2)
    order = np.lexsort((Cs[:, 2], key))
    key, Cs, Vs = key[order], Cs[order], Vs[order]
    brk = np.r_[0, np.where(np.diff(key) != 0)[0] + 1, len(key)]
    first_c, hsize, k175, dz1 = [], [], [], []
    for a, b in zip(brk[:-1], brk[1:]):
        z = Cs[a:b, 2]
        if len(z) < 3 or z[0] > 2.5:
            continue
        top = np.zeros(len(z))
        prev = 0.0
        okcol = True
        for i, zc in enumerate(z):
            t = 2 * zc - prev
            if t <= prev:
                okcol = False
                break
            top[i] = t
            prev = t
        if not okcol:
            continue
        i175 = int(np.searchsorted(top, 1.75)) + 1        # 1-based index of the cell containing 1.75 m
        first_c.append(z[0]); dz1.append(top[0]); hsize.append(np.sqrt(Vs[a] / top[0])); k175.append(i175)
    if first_c:
        k175 = np.array(k175)
        out["eval_zone_columns"] = len(first_c)
        out["first_centroid_m"] = {"median": float(np.median(first_c)), "max": float(np.max(first_c))}
        out["first_cell_height_m"] = {"median": float(np.median(dz1)), "p95": float(np.percentile(dz1, 95))}
        out["horizontal_size_m"] = {"median": float(np.median(hsize)), "p95": float(np.percentile(hsize, 95))}
        out["cell_index_containing_1p75m"] = {str(k): int((k175 == k).sum()) for k in np.unique(k175)}
        out["frac_columns_1p75_in_cell_ge3"] = float((k175 >= 3).mean())
(case / "mesh_stats.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
