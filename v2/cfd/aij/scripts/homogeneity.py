"""Empty-domain horizontal homogeneity test (2-D, same x/z grid, same inlet/ground/top BCs, no building).

Compares U and k profiles at the inlet (first cell), x = -0.40 m, x = 0 (building position), x = 1.0 m and the
outlet with (i) the imposed inlet profile and (ii) the measured approach flow. Deviations are reported for
0.005 <= z <= H (building height, 0.16 m) and 0.005 <= z <= 0.30 m.

Usage: python homogeneity.py --cases E:/PINN/runs/aij/hom_* --out ../results
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from post_aij import latest_dir, read_set

HERE = Path(__file__).resolve().parent
PROC = HERE.parent / "data" / "processed"
H = 0.16
STATIONS = ["inlet", "xm040", "x000", "x100", "outlet"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", required=True)
    ap.add_argument("--out", default=str(HERE.parent / "results"))
    ap.add_argument("--figs", default="E:/PINN/runs/aij/figs")
    a = ap.parse_args()
    out, figs = Path(a.out), Path(a.figs)
    out.mkdir(parents=True, exist_ok=True); figs.mkdir(parents=True, exist_ok=True)
    meas = pd.read_csv(PROC / "../raw/zenodo_15050148/AF_caseA.csv", encoding="utf-8-sig")
    meas.columns = ["z", "U", "su", "sv", "sw", "k"]
    rows, prof = [], {}
    for c in map(Path, a.cases):
        meta = json.loads((c / "case.json").read_text())
        d = latest_dir(c / "postProcessing" / "profiles")
        if d is None:
            print("no profiles in", c); continue
        P = {s: read_set(d, s) for s in STATIONS}
        prof[c.name] = (meta, P)
        ref = P["inlet"]
        for s in STATIONS[1:]:
            p = P[s]
            for zmax in (H, 0.30):
                m = (ref.z >= 0.005) & (ref.z <= zmax)
                du = (p["U_0"][m].to_numpy() - ref["U_0"][m].to_numpy()) / ref["U_0"][m].to_numpy()
                dk = (p["k"][m].to_numpy() - ref["k"][m].to_numpy()) / ref["k"][m].to_numpy()
                # against the measured approach flow (interpolated to the measurement heights)
                mm = (meas.z >= 0.005) & (meas.z <= zmax)
                um = np.interp(meas.z[mm], p.z, p["U_0"]); km = np.interp(meas.z[mm], p.z, p["k"])
                rows.append({"case": c.name, "model": meta["model"], "inlet": meta["inlet"], "ground": meta["ground"],
                             "station": s, "zmax": zmax,
                             "dU_max_%": 100 * float(np.max(np.abs(du))), "dU_mean_%": 100 * float(np.mean(du)),
                             "dk_max_%": 100 * float(np.max(np.abs(dk))), "dk_mean_%": 100 * float(np.mean(dk)),
                             "U_vs_meas_maxabs_%": 100 * float(np.max(np.abs(um / meas.U[mm] - 1))),
                             "k_vs_meas_mean_%": 100 * float(np.mean(km / meas.k[mm] - 1)),
                             "U_at_H_over_meas": float(np.interp(H, p.z, p["U_0"]) / np.interp(H, meas.z, meas.U)),
                             "U_at_z0.01_over_meas": float(np.interp(0.01, p.z, p["U_0"]) / np.interp(0.01, meas.z, meas.U))})
    df = pd.DataFrame(rows)
    df.to_csv(out / "homogeneity.csv", index=False, float_format="%.3g")
    pd.set_option("display.width", 250)
    print(df[(df.station.isin(["x000", "outlet"]))].to_string())

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cols = {"inlet": "#0b0b0b", "x000": "#2a78d6", "outlet": "#eb6834"}
    for name, (meta, P) in prof.items():
        fig, axs = plt.subplots(1, 2, figsize=(8, 4.5), sharey=True)
        for s in ("inlet", "x000", "outlet"):
            p = P[s]
            axs[0].plot(p["U_0"], p.z, color=cols[s], lw=2, ls={"inlet": "-", "x000": "--", "outlet": ":"}[s], label=s)
            axs[1].plot(p["k"], p.z, color=cols[s], lw=2, ls={"inlet": "-", "x000": "--", "outlet": ":"}[s])
        axs[0].plot(meas.U, meas.z, "o", ms=4, mfc="white", mec="#0b0b0b", label="measured")
        axs[1].plot(meas.k, meas.z, "o", ms=4, mfc="white", mec="#0b0b0b")
        axs[0].set_xlabel("U [m/s]"); axs[1].set_xlabel("k [m²/s²]"); axs[0].set_ylabel("z [m]")
        axs[0].set_ylim(0, 0.65); axs[0].axhline(H, color="#b0afaa", lw=0.8)
        axs[0].legend(frameon=False, fontsize=8)
        fig.suptitle(f"{name}: {meta['model']}, inlet={meta['inlet']}, ground={meta['ground']}", fontsize=9)
        fig.tight_layout()
        fig.savefig(figs / f"homog_{name}.png", dpi=120)
        plt.close(fig)


if __name__ == "__main__":
    main()
