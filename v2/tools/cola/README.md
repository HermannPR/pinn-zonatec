# Cola de trabajos a prueba de fallas (PINN Zona Tec)

Todo trabajo largo (mallado, simpleFoam, extracción, entrenamiento) se ejecuta **solo** a través de esta cola.

## Piezas
| Pieza | Qué hace |
|---|---|
| `E:\PINN\tools\cola\runner.ps1` | Ejecuta los trabajos de `cola\jobs\*.json` en orden de nombre, uno a la vez, en prioridad BelowNormal. Revisa el disco antes de cada caso, actualiza `estado.json` (latido cada vez que crece el log), verifica el resultado antes de marcar `DONE`, reintenta hasta `max_attempts` y marca `FAILED` con aviso al canal. |
| `E:\PINN\tools\cola\watchdog.ps1` | Tarea programada de usuario **PinnColaWatchdog** (cada 10 min y al iniciar sesión). Si hay trabajos pendientes y ningún runner vivo, lo relanza. |
| `E:\PINN\tools\estado.ps1`, `v2\scripts\estado.py` | Escriben `E:\PINN\estado.json` y `ESTADO.md`, que lee el monitor HivemindPinnEstado. |
| `cola\state\<id>.DONE / .FAILED / .attempts / .verify.log` | Marcas de estado. Para reintentar un FAILED, borra su `.FAILED` y su `.attempts`. |
| `cola\PAUSA` | Si existe este archivo, el watchdog no relanza nada (pausa manual). |

Probado el 28-sep-2026: trabajo OpenFOAM, trabajo Python, dependencias (`after`), reintentos, FAILED con máximo de intentos, y matar el runner a media corrida con el watchdog relanzándolo (el trabajo terminó en el intento 2). Las pruebas están en `cola\pruebas\`.

Limitación: tras un reinicio de Windows, la tarea corre **al iniciar sesión** (no hay inicio de sesión automático sin admin). Si la PC se reinicia, alguien tiene que iniciar sesión.

## Especificación de un trabajo (`cola\jobs\NNN_<id>.json`)
```json
{"id":"110_zt_base_th1125","fase":"F3 campaña","kind":"openfoam",
 "case":"E:\\PINN\\runs\\zonatec\\base_th1125","cmd":"./Allrun.resumable",
 "verify":"E:\\PINN\\.venv\\Scripts\\python.exe E:\\PINN\\v2\\cfd\\verify_case.py E:\\PINN\\runs\\zonatec\\base_th1125",
 "after":["100_zt_mesh_base"],"min_free_gb":15,"max_attempts":4,"hang_minutes":180,
 "notify":"16 direcciones: 1/16"}
```
`kind`: `openfoam` (ejecuta `cmd` en bash con el entorno de OpenFOAM, dentro de `case`) o `python` (`args`: lista; `workdir`, por defecto `E:\PINN\v2`).

## Contrato OBLIGATORIO para los scripts de trabajo
1. **Idempotente y reanudable.** Hay que poder matarlo en cualquier momento y relanzarlo, y debe seguir donde iba:
   - Cada paso deja su marca (`.mesh.ok`, `.decompose.ok`, …) y se salta si la marca existe y su salida es válida.
   - Solver: `startFrom latestTime`, `writeInterval` ≤ 200 iteraciones, `purgeWrite 2`.
   - Al reanudar, se valida el último tiempo escrito (todos los campos presentes y legibles; en paralelo, en todos los `processor*`). Si está incompleto porque lo cortó un apagón, se borra y se usa el anterior.
2. **Todo al stdout.** Los logs de los solvers deben aparecer en el log del trabajo (`2>&1 | tee log.X` o `cat log.X` al final de cada paso). Así avanza el latido y el monitor ve `FOAM FATAL`.
3. **Código de salida** ≠ 0 si algo falla (`set -e` en bash).
4. **Verificación** (`verify`) independiente del script, que termina con exit 0 solo si:
   - los residuales iniciales finales son < 1e-4, o están estancados y los monitores de U varían < 1 % en las últimas 500 iteraciones;
   - no hay NaN;
   - `checkMesh` está OK (solo en trabajos de malla);
   - existen los archivos de salida esperados (p. ej., el HDF5 del contrato).
5. **Espacio:** los casos terminados se reducen al último tiempo + postProcessing (y el HDF5), y los procesadores se reconstruyen o se borran.
