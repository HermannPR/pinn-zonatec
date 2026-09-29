// app.js -- PINN Zona Tec web app (P11=A). Ties together the map (map.js),
// the in-browser network + geometry features (model.js/features.js/core.js),
// the climate/comfort port (climate.js) and the UI (ui.js). Runs the heavy
// per-grid-cell forward passes in a Web Worker (worker.js) so the UI thread
// never blocks.

import { loadModel } from "./js/model.js";
import { loadGeometryGrids } from "./js/features.js";
import { evaluatePoint, kForAllSectors } from "./js/core.js";
import { lonLatToEnu, sectorLabel } from "./js/geo.js";
import {
  gustEquivalentMean, annualExceedanceWeibull, nen8100ComfortClass, nen8100ActivityQuality,
  nen8100DangerClass, lawsonLddcAssessment, NEN8100_COMFORT_THRESHOLD_MS, NEN8100_DANGER_THRESHOLD_MS,
} from "./js/climate.js";
import { initMap, addBuildingsLayer, addHeatmapSource, updateHeatmapImage, placeMarker } from "./js/map.js";
import { drawPolarKChart, kToColor, fmt, renderNen8100Table, renderLawsonTable } from "./js/ui.js";

const DATA_URL = "./data";
const SECTOR_OPTIONS = Array.from({ length: 16 }, (_, i) => i * 22.5);

const state = {
  ctx: null,       // {model, grids, climateData, sceneData}
  map: null,
  marker: null,
  point: null,      // {x,y,lon,lat}
  thetaDeg: 0,
  zQuery: 1.75,
  U10: 4.0,
  heatmapField: "K",
  worker: null,
  requestSeq: 0,
};

function $(id) { return document.getElementById(id); }

async function boot() {
  setStatus("Cargando datos (modelo, geometria, clima)...");
  const [model, grids, climateData, sceneData] = await Promise.all([
    loadModel(`${DATA_URL}/model.json`),
    loadGeometryGrids(DATA_URL),
    fetch(`${DATA_URL}/climate.json`).then((r) => r.json()),
    fetch(`${DATA_URL}/scene.json`).then((r) => r.json()),
  ]);
  state.ctx = { model, grids, climateData, sceneData };
  state.zQuery = sceneData.z_default_m;
  state.U10 = sceneData.u10_default_ms;

  showSyntheticBanner(model.metadata);
  buildControls(sceneData);

  state.map = initMap("map", sceneData);
  state.worker = new Worker("./js/worker.js", { type: "module" });
  state.worker.onmessage = onWorkerMessage;

  state.map.on("load", async () => {
    const geojson = await fetch(`${DATA_URL}/buildings.geojson`).then((r) => r.json());
    addBuildingsLayer(state.map, geojson);
    addHeatmapSource(state.map);
    setStatus("Listo. Haz clic en el mapa para consultar un punto.");
    requestHeatmap();
  });
  state.map.on("click", onMapClick);
  state.map.on("moveend", () => requestHeatmap());

  // Default point: campus origin.
  evaluateAndRender(sceneData.origin_lon, sceneData.origin_lat);
}

function setStatus(msg) {
  const el = $("status-line");
  if (el) el.textContent = msg;
}

function showSyntheticBanner(metadata) {
  const banner = $("synthetic-banner");
  if (metadata && metadata.synthetic) {
    banner.hidden = false;
    banner.textContent = metadata.warning_es || "MODELO DE PRUEBA (sintetico)";
  } else {
    banner.hidden = true;
  }
  const srcLine = $("model-source-line");
  if (srcLine && metadata) {
    srcLine.textContent = `Modelo actual: ${metadata.source_checkpoint || "?"} (${metadata.stage || ""}). ${metadata.trained_on || ""}`;
  }
}

