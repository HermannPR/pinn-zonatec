// core.js -- glue between model.js (network forward pass), features.js
// (SDF/height sampling) and climate.js (K -> physical units, comfort),
// shared by the main thread (app.js, single-point queries + the 16-sector
// comfort loop) and the heatmap worker (worker.js, grid queries), so both
// use exactly the same formulas.

import { forward } from "./model.js";
import { sdfAndHeight } from "./features.js";
import { uHOverU10 } from "./climate.js";

/** FROM-direction (deg, meteorological, 0=N clockwise) of a local ENU
 * horizontal velocity (u,v), consistent with DATA_CONTRACT's convention
 * "free-stream vector = -U*(sin theta, cos theta)" (see README.md). */
export function fromDirectionDeg(u, v) {
  const rad = Math.atan2(-u, -v);
  return ((rad * 180) / Math.PI + 360) % 360;
}

/**
 * Full point evaluation: runs the network once at (x,y,z,theta), converts
 * to physical units for the given U10 using the SCENE's real H_ref and the
 * sector's roughness (climate.json), and returns everything the UI/worker
 * need.
 *
 * @param {object} ctx {model, grids, climateData, sceneData}
 */
export function evaluatePoint(ctx, x, y, z, thetaDeg, U10) {
  const { model, grids, climateData, sceneData } = ctx;
  const { sdf, height } = sdfAndHeight(grids, x, y, z);
  const out = forward(model, x, y, z, thetaDeg, sdf, height);

  const sector = nearestSector(climateData.sectors, thetaDeg);
  const uHOverU10Ratio = uHOverU10(sector, sceneData.H_ref, climateData.constants);

  const speedNondim = Math.sqrt(out.u * out.u + out.v * out.v + out.w * out.w);
  const K = speedNondim * uHOverU10Ratio;
  const UH = uHOverU10Ratio * U10;
  const uPhys = out.u * UH, vPhys = out.v * UH, wPhys = out.w * UH;
  const speedPhys = K * U10;
  const dirDeg = fromDirectionDeg(uPhys, vPhys);
  // I = sqrt(2k/3)/U is scale-invariant (U_H cancels, see web/PROGRESO.md /
  // README.md derivation) -- computed directly from non-dim outputs.
  const turbulenceIntensity = speedNondim > 1e-9 ? Math.sqrt((2.0 / 3.0) * out.k) / speedNondim : NaN;

  return {
    sdf, height, raw: out, sector, uHOverU10: uHOverU10Ratio,
    K, U_H: UH, speed: speedPhys, dirDeg, u: uPhys, v: vPhys, w: wPhys,
    turbulenceIntensity,
  };
}

/** K(theta) for all 16 sector centres at one point (for the polar K chart
 * and for feeding the comfort/exceedance combination) -- 16 forward passes,
 * cheap (<1 ms total). */
export function kForAllSectors(ctx, x, y, z) {
  const { sdf, height } = sdfAndHeight(ctx.grids, x, y, z);
  return ctx.climateData.sectors.map((sector) => {
    const out = forward(ctx.model, x, y, z, sector.theta_deg, sdf, height);
    const speedNondim = Math.sqrt(out.u * out.u + out.v * out.v + out.w * out.w);
    const uHOverU10Ratio = uHOverU10(sector, ctx.sceneData.H_ref, ctx.climateData.constants);
    return {
      theta_deg: sector.theta_deg,
      K: speedNondim * uHOverU10Ratio,
      k_nondim: out.k,
      speedNondim,
    };
  });
}

function nearestSector(sectors, thetaDeg) {
  const t = ((thetaDeg % 360) + 360) % 360;
  let best = sectors[0], bestDiff = Infinity;
  for (const s of sectors) {
    let diff = Math.abs(s.theta_deg - t);
    diff = Math.min(diff, 360 - diff);
    if (diff < bestDiff) { bestDiff = diff; best = s; }
  }
  return best;
}
