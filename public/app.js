'use strict';
/* Viento urbano PINN: inferencia de la red en el navegador + visualización en canvas. */

const $ = (s) => document.querySelector(s);
const state = { view: 'pinn', particles: true, sensors: false, probe: null };
let M, F, NET, LX, LY;
const G = {};                 // grids

// ---------------- colormaps ----------------
const CMAPS = {
  speed: [[0, 13, 27, 62], [0.2, 31, 78, 156], [0.4, 31, 163, 168], [0.6, 126, 217, 87], [0.8, 255, 201, 60], [1, 255, 90, 54]],
  error: [[0, 7, 6, 15], [0.25, 59, 15, 112], [0.5, 140, 41, 129], [0.75, 222, 73, 104], [0.9, 254, 159, 109], [1, 252, 253, 191]],
};
function cmap(name, t) {
  const s = CMAPS[name];
  t = Math.min(1, Math.max(0, t));
  for (let i = 1; i < s.length; i++) {
    if (t <= s[i][0]) {
      const a = s[i - 1], b = s[i], f = (t - a[0]) / (b[0] - a[0]);
      return [a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2]), a[3] + f * (b[3] - a[3])];
    }
  }
  const l = s[s.length - 1];
  return [l[1], l[2], l[3]];
}
const RANGES = { speed: [0, 14], error: [0, 6] };

// ---------------- neural network ----------------
function buildNet(m) {
  const layers = m.layers.map((L) => {
    const nout = L.W.length, nin = L.W[0].length;
    const W = new Float64Array(nout * nin);
    L.W.forEach((row, j) => row.forEach((w, i) => { W[j * nin + i] = w; }));
    return { W, b: Float64Array.from(L.b), nin, nout };
  });
  const B = m.fourier && m.fourier.B ? m.fourier.B : null;
  const nff = B ? B[0].length : 0;
  const maxw = Math.max(2 + 2 * nff, ...layers.map((l) => l.nout));
  return {
    layers, B, nff, a: new Float64Array(maxw), c: new Float64Array(maxw),
    xn: m.in_norm, sc: m.out_scale,
  };
}
function netEval(x, y) {
  const N = NET;
  let a = N.a, c = N.c;
  a[0] = 2 * (x - N.xn.xmin) / (N.xn.xmax - N.xn.xmin) - 1;
  a[1] = 2 * (y - N.xn.ymin) / (N.xn.ymax - N.xn.ymin) - 1;
  if (N.nff) {
    for (let k = 0; k < N.nff; k++) {
      const z = Math.PI * (a[0] * N.B[0][k] + a[1] * N.B[1][k]);
      a[2 + k] = Math.sin(z); a[2 + N.nff + k] = Math.cos(z);
    }
  }
  const nl = N.layers.length;
  for (let l = 0; l < nl; l++) {
    const { W, b, nin, nout } = N.layers[l];
    const last = l === nl - 1;
    for (let j = 0; j < nout; j++) {
      let s = b[j]; const o = j * nin;
      for (let i = 0; i < nin; i++) s += W[o + i] * a[i];
      c[j] = last ? s : Math.tanh(s);
    }
    const t = a; a = c; c = t;
  }
  return [a[0] * N.sc.u, a[1] * N.sc.v, a[2] * N.sc.p];
}

