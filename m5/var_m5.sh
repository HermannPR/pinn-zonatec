#!/bin/bash
# Variante de geometria x 8 direcciones en la M5 (PLAN F3 prioridad 2; equivale a var_campaign.py de cln).
#
#   m5/var_m5.sh <malla> <primer_num_cola>      ej. m5/var_m5.sh .../mesh_var2_fine 04
#
# Corre como trabajo de la cola de noche.sh, despues de que la malla quede DONE. Genera los 8 casos en
# cadena caliente sobre la misma malla (el primero frio en 90 grados, cada uno arranca del anterior),
# los adapta a la M5 (mpiexec --oversubscribe) y los pone en la cola como <NN>_<caso>.
set -euo pipefail
MALLA=${1:?malla}; N0=$((10#${2:?primer numero}))
F=$HOME/dev/pinn-zonatec/f3
export ZT_V2=$F/paquete/pinn/v2 ZT_RUNS=$F/paquete/pinn/runs/zonatec ZT_PY=$F/.venv/bin/python
export ZT_SC=$ZT_V2/cfd/zonatec/scripts
COLA=$F/cola
[ -f "$MALLA/DONE" ] || { echo "malla sin DONE: $MALLA"; exit 1; }
prev=""; k=0
for th in 90 135 180 225 270 315 0 45; do
  cid=$("$ZT_PY" - "$MALLA" "$th" <<'PY'
import json, sys
sys.path.insert(0, __import__("os").environ["ZT_SC"])
from zt_common import case_id
m = json.load(open(sys.argv[1] + "/mesh.json"))
print(case_id(m["variant"], float(sys.argv[2]), 5.0, m["level"]["level"], "realizableKE"))
PY
)
  caso=$ZT_RUNS/$cid
  if [ ! -f "$caso/Allrun" ]; then
    args=(--mesh "$MALLA" --theta "$th" --U10 5 --model realizableKE --chunk 100
          --relax "p=0.3,U=0.6,turb=0.5,simplec=no,nonorth=1")
    [ -n "$prev" ] && args+=(--warm-from "$prev")
    ( cd "$ZT_SC" && "$ZT_PY" gen_case.py "${args[@]}" )
    sed -i '' 's/mpiexec -n /mpiexec --oversubscribe -n /' "$caso/Allrun"
    # parches M5 (17 oct): bug //sers de gen_case, salida local y rutas ZT_*
    sed -i '' -e 's|"//sers/|"/Users/|g' -e 's|extract_h5.py \. 2>&1|extract_h5.py . --out-dir h5_m5 2>\&1|' "$caso/Allrun"
    grep -q "^export ZT_V2" "$caso/Allrun" || perl -pi -e '$_ .= "export ZT_V2=$ENV{ZT_V2} ZT_RUNS=$ENV{ZT_RUNS} ZT_PY=$ENV{ZT_PY} ZT_SC=$ENV{ZT_SC}\n" if /^PY=/' "$caso/Allrun"
    chmod +x "$caso/Allrun"
  fi
  ln -sfn "$caso" "$COLA/$(printf %02d $((N0+k)))_$cid"
  echo "$(printf %02d $((N0+k))) theta $th ${prev:+caliente desde $(basename "$prev")} -> $cid"
  prev=$caso; k=$((k+1))
done
