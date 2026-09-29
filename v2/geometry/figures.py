"""
figures.py -- plan view of ZOI buildings (coloured by height, estimates
hatched) and the 16-sector z0/d rose.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import PatchCollection
import matplotlib.cm as cm
import matplotlib.colors as mcolors
import numpy as np


def _poly_patches(geom):
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    return []


def plan_view(records, zoi_poly, ring_poly, out_png, title="Zona Tec ZOI", eval_poly=None):
    fig, ax = plt.subplots(figsize=(9, 9))
    heights = [r["height_m"] for r in records]
    if not heights:
        heights = [1.0]
    norm = mcolors.Normalize(vmin=0, vmax=max(heights))
    try:
        cmap = matplotlib.colormaps["viridis"]
    except AttributeError:
        cmap = cm.get_cmap("viridis")

    for r in records:
        color = cmap(norm(r["height_m"]))
        flagged = r.get("needs_field_check", False)
        for p in _poly_patches(r["geom"]):
            patch = MplPolygon(
                np.array(p.exterior.coords), closed=True,
                facecolor=color, edgecolor="black", linewidth=0.2,
                hatch="///" if flagged else None,
            )
            ax.add_patch(patch)

    for poly, style, color, label in [
            (zoi_poly, "-", "red", "ZOI (explicit, meshed)"),
            (ring_poly, "--", "red", "ring (context, 1-2 blocks)"),
            (eval_poly, ":", "black", "evaluation zone (G5, >=1-2 blocks upwind)")]:
        if poly is None:
            continue
        xs, ys = poly.exterior.xy
        ax.plot(xs, ys, style, color=color, linewidth=1.5, label=label)

    minx, miny, maxx, maxy = ring_poly.bounds if ring_poly is not None else zoi_poly.bounds
    pad = 30
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    ax.set_aspect("equal")
    ax.set_xlabel("x (ZT-ENU east, m)")
    ax.set_ylabel("y (ZT-ENU north, m)")
    ax.set_title(title)

    sm = cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, fraction=0.04, pad=0.02)
    cbar.set_label("Building height (m)")

    # hatch legend entry (proxy artist, since hatch color isn't the identity channel)
    from matplotlib.patches import Patch
    hatch_proxy = Patch(facecolor="white", edgecolor="black", hatch="///",
                         label="estimated height (needs field check)")
    handles, labels = ax.get_legend_handles_labels()
    handles.append(hatch_proxy)
    labels.append(hatch_proxy.get_label())
    ax.legend(handles, labels, loc="upper right", fontsize=8, framealpha=0.9)

    fig.tight_layout()
    fig.savefig(out_png, dpi=160)
    plt.close(fig)


def roughness_rose(rows, out_png):
    """rows: list of dicts with theta_deg, z0_macdonald, z0_kanda, z0_control
    (and same for d_*)."""
    thetas = np.array([r["theta_deg"] for r in rows])
    theta_rad = np.radians(90 - thetas)  # compass -> math angle (0=E, ccw) for polar plot with N at top
    width = np.radians(18)

    fig, axes = plt.subplots(1, 2, subplot_kw={"projection": "polar"}, figsize=(13, 6))

    methods = [
        ("z0_macdonald", "Macdonald (1998)", "#2b6cb0", 0),
        ("z0_kanda", "Kanda (2013), sensitivity", "#d69e2e", 1),
        ("z0_control", "Control table (Wieringa/EN IV)", "#718096", 2),
    ]
    ax = axes[0]
    for key, label, color, off in methods:
        vals = np.array([r[key] for r in rows])
        ax.bar(theta_rad + (off - 1) * width / 3, vals, width=width / 3, color=color,
               label=label, alpha=0.9)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_title("z0 by sector (m)")
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.1), fontsize=8)

    ax = axes[1]
    for key, label, color, off in [("d_macdonald", "Macdonald (1998)", "#2b6cb0", 0),
                                    ("d_kanda", "Kanda (2013), sensitivity", "#d69e2e", 1)]:
        vals = np.array([r[key] for r in rows])
        ax.bar(theta_rad + (off - 0.5) * width / 2, vals, width=width / 2, color=color,
               label=label, alpha=0.9)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_title("displacement height d by sector (m)")

    fig.suptitle("Aerodynamic roughness / displacement height, 16 upwind sectors")
    fig.tight_layout()
    fig.savefig(out_png, dpi=160)
    plt.close(fig)
