"""Independent verification of an AIJ case (queue contract, E:/PINN/cola/README.md, item 4).

exit 0 only if
  * DONE marker present and no FAILED marker;
  * final initial residuals (p, Ux, Uy/Uz, k, eps/omega) all < 1e-4, OR the U monitors are stable:
    max over monitors of (max-min) of each velocity component over the last 500 iterations < 1 % of U_H
    (U_H = 4.491 m/s; relative to U_H because some monitors sit in the wake where |U| ~ 0);
  * no NaN in the solver logs;
  * expected outputs exist (building: sampleExp/expPoints + sampleLines; empty2d: profiles).
Usage: python verify_aij.py <case_dir>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np

UH = 4.491


def residuals(case: Path) -> dict:
    last = {}
    dirs = sorted((case / "postProcessing" / "residuals").glob("*"), key=lambda p: float(p.name))
    for d in dirs:
        f = d / "solverInfo.dat"
        if not f.exists():
            continue
        hdr = None
        for line in f.read_text().splitlines():
            if line.startswith("#"):
                if "Time" in line:
                    hdr = line.lstrip("#").split()
                continue
            v = line.split()
            if hdr and len(v) == len(hdr):
                row = dict(zip(hdr, v))
                last = {k: row[k] for k in hdr if k.endswith("_initial")}
                last["Time"] = row["Time"]
    return last


def monitors_stable(case: Path) -> tuple[bool, float]:
    rows = []
    for d in sorted((case / "postProcessing" / "monitors").glob("*"), key=lambda p: float(p.name)):
        f = d / "U"
        if f.exists():
            for line in f.read_text().splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                rows.append([float(x) for x in line.replace("(", " ").replace(")", " ").split()])
    if not rows:
        return False, float("nan")
    m = np.array(rows)
    t = m[:, 0]
    sel = t >= t.max() - 500
    if sel.sum() < 100 or t.max() - t.min() < 500:
        return False, float("nan")
    rng = (m[sel, 1:].max(0) - m[sel, 1:].min(0)).max() / UH
    return bool(rng < 0.01), float(rng)


def main(case: Path) -> int:
    ok, msgs = True, []
    meta = json.loads((case / "case.json").read_text())
    if not (case / "DONE").exists() or (case / "FAILED").exists():
        ok = False; msgs.append("DONE marker missing or FAILED present")
    for log in case.glob("log.simpleFoam.*"):
        if re.search(r"\bnan\b", log.read_text(errors="ignore"), re.I):
            ok = False; msgs.append(f"NaN in {log.name}")
    r = residuals(case)
    res_vals = {k: float(v) for k, v in r.items() if k.endswith("_initial") and v not in ("N/A",)}
    res_ok = bool(res_vals) and max(res_vals.values()) < 1e-4
    msgs.append(f"final initial residuals at it {r.get('Time')}: " + json.dumps({k: f'{v:.2e}' for k, v in res_vals.items()}))
    if meta["kind"] == "building":
        stable, rng = monitors_stable(case)
        msgs.append(f"monitor range last 500 it / U_H = {rng:.4f} (stable={stable})")
        if not (res_ok or stable):
            ok = False; msgs.append("not converged: residuals >= 1e-4 and monitors not stable")
        pp = case / "postProcessing"
        if not list(pp.glob("sampleExp/*/expPoints*.csv")):
            ok = False; msgs.append("missing sampleExp output")
        if not list(pp.glob("sampleLines/*/wake*.csv")):
            ok = False; msgs.append("missing sampleLines output")
    else:
        if not res_ok:
            ok = False; msgs.append("residuals >= 1e-4")
        if not list((case / "postProcessing").glob("profiles/*/x000*.csv")):
            ok = False; msgs.append("missing profiles output")
    print("\n".join(msgs))
    print("VERIFY", "OK" if ok else "FAIL", case.name)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
