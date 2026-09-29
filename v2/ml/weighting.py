"""Adaptive loss weighting (P26=A): fixed weights, and gradient-based
learning-rate annealing (LRA).

M2 (design review): the original LRA anchored on the data term alone
(lambda_hat_r = max|grad(L_data)| / mean|grad(L_r)|), uncapped. On the
smoke run this blew up (continuity weight 1687, wall 29024, momentum 642)
because (i) max/mean over ~1e4 parameters is >>1 even when gradients are
genuinely comparable in scale, and (ii) once the network collapses to a
near-constant field (which trivially satisfies continuity and u.n=0),
grad(L_physics) -> 0, so lambda -> infinity: a positive feedback loop. With
`clip_grad_norm_=1.0` and a total loss in the thousands, the physics term
alone dictated the step direction and the data term (0.999, i.e. "predict
the mean") never recovered.

Fixed per Wang, Teng & Perdikaris / the "expert's guide to training PINNs"
(2023) gradient-NORM formulation, applied symmetrically to ALL terms
(including data, no special anchor):

    lambda_i = (sum_j ||grad(L_j)||) / ||grad(L_i)||
    lambda_i <- alpha * lambda_i + (1-alpha) * lambda_i_hat      (EMA, alpha=0.9)
    lambda_i <- clip(lambda_i, lo * lambda_i^0, hi * lambda_i^0)  (cap, default [1e-2, 1e2] * initial)

and only updated every `update_every` steps (default 100) after a warmup
(default 1000 steps) during which physics weights are ramped in linearly
from 0 (see train.py) rather than applied at full strength while the
network is still near its untrained, wildly-out-of-scale-residual state.
"""
from __future__ import annotations

from typing import Dict, List

import torch


def _grad_norm(loss: torch.Tensor, params: List[torch.nn.Parameter]) -> float:
    grads = torch.autograd.grad(loss, params, retain_graph=True, allow_unused=True, create_graph=False)
    sq = 0.0
    for g in grads:
        if g is not None:
            sq += float(torch.sum(g * g).item())
    return sq ** 0.5


class FixedWeighting:
    def __init__(self, weights: Dict[str, float]):
        self.weights = dict(weights)

    def update(self, model, loss_terms: Dict[str, torch.Tensor]) -> Dict[str, float]:
        return self.weights


class LRAWeighting:
    """Bounded, symmetric gradient-norm LRA (M2). See module docstring."""

    def __init__(self, weights: Dict[str, float], alpha: float = 0.9,
                 cap_lo: float = 1e-2, cap_hi: float = 1e2):
        self.weights = dict(weights)
        self.initial_weights = dict(weights)
        self.alpha = alpha
        self.cap_lo = cap_lo
        self.cap_hi = cap_hi

    def update(self, model, loss_terms: Dict[str, torch.Tensor]) -> Dict[str, float]:
        params = [p for p in model.parameters() if p.requires_grad]
        norms = {name: _grad_norm(loss, params) for name, loss in loss_terms.items()}
        total = sum(norms.values())
        if total <= 0:
            return self.weights
        for name in loss_terms:
            n_i = max(norms[name], 1e-12)
            lambda_hat = total / n_i
            old = self.weights.get(name, self.initial_weights.get(name, 1.0))
            new = self.alpha * old + (1.0 - self.alpha) * lambda_hat
            lo = self.cap_lo * self.initial_weights.get(name, 1.0)
            hi = self.cap_hi * self.initial_weights.get(name, 1.0)
            self.weights[name] = float(min(max(new, lo), hi))
        return self.weights


def build_weighting(mode: str, weights: Dict[str, float], alpha: float = 0.9,
                     cap_lo: float = 1e-2, cap_hi: float = 1e2):
    if mode == "lra":
        return LRAWeighting(weights, alpha=alpha, cap_lo=cap_lo, cap_hi=cap_hi)
    return FixedWeighting(weights)
