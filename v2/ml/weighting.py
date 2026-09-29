"""Adaptive loss weighting (P26=A): fixed weights, and the gradient-statistics
learning-rate annealing of Wang, Teng & Perdikaris (2021), "Understanding and
mitigating gradient flow pathologies in physics-informed neural networks".

LRA update (per-term, anchored on the data loss):
    lambda_hat_r = max_p |grad_p(L_data)| / mean_p |grad_p(L_r)|
    lambda_r <- alpha * lambda_r + (1 - alpha) * lambda_hat_r
"""
from __future__ import annotations

from typing import Dict, Iterable, List

import torch


def _flat_grad(loss: torch.Tensor, params: List[torch.nn.Parameter]) -> torch.Tensor:
    grads = torch.autograd.grad(loss, params, retain_graph=True, allow_unused=True, create_graph=False)
    flat = [g.reshape(-1) for g, p in zip(grads, params) if g is not None]
    if not flat:
        return torch.zeros(1)
    return torch.cat(flat)


class FixedWeighting:
    def __init__(self, weights: Dict[str, float]):
        self.weights = dict(weights)

    def update(self, model, loss_terms: Dict[str, torch.Tensor]) -> Dict[str, float]:
        return self.weights


class LRAWeighting:
    def __init__(self, weights: Dict[str, float], alpha: float = 0.9, anchor: str = "data"):
        self.weights = dict(weights)
        self.alpha = alpha
        self.anchor = anchor

    def update(self, model, loss_terms: Dict[str, torch.Tensor]) -> Dict[str, float]:
        if self.anchor not in loss_terms:
            return self.weights
        params = [p for p in model.parameters() if p.requires_grad]
        g_anchor = _flat_grad(loss_terms[self.anchor], params)
        max_anchor = torch.max(torch.abs(g_anchor)).item() if g_anchor.numel() else 0.0
        for name, loss in loss_terms.items():
            if name == self.anchor:
                continue
            g = _flat_grad(loss, params)
            mean_r = torch.mean(torch.abs(g)).item() if g.numel() else 1e-12
            mean_r = max(mean_r, 1e-12)
            lambda_hat = max_anchor / mean_r
            old = self.weights.get(name, 1.0)
            self.weights[name] = self.alpha * old + (1.0 - self.alpha) * lambda_hat
        return self.weights


def build_weighting(mode: str, weights: Dict[str, float], alpha: float = 0.9):
    if mode == "lra":
        return LRAWeighting(weights, alpha=alpha)
    return FixedWeighting(weights)
