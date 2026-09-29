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
    (sin theta, cos theta), tanh(sdf/sdf_wall_scale) and local_height/h_ref
    instead of raw coordinates.
  * Outputs (u,v,w,p,k,nut) are non-dimensional (by U_H, U_H^2, U_H*h_ref)
    and are NOT rescaled inside the exported network -- `nondim` in the
    JSON carries (h_ref, kappa, cmu, z0, d) so the JS caller can compute
    U_H(U10) itself (same log-law formula as synthetic.py /
    docs/DATA_CONTRACT.md) and rescale outputs back to physical units. This
    is required because the model must generalise across held-out speeds,
    which a single baked-in `out_scale` (v1's approach) cannot do.
  * k and nut go through scale*softplus(raw)+eps to stay positive (design
    review M1: `nut_scale` defaults to 0.01 so the untrained network starts
    near a physically plausible turbulent-viscosity scale, not O(1)).
  * No per-variant embedding (design review M4): a held-out geometry
    variant would get an untrained embedding row, so geometry enters only
    through sdf/local_height, which are defined and meaningful for a
    variant the network never trained on.

app.js should therefore: (1) build the same feature vector as
PINNMLP.forward (fourier(xyz), sincos, tanh(sdf/sdf_wall_scale),
height/h_ref), (2) run the plain MLP, (3) apply scale*softplus+eps to the
k/nut columns, (4) multiply by U_H(U10) etc. using `nondim` before
displaying physical units.

Note on sdf / local_height at inference time (review point e)
----------------------------------------------------------------
This module does not embed the building geometry itself, only documents
its contract: the JS caller must compute sdf(x,y,z) and local_height(x,y)
client-side, in METRES, with whatever geometry source is authoritative for
the scene being rendered, and feed those into the exported net exactly as
`predict_from_json` does. For the synthetic smoke-test geometry (axial
boxes) that is the closed-form formula in `ml.synthetic.box_sdf` /
`local_height`. For the real Tec campus geometry, the analogous
differentiable/queryable source is a geometry-pipeline artifact (e.g. an
analytic smooth polygon-prism SDF, see `ml.features.PolygonPrismGeometry`)
that is outside this package's scope (`E:/PINN/v2/ml/` and
`E:/PINN/v2/data/synthetic/` only) -- wire it up on the web side once it
exists, using the same metres/`h_ref` units this module assumes.
"""
from __future__ import annotations

import json
import math
from typing import Dict

import numpy as np
import torch

from .config import KAPPA, CMU
from .models import PINNMLP, OUT_NAMES, POSITIVE_OUTPUTS


def export_pinn_mlp(model: PINNMLP, h_ref: float, z0: float, d: float, path: str) -> None:
    model = model.to("cpu").eval()
    layers = []
    for m in model.mlp:
        if isinstance(m, torch.nn.Linear):
            layers.append({
                "W": m.weight.detach().numpy().tolist(),  # [out, in]
                "b": m.bias.detach().numpy().tolist(),
            })
    obj = {
        "format_version": "2.1",
        "differs_from_v1": (
            "3D, multi-direction/geometry/speed; coords scaled by h_ref (not "
            "min-max box); outputs are non-dim (u,v,w,p,k,nut), rescale "
            "client-side with nondim.h_ref/kappa/z0/d and the target U10; "
            "k,nut pass through scale*softplus+eps (design review M1); no "
            "per-variant embedding (design review M4, see module docstring)."
        ),
        "activation": "tanh",
        "fourier": {
            "B": model.fourier.B.detach().numpy().tolist(),  # [3, num_bands]
        },
        "mlp": {"layers": layers},
        "output_names": OUT_NAMES,
        "positive_outputs": sorted(POSITIVE_OUTPUTS),
        "positive_scale": model.positive_scale,
        "softplus_eps": 1e-6,
        "sdf_wall_scale": model.sdf_wall_scale,
        "nondim": {
            "h_ref": h_ref, "kappa": KAPPA, "cmu": CMU, "z0": z0, "d": d,
            "note": (
                "U_H(U10) = (u_star/kappa)*ln((h_ref-d+z0)/z0), with "
                "u_star = T(theta)*U10 from the P14-A two-layer roughness "
                "transfer (climate.transfer.inflow_for_sector / "
                "transfer_factor), NOT u_star=U10*kappa/ln((10-d+z0)/z0) "
                "(that no-transfer formula treats the airport station's z0 "
                "as if it were the urban z0 and overestimates K by "
                "5-31% depending on sector -- design review I2/M-transfer). "
                "z0/d here are the SECTOR's regional (z0,d), matching "
                "climate.transfer.InflowResult.z0/.d for whichever "
                "(theta, U10) this case's data came from; T(theta) is NOT "
                "baked in here because one exported model serves every "
                "direction -- compute it client-side (or look it up from "
                "climate/roughness_16sectors.csv) the same way "
                "climate.transfer.transfer_factor does, or precompute a "
                "16-sector T table and ship it alongside this file."
            ),
        },
        "input_layout": ["fourier(sin,cos of 2*pi*B@[x,y,z]/h_ref)", "sin_theta", "cos_theta",
                          "tanh(sdf/sdf_wall_scale)", "local_height/h_ref"],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _softplus(x: np.ndarray) -> np.ndarray:
    return np.log1p(np.exp(-np.abs(x))) + np.maximum(x, 0.0)


def predict_from_json(obj: Dict, xyz_m: np.ndarray, theta_deg: np.ndarray,
                       sdf_m: np.ndarray, height_m: np.ndarray) -> Dict[str, np.ndarray]:
    """Pure NumPy reference forward pass matching PINNMLP.forward exactly,
    for round-trip verification against the torch model."""
    h_ref = obj["nondim"]["h_ref"]
    wall_scale = obj.get("sdf_wall_scale", 10.0)
    B = np.array(obj["fourier"]["B"])  # [3, num_bands]
    xyz_nd = xyz_m / h_ref
    proj = 2.0 * math.pi * (xyz_nd @ B)
    ff = np.concatenate([np.sin(proj), np.cos(proj)], axis=-1)

    theta = np.deg2rad(theta_deg)
    sincos = np.stack([np.sin(theta), np.cos(theta)], axis=-1)
    if sincos.ndim == 1:
        sincos = np.tile(sincos, (xyz_m.shape[0], 1))

    sdf_feat = np.tanh(sdf_m / wall_scale).reshape(-1, 1)
    h_feat = (height_m / h_ref).reshape(-1, 1)

    feat = np.concatenate([ff, sincos, sdf_feat, h_feat], axis=-1)

    x = feat
    layers = obj["mlp"]["layers"]
    for i, layer in enumerate(layers):
        W = np.array(layer["W"])  # [out, in]
        b = np.array(layer["b"])
        x = x @ W.T + b
        if i < len(layers) - 1:
            x = np.tanh(x)

    out = {}
    scale = obj.get("positive_scale", {})
    for i, name in enumerate(obj["output_names"]):
        col = x[:, i]
        if name in obj["positive_outputs"]:
            col = scale.get(name, 1.0) * _softplus(col) + obj["softplus_eps"]
        out[name] = col
    return out
