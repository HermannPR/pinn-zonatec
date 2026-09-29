"""
build_windrose.py -- Produce the deliverables for the PINN Zona Tec wind
climatology: windrose_16.csv, seasonal_daynight.csv, completeness tables and
the two figures (wind rose, Weibull fit check), from the cached QC'd hourly
ISD record (parse_isd.py) using windclimate.py.

Run:
    E:\\PINN\\.venv\\Scripts\\python.exe E:\\PINN\\v2\\climate\\build_windrose.py
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

import parse_isd
import windclimate as wc

OUT_DIR = r"E:\PINN\v2\climate"
FIG_DIR = os.path.join(OUT_DIR, "figures")

YEARS_FULL = list(range(2010, 2025))  # 15 complete years
YEAR_PARTIAL = 2025  # partial (Jan 1 - Aug 24), excluded from main climatology

# --- palette (dataviz skill reference palette, light mode) -----------------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95"]  # steps 100,200,350,450,600
CAT_BLUE = "#2a78d6"
CAT_ORANGE = "#eb6834"


def main() -> None:
    os.makedirs(FIG_DIR, exist_ok=True)

    # ---- 1. ingest + QC (rebuild cache to make this script self-contained) ----
    hourly_full = {}
    completeness = {}
    for station in ["MMMY", "MMAN"]:
        h = parse_isd.build_and_cache(station, YEARS_FULL + [YEAR_PARTIAL])
        hourly_full[station] = h
        completeness[station] = parse_isd.completeness_by_year(h, YEARS_FULL)

    hourly = hourly_full["MMMY"]
    hourly_15y = hourly[hourly["datetime_hour"].dt.year.isin(YEARS_FULL)].reset_index(drop=True)

    # ---- 2. wind rose + Weibull fits (primary station, 15 complete years) ----
    result = wc.build_windrose(hourly_15y)
    table = result.table.copy()
    table.insert(0, "station", "MMMY")
    table.to_csv(os.path.join(OUT_DIR, "windrose_16.csv"), index=False)

    calm_summary = pd.DataFrame([dict(
        station="MMMY", years=f"{YEARS_FULL[0]}-{YEARS_FULL[-1]}",
        n_hours_total=result.n_hours_total,
        calm_fraction=result.calm_fraction,
        variable_fraction=result.variable_fraction,
    )])
    calm_summary.to_csv(os.path.join(OUT_DIR, "calm_variable_summary.csv"), index=False)

    # ---- 3. seasonal / day-night table -------------------------------------
    seasonal = wc.seasonal_daynight_table(hourly_15y, strong_wind_threshold=5.0)
    seasonal.to_csv(os.path.join(OUT_DIR, "seasonal_daynight.csv"), index=False)

    # ---- 4. completeness tables ---------------------------------------------
    completeness["MMMY"].to_csv(os.path.join(OUT_DIR, "completeness_mmmy.csv"), index=False)
    completeness["MMAN"].to_csv(os.path.join(OUT_DIR, "completeness_mman.csv"), index=False)

    # ---- 5. exceedance: empirical-first (review F1 I3), Weibull as fallback ----
    emp5 = wc.empirical_exceedance(hourly_15y, 5.0)
    ann5_weib = wc.annual_exceedance(table, K=1.0, threshold_local=5.0, method="weibull")
    ann5_auto = wc.annual_exceedance(table, K=1.0, threshold_local=5.0,
                                      sector_speeds=result.sector_speeds, method="auto")
    emp15 = wc.empirical_exceedance(hourly_15y, 15.0)
    ann15_weib = wc.annual_exceedance(table, K=1.0, threshold_local=15.0, method="weibull")
    ann15_auto = wc.annual_exceedance(table, K=1.0, threshold_local=15.0,
                                       sector_speeds=result.sector_speeds, method="auto")
    ann10_auto = wc.annual_exceedance(table, K=1.0, threshold_local=10.0,
                                       sector_speeds=result.sector_speeds, method="auto")

    print("=== MMMY windrose (2010-2024) ===")
    print(table.round(4).to_string(index=False))
    print(f"calm_fraction={result.calm_fraction:.4f}  variable_fraction={result.variable_fraction:.6f}")
    print(f"P(U10>5 m/s): empirical(raw)={emp5*100:.4f}%  weibull(K=1)={ann5_weib['annual_probability']*100:.4f}%  "
          f"auto(empirical-first)={ann5_auto['annual_probability']*100:.4f}%")
    print(f"P(U10>10 m/s): auto(empirical-first)={ann10_auto['annual_probability']*100:.4f}%")
    print(f"P(U10>15 m/s): empirical(raw)={emp15*100:.4f}%  weibull(K=1)={ann15_weib['annual_probability']*100:.6f}%  "
          f"auto(empirical-first)={ann15_auto['annual_probability']*100:.4f}%  "
          f"[{ann15_auto['annual_probability']*result.n_hours_total:.1f} h observadas en {len(YEARS_FULL)} anios]")

    prevail = table.sort_values("frequency", ascending=False).head(3)
    print("Top-3 sectors by frequency:")
    print(prevail[["sector_centre_deg", "frequency", "mean_u10"]].to_string(index=False))
    mean_u10_all = (hourly_15y.loc[~hourly_15y["is_calm"], "wspd_ms"]).mean()
    print(f"Mean U10 (non-calm hours, all directions) = {mean_u10_all:.3f} m/s")

    # ---- 6. MMAN secondary-station comparison (daytime-only, for caveat) ---
    hourly_mman_15y = hourly_full["MMAN"][hourly_full["MMAN"]["datetime_hour"].dt.year.isin(YEARS_FULL)]
    res_mman = wc.build_windrose(hourly_mman_15y.reset_index(drop=True))
    prevail_mman = res_mman.table.sort_values("frequency", ascending=False).head(3)
    print("=== MMAN (secondary, daytime-biased record) top-3 sectors ===")
    print(prevail_mman[["sector_centre_deg", "frequency", "mean_u10"]].to_string(index=False))
    print(f"MMAN calm_fraction={res_mman.calm_fraction:.4f}")

    # ---- 7. figures -----------------------------------------------------------
    plot_windrose(hourly_15y, os.path.join(FIG_DIR, "windrose_mmmy.png"))
    plot_weibull_check(hourly_15y, table, os.path.join(FIG_DIR, "weibull_check_mmmy.png"))

    # ---- 8. I2: two-layer roughness transfer report (blocker fix) ----------
    try:
        import transfer as tr
        roughness = tr.load_roughness_table()
        transfer_report = tr.report_transfer_ratios(roughness)
        transfer_report.to_csv(os.path.join(OUT_DIR, "transfer_report_16sectors.csv"), index=False)
        print("\n=== I2: transfer T=u*_regional/U10 per sector (macdonald, blend60 vs EN1991 vs naive export.py) ===")
        print(transfer_report[["theta_deg", "z0_macdonald", "T_macdonald_blend60",
                                "T_macdonald_en1991", "export_overestimate_pct_macdonald"]].round(4).to_string(index=False))
    except FileNotFoundError as e:
        print(f"\n[I2] transfer report skipped, roughness table not found: {e}")

    # ---- 9. I5: MMMY representativeness vs ERA5 / SIMA Garza Laguera -------
    print_i5_representativeness(table)

    print("\nWrote: windrose_16.csv, calm_variable_summary.csv, seasonal_daynight.csv,")
    print("       completeness_mmmy.csv, completeness_mman.csv, transfer_report_16sectors.csv,")
    print(f"       figures/windrose_mmmy.png, figures/weibull_check_mmmy.png")


def print_i5_representativeness(table: pd.DataFrame) -> None:
    """Review F1 I5: quantify how representative MMMY (airport, 18 km NNE of
    campus) is of the campus wind climate, vs ERA5 (nearest reanalysis grid
    cell to the campus) and SIMA "Preparatoria ITESM Garza Laguera" (rooftop
    station ~4.1 km south of Campus Monterrey, inside the valley)."""
    era5_path = r"E:\PINN\datos\viento\era5_openmeteo_rose16.csv"
    if not os.path.exists(era5_path):
        print(f"\n[I5] ERA5 rose not found at {era5_path}, skipping representativeness comparison")
        return
    era5 = pd.read_csv(era5_path)
    # 8-point sector labels in the same clockwise-from-N order as SECTOR_CENTERS
    labels16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    era5 = era5.set_index("sector").loc[labels16].reset_index()
    mmmy_by_label = dict(zip(labels16, table.sort_values("sector_centre_deg")["frequency"] * 100))
    era5_by_label = dict(zip(labels16, era5["freq_pct"]))

    e_se_arc = ["ENE", "E", "ESE", "SE", "SSE"]  # 67.5-157.5 deg
    mmmy_arc = sum(mmmy_by_label[l] for l in e_se_arc)
    era5_arc = sum(era5_by_label[l] for l in e_se_arc)
    se_only_arc = ["ESE", "SE", "SSE"]  # ~112.5-157.5, roughly what SIMA's coarse "SE" 8-pt bucket spans
    mmmy_se = sum(mmmy_by_label[l] for l in se_only_arc)
    era5_se = sum(era5_by_label[l] for l in se_only_arc)
    n_nw_arc = ["N", "NNW", "NW"]
    mmmy_nnw = sum(mmmy_by_label[l] for l in n_nw_arc)
    era5_nnw = sum(era5_by_label[l] for l in n_nw_arc)

    print("\n=== I5: representatividad de MMMY vs ERA5 (grilla campus) y SIMA Garza Laguera ===")
    print(f"Arco ENE-SSE (67.5-157.5 deg): MMMY={mmmy_arc:.1f}%  ERA5(campus)={era5_arc:.1f}%  "
          f"diff={era5_arc-mmmy_arc:+.1f} pp")
    print(f"Arco ESE-SSE (~112.5-157.5, comparable al bin 'SE' de 8 puntos de SIMA): "
          f"MMMY={mmmy_se:.1f}%  ERA5(campus)={era5_se:.1f}%  SIMA Garza Laguera 'SE'=33% (2021-2023)")
    print(f"Arco N-NNW-NW: MMMY={mmmy_nnw:.1f}%  ERA5(campus)={era5_nnw:.1f}%  "
          f"SIMA Garza Laguera 'N'+'NO'=17%+14%=31% (2021-2023)")
    print("-> MMMY y ERA5 coinciden entre si (N/NW marginal, ~7%), pero AMBOS subrepresentan muy probablemente "
          "el componente N/NW que la estacion dentro del valle (SIMA, mas cercana al campus) reporta como "
          "sustancial (~31%), atribuido por el informe INECC 2025 a canalizacion NO-SE por la Sierra Madre "
          "Oriental / Cerro de la Silla -- efecto orografico local que ni el aeropuerto (18 km NNE, fuera del "
          "corredor) ni ERA5 (grilla ~31 km) resuelven. Ver README.md, seccion de limitaciones (I5).")


def plot_windrose(hourly: pd.DataFrame, path: str) -> None:
    """Stacked, speed-binned 16-sector wind rose (percent-of-hours per sector)."""
    speed_bins = [0, 2, 4, 6, 8, np.inf]
    bin_labels = ["0-2", "2-4", "4-6", "6-8", ">8"]

    dir_mask = (~hourly["is_calm"]) & (~hourly["is_variable"]) & hourly["wdir_deg"].notna()
    d = hourly.loc[dir_mask, "wdir_deg"].to_numpy()
    u = hourly.loc[dir_mask, "wspd_ms"].to_numpy()
    n_total = len(hourly)
    W = wc.sector_weights(d)  # (n,16)

    # percent-of-all-hours per (sector, speed bin)
    mat = np.zeros((len(bin_labels), wc.N_SECTORS))
    bin_idx = np.digitize(u, speed_bins[1:-1], right=False)  # 0..4
    for b in range(len(bin_labels)):
        m = bin_idx == b
        if m.any():
            mat[b] = W[m].sum(axis=0) / n_total * 100.0

    theta = np.deg2rad(wc.SECTOR_CENTERS)
    width = np.deg2rad(22.5) * 0.9

    fig = plt.figure(figsize=(7.5, 7.5), facecolor=SURFACE)
    ax = fig.add_subplot(111, projection="polar", facecolor=SURFACE)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)  # clockwise, meteorological convention

    bottom = np.zeros(wc.N_SECTORS)
    for b, label in enumerate(bin_labels):
        ax.bar(theta, mat[b], width=width, bottom=bottom, color=SEQ_BLUE[b],
               edgecolor=SURFACE, linewidth=0.5, label=f"{label} m/s")
        bottom += mat[b]

    ax.set_xticks(theta)
    ax.set_xticklabels([f"{int(t)}\u00b0" for t in wc.SECTOR_CENTERS], color=INK_SECONDARY, fontsize=9)
    ax.tick_params(axis="y", colors=INK_MUTED, labelsize=8)
    ax.grid(color=GRID, linewidth=0.8)
    ax.spines["polar"].set_color(BASELINE)
    ax.set_title("Rosa de vientos horaria -- MMMY (2010-2024)\n% de horas por sector y clase de velocidad "
                 f"(calmas {(hourly['is_calm'].mean()*100):.1f}% no mostradas)",
                 color=INK, fontsize=11, pad=20)
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.05), frameon=False,
              labelcolor=INK_SECONDARY, fontsize=9, title="Velocidad U10",
              title_fontsize=9)
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


def plot_weibull_check(hourly: pd.DataFrame, table: pd.DataFrame, path: str) -> None:
    """4x4 small multiples: empirical speed histogram (non-calm) per sector vs fitted Weibull PDF."""
    dir_mask = (~hourly["is_calm"]) & (~hourly["is_variable"]) & hourly["wdir_deg"].notna()
    d = hourly.loc[dir_mask, "wdir_deg"].to_numpy()
    u = hourly.loc[dir_mask, "wspd_ms"].to_numpy()
    W = wc.sector_weights(d)

    fig, axes = plt.subplots(4, 4, figsize=(13, 11), facecolor=SURFACE, sharex=True)
    axes = axes.ravel()
    x_grid = np.linspace(0.01, 16, 300)

    for j in range(wc.N_SECTORS):
        ax = axes[j]
        ax.set_facecolor(SURFACE)
        w_j = W[:, j]
        keep = w_j > 1e-6
        c_fit = table["weibull_c"].iloc[j]
        k_fit = table["weibull_k"].iloc[j]
        ax.hist(u[keep], bins=np.arange(0, 17, 1), weights=w_j[keep], density=True,
                color=CAT_BLUE, alpha=0.55, edgecolor=SURFACE, linewidth=0.3,
                label="Empirico")
        if np.isfinite(c_fit) and np.isfinite(k_fit):
            pdf = (k_fit / c_fit) * (x_grid / c_fit) ** (k_fit - 1) * np.exp(-(x_grid / c_fit) ** k_fit)
            ax.plot(x_grid, pdf, color=CAT_ORANGE, linewidth=1.6, label="Weibull MLE")
        ax.set_title(f"{wc.SECTOR_CENTERS[j]:.1f}\u00b0  (f={table['frequency'].iloc[j]*100:.1f}%)",
                     color=INK, fontsize=9)
        ax.tick_params(colors=INK_MUTED, labelsize=7)
        for spine in ax.spines.values():
            spine.set_color(BASELINE)
        ax.grid(color=GRID, linewidth=0.6)

    handles = [Patch(facecolor=CAT_BLUE, alpha=0.55, label="Empirico (no-calma)"),
               plt.Line2D([0], [0], color=CAT_ORANGE, linewidth=1.6, label="Weibull MLE")]
    fig.legend(handles=handles, loc="upper center", ncol=2, frameon=False,
               labelcolor=INK_SECONDARY, bbox_to_anchor=(0.5, 1.02))
    fig.suptitle("Ajuste Weibull por sector -- MMMY (2010-2024)", color=INK, fontsize=13, y=1.05)
    fig.supxlabel("U10 [m/s]", color=INK_SECONDARY)
    fig.supylabel("Densidad", color=INK_SECONDARY)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    main()
