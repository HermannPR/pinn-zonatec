"""Per-case cost summary from the simpleFoam logs -> prints lines appended to timing.txt and timing.json.
s/iteration = median of ExecutionTime increments over the last 200 iterations of stage 2 (steady state speed)."""
import json
import re
import sys
from pathlib import Path

import numpy as np

case = Path(sys.argv[1]).resolve()
out = {}
tot_it = 0
for stage in ("stage1", "stage2"):
    f = case / f"log.simpleFoam.{stage}"
    if not f.exists():
        continue
    txt = f.read_text(errors="ignore")
    times = [float(x) for x in re.findall(r"^Time = (\d+)", txt, re.M)]
    ex = [float(x) for x in re.findall(r"ExecutionTime = ([\d.]+) s", txt)]
    # ExecutionTime restarts at each restart; use positive increments only
    d = np.diff(ex)
    d = d[d > 0]
    out[stage] = {"iterations_logged": len(times),
                  "s_per_it_median_last200": float(np.median(d[-200:])) if len(d) else None,
                  "s_per_it_mean": float(np.mean(d)) if len(d) else None}
    tot_it += len(times)
m = json.loads((case / "case.json").read_text())
mesh = json.loads((Path(m["mesh_case"]) / "mesh_stats.json").read_text()) if (Path(m["mesh_case"]) / "mesh_stats.json").exists() else {}
out["cells"] = mesh.get("cells")
out["total_iterations_logged"] = tot_it
w = re.findall(r"wallclock_s_last_attempt (\d+)", (case / "timing.txt").read_text()) if (case / "timing.txt").exists() else []
out["wallclock_s_previous_attempts"] = [int(x) for x in w]
if out.get("stage2", {}).get("s_per_it_median_last200") and out["cells"]:
    out["s_per_it_per_Mcell"] = out["stage2"]["s_per_it_median_last200"] / (out["cells"] / 1e6)
(case / "timing.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out))
