"""
heights.py -- LOD1 height assignment (P18=A: OSM height/levels, else estimate + flag).

Also supports an optional external override CSV produced by other pipelines
(e.g. E:\\PINN\\datos\\alturas\\alturas_consolidadas.csv, keyed by osm_id, with a
recommended height, source, license, confidence). When present, an override
takes precedence over OSM tags and is recorded as height_source='override:<src>'.
"""
import csv
import os
import re

M_PER_LEVEL = 3.0

# default assumed level counts by OSM building tag, used only when neither
# height nor building:levels is tagged (P18=A: estimate + FLAG for field check)
DEFAULT_LEVELS_BY_TYPE = {
    "house": 1, "detached": 1, "bungalow": 1,
    "residential": 2, "apartments": 4, "dormitory": 5,
    "terrace": 2, "semidetached_house": 2,
    "commercial": 2, "retail": 1, "office": 4,
    "school": 2, "university": 2, "college": 2,
    "warehouse": 1, "industrial": 1, "garage": 1, "garages": 1,
    "hotel": 6, "hospital": 4, "public": 2, "civic": 2,
    "church": 1, "cathedral": 1, "chapel": 1,
    "roof": 1, "shed": 1, "carport": 1,
    "yes": 2,
}
DEFAULT_LEVELS_FALLBACK = 2

DEFAULT_HEIGHTS_CSV = r"E:\PINN\datos\alturas\alturas_consolidadas.csv"

_num_re = re.compile(r"[-+]?\d*\.?\d+")


def _parse_height_tag(val):
    """Parse OSM height tag values like '12', '12 m', "12'", '12.5m'."""
    if val is None:
        return None
    s = str(val).strip()
    m = _num_re.search(s)
    if not m:
        return None
    try:
        v = float(m.group())
    except ValueError:
        return None
    if v <= 0 or v > 500:
        return None
    return v


def _parse_levels_tag(val):
    if val is None:
        return None
    s = str(val).strip()
    m = _num_re.search(s)
    if not m:
        return None
    try:
        v = float(m.group())
    except ValueError:
        return None
    if v <= 0 or v > 150:
        return None
    return v


def load_height_overrides(path=DEFAULT_HEIGHTS_CSV):
    """Load an optional external height-override table. Returns dict
    osm_id(str) -> {"height_m":..., "source":..., "confidence":..., "license":...}
    Silently returns {} if the file does not exist or can't be parsed, since
    this table is produced by a separate, asynchronous pipeline."""
    if not path or not os.path.exists(path):
        return {}
    out = {}
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            cols = {c.lower(): c for c in (reader.fieldnames or [])}
            id_col = cols.get("osm_id") or cols.get("id")
            h_col = cols.get("height_m") or cols.get("height")
            src_col = cols.get("source")
            conf_col = cols.get("confidence")
            lic_col = cols.get("license") or cols.get("licence")
            if id_col is None or h_col is None:
                return {}
            for row in reader:
                raw_id = str(row.get(id_col, "")).strip()
                digits = re.sub(r"[^0-9]", "", raw_id)
                if not digits:
                    continue
                try:
                    h = float(row.get(h_col))
                except (TypeError, ValueError):
                    continue
                if h <= 0 or h > 500:
                    continue
                out[digits] = {
                    "height_m": h,
                    "source": (row.get(src_col) if src_col else "external") or "external",
                    "confidence": row.get(conf_col) if conf_col else None,
                    "license": row.get(lic_col) if lic_col else None,
                }
    except Exception:
        return {}
    return out


def assign_height(tags, osm_id, overrides=None):
    """H_osm scenario: pure OSM (height tag > building:levels x 3m > type
    estimate). `overrides` is accepted for API compatibility but is NOT used
    here any more -- see assign_height_best() for the multi-source H_best
    scenario. Return (height_m, levels, height_source, needs_field_check)."""
    h = _parse_height_tag(tags.get("height"))
    if h is not None:
        return h, round(h / M_PER_LEVEL, 2), "osm_height", False

    lev = _parse_levels_tag(tags.get("building:levels"))
    if lev is not None:
        return lev * M_PER_LEVEL, lev, "osm_levels", False

    btype = tags.get("building", "yes")
    if btype in DEFAULT_LEVELS_BY_TYPE:
        lev = DEFAULT_LEVELS_BY_TYPE[btype]
        return lev * M_PER_LEVEL, lev, "estimated_type", True

    lev = DEFAULT_LEVELS_FALLBACK
    return lev * M_PER_LEVEL, lev, "estimated_default", True


# ---------------------------------------------------------------------------
# H_best scenario (Hermann's decision, 2026-09-28: "trust the satellite" --
# he counted floor 11 from inside a Zona Tec tower with more floors above,
# confirming OSM under-counts). Priority order:
#   manual field check (out/heights_manual.csv, TOP priority)
#   > official source (e.g. CETEC/Conecta Tec, 43 m)
#   > Google Open Buildings 2.5D, QC-passed (MEDIAN height over the
#     footprint -- see google_raster.py; robust to "parallax bleed" from a
#     taller neighbour, since a median needs >50% of the footprint to agree)
#   > OSM height tag
#   > OSM building:levels x 3.4 m/floor (uniform storey height, 3.2-3.6 m
#     range per Hermann's guidance)
#   > default level count (by building type) x 3.4 m/floor
# `evidence[osm_id]['google_height_m']` is expected to already hold the
# zonal-median Google value (merged in by build_geometry.py via
# google_raster.compute_all_zonal_stats), not a single point sample.
# ---------------------------------------------------------------------------

