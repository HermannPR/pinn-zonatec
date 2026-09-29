"""Generate a Zona Tec DIRECTION case (theta, U10, turbulence model) on an existing (or queued) mesh case.

  python gen_case.py --mesh E:/PINN/runs/zonatec/mesh_base_fine --theta 112.5 --U10 5 --model realizableKE
  python gen_case.py --mesh ... --theta 135 --U10 5 --warm-from E:/PINN/runs/zonatec/zt_base_th1125_U050_m1
  python gen_case.py --mesh .../mesh_empty_fine --theta 112.5 --U10 5 --z0-zoi fetch --tag hom   (homogeneity test)

The mesh is identical for every direction; only the boundary-condition TYPES of the 32 lateral segments change
(inlet = atmBoundaryLayerInlet*, outlet = p 0 / inletOutlet) with the sign of U.n (zt_common.segment_roles).
Allrun steps (resumable): copy mesh -> init (log-law via setExprFields, or warm start = previous direction's
converged fields with U rotated in place) -> decomposePar -> stage 1 (first order) -> stage 2 (second order) in
chunks until convcheck.py says converged (review C7) or max iterations -> reconstructPar -> HDF5 extraction -> clean.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

import buildings as B
from zt_common import (CMU, KAPPA, N_SEG, PY_UNIX, RUNS, SCRIPTS_UNIX, Z0_ZOI_DEFAULT, case_id, domain,
                       dump_json, flow_dir, foam, inflow, segment_roles, to_unix, write_text)

GEN = "gen_case.py"
MODELS = {"realizableKE": "epsilon", "kEpsilon": "epsilon", "kOmegaSST": "omega"}


def tv(model):
    return MODELS[model]


# ------------------------------------------------------------------------------------------------ probes
CANDIDATE_PROBES = [  # z = 1.75 m; corners of the tall buildings (+4 m diagonal), streets and open areas
    (-239.6, 114.0), (-185.6, 175.4), (-201.6, -9.0), (-169.2, 40.5), (-58.5, -341.8), (117.4, -324.5),
    (0.0, 0.0), (100.0, 100.0), (-100.0, -150.0), (250.0, -50.0), (-300.0, 300.0), (300.0, 300.0),
    (-185.6, 114.0), (-239.6, 175.4), (-169.2, -9.0), (-201.6, 40.5), (150.0, -200.0), (-50.0, 250.0),
    (0.0, -100.0), (200.0, 0.0), (-200.0, -250.0), (50.0, -250.0), (-350.0, -50.0), (-120.0, 60.0), (180.0, 180.0),
]


def probe_points(variant: str) -> list[tuple]:
    geo_var = "base" if variant == "empty" else variant
    c = np.array([(x, y, 1.75) for x, y in CANDIDATE_PROBES])
    d = B.exact_sdf(c, geo_var)
    ok = [tuple(p) for p, s in zip(c, d) if s > 3.0][:10]
    return ok + [(0.0, 0.0, 20.0), (0.0, 0.0, 87.75)]


def profile_stations(theta: float, R: float) -> dict:
    """vertical sampling lines along the wind axis, named by upwind distance from the centre (m)"""
    e = flow_dir(theta)
    out = {}
    for name, s in (("inlet", R - 20.0), ("up1500", 1500.0), ("up771", 771.0), ("up545", 545.0),
                    ("centre", 0.0), ("dn771", -771.0), ("dn1500", -1500.0)):
        x, y = -s * e[0], -s * e[1]
        out[name] = (x, y)
    return out


# ------------------------------------------------------------------------------------------------ fields
def fields(inf, model: str, roles: list[str], z0_zoi: float, has_bld: bool, H_ref: float) -> dict:
    e = flow_dir(inf.theta_deg)
    ex, ey = e[0], e[1]
    Uref = float(inf.U(H_ref))
    k0 = inf.k
    abl = (f"flowDir         ({ex:.8f} {ey:.8f} 0);\n        zDir            (0 0 1);\n"
           f"        Uref            {Uref:.8g};\n        Zref            {H_ref:.6g};\n"
           f"        z0              uniform {inf.z0:.8g};\n        d               uniform 0;\n"
           f"        kappa           {KAPPA};\n        Cmu             {CMU};")
    tau = inf.u_star ** 2
    T = tv(model)
    ABLT = {"U": "atmBoundaryLayerInletVelocity", "k": "atmBoundaryLayerInletK",
            "epsilon": "atmBoundaryLayerInletEpsilon", "omega": "atmBoundaryLayerInletOmega"}
    eps_ref, om_ref = float(inf.eps(H_ref)), float(inf.omega(H_ref))
    zero = {"U": "uniform (0 0 0)", "p": "uniform 0", "k": f"uniform {k0:.8g}", "epsilon": f"uniform {eps_ref:.8g}",
            "omega": f"uniform {om_ref:.8g}", "nut": "uniform 0"}

    def seg_bc(q, role):
        if role == "inlet":
            if q == "p":
                return "type zeroGradient;"
            if q == "nut":
                return "type calculated; value uniform 0;"
            return f"type {ABLT[q]};\n        {abl}\n        value {zero[q]};"
        if q == "p":
            return "type fixedValue; value uniform 0;"
        if q == "nut":
            return "type calculated; value uniform 0;"
        if q == "U":
            return "type inletOutlet; inletValue uniform (0 0 0); value uniform (0 0 0);"
        return f"type inletOutlet; inletValue {zero[q]}; value {zero[q]};"

    def ground(q, z0):
        if q == "U":
            return "type noSlip;"
        if q == "p":
            return "type zeroGradient;"
        if q == "k":
            return f"type kqRWallFunction; value {zero['k']};"
        if q == "epsilon":
            return f"type atmEpsilonWallFunction; z0 uniform {z0:.8g}; value {zero['epsilon']};"
        if q == "omega":
            return f"type atmOmegaWallFunction; z0 uniform {z0:.8g}; value {zero['omega']};"
        return f"type atmNutkWallFunction; kappa {KAPPA}; Cmu {CMU}; z0 uniform {z0:.8g}; value uniform 0;"

    def bwall(q):
        return {"U": "type noSlip;", "p": "type zeroGradient;", "k": f"type kqRWallFunction; value {zero['k']};",
                "epsilon": f"type epsilonWallFunction; value {zero['epsilon']};",
                "omega": f"type omegaWallFunction; value {zero['omega']};",
                "nut": "type nutkWallFunction; value uniform 0;"}[q]

    def top(q):
        if q == "U":
            return f"type fixedShearStress; tau ({tau * ex:.8g} {tau * ey:.8g} 0); value uniform (0 0 0);"
        if q == "nut":
            return "type calculated; value uniform 0;"
        return "type zeroGradient;"

    out = {}
    meta = {"U": ("volVectorField", "[0 1 -1 0 0 0 0]", "uniform (0 0 0)"),
            "p": ("volScalarField", "[0 2 -2 0 0 0 0]", "uniform 0"),
            "k": ("volScalarField", "[0 2 -2 0 0 0 0]", zero["k"]),
            "epsilon": ("volScalarField", "[0 2 -3 0 0 0 0]", zero["epsilon"]),
            "omega": ("volScalarField", "[0 0 -1 0 0 0 0]", zero["omega"]),
            "nut": ("volScalarField", "[0 2 -1 0 0 0 0]", "uniform 0")}
    for q in ["U", "p", "k", T, "nut"]:
        cls, dims, init = meta[q]
        lines = [f"    ground_zoi\n    {{\n        {ground(q, z0_zoi)}\n    }}",
                 f"    ground_outer\n    {{\n        {ground(q, inf.z0)}\n    }}",
                 f"    top\n    {{\n        {top(q)}\n    }}"]
        for k, role in enumerate(roles):
            lines.append(f"    seg{k:02d}  // {role}\n    {{\n        {seg_bc(q, role)}\n    }}")
        if has_bld:
            lines.append(f"    \"bld_.*\"\n    {{\n        {bwall(q)}\n    }}")
        body = f"dimensions      {dims};\ninternalField   {init};\nboundaryField\n{{\n" + "\n".join(lines) + "\n}\n"
        out[q] = (cls, body)
    return out


def set_expr_dict(inf, model: str) -> str:
    """cold start: horizontally homogeneous Richards & Hoxey solution everywhere (d = 0)"""
    e = flow_dir(inf.theta_deg)
    us, z0 = inf.u_star, inf.z0
    lines = [f"""    U
    {{
        field       U;
        dimensions  [0 1 -1 0 0 0 0];
        expression  #{{ vector({e[0]:.8f}, {e[1]:.8f}, 0) * {us / KAPPA:.8g} * log((max(pos().z(), 0) + {z0:.8g})/{z0:.8g}) #}};
    }}""", f"""    k
    {{
        field       k;
        dimensions  [0 2 -2 0 0 0 0];
        expression  #{{ {inf.k:.8g} #}};
    }}"""]
    if tv(model) == "epsilon":
        lines.append(f"""    epsilon
    {{
        field       epsilon;
        dimensions  [0 2 -3 0 0 0 0];
        expression  #{{ {us ** 3 / KAPPA:.8g} / (max(pos().z(), 0) + {z0:.8g}) #}};
    }}""")
    else:
        lines.append(f"""    omega
    {{
        field       omega;
        dimensions  [0 0 -1 0 0 0 0];
        expression  #{{ {us / (KAPPA * math.sqrt(CMU)):.8g} / (max(pos().z(), 0) + {z0:.8g}) #}};
    }}""")
    return "expressions\n(\n" + "\n".join(lines) + "\n);\n"


# ------------------------------------------------------------------------------------------------ system
def schemes(order: int, model: str) -> str:
    T = tv(model)
    if order == 1:
        dU, dT = "bounded Gauss upwind", "bounded Gauss upwind"
    else:
        dU, dT = "bounded Gauss linearUpwind grad(U)", "bounded Gauss limitedLinear 1"
    return f"""
