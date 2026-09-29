"""
transfer.py -- P14-A two-layer roughness transfer: airport U10 (open terrain)
-> sector-dependent CFD inlet log profile (u*, z0, d).

Written in response to independent review `v2/docs/revisiones/F1_revision.md`,
blocker I2: the only place a "transfer" existed was `ml/export.py:93`
(`u* = U10*kappa/ln((10-d+z0)/z0)`), which applies the STATION's U10 directly
to the URBAN roughness log law -- i.e. it assumes U10 was already measured
over the urban fetch, so it does no transfer at all. That overestimates u*
(and hence K = U_local/U10) by +5 % to +31 % depending on sector z0 (see
`report_transfer_ratios` / `transfer_report_16sectors.csv`, and the review's
own table, both reproduced by `test_transfer.py`).

Method (matches the review's I2 proposal, which is the NEN 8100 / Wieringa
1986 "blending height" method -- the two-layer transfer P10=C/P14=A already
call for in `v2/docs/DATA_CONTRACT.md`):

  1. Station log law (open terrain, z0_station):
         u*_s = kappa * U10,s / ln(10 / z0_station)
  2. Blend to a height z_blend = 60 m where the flow is assumed to have
     forgotten the immediate station exposure but not yet adapted to the
     urban fetch (still using the station's roughness up to that height):
         U_blend = (u*_s / kappa) * ln(z_blend / z0_station)
  3. Re-equilibrate against the SECTOR's regional roughness z0_regional(theta)
     at that same blending height (displacement d_blend = 0 here: the review
     shows its effect at 60 m is <=2 %, so it is dropped for simplicity and
     documented, NOT because d is unimportant at ground level -- see step 4):
         u*_regional(theta) = kappa * U_blend / ln(z_blend / z0_regional)
  4. CFD inlet profile (Richards & Hoxey 1993, matches
     `docs/DATA_CONTRACT.md` exactly, WITH the ground-level displacement
     height d_regional(theta) from Macdonald/Kanda -- this is a DIFFERENT,
     non-zero d than the d_blend=0 used only in step 3):
         U(z)   = (u*_regional / kappa) * ln((z - d_regional + z0_regional) / z0_regional)
         k(z)   = u*_regional^2 / sqrt(Cmu)
         eps(z) = u*_regional^3 / (kappa * (z - d_regional + z0_regional))
         omega(z) = eps(z) / (Cmu * k(z))

Station z0 (z0_station) justification, "open terrain"
-------------------------------------------------------
MMMY (Gen. Mariano Escobedo Intl) is a WMO/ICAO synoptic station; ICAO Annex 3
siting rules require the anemometer to be sited over open, unobstructed
terrain representative of the airfield (grass/paved apron, no buildings/trees
within its exposure sector), which is the WMO "open terrain" exposure class.
WMO Guide No. 8 and Wieringa (1992)/Davenport-Wieringa give z0 ~ 0.01-0.05 m
for that class (short grass to fallow field); we use **z0_station = 0.03 m**
(midpoint, matches `docs/DATA_CONTRACT.md`'s "z0_open ~ 0.03 m"). This is a
literature-standard default for the exposure CLASS, NOT a site-specific
measurement of MMMY's actual land cover (no land-cover raster for the airport
surroundings was analysed here -- that is out of this module's scope, see
`v2/geometry`). Flagged **[no verificado]** at the specific-site level.
The review's optional refinement (a per-sector z0_station from ISD gust
factors, Verkaik 2000) is NOT implemented here (out of scope for this pass);
`ustar_station`/`transfer_factor` accept an explicit `z0_station` override so
it can be wired in later without changing the API.

Known kappa inconsistency (documented, not silently "fixed")
--------------------------------------------------------------
The Macdonald/Kanda morphometry (`v2/geometry/morphometry.py`) that produced
`roughness_16sectors.csv` uses kappa=0.40 (Macdonald 1998's own constant).
This module and `docs/DATA_CONTRACT.md` use **kappa=0.41** (OpenFOAM
default / Richards & Hoxey), consistent with the actual CFD inlet. The two
kappas differ by 2.5 %; per the review (G7) this is an acceptable, documented
simplification, not an error to silently reconcile.

API consumed by `ml/export.py` (I2 says the ML agent will switch to this)
----------------------------------------------------------------------------
- `inflow_for_sector(theta_deg, U10, roughness_row, z0_method) -> InflowResult`
  gives (u_star, z0, d, T) for one sector/method. `export.py` currently
  stores a single (z0, d) for the whole case; it should instead store, per
  case, `InflowResult.z0`, `.d`, `.u_star` (or `.T`, since u* scales linearly
  with U10 -- Reynolds-independence lets it be re-applied at inference time,
  per the review's I2 note) for the (theta, U10) of that case.
- `U_H_over_U10(z0, d, H_ref, ...)` replaces the K-relevant part of
  `export.py`'s `nondim.note` formula: instead of
  `U_H(U10) = (u*/kappa)*ln((h_ref-d+z0)/z0), u* = U10*kappa/ln((10-d+z0)/z0)`
  (no transfer, station z0 == urban z0), use
  `U_H(U10) = (T(theta)*U10/kappa)*ln((h_ref-d+z0)/z0)` with T from this
  module. `K_from_cfd_normalized` performs the full CFD-normalised-output ->
  K conversion in one call.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

KAPPA = 0.41          # Richards & Hoxey / OpenFOAM default; matches DATA_CONTRACT
CMU = 0.09
Z0_STATION_DEFAULT = 0.03   # m, WMO "open terrain" class, see module docstring
Z_BLEND_DEFAULT = 60.0      # m, Wieringa blending height (NEN 8100 method)
D_BLEND = 0.0               # displacement at the blending step ONLY (<=2% effect, review I2)

ROUGHNESS_CSV_OVERTURE = r"E:\PINN\v2\geometry\out\H_best\roughness_16sectors_overture.csv"
ROUGHNESS_CSV_OSM_ONLY = r"E:\PINN\v2\geometry\out\H_best\roughness_16sectors.csv"
ROUGHNESS_CSV_DEFAULT = ROUGHNESS_CSV_OVERTURE

# Primary source switched 2026-09-28 (review F1, G1): the OSM footprints
# underestimate lambda_p by roughly a factor of 2-3 in the N/NE/W/NW sectors
# (incomplete building coverage there) relative to a Google 2.5D raster
# control; Overture (Microsoft+Google+OSM merged, deduplicated) is now the
# primary footprint source for Macdonald. `roughness_16sectors_overture.csv`
# carries BOTH the Overture-based and the original OSM-based z0/d for
# Macdonald (suffixes _overture / _osm) in the same file/row alignment, so
# 'macdonald_osm' below is kept selectable as a sensitivity check against
# the previous (now superseded) primary. The plain `roughness_16sectors.csv`
# (OSM-only, no Overture columns) is kept as `ROUGHNESS_CSV_OSM_ONLY` for
# reference/back-compat but is no longer the default.
#
# z0_control/d_control (EN 1991-1-4 category IV table lookup) are NOT
# per-sector morphometry outputs -- they are fixed constants (z0=1.0 m,
# d=0) regardless of footprint source, so they are hardcoded below rather
# than read from either CSV.
EN1991_CATEGORY_IV_Z0 = 1.0
EN1991_CATEGORY_IV_D = 0.0

# method -> (z0_column, d_column) in ROUGHNESS_CSV_OVERTURE, or None for a
# hardcoded (z0, d) constant pair.
Z0_METHOD_COLUMNS = {
    "macdonald": ("z0_macdonald_overture", "d_macdonald_overture"),   # PRIMARY (P13-B binding model; Overture footprints, G1)
    "macdonald_osm": ("z0_macdonald_osm", "d_macdonald_osm"),          # sensitivity: previous (OSM-only) primary
    "kanda": ("z0_kanda_overture", "d_kanda_overture"),                 # sensitivity model (Overture footprints only, no OSM variant available)
    "control": None,        # EN 1991-1-4 category IV table value, constant
    "en1991-1-4": None,
}


# --------------------------------------------------------------------------
# Core two-layer (blending-height) transfer
# --------------------------------------------------------------------------

def ustar_station(U10: float | np.ndarray, z0_station: float = Z0_STATION_DEFAULT) -> float | np.ndarray:
    """Friction velocity implied by the station's own open-terrain log law."""
    return KAPPA * U10 / np.log(10.0 / z0_station)


