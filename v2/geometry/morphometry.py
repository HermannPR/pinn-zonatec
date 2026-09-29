"""
morphometry.py -- aerodynamic roughness (z0) and displacement height (d) per
16 wind sectors, per binding decision P13=B:
  - A (primary):    Macdonald et al. (1998) morphometric method.
  - control:        Wieringa (1993) / EN 1991-1-4 terrain category IV table
                     value (z0 = 1.0 m fixed; the simple table method does not
                     resolve a displacement height, so d_control = 0 m is used
                     as an explicit, documented simplification).
  - C (sensitivity): Kanda et al. (2013) height-variability correction to the
                     Macdonald X,Y (d,z0) estimate.

Upwind fetch sector: a 45-degree wedge centred on the ZOI centre, pointing in
the compass direction the wind comes FROM (theta), spanning radius
[R_IN, R_OUT] m. R_IN is set just outside the ZOI+ring envelope so the fetch
excludes the buildings that are explicitly resolved in the CFD mesh (the
morphometric z0/d describe the *unresolved upstream* terrain that sets the
inlet profile, not the explicitly meshed buildings) -- this avoids the
circularity of using the resolved buildings to define their own inflow.
A 45 deg width (rather than the minimal 22.5 deg bin) follows common
morphometric/source-area practice (e.g. Wieringa 1993, Grimmond & Oke 1999)
of using a wider representative fetch than the bin width alone.

NOTE ON KANDA (2013): implemented as a direct quadratic correction (not the
earlier power-law reconstruction, which was numerically degenerate):

    X = (sigma_H + H_mean) / H_max
    d_kanda  = H_max * [ c0*X**2 + (a0*lambda_p**b0 - c0)*X ]

    Y = lambda_p * sigma_H / H_mean
    z0_kanda = z0_macdonald * [ b1*Y**2 + c1*Y + a1 ]

with (a0,b0,c0,a1,b1,c1) = (1.29, 0.36, -0.17, 0.71, 20.21, -0.77). These
coefficients are reproduced from secondary literature; the primary paper
(Kanda et al. 2013, Boundary-Layer Meteorology) was not directly accessible
(paywalled) during development to cross-check them digit-for-digit, so
treat them as best-effort. Per project direction, the values are ALWAYS
reported (never silently substituted); `kanda_reliable` is an ANNOTATION
flag only (True when 0<d_kanda<H_max and 0<z0_kanda<H_max, i.e. the sector's
lambda_p/sigma_H fall in a range where the fit stays physically sensible),
not a switch that replaces the number with Macdonald's.
"""
import math

import numpy as np
from shapely.geometry import Polygon

KAPPA_MORPH = 0.4  # von Karman constant as used in Macdonald (1998) original
ALPHA_MACDONALD = 4.43
BETA_MACDONALD = 1.0
CD_MACDONALD = 1.2

Z0_CONTROL_M = 1.0  # Wieringa 1993 / EN 1991-1-4 terrain category IV
D_CONTROL_M = 0.0   # simple table method does not resolve d (documented simplification)

R_IN_M = 560.0
R_OUT_M = 1200.0
WEDGE_HALFWIDTH_DEG = 22.5  # -> 45 deg total wedge


def upwind_wedge(center_xy, theta_deg, r_in=R_IN_M, r_out=R_OUT_M,
                  halfwidth_deg=WEDGE_HALFWIDTH_DEG, n_arc=24):
    """Polygon of the upwind fetch wedge: bearing range
    [theta-halfwidth, theta+halfwidth], radius [r_in, r_out]."""
    cx, cy = center_xy
    bearings = np.linspace(theta_deg - halfwidth_deg, theta_deg + halfwidth_deg, n_arc)
    pts_out = [(cx + r_out * math.sin(math.radians(b)), cy + r_out * math.cos(math.radians(b))) for b in bearings]
    pts_in = [(cx + r_in * math.sin(math.radians(b)), cy + r_in * math.cos(math.radians(b))) for b in bearings[::-1]]
    return Polygon(pts_out + pts_in)