ddtSchemes {{ default steadyState; }}
gradSchemes
{{
    default         Gauss linear;
    grad(U)         cellLimited Gauss linear 1;
    grad(k)         cellLimited Gauss linear 1;
    grad({T})       cellLimited Gauss linear 1;
}}
divSchemes
{{
    default         none;
    div(phi,U)      {dU};
    div(phi,k)      {dT};
    div(phi,{T})    {dT};
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}
laplacianSchemes {{ default Gauss linear limited corrected 0.33; }}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default limited corrected 0.33; }}
wallDist {{ method meshWave; }}
"""


def fv_solution(model: str, stage: int, relax: dict) -> str:
    T = tv(model)
    if stage == 1:
        simple, rel = "consistent no;", f"fields {{ p 0.3; }}\n    equations {{ U 0.7; \"(k|epsilon|omega)\" 0.7; }}"
    else:
        simple = "consistent yes;"
        rel = (f"fields {{ p {relax['p']}; }}\n    equations {{ U {relax['U']}; \"(k|epsilon|omega)\" {relax['turb']}; }}")
    return f"""
solvers
{{
    p
    {{
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-7;
        relTol          0.05;
    }}
    "(U|k|epsilon|omega)"
    {{
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-8;
        relTol          0.1;
    }}
}}
SIMPLE
{{
    nNonOrthogonalCorrectors 0;
    {simple}
    residualControl
    {{
        p               1e-5;
        U               1e-5;
        "(k|{T})"       1e-5;
    }}
}}
relaxationFactors
{{
    {rel}
}}
cache {{ grad(U); }}
"""


def control_dict(model: str, probes, stations, Htop: float, write: int, has_bld: bool) -> str:
    T = tv(model)
    pr = "\n".join(f"            ({x:.3f} {y:.3f} {z:.3f})" for x, y, z in probes)
    st = "\n".join(f"            {n} {{ type uniform; axis z; start ({x:.3f} {y:.3f} 0.1); end ({x:.3f} {y:.3f} {Htop - 1:.2f}); nPoints 600; }}"
                   for n, (x, y) in stations.items())
    mass = "\n".join(
        f"    flux_{pn}\n    {{\n        type surfaceFieldValue; libs (fieldFunctionObjects); writeControl timeStep; "
        f"writeInterval 20; log false; writeFields false; regionType patch; name {pn}; operation sum; fields (phi);\n    }}"
        for pn in [f"seg{k:02d}" for k in range(N_SEG)] + ["top"])
    yplus = """
    yPlus
    {
        type            yPlus;
        libs            (fieldFunctionObjects);
        writeControl    writeTime;
    }""" if has_bld else ""
    return f"""
