// climate.js -- port of E:\PINN\v2\climate\transfer.py (P14-A two-layer
// roughness transfer) and E:\PINN\v2\climate\windclimate.py (16-sector wind
// rose exceedance, NEN 8100, Lawson LDDC), restricted to the Weibull-fit
// path (see web/build/build_climate_assets.py module docstring for why the
// empirical/'auto' path isn't ported: it needs the full 15-year hourly
// record). Verified against the Python outputs in web/tests/test_climate.mjs.

/**
 * T(theta) = u*_regional / U10_station (blending-height method, d_blend=0).
 * Mirrors transfer.py:transfer_factor exactly.
 */
export function transferFactorKappa(z0Regional, z0Station, zBlend, kappa) {
  return (
    (kappa * Math.log(zBlend / z0Station)) /
    (Math.log(10.0 / z0Station) * Math.log(zBlend / z0Regional))
  );
}

/**
 * U_H(U10)/U10 for one sector: the ratio the app multiplies the network's
 * own non-dimensional |u| by to get the REAL amplification factor
 * K = |U_local|/U10 -- independent of U10 (Reynolds-independence, P5) and
 * of the exported model's own training h_ref (see model.js / README.md
 * "Diseno de datos"). Mirrors
 * transfer.py:InflowResult.U_H / U_H_over_U10, using the SCENE's real
 * H_ref (Zona Tec, 87.75 m) and the sector's (z0,d) from climate.json.
 */
export function uHOverU10(sector, hRefReal, constants, method = "macdonald") {
  const { kappa, z0_station: z0Station, z_blend: zBlend } = constants;
  const z0 = method === "kanda" ? sector.z0_kanda : sector.z0_macdonald;
  const d = method === "kanda" ? sector.d_kanda : sector.d_macdonald;
  const T = transferFactorKappa(z0, z0Station, zBlend, kappa);
  const uH = (T / kappa) * Math.log((hRefReal - d + z0) / z0);
  return uH; // already divided by U10=1 implicitly (T carries the /U10)
}

/** Weibull survival function P(U10 > u | non-calm, sector). */
export function weibullSurvival(u, c, k) {
  if (u <= 0) return 1.0;
  return Math.exp(-Math.pow(u / c, k));
}

/**
 * Annual exceedance probability P(local speed > thresholdLocal), combining
 * the 16-sector climatology with a per-sector amplification K[i].
 * Mirrors windclimate.py:annual_exceedance(method='weibull').
 * @param {Array} sectors climate.json sectors (frequency, weibull_c, weibull_k)
 * @param {number[]} K length-16, aligned with `sectors` order
 */
export function annualExceedanceWeibull(sectors, K, thresholdLocal) {
  let annualProbability = 0;
  const perSector = sectors.map((s, i) => {
    const u10Equiv = thresholdLocal / K[i];
    const p = weibullSurvival(u10Equiv, s.weibull_c, s.weibull_k);
    const contribution = s.frequency * p;
    annualProbability += contribution;
    return { theta_deg: s.theta_deg, K: K[i], u10_equivalent: u10Equiv, p_exceed_given_sector: p, contribution };
  });
  return { perSector, annualProbability, hoursPerYear: annualProbability * 8760.0 };
}

/** GEM = max(U_local, U_gust/gustPeakToMean). Mirrors windclimate.py:gust_equivalent_mean. */
export function gustEquivalentMean(uLocal, kLocal, gustFactor = 3.25, gustPeakToMean = 1.85) {
  const sigmaU = Math.sqrt((2.0 / 3.0) * kLocal);
  const uGust = uLocal + gustFactor * sigmaU;
  return Math.max(uLocal, uGust / gustPeakToMean);
}

// NEN 8100 comfort classes: [label, pLowerIncl, pUpperExcl] over P(V>5 m/s)
export const NEN8100_COMFORT_CLASSES = [
  ["A", 0.0, 0.025], ["B", 0.025, 0.05], ["C", 0.05, 0.10], ["D", 0.10, 0.20], ["E", 0.20, 1.001],
];
export const NEN8100_ACTIVITY_QUALITY = {
  atravesar: { A: "buena", B: "buena", C: "buena", D: "moderada", E: "mala" },
  pasear: { A: "buena", B: "buena", C: "moderada", D: "mala", E: "mala" },
  estar_sentado: { A: "buena", B: "moderada", C: "mala", D: "mala", E: "mala" },
};
export const NEN8100_DANGER_CLASSES = [
  ["sin_riesgo", 0.0, 0.0005], ["riesgo_limitado", 0.0005, 0.003], ["peligroso", 0.003, 1.001],
];
export const NEN8100_COMFORT_THRESHOLD_MS = 5.0;
export const NEN8100_DANGER_THRESHOLD_MS = 15.0;

export function nen8100ComfortClass(pGt5) {
  for (const [label, lo, hi] of NEN8100_COMFORT_CLASSES) if (pGt5 >= lo && pGt5 < hi) return label;
  throw new Error(`p_gt_5=${pGt5} fuera de [0,1]`);
}
export function nen8100ActivityQuality(activity, pGt5) {
  const cls = nen8100ComfortClass(pGt5);
  return NEN8100_ACTIVITY_QUALITY[activity][cls];
}
export function nen8100DangerClass(pGt15) {
  for (const [label, lo, hi] of NEN8100_DANGER_CLASSES) if (pGt15 >= lo && pGt15 < hi) return label;
  throw new Error(`p_gt_15=${pGt15} fuera de [0,1]`);
}

// Lawson LDDC thresholds [m/s] (GEM-based), <5% annual exceedance criterion.
export const LAWSON_LDDC_COMFORT_THRESHOLDS_MS = {
  estar_sentado_largo: 4.0, estar_de_pie_pasear: 6.0, caminar_negocios: 8.0, incomodo: 10.0,
};
export const LAWSON_LDDC_COMFORT_EXCEEDANCE_LIMIT = 0.05;
export const LAWSON_LDDC_DANGER_THRESHOLDS_MS = { riesgo_limitado: 15.0, peligroso: 20.0 };

/**
 * Evaluate every Lawson LDDC comfort + danger threshold for one point given
 * its GEM-based K array (length 16, aligned with `sectors`).
 * Mirrors windclimate.py:lawson_lddc_assessment(method='weibull' implied).
 */
export function lawsonLddcAssessment(sectors, Kgem) {
  const out = { comfort: {}, danger: {} };
  for (const [label, threshold] of Object.entries(LAWSON_LDDC_COMFORT_THRESHOLDS_MS)) {
    const res = annualExceedanceWeibull(sectors, Kgem, threshold);
    out.comfort[label] = { thresholdMs: threshold, pExceed: res.annualProbability, passes: res.annualProbability < LAWSON_LDDC_COMFORT_EXCEEDANCE_LIMIT };
  }
  for (const [label, threshold] of Object.entries(LAWSON_LDDC_DANGER_THRESHOLDS_MS)) {
    const res = annualExceedanceWeibull(sectors, Kgem, threshold);
    out.danger[label] = { thresholdMs: threshold, pExceed: res.annualProbability };
  }
  return out;
}