// ---------------- geometry helpers ----------------
function inBuilding(x, y) {
  for (const b of F.buildings) if (x > b.x0 && x < b.x1 && y > b.y0 && y < b.y1) return true;
  return false;
}
function makeGrid(nx, ny, x0, y0, dx) {
  const n = nx * ny;
  return { nx, ny, x0, y0, dx, u: new Float32Array(n), v: new Float32Array(n), s: new Float32Array(n), solid: new Uint8Array(n) };
}
// bilinear interpolation of the vector field (solid cells carry u = v = 0)
function sampleVel(g, x, y) {
  let fx = (x - g.x0) / g.dx, fy = (y - g.y0) / g.dx;
  fx = Math.min(g.nx - 1.001, Math.max(0, fx)); fy = Math.min(g.ny - 1.001, Math.max(0, fy));
  const i = fx | 0, j = fy | 0, tx = fx - i, ty = fy - j;
  const k00 = i * g.ny + j, k10 = k00 + g.ny, k01 = k00 + 1, k11 = k10 + 1;
  const w00 = (1 - tx) * (1 - ty), w10 = tx * (1 - ty), w01 = (1 - tx) * ty, w11 = tx * ty;
  return [g.u[k00] * w00 + g.u[k10] * w10 + g.u[k01] * w01 + g.u[k11] * w11,
          g.v[k00] * w00 + g.v[k10] * w10 + g.v[k01] * w01 + g.v[k11] * w11];
}
// bilinear on a nullable array using only fluid neighbours
function sampleField(arr, x, y) {
  let fx = (x - F.x0) / F.dx, fy = (y - F.y0) / F.dx;
  fx = Math.min(F.nx - 1.001, Math.max(0, fx)); fy = Math.min(F.ny - 1.001, Math.max(0, fy));
  const i = fx | 0, j = fy | 0, tx = fx - i, ty = fy - j;
  let s = 0, w = 0;
  [[0, 0, (1 - tx) * (1 - ty)], [1, 0, tx * (1 - ty)], [0, 1, (1 - tx) * ty], [1, 1, tx * ty]].forEach(([di, dj, ww]) => {
    const val = arr[(i + di) * F.ny + j + dj];
    if (val !== null && ww > 0) { s += val * ww; w += ww; }
  });
  return w > 0 ? s / w : null;
}

// ---------------- precompute ----------------
function precompute() {
  // high-resolution PINN grid (2 m cells, same as the simulation)
  const nxh = 240, nyh = 120, dxh = LX / nxh;
  const P = makeGrid(nxh, nyh, dxh / 2, dxh / 2, dxh);
  for (let i = 0; i < nxh; i++) for (let j = 0; j < nyh; j++) {
    const k = i * nyh + j, x = P.x0 + i * dxh, y = P.y0 + j * dxh;
    if (inBuilding(x, y)) { P.solid[k] = 1; continue; }
    const [u, v] = netEval(x, y);
    P.u[k] = u; P.v[k] = v; P.s[k] = Math.hypot(u, v);
  }
  G.pinn = P;
  // simulation, baseline and PINN on the (coarser) field grid
  const S = makeGrid(F.nx, F.ny, F.x0, F.y0, F.dx), B = makeGrid(F.nx, F.ny, F.x0, F.y0, F.dx);
  const E = makeGrid(F.nx, F.ny, F.x0, F.y0, F.dx);
  for (let k = 0; k < F.nx * F.ny; k++) {
    const sol = F.solid[k];
    S.solid[k] = B.solid[k] = E.solid[k] = sol;
    if (sol) continue;
    S.u[k] = F.u[k]; S.v[k] = F.v[k]; S.s[k] = Math.hypot(F.u[k], F.v[k]);
    B.u[k] = F.base_u[k]; B.v[k] = F.base_v[k]; B.s[k] = Math.hypot(B.u[k], B.v[k]);
    const i = Math.floor(k / F.ny), j = k % F.ny;
    const [u, v] = netEval(F.x0 + i * F.dx, F.y0 + j * F.dx);
    E.s[k] = Math.abs(Math.hypot(u, v) - S.s[k]);
  }
  G.sim = S; G.base = B; G.err = E;
}

const VIEWS = {
  pinn: { heat: 'pinn', vel: 'pinn', cmap: 'speed', label: 'Velocidad del viento (PINN)',
    note: 'Campo de viento predicho por la PINN, evaluada en 28 800 puntos del mapa. Las partículas siguen la velocidad predicha por la red.' },
  sim: { heat: 'sim', vel: 'sim', cmap: 'speed', label: 'Velocidad del viento (simulación)',
    note: 'La “verdad”: la simulación completa (Lattice Boltzmann). La red nunca vio este campo, solo los valores en los sensores.' },
  error: { heat: 'err', vel: 'pinn', cmap: 'error', label: 'Error de rapidez |PINN − sim|',
    note: 'Diferencia de rapidez entre la PINN y la simulación. Oscuro = acierta; brillante = se equivoca. Los errores grandes se concentran en los chorros estrechos entre edificios.' },
  base: { heat: 'base', vel: 'base', cmap: 'speed', label: 'Velocidad (interpolación, sin física)',
    note: 'Lo que se obtiene interpolando linealmente entre los mismos sensores, sin física. No sabe que existen los edificios: el viento “los atraviesa” y se pierden los chorros de las calles.' },
};