application     simpleFoam;
libs            (atmosphericModels);
startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         300;
deltaT          1;
writeControl    timeStep;
writeInterval   {write};
purgeWrite      2;
writeFormat     binary;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable true;

functions
{{
    residuals
    {{
        type            solverInfo;
        libs            (utilityFunctionObjects);
        fields          (U p k {T});
        writeResidualFields no;
    }}
    monitors
    {{
        type            probes;
        libs            (sampling);
        fields          (U k p);
        probeLocations
        (
{pr}
        );
    }}
{mass}
    profiles
    {{
        type            sets;
        libs            (sampling);
        writeControl    writeTime;
        interpolationScheme cell;
        setFormat       csv;
        fields          (U k nut {T} p);
        sets
        {{
{st}
        }}
    }}{yplus}
}}
"""


ALLRUN = r"""#!/bin/bash
# Zona Tec direction case {name}. Generated by v2/cfd/zonatec/scripts/gen_case.py (OpenFOAM v2306 ESI MinGW).
# Resumable (E:/PINN/cola/README.md): step markers, startFrom latestTime, writeInterval {write}, purgeWrite 2,
# incomplete latest times removed on restart, all output to stdout, non-zero exit on failure.
set -eo pipefail
cd "${{0%/*}}"
NP={np}
PY={py}
SC={sc}
MESH="{mesh}"
WARM="{warm}"
STAGE1={stage1}
ENDT={endt}
CHUNK={chunk}
TV={tv}
rm -f DONE FAILED
trap 'echo "FAILED: line $LINENO" > FAILED' ERR
step() {{ echo; echo "=== $1  $(date '+%F %T')"; }}
run() {{ local log=$1; shift; echo "Running $*  -> $log"; "$@" 2>&1 | tee "$log"; ! grep -q "FOAM FATAL" "$log"; }}
runa() {{ local log=$1; shift; echo "Running $*  -> $log (append)"; "$@" 2>&1 | tee -a "$log"; ! grep -q "FOAM FATAL" "$log"; }}
latest() {{ local r=processor0; [ -d $r ] || r=.; ls -1 "$r" 2>/dev/null | grep -E '^[0-9.e+-]+$' | sort -g | tail -1; }}
clean_latest() {{
    local roots; roots=$(ls -d processor* 2>/dev/null || true)
    [ -z "$roots" ] && return 0
    local bad=0 last
    last=$(latest)
    [ -z "$last" ] || [ "$last" = 0 ] && return 0
    for r in $roots; do for f in U p k nut $TV; do [ -s "$r/$last/$f" ] || bad=1; done; done
    if [ "$bad" = 1 ]; then echo "latest time $last incomplete (power cut?) -> removing it"; for r in $roots; do rm -rf "$r/$last"; done; fi
}}
solve() {{
    local tag=$1
    echo "--- simpleFoam $tag from $(latest) to $(foamDictionary -entry endTime -value system/controlDict)"
    runa "log.simpleFoam.$tag" mpiexec -n $NP simpleFoam -parallel
    grep -qi "nan" <(grep -E "^(Time|smoothSolver|GAMG|DIC|time step continuity)" "log.simpleFoam.$tag" | tail -200) && {{ echo "NaN detected"; exit 4; }} || true
}}
t0=$(date +%s)

