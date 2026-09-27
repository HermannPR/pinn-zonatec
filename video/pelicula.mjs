// Compone la pelicula cuadro a cuadro y la escribe en stdout como RGB crudo.
// Se conecta a ffmpeg por tuberia: nunca toca el disco con cuadros sueltos.
import * as R from "./render.mjs";
import { texto, dibuja } from "./texto.mjs";

const { W, H, FPS, buf, limpiar, pinta, suma, linea, aPantalla, muestrea,
        colorVel, colorErr, VEL_MAX, part, avanzar, F, P, M, nx, ny, idx,
        escala, OX, OY, clamp, mezcla, suave, Lx, Ly } = R;

const BLANCO = [236, 240, 248], TENUE = [128, 142, 165], ACENTO = [120, 214, 226];
const SENSORES = M.sensors;

const ESCENAS = [
  ["ciudad",     4.0],
  ["simulacion", 9.0],
  ["sensores",   6.0],
  ["pinn",       9.0],
  ["comparar",  10.0],
  ["numeros",    7.0],
];
const TOTAL = ESCENAS.reduce((a, [, d]) => a + d, 0);

function escenaEn(t) {
  let acc = 0;
  for (const [nombre, dur] of ESCENAS) {
    if (t < acc + dur) return { nombre, local: t - acc, dur };
    acc += dur;
  }
  const u = ESCENAS[ESCENAS.length - 1];
  return { nombre: u[0], local: u[1], dur: u[1] };
}

/** Sube de 0 a 1 en los primeros `e` segundos y baja al final. */
const entra = (l, e = 0.7) => suave(clamp(l / e, 0, 1));
const sale = (l, d, e = 0.7) => suave(clamp((d - l) / e, 0, 1));

// ---------- piezas de dibujo ----------
function fondo() {
  // Degradado muy sutil: el negro plano se ve barato en video.
  for (let y = 0; y < H; y++) {
    const t = y / H;
    const r = 7 + t * 4, g = 9 + t * 6, b = 14 + t * 10;
    for (let x = 0; x < W; x++) {
      const o = (y * W + x) * 3;
      buf[o] = r; buf[o + 1] = g; buf[o + 2] = b;
    }
  }
}

function edificios(alfa) {
  for (const b of F.buildings) {
    const [px0, py1] = aPantalla(b.x0, b.y0);
    const [px1, py0] = aPantalla(b.x1, b.y1);
    for (let y = py0 | 0; y <= py1; y++) {
      for (let x = px0 | 0; x <= px1; x++) {
        const borde = x <= px0 + 1 || x >= px1 - 1 || y <= py0 + 1 || y >= py1 - 1;
        if (borde) pinta(x, y, 96, 110, 134, alfa);
        else pinta(x, y, 17, 21, 30, alfa);
      }
    }
  }
}

/** Pinta un campo escalar sobre el rectangulo de la ciudad. */
function campo(u, v, alfa, modoError = null) {
  const x1 = OX + Lx * escala, y1 = OY + Ly * escala;
  for (let py = OY | 0; py < y1; py++) {
    const wy = Ly - (py - OY) / escala;
    for (let px = OX | 0; px < x1; px++) {
      const wx = (px - OX) / escala;
      if (R.esSolido(wx + F.x0, wy + F.y0)) continue;
      let c;
      if (modoError) {
        const e = muestrea(modoError, wx + F.x0, wy + F.y0);
        c = colorErr(e / 5);
      } else {
        const s = Math.hypot(muestrea(u, wx + F.x0, wy + F.y0),
                             muestrea(v, wx + F.x0, wy + F.y0));
        c = colorVel(s / VEL_MAX);
      }
      pinta(px, py, c[0], c[1], c[2], alfa);
    }
  }
}

function particulas(alfa) {
  for (const p of part) {
    const [x, y] = aPantalla(p.x, p.y);
    const [xp, yp] = aPantalla(p.px ?? p.x, p.py ?? p.y);
    const s = Math.hypot(muestrea(F.u, p.x, p.y), muestrea(F.v, p.x, p.y));
    const c = colorVel(clamp(s / VEL_MAX + 0.25, 0, 1));
    // Se desvanecen al nacer y al morir: sin eso aparecen y desaparecen de golpe.
    const vf = Math.min(p.vida / 12, 1) * Math.min((p.max - p.vida) / 18, 1);
    linea(xp, yp, x, y, c[0], c[1], c[2], 0.5 * alfa * clamp(vf, 0, 1));
  }
}

function sensores(alfa, brillo = 1) {
  for (const [sx, sy] of SENSORES) {
    const [x, y] = aPantalla(sx, sy);
    suma(x, y, 255, 255, 255, alfa);
    for (const [dx_, dy_] of [[1,0],[-1,0],[0,1],[0,-1]]) {
      suma(x + dx_, y + dy_, 180, 230, 255, 0.55 * alfa * brillo);
    }
    for (const [dx_, dy_] of [[1,1],[-1,1],[1,-1],[-1,-1],[2,0],[-2,0],[0,2],[0,-2]]) {
      suma(x + dx_, y + dy_, 120, 200, 255, 0.22 * alfa * brillo);
    }
  }
}

