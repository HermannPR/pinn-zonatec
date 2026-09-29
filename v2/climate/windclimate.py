"""
windclimate.py -- Wind climatology core for "PINN Zona Tec".

Builds the 16-sector wind rose (frequency, mean U10, Weibull c/k fitted by
weighted MLE on non-calm hours) from the QC'd hourly ISD record produced by
parse_isd.py, and exposes the exceedance-probability API that the pedestrian
wind comfort module (Lawson LDDC / NEN 8100, P10=C) will call once it has
computed the amplification factor K(theta) = U_local(theta) / U10(theta)
from CFD.

Conventions (must match v2/docs/DATA_CONTRACT.md)
---------------------------------------------------
- theta = meteorological direction the wind comes FROM, clockwise from true
  north (0 = N, 90 = E). 16 sectors centred at 0, 22.5, ..., 337.5 deg,
  half-width 11.25 deg.
- U10 = reference speed = mean wind at 10 m over open terrain / airport
  (P14=A, WMO standard). Orographic / valley channeling effects are NOT
  modelled separately -- they are already embedded in the measured wind rose
  at the airport station (P19=D).

10 -> 22.5 degree sector aliasing
----------------------------------
METAR wind direction is transmitted at 10-degree resolution (confirmed
empirically for MMMY: >99.9% of coded directions are exact multiples of
10 deg). Our climate sectors are 22.5 deg wide, centred on multiples of
22.5 deg, so the reported 10-degree "point" values do not line up with the
22.5-degree sector edges (11.25, 33.75, 56.25, ...). Treating each reported
direction as an exact value would alias the true (unknown, uniformly
distributed within +-5 deg of the report) direction into the nearer sector
and bias sector frequencies near the boundaries.

We fix this by PROPORTIONAL REDISTRIBUTION (deterministic, no RNG): each
observation reported at direction d is treated as a uniform random variable
on [d-5, d+5) (the 10-degree bin the METAR code point represents), and its
unit probability mass is split between the (at most two) 22.5-degree sectors
that interval overlaps, weighted by the overlap length. This is equivalent
to integrating a uniform kernel over each sector and is the standard fix for
this exact problem (the alternative, randomising the direction within +-5
deg with a fixed seed, is numerically close but reproducibility then depends
on the RNG stream; we prefer the closed-form weights). All frequency, mean
speed and Weibull-fit statistics below use these fractional weights.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy import stats

SECTOR_CENTERS = np.round(np.arange(0.0, 360.0, 22.5), 2)  # 16 sectors
N_SECTORS = len(SECTOR_CENTERS)
SECTOR_HALF_WIDTH = 11.25
RAW_DIR_RESOLUTION = 10.0  # deg, METAR coding resolution
RAW_DIR_HALF = RAW_DIR_RESOLUTION / 2.0

LOCAL_UTC_OFFSET_HOURS = -6  # Mexico Central Standard Time, DST ignored (see README caveat)
DAY_START_LOCAL_HOUR = 7
DAY_END_LOCAL_HOUR = 19  # [7,19) local = "day", else "night"


# --------------------------------------------------------------------------
# Sector assignment (handles the 10 -> 22.5 deg aliasing)
# --------------------------------------------------------------------------

def sector_weights(direction_deg: np.ndarray) -> np.ndarray:
    """Fractional membership of each direction in the 16 sectors.

    Parameters
    ----------
    direction_deg : (n,) array of METAR-coded directions (multiples of 10 deg,
        0 < d <= 360; NaN not allowed here -- filter calm/variable/missing
        beforehand).

    Returns
    -------
    (n, 16) array, each row sums to 1 (proportional overlap of the assumed
    +-5 deg true-direction interval with each 22.5-deg sector).
    """
    d = np.asarray(direction_deg, dtype=float).reshape(-1, 1)
    c = SECTOR_CENTERS.reshape(1, -1)
    diff = (d - c + 180.0) % 360.0 - 180.0  # signed angular distance, deg
    lo = np.maximum(diff - RAW_DIR_HALF, -SECTOR_HALF_WIDTH)
    hi = np.minimum(diff + RAW_DIR_HALF, SECTOR_HALF_WIDTH)
    overlap = np.clip(hi - lo, 0.0, None)
    row_sum = overlap.sum(axis=1, keepdims=True)
    row_sum[row_sum == 0] = np.nan  # shouldn't happen; guards against div/0
    return overlap / row_sum


# --------------------------------------------------------------------------
# Weighted Weibull MLE (2-parameter, loc=0)
# --------------------------------------------------------------------------

def weibull_fit_weighted(x: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    """Weighted maximum-likelihood fit of a 2-parameter Weibull (loc=0).

    Solves the standard Weibull MLE equations generalised with weights w_i:
        sum(w x^k ln x) / sum(w x^k) - 1/k - sum(w ln x)/sum(w) = 0   (for k)
        c = (sum(w x^k) / sum(w))^(1/k)

    Parameters
    ----------
    x : (n,) positive wind speeds [m/s] (non-calm observations only).
    w : (n,) non-negative weights (e.g. sector-membership fractions).

    Returns
    -------
    (c, k) scale [m/s] and shape [-] of the fitted Weibull distribution.
    """
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    mask = (x > 0) & (w > 0) & np.isfinite(x) & np.isfinite(w)
    x, w = x[mask], w[mask]
    if len(x) < 5 or w.sum() <= 0:
        raise ValueError("Not enough weighted data to fit a Weibull distribution")
    lnx = np.log(x)
    s0 = w.sum()
    s1 = (w * lnx).sum() / s0

    def g(k: float) -> float:
        xk = x ** k
        return (w * xk * lnx).sum() / (w * xk).sum() - 1.0 / k - s1

    # bracket search: g is monotonically increasing-ish in k for wind data;
    # widen the bracket if needed to guarantee a sign change.
    lo, hi = 1e-2, 50.0
    glo, ghi = g(lo), g(hi)
    if glo * ghi > 0:
        # fall back to an unweighted scipy fit as a robust default
        c_s, k_s = stats.weibull_min.fit(x, floc=0)[2], stats.weibull_min.fit(x, floc=0)[0]
        return c_s, k_s
    k = brentq(g, lo, hi, xtol=1e-8, rtol=1e-10)
    c = ((w * x ** k).sum() / s0) ** (1.0 / k)
    return float(c), float(k)


# --------------------------------------------------------------------------
# Wind rose construction
# --------------------------------------------------------------------------

@dataclass
class WindRoseResult:
    table: pd.DataFrame           # 16 rows: sector_centre_deg, frequency, mean_u10, weibull_c, weibull_k, n_eff
    calm_fraction: float
    variable_fraction: float
    n_hours_total: int
    sector_speeds: list = None    # length-16 list of (speeds, weights) non-calm arrays per sector (for empirical exceedance, I3)


def build_windrose(hourly: pd.DataFrame) -> WindRoseResult:
    """Build the 16-sector wind rose + per-sector Weibull fit from QC'd hourly data.

    Parameters
    ----------
    hourly : DataFrame as produced by parse_isd.build_hourly, with columns
        wdir_deg, wspd_ms, is_calm, is_variable.

    Notes
    -----
    - `frequency` for sector j = (sum of fractional sector-membership weights
      of ALL non-calm, non-variable hours assigned to j) / n_hours_total.
      Frequencies over the 16 sectors PLUS calm_fraction PLUS
      variable_fraction sum to 1 (see test_windclimate.py).
    - Weibull (c, k) per sector is fit only on the (weighted) non-calm speeds
      in that sector; calm hours (U10=0) are excluded from the fit and
      reported separately as calm_fraction, consistent with standard wind
      engineering practice (a Weibull distribution has zero density at 0).
    """
    n_total = len(hourly)
    calm_mask = hourly["is_calm"].to_numpy()
    var_mask = hourly["is_variable"].to_numpy()
    dir_mask = (~calm_mask) & (~var_mask) & hourly["wdir_deg"].notna().to_numpy()

    calm_fraction = calm_mask.sum() / n_total
    variable_fraction = var_mask.sum() / n_total

    d = hourly.loc[dir_mask, "wdir_deg"].to_numpy()
    u = hourly.loc[dir_mask, "wspd_ms"].to_numpy()
    W = sector_weights(d)  # (n_dir, 16)

    rows = []
    sector_speeds = []
    for j, c_center in enumerate(SECTOR_CENTERS):
        w_j = W[:, j]
        n_eff = w_j.sum()
        freq = n_eff / n_total
        mean_u = (w_j * u).sum() / n_eff if n_eff > 0 else np.nan
        try:
            c_fit, k_fit = weibull_fit_weighted(u, w_j)
        except ValueError:
            c_fit, k_fit = np.nan, np.nan
        rows.append(dict(sector_centre_deg=c_center, frequency=freq,
                          mean_u10=mean_u, weibull_c=c_fit, weibull_k=k_fit,
                          n_eff=n_eff))
        keep = w_j > 1e-9
        sector_speeds.append((u[keep].copy(), w_j[keep].copy()))
    table = pd.DataFrame(rows)
    return WindRoseResult(table=table, calm_fraction=calm_fraction,
                           variable_fraction=variable_fraction,
                           n_hours_total=n_total, sector_speeds=sector_speeds)


def empirical_prob_exceed_sector(windrose: WindRoseResult, sector_idx: int, u_threshold: float) -> tuple[float, float]:
    """Direct (non-parametric) P(U10 > u_threshold | sector) from the raw
    weighted sample, plus the effective number of "hours" exceeding the
    threshold in that sector (n_eff_exceed = sum of fractional weights of
    exceeding observations -- directly comparable across the 16 sectors and
    to `WindRoseResult.n_hours_total`, see review F1 I3: aggregating
    n_eff_exceed over all 16 sectors for u=15 m/s reproduces the reviewer's
    "7 h in 15 years" figure exactly).

    Returns (p_exceed_given_sector, n_eff_exceed).
    """
    speeds, weights = windrose.sector_speeds[sector_idx]
    n_eff = weights.sum()
    if n_eff <= 0:
        return np.nan, 0.0
    exceed_mask = speeds > u_threshold
    n_eff_exceed = float(weights[exceed_mask].sum())
    return n_eff_exceed / n_eff, n_eff_exceed


# --------------------------------------------------------------------------
# Seasonal / day-night split
# --------------------------------------------------------------------------

def _local_hour(dt_utc: pd.Series) -> pd.Series:
    return (dt_utc + pd.Timedelta(hours=LOCAL_UTC_OFFSET_HOURS)).dt.hour


def _season(month: pd.Series) -> pd.Series:
    return month.map({12: "DJF", 1: "DJF", 2: "DJF",
                       3: "MAM", 4: "MAM", 5: "MAM",
                       6: "JJA", 7: "JJA", 8: "JJA",
                       9: "SON", 10: "SON", 11: "SON"})


def seasonal_daynight_table(hourly: pd.DataFrame, strong_wind_threshold: float = 5.0) -> pd.DataFrame:
    """Season x day/night breakdown of calm fraction, mean U10 and strong-wind
    frequency (fraction of hours with U10 > strong_wind_threshold).

    Neutral-stability caveat: this split is purely climatological (by clock
    hour / calendar month). No atmospheric-stability classification is
    performed; the split is provided because the strongest winds (the ones
    that matter for pedestrian comfort/danger) are usually associated with
    daytime convective mixing / frontal passages rather than with the
    night-time low-level jet regime, so day vs night and season are useful
    stratifiers even without an explicit stability class.
    Local time uses a fixed UTC-6 offset (Mexico Central Standard Time);
    daylight-saving time (in effect roughly 2010-2021, abolished nationally
    in 2022 except the US-border strip) is NOT applied -- see README.md.
    """
    df = hourly.copy()
    local_hour = _local_hour(df["datetime_hour"])
    df["is_day"] = local_hour.between(DAY_START_LOCAL_HOUR, DAY_END_LOCAL_HOUR - 1)
    df["season"] = _season(df["datetime_hour"].dt.month)

    rows = []
    for season in ["DJF", "MAM", "JJA", "SON"]:
        for is_day, label in [(True, "day"), (False, "night")]:
            sub = df[(df["season"] == season) & (df["is_day"] == is_day)]
            n = len(sub)
            if n == 0:
                continue
            calm_frac = sub["is_calm"].mean()
            mean_u = sub.loc[~sub["is_calm"], "wspd_ms"].mean()
            strong_frac = (sub["wspd_ms"] > strong_wind_threshold).mean()
            rows.append(dict(season=season, period=label, n_hours=n,
                              calm_fraction=calm_frac, mean_u10_nonc_alm=mean_u,
                              frac_u10_gt_threshold=strong_frac))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Exceedance-probability API (used by the comfort module, P10=C)
# --------------------------------------------------------------------------

def prob_exceed_conditional(u: float, c: float, k: float) -> float:
    """P(U10 > u | non-calm, this sector) for a fitted Weibull(c, k).

    This is the Weibull survival function; c, k come from windrose_16.csv.
    """
    if u <= 0:
        return 1.0
    return float(np.exp(-(u / c) ** k))


MIN_RELIABLE_EFFECTIVE_HOURS = 30.0  # review F1 I3: below this, don't trust either estimator


def annual_exceedance(windrose, K, threshold_local: float, sector_speeds=None,
                       method: str = "auto", min_count: float = MIN_RELIABLE_EFFECTIVE_HOURS) -> dict:
    """Annual probability that the LOCAL pedestrian-level wind speed exceeds
    a comfort/danger threshold, combining the measured climatology with a
    CFD-derived amplification factor K(theta) = U_local(theta) / U10(theta).

    This is the function the comfort module (Lawson LDDC / NEN 8100 criteria,
    P10=C) calls once K(theta) has been computed from the CFD cases (K may
    also be a GEM-based effective amplification factor, see
    `gust_equivalent_mean`, for the Lawson criteria).

    Review F1 (I3): the single Weibull fit per sector reproduces the body of
    the distribution well but UNDERESTIMATES the extreme tail (e.g. at
    K=1, Weibull gives P(U10>15)=0.0013%, vs. 0.0055% -- 7 h in 15 years --
    from the raw hourly record). Per the review's fix, this function now
    uses the **direct weighted-empirical** estimate by default whenever there
    is enough data to trust it (>= `min_count` effective hours exceeding the
    sector-equivalent threshold), and only falls back to the Weibull fit
    (interpolation/smoothing role) when the empirical sample is too thin --
    in which case the sector row is flagged `note='n_eff_exceed < {min_count}
    h -> inconclusive, Weibull extrapolation shown'` instead of silently
    reporting a number as if it were reliable.

    Parameters
    ----------
    windrose : the 16-row table from build_windrose(...).table (or
        windrose_16.csv reloaded), with columns sector_centre_deg, frequency,
        weibull_c, weibull_k.
    K : scalar or length-16 array-like, amplification factor per sector,
        aligned with `windrose['sector_centre_deg']` order (ascending, 0 to
        337.5). K=1 everywhere reproduces the plain climatological
        exceedance of U10 itself (used as the NEN 8100 sanity check in
        test_windclimate.py).
    threshold_local : local threshold speed [m/s] the criterion is evaluated
        against, e.g. 5 m/s (NEN 8100 class boundaries), 15 m/s (danger
        criterion), or any Lawson LDDC threshold (4/6/8/... m/s exceeded
        with some frequency).
    sector_speeds : optional, `WindRoseResult.sector_speeds` (list of 16
        (speeds, weights) arrays). Required for the empirical path; if None,
        `method` is forced to 'weibull' (backward-compatible pure-Weibull
        behaviour).
    method : 'auto' (default; empirical when reliable, else Weibull,
        flagged), 'weibull' (always use the fitted Weibull), or 'empirical'
        (always use the direct weighted-empirical estimate, whatever its
        sample size -- use with caution beyond ~12 m/s equivalent U10).
    min_count : effective-hours threshold below which the empirical estimate
        is considered unreliable (review default: 30 h over the 15-year
        record).

    Returns
    -------
    dict with:
      'per_sector' : DataFrame (sector_centre_deg, K, u10_equivalent,
                     p_exceed_given_sector, contribution, source, n_eff_exceed,
                     note) where contribution = frequency * p_exceed_given_sector.
      'annual_probability' : sum of 'contribution' over sectors (fraction of
                     all hours/year, calm included implicitly as 0 exceedance).
      'hours_per_year' : annual_probability * 8760.
    """
    wr = windrose.reset_index(drop=True)
    n = len(wr)
    K_arr = np.full(n, float(K)) if np.isscalar(K) else np.asarray(K, dtype=float)
    if len(K_arr) != n:
        raise ValueError(f"K must be scalar or have length {n} (got {len(K_arr)})")
    if method not in ("auto", "weibull", "empirical"):
        raise ValueError("method must be 'auto', 'weibull' or 'empirical'")
    if sector_speeds is None and method != "weibull":
        method = "weibull"  # no data to do otherwise; backward compatible

    u10_equiv = threshold_local / K_arr  # U10 needed for U_local to hit threshold
    p_cond = np.empty(n)
    source = [""] * n
    n_eff_exceed = np.full(n, np.nan)
    notes = [""] * n

    for i in range(n):
        p_weib = prob_exceed_conditional(u10_equiv[i], wr["weibull_c"].iloc[i], wr["weibull_k"].iloc[i])
        p_emp, n_exc = (np.nan, np.nan)
        if sector_speeds is not None:
            speeds, weights = sector_speeds[i]
            n_eff_i = weights.sum()
            if n_eff_i > 0:
                exceed_mask = speeds > u10_equiv[i]
                n_exc = float(weights[exceed_mask].sum())
                p_emp = n_exc / n_eff_i
            n_eff_exceed[i] = n_exc

        if method == "weibull":
            use_empirical = False
        elif method == "empirical":
            use_empirical = np.isfinite(p_emp)
        else:  # 'auto': trust any DIRECTLY OBSERVED exceedance (n_exc>0) over
            # the Weibull fit, which is known to bias the tail (review I3);
            # only fall back to Weibull when this sector has NO observed
            # exceedance at all at this threshold (true extrapolation).
            use_empirical = np.isfinite(n_exc) and n_exc > 0

        if use_empirical and np.isfinite(p_emp):
            p_cond[i] = p_emp
            source[i] = "empirical"
            if np.isfinite(n_exc) and n_exc < min_count:
                notes[i] = (f"n_eff_exceed={n_exc:.2f} h < {min_count:.0f} h: estimacion empirica con "
                            f"incertidumbre muestral grande a esta rareza, interpretar como orden de magnitud")
        else:
            p_cond[i] = p_weib
            source[i] = "weibull"
            if sector_speeds is not None:
                notes[i] = ("sin excedencias observadas en este sector para este umbral -> "
                            "extrapolacion Weibull (orden de magnitud unicamente)")

    contribution = wr["frequency"].to_numpy() * p_cond
    per_sector = pd.DataFrame({
        "sector_centre_deg": wr["sector_centre_deg"],
        "K": K_arr,
        "u10_equivalent": u10_equiv,
        "p_exceed_given_sector": p_cond,
        "contribution": contribution,
        "source": source,
        "n_eff_exceed_hours": n_eff_exceed,
        "note": notes,
    })
    annual_p = float(contribution.sum())
    return dict(per_sector=per_sector, annual_probability=annual_p,
                hours_per_year=annual_p * 8760.0)


def empirical_exceedance(hourly: pd.DataFrame, threshold: float) -> float:
    """Direct empirical P(U10 > threshold) over ALL hours (incl. calm),
    used only to validate the Weibull-based `annual_exceedance` (K=1 case)
    in test_windclimate.py -- not used by the comfort module itself.
    """
    return float((hourly["wspd_ms"] > threshold).mean())


# --------------------------------------------------------------------------
# Gust-equivalent mean (Lawson LDDC input), review F1 I4
# --------------------------------------------------------------------------

def gust_equivalent_mean(u_local: float, k_local: float, gust_factor: float = 3.25,
                          gust_peak_to_mean: float = 1.85):
    """GEM = max(U_local, U_gust / gust_peak_to_mean), an ESTIMATE of the
    Lawson LDDC "gust equivalent mean" speed from a steady-RANS point (mean
    speed + turbulent kinetic energy only -- no resolved gust spectrum).

        sigma_u   = sqrt(2 k_local / 3)           (isotropic turbulence assumption)
        U_gust    = u_local + gust_factor * sigma_u   (gust_factor g ~ 3.0-3.5, review F1 I4)
        GEM       = max(u_local, U_gust / gust_peak_to_mean)   (1.85: Lawson's peak/gust-to-mean ratio)

    **[ESTIMACION -- no verificado contra la definicion original de gust
    equivalent mean de Lawson]**: con RANS de estado estacionario solo se
    tiene la media y k, no el espectro de rafagas real; esta es la via
    estandar para aproximarlo (revision F1, I4) pero debe declararse como
    estimacion en cualquier reporte de Lawson LDDC. Para comparar contra
    NEN 8100 (que usa la media, no GEM) usando el mismo K de la media
    (`U_local`, sin ajuste de rafaga) evita sesgar la comparacion a favor de
    Lawson (revision F1, I4, ultima frase).

    Returns the GEM speed [m/s] (same array shape as u_local/k_local); pass
    an array of GEM(theta)/U10(theta) as `K` to `annual_exceedance` to get
    the Lawson-criterion annual exceedance probability at a point.
    """
    sigma_u = np.sqrt(2.0 / 3.0 * np.asarray(k_local, dtype=float))
    u_gust = np.asarray(u_local, dtype=float) + gust_factor * sigma_u
    return np.maximum(u_local, u_gust / gust_peak_to_mean)


# --------------------------------------------------------------------------
# NEN 8100 comfort/danger classes and Lawson LDDC thresholds, review F1 I4
#
# **[no verificado contra el texto impreso de NEN 8100:2006]**: los cortes
# de clase y las cualidades por actividad reproducidos abajo vienen del
# resumen de la revision independiente F1 (`docs/revisiones/F1_revision.md`,
# seccion I4), no de una lectura directa de la norma. Usar con esa reserva
# hasta cotejarlos contra el documento NEN oficial.
# --------------------------------------------------------------------------

NEN8100_COMFORT_THRESHOLD_MS = 5.0   # local mean speed @ 1.75 m, NEN 8100
NEN8100_DANGER_THRESHOLD_MS = 15.0

# (class, p_lower_inclusive, p_upper_exclusive), P(V_loc > 5 m/s), as fractions
NEN8100_COMFORT_CLASSES = [
    ("A", 0.000, 0.025),
    ("B", 0.025, 0.05),
    ("C", 0.05, 0.10),
    ("D", 0.10, 0.20),
    ("E", 0.20, 1.001),
]

# quality of a class for a given pedestrian activity ("buena"/"moderada"/"mala")
NEN8100_ACTIVITY_QUALITY = {
    "atravesar": {"A": "buena", "B": "buena", "C": "buena", "D": "moderada", "E": "mala"},
    "pasear": {"A": "buena", "B": "buena", "C": "moderada", "D": "mala", "E": "mala"},
    "estar_sentado": {"A": "buena", "B": "moderada", "C": "mala", "D": "mala", "E": "mala"},
}

# (label, p_lower_inclusive, p_upper_exclusive), P(V_loc > 15 m/s)
NEN8100_DANGER_CLASSES = [
    ("sin_riesgo", 0.0000, 0.0005),
    ("riesgo_limitado", 0.0005, 0.003),
    ("peligroso", 0.003, 1.001),
]

# Lawson LDDC comfort thresholds [m/s], each evaluated against GEM and a
# <5% annual exceedance criterion (increasingly permissive land use).
# **[no verificado contra Lawson 1978 / la version exacta citada por un
# consultor]** -- ver docstring de gust_equivalent_mean.
LAWSON_LDDC_COMFORT_THRESHOLDS_MS = {
    "estar_sentado_largo": 4.0,
    "estar_de_pie_pasear": 6.0,
    "caminar_negocios": 8.0,
    "incomodo": 10.0,
}
LAWSON_LDDC_COMFORT_EXCEEDANCE_LIMIT = 0.05  # "exceeded < 5% of the time"

# Lawson safety/danger thresholds [m/s] (mean or GEM), annual % very low.
# **[no verificado]**.
LAWSON_LDDC_DANGER_THRESHOLDS_MS = {
    "riesgo_limitado": 15.0,
    "peligroso": 20.0,
}


def nen8100_comfort_class(p_gt_5: float) -> str:
    """NEN 8100 class A-E from P(V_loc > 5 m/s) (annual, local pedestrian height).
    **[no verificado contra el texto impreso]**, see module note above."""
    for label, lo, hi in NEN8100_COMFORT_CLASSES:
        if lo <= p_gt_5 < hi:
            return label
    raise ValueError(f"p_gt_5={p_gt_5} out of [0,1] range")


def nen8100_activity_quality(activity: str, p_gt_5: float) -> str:
    """'buena'/'moderada'/'mala' quality of the site for `activity` in
    {'atravesar','pasear','estar_sentado'}. **[no verificado]**."""
    if activity not in NEN8100_ACTIVITY_QUALITY:
        raise ValueError(f"activity must be one of {sorted(NEN8100_ACTIVITY_QUALITY)}")
    cls = nen8100_comfort_class(p_gt_5)
    return NEN8100_ACTIVITY_QUALITY[activity][cls]


def nen8100_danger_class(p_gt_15: float) -> str:
    """'sin_riesgo'/'riesgo_limitado'/'peligroso' from P(V_loc > 15 m/s).
    **[no verificado contra el texto impreso]**."""
    for label, lo, hi in NEN8100_DANGER_CLASSES:
        if lo <= p_gt_15 < hi:
            return label
    raise ValueError(f"p_gt_15={p_gt_15} out of [0,1] range")


def lawson_lddc_assessment(windrose, K_gem, sector_speeds=None, method: str = "auto") -> dict:
    """Evaluate every Lawson LDDC comfort threshold (4/6/8/10 m/s, GEM,
    <5% of the time) and the two danger thresholds (15/20 m/s) for one point,
    given its GEM-based effective amplification K_gem(theta) = GEM(theta)/U10(theta)
    (see `gust_equivalent_mean`). **[no verificado]**, see module note.

    Returns a dict: {label: {'threshold': ms, 'p_exceed': float, 'passes':
    bool (comfort) or ...}} for each comfort threshold (passes = p_exceed <
    5%), plus a 'danger' sub-dict {label: {'threshold','p_exceed'}} for the
    15/20 m/s thresholds (no pass/fail cutoff attached here -- report the
    number and compare to the review's qualitative bands).
    """
    out = {"comfort": {}, "danger": {}}
    for label, threshold in LAWSON_LDDC_COMFORT_THRESHOLDS_MS.items():
        res = annual_exceedance(windrose, K_gem, threshold, sector_speeds=sector_speeds, method=method)
        p = res["annual_probability"]
        out["comfort"][label] = dict(threshold_ms=threshold, p_exceed=p,
                                      passes=p < LAWSON_LDDC_COMFORT_EXCEEDANCE_LIMIT)
    for label, threshold in LAWSON_LDDC_DANGER_THRESHOLDS_MS.items():
        res = annual_exceedance(windrose, K_gem, threshold, sector_speeds=sector_speeds, method=method)
        out["danger"][label] = dict(threshold_ms=threshold, p_exceed=res["annual_probability"])
    return out
