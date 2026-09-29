"""Post-process AIJ Case A runs: sample at the experimental points, validation metrics, reattachment, plots.

Usage:
  python post_aij.py --cases E:/PINN/runs/aij/bld_rke_M E:/PINN/runs/aij/bld_sst_M E:/PINN/runs/aij/bld_ske_M \
                     --tag M --out ../results

Metrics (all on values normalised by U_H = 4.491 m/s, the approach-flow speed at z = H):
  * Hit rate q (VDI 3783-9): hit if |P-O|/|O| <= D (D = 0.25) OR |P-O| <= W.  VDI 3783-9 takes W from the
    repeatability of each reference data set; the AIJ Case A release gives no repeatability, so W = 0.05
    (normalised velocity, i.e. ~0.22 m/s) is used as the main value and q is also reported for W = 0 and W = 0.10.
    Computed per velocity component (U, V, W) as VDI does, and for the speed |U| at the two horizontal planes.
  * FAC2, NMSE, FB (Chang & Hanna 2004) on positive quantities only: speed |U| (all 186 points) and k.
      FAC2 = fraction with 0.5 <= P/O <= 2 ; NMSE = <(O-P)^2>/(<O><P>) ; FB = 2(<O>-<P>)/(<O>+<P>)
  * Reattachment: roof X_R (from the windward roof edge) and wake X_F (from the leeward face) where the
    first-cell streamwise velocity on y = 0 changes sign; compared with Exp. X_R/b = 0.52, X_F/b = 1.42
    (Tominaga et al. 2004 JAABE 3:63-70, Table 1, AIJ cross comparison of Case A).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROC = HERE.parent / "data" / "processed"
B, H = 0.08, 0.16
EXP_XR, EXP_XF = 0.52, 1.42
LIT = {  # Tominaga et al. (2004) JAABE 3(1) 63-70, Table 1 (AIJ cross comparison, Case A), X/b
    "standard k-eps (KE1-KE8)": {"XR": "no reverse flow", "XF": "1.66-2.70"},
    "RNG k-eps (RNG1, RNG2)": {"XR": "0.50-0.58", "XF": "2.80-3.34"},
    "LK k-eps (LK1-LK3)": {"XR": "0.53-0.87", "XF": "2.98-3.19"},
    "Durbin k-eps (DBN)": {"XR": "0.63", "XF": "2.70"},
    "DSM": {"XR": ">1.0", "XF": "4.22"},
    "LES with inflow turbulence (LES2)": {"XR": "0.50", "XF": "2.10"},
    "Experiment (Ishihara & Hibi 1998)": {"XR": "0.52", "XF": "1.42"},
}
MODEL_STYLE = {  # colour (validated default categorical order) + dash as secondary encoding
    "realizableKE": ("#2a78d6", "-"), "kOmegaSST": ("#eb6834", "--"), "kEpsilon": ("#1baf7a", ":")}


def latest_dir(p: Path) -> Path | None:
    if not p.exists():
        return None
    ts = [d for d in p.iterdir() if d.is_dir()]
    try:
        return max(ts, key=lambda d: float(d.name)) if ts else None
    except ValueError:
        return None


def read_set(dirp: Path, name: str) -> pd.DataFrame | None:
    """Merge all csv files written for set `name` (writers may split scalar/vector fields)."""
    files = sorted(f for f in dirp.glob(f"{name}*.csv")
                   if f.stem == name or f.stem.startswith(name + "_"))
    if not files:
        return None
    df = None
    for f in files:
        d = pd.read_csv(f)
        d.columns = [c.strip().lstrip("#").strip() for c in d.columns]
        if df is None:
            df = d
        else:
            new = [c for c in d.columns if c not in df.columns]
            df = pd.concat([df.reset_index(drop=True), d[new].reset_index(drop=True)], axis=1)
    # normalise vector column names -> U_0,U_1,U_2
    ren = {}
    for c in df.columns:
        for suf, i in (("_x", 0), ("_y", 1), ("_z", 2), ("_0", 0), ("_1", 1), ("_2", 2)):
            if c.startswith("U") and c.endswith(suf) and len(c) == 1 + len(suf):
                ren[c] = f"U_{i}"
    return df.rename(columns=ren)


def hit_rate(P, O, D=0.25, W=0.05):
    P, O = np.asarray(P), np.asarray(O)
    d = np.abs(P - O)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.where(np.abs(O) > 0, d / np.abs(O), np.inf)
    return float(np.mean((rel <= D) | (d <= W)))


def chang_hanna(P, O):
    P, O = np.asarray(P, float), np.asarray(O, float)
    m = (O > 0) & (P > 0)
    fac2 = float(np.mean((P / np.where(O > 0, O, np.nan) >= 0.5) & (P / np.where(O > 0, O, np.nan) <= 2.0)))
    nmse = float(np.mean((O - P) ** 2) / (O.mean() * P.mean()))
    fb = float(2 * (O.mean() - P.mean()) / (O.mean() + P.mean()))
    return {"FAC2": fac2, "NMSE": nmse, "FB": fb, "n_pos": int(m.sum())}


def crossing(x, u, start_neg=True):
    """first x where u goes from <0 to >=0 (linear interpolation); None if never."""
    x, u = np.asarray(x), np.asarray(u)
    neg = u < 0
    if not neg.any():
        return None
    i0 = int(np.argmax(neg))
    for i in range(i0, len(u) - 1):
        if u[i] < 0 <= u[i + 1]:
            return float(x[i] + (x[i + 1] - x[i]) * (-u[i]) / (u[i + 1] - u[i]))
    return float("inf")


def convergence(case: Path) -> dict:
    out = {}
    res = []
    for d in sorted((case / "postProcessing" / "residuals").glob("*"), key=lambda p: float(p.name)):
        f = d / "solverInfo.dat"
        if f.exists():
            t = pd.read_csv(f, sep=r"\s+", comment="#", header=None)
            hdr = [l for l in f.read_text().splitlines() if l.startswith("#")][-1].lstrip("#").split()
            t.columns = hdr[: t.shape[1]]
            res.append(t)
    if res:
        r = pd.concat(res).drop_duplicates("Time", keep="last")
        out["n_iter"] = int(r.Time.max())
        for c in r.columns:
            if c.endswith("_initial") or c.endswith("Ux_initial"):
                out["final_" + c] = float(r[c].iloc[-1])
    # monitor stability over the last 500 iterations
    mons = []
    for d in sorted((case / "postProcessing" / "monitors").glob("*"), key=lambda p: float(p.name)):
        f = d / "U"
        if f.exists():
            rows = []
            for line in f.read_text().splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                s = line.replace("(", " ").replace(")", " ").split()
                rows.append([float(v) for v in s])
            mons.append(np.array(rows))
    if mons:
        m = np.vstack(mons)
        t = m[:, 0]
        ux = m[:, 1::3]
        last = t >= t.max() - 500
        if last.sum() > 10:
            rng = ux[last].max(0) - ux[last].min(0)
            out["monitor_Ux_range_last500_over_UH"] = float(rng.max() / 4.491)
    return out


def process_case(case: Path) -> dict:
    meta = json.loads((case / "case.json").read_text())
    UH = meta["U_H"]
    e = pd.read_csv(PROC / "exp_points.csv")
    tdir = latest_dir(case / "postProcessing" / "sampleExp")
    s = read_set(tdir, "expPoints")
    # match by coordinates
    xyz = s[["x", "y", "z"]].to_numpy()
    idx = []
    for p in e[["x", "y", "z"]].to_numpy():
        dd = np.linalg.norm(xyz - p, axis=1)
        j = int(np.argmin(dd))
        idx.append(j if dd[j] < 1e-5 else -1)
    idx = np.array(idx)
    ok = idx >= 0
    e = e[ok].copy()
    si = s.iloc[idx[ok]].reset_index(drop=True)
    e = e.reset_index(drop=True)
    e["Uc"], e["Vc"], e["Wc"] = si["U_0"] / UH, si["U_1"] / UH, si["U_2"] / UH
    e["kc"] = si["k"] / UH ** 2
    e["Uo"], e["Vo"], e["Wo"] = e.U / UH, e.V / UH, e.W / UH
    e["Sc"] = np.sqrt(e.Uc ** 2 + e.Vc ** 2 + e.Wc ** 2)
    e["So"] = e.Umag_UH
    res = {"case": case.name, "model": meta["model"], "level": meta["level"], "ncells": meta["mesh"]["ncells"],
           "n_points": int(ok.sum()), "time_dir": tdir.name}
    for W in (0.0, 0.05, 0.10):
        tag = f"W{W:.2f}"
        res[f"q_U_{tag}"] = hit_rate(e.Uc, e.Uo, W=W)
        res[f"q_V_{tag}"] = hit_rate(e.Vc, e.Vo, W=W)
        res[f"q_W_{tag}"] = hit_rate(e.Wc, e.Wo, W=W)
        res[f"q_S_all_{tag}"] = hit_rate(e.Sc, e.So, W=W)
        for st in ("vert", "h0125", "h125"):
            m = e.set == st
            res[f"q_U_{st}_{tag}"] = hit_rate(e.Uc[m], e.Uo[m], W=W)
            res[f"q_S_{st}_{tag}"] = hit_rate(e.Sc[m], e.So[m], W=W)
    for k, v in chang_hanna(e.Sc, e.So).items():
        res[f"S_{k}"] = v
    m = e.set == "h0125"
    for k, v in chang_hanna(e.Sc[m], e.So[m]).items():
        res[f"Sped_{k}"] = v
    for k, v in chang_hanna(e.kc, e.k_UH2).items():
        res[f"k_{k}"] = v
    # reattachment
    ldir = latest_dir(case / "postProcessing" / "sampleLines")
    roof, wake, front = read_set(ldir, "roof"), read_set(ldir, "wake"), read_set(ldir, "front")
    xr = None
    if roof is not None:
        u = roof["U_0"].to_numpy()
        if (u < 0).any():
            c = crossing(roof.x, u)
            xr = (c + B / 2) / B if c is not None and np.isfinite(c) else float("inf")
            res["roof"] = "reattaches" if np.isfinite(xr) else "no reattachment on roof"
        else:
            res["roof"] = "no reverse flow"
    res["XR_b"] = xr
    if wake is not None:
        c = crossing(wake.x, wake["U_0"].to_numpy())
        res["XF_b"] = (c - B / 2) / B if c is not None and np.isfinite(c) else None
    if front is not None:   # upstream horseshoe separation point on the ground (last sign change before the face)
        u = front["U_0"].to_numpy()
        neg = np.where(u < 0)[0]
        res["front_sep_b"] = float((-B / 2 - front.x.iloc[neg[0]]) / B) if len(neg) else None
    res.update(convergence(case))
    tf = case / "timing.txt"
    if tf.exists():
        res["wallclock_s"] = float(tf.read_text().split()[1])
    e.to_csv(case / "exp_vs_cfd.csv", index=False, float_format="%.5g")
    return res, e


def plots(cases: list[Path], out: Path, tag: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, ink2, grid = "#0b0b0b", "#52514e", "#e4e3df"
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": ink2, "axes.labelcolor": ink, "xtick.color": ink2,
                         "ytick.color": ink2, "axes.grid": True, "grid.color": grid, "grid.linewidth": 0.6,
                         "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "#fcfcfb",
                         "axes.facecolor": "#fcfcfb"})
    e0 = pd.read_csv(PROC / "exp_points.csv")
    UH = 4.491
    xb = [-0.75, -0.5, -0.25, 0.0, 0.5, 0.75, 1.25, 2.0, 3.25]
    # --- vertical profiles, centre plane
    fig, axs = plt.subplots(1, 9, figsize=(15, 4.2), sharey=True)
    for i, (ax, s) in enumerate(zip(axs, xb)):
        ev = e0[(e0.set == "vert") & np.isclose(e0.x_b, s)]
        for c in cases:
            meta = json.loads((c / "case.json").read_text())
            d = read_set(latest_dir(c / "postProcessing" / "sampleProfiles"), f"v{i}")
            if d is None:
                continue
            col, ls = MODEL_STYLE.get(meta["model"], ("#4a3aa7", "-"))
            ax.plot(d["U_0"] / UH, d.z / B, color=col, ls=ls, lw=2, label=meta["model"] if i == 0 else None)
        ax.plot(ev.U_UH, ev.z_b, "o", ms=5, mfc="white", mec=ink, mew=1.2, label="Exp." if i == 0 else None)
        ax.axvline(0, color=ink2, lw=0.6)
        ax.set_title(f"x/b = {s}", fontsize=9)
        ax.set_xlim(-0.5, 1.4)
        ax.set_xlabel("U/U_H")
        if s in (-0.25, 0.0):
            ax.axhspan(0, 2, color="#d9d8d3", zorder=0)
    axs[0].set_ylabel("z/b")
    axs[0].set_ylim(0, 3.75)
    fig.legend(loc="upper center", ncol=4, frameon=False)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(out / f"vertical_profiles_{tag}.png", dpi=130)
    plt.close(fig)
    # --- lateral profiles, pedestrian level z/b = 0.125 (speed)
    fig, axs = plt.subplots(1, 9, figsize=(15, 3.8), sharey=True)
    for i, (ax, s) in enumerate(zip(axs, xb)):
        eh = e0[(e0.set == "h0125") & np.isclose(e0.x_b, s)]
        for c in cases:
            meta = json.loads((c / "case.json").read_text())
            d = read_set(latest_dir(c / "postProcessing" / "sampleProfiles"), f"ha{i}")
            if d is None:
                continue
            col, ls = MODEL_STYLE.get(meta["model"], ("#4a3aa7", "-"))
            sp = np.sqrt(d["U_0"] ** 2 + d["U_1"] ** 2 + d["U_2"] ** 2) / UH
            ax.plot(sp, d.y / B, color=col, ls=ls, lw=2, label=meta["model"] if i == 0 else None)
        ax.plot(eh.Umag_UH, eh.y_b, "o", ms=5, mfc="white", mec=ink, mew=1.2, label="Exp." if i == 0 else None)
        ax.set_title(f"x/b = {s}", fontsize=9)
        ax.set_xlim(0, 1.1)
        ax.set_xlabel("|U|/U_H")
    axs[0].set_ylabel("y/b")
    fig.legend(loc="upper center", ncol=4, frameon=False)
    fig.suptitle("z/b = 0.125 (pedestrian level)", y=0.86, fontsize=9, color=ink2)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    fig.savefig(out / f"pedestrian_profiles_{tag}.png", dpi=130)
    plt.close(fig)
    # --- scatter, pedestrian level speed
    n = len(cases)
    fig, axs = plt.subplots(1, n, figsize=(4.2 * n, 4.2), squeeze=False)
    for ax, c in zip(axs[0], cases):
        meta = json.loads((c / "case.json").read_text())
        e = pd.read_csv(c / "exp_vs_cfd.csv")
        col, _ = MODEL_STYLE.get(meta["model"], ("#4a3aa7", "-"))
        for st, mk in (("h0125", "o"), ("h125", "s"), ("vert", "^")):
            m = e.set == st
            ax.plot(e.So[m], e.Sc[m], mk, ms=5, color=col, alpha=0.85 if st == "h0125" else 0.35,
                    mec="#fcfcfb", mew=0.8, label={"h0125": "z/b=0.125", "h125": "z/b=1.25", "vert": "y=0 plane"}[st])
        g = np.linspace(0, 1.5, 10)
        ax.plot(g, g, color=ink2, lw=1)
        ax.fill_between(g, 0.75 * g, 1.25 * g, color="#d9d8d3", alpha=0.5, lw=0, label="±25 %")
        ax.set_xlim(0, 1.5); ax.set_ylim(0, 1.5)
        ax.set_xlabel("Exp. |U|/U_H"); ax.set_ylabel("CFD |U|/U_H")
        ax.set_title(meta["model"], fontsize=10)
        ax.legend(fontsize=7, frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(out / f"scatter_speed_{tag}.png", dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", required=True)
    ap.add_argument("--tag", default="M")
    ap.add_argument("--out", default=str(HERE.parent / "results"))
    ap.add_argument("--figs", default="E:/PINN/runs/aij/figs")
    a = ap.parse_args()
    out, figs = Path(a.out), Path(a.figs)
    out.mkdir(parents=True, exist_ok=True)
    figs.mkdir(parents=True, exist_ok=True)
    cases = [Path(c) for c in a.cases]
    rows = []
    for c in cases:
        r, _ = process_case(c)
        rows.append(r)
        print(json.dumps(r, indent=1))
    df = pd.DataFrame(rows)
    df.to_csv(out / f"metrics_{a.tag}.csv", index=False, float_format="%.4g")
    (out / "literature_reattachment.json").write_text(json.dumps(LIT, indent=1))
    plots(cases, figs, a.tag)
    cols = ["model", "ncells", "q_U_W0.05", "q_V_W0.05", "q_W_W0.05", "q_S_h0125_W0.05", "q_S_all_W0.05",
            "S_FAC2", "S_NMSE", "S_FB", "k_FAC2", "XR_b", "XF_b", "n_iter"]
    print(df[[c for c in cols if c in df.columns]].to_string())


if __name__ == "__main__":
    main()
