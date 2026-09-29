"""Horizontal-homogeneity test at full scale (review F1 C1.2/C3; PLAN F2) for an EMPTY-domain Zona Tec case.

Vertical profiles (one sample per cell, OpenFOAM 'midPoint' sets) along the wind axis: inlet (R-20 m), 1500 m,
771 m (ring corner), 545 m (ring edge) upwind, centre, 771 and 1500 m downwind. For 2 <= z <= 100 m reports
  * max |U_h/U_RH - 1| and max |k/k_RH - 1| vs the imposed Richards & Hoxey profile at the same (cell-centre) heights,
  * max |U_h(station)/U_h(inlet station) - 1| and same for k, interpolated in log z (station-to-inlet drift).
Acceptance (PLAN F2 / review C1): U within +-5 %, k within +-20 % below 100 m between the inlet and the centre
(and the ring edge). Writes <case>/homogeneity.json, homogeneity.csv, homogeneity.png and copies them to
v2/cfd/zonatec/results/. Usage: python homogeneity_zt.py <case> [--time T]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ofio  # noqa: E402
from zt_common import CMU, KAPPA, ZT  # noqa: E402

ZMIN, ZMAX = 2.0, 100.0


def load(case: Path, t: str, station: str) -> pd.DataFrame:
    f = next((case / "postProcessing" / "profiles" / t).glob(f"{station}_*.csv"))
    d = pd.read_csv(f)
    d["Uh"] = np.hypot(d["U_0"], d["U_1"])
    return d.drop_duplicates("z").sort_values("z").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--time", default=None)
    a = ap.parse_args()
    case = Path(a.case).resolve()
    meta = json.loads((case / "case.json").read_text())
    inf = meta["inflow"]
    us, z0 = inf["u_star"], inf["z0"]
    pdir = case / "postProcessing" / "profiles"
    t = a.time or max((p.name for p in pdir.iterdir()), key=float)
    Urh = lambda z: us / KAPPA * np.log((z + z0) / z0)  # noqa: E731
    krh = us ** 2 / np.sqrt(CMU)
    rows, prof = [], {}
    ref = load(case, t, "inlet")
    for st in ["inlet", "up1500", "up771", "up545", "centre", "dn771", "dn1500"]:
        d = load(case, t, st)
        prof[st] = d
        m = (d.z >= ZMIN) & (d.z <= ZMAX)
        dz = d[m]
        eU = dz.Uh / Urh(dz.z) - 1
        ek = dz.k / krh - 1
        # drift relative to the sampled inlet profile (log-z interpolation of the inlet column)
        Ui = np.interp(np.log(dz.z), np.log(ref.z), ref.Uh)
        ki = np.interp(np.log(dz.z), np.log(ref.z), ref.k)
        rows.append({"station": st, "n_cells_2_100m": int(m.sum()), "z_first_centroid": float(d.z.iloc[0]),
                     "dU_vs_RH_maxabs_pct": float(100 * np.abs(eU).max()), "dU_vs_RH_mean_pct": float(100 * eU.mean()),
                     "dk_vs_RH_maxabs_pct": float(100 * np.abs(ek).max()), "dk_vs_RH_mean_pct": float(100 * ek.mean()),
                     "dU_vs_inlet_maxabs_pct": float(100 * np.abs(dz.Uh / Ui - 1).max()),
                     "dk_vs_inlet_maxabs_pct": float(100 * np.abs(dz.k / ki - 1).max()),
                     "U10_over_RH": float(np.interp(np.log(10), np.log(d.z), d.Uh) / Urh(10.0)),
                     "U1p75_over_RH": float(np.interp(np.log(1.75), np.log(d.z), d.Uh) / Urh(1.75)) if d.z.iloc[0] < 1.75 else None})
    df = pd.DataFrame(rows)
    crit = df[df.station.isin(["up545", "centre", "up771"])]
    acc = {"U_within_5pct_vs_RH": bool((crit.dU_vs_RH_maxabs_pct <= 5).all()),
           "k_within_20pct_vs_RH": bool((crit.dk_vs_RH_maxabs_pct <= 20).all()),
           "U_within_5pct_vs_inlet": bool((crit.dU_vs_inlet_maxabs_pct <= 5).all()),
           "k_within_20pct_vs_inlet": bool((crit.dk_vs_inlet_maxabs_pct <= 20).all())}
    out = {"case": meta["case_id"], "time": t, "z_range": [ZMIN, ZMAX], "u_star": us, "z0": z0,
           "z0_ground_zoi": meta["z0_ground_zoi"], "model": meta["model"], "stations": rows, "acceptance": acc}
    (case / "homogeneity.json").write_text(json.dumps(out, indent=2))
    df.to_csv(case / "homogeneity.csv", index=False)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 3, figsize=(13, 5), sharey=True)
        zz = np.geomspace(0.2, 500, 200)
        ax[0].plot(Urh(zz), zz, "k--", lw=2, label="RH impuesto")
        ax[1].axvline(krh, color="k", ls="--", lw=2)
        for st, d in prof.items():
            ax[0].plot(d.Uh, d.z, ".-", ms=3, label=st)
            ax[1].plot(d.k, d.z, ".-", ms=3)
            ax[2].plot(100 * (d.Uh / Urh(d.z) - 1), d.z, ".-", ms=3)
        for x in (-5, 5):
            ax[2].axvline(x, color="r", ls=":")
        ax[0].set_yscale("log"); ax[0].set_ylim(0.2, 520)
        ax[0].set_xlabel("U horizontal [m/s]"); ax[1].set_xlabel("k [m2/s2]"); ax[2].set_xlabel("dU vs RH [%]")
        ax[2].set_xlim(-20, 20); ax[0].set_ylabel("z [m]"); ax[0].legend(fontsize=7)
        fig.suptitle(f"Homogeneidad {meta['case_id']} ({meta['model']}, it {t})")
        fig.tight_layout(); fig.savefig(case / "homogeneity.png", dpi=110)
    except Exception as e:  # noqa: BLE001
        print("plot failed:", e)
    res = ZT / "results"
    res.mkdir(exist_ok=True)
    for f in ("homogeneity.json", "homogeneity.csv", "homogeneity.png"):
        if (case / f).exists():
            shutil.copy(case / f, res / f"{meta['case_id']}_{f}")
    print(df.round(2).to_string(index=False))
    print(json.dumps(acc))


if __name__ == "__main__":
    main()
