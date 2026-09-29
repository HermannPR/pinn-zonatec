"""Independent verification of a Zona Tec MESH job (queue contract item 4). exit 0 only if
  * DONE present, no FAILED, no RAM-guard trip;
  * checkMesh ran and reports no hard error (negative/zero volumes or areas, wrong orientation, open cells);
    'highly skew faces' / high aspect ratio are soft warnings (reported, typical of snapped + layered meshes);
  * mesh_stats.json exists; for fine/medium/coarse: >= 90 % of evaluation-zone columns have z = 1.75 m in the
    3rd or higher cell from the ground (AIJ guideline, Tominaga et al. 2008);
  * layer coverage and snappy peak RAM are printed (soft).
Usage: python verify_mesh.py <mesh_case>"""
import json
import sys
from pathlib import Path

case = Path(sys.argv[1])
ok, msg = True, []
if not (case / "DONE").exists() or (case / "FAILED").exists():
    ok = False; msg.append("DONE missing or FAILED present")
if (case / "mem_guard_tripped.txt").exists():
    ok = False; msg.append("RAM guard tripped: " + (case / "mem_guard_tripped.txt").read_text())
cm = (case / "log.checkMesh").read_text(errors="ignore") if (case / "log.checkMesh").exists() else ""
if "cells:" not in cm:
    ok = False; msg.append("checkMesh log missing")
hard = ["negative", "incorrectly oriented", "Zero or negative", "open cells", "Wrong", "illegal"]
for line in cm.splitlines():
    if line.strip().startswith("***") and any(h.lower() in line.lower() for h in hard):
        ok = False; msg.append("checkMesh hard failure: " + line.strip())
st = json.loads((case / "mesh_stats.json").read_text()) if (case / "mesh_stats.json").exists() else None
if st is None:
    ok = False; msg.append("mesh_stats.json missing")
else:
    msg.append(f"cells {st.get('cells')}, checkMesh OK={st.get('checkMesh_ok')} failures={st.get('checkMesh_failures')}")
    msg.append(f"max non-ortho {st.get('max_nonortho')}, max skewness {st.get('max_skewness')}, layers {st.get('layers')}")
    msg.append(f"snappy wall {st.get('snappy_wall_s')} s, peak WS {st.get('snappy_peak_ws_MB')} MB, "
               f"min system avail {st.get('snappy_min_system_avail_MB')} MB")
    msg.append(f"1.75 m cell index distribution {st.get('cell_index_containing_1p75m')}, first centroid "
               f"{st.get('first_centroid_m')}, horizontal size {st.get('horizontal_size_m')}")
    if st.get("level") != "xcoarse":
        f = st.get("frac_columns_1p75_in_cell_ge3")
        if f is None or f < 0.90:
            ok = False; msg.append(f"pedestrian-level criterion failed: fraction of columns with 1.75 m in cell >= 3 = {f}")
print("\n".join(msg))
print("VERIFY", "OK" if ok else "FAIL", case.name)
sys.exit(0 if ok else 1)