def u_blend(U10: float | np.ndarray, z0_station: float = Z0_STATION_DEFAULT,
            z_blend: float = Z_BLEND_DEFAULT) -> float | np.ndarray:
    """Wind speed at the blending height, still on the station's roughness."""
    return U10 * np.log(z_blend / z0_station) / np.log(10.0 / z0_station)


def transfer_factor(z0_regional: float | np.ndarray, z0_station: float = Z0_STATION_DEFAULT,
                     z_blend: float = Z_BLEND_DEFAULT) -> float | np.ndarray:
    """T(theta) = u*_regional / U10,station (blending-height method, d_blend=0).

    T = kappa * ln(z_blend/z0_station) / [ln(10/z0_station) * ln(z_blend/z0_regional)]
    """
    return (KAPPA * np.log(z_blend / z0_station)
            / (np.log(10.0 / z0_station) * np.log(z_blend / z0_regional)))


def transfer_factor_en1991(z0_regional: float | np.ndarray, z0_station: float = Z0_STATION_DEFAULT) -> float | np.ndarray:
    """Control/cross-check: EN 1991-1-4 eq. 4.4-4.5 roughness factor k_r(z0),
    used to derive the same T = u*_regional/U10,station via an independent
    (non-blending-height) route. k_r(z0) = 0.19*(z0/0.05)^0.07.
    """
    def k_r(z0):
        return 0.19 * (z0 / 0.05) ** 0.07
    return KAPPA * k_r(z0_regional) / (k_r(z0_station) * np.log(10.0 / z0_station))


