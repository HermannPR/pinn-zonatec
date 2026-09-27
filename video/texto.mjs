// Envoltorio del renderizador de texto en Swift. Cachea, porque el mismo
// rotulo aparece en decenas de cuadros y lanzar un proceso por cuadro seria
// absurdo.
import { execFileSync } from "node:child_process";
import { readFileSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";

const CACHE = "/tmp/wind-pinn-texto";
mkdirSync(CACHE, { recursive: true });
const memo = new Map();

export function texto(cadena, tam, rgb = [255, 255, 255]) {
  const clave = `${cadena}|${tam}|${rgb.join(",")}`;
  if (memo.has(clave)) return memo.get(clave);
  const h = createHash("md5").update(clave).digest("hex").slice(0, 16);
  const ruta = `${CACHE}/${h}.rgba`;
  const salida = execFileSync("./video/texto",
    [cadena, String(tam), String(rgb[0]), String(rgb[1]), String(rgb[2]), ruta],
    { encoding: "utf8" }).trim().split(" ").map(Number);
  const [ancho, alto, paso] = salida;
  const px = readFileSync(ruta);
  const t = { ancho, alto, paso, px };
  memo.set(clave, t);
  return t;
}

/** Dibuja el rotulo con su alfa. x,y es la esquina superior izquierda. */
export function dibuja(pinta, t, x, y, alfa = 1) {
  for (let j = 0; j < t.alto; j++) {
    for (let i = 0; i < t.ancho; i++) {
      const o = j * t.paso + i * 4;
      const a = t.px[o + 3] / 255;
      if (a < 0.004) continue;
      // Viene premultiplicado: hay que deshacerlo para mezclar bien.
      pinta(x + i, y + j, t.px[o] / a, t.px[o + 1] / a, t.px[o + 2] / a, a * alfa);
    }
  }
}

export const anchoDe = (cadena, tam) => texto(cadena, tam).ancho;
