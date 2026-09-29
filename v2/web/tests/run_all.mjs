// run_all.mjs -- runs every JS-vs-Python correctness test in sequence and
// exits non-zero if any fails. See web/README.md "Pruebas".
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const tests = ["test_model.mjs", "test_features.mjs", "test_climate.mjs"];

let ok = true;
for (const t of tests) {
  console.log(`\n=== ${t} ===`);
  const res = spawnSync(process.execPath, [join(__dirname, t)], { stdio: "inherit" });
  if (res.status !== 0) ok = false;
}
process.exit(ok ? 0 : 1);
