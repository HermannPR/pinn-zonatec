"""Generate a Zona Tec MESH case (one per geometry variant and mesh level; reused by all 16 directions).

  python gen_mesh.py --variant base --level fine  [--out E:/PINN/runs/zonatec/mesh_base_fine] [--np 6]
  python gen_mesh.py --variant empty --level fine        # homogeneity test mesh: same everything, no buildings

Pipeline written into <case>/Allrun (resumable, queue contract): blockMesh O-grid -> 32-segment lateral split
(split_lateral.py + createPatch) -> surfaceFeatureExtract -> decomposePar -> snappyHexMesh -parallel (castellate,
snap, 3 ground layers on ground_zoi), RAM monitored by memwatch.ps1 -> reconstructParMesh -> checkMesh (+ wall
distance and cell volumes) -> writeCellCentres -> mesh_stats.py. See README.md §3 for the design rationale.
"""
from __future__ import annotations

import argparse
import math
import shutil
from pathlib import Path

import numpy as np

import buildings as B
from zt_common import (RUNS, S_CORE, SCRIPTS_UNIX, PY_UNIX, dump_json, domain, foam, level_info,
                       refinement_boxes, write_text)

GEN = "gen_mesh.py"
N_LAYERS = 3
LAYER_FIRST_REL = 0.2        # first ground layer = 0.2 * (level-4 cell) = 0.40 m on the fine mesh
LAYER_EXP = 1.2


def solve_ratio(L: float, n: int, d0: float) -> float:
    """cell-to-cell ratio r with d0 (r^n - 1)/(r - 1) = L"""
    if abs(n * d0 - L) < 1e-9:
        return 1.0
    lo, hi = (1.0 + 1e-12, 5.0) if n * d0 < L else (0.05, 1.0 - 1e-12)
    for _ in range(300):
        r = 0.5 * (lo + hi)
        s = d0 * (r ** n - 1) / (r - 1)
        if (s < L) == (n * d0 < L):
            lo = r
        else:
            hi = r
    return 0.5 * (lo + hi)


