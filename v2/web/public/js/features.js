// features.js -- SDF (signed distance to buildings) + local building height
// sampling from the quantized grids built by
// web/build/build_geometry_assets.py, mirroring
// E:\PINN\v2\ml\features.py: NestedSDFGridGeometry / _trilinear_nonuniform_z
// / _bilinear_uniform EXACTLY (same nested fine/coarse scheme, same
// clamped-index trilinear interpolation) so JS features agree with the
// Python training-time features to within grid downsampling + int16
// quantization (see sdf_grid_meta.json's quantization_note).

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`fetch ${url}: ${r.status}`);
  return r.json();
}

async function fetchInt16(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`fetch ${url}: ${r.status}`);
  const buf = await r.arrayBuffer();
  return new Int16Array(buf);
}

export async function loadGeometryGrids(dataUrl) {
  const [sdfMeta, heightMeta] = await Promise.all([
    fetchJSON(`${dataUrl}/sdf_grid_meta.json`),
    fetchJSON(`${dataUrl}/height_grid_meta.json`),
  ]);
  const [fineRaw, coarseRaw, heightRaw] = await Promise.all([
    fetchInt16(`${dataUrl}/${sdfMeta.fine.file}`),
    fetchInt16(`${dataUrl}/${sdfMeta.coarse.file}`),
    fetchInt16(`${dataUrl}/${heightMeta.file}`),
  ]);
  const scale = sdfMeta.quantization.scale;
  const hScale = heightMeta.quantization.scale;

  return {
    fine: { ...sdfMeta.fine, data: fineRaw, scale },
    coarse: { ...sdfMeta.coarse, data: coarseRaw, scale },
    height: { ...heightMeta, data: heightRaw, scale: hScale },
  };
}

function clampi(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v;
}

// Trilinear interp of a [nz,ny,nx] int16 volume (row-major, z slowest), xy
// uniform, z given by a (non-uniform, ascending) `zLevels` array. Mirrors
// ml/features.py:_trilinear_nonuniform_z.
function trilinearNonuniformZ(grid, x, y, z) {
  const [nz, ny, nx] = grid.shape_zyx;
  const { x0, y0, res_xy: res, z_levels: zLevels, data, scale } = grid;

  const fx = (x - x0) / res;
  const fy = (y - y0) / res;
  let ix0 = clampi(Math.floor(fx), 0, nx - 2);
  let iy0 = clampi(Math.floor(fy), 0, ny - 2);

  // searchsorted(zLevels, z, side='right') - 1, clamped to [0, nz-2]
  let iz0 = zLevels.length - 1;
  for (let i = 0; i < zLevels.length; i++) {
    if (zLevels[i] > z) { iz0 = i - 1; break; }
  }
  iz0 = clampi(iz0, 0, nz - 2);

  const tx = clampi(fx - ix0, 0.0, 1.0);
  const ty = clampi(fy - iy0, 0.0, 1.0);
  const z0v = zLevels[iz0], z1v = zLevels[iz0 + 1];
  const tz = clampi((z - z0v) / Math.max(z1v - z0v, 1e-6), 0.0, 1.0);

  const strideZ = ny * nx, strideY = nx;
  const at = (iz, iy, ix) => data[iz * strideZ + iy * strideY + ix] * scale;

  const c000 = at(iz0, iy0, ix0), c001 = at(iz0, iy0, ix0 + 1);
  const c010 = at(iz0, iy0 + 1, ix0), c011 = at(iz0, iy0 + 1, ix0 + 1);
  const c100 = at(iz0 + 1, iy0, ix0), c101 = at(iz0 + 1, iy0, ix0 + 1);
  const c110 = at(iz0 + 1, iy0 + 1, ix0), c111 = at(iz0 + 1, iy0 + 1, ix0 + 1);

  const c00 = c000 * (1 - tx) + c001 * tx;
  const c01 = c010 * (1 - tx) + c011 * tx;
  const c10 = c100 * (1 - tx) + c101 * tx;
  const c11 = c110 * (1 - tx) + c111 * tx;
  const c0 = c00 * (1 - ty) + c01 * ty;
  const c1 = c10 * (1 - ty) + c11 * ty;
  return c0 * (1 - tz) + c1 * tz;
}

// Bilinear interp of a [ny,nx] int16 raster. Mirrors
// ml/features.py:_bilinear_uniform.
export function bilinearUniform(grid, x, y) {
  const [ny, nx] = grid.shape_yx;
  const { x0, y0, res, data, scale } = grid;
  const fx = clampi((x - x0) / res, 0.0, nx - 1.0);
  const fy = clampi((y - y0) / res, 0.0, ny - 1.0);
  const ix0 = clampi(Math.floor(fx), 0, nx - 2);
  const iy0 = clampi(Math.floor(fy), 0, ny - 2);
  const tx = fx - ix0, ty = fy - iy0;
  const at = (iy, ix) => data[iy * nx + ix] * scale;
  const c00 = at(iy0, ix0), c01 = at(iy0, ix0 + 1);
  const c10 = at(iy0 + 1, ix0), c11 = at(iy0 + 1, ix0 + 1);
  const c0 = c00 * (1 - tx) + c01 * tx;
  const c1 = c10 * (1 - tx) + c11 * tx;
  return c0 * (1 - ty) + c1 * ty;
}

/**
 * Signed distance + local building height at (x,y,z), metres, ZT-ENU.
 * Mirrors ml/features.py:NestedSDFGridGeometry.sdf_and_height: fine grid
 * (near ground, z <= fine z-top) else coarse grid.
 */
export function sdfAndHeight(grids, x, y, z) {
  const fineTop = grids.fine.z_levels[grids.fine.z_levels.length - 1];
  const sdf = z <= fineTop
    ? trilinearNonuniformZ(grids.fine, x, y, Math.min(z, fineTop))
    : trilinearNonuniformZ(grids.coarse, x, y, z);
  const height = bilinearUniform(grids.height, x, y);
  return { sdf, height };
}