function buildControls(sceneData) {
  const dirSel = $("direction-select");
  dirSel.innerHTML = "";
  const optTodas = document.createElement("option");
  optTodas.value = "todas";
  optTodas.textContent = "Todas (confort anual)";
  dirSel.appendChild(optTodas);
  SECTOR_OPTIONS.forEach((theta) => {
    const opt = document.createElement("option");
    opt.value = String(theta);
    opt.textContent = `${sectorLabel(theta)} (${theta.toFixed(1)} deg, viene del)`;
    dirSel.appendChild(opt);
  });
  dirSel.value = "0";
  dirSel.addEventListener("change", () => {
    if (dirSel.value !== "todas") state.thetaDeg = parseFloat(dirSel.value);
    rerenderPanel();
    requestHeatmap();
  });

  const zSlider = $("z-slider");
  zSlider.min = sceneData.z_min_query_m;
  zSlider.max = sceneData.z_max_query_m;
  zSlider.step = 0.25;
  zSlider.value = sceneData.z_default_m;
  $("z-value").textContent = `${fmt(sceneData.z_default_m, 2)} m`;
  zSlider.addEventListener("input", () => {
    state.zQuery = parseFloat(zSlider.value);
    $("z-value").textContent = `${fmt(state.zQuery, 2)} m`;
    rerenderPanel();
    requestHeatmap();
  });

  const u10Input = $("u10-input");
  u10Input.value = sceneData.u10_default_ms;
  u10Input.addEventListener("change", () => {
    state.U10 = Math.max(0.1, parseFloat(u10Input.value) || sceneData.u10_default_ms);
    rerenderPanel();
    requestHeatmap();
  });

  const fieldSel = $("heatmap-field");
  fieldSel.addEventListener("change", () => {
    state.heatmapField = fieldSel.value;
    requestHeatmap();
  });

  $("about-toggle").addEventListener("click", () => {
    $("about-panel").classList.toggle("open");
  });
}

function onMapClick(ev) {
  evaluateAndRender(ev.lngLat.lng, ev.lngLat.lat);
}

function evaluateAndRender(lon, lat) {
  const { sceneData } = state.ctx;
  const [x, y] = lonLatToEnu(lon, lat, sceneData.origin_lon, sceneData.origin_lat);
  state.point = { x, y, lon, lat };
  state.marker = placeMarker(state.map, state.marker, lon, lat);
  rerenderPanel();
}

function rerenderPanel() {
  if (!state.point) return;
  const { x, y } = state.point;
  const z = state.zQuery;
  const dirSel = $("direction-select");
  const isTodas = dirSel.value === "todas";

  const sectorK = kForAllSectors(state.ctx, x, y, z);
  drawPolarKChart($("polar-chart"), sectorK, isTodas ? NaN : state.thetaDeg);

  if (!isTodas) {
    const res = evaluatePoint(state.ctx, x, y, z, state.thetaDeg, state.U10);
    $("out-speed").textContent = `${fmt(res.speed, 2)} m/s`;
    $("out-dir").textContent = `${fmt(res.dirDeg, 1)} deg (${sectorLabel(res.dirDeg)})`;
    $("out-k").textContent = fmt(res.K, 3);
    $("out-turb").textContent = fmt(res.turbulenceIntensity, 3);
    $("single-direction-block").hidden = false;
  } else {
    $("single-direction-block").hidden = true;
  }

  renderComfort(sectorK);
  $("coord-readout").textContent = `x=${fmt(x, 1)} m, y=${fmt(y, 1)} m, z=${fmt(z, 2)} m`;
}