def transfer_factor_naive_export(z0_regional: float | np.ndarray) -> float | np.ndarray:
    """Reproduces the FLAWED formula currently in `ml/export.py` (d=0 case):
    u* = U10*kappa/ln(10/z0_regional), i.e. no station->regional transfer at
    all (treats the station's U10 as if it were already measured within the
    urban fetch). Kept here ONLY so tests can quantify and bound the
    overestimation the review found (+5% to +31%); do not use for the inlet.
    """
    return KAPPA / np.log(10.0 / z0_regional)


def ustar_regional(U10: float | np.ndarray, z0_regional: float | np.ndarray,
                    z0_station: float = Z0_STATION_DEFAULT,
                    z_blend: float = Z_BLEND_DEFAULT) -> float | np.ndarray:
    """u*_regional(theta) for the two-layer transfer, ready to feed the CFD inlet."""
    return transfer_factor(z0_regional, z0_station, z_blend) * U10


def u10m_urban_over_u10_station(z0_regional: float | np.ndarray, z0_station: float = Z0_STATION_DEFAULT,
                                 z_blend: float = Z_BLEND_DEFAULT) -> float | np.ndarray:
    """U(10 m) evaluated on the urban (regional) profile, over U10,station.
    Uses d=0 at 10 m for this diagnostic ratio (reporting only; the real
    inlet profile below 10 m uses the sector's actual d_regional, see
    `inlet_profile`)."""
    T = transfer_factor(z0_regional, z0_station, z_blend)
    return (T / KAPPA) * np.log((10.0 + z0_regional) / z0_regional)


# --------------------------------------------------------------------------
# Per-sector lookup + full inflow result
# --------------------------------------------------------------------------

