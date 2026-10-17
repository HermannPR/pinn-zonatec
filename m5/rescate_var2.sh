#!/bin/bash
# Rescate del primer caso de una variante que divergio en frio (receta de cln, 160 de var1, 17 oct):
# puente sobre la malla destino + mapFields -consistent desde una fuente convergida + warmstart (rota U si
# cambia theta) + 200 it de primer orden y relajacion baja.
#
#   m5/rescate_var2.sh <fuente> [--solo-puente | --lanzar]
#
#   --solo-puente  arma y mapea el puente; no toca el caso ni la cola (preparacion, sin OK)
#   (sin flag)     ademas guarda el frio como .frio-diverge-<fecha>, regenera el caso y limpia marcas de la cola
#   --lanzar       todo lo anterior y kickstart de noche.sh
# Reintentar un caso FAILED pide OK de Hermann: solo corre sin --solo-puente con ese OK.
set -euo pipefail
FUENTE=$(cd "${1:?caso fuente convergido}" && pwd); MODO=${2:-}
F=$HOME/dev/pinn-zonatec/f3
export ZT_V2=$F/paquete/pinn/v2 ZT_RUNS=$F/paquete/pinn/runs/zonatec ZT_PY=$F/.venv/bin/python
export ZT_SC=$ZT_V2/cfd/zonatec/scripts
OF=/Applications/OpenFOAM-v2306.app/Contents/Resources/etc/openfoam
MALLA=$ZT_RUNS/mesh_var2_fine; CID=zt_var2_th0900_U050_m1; CASO=$ZT_RUNS/$CID; PUENTE=${CASO}_mapsrc
COLA=$F/cola; HOY=$(date +%Y%m%d-%H%M)

# 1) puente: malla destino, system/constant/0/case.json del caso frio (o del frio guardado)
PLANT=$CASO; [ -f "$PLANT/case.json" ] || PLANT=$(ls -d "$CASO".frio-diverge-* | tail -1)
if [ ! -f "$PUENTE/1/U" ]; then
  rm -rf "$PUENTE"; mkdir -p "$PUENTE"
  cp -R "$PLANT/system" "$PLANT/constant" "$PLANT/case.json" "$PUENTE/"
  cp -R "$PLANT/0.orig" "$PUENTE/0" 2>/dev/null || cp -R "$PLANT/0" "$PUENTE/0"
  rm -f "$PUENTE"/system/decomposeParDict.bak
  "$OF" -c "cd '$PUENTE' && mapFields '$FUENTE' -sourceTime latestTime -consistent" > "$PUENTE/log.mapFields" 2>&1
  mkdir -p "$PUENTE/1"; for f in U p k epsilon nut; do cp "$PUENTE/0/$f" "$PUENTE/1/$f"; done
  # theta de la fuente en el puente: warmstart rota U por (theta destino - theta puente)
  "$ZT_PY" - "$FUENTE/case.json" "$PUENTE/case.json" <<'PY'
import json, sys
s, p = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
p["theta_deg"] = s["theta_deg"]; json.dump(p, open(sys.argv[2], "w"), indent=1)
print("puente theta", p["theta_deg"])
PY
fi
grep -E "^Mapping|^End|FOAM FATAL" "$PUENTE/log.mapFields" | tail -3
[ "$MODO" = "--solo-puente" ] && { echo "puente listo: $PUENTE"; exit 0; }

# 2) guardar el frio y regenerar en caliente (mismos parches M5 que var_m5.sh)
[ -d "$CASO" ] && mv "$CASO" "$CASO.frio-diverge-$HOY"
( cd "$ZT_SC" && "$ZT_PY" gen_case.py --mesh "$MALLA" --theta 90 --U10 5 --model realizableKE --chunk 100 \
    --relax "p=0.2,U=0.5,turb=0.4,simplec=no,nonorth=1" --warm-from "$PUENTE" --stage1 200 )
sed -i '' 's/mpiexec -n /mpiexec --oversubscribe -n /' "$CASO/Allrun"
sed -i '' -e 's|"//sers/|"/Users/|g' -e 's|extract_h5.py \. 2>&1|extract_h5.py . --out-dir h5_m5 2>\&1|' "$CASO/Allrun"
grep -q "^export ZT_V2" "$CASO/Allrun" || perl -pi -e '$_ .= "export ZT_V2=$ENV{ZT_V2} ZT_RUNS=$ENV{ZT_RUNS} ZT_PY=$ENV{ZT_PY} ZT_SC=$ENV{ZT_SC}\n" if /^PY=/' "$CASO/Allrun"
chmod +x "$CASO/Allrun"

# 3) limpiar marcas de fallo del 04 (se guardan, no se borran). 05-11 es otro paso (pide plan a la maestra)
for c in "$COLA"/04_zt_var2_*; do
  mkdir -p "$c/.fallo-$HOY"; for m in .FAILED FAILED; do [ -e "$c/$m" ] && mv "$c/$m" "$c/.fallo-$HOY/"; done
done
echo "04 regenerado en caliente desde $(basename "$FUENTE") via puente"
[ "$MODO" = "--lanzar" ] && launchctl kickstart "gui/$(id -u)/com.hermann.pinn-noche" && echo "noche.sh lanzado"
exit 0