INVESTIGADAS_CSV = r"E:\PINN\datos\alturas\alturas_investigadas.csv"

STOREY_HEIGHT_M = 3.4  # uniform floor-to-floor height (Hermann's guidance: 3.2-3.6 m)

GOOGLE_QC_MIN_HEIGHT_M = 2.0     # below this, almost certainly ground noise
GOOGLE_QC_MAX_HEIGHT_M = 250.0
GOOGLE_QC_BAD_CONFIDENCE = {"low"}
DISCREPANCY_RATIO_LOW = 0.7
DISCREPANCY_RATIO_HIGH = 1.4


def _storey_height(building_type=None):
    return STOREY_HEIGHT_M


def load_investigadas(path=INVESTIGADAS_CSV):
    """Parse the long-format per-source height investigation table into a
    dict osm_id(str) -> evidence dict. Returns {} if missing/unparsable."""
    if not path or not os.path.exists(path):
        return {}
    ev = {}
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                raw_id = str(row.get("osm_id", "")).strip()
                digits = re.sub(r"[^0-9]", "", raw_id)
                if not digits:
                    continue
                e = ev.setdefault(digits, {
                    "osm_height_m": None, "osm_levels": None,
                    "google_height_m": None, "google_confidence": None,
                    "official_height_m": None, "official_levels": None,
                    "official_source": None,
                })
                src = row.get("source_id", "")
                try:
                    h = float(row.get("height_m")) if row.get("height_m") not in (None, "") else None
                except ValueError:
                    h = None
                try:
                    fl = float(row.get("floors")) if row.get("floors") not in (None, "") else None
                except ValueError:
                    fl = None

                if src == "osm_tags":
                    method = row.get("method", "")
                    if "height" in method.lower() and "levels" not in method.lower():
                        e["osm_height_m"] = h
                    else:
                        e["osm_levels"] = fl
                elif src == "google_open_buildings_25d":
                    e["google_height_m"] = h
                    e["google_confidence"] = row.get("confidence")
                elif src:  # any other named source (official/developer/etc.)
                    if h is not None and (e["official_height_m"] is None
                                           or row.get("confidence") == "high"):
                        e["official_height_m"] = h
                        e["official_levels"] = fl
                        e["official_source"] = src
    except Exception:
        return {}
    return ev


def load_manual_overrides(path):
    """out/heights_manual.csv: osm_id,height_m,source -- Hermann's confirmed
    field floor counts. Top priority in the H_best scenario. Creates an
    empty template (header only) if missing, and returns {} in that case."""
    if not path:
        return {}
    if not os.path.exists(path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(["osm_id", "height_m", "source"])
        except Exception:
            pass
        return {}
    out = {}
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                digits = re.sub(r"[^0-9]", "", str(row.get("osm_id", "")))
                if not digits:
                    continue
                try:
                    h = float(row.get("height_m"))
                except (TypeError, ValueError):
                    continue
                if h <= 0 or h > 500:
                    continue
                out[digits] = {"height_m": h, "source": row.get("source") or "manual_field_check"}
    except Exception:
        return {}
    return out


def assign_height_best(tags, osm_id, evidence, manual_overrides=None):
    """H_best scenario. Returns (height_m, levels, height_source,
    needs_field_check, google_vs_levels_discrepancy_flag)."""
    key = str(osm_id)
    btype = tags.get("building", "yes")
    sh = _storey_height(btype)

    e = (evidence or {}).get(key, {})

    # levels-based candidate (real OSM levels preferred over our default guess)
    if e.get("osm_levels") is not None:
        levels_based_h = e["osm_levels"] * sh
        levels_is_real = True
    else:
        levels_based_h = DEFAULT_LEVELS_BY_TYPE.get(btype, DEFAULT_LEVELS_FALLBACK) * sh
        levels_is_real = False

    g = e.get("google_height_m")
    discrepancy_flag = False
    if g is not None and levels_based_h > 0:
        ratio = g / levels_based_h
        discrepancy_flag = ratio < DISCREPANCY_RATIO_LOW or ratio > DISCREPANCY_RATIO_HIGH

    manual = (manual_overrides or {}).get(key)
    if manual is not None:
        h = manual["height_m"]
        return h, round(h / sh, 2), f"manual:{manual['source']}", False, discrepancy_flag

    if e.get("official_height_m") is not None:
        h = e["official_height_m"]
        lev = e.get("official_levels") or round(h / sh, 2)
        return h, lev, f"official:{e.get('official_source', 'unknown')}", False, discrepancy_flag

    g_conf = e.get("google_confidence")
    google_qc_pass = (g is not None and g_conf not in GOOGLE_QC_BAD_CONFIDENCE
                       and GOOGLE_QC_MIN_HEIGHT_M <= g <= GOOGLE_QC_MAX_HEIGHT_M)
    if google_qc_pass:
        return g, round(g / sh, 2), "google_25d", discrepancy_flag, discrepancy_flag

    if e.get("osm_height_m") is not None:
        return e["osm_height_m"], round(e["osm_height_m"] / sh, 2), "osm_height", False, discrepancy_flag

    if levels_is_real:
        return levels_based_h, e["osm_levels"], "osm_levels_x3.4", False, discrepancy_flag

    return levels_based_h, DEFAULT_LEVELS_BY_TYPE.get(btype, DEFAULT_LEVELS_FALLBACK), \
        "estimated_type_x3.4", True, discrepancy_flag
