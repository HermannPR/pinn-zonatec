#!/bin/bash
# Rescate en caliente de un caso de la cola que fallo o divergio (orden de Hermann, 17 oct: "si siempre
# relanzar casos sin mi ok"). Lo llama noche.sh una vez por caso (RESCATE en <cola>/.noche.env).
#
#   m5/rescate_caso.sh <cola>/<NN_caso>
#
# - Fuente: el WARM del Allrun si ya quedo DONE; si no (el anterior tambien fallo), el ultimo caso de la
#   cola con DONE sobre la misma malla; si no hay ninguno, en frio con 300 it de primer orden.
# - Guarda el caso fallido como <caso>.fallo-<fecha> (no borra nada) y lo regenera con gen_case.py:
#   200 it de primer orden y relajacion baja (receta del 160 de var1 y del 04 de var2), mas los parches M5.
set -euo pipefail
Q=${1:?caso de la cola}
COLA=$(cd "$(dirname "$Q")" && pwd); NOMBRE=$(basename "$Q")
[ -L "$Q" ] || { echo "$Q no es symlink a runs/; no lo toco"; exit 2; }
CASO=$(cd -P "$Q" && pwd)
F=$HOME/dev/pinn-zonatec/f3
export ZT_V2=${ZT_V2:-$F/paquete/pinn/v2} ZT_RUNS=${ZT_RUNS:-$F/paquete/pinn/runs/zonatec} ZT_PY=${ZT_PY:-$F/.venv/bin/python}
export ZT_SC=${ZT_SC:-$ZT_V2/cfd/zonatec/scripts}
HOY=$(date +%Y%m%d-%H%M)

lee() { "$ZT_PY" -c 'import json,sys; v=json.load(open(sys.argv[1])).get(sys.argv[2]); print("" if v is None else v)' "$CASO/case.json" "$1"; }
MALLA=$(lee mesh_case); TH=$(lee theta_deg); U10=$(lee U10); MODELO=$(lee model); WARM=$(lee warm_from)
[ -n "$MALLA" ] && [ -n "$TH" ] || { echo "case.json incompleto en $CASO"; exit 2; }

FUENTE=""
if [ -n "$WARM" ] && [ -f "$WARM/DONE" ]; then FUENTE=$WARM
else
  for q in $(ls -d "$COLA"/*/ | sed 's|/$||' | sort -r); do
    [ "$(basename "$q")" \< "$NOMBRE" ] || continue
    r=$(cd -P "$q" && pwd)
    [ -f "$r/DONE" ] && [ -f "$r/case.json" ] || continue
    [ "$("$ZT_PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("mesh_case",""))' "$r/case.json")" = "$MALLA" ] || continue
    FUENTE=$r; break
  done
fi

args=(--mesh "$MALLA" --theta "$TH" --U10 "${U10:-5}" --model "${MODELO:-realizableKE}" --chunk 100
      --relax "p=0.2,U=0.5,turb=0.4,simplec=no,nonorth=1")
if [ -n "$FUENTE" ]; then args+=(--warm-from "$FUENTE" --stage1 200); else args+=(--stage1 300); fi

mv "$CASO" "$CASO.fallo-$HOY"
( cd "$ZT_SC" && "$ZT_PY" gen_case.py "${args[@]}" )
if [ ! -f "$CASO/Allrun" ]; then   # gen_case fallo: dejar el caso como estaba
  echo "gen_case no dejo $CASO/Allrun"; [ -d "$CASO" ] && mv "$CASO" "$CASO.gen-fallo-$HOY"; mv "$CASO.fallo-$HOY" "$CASO"; exit 3
fi
# parches M5 (los mismos de var_m5.sh)
sed -i '' 's/mpiexec -n /mpiexec --oversubscribe -n /' "$CASO/Allrun"
sed -i '' -e 's|"//sers/|"/Users/|g' -e 's|extract_h5.py \. 2>&1|extract_h5.py . --out-dir h5_m5 2>\&1|' "$CASO/Allrun"
grep -q "^export ZT_V2" "$CASO/Allrun" || perl -pi -e '$_ .= "export ZT_V2=$ENV{ZT_V2} ZT_RUNS=$ENV{ZT_RUNS} ZT_PY=$ENV{ZT_PY} ZT_SC=$ENV{ZT_SC}\n" if /^PY=/' "$CASO/Allrun"
chmod +x "$CASO/Allrun"
touch "$CASO/.rescatado"
if [ -n "$FUENTE" ]; then como="en caliente desde $(basename "$FUENTE")"; else como="en frio"; fi
echo "$(date '+%m-%d %H:%M') $NOMBRE rescatado $como; el fallido queda en $(basename "$CASO").fallo-$HOY"