step "mesh (copy from $MESH)"
if [ ! -f .mesh.ok ]; then
    [ -f "$MESH/.reconstruct.ok" ] || {{ echo "mesh case not ready: $MESH"; exit 2; }}
    rm -rf constant/polyMesh; mkdir -p constant
    cp -r "$MESH/constant/polyMesh" constant/
    touch .mesh.ok
fi

step "initial fields"
if [ ! -f .init.ok ]; then
    rm -rf 0 processor* .decompose.ok .stage1.ok .stage2.ok postProcessing
    cp -r 0.orig 0
    if [ -n "$WARM" ]; then
        $PY $SC/warmstart.py "$WARM" . 2>&1 | tee log.warmstart
    else
        run log.setExprFields setExprFields -time 0
    fi
    touch .init.ok
fi

step "decomposePar"
if [ ! -f .decompose.ok ]; then
    run log.decomposePar decomposePar -force
    touch .decompose.ok
fi

step "stage 1: first-order start ($STAGE1 it)"
clean_latest
if [ ! -f .stage1.ok ]; then
    if [ "$STAGE1" -gt 0 ]; then
        cp -f system/fvSchemes.stage1 system/fvSchemes; cp -f system/fvSolution.stage1 system/fvSolution
        foamDictionary -entry endTime -set $STAGE1 system/controlDict > /dev/null
        [ "$(latest)" -ge "$STAGE1" ] 2>/dev/null || solve stage1
    fi
    touch .stage1.ok
