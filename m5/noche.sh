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
# - La bandera CEDER del gestor de recursos (RAM critica con un render) tambien detiene, igual que PAUSA.
# - No arranca si memory_pressure da menos de MEM_MIN% libre o si hay un render (ffmpeg, Resolve).
# - <cola>/.noche.env (opcional) fija variables por cola, p. ej. la cadena var2 (OK14, 17 oct):
#     SILENCIO_MIN=30  no arranca un caso nuevo hasta que pasen 30 min sin mensajes de Hermann
#                      (ts de la ultima linea de SILENCIO_ARCHIVO); el caso que ya corre no se toca
#     CADENA=1         si un caso queda FAILED no se lanza ningun otro (la cadena caliente depende del anterior)
set -u
COLA=${1:?uso: noche.sh <cola>}
[ -f "$COLA/.noche.env" ] && . "$COLA/.noche.env"
SILENCIO_MIN=${SILENCIO_MIN:-0}
SILENCIO_ARCHIVO=${SILENCIO_ARCHIVO:-$HOME/cerebro/certyca/datos/para-mind.jsonl}
CADENA=${CADENA:-0}
HORA_INI=${HORA_INI:-23}
HORA_FIN=${HORA_FIN:-7}
MEM_MIN=${MEM_MIN:-30}
LOG=${LOG:-$COLA/noche.log}
CTRL=${CTRL:-$HOME/pinn-control}
# Misma version que Culiacan (v2306 MinGW + MS-MPI); la v2606 de brew queda para pruebas.
SOLVER_PAT=${SOLVER_PAT:-simpleFoam -parallel}
OF=${OF:-/Applications/OpenFOAM-v2306.app/Contents/Resources/etc/openfoam}
# Bandera del gestor de recursos (clase CIENCIA): con RAM critica pide guardar (writeNow) y ceder.
CEDER=${CEDER:-$HOME/Library/Application Support/hivemind/gestor/CEDER}

# Una sola copia por cola (launchd la llama cada 30 min).
PIDF=$COLA/.noche.pid
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null; then exit 0; fi
echo $$ > "$PIDF"; trap 'rm -f "$PIDF"' EXIT

log() { echo "$(date '+%m-%d %H:%M') $*" >> "$LOG"; }
estado() { mkdir -p "$CTRL" && echo "$(date '+%m-%d %H:%M') $*" > "$CTRL/ESTADO"; }
en_ventana() {
  [ -e "$COLA/.PARAR" ] || [ -e "$CTRL/PAUSA" ] && return 1   # parada manual: se trata como fin de ventana
  [ -e "$CEDER" ] && return 1                                  # el gestor pide ceder (RAM critica con un render)
  local h=$((10#$(date +%H)))
  if [ "$HORA_INI" -gt "$HORA_FIN" ]; then [ "$h" -ge "$HORA_INI" ] || [ "$h" -lt "$HORA_FIN" ]
  else [ "$h" -ge "$HORA_INI" ] && [ "$h" -lt "$HORA_FIN" ]; fi
}
mem_libre() { memory_pressure | awk -F': ' '/free percentage/ {gsub("%","",$2); print $2}'; }
hay_render() { pgrep -qx ffmpeg || pgrep -qf 'DaVinci Resolve'; }
# Minutos desde el ultimo mensaje de Hermann; si no se puede leer, 0 (no arranca, lo seguro)
min_silencio() {
  local ts; ts=$(tail -1 "$SILENCIO_ARCHIVO" 2>/dev/null | sed -n 's/.*"ts": *\([0-9]*\).*/\1/p')
  [ -n "$ts" ] && echo $(( ($(date +%s) - ts) / 60 )) || echo 0
}

for caso in "$COLA"/*/; do
  caso=${caso%/}
  [ -e "$caso/.DONE" ] && continue
  if [ -e "$caso/.FAILED" ]; then
    [ "$CADENA" = 1 ] && { log "cadena parada: $caso FAILED"; estado "PINN cadena parada en $(basename "$caso")"; exit 0; }
    continue
  fi
  [ -x "$caso/Allrun" ] || { log "$caso sin Allrun, salto"; continue; }
  en_ventana || { log "fuera de ventana o en PAUSA, salgo"; estado "PINN en pausa (sin ventana o PAUSA)"; exit 0; }
  if [ "$(mem_libre)" -lt "$MEM_MIN" ]; then log "memoria libre $(mem_libre)% < $MEM_MIN%, salgo"; exit 0; fi
  if hay_render; then log "hay un render corriendo, salgo"; exit 0; fi
  if [ "$SILENCIO_MIN" -gt 0 ] && [ "$(min_silencio)" -lt "$SILENCIO_MIN" ]; then
    log "Hermann activo hace $(min_silencio) min (< $SILENCIO_MIN), salgo"; estado "PINN espera silencio de Hermann"; exit 0
  fi

  rm -f "$caso/.PAUSADO"
  log "arranca $caso"; estado "PINN corriendo $(basename "$caso")"
  set -m   # el caso corre en su propio grupo de procesos (pid = pgid) para poder pararlo entero
  ( cd "$caso" && exec "$OF" -c ./Allrun ) >> "$caso/log.noche" 2>&1 &
  pid=$!
  set +m
  while kill -0 "$pid" 2>/dev/null; do
    if ! en_ventana; then
      log "fin de ventana: writeNow en $caso"
      "$OF" -c "foamDictionary -entry stopAt -set writeNow '$caso/system/controlDict'" > /dev/null 2>&1
      touch "$caso/.PAUSADO"
      # El Allrun corre por tramos y relanzaria el solver: en cuanto el solver escribe y sale
      # (o a los 15 min), se detiene todo el grupo. Allrun reanuda desde latestTime y limpia tiempos incompletos.
      vivos=$(pgrep -f "$SOLVER_PAT")   # los procesos del solver que estaban corriendo al pedir writeNow
      for _ in $(seq 450); do
        sleep 2
        kill -0 "$pid" 2>/dev/null || break
        sigue=0; for v in $vivos; do kill -0 "$v" 2>/dev/null && sigue=1; done
        [ "$sigue" = 0 ] && break
      done
      kill -TERM -- "-$pid" 2>/dev/null; sleep 5; kill -KILL -- "-$pid" 2>/dev/null
      wait "$pid" 2>/dev/null
      "$OF" -c "foamDictionary -entry stopAt -set endTime '$caso/system/controlDict'" > /dev/null 2>&1
      log "pausado $caso"; estado "PINN pausado en $(basename "$caso")"
      exit 0
    fi
    sleep 60
  done
  if wait "$pid"; then touch "$caso/.DONE"; log "termina $caso"
  else touch "$caso/.FAILED"; log "FALLA $caso (ver log.noche)"
    [ "$CADENA" = 1 ] && { log "cadena parada: $caso FAILED"; estado "PINN cadena parada en $(basename "$caso")"; exit 0; }
  fi
done
log "cola vacia"; estado "PINN cola vacia"