// ---------------- rendering ----------------
const heat = $('#heat'), flow = $('#flow'), over = $('#over'), wrap = $('#mapwrap');
const hctx = heat.getContext('2d'), fctx = flow.getContext('2d'), octx = over.getContext('2d');
let W = 0, H = 0, DPR = 1;
const toPx = (x, y) => [x / LX * W, (1 - y / LY) * H];

function resize() {
  DPR = Math.min(window.devicePixelRatio || 1, 2);
  const r = wrap.getBoundingClientRect();
  W = Math.round(r.width * DPR); H = Math.round(r.height * DPR);
  for (const c of [heat, flow, over]) { c.width = W; c.height = H; }
  drawHeat(); drawOver(); initParticles();
}

function drawHeat() {
  if (!G.pinn) return;
  const V = VIEWS[state.view], g = G[V.heat], [lo, hi] = RANGES[V.cmap];
  const off = document.createElement('canvas');
  off.width = g.nx; off.height = g.ny;
  const octx2 = off.getContext('2d'), img = octx2.createImageData(g.nx, g.ny);
  for (let i = 0; i < g.nx; i++) for (let j = 0; j < g.ny; j++) {
    const k = i * g.ny + j, p = ((g.ny - 1 - j) * g.nx + i) * 4;
    const c = g.solid[k] ? [34, 42, 54] : cmap(V.cmap, (g.s[k] - lo) / (hi - lo));
    img.data[p] = c[0]; img.data[p + 1] = c[1]; img.data[p + 2] = c[2]; img.data[p + 3] = 255;
  }
  octx2.putImageData(img, 0, 0);
  hctx.imageSmoothingEnabled = true;
  hctx.drawImage(off, 0, 0, W, H);
  // crisp buildings
  hctx.fillStyle = '#222a36'; hctx.strokeStyle = '#3a4658'; hctx.lineWidth = DPR;
  for (const b of F.buildings) {
    const [x0, y1] = toPx(b.x0, b.y0), [x1, y0] = toPx(b.x1, Math.min(b.y1, LY));
    hctx.fillRect(x0, y0, x1 - x0, y1 - y0);
    hctx.strokeRect(x0 + .5, y0 + .5, x1 - x0 - 1, y1 - y0 - 1);
  }
  drawLegend(V);
  $('#viewNote').textContent = V.note;
}

function drawLegend(V) {
  const c = $('#legbar'), x = c.getContext('2d');
  for (let i = 0; i < c.width; i++) {
    const [r, g, b] = cmap(V.cmap, i / (c.width - 1));
    x.fillStyle = `rgb(${r | 0},${g | 0},${b | 0})`; x.fillRect(i, 0, 1, c.height);
  }
  $('#legLabel').textContent = V.label;
  const [lo, hi] = RANGES[V.cmap], n = V.cmap === 'speed' ? 7 : 6;
  $('#legTicks').innerHTML = Array.from({ length: n + 1 }, (_, i) => {
    const v = lo + (hi - lo) * i / n;
    return `<span>${v.toFixed(0)}${i === n ? '+ m/s' : ''}</span>`;
  }).join('');
}