fi

step "stage 2: second order, chunks of $CHUNK until converged (convcheck.py) or $ENDT it"
cp -f system/fvSchemes.stage2 system/fvSchemes; cp -f system/fvSolution.stage2 system/fvSolution
if [ ! -f .stage2.ok ]; then
    while true; do
        clean_latest
        it=$(latest)
        if [ "$it" -ge $((STAGE1 + 500)) ] && $PY $SC/convcheck.py . --quiet; then echo "converged at $it"; break; fi
        if [ "$it" -ge "$ENDT" ]; then echo "reached ENDT=$ENDT without meeting the criterion (verify will decide)"; break; fi
        nxt=$((it + CHUNK)); [ "$nxt" -gt "$ENDT" ] && nxt=$ENDT
        foamDictionary -entry endTime -set $nxt system/controlDict > /dev/null
        solve stage2
        # residualControl may stop the run early: then it is converged by residuals
        if grep -q "SIMPLE solution converged" log.simpleFoam.stage2 2>/dev/null && [ "$(latest)" -lt "$nxt" ]; then echo "residualControl reached"; break; fi
    done
    $PY $SC/convcheck.py . | tee convergence.txt || true
    touch .stage2.ok
fi

step "reconstructPar (latest time)"
if [ ! -f .reconstruct.ok ]; then
    run log.reconstructPar reconstructPar -latestTime
    touch .reconstruct.ok
fi

step "extraction to HDF5 (data contract)"
if [ ! -f .extract.ok ]; then
    {extract_cmd}
    touch .extract.ok
fi

