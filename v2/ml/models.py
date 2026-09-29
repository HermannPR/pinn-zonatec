"""Models: the main hybrid-PINN MLP (P25=A) and the DeepONet comparator.

Both operate entirely in **non-dimensional** space (see config.py / the data
contract): coordinates are already divided by H_ref, and the six outputs
(u,v,w,p,k,nut) are the non-dimensional quantities the network is trained
to reproduce directly. Turning predictions back into physical units is a
simple multiply by (U_H, U_H, U_H, U_H^2, U_H^2, U_H*H_ref) done in data.py
/ metrics.py, not inside the model.

Design review changes (M1, M4, M11, M13)
-------------------------------------------
* **M4 -- no variant embedding.** A held-out geometry variant gets an
  `nn.Embedding` row that never received a gradient (random init noise),
  so the "held-out variant" test was really testing an untrained lookup,
  not generalisation (smoke: rel_l2_v=15.7 on test-variant). Geometry now
  enters *only* through sdf / local_height, which are actually
  variant-aware and defined for a geometry the network has never seen.
  `PINNMLP` and `DeepONetPINN` no longer take a `variant_id` input at all.
* **M11 -- DeepONet branch has no U10.** Outputs are already
  non-dimensionalised by U_H(U10); making the branch a function of U10 too
  is a spurious, badly-extrapolating dependency (smoke: rel_l2_u=17 on
  test-speed). The branch is now just (sin theta, cos theta).
* **M1 -- nut is output-scaled.** `softplus(0) = 0.69`, so an untrained
  network starts with nut_nd ~ 0.7 -- one to two orders of magnitude above
  a physically plausible turbulent viscosity (nut_nd ~ 1e-2 to 1e-3 for
  Zona-Tec-like urban boundary layers). Combined with Fourier features
  amplifying second derivatives by ~(2*pi*sigma)^2, this alone explains why
  the momentum residual is huge (~1e4) before any training happens (see
  physics.py / weighting.py docstrings). `nut_scale` (default 0.01)
  multiplies softplus(raw) so the *initial* nut_nd is O(nut_scale), close
  to the physical scale, instead of O(1).
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


def _split_outputs(raw: torch.Tensor, positive_scale: Dict[str, float]) -> Dict[str, torch.Tensor]:
    out = {}
    for i, name in enumerate(OUT_NAMES):
        col = raw[..., i]
        if name in POSITIVE_OUTPUTS:
            col = positive_scale.get(name, 1.0) * F.softplus(col) + _SOFTPLUS_EPS
        out[name] = col
    return out


class PINNMLP(nn.Module):
    """Fourier-feature MLP, P25=A.

    Inputs:
      xyz    [N,3] non-dim coordinates (x,y,z)/H_ref
      sincos [N,2] (sin theta, cos theta)
      sdf    [N,1] signed distance to buildings, metres (raw; scaled internally)
      height [N,1] local building height, metres (raw; scaled internally)

    No variant_id/embedding (M4 -- see module docstring): geometry enters
    only through sdf/height, which generalise to an unseen variant.
    """

    def __init__(self, h_ref: float, num_fourier_bands: int = 8,
                 fourier_sigma: float = 4.0, hidden_layers: Optional[List[int]] = None,
                 activation: str = "tanh", sdf_wall_scale: float = 10.0,
                 nut_scale: float = 0.01, k_scale: float = 1.0,
                 num_variants: Optional[int] = None, variant_embedding_dim: Optional[int] = None):
        super().__init__()
        # num_variants / variant_embedding_dim accepted-and-ignored for
        # backward compatibility with older checkpoints/configs; no
        # embedding table is created (M4).
        hidden_layers = hidden_layers or [128, 128, 128, 128]
        self.h_ref = h_ref
        self.sdf_wall_scale = sdf_wall_scale
        self.positive_scale = {"k": k_scale, "nut": nut_scale}
        self.fourier = FourierFeatures(in_dim=3, num_bands=num_fourier_bands, sigma=fourier_sigma)
        in_dim = self.fourier.out_dim + 2 + 1 + 1
        self.mlp = _make_mlp(in_dim, hidden_layers, len(OUT_NAMES), activation)

    def forward(self, xyz: torch.Tensor, sincos: torch.Tensor,
                sdf: torch.Tensor, height: torch.Tensor,
                variant_id: Optional[torch.Tensor] = None) -> Dict[str, torch.Tensor]:
        # variant_id accepted-and-ignored (see __init__ note); kept so old
        # call sites that still pass it don't need special-casing.
        ff = self.fourier(xyz)
        sdf_s = scale_sdf(sdf, self.sdf_wall_scale).view(-1, 1)
        h_s = scale_height(height, self.h_ref).view(-1, 1)
        feat = torch.cat([ff, sincos, sdf_s, h_s], dim=-1)
        raw = self.mlp(feat)
        return _split_outputs(raw, self.positive_scale)


class DeepONetPINN(nn.Module):
    """DeepONet comparator: branch = (sin theta, cos theta) only (M4, M11 --
    see module docstring: no variant embedding, no U10); trunk = Fourier
    features of (x,y,z,sdf,local height). Shares the outputs and
    non-dimensionalisation of PINNMLP.
    """

    def __init__(self, h_ref: float, latent_dim: int = 64,
                 num_fourier_bands: int = 8, fourier_sigma: float = 4.0,
                 branch_hidden: Optional[List[int]] = None,
                 trunk_hidden: Optional[List[int]] = None, activation: str = "tanh",
                 sdf_wall_scale: float = 10.0, nut_scale: float = 0.01, k_scale: float = 1.0,
                 num_variants: Optional[int] = None, variant_embedding_dim: Optional[int] = None):
        super().__init__()
        branch_hidden = branch_hidden or [64, 64]
        trunk_hidden = trunk_hidden or [128, 128, 128]
        self.h_ref = h_ref
        self.sdf_wall_scale = sdf_wall_scale
        self.positive_scale = {"k": k_scale, "nut": nut_scale}
        self.latent_dim = latent_dim
        self.n_out = len(OUT_NAMES)

        branch_in = 2  # sincos only
        self.branch = _make_mlp(branch_in, branch_hidden, latent_dim * self.n_out, activation)

        self.fourier = FourierFeatures(in_dim=5, num_bands=num_fourier_bands, sigma=fourier_sigma)
        trunk_in = self.fourier.out_dim
        self.trunk = _make_mlp(trunk_in, trunk_hidden, latent_dim * self.n_out, activation)

    def forward(self, xyz: torch.Tensor, sincos: torch.Tensor,
                sdf: torch.Tensor, height: torch.Tensor,
                variant_id: Optional[torch.Tensor] = None,
                u10_over_uref: Optional[torch.Tensor] = None) -> Dict[str, torch.Tensor]:
        # variant_id / u10_over_uref accepted-and-ignored (M4, M11 -- see
        # module docstring) so old call sites don't need special-casing.
        b = self.branch(sincos).view(-1, self.n_out, self.latent_dim)

        sdf_s = scale_sdf(sdf, self.sdf_wall_scale).view(-1, 1)
        h_s = scale_height(height, self.h_ref).view(-1, 1)
        trunk_in_raw = torch.cat([xyz, sdf_s, h_s], dim=-1)
        t = self.trunk(self.fourier(trunk_in_raw)).view(-1, self.n_out, self.latent_dim)

        raw = (b * t).sum(dim=-1)  # [N, n_out]
        return _split_outputs(raw, self.positive_scale)