function marco(alfa) {
  const x1 = OX + Lx * escala, y1 = OY + Ly * escala;
  for (let x = OX | 0; x <= x1; x++) { suma(x, OY, 60, 74, 96, alfa); suma(x, y1, 60, 74, 96, alfa); }
  for (let y = OY | 0; y <= y1; y++) { suma(OX, y, 60, 74, 96, alfa); suma(x1, y, 60, 74, 96, alfa); }
}

function rotulo(cadena, tam, x, y, alfa, color = BLANCO, centrado = false) {
  if (alfa <= 0.004) return;
  const t = texto(cadena, tam, color);
  dibuja(pinta, t, centrado ? x - t.ancho / 2 : x, y, alfa);
}

// campo de error precalculado
const ERR = new Float64Array(nx * ny);
for (let k = 0; k < ERR.length; k++) {
  if (F.solid[k]) continue;
  ERR[k] = Math.abs(Math.hypot(P.u[k], P.v[k]) - Math.hypot(F.u[k], F.v[k]));
}

// ---------- bucle principal ----------
const nCuadros = Math.round(TOTAL * FPS);

/** Escribe respetando la contrapresion de la tuberia.
 *  Sin esto Node acumula los 1350 cuadros en memoria (8 GB) y la escritura
 *  falla con EINVAL cuando ffmpeg no consume tan rapido como generamos. */
function escribir(b) {
  return new Promise((res) => {
    if (process.stdout.write(b)) res();
    else process.stdout.once("drain", res);
  });
}

