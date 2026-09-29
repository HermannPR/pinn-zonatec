"""
overture_parse.py -- load Overture Maps building footprints (Microsoft ML
Buildings + Google Open Buildings + OSM, conflated, no duplicates) for the
F1 review's G1 fix: OSM footprints are incomplete in the N/NE/W/NW sectors
(lambda_p 0.16-0.29 vs 0.44-0.53 measured from the Google 2.5D raster),
which biases the upwind morphometry (z0/d) low in those sectors. Overture
has 26,507 footprints in the same bbox vs OSM's 2,942.
"""
import json
import os

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform as shp_transform

OVERTURE_GEOJSON = r"E:\PINN\datos\alturas\raw\overture_buildings_zonatec.geojson"

_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32614", always_xy=True)


def load_overture_buildings(path=OVERTURE_GEOJSON):
    """Return list of dicts: {osm_id (=overture_id), osm_type='overture',
    tags={}, geom (shapely polygon, UTM14N)}."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    out = []
    for feat in d["features"]:
        geom_ll = shape(feat["geometry"])
        if geom_ll.is_empty:
            continue
        try:
            geom_utm = shp_transform(lambda x, y: _to_utm.transform(x, y), geom_ll)
        except Exception:
            continue
        if not geom_utm.is_valid:
            geom_utm = geom_utm.buffer(0)
        if geom_utm.is_empty or geom_utm.area <= 0:
            continue
        out.append({
            "osm_id": feat.get("id"), "osm_type": "overture",
            "tags": {}, "geom": geom_utm,
        })
    return out
