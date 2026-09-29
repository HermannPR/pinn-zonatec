"""Shared helpers for the v2/web build scripts. Do not import ml/geometry/
climate packages here (keep the dependency arrows one-way: web build ->
those packages, never the reverse) -- only numpy/json-level glue.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

GEOMETRY_OUT = Path(r"E:\PINN\v2\geometry\out\H_best")
CLIMATE_DIR = Path(r"E:\PINN\v2\climate")
WEB_DATA = Path(r"E:\PINN\v2\web\public\data")


def load_frame(scenario_dir: Path = GEOMETRY_OUT) -> dict:
    with open(scenario_dir / "frame.json", "r", encoding="utf-8") as f:
        return json.load(f)


def meters_per_degree(lat_deg: float) -> tuple[float, float]:
    """(meters_per_deg_lat, meters_per_deg_lon) at latitude `lat_deg`,
    WGS84 ellipsoid, standard series expansion (accurate to << 1 m over the
    ~1 km scale of Zona Tec) -- see web/README.md "Marco de coordenadas".
    Must match public/js/geo.js's `metersPerDegree` EXACTLY (same formula,
    same constants) so every asset built here (buildings.geojson, grid
    origins) lines up with everything computed client-side (heatmap,
    markers) to floating-point precision, independent of how geodetically
    exact the approximation itself is.
    """
    lat = math.radians(lat_deg)
    m_per_deg_lat = (111132.92 - 559.82 * math.cos(2 * lat)
                      + 1.175 * math.cos(4 * lat) - 0.0023 * math.cos(6 * lat))
    m_per_deg_lon = (111412.84 * math.cos(lat) - 93.5 * math.cos(3 * lat)
                      + 0.118 * math.cos(5 * lat))
    return m_per_deg_lat, m_per_deg_lon


def enu_to_lonlat(x: float, y: float, origin_lon: float, origin_lat: float) -> tuple[float, float]:
    """Local ENU (x=East m, y=North m) -> (lon, lat) deg, tangent-plane
    approximation anchored at (origin_lon, origin_lat). See
    `meters_per_degree` docstring: intentionally NOT a full UTM inverse
    projection, so that every asset (buildings, grids) and the client-side
    JS use the identical, exactly-reproducible formula."""
    m_lat, m_lon = meters_per_degree(origin_lat)
    lon = origin_lon + x / m_lon
    lat = origin_lat + y / m_lat
    return lon, lat