for (let n = 0; n < nCuadros; n++) {
  const t = n / FPS;
  const { nombre, local, dur } = escenaEn(t);
  fondo();

  const campoVivo = nombre === "pinn" || nombre === "comparar" ? P : F;
  avanzar(campoVivo.u ?? F.u, campoVivo.v ?? F.v, 0.9);

  if (nombre === "ciudad") {
    const a = entra(local, 1.4);
    marco(a * 0.8);
    edificios(a);
    rotulo("Reconstruir el viento de una ciudad", 62, W / 2, 96, a, BLANCO, true);
    rotulo("480 x 240 metros  ·  31 edificios  ·  viento de entrada 5 m/s",
           27, W / 2, H - 132, entra(local - 0.9, 1.2), TENUE, true);
  }

  else if (nombre === "simulacion") {
    const a = entra(local, 1.2) * sale(local, dur, 0.8);
    campo(F.u, F.v, a);
    edificios(1);
    particulas(a);
    marco(0.8);
    rotulo("Simulación de fluidos", 54, W / 2, 96, a, BLANCO, true);
    rotulo("Lattice-Boltzmann · 23 809 celdas resueltas · esto es la verdad de referencia",
           26, W / 2, H - 132, a, TENUE, true);
  }

  else if (nombre === "sensores") {
    const desvanece = suave(clamp(local / 1.8, 0, 1));
    campo(F.u, F.v, 0.9 * (1 - desvanece * 0.88));
    edificios(1);
    particulas(0.25 * (1 - desvanece));
    sensores(entra(local - 0.8, 1.4), 1 + 0.4 * Math.sin(local * 3));
    marco(0.8);
    rotulo("Lo único que ve el modelo", 54, W / 2, 96, entra(local, 1), BLANCO, true);
    rotulo("250 sensores  ·  el 1 % del mapa", 30, W / 2, H - 132,
           entra(local - 1.2, 1), ACENTO, true);
  }

  else if (nombre === "pinn") {
    // La reconstruccion "crece" desde los sensores hacia fuera.
    const a = suave(clamp((local - 0.6) / 2.6, 0, 1));
    campo(P.u, P.v, a);
    edificios(1);
    particulas(a * 0.95);
    sensores(clamp(1 - local / 2.4, 0, 1) * 0.9);
    marco(0.8);
    rotulo("Lo que reconstruye la red", 54, W / 2, 96, entra(local, 1), BLANCO, true);
    rotulo("Red informada por la física · obligada a cumplir Navier-Stokes",
           26, W / 2, H - 132, entra(local - 1, 1.2), TENUE, true);
  }

  else if (nombre === "comparar") {
    const fase = local / dur;
    if (fase < 0.55) {
      // Barrido vertical: simulacion a la izquierda, PINN a la derecha.
      const corte = OX + Lx * escala * suave(clamp((local - 0.5) / 3.5, 0, 1));
      campo(F.u, F.v, 1);
      const x1 = OX + Lx * escala, y1 = OY + Ly * escala;
      for (let py = OY | 0; py < y1; py++) {
        const wy = Ly - (py - OY) / escala;
        for (let px = corte | 0; px < x1; px++) {
          const wx = (px - OX) / escala;
          if (R.esSolido(wx + F.x0, wy + F.y0)) continue;
          const s = Math.hypot(muestrea(P.u, wx + F.x0, wy + F.y0),
                               muestrea(P.v, wx + F.x0, wy + F.y0));
          const c = colorVel(s / VEL_MAX);
          pinta(px, py, c[0], c[1], c[2], 1);
        }
      }
      for (let py = OY | 0; py < y1; py++) suma(corte, py, 255, 255, 255, 0.85);
      edificios(1);
      marco(0.8);
      rotulo("Simulación", 34, OX + 24, OY - 54, 1, TENUE);
      rotulo("Reconstrucción", 34, OX + Lx * escala - 24 - texto("Reconstrucción", 34, TENUE).ancho,
             OY - 54, 1, ACENTO);
      rotulo("Mismo mapa, dos orígenes", 50, W / 2, 96, entra(local, 1), BLANCO, true);
    } else {
      const a = suave(clamp((local - dur * 0.55) / 1.2, 0, 1));
      campo(null, null, a, ERR);
      edificios(1);
      marco(0.8);
      rotulo("Dónde se equivoca", 50, W / 2, 96, a, BLANCO, true);
      rotulo("Error absoluto de rapidez · magenta = mayor desacuerdo",
             26, W / 2, H - 132, a, TENUE, true);
    }
  }

  else if (nombre === "numeros") {
    const a = entra(local, 1);
    campo(P.u, P.v, 0.10 * a);
    edificios(0.5 * a);
    const m = M.metrics;
    const filas = [
      ["", "PINN", "Interpolación", "MLP sin física"],
      ["Error relativo de rapidez",
        m.pinn.rel_l2_speed.toFixed(3),
        m.baseline_griddata.rel_l2_speed.toFixed(3),
        m.baseline_mlp_data_only.rel_l2_speed.toFixed(3)],
      ["Error de presión (Pa)",
        m.pinn.mae_pressure_pa.toFixed(2),
        m.baseline_griddata.mae_pressure_pa.toFixed(2),
        m.baseline_mlp_data_only.mae_pressure_pa.toFixed(2)],
    ];
    rotulo("Los números, completos", 54, W / 2, 128, a, BLANCO, true);
    const cols = [W / 2 - 560, W / 2 + 100, W / 2 + 330, W / 2 + 600];
    filas.forEach((fila, i) => {
      const ay = 300 + i * 92;
      const af = suave(clamp((local - 0.8 - i * 0.45) / 0.8, 0, 1));
      fila.forEach((celda, j) => {
        if (!celda) return;
        const esTitulo = i === 0;
        const ganador = !esTitulo && j === 1 && i === 1;
        const perdedor = !esTitulo && j === 1 && i === 2;
        const color = esTitulo ? TENUE : ganador ? [126, 224, 168]
                    : perdedor ? [244, 138, 120] : BLANCO;
        rotulo(celda, esTitulo ? 27 : 34, cols[j], ay, af, color, j > 0);
      });
    });
    rotulo("La red gana en velocidad y pierde en presión frente a una interpolación simple.",
           28, W / 2, 660, suave(clamp((local - 2.6) / 1, 0, 1)), BLANCO, true);
    rotulo("El término físico restringe el campo de velocidades; la presión queda determinada sólo hasta una constante.",
           25, W / 2, 706, suave(clamp((local - 3.2) / 1, 0, 1)), TENUE, true);
    rotulo("250 sensores  →  23 809 celdas", 46, W / 2, 830,
           suave(clamp((local - 4.2) / 1, 0, 1)), ACENTO, true);
  }

  // Viñeta suave, para que la vista caiga al centro.
  for (let y = 0; y < H; y += 1) {
    for (let x = 0; x < W; x += 1) {
      const dx_ = (x - W / 2) / (W / 2), dy_ = (y - H / 2) / (H / 2);
      const d = Math.sqrt(dx_ * dx_ + dy_ * dy_);
      if (d < 0.82) continue;
      const k = Math.min((d - 0.82) / 0.62, 1) * 0.55;
      const o = (y * W + x) * 3;
      buf[o] *= 1 - k; buf[o + 1] *= 1 - k; buf[o + 2] *= 1 - k;
    }
  }

  // Copia: el buffer se reutiliza en el siguiente cuadro y la escritura es
  // asincrona, asi que enviar el mismo objeto duplicaria cuadros.
  await escribir(Buffer.from(buf));
  if (n % 120 === 0) process.stderr.write(`  cuadro ${n}/${nCuadros}\n`);
}
process.stderr.write(`  listo: ${nCuadros} cuadros, ${TOTAL}s\n`);
