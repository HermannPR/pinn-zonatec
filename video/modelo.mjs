// Evalua la PINN exportada. Sin dependencias: el modelo son pesos crudos, un
// MLP con tanh y rasgos de Fourier, asi que se reimplementa en unas lineas.
import { readFileSync } from "node:fs";

export function cargar(rutaModelo, rutaCampo) {
  const M = JSON.parse(readFileSync(rutaModelo, "utf8"));
  const F = JSON.parse(readFileSync(rutaCampo, "utf8"));
  return { M, F };
}

/** Normaliza a [-1,1], aplica Fourier si existe, y pasa por las capas. */
export function predecir(M, x, y) {
  const n = M.in_norm;
  let a = [
    2 * ((x - n.xmin) / (n.xmax - n.xmin)) - 1,
    2 * ((y - n.ymin) / (n.ymax - n.ymin)) - 1,
  ];

  // B es [2][nff], y las coordenadas crudas SE CONSERVAN ademas de los senos y
  // cosenos: la primera capa espera 2 + 2*nff entradas, no 2*nff.
  if (M.fourier?.B) {
    const B = M.fourier.B;
    const nff = B[0].length;
    const ent = [a[0], a[1]];
    for (let k = 0; k < nff; k++) {
      const z = Math.PI * (a[0] * B[0][k] + a[1] * B[1][k]);
      ent.push(Math.sin(z));
    }
    for (let k = 0; k < nff; k++) {
      const z = Math.PI * (a[0] * B[0][k] + a[1] * B[1][k]);
      ent.push(Math.cos(z));
    }
    a = ent;
  }

  for (let li = 0; li < M.layers.length; li++) {
    const L = M.layers[li];
    const ultima = li === M.layers.length - 1;
    const salida = new Array(L.W.length);
    for (let j = 0; j < L.W.length; j++) {
      const fila = L.W[j];
      let s = L.b[j];
      for (let i = 0; i < fila.length; i++) s += fila[i] * a[i];
      salida[j] = ultima ? s : Math.tanh(s);
    }
    a = salida;
  }

  const o = M.out_scale;
  return [a[0] * o.u, a[1] * o.v, a[2] * o.p];
}

/** Malla completa: devuelve u,v,p de la PINN en cada celda. */
export function predecirMalla(M, F) {
  const { nx, ny, dx, x0, y0 } = F;
  const u = new Float64Array(nx * ny), v = new Float64Array(nx * ny), p = new Float64Array(nx * ny);
  for (let ix = 0; ix < nx; ix++) {
    for (let iy = 0; iy < ny; iy++) {
      const k = ix * ny + iy;
      const [pu, pv, pp] = predecir(M, x0 + ix * dx, y0 + iy * dx);
      u[k] = pu; v[k] = pv; p[k] = pp;
    }
  }
  return { u, v, p };
}