def block_mesh(lv: dict, dom: dict) -> tuple[str, dict]:
    S, R, Ht, D0, nC = S_CORE, dom["R"], dom["Htop"], lv["D0"], lv["n_core"]
    a = R / math.sqrt(2)
    # vertical: first cell exactly D0 (so level-L cells next to the ground are D0/2^L cubes), last ~2 D0
    nz = max(3, int(round(Ht / (1.44 * D0))))
    rz = solve_ratio(Ht, nz, D0)
    Ez = rz ** (nz - 1)
    # radial (outer blocks): first cell D0 at the core square, last ~ tangential arc cell size at R
    d_out = (math.pi * R / 2) / nC
    Lr = R - S
    r_r = (Lr - D0) / (Lr - d_out)
    nR = max(3, int(round(1 + math.log(d_out / D0) / math.log(r_r))))
    rr = solve_ratio(Lr, nR, D0)
    Er = rr ** (nR - 1)
    P = [(-S, -S), (S, -S), (S, S), (-S, S), (-a, -a), (a, -a), (a, a), (-a, -a)]
    P[7] = (-a, a)
    verts = [(x, y, 0.0) for x, y in P] + [(x, y, Ht) for x, y in P]
    V = np.array(verts)
    T = 8
    blocks = [
        ((0, 1, 2, 3), (nC, nC, nz), f"(1 1 {Ez:.6g})"),                         # core
        ((4, 5, 1, 0), (nC, nR, nz), f"(1 {1/Er:.6g} {Ez:.6g})"),                  # south (x2 inward)
        ((1, 5, 6, 2), (nR, nC, nz), f"({Er:.6g} 1 {Ez:.6g})"),                    # east (x1 outward)
        ((3, 2, 6, 7), (nC, nR, nz), f"(1 {Er:.6g} {Ez:.6g})"),                    # north (x2 outward)
        ((4, 0, 3, 7), (nR, nC, nz), f"({1/Er:.6g} 1 {Ez:.6g})"),                  # west (x1 inward)
    ]
    btxt = []
    for q, n, g in blocks:
        ids = list(q) + [i + T for i in q]
        btxt.append(f"    hex ({' '.join(map(str, ids))}) ({n[0]} {n[1]} {n[2]}) simpleGrading {g}")
    edges = []
    for z, off in ((0.0, 0), (Ht, T)):
        edges += [f"    arc {4+off} {5+off} (0 {-R:.6f} {z})", f"    arc {5+off} {6+off} ({R:.6f} 0 {z})",
                  f"    arc {6+off} {7+off} (0 {R:.6f} {z})", f"    arc {7+off} {4+off} ({-R:.6f} 0 {z})"]

    def oriented(face, outward):
        f = list(face)
        p = V[f]
        n = np.cross(p[1] - p[0], p[2] - p[0]) + np.cross(p[2] - p[0], p[3] - p[0])
        if np.dot(n, outward) < 0:
            f = f[::-1]
        return "(" + " ".join(map(str, f)) + ")"

    ground_zoi = [oriented((0, 1, 2, 3), (0, 0, -1))]
    ground_outer = [oriented(q, (0, 0, -1)) for q in [(4, 5, 1, 0), (1, 5, 6, 2), (3, 2, 6, 7), (4, 0, 3, 7)]]
    top = [oriented(tuple(i + T for i in q), (0, 0, 1)) for q, _, _ in blocks]
    lat = []
    for i, j in ((4, 5), (5, 6), (6, 7), (7, 4)):
        c = (V[i] + V[j]) / 2
        lat.append(oriented((i, j, j + T, i + T), (c[0], c[1], 0)))

    def patch(name, typ, faces):
        return f"    {name}\n    {{\n        type {typ};\n        faces\n        (\n            " + \
            "\n            ".join(faces) + "\n        );\n    }"
    body = ("scale 1;\n\nvertices\n(\n" + "\n".join(f"    ({x:.6f} {y:.6f} {z:.6f})" for x, y, z in verts)
            + "\n);\n\nblocks\n(\n" + "\n".join(btxt) + "\n);\n\nedges\n(\n" + "\n".join(edges)
            + "\n);\n\nboundary\n(\n" + "\n".join([patch("ground_zoi", "wall", ground_zoi),
                                                   patch("ground_outer", "wall", ground_outer),
                                                   patch("top", "patch", top), patch("lateral", "patch", lat)])
            + "\n);\n")
    ncells = nC * nC * nz + 4 * nC * nR * nz
    info = {"nz": nz, "rz": rz, "dz_first": D0, "dz_last": D0 * Ez, "nR": nR, "rr": rr, "dr_last": D0 * Er,
            "d_tangential_at_R": d_out, "n_core": nC, "bg_cells": ncells}
    return body, info


