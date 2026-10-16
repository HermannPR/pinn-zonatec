#!/bin/bash
# Corre f4.py de dia con nice 19 y lo reanuda cuando deja de haber motivo para ceder.
#   train/correr.sh <run> [args de f4.py...]      (nohup ... &; un solo correr.sh por run)
# f4.py sale con 75 cuando cede (CEDER del gestor, PAUSA_ENTRENO, render, CFD, memoria): espera 5 min y reintenta.
# Tres fallas seguidas de otro tipo dejan train/runs/<run>/FAILED y paran.
set -u
AQUI="$(cd "$(dirname "$0")" && pwd)"
RUN=${1:?uso: correr.sh <run> [args]}; shift
DIR="$AQUI/runs/$RUN"; mkdir -p "$DIR"
PIDF="$DIR/correr.pid"
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then echo "ya corre"; exit 0; fi
echo $$ > "$PIDF"; trap 'rm -f "$PIDF"' EXIT
fallas=0
while [ ! -e "$DIR/DONE" ] && [ ! -e "$DIR/FAILED" ]; do
  nice -n 19 "$AQUI/.venv/bin/python" "$AQUI/f4.py" --run "$RUN" "$@" >> "$DIR/salida.log" 2>&1
  rc=$?
  if [ $rc = 0 ]; then break
  elif [ $rc = 75 ]; then fallas=0; sleep 300
  else fallas=$((fallas + 1)); echo "$(date '+%m-%d %H:%M') f4.py salio con $rc ($fallas)" >> "$DIR/salida.log"
       [ $fallas -ge 3 ] && touch "$DIR/FAILED"; sleep 60; fi
done
