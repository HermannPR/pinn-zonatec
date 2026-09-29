"""Write queue jobs (E:/PINN/cola/README.md) for Zona Tec mesh / direction cases that already exist on disk.

  python make_jobs.py --id 100 --kind mesh --case E:/PINN/runs/zonatec/mesh_empty_fine --after 022_aij_bld_ske_M
  python make_jobs.py --id 101 --kind case --case E:/PINN/runs/zonatec/zt_empty_th1125_U050_m1_hom --after 100_zt_mesh_empty_fine
Job ids: 1xx_zt_<name> (Zona Tec; AIJ uses 0xx)."""
import argparse
import json
from pathlib import Path

PY = r"E:\PINN\.venv\Scripts\python.exe"
SC = r"E:\PINN\v2\cfd\zonatec\scripts"
ap = argparse.ArgumentParser()
ap.add_argument("--id", type=int, required=True)
ap.add_argument("--kind", choices=["mesh", "case"], required=True)
ap.add_argument("--case", required=True)
ap.add_argument("--after", nargs="*", default=[])
ap.add_argument("--fase", default="F2 Zona Tec piloto")
ap.add_argument("--notify", default="")
ap.add_argument("--hang", type=int, default=None)
ap.add_argument("--attempts", type=int, default=None)
ap.add_argument("--min-free-gb", type=int, default=15)
a = ap.parse_args()
case = Path(a.case)
if not (case / "Allrun").exists():
    raise SystemExit(f"no Allrun in {case}")
name = case.name.replace("mesh_", "mesh_") if a.kind == "mesh" else case.name.replace("zt_", "")
jid = f"{a.id:03d}_zt_{name}"
ver = "verify_mesh.py" if a.kind == "mesh" else "verify_case.py"
job = {"id": jid, "fase": a.fase, "kind": "openfoam", "case": str(case).replace("/", "\\"), "cmd": "bash ./Allrun",
       "verify": f"& '{PY}' '{SC}\\{ver}' '{str(case)}'; exit $LASTEXITCODE",
       "min_free_gb": a.min_free_gb,
       "max_attempts": a.attempts or (2 if a.kind == "mesh" else 3),
       "hang_minutes": a.hang or (120 if a.kind == "mesh" else 90),
       "notify": a.notify or f"Zona Tec {a.kind}: {case.name}"}
if a.after:
    job["after"] = a.after
out = Path(r"E:\PINN\cola\jobs") / f"{jid}.json"
out.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out}")
