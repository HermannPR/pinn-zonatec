"""Plan (and optionally create + enqueue) the 16-direction base campaign on one mesh.

Order: circular from the pilot direction 112.5 deg; each TRAINING direction is warm-started from the previous
training direction (U rotated in place, warmstart.py). The four HELD-OUT directions of the sealed split
(22.5, 157.5, 247.5, 337.5; PLAN F3) are COLD-started (log-law init) so they carry no memory of a neighbouring
solution (review F1 M9/C7). Job ids 110.. (1xx_zt_*), each after its warm-start source (or after the mesh).

  python campaign.py --mesh E:/PINN/runs/zonatec/mesh_base_fine                 # print plan only
  python campaign.py --mesh ... --create --enqueue --start-id 110               # create cases + queue jobs
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from zt_common import PY, RUNS, case_id  # noqa: E402

HELD_OUT = {22.5, 157.5, 247.5, 337.5}
HERE = Path(__file__).resolve().parent


def plan(start=112.5, U10=5.0):
    dirs = [(start + 22.5 * i) % 360 for i in range(16)]
    out, prev = [], None
    for th in dirs:
        if th in HELD_OUT:
            out.append((th, None))
        else:
            out.append((th, prev))
            prev = th
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", required=True)
    ap.add_argument("--U10", type=float, default=5.0)
    ap.add_argument("--model", default="realizableKE")
    ap.add_argument("--start-id", type=int, default=110)
    ap.add_argument("--skip", nargs="*", type=float, default=[], help="directions already done (e.g. the pilot)")
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--enqueue", action="store_true")
    a = ap.parse_args()
    mesh = Path(a.mesh)
    mm = json.loads((mesh / "mesh.json").read_text())
    variant, level = mm["variant"], mm["level"]["level"]
    mesh_job = f"_zt_mesh_{variant}_{level}"
    jid = a.start_id
    ids = {}
    for th, src in plan(U10=a.U10):
        cid = case_id(variant, th, a.U10, level, a.model)
        warm = RUNS / case_id(variant, src, a.U10, level, a.model) if src is not None else None
        print(f"{jid:03d}  theta {th:6.1f}  {'COLD (held-out)' if th in HELD_OUT else ('COLD' if warm is None else 'warm from ' + str(src))}  -> {cid}")
        if th in a.skip:
            ids[th] = None
            continue
        if a.create and not (RUNS / cid).exists():
            cmd = [PY, str(HERE / "gen_case.py"), "--mesh", str(mesh), "--theta", str(th), "--U10", str(a.U10),
                   "--model", a.model]
            if warm is not None:
                cmd += ["--warm-from", str(warm)]
            subprocess.run(cmd, check=True)
        if a.enqueue:
            after = []
            if src is not None and ids.get(src):
                after = [ids[src]]
            cmd = [PY, str(HERE / "make_jobs.py"), "--id", str(jid), "--kind", "case", "--case", str(RUNS / cid),
                   "--fase", "F3 campana base", "--notify", f"campana base theta {th}"]
            if after:
                cmd += ["--after", *after]
            subprocess.run(cmd, check=True)
        ids[th] = f"{jid:03d}_zt_{cid.replace('zt_', '')}"
        jid += 1


if __name__ == "__main__":
    main()