def snappy_dict(lv: dict, dom: dict, variant: str, towers: list[dict], has_bld: bool, np_: int) -> str:
    boxes = refinement_boxes()
    geo, regs = [], []
    if has_bld:
        geo += ["    bld_zoi.stl  { type triSurfaceMesh; name bld_zoi; }",
                "    bld_ring.stl { type triSurfaceMesh; name bld_ring; }"]
    for name, b in boxes.items():
        if b.get("cylinder"):
            geo.append(f"    {name} {{ type searchableCylinder; point1 (0 0 {b['z'][0]}); point2 (0 0 {b['z'][1]:.3f}); "
                       f"radius {b['radius']}; }}")
        else:
            geo.append(f"    {name} {{ type searchableBox; min ({b['min'][0]} {b['min'][1]} {b['min'][2]}); "
                       f"max ({b['max'][0]} {b['max'][1]} {b['max'][2]:.3f}); }}")
        regs.append(f"        {name} {{ mode inside; levels ((1e15 {b['level']})); }}")
    for t in towers:
        geo.append(f"    {t['name']} {{ type searchableBox; min ({t['min'][0]:.2f} {t['min'][1]:.2f} {t['min'][2]}); "
                   f"max ({t['max'][0]:.2f} {t['max'][1]:.2f} {t['max'][2]:.2f}); }}")
        regs.append(f"        {t['name']} {{ mode inside; levels ((1e15 3)); }}")
    feats = ("        { file \"bld_zoi.eMesh\"; level 4; }\n        { file \"bld_ring.eMesh\"; level 3; }"
             if has_bld else "")
    surfs = ("        bld_zoi  { level (4 4); patchInfo { type wall; } }\n"
             "        bld_ring { level (3 3); patchInfo { type wall; } }" if has_bld else "")
    first = LAYER_FIRST_REL * lv["d4"]
    return f"""
castellatedMesh true;
snap            true;
addLayers       true;

geometry
{{
{chr(10).join(geo)}
}}

castellatedMeshControls
{{
    maxLocalCells       4000000;
    maxGlobalCells      9000000;     // RAM guard (16 GB machine): refinement stops beyond this
    minRefinementCells  10;
    maxLoadUnbalance    0.10;
    nCellsBetweenLevels 3;
    features
    (
{feats}
    );
    refinementSurfaces
    {{
{surfs}
    }}
    resolveFeatureAngle 30;
    refinementRegions
    {{
{chr(10).join(regs)}
    }}
    locationInMesh (3.137 7.291 {0.6 * dom['Htop']:.3f});
    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch    3;
    tolerance       2.0;
    nSolveIter      50;
    nRelaxIter      5;
    nFeatureSnapIter 10;
    implicitFeatureSnap false;
    explicitFeatureSnap {'true' if has_bld else 'false'};
    multiRegionFeatureSnap false;
}}

addLayersControls
{{
    relativeSizes       false;
    layers
    {{
        ground_zoi {{ nSurfaceLayers {N_LAYERS}; }}
    }}
    firstLayerThickness {first:.4f};
    expansionRatio      {LAYER_EXP};
    minThickness        {0.25 * first:.4f};
    nGrow               0;
    featureAngle        130;
    slipFeatureAngle    30;
    nRelaxIter          5;
    nSmoothSurfaceNormals 1;
    nSmoothNormals      3;
    nSmoothThickness    10;
    maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3;
    minMedialAxisAngle  90;
    nBufferCellsNoExtrude 0;
    nLayerIter          12;
    nRelaxedIter        6;
}}

meshQualityControls
{{
    #includeEtc "caseDicts/meshQualityDict"
    nSmoothScale    4;
    errorReduction  0.75;
    relaxed
    {{
        maxNonOrtho 75;
    }}
}}

writeFlags ( layerFields );
mergeTolerance 1e-6;
"""


CONTROL = """
application     snappyHexMesh;
startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         0;
deltaT          1;
writeControl    timeStep;
writeInterval   1;
purgeWrite      0;
writeFormat     {fmt};
writePrecision  10;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable false;
"""

SCHEMES = """
ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes { default none; }
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
wallDist { method meshWave; }
"""
SOLUTION = """
solvers {}
"""

