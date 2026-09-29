"""Loss terms for stages A/B/C (P23) and the impermeability BC (P24=B).

M5 (design review): `data_loss` standardises each field's error by that
field's own training-set standard deviation (passed in as `field_std`)
before averaging. On the synthetic smoke data the non-dim std ranges from
~0.003 (k) to ~0.28 (v); an unweighted MSE sum effectively only fits v,
leaving k, w, p (and, transitively, nut, which feeds the momentum residual)
almost unsupervised. `field_std` defaults to all-ones (old, unweighted
behaviour) so this is opt-in via whoever computes stats (train.py, from
CaseStore.field_stats).

M6 (design review): `continuity_loss`/`momentum_loss` accept an optional
`vol_weight` (cell volume normalised to a batch mean of 1, from
EpochSampler) so refined-mesh regions -- oversampled by plain per-point
averaging over an already-imbalanced point cloud -- don't dominate the
residual.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import torch

from . import physics

DATA_FIELDS = ["u", "v", "w", "p", "k", "nut"]


def data_loss(pred: Dict[str, torch.Tensor], target: Dict[str, torch.Tensor],
              field_std: Optional[Dict[str, float]] = None
              ) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
    field_std = field_std or {}
    per_field = {}
    for f in DATA_FIELDS:
        s = max(field_std.get(f, 1.0), 1e-8)
        per_field[f] = torch.mean(((pred[f] - target[f]) / s) ** 2)
    total = sum(per_field.values())
    return total, per_field


def _weighted_mean(x: torch.Tensor, weight: Optional[torch.Tensor]) -> torch.Tensor:
    if weight is None:
        return torch.mean(x)
    return torch.sum(x * weight) / torch.clamp(torch.sum(weight), min=1e-12)


def continuity_loss(pred: Dict[str, torch.Tensor], xyz: torch.Tensor,
                     vol_weight: Optional[torch.Tensor] = None) -> torch.Tensor:
    """`xyz` must be the exact tensor object passed into the model's forward
    call that produced `pred` (see physics.py module docstring)."""
    res = physics.continuity_residual(pred["u"], pred["v"], pred["w"], xyz)
    return _weighted_mean(res ** 2, vol_weight)


def momentum_loss(pred: Dict[str, torch.Tensor], xyz: torch.Tensor, nu: float,
                   pressure_includes_two_thirds_k: bool = False,
                   vol_weight: Optional[torch.Tensor] = None) -> torch.Tensor:
    rx, ry, rz = physics.momentum_residual(
        pred["u"], pred["v"], pred["w"], pred["p"], pred["nut"], xyz, nu,
        pressure_includes_two_thirds_k=pressure_includes_two_thirds_k, k=pred.get("k"))
    return (_weighted_mean(rx ** 2, vol_weight) + _weighted_mean(ry ** 2, vol_weight)
            + _weighted_mean(rz ** 2, vol_weight))


def wall_bc_loss(pred: Dict[str, torch.Tensor], normal: Dict[str, torch.Tensor]) -> torch.Tensor:
    flux = physics.wall_normal_flux(pred["u"], pred["v"], pred["w"], normal["nx"], normal["ny"], normal["nz"])
    return torch.mean(flux ** 2)
