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
    table = pd.DataFrame(rows)
    return WindRoseResult(table=table, calm_fraction=calm_fraction,
                           variable_fraction=variable_fraction,
                           n_hours_total=n_total)


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


def annual_exceedance(windrose: pd.DataFrame, K, threshold_local: float) -> dict:
    """Annual probability that the LOCAL pedestrian-level wind speed exceeds
    a comfort/danger threshold, combining the measured climatology with a
    CFD-derived amplification factor K(theta) = U_local(theta) / U10(theta).

    This is the function the comfort module (Lawson LDDC / NEN 8100 criteria,
    P10=C) calls once K(theta) has been computed from the CFD cases.

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

    Returns
    -------
    dict with:
      'per_sector' : DataFrame (sector_centre_deg, K, u10_equivalent,
                     p_exceed_given_sector, contribution) where
                     contribution = frequency * p_exceed_given_sector.
      'annual_probability' : sum of 'contribution' over sectors (fraction of
                     all hours/year, calm included implicitly as 0 exceedance).
      'hours_per_year' : annual_probability * 8760.
    """
    wr = windrose.reset_index(drop=True)
    n = len(wr)
    K_arr = np.full(n, float(K)) if np.isscalar(K) else np.asarray(K, dtype=float)
    if len(K_arr) != n:
        raise ValueError(f"K must be scalar or have length {n} (got {len(K_arr)})")

    u10_equiv = threshold_local / K_arr  # U10 needed for U_local to hit threshold
    p_cond = np.array([
        prob_exceed_conditional(u10_equiv[i], wr["weibull_c"].iloc[i], wr["weibull_k"].iloc[i])
        for i in range(n)
    ])
    contribution = wr["frequency"].to_numpy() * p_cond
    per_sector = pd.DataFrame({
        "sector_centre_deg": wr["sector_centre_deg"],
        "K": K_arr,
        "u10_equivalent": u10_equiv,
        "p_exceed_given_sector": p_cond,
        "contribution": contribution,
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
