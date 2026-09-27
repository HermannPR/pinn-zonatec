// Renderiza la visualizacion a cuadros RGB crudos en stdout, para ffmpeg.
//
// No es una grabacion de pantalla: cada cuadro se compone aqui, con control
// del tiempo, de las transiciones y del avance de las particulas.
import { cargar, predecirMalla } from "./modelo.mjs";
import { readFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";

const W = 1920, H = 1080, FPS = 30;
const { M, F } = cargar("public/model.json", "public/field.json");
const P = predecirMalla(M, F);
const { nx, ny, dx, x0, y0, Lx, Ly } = F;

// ---------- utilidades de color ----------
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
const mezcla = (a, b, t) => a + (b - a) * t;
const suave = (t) => t * t * (3 - 2 * t);           // suavizado de extremos

/** Escala de velocidad: azul profundo -> cian -> ambar -> blanco caliente. */
function colorVel(t) {
  t = clamp(t, 0, 1);
  const paradas = [
    [0.00, 8, 14, 38], [0.25, 18, 86, 140], [0.50, 34, 178, 176],
    [0.72, 230, 178, 62], [0.90, 244, 108, 52], [1.00, 255, 244, 214],
  ];
  for (let i = 1; i < paradas.length; i++) {
    if (t <= paradas[i][0]) {
      const [p0, r0, g0, b0] = paradas[i - 1], [p1, r1, g1, b1] = paradas[i];
      const f = (t - p0) / (p1 - p0);
      return [mezcla(r0, r1, f), mezcla(g0, g1, f), mezcla(b0, b1, f)];
    }
  }
  return [255, 244, 214];
}

/** Escala de error: transparente -> magenta. El error se SUMA, no sustituye. */
function colorErr(t) {
  t = clamp(t, 0, 1);
  return [mezcla(10, 255, t), mezcla(10, 60, t), mezcla(20, 180, t)];
}

// ---------- geometria: la ciudad ocupa un rectangulo centrado ----------
const MARGEN_X = 130, MARGEN_SUP = 210, MARGEN_INF = 190;
const escala = Math.min((W - MARGEN_X * 2) / Lx, (H - MARGEN_SUP - MARGEN_INF) / Ly);
const OX = (W - Lx * escala) / 2;
const OY = MARGEN_SUP + (H - MARGEN_SUP - MARGEN_INF - Ly * escala) / 2;
const aPantalla = (x, y) => [OX + x * escala, OY + (Ly - y) * escala];

const idx = (ix, iy) => ix * ny + iy;
const dentro = (ix, iy) => ix >= 0 && ix < nx && iy >= 0 && iy < ny;

/** Muestreo bilineal de un campo en coordenadas del mundo. */
function muestrea(campo, x, y) {
  const fx = (x - x0) / dx, fy = (y - y0) / dx;
  const ix = Math.floor(fx), iy = Math.floor(fy);
  if (!dentro(ix, iy) || !dentro(ix + 1, iy + 1)) return 0;
  const tx = fx - ix, ty = fy - iy;
  return mezcla(
    mezcla(campo[idx(ix, iy)], campo[idx(ix + 1, iy)], tx),
    mezcla(campo[idx(ix, iy + 1)], campo[idx(ix + 1, iy + 1)], tx), ty);
}
function esSolido(x, y) {
  const ix = Math.round((x - x0) / dx), iy = Math.round((y - y0) / dx);
  return !dentro(ix, iy) || F.solid[idx(ix, iy)] === 1;
}

const VEL_MAX = 13;

// ---------- particulas ----------
const NPART = 2600;
const part = [];
function nacer(p, alAzar) {
  p.x = alAzar ? Math.random() * Lx : Math.random() * 12;
  p.y = Math.random() * Ly;
  p.vida = 0;
  p.max = 60 + Math.random() * 140;
  let intentos = 0;
  while (esSolido(p.x, p.y) && intentos++ < 30) {
    p.x = Math.random() * Lx; p.y = Math.random() * Ly;
  }
}
for (let i = 0; i < NPART; i++) { const p = {}; nacer(p, true); part.push(p); }

function avanzar(u, v, dt) {
  for (const p of part) {
    const vx = muestrea(u, p.x, p.y), vy = muestrea(v, p.x, p.y);
    p.px = p.x; p.py = p.y;
    p.x += vx * dt; p.y += vy * dt;
    p.vida++;
    if (p.x > Lx || p.x < 0 || p.y > Ly || p.y < 0 || p.vida > p.max || esSolido(p.x, p.y)) {
      nacer(p, false);
      p.px = p.x; p.py = p.y;
    }
  }
}

// ---------- lienzo ----------
const buf = Buffer.alloc(W * H * 3);
function limpiar(r, g, b) { for (let i = 0; i < buf.length; i += 3) { buf[i] = r; buf[i+1] = g; buf[i+2] = b; } }
function pinta(x, y, r, g, b, a = 1) {
  x |= 0; y |= 0;
  if (x < 0 || x >= W || y < 0 || y >= H) return;
  const o = (y * W + x) * 3;
  buf[o]   = clamp(buf[o]   * (1 - a) + r * a, 0, 255);
  buf[o+1] = clamp(buf[o+1] * (1 - a) + g * a, 0, 255);
  buf[o+2] = clamp(buf[o+2] * (1 - a) + b * a, 0, 255);
}
function suma(x, y, r, g, b, a) {
  x |= 0; y |= 0;
  if (x < 0 || x >= W || y < 0 || y >= H) return;
  const o = (y * W + x) * 3;
  buf[o]   = clamp(buf[o]   + r * a, 0, 255);
  buf[o+1] = clamp(buf[o+1] + g * a, 0, 255);
  buf[o+2] = clamp(buf[o+2] + b * a, 0, 255);
}
function linea(x0_, y0_, x1_, y1_, r, g, b, a) {
  const d = Math.max(Math.abs(x1_ - x0_), Math.abs(y1_ - y0_)) | 0;
  for (let i = 0; i <= d; i++) {
    const t = d ? i / d : 0;
    suma(mezcla(x0_, x1_, t), mezcla(y0_, y1_, t), r, g, b, a);
  }
}
export { W, H, FPS, buf, limpiar, pinta, suma, linea, aPantalla, muestrea, esSolido,
         colorVel, colorErr, VEL_MAX, part, avanzar, nacer, F, P, M, nx, ny, idx,
         escala, OX, OY, clamp, mezcla, suave, Lx, Ly, dx, x0, y0 };