function drawOver() {
  octx.clearRect(0, 0, W, H);
  if (state.sensors && M) {
    for (const [x, y] of M.sensors) {
      const [px, py] = toPx(x, y);
      octx.beginPath(); octx.arc(px, py, 3.2 * DPR, 0, 7);
      octx.fillStyle = '#ffffff'; octx.fill();
      octx.lineWidth = 1.5 * DPR; octx.strokeStyle = '#0b0f14'; octx.stroke();
    }
  }
  if (state.probe) {
    const [px, py] = toPx(state.probe.x, state.probe.y);
    octx.lineWidth = 2 * DPR; octx.strokeStyle = '#fff';
    octx.beginPath(); octx.arc(px, py, 9 * DPR, 0, 7); octx.stroke();
    octx.beginPath(); octx.arc(px, py, 2.5 * DPR, 0, 7); octx.fillStyle = '#fff'; octx.fill();
    if (state.probe.uv) {
      const [u, v] = state.probe.uv, s = Math.hypot(u, v) || 1, L = 26 * DPR;
      const ex = px + u / s * L, ey = py - v / s * L;
      octx.beginPath(); octx.moveTo(px, py); octx.lineTo(ex, ey); octx.stroke();
      const a = Math.atan2(ey - py, ex - px);
      octx.beginPath(); octx.moveTo(ex, ey);
      octx.lineTo(ex - 8 * DPR * Math.cos(a - .45), ey - 8 * DPR * Math.sin(a - .45));
      octx.lineTo(ex - 8 * DPR * Math.cos(a + .45), ey - 8 * DPR * Math.sin(a + .45));
      octx.closePath(); octx.fillStyle = '#fff'; octx.fill();
    }
  }
}

// ---------------- particles ----------------
let parts = [];
function spawn(p) {
  let x, y, tries = 0;
  do { x = Math.random() * LX; y = Math.random() * LY; tries++; } while (inBuilding(x, y) && tries < 20);
  p.x = x; p.y = y; p.age = 0; p.life = 60 + Math.random() * 140;
  return p;
}
function initParticles() {
  const n = Math.min(2600, Math.round((W / DPR) * (H / DPR) / 160));
  parts = Array.from({ length: n }, () => spawn({}));
  fctx.clearRect(0, 0, W, H);
}
const TIME_SCALE = 0.22;      // seconds of physical time per frame
function step() {
  if (state.particles && G.pinn) {
    fctx.globalCompositeOperation = 'destination-in';
    fctx.fillStyle = 'rgba(0,0,0,0.9)'; fctx.fillRect(0, 0, W, H);
    fctx.globalCompositeOperation = 'source-over';
    const g = G[VIEWS[state.view].vel];
    fctx.lineWidth = 1.1 * DPR; fctx.strokeStyle = 'rgba(255,255,255,0.78)';
    fctx.beginPath();
    for (const p of parts) {
      const [u, v] = sampleVel(g, p.x, p.y);
      const nx = p.x + u * TIME_SCALE, ny = p.y + v * TIME_SCALE;
      p.age++;
      if (p.age > p.life || nx < 0 || nx > LX || ny < 0 || ny > LY || inBuilding(nx, ny) || (u * u + v * v) < 0.01 && p.age > 30) {
        spawn(p); continue;
      }
      const [x0, y0] = toPx(p.x, p.y), [x1, y1] = toPx(nx, ny);
      fctx.moveTo(x0, y0); fctx.lineTo(x1, y1);
      p.x = nx; p.y = ny;
    }
    fctx.stroke();
  }
  requestAnimationFrame(step);
}

