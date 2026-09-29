"""Calibrate the tabulated AIJ inlet so that the INCIDENT profile (empty domain, x = 0 = building position)
matches the measured approach flow (review item C2, E:/PINN/v2/docs/revisiones/F1_revision.md).

One pass: U_in <- U_in * U_meas/U_calc(x=0), k_in <- k_in * k_meas/k_calc(x=0) (factors clipped to [0.8, 1.25],
evaluated at the measurement heights 0.005-0.60 m and interpolated in z; held constant outside that range);
epsilon re-derived from P_k = epsilon (eps = Cmu^1/2 k dU/dz, as in prepare_data.py), omega = eps/(Cmu k).

Usage: python calibrate_inlet.py --case E:/PINN/runs/aij/hom_rke_table_rough --out ../data/processed/inlet_rke_c1.csv
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
CMU = 0.09


def eps_from(z, U, k):
    m = (z >= 0.005) & (z <= 0.6)
    c = np.polyfit(np.log(z[m]), U[m], 3)
    g = np.polyval(np.polyder(c), np.log(z)) / z
    eps = np.sqrt(CMU) * k * np.maximum(g, 1e-6)
    # below 5 mm: log-law gradient through the lowest table points; above 0.5 m: constant length scale
    low = z < 0.005
    if low.any():
        zl, Ul = z[m][:3], U[m][:3]
        us = np.polyfit(np.log(zl), Ul, 1)[0] * 0.41
        eps[low] = np.sqrt(CMU) * k[low] * us / (0.41 * z[low])
    i05 = int(np.argmin(np.abs(z - 0.5)))
    L05 = CMU ** 0.75 * k[i05] ** 1.5 / eps[i05]
    hi = z > 0.5
    eps[hi] = CMU ** 0.75 * k[hi] ** 1.5 / L05
    return eps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    case = Path(a.case)
    meta = json.loads((case / "case.json").read_text())
    tab = pd.read_csv(meta.get("inlet_table") or (PROC / "inlet_profile.csv"))
    p = read_set(latest_dir(case / "postProcessing" / "profiles"), "x000")
    meas = pd.read_csv(HERE.parent / "data/raw/zenodo_15050148/AF_caseA.csv", encoding="utf-8-sig")
    meas.columns = ["z", "U", "su", "sv", "sw", "k"]
    fU = np.clip(meas.U / np.interp(meas.z, p.z, p["U_0"]), 0.8, 1.25).to_numpy().copy()
    fk = np.clip(meas.k / np.interp(meas.z, p.z, p["k"]), 0.8, 1.25).to_numpy().copy()
    # the first measured point (z = 5 mm, 2-3 cells above the ground) is dominated by the ground wall function,
    # which the inlet cannot correct: use the factors of z = 10 mm below 10 mm
    zm = meas.z.to_numpy()
    fU[zm < 0.01] = fU[np.argmin(np.abs(zm - 0.01))]
    fk[zm < 0.01] = fk[np.argmin(np.abs(zm - 0.01))]
    z = tab.z.to_numpy()
    U = tab.U.to_numpy() * np.interp(z, zm, fU)
    U = np.maximum.accumulate(U)          # keep U(z) monotonic (dU/dz >= 0 for P_k = eps)
    k = tab.k.to_numpy() * np.interp(z, zm, fk)
    eps = eps_from(z, U, k)
    out = pd.DataFrame({"z": z, "U": U, "k": k, "epsilon": eps, "omega": eps / (CMU * k),
                        "L_eps": CMU ** 0.75 * k ** 1.5 / eps})
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.out, index=False, float_format="%.6g")
    print(f"{case.name}: fU {fU.min():.3f}-{fU.max():.3f}, fk {fk.min():.3f}-{fk.max():.3f} -> {a.out}")


if __name__ == "__main__":
    main()
