// worker.js -- computes the heatmap grid off the main thread (module Web
// Worker) so the UI never freezes while evaluating a few thousand network
// forward passes. Loads its own copy of model/geometry/climate data (same
// URLs as the main thread) the first time it gets a 'computeHeatmap'
// message.

import { loadModel } from "./model.js";
import { loadGeometryGrids } from "./features.js";
import { evaluatePoint } from "./core.js";

let ctx = null;
let loading = null;

async function ensureLoaded(dataUrl) {
  if (ctx) return ctx;
  if (!loading) {
    loading = (async () => {
      const [model, grids, climateData, sceneData] = await Promise.all([
        loadModel(`${dataUrl}/model.json`),
        loadGeometryGrids(dataUrl),
        fetch(`${dataUrl}/climate.json`).then((r) => r.json()),
        fetch(`${dataUrl}/scene.json`).then((r) => r.json()),
      ]);
      ctx = { model, grids, climateData, sceneData };
      return ctx;
    })();
  }
  return loading;
}

self.onmessage = async (ev) => {
  const msg = ev.data;
  if (msg.type !== "computeHeatmap") return;
  const { dataUrl, requestId, x0, y0, dx, dy, nx, ny, z, thetaDeg, U10, field } = msg;
  try {
    const c = await ensureLoaded(dataUrl);
    const values = new Float32Array(nx * ny);
    for (let j = 0; j < ny; j++) {
      const y = y0 + j * dy;
      for (let i = 0; i < nx; i++) {
        const x = x0 + i * dx;
        const res = evaluatePoint(c, x, y, z, thetaDeg, U10);
        let v;
        if (field === "speed") v = res.speed;
        else if (field === "turbulence") v = res.turbulenceIntensity;
        else v = res.K; // default: amplification factor
        values[j * nx + i] = v;
      }
    }
    self.postMessage({ type: "heatmapResult", requestId, nx, ny, values }, [values.buffer]);
  } catch (err) {
    self.postMessage({ type: "heatmapError", requestId, message: String(err && err.message || err) });
  }
};
