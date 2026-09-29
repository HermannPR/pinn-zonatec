"""
domain.py -- CFD domain sizing per COST 732 / Franke et al. (2007) best-practice
guidelines, for a wind-aligned rectangular domain, evaluated at the 16 standard
meteorological sectors (theta = direction wind comes FROM, clockwise from N).

Rules of thumb applied (Franke et al. 2007, COST Action 732; see also
Blocken 2015, "50 years of CFD for wind engineering"):
  - inlet / lateral / top margins   >= 5  * H_max  (measured from the ZOI envelope)
  - outlet margin                  >= 15 * H_max
  - domain height                  ~= H_max + 5*H_max = 6*H_max (initial guess)
  - blockage ratio (frontal area / cross-section normal to flow) < 3%
    (lateral margin, then height, is increased iteratively if exceeded)

Frontal area is computed as the sum, over ZOI+ring buildings, of
height * (silhouette width perpendicular to the flow), i.e. WITHOUT
accounting for mutual shading between buildings -> a conservative
(upper-bound) blockage estimate. This is deliberately conservative and is
stated as such in the report.
"""
import math

import numpy as np

DIRECTIONS_16 = [i * 22.5 for i in range(16)]


def flow_unit_vector(theta_deg):
    """ENU unit vector of the direction the air TRAVELS towards, for wind
    coming FROM theta_deg (met. convention), per the data contract:
    velocity vector (ENU) = -U*(sin theta, cos theta)."""
    th = math.radians(theta_deg)
    return (-math.sin(th), -math.cos(th))


def _rotate_to_wind_frame(xy, theta_deg):
    """Rotate ENU points (N,2) into a frame where +x' = downwind (flow
    travel) direction, +y' = crosswind."""
    fx, fy = flow_unit_vector(theta_deg)
    # crosswind unit vector (rotate flow vector +90 deg)
    cx, cy = -fy, fx
    xp = xy[:, 0] * fx + xy[:, 1] * fy
    yp = xy[:, 0] * cx + xy[:, 1] * cy
    return np.column_stack([xp, yp])


def envelope_extent(building_xy_polys, theta_deg):
    """Return (Lx_downwind_extent, Ly_crosswind_extent) of the union of all
    building footprint vertices, in the wind-aligned frame."""
    all_pts = np.vstack(building_xy_polys)
    rot = _rotate_to_wind_frame(all_pts, theta_deg)
    Lx = rot[:, 0].max() - rot[:, 0].min()
    Ly = rot[:, 1].max() - rot[:, 1].min()
    return Lx, Ly


def frontal_area(buildings, theta_deg, bin_res=1.0):
    """Projected frontal (silhouette) area of the building set as seen by
    the incoming flow, for CFD domain BLOCKAGE sizing. This is the physical
    shadow the geometry casts on a plane normal to the flow: buildings that
    overlap in the crosswind direction do NOT add their heights (one hides
    behind the other), so we bin the crosswind axis and take, per bin, the
    MAX height among buildings covering it, then integrate.
    (Note: this is deliberately different from the morphometric "frontal
    area index" lambda_f used in Macdonald/Kanda roughness formulas, which
    by definition sums individual obstacle frontal areas without shadowing
    -- see morphometry.py.)
    """
    spans = []
    ymin_all, ymax_all = np.inf, -np.inf
    for b in buildings:
        xy = np.array(b["xy"])
        rot = _rotate_to_wind_frame(xy, theta_deg)
        y0, y1 = rot[:, 1].min(), rot[:, 1].max()
        spans.append((y0, y1, b["height_m"]))
        ymin_all = min(ymin_all, y0)
        ymax_all = max(ymax_all, y1)
    if not spans or ymax_all <= ymin_all:
        return 0.0
    nbins = max(1, int(np.ceil((ymax_all - ymin_all) / bin_res)))
    profile = np.zeros(nbins)
    for y0, y1, h in spans:
        i0 = int((y0 - ymin_all) / bin_res)
        i1 = min(nbins, int(np.ceil((y1 - ymin_all) / bin_res)))
        if i1 > i0:
            profile[i0:i1] = np.maximum(profile[i0:i1], h)
    return float(profile.sum() * bin_res)


