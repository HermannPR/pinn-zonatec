"""Build public/data/climate.json: the 16-sector wind rose (frequency,
Weibull c/k) from `climate/windrose_16.csv` plus the per-sector roughness
(z0, d) needed for the P14-A two-layer transfer (`climate/transfer.py`,
method='macdonald', the P13-B primary model since review F1/G1) from
`geometry/out/H_best/roughness_16sectors_overture.csv`. Ported to JS in
public/js/climate.js (transfer_factor, annual_exceedance (Weibull-only,
see note below), NEN 8100, Lawson LDDC).

Run from E:\\PINN\\v2 with the project venv:
    E:\\PINN\\.venv\\Scripts\\python.exe web\\build\\build_climate_assets.py

Note on the empirical-exceedance path: `windclimate.annual_exceedance`
prefers the direct weighted-empirical estimate over the sector's Weibull
fit whenever enough raw hourly observations exist (method='auto', see its
docstring). That needs the FULL per-sector (speeds, weights) arrays from
the 15-year hourly ISD record, which are large and not something a static
site should download. The browser therefore always uses the Weibull fit
(`method='weibull'` in `windclimate.py` terms) -- a documented
simplification, verified in tests/test_climate.py to match
`windclimate.prob_exceed_conditional` / `annual_exceedance(..., method=
'weibull')` exactly (not the 'auto'/'empirical' path).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CLIMATE_DIR, GEOMETRY_OUT, WEB_DATA  # noqa: E402

ROUGHNESS_CSV = GEOMETRY_OUT / "roughness_16sectors_overture.csv"
WINDROSE_CSV = CLIMATE_DIR / "windrose_16.csv"

KAPPA = 0.41
CMU = 0.09
Z0_STATION = 0.03
Z_BLEND = 60.0


def main() -> None:
    wr = pd.read_csv(WINDROSE_CSV)
    rough = pd.read_csv(ROUGHNESS_CSV).set_index("theta_deg").sort_index()

    sectors = []
    for _, row in wr.iterrows():
        theta = float(row["sector_centre_deg"])
        rr = rough.loc[theta]
        sectors.append({
            "theta_deg": theta,
            "frequency": float(row["frequency"]),
            "mean_u10": float(row["mean_u10"]),
            "weibull_c": float(row["weibull_c"]),
            "weibull_k": float(row["weibull_k"]),
            "n_eff": float(row["n_eff"]),
            "z0_macdonald": float(rr["z0_macdonald_overture"]),
            "d_macdonald": float(rr["d_macdonald_overture"]),
            "z0_kanda": float(rr["z0_kanda_overture"]),
            "d_kanda": float(rr["d_kanda_overture"]),
        })

    obj = {
        "station": "MMMY",
        "source": {
            "windrose": "climate/windrose_16.csv (NOAA ISD, MMMY, see climate/README.md)",
            "roughness": "geometry/out/H_best/roughness_16sectors_overture.csv (Macdonald 1998 morphometry, Overture footprints, method='macdonald' primary per review F1/G1)",
        },
        "constants": {"kappa": KAPPA, "cmu": CMU, "z0_station": Z0_STATION, "z_blend": Z_BLEND,
                      "z0_control_en1991": 1.0, "d_control_en1991": 0.0},
        "exceedance_method_note": (
            "El navegador usa unicamente el ajuste Weibull por sector "
            "(no el metodo empirico 'auto' de windclimate.py, que requiere "
            "el registro horario completo de 15 anios) -- ver docstring de "
            "build_climate_assets.py."
        ),
        "sectors": sectors,
    }
    out_path = WEB_DATA / "climate.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=None)
    print(f"[climate] wrote {len(sectors)} sectors -> {out_path} ({out_path.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    main()
