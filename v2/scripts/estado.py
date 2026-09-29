"""Update E:\\PINN\\estado.json from Python jobs (ML training, extraction).

Same schema as tools/estado.ps1 (read by the HivemindPinnEstado scheduled task):
{"fase","caso","progreso","detalle","corriendo","proceso","log","latido"}.

    from scripts.estado import set_estado
    set_estado(fase="F4 PINN", caso="stageB", progreso="epoch 120/2000",
               detalle="loss 3.2e-3", corriendo=True, proceso="python", log=r"E:\\PINN\\logs\\train.log")

Call it at every epoch/checkpoint so 'latido' stays fresh (the monitor alerts after 45 min
without a heartbeat). Call set_estado(corriendo=False, ...) when the job ends.
Writes atomically; never raises (status reporting must not kill a training run).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import time

ESTADO_JSON = r"E:\PINN\estado.json"
_KEYS = ("fase", "caso", "progreso", "detalle", "corriendo", "proceso", "log", "latido")


def get_estado() -> dict:
    try:
        with open(ESTADO_JSON, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def set_estado(latido: bool = True, **kw) -> None:
    try:
        e = {k: "" for k in _KEYS}
        e["corriendo"] = False
        e.update({k: v for k, v in get_estado().items() if k in _KEYS})
        e.update({k: v for k, v in kw.items() if k in _KEYS})
        if latido:
            e["latido"] = _dt.datetime.now().replace(microsecond=0).isoformat()
        tmp = ESTADO_JSON + ".pytmp"
        for _ in range(5):
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(e, f, ensure_ascii=False, indent=2)
                os.replace(tmp, ESTADO_JSON)
                break
            except OSError:
                time.sleep(0.3)
    except Exception:
        pass
