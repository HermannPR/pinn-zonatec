// ui.js -- rendering helpers: the 16-sector polar K chart (canvas), the
// heatmap colour scale, and the comfort-table HTML. Palette: validated
// diverging blue<->red pair (K<1 sheltered / K>1 accelerated, neutral gray
// at K=1) from the project's data-viz skill reference palette.

export const COLOR = {
  blue700: "#0d366b", blue600: "#184f95", blue500: "#256abf", blue400: "#3987e5", blue300: "#6da7ec", blue100: "#cde2fb",
  red: "#e34948", redDark: "#b23231",
  neutral: "#f0efec",
  ink: "#0b0b0b", inkSecondary: "#52514e", muted: "#898781", grid: "#e1e0d9", baseline: "#c3c2b7",
  good: "#0ca30c", warning: "#fab219", serious: "#ec835a", critical: "#d03b3b",
};

/** Diverging colour for K = U_local/U10 around the neutral point K=1. */
export function kToColor(k) {
  if (!Number.isFinite(k)) return COLOR.muted;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  if (k <= 1.0) {
    const t = clamp((1.0 - k) / 0.6, 0, 1); // 0.4 -> full blue
    return lerpHex(COLOR.neutral, COLOR.blue400, t);
  }
  const t = clamp((k - 1.0) / 0.8, 0, 1); // 1.8 -> full red
  return lerpHex(COLOR.neutral, COLOR.red, t);
}

function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function lerpHex(a, b, t) {
  const [ar, ag, ab] = hexToRgb(a), [br, bg, bb] = hexToRgb(b);
  const r = Math.round(ar + (br - ar) * t), g = Math.round(ag + (bg - ag) * t), bl = Math.round(ab + (bb - ab) * t);
  return `rgb(${r},${g},${bl})`;
}

const SECTOR_LABELS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"];

/**
 * Draw the 16-sector K polar chart into a canvas.
 * @param {HTMLCanvasElement} canvas
 * @param {{theta_deg:number, K:number}[]} sectorK
 * @param {number} highlightThetaDeg current inflow direction (drawn as a marker)
 */
export function drawPolarKChart(canvas, sectorK, highlightThetaDeg) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h / 2;
  const rMax = Math.min(w, h) / 2 - 24;

  const kMax = Math.max(1.5, ...sectorK.map((s) => s.K));
  const rOf = (k) => (k / kMax) * rMax;

  // Grid rings at K = 0.5, 1.0, 1.5 (or scaled)
  ctx.strokeStyle = COLOR.grid;
  ctx.fillStyle = COLOR.muted;
  ctx.font = "10px system-ui, sans-serif";
  ctx.textAlign = "left";
  const ringSteps = 3;
  for (let i = 1; i <= ringSteps; i++) {
    const kRing = (kMax * i) / ringSteps;
    ctx.beginPath();
    ctx.arc(cx, cy, rOf(kRing), 0, 2 * Math.PI);
    ctx.stroke();
    ctx.fillText(kRing.toFixed(1), cx + 3, cy - rOf(kRing) - 2);
  }
  // K=1 ring emphasised (neutral reference)
  ctx.strokeStyle = COLOR.baseline;
  ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.arc(cx, cy, rOf(1.0), 0, 2 * Math.PI);
  ctx.stroke();
  ctx.setLineDash([]);

  // theta=0 (N) is up, clockwise, matching meteorological convention.
  const angleOf = (thetaDeg) => (thetaDeg - 90) * (Math.PI / 180);

  // Filled polygon
  ctx.beginPath();
  sectorK.forEach((s, i) => {
    const a = angleOf(s.theta_deg);
    const r = rOf(s.K);
    const x = cx + r * Math.cos(a), y = cy + r * Math.sin(a);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.closePath();
  ctx.fillStyle = "rgba(42,120,214,0.18)";
  ctx.strokeStyle = COLOR.blue500;
  ctx.lineWidth = 2;
  ctx.fill();
  ctx.stroke();

  // Per-sector points, coloured by K
  sectorK.forEach((s) => {
    const a = angleOf(s.theta_deg);
    const r = rOf(s.K);
    const x = cx + r * Math.cos(a), y = cy + r * Math.sin(a);
    ctx.beginPath();
    ctx.arc(x, y, 3.5, 0, 2 * Math.PI);
    ctx.fillStyle = kToColor(s.K);
    ctx.fill();
    ctx.strokeStyle = COLOR.ink;
    ctx.lineWidth = 0.5;
    ctx.stroke();
  });

  // Direction labels
  ctx.fillStyle = COLOR.inkSecondary;
  ctx.font = "11px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  sectorK.forEach((s, i) => {
    const a = angleOf(s.theta_deg);
    const x = cx + (rMax + 14) * Math.cos(a), y = cy + (rMax + 14) * Math.sin(a);
    ctx.fillText(SECTOR_LABELS[i], x, y);
  });

  // Highlighted current direction (dashed radius + marker)
  if (Number.isFinite(highlightThetaDeg)) {
    const a = angleOf(highlightThetaDeg);
    ctx.strokeStyle = COLOR.ink;
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + rMax * Math.cos(a), cy + rMax * Math.sin(a));
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

