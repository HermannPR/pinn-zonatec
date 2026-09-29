"""Export the PINN smoke-test checkpoint to public/data/model.json for the
web app (P11=A). Run from E:\\PINN\\v2 with the project venv:

    E:\\PINN\\.venv\\Scripts\\python.exe web\\build\\export_model.py

Reads a trained PINNMLP checkpoint (default: the latest smoke stageC_fixed
run, which has real physics residuals and converges reasonably on the
synthetic smoke dataset -- see ml/README.md and ml/PROGRESO.md) and writes
the JSON format `ml/export.py` defines, plus a `metadata` block the web app
uses to show the "MODELO DE PRUEBA (sintetico)" banner.

IMPORTANT (see PROGRESO.md "Diseno de datos"): `nondim.h_ref` in the
exported JSON is the checkpoint's OWN TRAINING h_ref (25.0 m for the smoke
model), not Zona Tec's real H_ref (87.75 m). This is required for the JS
forward pass to reproduce the torch forward pass exactly (round-trip test,
1e-5). The REAL H_ref and per-sector (z0,d) used to convert the network's
non-dimensional output into physical K/U_H come from a separate file
(scene.json / climate.json, see build_climate_assets.py) -- when the real
model (trained on real Zona Tec geometry) replaces this one, its own
nondim.h_ref will be 87.75 and the two paths naturally agree.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import torch

V2_ROOT = Path(r"E:\PINN\v2")
sys.path.insert(0, str(V2_ROOT))

from ml.export import export_pinn_mlp  # noqa: E402
from ml.models import PINNMLP  # noqa: E402

CHECKPOINT = V2_ROOT / "ml" / "runs" / "smoke" / "20260928_195807" / "stageC_fixed" / "checkpoint.pt"
OUT_PATH = Path(r"E:\PINN\v2\web\public\data\model.json")

# Must match ml/runs/smoke/20260928_195807/stageC_fixed/config.yaml exactly
# (data.h_ref, features.*, model.*) -- this is what the checkpoint's weights
# were trained with.
H_REF_TRAIN = 25.0
NUM_FOURIER_BANDS = 8
FOURIER_SIGMA = 4.0
HIDDEN_LAYERS = [64, 64, 64]
ACTIVATION = "tanh"
SDF_WALL_SCALE = 10.0
NUT_SCALE = 0.01
K_SCALE = 1.0

# Placeholder (z0, d) baked into nondim purely for backward-compat with
# `ml.export.export_pinn_mlp`'s signature / `predict_from_json`'s note
# formula; the web app does NOT use these for the real K computation (see
# module docstring above and climate.js) -- it uses the per-sector table in
# climate.json instead.
PLACEHOLDER_Z0 = 0.5
PLACEHOLDER_D = 0.0


def main() -> None:
    if not CHECKPOINT.exists():
        raise SystemExit(f"Checkpoint not found: {CHECKPOINT}")

    model = PINNMLP(
        h_ref=H_REF_TRAIN,
        num_fourier_bands=NUM_FOURIER_BANDS,
        fourier_sigma=FOURIER_SIGMA,
        hidden_layers=HIDDEN_LAYERS,
        activation=ACTIVATION,
        sdf_wall_scale=SDF_WALL_SCALE,
        nut_scale=NUT_SCALE,
        k_scale=K_SCALE,
    )
    ckpt = torch.load(CHECKPOINT, map_location="cpu")
    # ml/train.py saves {'state_dict': ..., 'model_kind', 'stage', 'hidden_layers',
    # 'activation', 'num_fourier_bands', 'fourier_sigma', 'h_ref', 'sdf_wall_scale',
    # 'nut_scale', 'k_scale'} -- sanity-check the saved config matches the
    # constants above (loud failure beats a silently-wrong export) before
    # loading state_dict.
    if isinstance(ckpt, dict) and "state_dict" in ckpt:
        expected = dict(hidden_layers=HIDDEN_LAYERS, activation=ACTIVATION,
                         num_fourier_bands=NUM_FOURIER_BANDS, fourier_sigma=FOURIER_SIGMA,
                         h_ref=H_REF_TRAIN, sdf_wall_scale=SDF_WALL_SCALE,
                         nut_scale=NUT_SCALE, k_scale=K_SCALE)
        for k, v in expected.items():
            if k in ckpt and ckpt[k] != v:
                raise SystemExit(f"Checkpoint config mismatch: {k}={ckpt[k]!r} but script has {v!r}")
        state = ckpt["state_dict"]
    else:
        state = ckpt
    model.load_state_dict(state)
    model.eval()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    export_pinn_mlp(model, h_ref=H_REF_TRAIN, z0=PLACEHOLDER_Z0, d=PLACEHOLDER_D, path=str(OUT_PATH))

    # Patch in web-facing metadata (format_version stays ml/export.py's own).
    with open(OUT_PATH, "r", encoding="utf-8") as f:
        obj = json.load(f)
    obj["metadata"] = {
        "synthetic": True,
        "source_checkpoint": str(CHECKPOINT.relative_to(Path(r"E:\PINN"))).replace("\\", "/"),
        "stage": "C_fixed (datos + continuidad + momento RANS, pesos fijos)",
        "trained_on": "geometria sintetica de humo (ml/synthetic.py), NO Zona Tec real",
        "warning_es": (
            "MODELO DE PRUEBA (sintetico): esta red fue entrenada sobre una "
            "escena sintetica de cajas para probar el flujo de datos "
            "(navegador <- JSON <- entrenamiento), no sobre CFD real de Zona "
            "Tec. Los valores de viento mostrados NO son fisicamente "
            "representativos del campus todavia."
        ),
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(obj, f)

    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
