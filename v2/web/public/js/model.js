// model.js -- pure-JS forward pass for the exported PINNMLP, mirroring
// E:\PINN\v2\ml\export.py:predict_from_json EXACTLY (same operations, same
// order) so results match the Python/torch model to float32 precision.
// See ml/export.py module docstring for the input/output contract.

/**
 * @typedef {Object} PinnModel
 * @property {number[][]} fourierB  [3][num_bands]
 * @property {{W:number[][], b:number[]}[]} layers
 * @property {string[]} outputNames
 * @property {Set<string>} positiveOutputs
 * @property {Object<string,number>} positiveScale
 * @property {number} softplusEps
 * @property {number} sdfWallScale
 * @property {number} hRef
 * @property {Object} nondim
 * @property {Object} metadata
 */

/** Load and pre-flatten a model.json into typed arrays for fast inference. */
export async function loadModel(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`No se pudo cargar el modelo: ${url} (${resp.status})`);
  const obj = await resp.json();
  return prepareModel(obj);
}

export function prepareModel(obj) {
  const B = obj.fourier.B; // [3, num_bands]
  const numBands = B[0].length;
  // Flatten B to Float64Array[3*numBands] row-major (dim, band)
  const Bflat = new Float64Array(3 * numBands);
  for (let i = 0; i < 3; i++) for (let j = 0; j < numBands; j++) Bflat[i * numBands + j] = B[i][j];

  const layers = obj.mlp.layers.map((layer) => {
    const outDim = layer.b.length;
    const inDim = layer.W[0].length;
    const Wflat = new Float64Array(outDim * inDim);
    for (let o = 0; o < outDim; o++) for (let i = 0; i < inDim; i++) Wflat[o * inDim + i] = layer.W[o][i];
    return { W: Wflat, b: Float64Array.from(layer.b), inDim, outDim };
  });

  return {
    numBands,
    Bflat,
    layers,
    outputNames: obj.output_names,
    positiveOutputs: new Set(obj.positive_outputs || []),
    positiveScale: obj.positive_scale || {},
    softplusEps: obj.softplus_eps ?? 1e-6,
    sdfWallScale: obj.sdf_wall_scale ?? 10.0,
    hRef: obj.nondim.h_ref,
    nondim: obj.nondim,
    metadata: obj.metadata || {},
  };
}

function softplus(x) {
  // matches ml/export.py:_softplus (numerically stable form)
  return Math.log1p(Math.exp(-Math.abs(x))) + Math.max(x, 0.0);
}

/**
 * Single-point forward pass.
 * @param {PinnModel} model
 * @param {number} x metres (ZT-ENU)
 * @param {number} y metres
 * @param {number} z metres
 * @param {number} thetaDeg meteorological FROM direction, degrees
 * @param {number} sdfM signed distance to buildings, metres
 * @param {number} heightM local building height, metres
 * @returns {Object<string, number>} non-dimensional outputs (u,v,w,p,k,nut)
 */
export function forward(model, x, y, z, thetaDeg, sdfM, heightM) {
  const hRef = model.hRef;
  const xn = x / hRef, yn = y / hRef, zn = z / hRef;
  const nb = model.numBands;
  const B = model.Bflat;

  // Fourier features: [sin(2*pi*proj), cos(2*pi*proj)], proj = xyz_nd @ B[3,nb]
  const feat = new Float64Array(2 * nb + 2 + 1 + 1);
  const TWO_PI = 2.0 * Math.PI;
  for (let j = 0; j < nb; j++) {
    const proj = TWO_PI * (xn * B[0 * nb + j] + yn * B[1 * nb + j] + zn * B[2 * nb + j]);
    feat[j] = Math.sin(proj);
    feat[nb + j] = Math.cos(proj);
  }
  const theta = (thetaDeg * Math.PI) / 180.0;
  feat[2 * nb + 0] = Math.sin(theta);
  feat[2 * nb + 1] = Math.cos(theta);
  feat[2 * nb + 2] = Math.tanh(sdfM / model.sdfWallScale);
  feat[2 * nb + 3] = heightM / hRef;

  let cur = feat;
  for (let li = 0; li < model.layers.length; li++) {
    const layer = model.layers[li];
    const out = new Float64Array(layer.outDim);
    for (let o = 0; o < layer.outDim; o++) {
      let acc = layer.b[o];
      const rowOff = o * layer.inDim;
      for (let i = 0; i < layer.inDim; i++) acc += layer.W[rowOff + i] * cur[i];
      out[o] = li < model.layers.length - 1 ? Math.tanh(acc) : acc;
    }
    cur = out;
  }

  const result = {};
  for (let i = 0; i < model.outputNames.length; i++) {
    const name = model.outputNames[i];
    let v = cur[i];
    if (model.positiveOutputs.has(name)) {
      const scale = model.positiveScale[name] ?? 1.0;
      v = scale * softplus(v) + model.softplusEps;
    }
    result[name] = v;
  }
  return result;
}