export function fmt(x, digits = 2) {
  if (!Number.isFinite(x)) return "-";
  return x.toLocaleString("es-MX", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
export function fmtPct(x, digits = 2) {
  if (!Number.isFinite(x)) return "-";
  return (x * 100).toLocaleString("es-MX", { minimumFractionDigits: digits, maximumFractionDigits: digits }) + "%";
}

const NEN_CLASS_COLOR = { A: COLOR.good, B: "#7a9a0c", C: COLOR.warning, D: COLOR.serious, E: COLOR.critical };

export function renderNen8100Table(cls, pGt5, activityQuality) {
  const color = NEN_CLASS_COLOR[cls] || COLOR.muted;
  const rows = Object.entries(activityQuality)
    .map(([act, q]) => `<tr><td>${ACTIVITY_LABEL_ES[act] || act}</td><td>${q}</td></tr>`)
    .join("");
  return `
    <div class="comfort-badge" style="--badge-color:${color}">
      <span class="comfort-badge-letter">${cls}</span>
      <span class="comfort-badge-desc">NEN 8100, P(V&gt;5 m/s) = ${fmtPct(pGt5)}</span>
    </div>
    <table class="mini-table"><thead><tr><th>Actividad</th><th>Calidad</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

const ACTIVITY_LABEL_ES = { atravesar: "Atravesar (transito)", pasear: "Pasear", estar_sentado: "Estar sentado" };
const LAWSON_LABEL_ES = {
  estar_sentado_largo: "Sentarse un buen rato (4 m/s)",
  estar_de_pie_pasear: "Estar de pie / pasear (6 m/s)",
  caminar_negocios: "Caminar de prisa (8 m/s)",
  incomodo: "Incomodo por encima de (10 m/s)",
};
const LAWSON_DANGER_LABEL_ES = { riesgo_limitado: "Riesgo limitado (15 m/s)", peligroso: "Peligroso (20 m/s)" };

export function renderLawsonTable(assessment) {
  const rows = Object.entries(assessment.comfort)
    .map(([label, r]) => `<tr>
        <td>${LAWSON_LABEL_ES[label] || label}</td>
        <td>${fmtPct(r.pExceed)}</td>
        <td>${r.passes ? '<span class="ok">cumple (&lt;5%)</span>' : '<span class="fail">no cumple</span>'}</td>
      </tr>`)
    .join("");
  const dangerRows = Object.entries(assessment.danger)
    .map(([label, r]) => `<tr><td>${LAWSON_DANGER_LABEL_ES[label] || label}</td><td>${fmtPct(r.pExceed, 4)}</td></tr>`)
    .join("");
  return `
    <table class="mini-table"><thead><tr><th>Criterio LDDC</th><th>P(excedencia anual)</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="mini-table-caption">Umbrales de peligro (informativos):</p>
    <table class="mini-table"><tbody>${dangerRows}</tbody></table>`;
}
