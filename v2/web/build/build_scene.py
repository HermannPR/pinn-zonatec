"""Build public/data/scene.json: map camera framing + the REAL Zona Tec
scenario constants (H_ref, H_max, coordinate-frame origin) that the app uses
to convert the network's non-dimensional output into physical K/U_H -- kept
separate from model.json's own `nondim` block on purpose (see
export_model.py's module docstring and web/PROGRESO.md).

Run from E:\\PINN\\v2 with the project venv:
    E:\\PINN\\.venv\\Scripts\\python.exe web\\build\\build_scene.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import GEOMETRY_OUT, WEB_DATA, load_frame  # noqa: E402


def main() -> None:
    frame = load_frame()
    obj = {
        "scenario": frame["scenario"],
        "epsg": frame["epsg"],
        "origin_lon": frame["origin_lon"],
        "origin_lat": frame["origin_lat"],
        "H_ref": frame["H_ref"],
        "H_ref_source": frame["H_ref_source"],
        "H_max": frame["H_max"],
        "zoi_half_size_m": frame["zoi_half_size_m"],
        "ring_half_size_m": frame["ring_half_size_m"],
        "eval_half_size_m": frame["eval_half_size_m"],
        "z_min_query_m": round(0.5, 2),
        "z_max_query_m": round(2.0 * frame["H_max"], 2),
        "z_default_m": 1.75,
        "u10_default_ms": 4.0,
        "notes_es": (
            "Marco ZT-ENU local (x=Este, y=Norte, metros; origen en "
            "origin_lon/origin_lat). H_ref/H_max son del edificio de "
            "referencia real de Zona Tec (Google Open Buildings 2.5D). "
            "z_max_query = 2*H_max (P9=B)."
        ),
    }
    out_path = WEB_DATA / "scene.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=None)
    print(f"[scene] wrote {out_path} ({out_path.stat().st_size/1024:.2f} KB)")


if __name__ == "__main__":
    main()
