# Data contract v2 (binding for geometry, CFD, ML, web)

## Coordinate frame
- Projected CRS: WGS84 / UTM zone 14N (EPSG:32614).
- Local frame "ZT-ENU": x = East [m], y = North [m], z = Up [m] above local ground (flat terrain, P19=A).
- Origin (x=0,y=0) = reference point defined in `v2/geometry/frame.json`
  (`{"epsg":32614,"origin_easting":..., "origin_northing":..., "origin_lon":..., "origin_lat":...}`).
  Everything stored on disk (STL, CFD samples, ML data, web) is in ZT-ENU unless the file name says otherwise.

## Wind direction convention
- theta [deg] = meteorological direction the wind comes FROM, clockwise from true North (0 = N, 90 = E).
  16 sectors: theta = 0, 22.5, ..., 337.5 (same as SMN/NOAA wind roses).
- Free-stream horizontal velocity vector (ENU) = -U * (sin theta, cos theta).
- Networks receive (sin theta, cos theta), never theta itself.

## Reference speed and inflow (P12=B, P14=A)
- U_ref = U10 = mean wind at 10 m over open terrain (airport, z0_open ~ 0.03 m, WMO standard).
- Inflow at the domain inlet: neutral log law u(z) = (u*/kappa) ln((z - d + z0)/z0), kappa = 0.41 (OpenFOAM default; state it),
  k = u*^2/sqrt(Cmu), eps = u*^3/(kappa (z - d + z0)) (Richards & Hoxey 1993), Cmu = 0.09.
  u* and z0 (and d) of the inlet come from the two-layer roughness transfer U10(open) -> urban fetch (sector-dependent z0,d
  from Macdonald 1998; Kanda 2013 as sensitivity; Wieringa/EN table as control). Stored per case.

## Per-case CFD sample file: `v2/data/processed/<case_id>.h5`
case_id pattern: `zt_<variant>_th<theta*10:04d>_U<U10*10:03d>_<mesh>` e.g. `zt_base_th0225_U050_m2`.
Datasets (float32, shape [N]): `x,y,z,u,v,w,p,k,nut` and one of `epsilon`/`omega`; `vol` (cell volume, m^3);
`wall_dist` (distance to nearest wall incl. ground, m); `sdf` (signed distance to buildings only, >0 in fluid, m);
`is_wall_adjacent` (uint8, first cell layer next to buildings/ground);
`local_height` (m, smoothed neighbourhood building height sampled from `geometry/out/<scenario>/height_raster_smooth_s5.npy`,
the same differentiable feature ml/ trains on — not the raw raster).
The SDF must come from `geometry/sdf.py: ExactPrismSDF` (single implementation for CFD extraction, ML and web).
- p is kinematic pressure (p/rho, m^2/s^2) as OpenFOAM simpleFoam writes it.
- Region stored: the "zone of interest" box (buildings of interest + margin), z from 0 to 2*H_max (P9=B), not the whole domain.
Group `wall_faces` (optional): `x,y,z,nx,ny,nz` of building/ground face centres (for the u.n = 0 loss, P24=B),
plus `height` (m, true height of the face's building; 0 for ground faces).
Group `inlet_profile`: `z,u,k,eps` as imposed.
Attributes: `theta_deg, U10, u_star, z0, d, kappa, Cmu, variant, mesh_id, turb_model, solver, of_version,
n_iter, converged (bool), final_residuals (json str), rho (1.13 kg/m3 for Monterrey, used only for Pa conversions), created,
h_ref (m), u_h (m/s, inflow speed at h_ref = climate/transfer.py InflowResult.U_H(h_ref)), T_transfer (= u_star/U10 applied, P14-A),
z0_ground_zoi (m, local ground roughness inside the ZOI, distinct from inlet z0), sdf_version (method + date/git rev)`.
Note: in OpenFOAM v2306 the ABL ground wall function is `atmNutkWallFunction`.

## Manifest: `v2/data/processed/manifest.csv`
One row per case: case_id, variant, theta_deg, U10, mesh_id, turb_model, split (train/val/test-direction/test-variant/test-speed),
n_points, converged, path. **This manifest, sealed with a SHA-256 sidecar (`manifest.csv.sha256`), is the SOLE authority
for `split`**; loaders verify the hash and never trust a per-HDF5 `split` attribute.
Evaluation metrics are computed only inside the evaluation zone (|x|,|y| <= eval_half_size_m = 325 m in frame.json) and
additionally reported for the pedestrian layer 1.5-2.0 m.

## Non-dimensionalisation (ML)
Lengths / H_ref (H_ref = height of the reference building, stored in frame.json), velocities / U_H (inflow speed at H_ref),
p / U_H^2, k / U_H^2, nut / (U_H H_ref). K = |U_local| / U10 is the amplification factor reported to users.
