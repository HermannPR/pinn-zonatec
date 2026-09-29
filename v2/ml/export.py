"""Export a trained PINNMLP to a small JSON of weights for in-browser JS
inference, plus a pure NumPy reference forward pass used to verify the
round-trip (torch vs. exported JSON) to 1e-5 (ml/tests/test_export.py).

Differences from v1 (E:\\PINN\\inbox\\wind-pinn\\public\\model.json)
----------------------------------------------------------------------
v1 was a 2D, single-speed model: inputs were raw (x,y) min-max normalised
via `in_norm`, output was 3 quantities (u,v,p) rescaled by a single fixed
`out_scale`, and the whole file baked in one fixed (rho, nu, U0, L0).

v2 (this module) is 3D, multi-direction, multi-geometry, multi-speed:
  * Inputs are (x,y,z) DIVIDED BY h_ref (not min-max scaled to a box), plus
    (sin theta, cos theta), a learned per-variant embedding vector, and
    tanh(sdf/h_ref) / (local_height/h_ref) instead of raw coordinates.
  * Outputs (u,v,w,p,k,nut) are non-dimensional (by U_H, U_H^2, U_H*h_ref)
    and are NOT rescaled inside the exported network -- `nondim` in the
    JSON carries (h_ref, kappa, cmu, z0, d) so the JS caller can compute
    U_H(U10) itself (same log-law formula as synthetic.py /
    docs/DATA_CONTRACT.md) and rescale outputs back to physical units. This
    is required because the model must generalise across held-out speeds,
    which a single baked-in `out_scale` (v1's approach) cannot do.
  * k and nut go through softplus(+eps) to stay positive; v1 had no such
    constraint (it did not predict k/nut at all).
  * A `variant_embedding` table replaces v1's implicit single-geometry
    assumption.

app.js should therefore: (1) look up the variant embedding row by name,
(2) build the same feature vector as PINNMLP.forward, (3) run the plain
MLP, (4) apply softplus to the k/nut columns, (5) multiply by U_H(U10) etc.
using `nondim` before displaying physical units.

Note on sdf / local_height at inference time (review point e)
----------------------------------------------------------------
This module does not embed the building geometry itself, only documents
its contract: the JS caller must compute sdf(x,y,z) and local_height(x,y)
client-side, in METRES, with whatever geometry source is authoritative for
the scene being rendered, and feed those into the exported net exactly as
`predict_from_json` does. For the synthetic smoke-test geometry (axial
boxes) that is the closed-form formula in `ml.synthetic.box_sdf` /
`local_height`. For the real Tec campus geometry, the analogous
differentiable/queryable source is a geometry-pipeline artifact (e.g. a
precomputed SDF/height grid under `E:/PINN/v2/geometry/out/*`) that is
outside this package's scope (`E:/PINN/v2/ml/` and
`E:/PINN/v2/data/synthetic/` only) -- wire it up on the web side once it
exists, using the same metres/`h_ref` units this module assumes.
"""
from __future__ import annotations

import json
import math
from typing import Dict, List

import numpy as np
import torch

from .config import KAPPA, CMU
from .data import VariantVocab
from .models import PINNMLP, OUT_NAMES, POSITIVE_OUTPUTS


def export_pinn_mlp(model: PINNMLP, vocab: VariantVocab, h_ref: float, z0: float, d: float,
                     path: str) -> None:
    model = model.to("cpu").eval()
    layers = []
    for m in model.mlp:
        if isinstance(m, torch.nn.Linear):
            layers.append({
                "W": m.weight.detach().numpy().tolist(),  # [out, in]
                "b": m.bias.detach().numpy().tolist(),
            })
    obj = {
        "format_version": "2.0",
        "differs_from_v1": (
            "3D, multi-direction/geometry/speed; coords scaled by h_ref (not "
            "min-max box); outputs are non-dim (u,v,w,p,k,nut), rescale "
            "client-side with nondim.h_ref/kappa/z0/d and the target U10; "
            "k,nut pass through softplus; adds a variant embedding table."
        ),
        "activation": "tanh",
        "fourier": {
            "B": model.fourier.B.detach().numpy().tolist(),  # [3, num_bands]
        },
        "variant_embedding": {
            "names": vocab.variants,
            "table": model.variant_emb.weight.detach().numpy().tolist(),
        },
        "mlp": {"layers": layers},
        "output_names": OUT_NAMES,
        "positive_outputs": sorted(POSITIVE_OUTPUTS),
        "softplus_eps": 1e-6,
        "nondim": {
            "h_ref": h_ref, "kappa": KAPPA, "cmu": CMU, "z0": z0, "d": d,
            "note": "U_H(U10) = (u*/kappa)*ln((h_ref-d+z0)/z0), u* = U10*kappa/ln((10-d+z0)/z0)",
        },
        "input_layout": ["fourier(sin,cos of 2*pi*B@[x,y,z]/h_ref)", "sin_theta", "cos_theta",
                          "variant_embedding", "tanh(sdf/h_ref)", "local_height/h_ref"],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _softplus(x: np.ndarray) -> np.ndarray:
    return np.log1p(np.exp(-np.abs(x))) + np.maximum(x, 0.0)


def predict_from_json(obj: Dict, xyz_m: np.ndarray, theta_deg: np.ndarray, variant_name,
                       sdf_m: np.ndarray, height_m: np.ndarray) -> Dict[str, np.ndarray]:
    """Pure NumPy reference forward pass matching PINNMLP.forward exactly,
    for round-trip verification against the torch model."""
    h_ref = obj["nondim"]["h_ref"]
    B = np.array(obj["fourier"]["B"])  # [3, num_bands]
    xyz_nd = xyz_m / h_ref
    proj = 2.0 * math.pi * (xyz_nd @ B)
    ff = np.concatenate([np.sin(proj), np.cos(proj)], axis=-1)

    theta = np.deg2rad(theta_deg)
    sincos = np.stack([np.sin(theta), np.cos(theta)], axis=-1)
    if sincos.ndim == 1:
        sincos = np.tile(sincos, (xyz_m.shape[0], 1))

    names = obj["variant_embedding"]["names"]
    table = np.array(obj["variant_embedding"]["table"])
    if isinstance(variant_name, str):
        vid = names.index(variant_name)
        emb = np.tile(table[vid], (xyz_m.shape[0], 1))
    else:
        idx = np.array([names.index(v) for v in variant_name])
        emb = table[idx]

    sdf_feat = np.tanh(sdf_m / h_ref).reshape(-1, 1)
    h_feat = (height_m / h_ref).reshape(-1, 1)

    feat = np.concatenate([ff, sincos, emb, sdf_feat, h_feat], axis=-1)

    x = feat
    layers = obj["mlp"]["layers"]
    for i, layer in enumerate(layers):
        W = np.array(layer["W"])  # [out, in]
        b = np.array(layer["b"])
        x = x @ W.T + b
        if i < len(layers) - 1:
            x = np.tanh(x)

    out = {}
    for i, name in enumerate(obj["output_names"]):
        col = x[:, i]
        if name in obj["positive_outputs"]:
            col = _softplus(col) + obj["softplus_eps"]
        out[name] = col
    return out
