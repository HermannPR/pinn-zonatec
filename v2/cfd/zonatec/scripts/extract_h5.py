"""Extract a converged Zona Tec direction case to the HDF5 data contract (v2/docs/DATA_CONTRACT.md).

Output: E:/PINN/v2/data/processed/<case_id>.h5
  datasets (float32, [N]; cells of the ZOI box |x|,|y| <= zoi_half, 0 <= z <= 2 H_max):
    x y z u v w p k nut epsilon|omega vol wall_dist sdf ; is_wall_adjacent (uint8) ; cell_id (int32)
    + proposed (contract diff, M12): local_height (float32, height of the LOD1 building whose footprint contains
      (x,y), 0 outside buildings -- unsmoothed, exact geometry)
  group wall_faces: x y z nx ny nz area (float32) + kind (uint8: 0 ground, 1 building) for boundary faces of
    walls inside the ZOI box (unit outward normals, pointing INTO the wall i.e. out of the fluid domain)
  group inlet_profile: z u k eps omega (as imposed at the inlet, Richards & Hoxey, d = 0)
  attributes: see ATTRS below.
Sources: fields = latest reconstructed time of the case; cell centres / volumes / wall distance = mesh case 0/
(checkMesh -writeFields + writeCellCentres, identical mesh); SDF = buildings.exact_sdf (canonical ExactPrismSDF formula).
Usage: python extract_h5.py <case> [--out-dir DIR]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buildings as B  # noqa: E402
import convcheck  # noqa: E402
import ofio  # noqa: E402
from zt_common import CMU, KAPPA  # noqa: E402

OUT_DIR = Path(r"E:\PINN\v2\data\processed")
RHO = 1.13
SDF_VERSION = "ExactPrismSDF(geometry/sdf.py, LOD1 prism union) via cfd/zonatec/scripts/buildings.exact_sdf; footprints from *_multisolid.stl bottom caps"


def local_height(x, y, variant):
    import shapely
    recs = B.load_records(variant)
    h = np.zeros(len(x), dtype=np.float32)
    if not recs:
        return h
    polys = [r["geom"] for r in recs]
    tree = shapely.STRtree(polys)
    pts = shapely.points(x, y)
    ip, ig = tree.query(pts, predicate="within")
    hh = np.array([r["height_m"] for r in recs], dtype=np.float32)
    np.maximum.at(h, ip, hh[ig])
    return h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    a = ap.parse_args()
    case = Path(a.case).resolve()
    meta = json.loads((case / "case.json").read_text())
    mesh_case = Path(meta["mesh_case"])
    mstats = json.loads((mesh_case / "mesh_stats.json").read_text()) if (mesh_case / "mesh_stats.json").exists() else {}
    dom = meta["domain"]
    zh, zmax = dom["zoi_half"], 2.0 * dom["H_max"]
    t = ofio.latest_time(case)
    T = "omega" if meta["model"] == "kOmegaSST" else "epsilon"

    m0 = mesh_case / "0"
    C, _ = ofio.read_field(m0 / "C")
    V, _ = ofio.read_field(m0 / "cellVolume")
    W, _ = ofio.read_field(m0 / "wallDistance")
    sel = np.where((np.abs(C[:, 0]) <= zh) & (np.abs(C[:, 1]) <= zh) & (C[:, 2] >= 0) & (C[:, 2] <= zmax))[0]
    print(f"cells in ZOI box: {len(sel)} of {len(C)}")
    F = {}
    for q in ("U", "p", "k", T, "nut"):
        arr, _ = ofio.read_field(case / t / q)
        if len(arr) != len(C):
            raise SystemExit(f"{q}: {len(arr)} values but mesh has {len(C)} cells")
        F[q] = arr[sel]

    # wall-adjacent cells and wall faces
    pm = case / "constant" / "polyMesh"
    if not (pm / "owner").exists():
        pm = mesh_case / "constant" / "polyMesh"
    bnd = ofio.read_boundary(pm)
    owner = ofio.read_owner(pm)
    walls = {n: p for n, p in bnd.items() if p["type"] == "wall" and p["nFaces"] > 0}
    adj = np.zeros(len(C), dtype=np.uint8)
    wf = []
    pts = ofio.read_points(pm)
    off, lab = ofio.read_faces(pm)
    for name, p in walls.items():
        f = np.arange(p["startFace"], p["startFace"] + p["nFaces"])
        adj[owner[f]] = 1
        cen, area = ofio.face_centres_normals(pts, off, lab, f)
        inbox = (np.abs(cen[:, 0]) <= zh) & (np.abs(cen[:, 1]) <= zh) & (cen[:, 2] <= zmax)
        A = np.linalg.norm(area[inbox], axis=1)
        n = area[inbox] / A[:, None]
        kind = 0 if name.startswith("ground") else 1
        wf.append((cen[inbox], n, A, np.full(inbox.sum(), kind, dtype=np.uint8)))
    xyz = C[sel]
    print("computing exact SDF ...")
    sdf = B.exact_sdf(xyz, meta["variant"], meta["scenario"])
    lh = local_height(xyz[:, 0], xyz[:, 1], meta["variant"])

    inf = meta["inflow"]
    us, z0 = inf["u_star"], inf["z0"]
    zp = np.unique(np.r_[np.geomspace(0.1, dom["Htop"], 120), [1.75, 10.0, dom["H_ref"]]])
    Up = us / KAPPA * np.log((zp + z0) / z0)
    kp = np.full_like(zp, us ** 2 / np.sqrt(CMU))
    ep = us ** 3 / (KAPPA * (zp + z0))
    op = ep / (CMU * kp)

    rep = convcheck.check(case)
    ofv = "v2306"
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    h5p = out_dir / f"{meta['case_id']}.h5"
    tmp = h5p.with_suffix(".h5.tmp")
    import h5py
    with h5py.File(tmp, "w") as h:
        kw = dict(compression="gzip", compression_opts=4, shuffle=True)
        f32 = lambda v: np.asarray(v, dtype=np.float32)  # noqa: E731
        for name, v in (("x", xyz[:, 0]), ("y", xyz[:, 1]), ("z", xyz[:, 2]), ("u", F["U"][:, 0]),
                        ("v", F["U"][:, 1]), ("w", F["U"][:, 2]), ("p", F["p"]), ("k", F["k"]), ("nut", F["nut"]),
                        (T, F[T]), ("vol", V[sel]), ("wall_dist", W[sel]), ("sdf", sdf), ("local_height", lh)):
            h.create_dataset(name, data=f32(v), **kw)
        h.create_dataset("is_wall_adjacent", data=adj[sel], **kw)
        h.create_dataset("cell_id", data=sel.astype(np.int32), **kw)
        g = h.create_group("wall_faces")
        cen = np.vstack([w[0] for w in wf]); nrm = np.vstack([w[1] for w in wf])
        for i, c in enumerate("xyz"):
            g.create_dataset(c, data=f32(cen[:, i]), **kw)
            g.create_dataset("n" + c, data=f32(nrm[:, i]), **kw)
        g.create_dataset("area", data=f32(np.concatenate([w[2] for w in wf])), **kw)
        g.create_dataset("kind", data=np.concatenate([w[3] for w in wf]), **kw)
        g.attrs["kind_codes"] = "0 = ground (ground_zoi/ground_outer), 1 = building (bld_zoi/bld_ring)"
        g.attrs["normal_convention"] = "unit face normal pointing out of the fluid domain (OpenFOAM boundary-face convention)"
        ip = h.create_group("inlet_profile")
        for name, v in (("z", zp), ("u", Up), ("k", kp), ("eps", ep), ("omega", op)):
            ip.create_dataset(name, data=f32(v))
        ip.attrs["formula"] = "Richards & Hoxey (1993), d = 0: U = u*/kappa ln((z+z0)/z0), k = u*^2/sqrt(Cmu), eps = u*^3/(kappa (z+z0))"
        at = h.attrs
        at["case_id"] = meta["case_id"]
        at["theta_deg"] = meta["theta_deg"]; at["U10"] = meta["U10"]
        at["u_star"] = us; at["z0"] = z0; at["d"] = 0.0; at["kappa"] = KAPPA; at["Cmu"] = CMU
        at["variant"] = meta["variant"]; at["mesh_id"] = {"fine": "m1", "medium": "m2", "coarse": "m3"}.get(meta["level"], meta["level"])
        at["turb_model"] = meta["model"]; at["solver"] = "simpleFoam (SIMPLEC, steady RANS)"; at["of_version"] = ofv
        at["n_iter"] = float(t); at["converged"] = bool(rep["converged"])
        at["final_residuals"] = json.dumps(rep.get("final_initial_residuals", {}))
        at["convergence_report"] = json.dumps({k: rep.get(k) for k in ("probe_max_range_over_UH_last500", "mass_balance",
                                                                      "criterion_A_residuals", "criterion_B_plateau_probes")})
        at["rho"] = RHO
        at["created"] = dt.datetime.now().isoformat(timespec="seconds")
        # proposed additions (contract diff in README / final report; M12)
        at["h_ref"] = dom["H_ref"]; at["u_h"] = meta["U_H"]; at["T_transfer"] = inf["T"]
        at["z0_method"] = inf["z0_method"]; at["d_morph"] = inf.get("d_morph", 0.0)
        at["z0_ground_zoi"] = meta["z0_ground_zoi"]; at["z0_fetch"] = meta["z0_fetch"]
        at["sdf_version"] = SDF_VERSION; at["scenario"] = meta["scenario"]
        at["region"] = json.dumps({"x": [-zh, zh], "y": [-zh, zh], "z": [0, zmax]})
        at["n_cells_mesh"] = len(C); at["mesh_case"] = str(mesh_case)
        at["frame"] = "ZT-ENU (geometry/out/<scenario>/frame.json)"
    tmp.replace(h5p)
    print(f"wrote {h5p}: {len(sel)} cells, {len(cen)} wall faces, converged={rep['converged']}")


if __name__ == "__main__":
    main()