def sector_geometry_stats(buildings, wedge_poly, theta_deg):
    """buildings: list of dicts with 'geom' (shapely polygon, footprint) and
    'height_m'. Returns dict of lambda_p, lambda_f, H_mean, H_max, sigma_H,
    n_buildings, lot_area_m2 (computed over buildings intersecting the wedge,
    clipped to it)."""
    from domain import _rotate_to_wind_frame

    lot_area = wedge_poly.area
    plan_area = 0.0
    heights = []
    weights = []
    frontal = 0.0
    n = 0
    n_real = 0
    real_area = 0.0
    for b in buildings:
        g = b["geom"]
        if not g.intersects(wedge_poly):
            continue
        clipped = g.intersection(wedge_poly)
        if clipped.is_empty:
            continue
        a = clipped.area
        if a <= 0:
            continue
        n += 1
        plan_area += a
        heights.append(b["height_m"])
        weights.append(a)
        src = b.get("height_source", "")
        is_real = not src.startswith("estimated") and src != ""
        if is_real:
            n_real += 1
            real_area += a
        # frontal width from the (unclipped) footprint, in wind-aligned frame
        xy = np.array(g.exterior.coords) if g.geom_type == "Polygon" else np.array(g.convex_hull.exterior.coords)
        rot = _rotate_to_wind_frame(xy, theta_deg)
        width = rot[:, 1].max() - rot[:, 1].min()
        frontal += width * b["height_m"] * (a / max(g.area, 1e-9))  # scale by fraction inside wedge

    if n == 0 or plan_area <= 0:
        return None

    heights = np.array(heights)
    weights = np.array(weights)
    H_mean = float(np.average(heights, weights=weights))
    H_max = float(heights.max())
    sigma_H = float(np.sqrt(np.average((heights - H_mean) ** 2, weights=weights)))

    lambda_p = plan_area / lot_area
    lambda_f = frontal / lot_area

    return {
        "n_buildings": n,
        "lot_area_m2": lot_area,
        "lambda_p": lambda_p,
        "lambda_f": lambda_f,
        "H_mean": H_mean,
        "H_max": H_max,
        "sigma_H": sigma_H,
        "frac_real_height_by_count": n_real / n if n else 0.0,
        "frac_real_height_by_area": real_area / plan_area if plan_area > 0 else 0.0,
    }


def macdonald_z0_d(H_mean, lambda_p, lambda_f, alpha=ALPHA_MACDONALD,
                    beta=BETA_MACDONALD, Cd=CD_MACDONALD, kappa=KAPPA_MORPH):
    if lambda_p <= 1e-6 or H_mean <= 0:
        return 0.0002, 0.0  # ~bare/open ground fallback
    lp = min(lambda_p, 0.999)
    d = H_mean * (1.0 + alpha ** (-lp) * (lp - 1.0))
    d = max(0.0, min(d, 0.99 * H_mean))
    one_minus = max(1.0 - d / H_mean, 1e-6)
    if lambda_f <= 1e-9:
        z0 = 0.0002
    else:
        expo = 0.5 * beta * (Cd / kappa ** 2) * one_minus * lambda_f
        z0 = H_mean * one_minus * math.exp(-(expo ** -0.5))
    z0 = max(z0, 1e-4)
    return z0, d


def kanda_z0_d(H_mean, H_max, sigma_H, lambda_p, lambda_f):
    """Kanda et al. (2013) height-variability correction (quadratic form,
    see module docstring). Always returns a computed (z0_kanda, d_kanda);
    `reliable` is an annotation only (fit is expected to be physically
    sensible), never a trigger to substitute Macdonald's value."""
    z0_mac, d_mac = macdonald_z0_d(H_mean, lambda_p, lambda_f)
    if H_max <= 0 or H_mean <= 0:
        return z0_mac, d_mac, False

    a0, b0, c0 = 1.29, 0.36, -0.17
    a1, b1, c1 = 0.71, 20.21, -0.77

    X = (sigma_H + H_mean) / H_max
    lp = max(lambda_p, 1e-9)
    d_kanda = H_max * (c0 * X ** 2 + (a0 * lp ** b0 - c0) * X)

    Y = lambda_p * sigma_H / H_mean
    z0_kanda = z0_mac * (b1 * Y ** 2 + c1 * Y + a1)

    reliable = (0.0 < d_kanda < H_max) and (0.0 < z0_kanda < H_max)
    return z0_kanda, d_kanda, reliable


def sensitivity_perturb_heights(buildings, delta_levels=1.0, m_per_level=3.0):
    """Return a copy of `buildings` with every height that came from an
    ESTIMATE (not osm_height/osm_levels/override) shifted by
    +/- delta_levels floors, to quantify sensitivity to the many
    outside-ZOI buildings whose floor count is unverified."""
    out = []
    for b in buildings:
        h = b["height_m"]
        if b.get("height_source", "").startswith(("estimated",)):
            h = max(m_per_level, h + delta_levels * m_per_level)
        out.append(dict(b, height_m=h))
    return out
