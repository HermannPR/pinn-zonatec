"""Prepare AIJ Case A data: experimental points, inflow fits and inlet tables.

Inputs  : data/raw/zenodo_15050148/{AF_caseA.csv, RS-caseA.csv}  (CC BY 4.0, see data/raw/SOURCE.md)
Outputs : data/processed/exp_points.csv       186 measuring points with normalised values
          data/processed/inflow_fit.json      log-law and power-law fits of the approach flow
          data/processed/inlet_profile.csv    tabulated inlet U, k, epsilon, omega used by fixedProfile

Run: E:\\PINN\\.venv\\Scripts\\python.exe prepare_data.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RAW = ROOT / "data" / "raw" / "zenodo_15050148"
OUT = ROOT / "data" / "processed"

B = 0.08          # building width/depth [m]
H = 0.16          # building height [m]
KAPPA = 0.41      # von Karman constant (OpenFOAM atmBoundaryLayer default)
CMU = 0.09
DELTA = 0.60      # top of the measured approach-flow profile (~boundary-layer depth) [m]


def load_inflow() -> pd.DataFrame:
    a = pd.read_csv(RAW / "AF_caseA.csv", encoding="utf-8-sig")
    a.columns = ["z", "U", "su", "sv", "sw", "k"]
    return a


def load_points() -> pd.DataFrame:
    r = pd.read_csv(RAW / "RS-caseA.csv", encoding="utf-8-sig")
    r.columns = ["no", "x", "y", "z", "U", "V", "W", "su", "sv", "sw", "k"]
    # set membership follows the file order: 1-66 vertical plane, 67-126 z=0.01, 127-186 z=0.10
    r["set"] = np.where(r.index < 66, "vert", np.where(r.index < 126, "h0125", "h125"))
    r["pt"] = np.concatenate([np.arange(1, 67), np.arange(1, 61), np.arange(1, 61)])
    return r


def loglaw(z, us, z0):
    return us / KAPPA * np.log((z + z0) / z0)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    a = load_inflow()
    U_H = float(np.interp(H, a.z, a.U))

    # ---------------- fits ----------------
    fits = {"U_H": U_H, "H": H, "b": B, "kappa": KAPPA, "Cmu": CMU, "loglaw": [], "powerlaw": []}
    for zmax in (0.02, 0.05, 0.10, 0.16, 0.25, 0.35):
        s = a[a.z <= zmax + 1e-9]
        p, _ = curve_fit(loglaw, s.z, s.U, p0=[0.3, 1e-4], bounds=([0, 1e-8], [2, 0.1]))
        us, z0 = map(float, p)
        rms = float(np.sqrt(np.mean((loglaw(s.z, *p) - s.U) ** 2)))
        fits["loglaw"].append({
            "zmax": zmax, "n": int(len(s)), "u_star": us, "z0": z0, "rms_fit": rms,
            "k_RH": us ** 2 / np.sqrt(CMU),
            "k_meas_mean_in_range": float(s.k.mean()),
            "U_at_0.6m_extrapolated": float(loglaw(0.6, *p)),
            "z0_plus": z0 * us / 1.5e-5,
        })
    for zmax in (0.16, 0.30, 0.45, 0.60):
        s = a[a.z <= zmax + 1e-9]
        g = lambda z, al: U_H * (z / H) ** al  # noqa: E731  (U_H fixed to the measured value)
        p, _ = curve_fit(g, s.z, s.U, p0=[0.25])
        rms = float(np.sqrt(np.mean((g(s.z, *p) - s.U) ** 2)))
        fits["powerlaw"].append({"zmax": zmax, "alpha": float(p[0]), "rms_fit": rms})
    # u* implied by measured k near the ground (equilibrium assumption k = u*^2/sqrt(Cmu))
    fits["u_star_from_k_near_ground"] = float(CMU ** 0.25 * np.sqrt(a.k.iloc[:3].mean()))
    fits["note"] = (
        "Log-law fits give tiny z0 (hydraulically smooth floor, z0+ < 1) and k_RH = u*^2/sqrt(Cmu) 2.5-4x below the "
        "measured k: the tunnel approach flow is not a Richards-Hoxey equilibrium surface layer (spire/fence "
        "generated turbulence). Hence the validation runs use the tabulated measured U and k (AIJ practice), "
        "epsilon from P_k = epsilon (AIJ Eq. 8), and the RH log-law variant is only tested in the empty domain."
    )
    # RH parameters for the empty-domain comparison: fit up to z = H (building height)
    rh = next(f for f in fits["loglaw"] if abs(f["zmax"] - 0.16) < 1e-9)
    fits["RH_variant"] = {"u_star": rh["u_star"], "z0": rh["z0"], "Zref": H,
                          "Uref": float(loglaw(H, rh["u_star"], rh["z0"]))}

    # ---------------- inlet table ----------------
    # smooth U(z) for the derivative: cubic polynomial in ln z on 0.005 <= z <= DELTA
    s = a[a.z <= DELTA + 1e-9]
    c = np.polyfit(np.log(s.z), s.U, 3)
    dUdz = lambda z: np.polyval(np.polyder(c), np.log(z)) / z  # noqa: E731
    # near-ground extension below the first measured point: log law through the 3 lowest points
    s3 = a.iloc[:3]
    p3, _ = curve_fit(loglaw, s3.z, s3.U, p0=[0.2, 1e-5], bounds=([0, 1e-9], [2, 0.1]))
    fits["near_ground_extension"] = {"u_star": float(p3[0]), "z0": float(p3[1]), "points": s3.z.tolist()}
    z_ext = np.array([0.0005, 0.001, 0.002, 0.003, 0.004])
    zt = np.concatenate([z_ext, a.z.values, [0.7, 0.8, 1.0, 1.5]])
    Ut = np.concatenate([loglaw(z_ext, *p3), a.U.values, np.full(4, a.U.iloc[-1])])
    kt = np.concatenate([np.full(len(z_ext), a.k.iloc[0]), a.k.values, np.full(4, a.k.iloc[-1])])
    eps = np.empty_like(zt)
    for i, z in enumerate(zt):
        if z < a.z.iloc[0]:
            g = p3[0] / (KAPPA * (z + p3[1]))            # log-law gradient below the data
        elif z <= 0.5:
            g = max(dUdz(z), 1e-6)
        else:
            g = np.nan
        eps[i] = np.sqrt(CMU) * kt[i] * g if not np.isnan(g) else np.nan
    # above z = 0.5 m (edge of the boundary layer, dU/dz -> 0): keep the length scale of z = 0.5 m
    i05 = np.where(np.isclose(zt, 0.5))[0][0]
    L05 = CMU ** 0.75 * kt[i05] ** 1.5 / eps[i05]
    for i in np.where(np.isnan(eps))[0]:
        eps[i] = CMU ** 0.75 * kt[i] ** 1.5 / L05
    omega = eps / (CMU * kt)
    inlet = pd.DataFrame({"z": zt, "U": Ut, "k": kt, "epsilon": eps, "omega": omega,
                          "L_eps": CMU ** 0.75 * kt ** 1.5 / eps})
    inlet.to_csv(OUT / "inlet_profile.csv", index=False, float_format="%.6g")
    fits["inlet_table"] = {"file": "inlet_profile.csv", "L_const_above_0.5m": float(L05),
                           "dUdz_fit": "cubic polynomial of U in ln z (0.005-0.6 m)"}
    (OUT / "inflow_fit.json").write_text(json.dumps(fits, indent=2))

    # ---------------- experimental points ----------------
    r = load_points()
    r["x_b"], r["y_b"], r["z_b"] = r.x / B, r.y / B, r.z / B
    r["Umag"] = np.sqrt(r.U ** 2 + r.V ** 2 + r.W ** 2)
    r["Uh"] = np.sqrt(r.U ** 2 + r.V ** 2)
    r["U_UH"], r["Umag_UH"], r["Uh_UH"], r["k_UH2"] = r.U / U_H, r.Umag / U_H, r.Uh / U_H, r.k / U_H ** 2
    r.to_csv(OUT / "exp_points.csv", index=False, float_format="%.6g")

    print(f"U_H = {U_H:.3f} m/s")
    for f in fits["loglaw"]:
        print(f"log  zmax={f['zmax']:.2f}: u*={f['u_star']:.3f} z0={f['z0']*1e3:.4f} mm  kRH={f['k_RH']:.3f} "
              f"(k_meas~{f['k_meas_mean_in_range']:.3f}) rms={f['rms_fit']:.3f} U(0.6)={f['U_at_0.6m_extrapolated']:.2f}")
    for f in fits["powerlaw"]:
        print(f"pow  zmax={f['zmax']:.2f}: alpha={f['alpha']:.3f} rms={f['rms_fit']:.3f}")
    print("u* from k near ground:", round(fits["u_star_from_k_near_ground"], 3))
    print(inlet.round(4).to_string())


if __name__ == "__main__":
    main()