function renderComfort(sectorK) {
  const { climateData } = state.ctx;
  const sectors = climateData.sectors;
  const K = sectorK.map((s) => s.K);
  const Kgem = sectorK.map((s) => {
    const gem = gustEquivalentMean(s.speedNondim, s.k_nondim);
    const ratio = s.K / Math.max(s.speedNondim, 1e-12); // = uHOverU10 for that sector
    return gem * ratio;
  });

  const resComfort = annualExceedanceWeibull(sectors, K, NEN8100_COMFORT_THRESHOLD_MS);
  const resDanger = annualExceedanceWeibull(sectors, K, NEN8100_DANGER_THRESHOLD_MS);
  const cls = nen8100ComfortClass(resComfort.annualProbability);
  const dangerCls = nen8100DangerClass(resDanger.annualProbability);
  const activityQuality = {
    atravesar: nen8100ActivityQuality("atravesar", resComfort.annualProbability),
    pasear: nen8100ActivityQuality("pasear", resComfort.annualProbability),
    estar_sentado: nen8100ActivityQuality("estar_sentado", resComfort.annualProbability),
  };
  $("nen8100-block").innerHTML = renderNen8100Table(cls, resComfort.annualProbability, activityQuality)
    + `<p class="mini-table-caption">Peligro NEN 8100: <strong>${dangerCls}</strong> (P(V&gt;15 m/s)=${(resDanger.annualProbability * 100).toFixed(4)}%)</p>`;

  const lawson = lawsonLddcAssessment(sectors, Kgem);
  $("lawson-block").innerHTML = renderLawsonTable(lawson);
}

function requestHeatmap() {
  if (!state.map || !state.map.getSource || !state.map.getSource("heatmap")) return;
  const { sceneData } = state.ctx;
  const half = sceneData.eval_half_size_m;
  const spacing = 6.0; // coarse grid, metres (P11: "malla gruesa")
  const nx = Math.round((2 * half) / spacing) + 1;
  const ny = nx;
  const theta = $("direction-select").value === "todas" ? 0 : state.thetaDeg;
  const requestId = ++state.requestSeq;
  state.lastHeatmapBounds = { x0: -half, y0: -half, x1: half, y1: half };
  state.worker.postMessage({
    type: "computeHeatmap", dataUrl: DATA_URL, requestId,
    x0: -half, y0: -half, dx: spacing, dy: spacing, nx, ny,
    z: state.zQuery, thetaDeg: theta, U10: state.U10, field: state.heatmapField,
  });
}

function onWorkerMessage(ev) {
  const msg = ev.data;
  if (msg.type === "heatmapError") { console.error("[worker]", msg.message); return; }
  if (msg.type !== "heatmapResult") return;
  if (msg.requestId !== state.requestSeq) return; // stale
  renderHeatmapToMap(msg);
}

function renderHeatmapToMap(msg) {
  const { nx, ny, values } = msg;
  const canvas = document.createElement("canvas");
  canvas.width = nx; canvas.height = ny;
  const ctx2d = canvas.getContext("2d");
  const img = ctx2d.createImageData(nx, ny);
  const field = state.heatmapField;
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const v = values[j * nx + i];
      const destRow = ny - 1 - j; // row 0 (south, y0) -> bottom of image
      const color = field === "K" ? kToColor(v) : sequentialColor(v, field);
      const [r, g, b] = parseRgb(color);
      const idx = (destRow * nx + i) * 4;
      img.data[idx] = r; img.data[idx + 1] = g; img.data[idx + 2] = b; img.data[idx + 3] = 200;
    }
  }
  ctx2d.putImageData(img, 0, 0);
  updateHeatmapImage(state.map, canvas.toDataURL(), state.lastHeatmapBounds, state.ctx.sceneData);
}

function sequentialColor(v, field) {
  // speed / turbulence: single-hue sequential blue ramp, 0 -> light, high -> dark.
  const max = field === "speed" ? Math.max(2 * state.U10, 1) : 0.6;
  const t = Math.max(0, Math.min(1, v / max));
  const steps = ["#cde2fb", "#9ec5f4", "#5598e7", "#2a78d6", "#184f95", "#0d366b"];
  const idx = Math.min(steps.length - 1, Math.floor(t * (steps.length - 1)));
  return steps[idx];
}
function parseRgb(color) {
  if (color.startsWith("rgb")) {
    const m = color.match(/\d+/g).map(Number);
    return [m[0], m[1], m[2]];
  }
  const h = color.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

boot().catch((err) => {
  console.error(err);
  setStatus(`Error al cargar la app: ${err.message}`);
});
