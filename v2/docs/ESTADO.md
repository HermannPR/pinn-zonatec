# ESTADO - PINN Zona Tec

Documento para que cualquiera sepa qué está pasando. La parte automática la reescriben los scripts (`tools\estado.ps1`, `v2\scripts\estado.py`, la cola de trabajos); el resto lo actualiza el líder.

## Cómo revisar
- Estado actual: esta página o `E:\PINN\estado.json`. Cada 5 min lo lee la tarea programada **HivemindPinnEstado** y avisa al canal: ALERTA si el proceso murió, si no hay latido en más de 45 min, si hay un error en el log o si quedan menos de 10 GB en E:.
- Cola de trabajos largos: `E:\PINN\cola\` (ver `cola\README.md`); cada trabajo deja las marcas `DONE`/`FAILED` en `cola\state\`.
- Logs: `E:\PINN\logs\`.

## Estado automÃ¡tico
<!-- AUTO:BEGIN (generado por tools\estado.ps1; no editar a mano) -->
| Campo | Valor |
|---|---|
| Fase | cola |
| Caso | - |
| Progreso | 3/3 |
| Detalle | cola vacía: todos los trabajos terminados |
| Corriendo | False |
| Proceso |  |
| Log | `` |
| Último latido | 2026-09-28T19:19:44 |
<!-- AUTO:END -->



