@dataclass
class InflowResult:
    theta_deg: float
    U10: float
    z0_method: str
    z0_station: float
    z_blend: float
    z0: float          # regional z0(theta) used for the CFD inlet, from roughness table / override
    d: float           # regional displacement height d(theta) used for the CFD inlet (NOT d_blend)
    u_star: float
    T: float           # u_star / U10

    def U_H(self, H_ref: float) -> float:
        """Mean inlet speed at the reference building height H_ref (DATA_CONTRACT log law)."""
        return (self.u_star / KAPPA) * np.log((H_ref - self.d + self.z0) / self.z0)

    def k(self) -> float:
        return self.u_star ** 2 / np.sqrt(CMU)

    def epsilon(self, z: float | np.ndarray) -> float | np.ndarray:
        return self.u_star ** 3 / (KAPPA * (z - self.d + self.z0))

    def omega(self, z: float | np.ndarray) -> float | np.ndarray:
        return self.epsilon(z) / (CMU * self.k())

    def inlet_profile(self, z: np.ndarray) -> dict:
        """Richards & Hoxey inlet profile at height(s) z (DATA_CONTRACT formula).

        Raises ValueError if any z is at/below the displacement height
        (z - d + z0 <= 0), where the log law is undefined. This is a real
        constraint here: d_macdonald (Overture footprints, primary since
        review F1 G1) is ~3.4-5.3 m in EVERY sector of
        `roughness_16sectors_overture.csv`, ABOVE pedestrian height (1.75 m, NEN 8100).
        This function describes the domain-INLET boundary condition (the
        undisturbed upstream approach flow imposed at the inlet patch, from
        z=0 at that patch up to the domain top) -- it is NOT the near-ground
        velocity field inside the urban canopy around the buildings of
        interest, which instead comes from the CFD solution itself
        (u/U_H field, see DATA_CONTRACT). Do not call this at pedestrian
        height to get a "local" speed; use K = U_local/U10 from the CFD
        output instead (`K_from_cfd_normalized`).
        """
        z = np.asarray(z, dtype=float)
        zshift = z - self.d + self.z0
        if np.any(zshift <= 0):
            raise ValueError(
                "z - d + z0 <= 0 for at least one requested height: the "
                "Richards & Hoxey log law is undefined at/below the "
                "displacement height. This profile is the domain-inlet "
                "boundary condition (undisturbed approach flow), not the "
                "near-ground field inside the urban canopy -- see the "
                "inlet_profile docstring."
            )
        U = (self.u_star / KAPPA) * np.log(zshift / self.z0)
        k = np.full_like(z, self.k())
        eps = self.epsilon(z)
        omega = eps / (CMU * k)
        return dict(z=z, u=U, k=k, epsilon=eps, omega=omega)


def load_roughness_table(path: str = ROUGHNESS_CSV_DEFAULT) -> pd.DataFrame:
    """Load the 16-sector roughness table. Defaults to the Overture-based
    file (`ROUGHNESS_CSV_OVERTURE`, primary since review F1 G1); pass
    `ROUGHNESS_CSV_OSM_ONLY` explicitly to load the superseded OSM-only file
    (older schema, no `_overture`/`_osm` suffixes)."""
    df = pd.read_csv(path)
    return df.set_index("theta_deg", drop=False).sort_index()


def inflow_for_sector(theta_deg: float, U10: float, roughness_row,
                       z0_method: str = "macdonald",
                       z0_station: float = Z0_STATION_DEFAULT,
                       z_blend: float = Z_BLEND_DEFAULT) -> InflowResult:
    """Build the full sector inflow (u*, z0, d, T) for the CFD inlet.

    Parameters
    ----------
    theta_deg : sector centre [deg], for bookkeeping only.
    U10 : station reference speed [m/s] (open terrain, MMMY, P14=A).
    roughness_row : a row (dict-like / pandas Series) from
        `roughness_16sectors_overture.csv` (one row of
        `load_roughness_table(...)`), OR any mapping with the columns
        `z0_<method>`, `d_<method>` matching `Z0_METHOD_COLUMNS`.
    z0_method : 'macdonald' (PRIMARY since review F1 G1, Overture footprints,
        P13-B binding model), 'macdonald_osm' (sensitivity: previous,
        OSM-only-footprint primary, kept selectable), 'kanda' (sensitivity
        model, Overture footprints), 'control'/'en1991-1-4' (EN 1991-1-4
        category IV table value, z0=1 m, d=0 -- fixed constant, not read
        from the roughness table).
    """
    if z0_method not in Z0_METHOD_COLUMNS:
        raise ValueError(f"z0_method must be one of {sorted(Z0_METHOD_COLUMNS)}, got {z0_method!r}")
    cols = Z0_METHOD_COLUMNS[z0_method]
    if cols is None:
        z0_regional, d_regional = EN1991_CATEGORY_IV_Z0, EN1991_CATEGORY_IV_D
    else:
        z0_col, d_col = cols
        z0_regional = float(roughness_row[z0_col])
        d_regional = float(roughness_row[d_col])
    T = transfer_factor(z0_regional, z0_station, z_blend)
    u_star = T * U10
    return InflowResult(theta_deg=theta_deg, U10=U10, z0_method=z0_method,
                         z0_station=z0_station, z_blend=z_blend,
                         z0=z0_regional, d=d_regional, u_star=u_star, T=T)