// ---------------- probe ----------------
const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSO', 'SO', 'OSO', 'O', 'ONO', 'NO', 'NNO'];
const f1 = (v, d = 1) => (v === null || !isFinite(v) ? '—' : v.toFixed(d));
function probeAt(x, y) {
  const el = $('#probe');
  const pos = `<span class="pill">x = ${x.toFixed(0)} m · y = ${y.toFixed(0)} m</span>`;
  if (inBuilding(x, y)) {
    state.probe = { x, y };
    el.innerHTML = `<h2>Punto seleccionado</h2>${pos}<p class="building" style="margin-top:10px">🏢 Aquí hay un edificio: dentro no hay viento que predecir.</p>`;
    drawOver(); return;
  }
  const [u, v, p] = netEval(x, y), s = Math.hypot(u, v);
  const from = (Math.atan2(-u, -v) * 180 / Math.PI + 360) % 360;
  const comp = COMPASS[Math.round(from / 22.5) % 16];
  const su = sampleField(F.u, x, y), sv = sampleField(F.v, x, y), sp = sampleField(F.p, x, y);
  const ss = su !== null ? Math.hypot(su, sv) : null;
  const bu = sampleField(F.base_u, x, y), bv = sampleField(F.base_v, x, y);
  const bs = bu !== null ? Math.hypot(bu, bv) : null;
  const toward = Math.atan2(v, u) * 180 / Math.PI;
  state.probe = { x, y, uv: [u, v] };
  el.innerHTML = `
    <h2>Predicción de la PINN</h2>${pos}
    <div class="dirrow">
      <svg class="arrow" viewBox="-24 -24 48 48" aria-hidden="true">
        <circle r="22" fill="none" stroke="#243142" stroke-width="2"/>
        <text y="-13" text-anchor="middle" font-size="8" fill="#8d9bad">N</text>
        <g transform="rotate(${(-toward).toFixed(1)})"><path d="M-14 0H10M4-6l8 6-8 6" stroke="#59d8ff" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/></g>
      </svg>
      <div><div class="big">${f1(s)} <span class="unit">m/s</span></div>
      <div class="muted">${f1(s * 3.6)} km/h</div></div>
    </div>
    <dl class="kv">
      <dt>Dirección (de dónde viene)</dt><dd>${from.toFixed(0)}° · ${comp}</dd>
      <dt>u (hacia el este)</dt><dd>${f1(u, 2)} m/s</dd>
      <dt>v (hacia el norte)</dt><dd>${f1(v, 2)} m/s</dd>
      <dt>Presión (relativa)</dt><dd>${f1(p)} Pa</dd>
    </dl>
    <div class="cmp">
      <dl class="kv">
        <dt>Simulación (verdad)</dt><dd>${f1(ss)} m/s · ${f1(sp)} Pa</dd>
        <dt>Error de la PINN</dt><dd>${ss === null ? '—' : f1(Math.abs(s - ss)) + ' m/s'}</dd>
        <dt>Interpolación sin física</dt><dd>${f1(bs)} m/s${ss === null ? '' : ' (error ' + f1(Math.abs(bs - ss)) + ')'}</dd>
      </dl>
    </div>`;
  drawOver();
}
wrap.addEventListener('click', (e) => {
  if (!G.pinn) return;
  const r = wrap.getBoundingClientRect();
  probeAt((e.clientX - r.left) / r.width * LX, (1 - (e.clientY - r.top) / r.height) * LY);
});

