"""
parse_isd.py -- Ingest NOAA ISD / Global Hourly CSV files for the ZT wind
climatology and turn them into a QC'd, deduplicated, one-record-per-hour
table per station.

Data source
-----------
NOAA NCEI ISD ("Integrated Surface Database") / Global Hourly access files:
    https://www.ncei.noaa.gov/data/global-hourly/access/<year>/<USAF+WBAN>.csv
Station ids used here (verified against NOAA's isd-history.csv on 2026-09-28,
see E:\\PINN\\v2\\data\\raw\\climate\\isd-history.csv):

    MMMY  General Mariano Escobedo Intl / Monterrey Intl   USAF=763943 WBAN=99999
          -> combined id 76394399999   lat +25.778  lon -100.107  elev 389.5 m
          record BEGIN 1990-06-01, END (metadata) 2025-08-24
    MMAN  Del Norte Intl (secondary GA airport, Monterrey)  USAF=763940 WBAN=99999
          -> combined id 76394099999   lat +25.866  lon -100.237  elev 449.9 m
          record BEGIN 1973-01-01, END (metadata) 2025-08-24

MMMY is used as the PRIMARY reference station: it is the WMO/ICAO
international airport, matches the P14=A convention (U10 = mean wind at 10 m
over open terrain / airport), and its METAR record is essentially complete
and consistently coded (FM-15/FM-16 only, no SOD/SOM summaries) for 2010-2025.
MMAN is kept as a secondary cross-check station (same valley, different
exposure/orography) -- see README.md for the comparison.

WND field (ISD fixed fields), comma separated:
    direction (3 digits, deg true, 999 = missing),
    direction quality code (1 char),
    type code (1 char): N=normal, C=calm, V=variable, 9=missing,
                          (also A/B/H/Q/R/T for Beaufort/averaged reports,
                           not seen in this station's record),
    speed rate (4 digits, m/s x10, 9999 = missing),
    speed quality code (1 char).

ISD quality code domain (both direction and speed):
    0 = passed gross limits check
    1 = passed all quality control checks
    2 = suspect
    3 = erroneous
    4 = passed gross limits check, data from an NCEI data source
    5 = passed all quality control checks, data from an NCEI data source
    6 = suspect, data from an NCEI data source
    7 = erroneous, data from an NCEI data source
    9 = passed gross limits check if element is present (also used as the
        "not applicable" flag for direction when type=='C', calm)
GOOD = {'0', '1', '4', '5', '9'}; REJECT = {'2', '3', '6', '7'}.

Anemometer height: NOT stated per-station in ISD metadata. Assumed 10 m AGL
(WMO/ICAO standard exposure for airport anemometers) -- UNVERIFIED for these
two stations specifically; flagged as a caveat in README.md.

METAR direction rounding: directions are coded in the WND field at 10-degree
resolution (confirmed empirically: >99.9% of MMMY 2023 directions are exact
multiples of 10), while speed is reported in whole knots and converted to
m/s x10 by NOAA (so speed also comes in a discrete, non-uniform grid, e.g.
10, 15, 21, 26, 31, 36 ... for 2, 3, 4, 5, 6, 7 kt). Both are climatological
resolution limitations, not errors; they are handled downstream (see
windclimate.py: sector aliasing is handled by proportional redistribution of
each 10-degree direction across the two neighbouring 22.5-degree sectors it
overlaps).
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

RAW_DIR = r"E:\PINN\v2\data\raw\climate"
CACHE_DIR = r"E:\PINN\v2\climate\cache"

STATIONS = {
    "MMMY": dict(combined_id="76394399999", folder="MMMY_76394399999",
                 name="Gen. Mariano Escobedo Intl (Monterrey Intl)",
                 lat=25.778489, lon=-100.106878, elev_m=389.53,
                 role="primary"),
    "MMAN": dict(combined_id="76394099999", folder="MMAN_76394099999",
                 name="Del Norte Intl (Monterrey)",
                 lat=25.866, lon=-100.237, elev_m=449.9,
                 role="secondary"),
}

GOOD_Q = {"0", "1", "4", "5", "9"}

# Priority for keeping one record per hour when several report types coexist
# in the same clock hour (METAR + SPECI, etc.)
REPORT_TYPE_PRIORITY = {"FM-15": 0, "FM-16": 1, "FM-12": 2, "SAO": 3}


def _report_priority(rt: str) -> int:
    return REPORT_TYPE_PRIORITY.get(rt, 99)


def _parse_wnd(wnd: pd.Series) -> pd.DataFrame:
    """Split the raw WND field into typed columns with ISD missing codes as NaN."""
    parts = wnd.str.split(",", expand=True)
    parts.columns = ["dir_raw", "dir_q", "wtype", "spd_raw", "spd_q"]
    out = pd.DataFrame(index=wnd.index)
    out["wdir_deg"] = pd.to_numeric(parts["dir_raw"], errors="coerce")
    out.loc[out["wdir_deg"] >= 999, "wdir_deg"] = np.nan
    out["dir_q"] = parts["dir_q"]
    out["wtype"] = parts["wtype"]
    spd = pd.to_numeric(parts["spd_raw"], errors="coerce") / 10.0
    spd[parts["spd_raw"] == "9999"] = np.nan
    out["wspd_ms"] = spd
    out["spd_q"] = parts["spd_q"]
    return out


def load_station_raw(station: str, years: list[int]) -> pd.DataFrame:
    """Read raw ISD CSVs for one station/years, parse WND, apply ISD QC flags.

    Returns one row per *retained raw record* (i.e. before hourly dedup),
    with columns: datetime (UTC, tz-naive), report_type, wdir_deg, wtype,
    wspd_ms, qc_flag ('ok'/'reject_dirq'/'reject_spdq'/'reject_missing').
    """
    meta = STATIONS[station]
    frames = []
    for yr in years:
        path = os.path.join(RAW_DIR, meta["folder"], f"{yr}.csv")
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path, dtype=str, usecols=["DATE", "REPORT_TYPE", "WND"])
        df["datetime"] = pd.to_datetime(df["DATE"], utc=False)
        wnd = _parse_wnd(df["WND"])
        df = pd.concat([df[["datetime", "REPORT_TYPE"]], wnd], axis=1)
        df["year_file"] = yr
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True)
    raw = raw.rename(columns={"REPORT_TYPE": "report_type"})

    # --- QC classification -------------------------------------------------
    qc = np.full(len(raw), "ok", dtype=object)

    # missing wind entirely
    qc[raw["wtype"].isin(["9"]) | raw["wtype"].isna()] = "reject_missing_type"

    # direction quality: only enforced when a direction is actually reported
    has_dir = raw["wdir_deg"].notna()
    bad_dirq = has_dir & (~raw["dir_q"].isin(GOOD_Q))
    qc[bad_dirq & (qc == "ok")] = "reject_dirq"

    # speed quality: always enforced (calm hours have spd_q too, usually '1')
    bad_spdq = ~raw["spd_q"].isin(GOOD_Q)
    qc[bad_spdq & (qc == "ok")] = "reject_spdq"

    # speed missing (shouldn't happen once spd_q is good, but guard anyway)
    qc[raw["wspd_ms"].isna() & (qc == "ok")] = "reject_missing_speed"

    raw["qc_flag"] = qc
    return raw


def build_hourly(station: str, years: list[int]) -> pd.DataFrame:
    """QC + dedup raw ISD records into one row per calendar hour (UTC).

    Dedup rule: floor timestamp to the hour (obs at this station are always
    taken ~40-56 min past the hour, i.e. squarely inside that clock hour);
    when >1 record survives QC in the same hour (METAR + SPECI), keep the one
    with the highest-priority report_type (FM-15 > FM-16 > ...), then the
    latest timestamp.

    Output columns: datetime_hour, wdir_deg (NaN for calm/variable/rejected),
    wtype ('N','C','V'), wspd_ms, is_calm (bool), is_variable (bool).
    """
    raw = load_station_raw(station, years)
    if raw.empty:
        return raw
    good = raw[raw["qc_flag"] == "ok"].copy()
    good["datetime_hour"] = good["datetime"].dt.floor("h")
    good["prio"] = good["report_type"].map(_report_priority)
    good = good.sort_values(["datetime_hour", "prio", "datetime"])
    dedup = good.groupby("datetime_hour", as_index=False).first()

    dedup["is_calm"] = dedup["wtype"] == "C"
    dedup["is_variable"] = dedup["wtype"] == "V"
    # For calm hours force direction NaN and speed 0 (should already hold)
    dedup.loc[dedup["is_calm"], "wdir_deg"] = np.nan
    dedup.loc[dedup["is_calm"], "wspd_ms"] = 0.0

    cols = ["datetime_hour", "wdir_deg", "wtype", "wspd_ms", "is_calm", "is_variable"]
    out = dedup[cols].sort_values("datetime_hour").reset_index(drop=True)
    return out


def completeness_by_year(hourly: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """Fraction of expected hours present (post-QC) per calendar year."""
    rows = []
    for yr in years:
        expected = pd.date_range(f"{yr}-01-01", f"{yr+1}-01-01", freq="h",
                                  inclusive="left")
        n_expected = len(expected)
        n_present = hourly["datetime_hour"].dt.year.eq(yr).sum()
        rows.append(dict(year=yr, n_expected=n_expected, n_present=n_present,
                          completeness=n_present / n_expected))
    return pd.DataFrame(rows)


def cache_path(station: str) -> str:
    return os.path.join(CACHE_DIR, f"{station.lower()}_hourly.parquet")


def build_and_cache(station: str, years: list[int]) -> pd.DataFrame:
    os.makedirs(CACHE_DIR, exist_ok=True)
    hourly = build_hourly(station, years)
    hourly.to_parquet(cache_path(station), index=False)
    return hourly


def load_cached(station: str) -> pd.DataFrame:
    return pd.read_parquet(cache_path(station))


if __name__ == "__main__":
    years = list(range(2010, 2025))  # 15 complete years, 2025 partial excluded
    for st in STATIONS:
        hourly = build_and_cache(st, years + [2025])
        comp = completeness_by_year(hourly, years)
        print(f"=== {st} ===")
        print(comp.to_string(index=False))
        n_calm = hourly["is_calm"].sum()
        n_var = hourly["is_variable"].sum()
        print(f"total hours retained: {len(hourly)}  calm: {n_calm} "
              f"({n_calm/len(hourly):.2%})  variable: {n_var} "
              f"({n_var/len(hourly):.2%})")
