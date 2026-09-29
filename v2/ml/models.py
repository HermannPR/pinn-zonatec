"""Models: the main hybrid-PINN MLP (P25=A) and the DeepONet comparator.

Both operate entirely in **non-dimensional** space (see config.py / the data
contract): coordinates are already divided by H_ref, and the six outputs
(u,v,w,p,k,nut) are the non-dimensional quantities the network is trained
to reproduce directly. Turning predictions back into physical units is a
simple multiply by (U_H, U_H, U_H, U_H^2, U_H^2, U_H*H_ref) done in data.py
/ metrics.py, not inside the model.

Note both models intentionally do *not* take U10 as an input (per P25=A);
the non-dimensionalisation by U_H(U10) is what lets the network generalise
across the held-out speed split. The DeepONet branch is the one exception
(spec explicitly includes U10/Uref in the branch net).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from .features import FourierFeatures, scale_sdf, scale_height

OUT_NAMES = ["u", "v", "w", "p", "k", "nut"]
POSITIVE_OUTPUTS = {"k", "nut"}
_SOFTPLUS_EPS = 1e-6


def _make_mlp(in_dim: int, hidden: List[int], out_dim: int, activation: str) -> nn.Sequential:
    act_cls = {"tanh": nn.Tanh, "relu": nn.ReLU, "gelu": nn.GELU, "silu": nn.SiLU}[activation]
    layers = []
    d = in_dim
    for h in hidden:
        layers.append(nn.Linear(d, h))
        layers.append(act_cls())
        d = h
    layers.append(nn.Linear(d, out_dim))
    return nn.Sequential(*layers)


def _split_outputs(raw: torch.Tensor) -> Dict[str, torch.Tensor]:
    out = {}
    for i, name in enumerate(OUT_NAMES):
        col = raw[..., i]
        if name in POSITIVE_OUTPUTS:
            col = F.softplus(col) + _SOFTPLUS_EPS
        out[name] = col
    return out


class PINNMLP(nn.Module):
    """Fourier-feature MLP, P25=A.

    Inputs (all passed separately so callers can set requires_grad on the
    coordinate tensors only, for autograd residuals):
      xyz        [N,3] non-dim coordinates (x,y,z)/H_ref
      sincos     [N,2] (sin theta, cos theta)
      variant_id [N]   long, index into the variant embedding table
      sdf        [N,1] signed distance to buildings, metres (raw; scaled internally)
      height     [N,1] local building height, metres (raw; scaled internally)
    """

    def __init__(self, num_variants: int, h_ref: float, num_fourier_bands: int = 8,
                 fourier_sigma: float = 4.0, variant_embedding_dim: int = 4,
                 hidden_layers: Optional[List[int]] = None, activation: str = "tanh"):
        super().__init__()
        hidden_layers = hidden_layers or [128, 128, 128, 128]
        self.h_ref = h_ref
        self.fourier = FourierFeatures(in_dim=3, num_bands=num_fourier_bands, sigma=fourier_sigma)
        self.variant_emb = nn.Embedding(num_variants, variant_embedding_dim)
        in_dim = self.fourier.out_dim + 2 + variant_embedding_dim + 1 + 1
        self.mlp = _make_mlp(in_dim, hidden_layers, len(OUT_NAMES), activation)

    def forward(self, xyz: torch.Tensor, sincos: torch.Tensor, variant_id: torch.Tensor,
                sdf: torch.Tensor, height: torch.Tensor) -> Dict[str, torch.Tensor]:
        ff = self.fourier(xyz)
        emb = self.variant_emb(variant_id)
        sdf_s = scale_sdf(sdf, self.h_ref).view(-1, 1)
        h_s = scale_height(height, self.h_ref).view(-1, 1)
        feat = torch.cat([ff, sincos, emb, sdf_s, h_s], dim=-1)
        raw = self.mlp(feat)
        return _split_outputs(raw)


class DeepONetPINN(nn.Module):
    """DeepONet comparator (spec): branch = (sin,cos theta, variant emb,
    U10/Uref); trunk = Fourier features of (x,y,z,sdf,local height). Shares
    the outputs and non-dimensionalisation of PINNMLP.
    """

    def __init__(self, num_variants: int, h_ref: float, latent_dim: int = 64,
                 num_fourier_bands: int = 8, fourier_sigma: float = 4.0,
                 variant_embedding_dim: int = 4, branch_hidden: Optional[List[int]] = None,
                 trunk_hidden: Optional[List[int]] = None, activation: str = "tanh"):
        super().__init__()
        branch_hidden = branch_hidden or [64, 64]
        trunk_hidden = trunk_hidden or [128, 128, 128]
        self.h_ref = h_ref
        self.latent_dim = latent_dim
        self.n_out = len(OUT_NAMES)

        self.variant_emb = nn.Embedding(num_variants, variant_embedding_dim)
        branch_in = 2 + variant_embedding_dim + 1  # sincos + variant + U10/Uref
        self.branch = _make_mlp(branch_in, branch_hidden, latent_dim * self.n_out, activation)

        self.fourier = FourierFeatures(in_dim=5, num_bands=num_fourier_bands, sigma=fourier_sigma)
        trunk_in = self.fourier.out_dim
        self.trunk = _make_mlp(trunk_in, trunk_hidden, latent_dim * self.n_out, activation)

    def forward(self, xyz: torch.Tensor, sincos: torch.Tensor, variant_id: torch.Tensor,
                sdf: torch.Tensor, height: torch.Tensor, u10_over_uref: torch.Tensor) -> Dict[str, torch.Tensor]:
        emb = self.variant_emb(variant_id)
        branch_in = torch.cat([sincos, emb, u10_over_uref.view(-1, 1)], dim=-1)
        b = self.branch(branch_in).view(-1, self.n_out, self.latent_dim)

        sdf_s = scale_sdf(sdf, self.h_ref).view(-1, 1)
        h_s = scale_height(height, self.h_ref).view(-1, 1)
        trunk_in_raw = torch.cat([xyz, sdf_s, h_s], dim=-1)
        t = self.trunk(self.fourier(trunk_in_raw)).view(-1, self.n_out, self.latent_dim)

        raw = (b * t).sum(dim=-1)  # [N, n_out]
        return _split_outputs(raw)
