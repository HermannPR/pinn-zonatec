"""Loss terms for stages A/B/C (P23) and the impermeability BC (P24=B)."""
from __future__ import annotations

from typing import Dict, Tuple

import torch

from . import physics

DATA_FIELDS = ["u", "v", "w", "p", "k", "nut"]


def data_loss(pred: Dict[str, torch.Tensor], target: Dict[str, torch.Tensor]) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
    per_field = {f: torch.mean((pred[f] - target[f]) ** 2) for f in DATA_FIELDS}
    total = sum(per_field.values())
    return total, per_field


def continuity_loss(pred: Dict[str, torch.Tensor], xyz: torch.Tensor) -> torch.Tensor:
    """`xyz` must be the exact tensor object passed into the model's forward
    call that produced `pred` (see physics.py module docstring)."""
    res = physics.continuity_residual(pred["u"], pred["v"], pred["w"], xyz)
    return torch.mean(res ** 2)


def momentum_loss(pred: Dict[str, torch.Tensor], xyz: torch.Tensor, nu: float,
                   pressure_includes_two_thirds_k: bool = False) -> torch.Tensor:
    rx, ry, rz = physics.momentum_residual(
        pred["u"], pred["v"], pred["w"], pred["p"], pred["nut"], xyz, nu,
        pressure_includes_two_thirds_k=pressure_includes_two_thirds_k, k=pred.get("k"))
    return torch.mean(rx ** 2) + torch.mean(ry ** 2) + torch.mean(rz ** 2)


def wall_bc_loss(pred: Dict[str, torch.Tensor], normal: Dict[str, torch.Tensor]) -> torch.Tensor:
    flux = physics.wall_normal_flux(pred["u"], pred["v"], pred["w"], normal["nx"], normal["ny"], normal["nz"])
    return torch.mean(flux ** 2)