ALLRUN = r"""#!/bin/bash
# Zona Tec mesh case {name}. Generated by v2/cfd/zonatec/scripts/gen_mesh.py (OpenFOAM v2306 ESI MinGW).
# Resumable (E:/PINN/cola/README.md): step markers .<step>.ok; snappy restarts from the pristine background mesh.
set -eo pipefail
cd "${{0%/*}}"
NP={np}
PY={py}
SC={sc}
rm -f DONE FAILED
trap 'echo "FAILED: line $LINENO" > FAILED' ERR
step() {{ echo; echo "=== $1  $(date '+%F %T')"; }}
run() {{ local log=$1; shift; echo "Running $*  -> $log"; "$@" 2>&1 | tee "$log"; ! grep -q "FOAM FATAL" "$log"; }}
setfmt() {{ foamDictionary -entry writeFormat -set $1 system/controlDict > /dev/null; }}
t0=$(date +%s)

step "blockMesh (O-grid background)"
if [ ! -f .blockMesh.ok ]; then
    rm -rf constant/polyMesh processor* .patches.ok .decompose.ok .snappy.ok .reconstruct.ok .check.ok .stats.ok
    setfmt ascii
    run log.blockMesh blockMesh
    touch .blockMesh.ok
fi

step "lateral boundary -> {nseg} segments"
if [ ! -f .patches.ok ]; then
    setfmt ascii
    $PY $SC/split_lateral.py . 2>&1 | tee log.split_lateral
    run log.createPatch createPatch -overwrite
    rm -rf constant/polyMesh/sets
    run log.checkMesh.bg checkMesh
    touch .patches.ok
fi
setfmt binary

step "surfaceFeatureExtract"
if [ ! -f .features.ok ]; then
    if [ -f constant/triSurface/bld_zoi.stl ]; then run log.surfaceFeatureExtract surfaceFeatureExtract; fi
    touch .features.ok
fi

step "snappyHexMesh (parallel $NP, RAM monitored)"
if [ ! -f .snappy.ok ]; then
    # always restart from the pristine background mesh in constant/polyMesh (snappy writes only processor*)
    run log.decomposePar decomposePar -force
    rm -f .memstop mem_snappy.csv mem_snappy_peak.txt
    /c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -ExecutionPolicy Bypass \
        -File "E:/PINN/v2/cfd/zonatec/scripts/memwatch.ps1" -Dir "$(pwd -W)" -Names snappyHexMesh \
        -MinAvailMB {minavail} > log.memwatch 2>&1 &
    MW=$!
    ts=$(date +%s)
    set +e
    mpiexec -n $NP snappyHexMesh -parallel -overwrite 2>&1 | tee log.snappyHexMesh
    rc=${{PIPESTATUS[0]}}
    set -e
    touch .memstop; wait $MW || true
    te=$(date +%s)
    echo "snappy_wall_s $((te-ts))" | tee -a timing.txt
    cat mem_snappy_peak.txt 2>/dev/null | tee -a timing.txt || true
    if [ -f mem_guard_tripped.txt ]; then echo "RAM guard tripped"; cat mem_guard_tripped.txt; exit 3; fi
    [ "$rc" = 0 ] || exit $rc
    ! grep -q "FOAM FATAL" log.snappyHexMesh
    grep -q "Finished meshing" log.snappyHexMesh
    touch .snappy.ok
fi

step "reconstructParMesh"
if [ ! -f .reconstruct.ok ]; then
    run log.reconstructParMesh reconstructParMesh -constant -mergeTol 1e-6
    touch .reconstruct.ok
fi

step "checkMesh + wall distance + cell volumes + cell centres"
if [ ! -f .check.ok ]; then
    rm -rf 0; mkdir -p 0
    run log.checkMesh checkMesh -time 0 -writeFields '(wallDistance cellVolume nonOrthoAngle skewness)'
    run log.writeCellCentres postProcess -func writeCellCentres -time 0
    touch .check.ok
fi

step "mesh statistics (cells below 1.75 m, layer coverage, RAM)"
if [ ! -f .stats.ok ]; then
    $PY $SC/mesh_stats.py . 2>&1 | tee log.mesh_stats
    touch .stats.ok
fi
rm -rf processor*
t1=$(date +%s)
echo "wallclock_s_last_attempt $((t1-t0))" >> timing.txt
echo "OK $(date)" > DONE
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="base", choices=B.VARIANTS)
    ap.add_argument("--level", default="fine")
    ap.add_argument("--scenario", default="H_best")
    ap.add_argument("--np", type=int, default=6)
    ap.add_argument("--min-avail-mb", type=int, default=1500, help="RAM guard: kill snappy if free RAM drops below")
    ap.add_argument("--out", default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    lv = level_info(a.level)
    dom = domain(a.scenario)
    case = Path(a.out) if a.out else RUNS / f"mesh_{a.variant}_{a.level}"
    if case.exists() and any(case.iterdir()):
        if not a.force:
            raise SystemExit(f"{case} exists (use --force to regenerate its dictionaries; markers are kept)")
    has_bld = a.variant != "empty"
    towers = B.towers("base" if a.variant == "empty" else a.variant, a.scenario)   # empty: same refinement as base
    bm, binfo = block_mesh(lv, dom)
    foam(case / "system" / "blockMeshDict", "dictionary", "blockMeshDict", bm, GEN)
    foam(case / "system" / "controlDict", "dictionary", "controlDict", CONTROL.format(fmt="ascii"), GEN)
    foam(case / "system" / "fvSchemes", "dictionary", "fvSchemes", SCHEMES, GEN)
    foam(case / "system" / "fvSolution", "dictionary", "fvSolution", SOLUTION, GEN)
    foam(case / "system" / "decomposeParDict", "dictionary", "decomposeParDict",
         f"numberOfSubdomains {a.np};\nmethod scotch;\n", GEN)
    foam(case / "system" / "snappyHexMeshDict", "dictionary", "snappyHexMeshDict",
         snappy_dict(lv, dom, a.variant, towers, has_bld, a.np), GEN)
    from zt_common import N_SEG
    pats = "\n".join(f"    {{ name seg{k:02d}; patchInfo {{ type patch; inGroups (lateral); }} constructFrom set; set seg{k:02d}; }}"
                     for k in range(N_SEG))
    foam(case / "system" / "createPatchDict", "dictionary", "createPatchDict",
         f"pointSync false;\npatches\n(\n{pats}\n);\n", GEN)
    stl = {}
    if has_bld:
        (case / "constant" / "triSurface").mkdir(parents=True, exist_ok=True)
        stl = B.write_snappy_stls(a.variant, case / "constant" / "triSurface", a.scenario)
        foam(case / "system" / "surfaceFeatureExtractDict", "dictionary", "surfaceFeatureExtractDict", """
