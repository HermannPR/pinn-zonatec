// Comprueba que mi reimplementacion del modelo reproduce la metrica que
// reporto el entrenamiento. Si sale 0.317, la implementacion es correcta.
import { cargar, predecirMalla } from "./modelo.mjs";

const { M, F } = cargar("public/model.json", "public/field.json");
const t0 = Date.now();
const P = predecirMalla(M, F);
const ms = Date.now() - t0;

let numSpd = 0, denSpd = 0, n = 0;
for (let k = 0; k < F.u.length; k++) {
  if (F.solid[k]) continue;
  const vt = Math.hypot(F.u[k], F.v[k]);
  const vp = Math.hypot(P.u[k], P.v[k]);
  numSpd += (vp - vt) ** 2;
  denSpd += vt ** 2;
  n++;
}
const rel = Math.sqrt(numSpd) / Math.sqrt(denSpd);

console.log(`  celdas fluidas evaluadas: ${n}`);
console.log(`  tiempo de evaluacion:     ${ms} ms`);
console.log(`  rel_l2_speed calculado:   ${rel.toFixed(5)}`);
console.log(`  rel_l2_speed reportado:   ${M.metrics.pinn.rel_l2_speed.toFixed(5)}`);
const dif = Math.abs(rel - M.metrics.pinn.rel_l2_speed);
console.log(`  diferencia:               ${dif.toFixed(6)}  ${dif < 0.02 ? "-> implementacion correcta" : "-> ALGO NO CUADRA"}`);