step "timing + cleanup"
$PY $SC/timing.py . 2>&1 | tee -a timing.txt || true
rm -rf processor*
t1=$(date +%s)
echo "wallclock_s_last_attempt $((t1-t0))" >> timing.txt
echo "OK $(date)" > DONE
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", required=True, help="mesh case directory (gen_mesh.py)")
    ap.add_argument("--theta", type=float, required=True)
    ap.add_argument("--U10", type=float, default=5.0)
    ap.add_argument("--model", default="realizableKE", choices=list(MODELS))
    ap.add_argument("--sigma-eps", type=float, default=None,
                    help="kEpsilon sigmaEps; default 1.167 (= kappa^2/((C2-C1) sqrt(Cmu)), RH-consistent, kappa 0.41)")
    ap.add_argument("--z0-method", default="macdonald")
    ap.add_argument("--z0-fetch", type=float, default=None, help="override inlet/ground_outer z0 (sensitivity G2)")
    ap.add_argument("--z0-zoi", default=str(Z0_ZOI_DEFAULT), help="ground_zoi z0 [m] or 'fetch' (= inlet z0)")
    ap.add_argument("--warm-from", default="", help="converged case to warm-start from (U rotated in place)")
    ap.add_argument("--stage1", type=int, default=None, help="first-order iterations (default 300 cold / 0 warm)")
    ap.add_argument("--end", type=int, default=4000)
    ap.add_argument("--chunk", type=int, default=500)
    ap.add_argument("--write", type=int, default=200)
    ap.add_argument("--relax", default="p=1,U=0.6,turb=0.6", help="stage-2 SIMPLEC relaxation")
    ap.add_argument("--np", type=int, default=6)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-extract", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    mesh = Path(a.mesh)
    mmeta = json.loads((mesh / "mesh.json").read_text())
    variant, level, sc = mmeta["variant"], mmeta["level"]["level"], mmeta["scenario"]
    dom = domain(sc)
    has_bld = variant != "empty"
    inf = inflow(a.theta, a.U10, a.z0_method, a.z0_fetch)
    z0_zoi = inf.z0 if a.z0_zoi == "fetch" else float(a.z0_zoi)
    cid = case_id(variant, a.theta, a.U10, level, a.model, a.tag)
    case = Path(a.out) if a.out else RUNS / cid
    if case.exists() and any(case.iterdir()):
        raise SystemExit(f"{case} exists and is not empty")
    roles = segment_roles(a.theta)
    T = tv(a.model)
    relax = dict(kv.split("=") for kv in a.relax.split(","))
    stage1 = a.stage1 if a.stage1 is not None else (0 if a.warm_from else 300)

    for q, (cls, body) in fields(inf, a.model, roles, z0_zoi, has_bld, dom["H_ref"]).items():
        foam(case / "0.orig" / q, cls, q, body, GEN)
    probes = probe_points(variant)
    stations = profile_stations(a.theta, dom["R"])
    foam(case / "system" / "controlDict", "dictionary", "controlDict",
         control_dict(a.model, probes, stations, dom["Htop"], a.write, has_bld), GEN)
    for s in (1, 2):
        foam(case / "system" / f"fvSchemes.stage{s}", "dictionary", "fvSchemes", schemes(s, a.model), GEN)
        foam(case / "system" / f"fvSolution.stage{s}", "dictionary", "fvSolution", fv_solution(a.model, s, relax), GEN)
    foam(case / "system" / "fvSchemes", "dictionary", "fvSchemes", schemes(1, a.model), GEN)
    foam(case / "system" / "fvSolution", "dictionary", "fvSolution", fv_solution(a.model, 1, relax), GEN)
    foam(case / "system" / "decomposeParDict", "dictionary", "decomposeParDict",
         f"numberOfSubdomains {a.np};\nmethod scotch;\n", GEN)
    foam(case / "system" / "setExprFieldsDict", "dictionary", "setExprFieldsDict", set_expr_dict(inf, a.model), GEN)
    foam(case / "constant" / "transportProperties", "dictionary", "transportProperties",
         "transportModel  Newtonian;\nnu              1.5e-05;\n", GEN)
    coeffs = ""
    sig = a.sigma_eps if a.sigma_eps else (1.167 if a.model == "kEpsilon" else None)
    if a.model == "kEpsilon":
        coeffs = f"    kEpsilonCoeffs\n    {{\n        Cmu 0.09;\n        C1 1.44;\n        C2 1.92;\n        C3 0;\n        sigmak 1.0;\n        sigmaEps {sig};\n    }}\n"
    elif a.model == "realizableKE" and a.sigma_eps:
        coeffs = f"    realizableKECoeffs\n    {{\n        sigmaEps {a.sigma_eps};\n    }}\n"
    foam(case / "constant" / "turbulenceProperties", "dictionary", "turbulenceProperties",
         f"simulationType RAS;\nRAS\n{{\n    RASModel        {a.model};\n    turbulence      on;\n    printCoeffs     on;\n{coeffs}}}\n", GEN)
    extract = ("echo 'extraction disabled for this case'" if (a.no_extract or not has_bld)
               else f"$PY $SC/extract_h5.py . 2>&1 | tee log.extract")
    write_text(case / "Allrun", ALLRUN.format(name=case.name, np=a.np, py=PY_UNIX, sc=SCRIPTS_UNIX,
                                              mesh=to_unix(mesh), warm=to_unix(a.warm_from) if a.warm_from else "",
                                              stage1=stage1, endt=a.end, chunk=a.chunk, tv=T, write=a.write,
                                              extract_cmd=extract))
    meta = {"case_id": cid, "case": str(case), "mesh_case": str(mesh), "variant": variant, "level": level,
            "scenario": sc, "theta_deg": a.theta, "U10": a.U10, "model": a.model, "sigma_eps": sig,
            "inflow": inf, "U_H": float(inf.U(dom["H_ref"])), "H_ref": dom["H_ref"], "z0_ground_zoi": z0_zoi,
            "z0_fetch": inf.z0, "segments": {f"seg{k:02d}": r for k, r in enumerate(roles)},
            "n_inlet_segments": roles.count("inlet"), "probes": probes, "stations": stations,
            "warm_from": a.warm_from, "stage1": stage1, "end": a.end, "chunk": a.chunk, "relax_stage2": relax,
            "np": a.np, "domain": dom, "has_buildings": has_bld}
    dump_json(case / "case.json", meta)
    print(f"case written: {case}\n  u*={inf.u_star:.4f} m/s z0={inf.z0:.4f} m T={inf.T:.4f} U_H={meta['U_H']:.3f} m/s "
          f"inlet segments {roles.count('inlet')}/{N_SEG}, probes {len(probes)}")


if __name__ == "__main__":
    main()