bld_zoi.stl  { extractionMethod extractFromSurface; includedAngle 150; subsetFeatures { nonManifoldEdges no; openEdges yes; } writeObj no; }
bld_ring.stl { extractionMethod extractFromSurface; includedAngle 150; subsetFeatures { nonManifoldEdges no; openEdges yes; } writeObj no; }
""", GEN)
    write_text(case / "Allrun", ALLRUN.format(name=case.name, np=a.np, py=PY_UNIX, sc=SCRIPTS_UNIX,
                                              nseg=N_SEG, minavail=a.min_avail_mb))
    meta = {"case": case.name, "kind": "mesh", "variant": a.variant, "scenario": a.scenario, "level": lv,
            "domain": dom, "background": binfo, "refinement_boxes": refinement_boxes(a.scenario),
            "towers": towers, "stl": stl, "layers": {"n": N_LAYERS, "first": LAYER_FIRST_REL * lv["d4"],
                                                      "expansion": LAYER_EXP, "patch": "ground_zoi"},
            "np": a.np, "core_half": S_CORE}
    dump_json(case / "mesh.json", meta)
    print(f"mesh case written: {case}\n  D0={lv['D0']:.2f} m, level-4={lv['d4']:.3f} m, background cells={binfo['bg_cells']}"
          f" (nz={binfo['nz']}, dz_last={binfo['dz_last']:.1f} m, nR={binfo['nR']}, dr_last={binfo['dr_last']:.1f} m)")


if __name__ == "__main__":
    main()