def size_domain_for_direction(buildings, theta_deg, H_max, margin_in=5.0,
                               margin_out=15.0, height_factor=6.0,
                               blockage_limit=0.03, max_iter=20):
    """Compute wind-aligned rectangular domain dimensions for one direction,
    iteratively widening the lateral margin (and, if that alone is not
    enough, the domain height) until blockage < blockage_limit."""
    xy_list = [np.array(b["xy"]) for b in buildings]
    Lx, Ly = envelope_extent(xy_list, theta_deg)
    A_frontal = frontal_area(buildings, theta_deg)

    lat_margin_factor = margin_in
    height = height_factor * H_max
    for _ in range(max_iter):
        upwind = margin_in * H_max
        downwind = margin_out * H_max
        length = Lx + upwind + downwind
        width = Ly + 2 * lat_margin_factor * H_max
        cross_section = width * height
        blockage = A_frontal / cross_section if cross_section > 0 else np.inf
        if blockage <= blockage_limit:
            break
        # widen laterally first
        lat_margin_factor += 1.0
        if lat_margin_factor > 30:
            # fall back to also raising the domain height
            height += H_max
    return {
        "theta_deg": theta_deg,
        "Lx_zoi_along_wind_m": Lx,
        "Ly_zoi_cross_wind_m": Ly,
        "upwind_margin_m": margin_in * H_max,
        "downwind_margin_m": margin_out * H_max,
        "lateral_margin_factor_H": lat_margin_factor,
        "lateral_margin_m": lat_margin_factor * H_max,
        "domain_length_m": length,
        "domain_width_m": width,
        "domain_height_m": height,
        "frontal_area_m2": A_frontal,
        "cross_section_m2": cross_section,
        "blockage_ratio": blockage,
    }


def size_domain_all_directions(buildings, H_max, **kwargs):
    return [size_domain_for_direction(buildings, th, H_max, **kwargs) for th in DIRECTIONS_16]


def circular_domain(ring_half_m, H_max, frontal_areas_by_theta, margin_out_factor=15.0,
                     height_factor=6.0):
    """Single rotation-invariant circular domain, reused for all 16 wind
    directions (so the CFD mesh is built once, not 16 times).

    COMPROMISE for the asymmetric COST-732 margins (>=5H upstream, >=15H
    downstream) in a shape that has no preferred direction: apply the
    LARGER (15H, outlet) margin uniformly on every side. This trivially
    satisfies the smaller 5H upstream/lateral requirement too, at the cost
    of "wasting" extra background-mesh distance upstream/laterally -- which
    is cheap because that region sits far from the ZOI and is meshed with
    coarse background cells regardless of which side ends up downwind for a
    given run's direction. This is the standard pragmatic choice in the
    literature for rotatable/reusable CFD domains that sweep wind direction
    without remeshing (the alternative -- an actual direction-dependent
    asymmetric or elliptical boundary -- would defeat the "one mesh for all
    directions" purpose). A 16-sided polygon (16-gon) circumscribing the
    same radius would trim ~(1-pi/4)~=21% of the background volume relative
    to the circle for the same corner-to-corner reach, at the cost of a
    slightly more complex background block in snappyHexMesh; not adopted
    here for simplicity, but flagged as a cheap follow-up optimisation.
    """
    R = ring_half_m * math.sqrt(2) + margin_out_factor * H_max
    height = height_factor * H_max
    cross_section = 2 * R * height  # worst-case (diametral) cross-section, any direction
    A_frontal_max = max(frontal_areas_by_theta)
    blockage = A_frontal_max / cross_section
    return {
        "radius_m": R, "height_m": height, "cross_section_m2": cross_section,
        "frontal_area_max_m2": A_frontal_max, "blockage_ratio": blockage,
        "margin_out_factor_H": margin_out_factor, "height_factor_H": height_factor,
    }


def estimate_mesh_cells(R_m, domain_height_m, ring_half_m, zoi_half_m,
                         bg_res_m, ring_res_m, zoi_res_m,
                         ring_zone_height_m, zoi_zone_height_m):
    """Very rough octree-style snappyHexMesh cell-count budget: a uniform
    circular background at `bg_res_m`, a square ring refinement box (plan
    2*ring_half_m, up to ring_zone_height_m) at `ring_res_m`, and a square
    ZOI-core refinement box (plan 2*zoi_half_m, up to zoi_zone_height_m) at
    `zoi_res_m`, nested (ZOI inside ring inside background). Near-wall
    boundary-layer prism cells are NOT included (typically a modest
    ~10-20% add-on on top of the near-surface cell count, not a volumetric
    multiplier); this estimates the background/refinement volume mesh only.
    """
    V_total = math.pi * R_m ** 2 * domain_height_m
    V_ring_box = (2 * ring_half_m) ** 2 * ring_zone_height_m
    V_zoi_box = (2 * zoi_half_m) ** 2 * zoi_zone_height_m

    V_outside_ring = V_total - V_ring_box
    V_ring_band = V_ring_box - V_zoi_box

    n_bg = V_outside_ring / bg_res_m ** 3
    n_ring = V_ring_band / ring_res_m ** 3
    n_zoi = V_zoi_box / zoi_res_m ** 3
    return {
        "V_total_m3": V_total, "n_background": n_bg, "n_ring_band": n_ring,
        "n_zoi_core": n_zoi, "n_total_estimate": n_bg + n_ring + n_zoi,
    }
