#!/bin/bash
# Corredor nocturno del PINN en la M5: un caso a la vez, solo dentro de la ventana.
#
#   m5/noche.sh <cola>          cola/<NN>_<caso>/ con Allrun; marca .DONE / .FAILED / .PAUSADO
#
# - Fuera de la ventana (HORA_INI..HORA_FIN) no arranca nada.
# - A HORA_FIN pide writeNow al solver (controlDict stopAt) y deja el caso .PAUSADO;
#   la noche siguiente sigue desde el ultimo tiempo escrito (Allrun debe usar latestTime).
# - touch <cola>/.PARAR o el interruptor $CTRL/PAUSA (~/pinn-control/PAUSA, lo mueve la maestra)
#   detienen igual que el fin de ventana. Corre solo si hay ventana Y no hay PAUSA.
# - Deja una linea de estado en $CTRL/ESTADO para que la maestra la lea en voz.
# - No arranca si memory_pressure da menos de MEM_MIN% libre o si hay un render (ffmpeg, Resolve).
set -u
COLA=${1:?uso: noche.sh <cola>}
HORA_INI=${HORA_INI:-23}
HORA_FIN=${HORA_FIN:-7}
MEM_MIN=${MEM_MIN:-30}
LOG=${LOG:-$COLA/noche.log}
CTRL=${CTRL:-$HOME/pinn-control}

log() { echo "$(date '+%m-%d %H:%M') $*" >> "$LOG"; }
estado() { mkdir -p "$CTRL" && echo "$(date '+%m-%d %H:%M') $*" > "$CTRL/ESTADO"; }
en_ventana() {
  [ -e "$COLA/.PARAR" ] || [ -e "$CTRL/PAUSA" ] && return 1   # parada manual: se trata como fin de ventana
  local h=$((10#$(date +%H)))
  if [ "$HORA_INI" -gt "$HORA_FIN" ]; then [ "$h" -ge "$HORA_INI" ] || [ "$h" -lt "$HORA_FIN" ]
  else [ "$h" -ge "$HORA_INI" ] && [ "$h" -lt "$HORA_FIN" ]; fi
}
mem_libre() { memory_pressure | awk -F': ' '/free percentage/ {gsub("%","",$2); print $2}'; }
hay_render() { pgrep -qx ffmpeg || pgrep -qf 'DaVinci Resolve'; }

for caso in "$COLA"/*/; do
  caso=${caso%/}
  [ -e "$caso/.DONE" ] || [ -e "$caso/.FAILED" ] && continue
  [ -x "$caso/Allrun" ] || { log "$caso sin Allrun, salto"; continue; }
  en_ventana || { log "fuera de ventana o en PAUSA, salgo"; estado "PINN en pausa (sin ventana o PAUSA)"; exit 0; }
  if [ "$(mem_libre)" -lt "$MEM_MIN" ]; then log "memoria libre $(mem_libre)% < $MEM_MIN%, salgo"; exit 0; fi
  if hay_render; then log "hay un render corriendo, salgo"; exit 0; fi

  rm -f "$caso/.PAUSADO"
  log "arranca $caso"; estado "PINN corriendo $(basename "$caso")"
  ( cd "$caso" && exec openfoam -c ./Allrun ) >> "$caso/log.noche" 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if ! en_ventana; then
      log "fin de ventana: writeNow en $caso"
      openfoam -c "foamDictionary -entry stopAt -set writeNow '$caso/system/controlDict'" > /dev/null 2>&1
      touch "$caso/.PAUSADO"
      wait "$pid"
      openfoam -c "foamDictionary -entry stopAt -set endTime '$caso/system/controlDict'" > /dev/null 2>&1
      log "pausado $caso"; estado "PINN pausado en $(basename "$caso")"
      exit 0
    fi
    sleep 60
  done
  if wait "$pid"; then touch "$caso/.DONE"; log "termina $caso"
  else touch "$caso/.FAILED"; log "FALLA $caso (ver log.noche)"; fi
done
log "cola vacia"; estado "PINN cola vacia"