# --------------------------------------------------------------------------
# K (amplification factor) conversion helpers, for ml/export.py
# --------------------------------------------------------------------------

def U_H_over_U10(inflow: InflowResult, H_ref: float) -> float:
    """U_H(reference building height) / U10,station -- the single number
    `ml/export.py` needs to convert a CFD run's non-dimensional output back
    to K = U_local/U10."""
    return inflow.U_H(H_ref) / inflow.U10


def K_from_cfd_normalized(u_over_UH: float | np.ndarray, inflow: InflowResult, H_ref: float) -> float | np.ndarray:
    """K = |U_local|/U10,station, given CFD's own non-dimensional output
    (u_over_UH = |U_local|/U_H, as stored per DATA_CONTRACT) and the sector's
    InflowResult."""
    return u_over_UH * U_H_over_U10(inflow, H_ref)


# --------------------------------------------------------------------------
# Reporting: T ratios per sector for Macdonald / Kanda / control z0
# --------------------------------------------------------------------------

REPORT_METHODS = ["macdonald", "macdonald_osm", "kanda", "control"]  # 'en1991-1-4' is an alias of 'control', skipped


def report_transfer_ratios(roughness_table: pd.DataFrame, z0_station: float = Z0_STATION_DEFAULT,
                            z_blend: float = Z_BLEND_DEFAULT) -> pd.DataFrame:
    """Per-sector u*_regional/U10 (=T) for each z0 source (Macdonald/Overture
    primary, Macdonald/OSM sensitivity, Kanda sensitivity, EN 1991-1-4
    control), by the primary blending-height method and the EN 1991-1-4
    control route, plus the naive `ml/export.py` formula for comparison (to
    quantify its overestimation)."""
    rows = []
    for theta, row in roughness_table.iterrows():
        rec = dict(theta_deg=theta)
        for method in REPORT_METHODS:
            cols = Z0_METHOD_COLUMNS[method]
            if cols is None:
                z0, d = EN1991_CATEGORY_IV_Z0, EN1991_CATEGORY_IV_D
            else:
                z0_col, d_col = cols
                z0 = float(row[z0_col])
                d = float(row[d_col])
            T_blend = transfer_factor(z0, z0_station, z_blend)
            T_en = transfer_factor_en1991(z0, z0_station)
            T_naive = transfer_factor_naive_export(z0)
            rec[f"z0_{method}"] = z0
            rec[f"d_{method}"] = d
            rec[f"T_{method}_blend60"] = T_blend
            rec[f"T_{method}_en1991"] = T_en
            rec[f"T_{method}_export_naive"] = T_naive
            rec[f"export_overestimate_pct_{method}"] = (T_naive / T_blend - 1.0) * 100.0
        rows.append(rec)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    table = load_roughness_table()
    report = report_transfer_ratios(table)
    out_path = os.path.join(os.path.dirname(__file__), "transfer_report_16sectors.csv")
    report.to_csv(out_path, index=False)
    print(f"Wrote {out_path}")
    print(report[["theta_deg", "z0_macdonald", "T_macdonald_blend60",
                   "T_macdonald_en1991", "export_overestimate_pct_macdonald"]].round(4).to_string(index=False))