// ---------------- metrics + text ----------------
function renderMetrics() {
  const R = M.metrics;
  const rows = [
    ['PINN (datos + física)', R.pinn, 'pinn'],
    ['Interpolación lineal', R.baseline_griddata, ''],
    ['Misma red, sin física', R.baseline_mlp_data_only, ''],
  ].filter((r) => r[1]);
  const cols = [['rel_l2_speed', 'Error rel. rapidez', (v) => (v * 100).toFixed(0) + ' %'],
    ['mae_speed_ms', 'Error medio', (v) => v.toFixed(2) + ' m/s'],
    ['mae_pressure_pa', 'Error presión', (v) => v.toFixed(1) + ' Pa']];
  const best = {};
  cols.forEach(([k]) => { best[k] = Math.min(...rows.map((r) => r[1][k])); });
  $('#metrics').innerHTML = `<tr><th>Método</th>${cols.map((c) => `<th>${c[1]}</th>`).join('')}</tr>` +
    rows.map(([n, m, cls]) => `<tr class="${cls}"><td>${n}</td>${cols.map(([k, , fmt]) =>
      `<td class="${m[k] === best[k] ? 'best' : ''}">${fmt(m[k])}</td>`).join('')}</tr>`).join('');
  const pi = R.pinn.rel_l2_speed, gd = R.baseline_griddata.rel_l2_speed;
  $('#verdict').innerHTML = pi < gd
    ? `Con los mismos ${R.n_sensors} sensores, la física reduce el error de rapidez de <b>${(gd * 100).toFixed(0)} %</b> a <b>${(pi * 100).toFixed(0)} %</b> (${((1 - pi / gd) * 100).toFixed(0)} % menos). No es perfecta: le cuesta reproducir los chorros más estrechos entre edificios (mira la vista de error).`
    : `Honestamente: en este entrenamiento la PINN (${(pi * 100).toFixed(0)} %) no supera a la interpolación lineal (${(gd * 100).toFixed(0)} %).`;
  $('#nSensors').textContent = R.n_sensors;
  $('#nCells').textContent = R.n_fluid_cells.toLocaleString('es');
  const C = R.config, ph = M.physics;
  const arch = `${C.depth} capas ocultas × ${C.width} neuronas, tanh${M.fourier ? `, ${C.ff} rasgos de Fourier (σ = ${C.ff_sigma})` : ''}`;
  $('#tech').innerHTML = `<ul>
    <li><b>Red:</b> (x, y) → (u, v, p), ${arch}. Entradas normalizadas a [−1, 1]; salidas escaladas por U₀ = ${ph.U0} m/s y P₀ = ρU₀² = ${(ph.rho * ph.U0 ** 2).toFixed(0)} Pa.</li>
    <li><b>Datos:</b> ${R.n_sensors} “sensores” en celdas de aire elegidas al azar (semilla fija), cada uno mide u, v y p.</li>
    <li><b>Física:</b> Navier–Stokes 2D estacionario e incompresible con ρ = ${ph.rho} kg/m³ y ν = ${ph.nu.toFixed(2)} m²/s (la viscosidad efectiva de la simulación): u<sub>x</sub> + v<sub>y</sub> = 0; u u<sub>x</sub> + v u<sub>y</sub> + p<sub>x</sub>/ρ − ν∇²u = 0; igual para v. Derivadas exactas con diferenciación automática en ${C.ncol} puntos de colocación aleatorios por iteración.</li>
    <li><b>Bordes:</b> no deslizamiento (u = v = 0) en las paredes de los edificios; entrada u = 5 m/s, v = 0, p = 0 en x = 0; v = 0 arriba y abajo.</li>
    <li><b>Pérdida:</b> ${ph.weights.data}·datos + ${ph.weights.pde}·física + ${ph.weights.bc}·bordes, con residuos adimensionalizados (L₀ = ${ph.L0} m).</li>
    <li><b>Entrenamiento:</b> Adam ${C.iters} iteraciones${C.lbfgs ? ` + L-BFGS ${C.lbfgs}` : ''}, CPU, ${(R.pinn.train_seconds / 60).toFixed(1)} min.</li>
    <li><b>Limitación honesta:</b> el campo de la simulación es un promedio temporal de un flujo con vórtices, así que no cumple exactamente las ecuaciones estacionarias; la física actúa como guía, no como verdad absoluta.</li>
  </ul>`;
}

// ---------------- UI ----------------
document.querySelectorAll('.seg button').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('.seg button').forEach((x) => x.classList.toggle('on', x === b));
  state.view = b.dataset.view;
  drawHeat(); fctx.clearRect(0, 0, W, H);
}));
$('#tParticles').addEventListener('change', (e) => { state.particles = e.target.checked; if (!state.particles) fctx.clearRect(0, 0, W, H); });
$('#tSensors').addEventListener('change', (e) => { state.sensors = e.target.checked; drawOver(); });
let rt; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(resize, 150); });

async function main() {
  try {
    [M, F] = await Promise.all([fetch('model.json').then((r) => r.json()), fetch('field.json').then((r) => r.json())]);
  } catch (e) {
    $('#loading').textContent = 'No se pudo cargar el modelo.'; return;
  }
  LX = F.Lx; LY = F.Ly; NET = buildNet(M);
  renderMetrics();
  await new Promise((r) => setTimeout(r, 30));
  const t0 = performance.now();
  precompute();
  console.log(`PINN evaluada en ${(G.pinn.nx * G.pinn.ny + F.nx * F.ny)} puntos en ${(performance.now() - t0).toFixed(0)} ms`);
  $('#loading').remove();
  resize();
  requestAnimationFrame(step);
}
main();
