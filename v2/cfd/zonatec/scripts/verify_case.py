"""Independent verification of a Zona Tec DIRECTION job (queue contract item 4). exit 0 only if
  * DONE present, no FAILED;
  * convcheck.check(): no NaN, mass balance < 1e-4, and (residuals < 1e-4 OR plateau + probes stable within 1 % U_H
    over the last 500 second-order iterations) -- review F1 C7;
  * no 'nan' in the solver logs;
  * the latest reconstructed time holds U p k nut eps|omega;
  * the HDF5 file of the data contract exists and opens (unless the case has no buildings / extraction disabled).
Usage: python verify_case.py <case>"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import convcheck  # noqa: E402
import ofio  # noqa: E402

case = Path(sys.argv[1])
meta = json.loads((case / "case.json").read_text())
ok, msg = True, []
if not (case / "DONE").exists() or (case / "FAILED").exists():
    ok = False; msg.append("DONE missing or FAILED present")
rep = convcheck.check(case)
msg.append(json.dumps({k: rep.get(k) for k in ("iteration", "final_initial_residuals", "probe_max_range_over_UH_last500",
                                                 "mass_balance", "criterion_A_residuals", "criterion_B_plateau_probes")}))
if not rep["converged"]:
    ok = False; msg.append("NOT CONVERGED by the C7 criterion")
for log in case.glob("log.simpleFoam.*"):
    if re.search(r"(=|\s)-?nan\b", log.read_text(errors="ignore"), re.I):
        ok = False; msg.append(f"NaN in {log.name}")
t = ofio.latest_time(case)
T = "omega" if meta["model"] == "kOmegaSST" else "epsilon"
if t is None or float(t) == 0 or not all((case / t / f).exists() for f in ("U", "p", "k", "nut", T)):
    ok = False; msg.append(f"reconstructed latest time missing/incomplete ({t})")
if meta.get("has_buildings") and "extraction disabled" not in (case / "Allrun").read_text():
    h5 = Path(r"E:\PINN\v2\data\processed") / f"{meta['case_id']}.h5"
    try:
        import h5py
        with h5py.File(h5, "r") as f:
            n = f["x"].shape[0]
            msg.append(f"HDF5 {h5.name}: {n} points, attrs converged={f.attrs.get('converged')}")
            if n == 0:
                ok = False
    except Exception as e:  # noqa: BLE001
        ok = False; msg.append(f"HDF5 missing/unreadable: {h5} ({e})")
print("\n".join(msg))
print("VERIFY", "OK" if ok else "FAIL", case.name)
sys.exit(0 if ok else 1)
