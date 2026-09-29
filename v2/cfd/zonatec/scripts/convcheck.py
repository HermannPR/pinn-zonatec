"""Operational convergence criterion for a Zona Tec direction case (review F1 C7; PLAN F2).

CONVERGED  <=>  no NaN  AND  mass balance |sum(phi)| / inflow < 1e-4 (last sample)  AND
               [ (A) all final initial residuals (p, Ux, Uy, Uz, k, eps|omega) < 1e-4
                 OR
                 (B) >= 500 second-order iterations AND every monitor point (10 at z = 1.75 m + 2 above the
                     centre) has max-min of each velocity component over the last 500 iterations < 1 % of U_H
                     (absolute, relative to the inflow speed at H_ref -- in wakes |U| ~ 0 so a relative criterion
                     would never be met) AND max initial residual < 1e-3 (plateau, not divergence) ]
Usage: python convcheck.py <case> [--quiet] [--json out.json]; exit 0 if converged, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

RES_TOL = 1e-4
PLATEAU_RES_MAX = 1e-3
PROBE_TOL = 0.01
WINDOW = 500
MASS_TOL = 1e-4


def _dat_rows(files):
    """merge time-series written in several restart directories; later restarts overwrite earlier times"""
    rows, hdr = {}, None
    for f in files:
        for line in f.read_text(errors="ignore").splitlines():
            if line.startswith("#"):
                h = line.lstrip("#").split()
                if h and h[0] == "Time":
                    hdr = h
                continue
            v = line.replace("(", " ").replace(")", " ").split()
            if not v:
                continue
            try:
                t = float(v[0])
            except ValueError:
                continue
            rows[t] = v
    return hdr, [rows[t] for t in sorted(rows)]


def _dirs(case: Path, fo: str):
    d = case / "postProcessing" / fo
    return sorted([p for p in d.glob("*") if p.is_dir()], key=lambda p: float(p.name)) if d.exists() else []


def residuals(case: Path):
    hdr, rows = _dat_rows([p / "solverInfo.dat" for p in _dirs(case, "residuals") if (p / "solverInfo.dat").exists()])
    if not rows:
        return None, None
    cols = [i for i, h in enumerate(hdr) if h.endswith("_initial")]
    names = [hdr[i].replace("_initial", "") for i in cols]
    t = np.array([float(r[0]) for r in rows])
    R = np.array([[float(r[i]) if r[i] not in ("N/A",) else np.nan for i in cols] for r in rows])
    return t, dict(zip(names, R.T))


def probes(case: Path):
    hdr, rows = _dat_rows([p / "U" for p in _dirs(case, "monitors") if (p / "U").exists()])
    if not rows:
        return None, None
    t = np.array([float(r[0]) for r in rows])
    M = np.array([[float(x) for x in r[1:]] for r in rows])
    return t, M


def mass(case: Path):
    """net boundary mass flux / inflow at the last common sample of the per-patch flux_<patch> function objects
    (walls carry no flux; all open patches are the 32 lateral segments + top)"""
    series = {}
    pp = case / "postProcessing"
    for d in sorted(pp.glob("flux_*")) if pp.exists() else []:
        hdr, rows = _dat_rows([f for p in _dirs(case, d.name) for f in p.glob("*.dat")])
        if rows:
            series[d.name] = {float(r[0]): float(r[1]) for r in rows}
    if not series:
        return None
    common = set.intersection(*[set(s) for s in series.values()])
    if not common:
        return None
    t = max(common)
    vals = np.array([s[t] for s in series.values()])
    inflow = -vals[vals < 0].sum()
    net = vals.sum()
    return {"time": t, "net": float(net), "inflow": float(inflow), "n_patches": len(vals),
            "rel": float(abs(net) / inflow) if inflow > 0 else float("nan")}


def check(case: Path) -> dict:
    meta = json.loads((case / "case.json").read_text())
    UH = meta["U_H"]
    stage1 = int(meta.get("stage1", 0))
    rep = {"case": meta["case_id"], "U_H": UH}
    t, R = residuals(case)
    nan = False
    if t is None:
        rep.update(converged=False, reason="no residual data")
        return rep
    last = {k: float(v[-1]) for k, v in R.items()}
    nan |= any(not math.isfinite(v) for k, v in last.items() if k != "Uz" or True)
    rep["iteration"] = float(t[-1])
    rep["second_order_iterations"] = float(t[-1] - stage1)
    rep["final_initial_residuals"] = last
    finite = [v for v in last.values() if math.isfinite(v)]
    rmax = max(finite) if finite else float("nan")
    res_ok = bool(finite) and rmax < RES_TOL
    # residual plateau diagnostic: max residual averaged over last 100 its vs 400 its earlier
    Rm = np.nanmax(np.vstack(list(R.values())), axis=0)
    if len(Rm) >= WINDOW:
        a, b = np.exp(np.mean(np.log(Rm[-100:]))), np.exp(np.mean(np.log(Rm[-WINDOW:-WINDOW + 100])))
        rep["residual_ratio_last100_vs_500ago"] = float(a / b)
    tp, M = probes(case)
    stable, rng = False, float("nan")
    if tp is not None and len(tp):
        nan |= not np.all(np.isfinite(M[-min(len(M), WINDOW):]))
        sel = tp >= tp[-1] - WINDOW
        enough = (tp[-1] - max(tp[0], stage1)) >= WINDOW and sel.sum() >= 100
        if sel.sum() > 1:
            rngs = (M[sel].max(0) - M[sel].min(0)) / UH
            rng = float(np.nanmax(rngs))
            rep["probe_range_per_probe"] = [float(np.max(rngs[i:i + 3])) for i in range(0, len(rngs), 3)]
        stable = bool(enough and rng < PROBE_TOL)
    rep["probe_max_range_over_UH_last500"] = rng
    mb = mass(case)
    rep["mass_balance"] = mb
    mass_ok = mb is not None and mb["rel"] < MASS_TOL
    plateau_ok = stable and rmax < PLATEAU_RES_MAX
    rep["criterion_A_residuals"] = res_ok
    rep["criterion_B_plateau_probes"] = plateau_ok
    rep["mass_ok"] = mass_ok
    rep["nan"] = nan
    rep["converged"] = bool((not nan) and mass_ok and (res_ok or plateau_ok))
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    rep = check(Path(a.case))
    if a.json:
        Path(a.json).write_text(json.dumps(rep, indent=2))
    if a.quiet:
        print(f"convcheck it={rep.get('iteration')} res_max={max(rep.get('final_initial_residuals', {0: 0}).values()):.2e} "
              f"probe_range={rep.get('probe_max_range_over_UH_last500')} mass={rep.get('mass_balance')} -> "
              f"{'CONVERGED' if rep['converged'] else 'not converged'}")
    else:
        print(json.dumps(rep, indent=2))
    sys.exit(0 if rep["converged"] else 1)


if __name__ == "__main__":
    main()
