"""Physics residuals for the hybrid PINN (P23 stages B/C).

Pressure convention (documented per the task's binding instructions)
----------------------------------------------------------------------
OpenFOAM's `simpleFoam` solves for **kinematic** pressure p = p_static/rho,
and its momentum equation is written with the *effective* (molecular +
turbulent) stress computed from the *whole* pressure field, i.e. p as
written by simpleFoam does **not** have 2/3*k explicitly subtracted out
anywhere in the files we read: the 2/3*k term is implicitly absorbed into
that single scalar p (this is the standard incompressible RANS practice:
one solves for a "modified pressure" P = p + 2/3 k and just calls it p).

We keep that convention throughout this codebase:
  * `p` in the HDF5 files and in all losses/metrics is exactly the
    simpleFoam field, i.e. the modified/effective kinematic pressure.
  * The momentum residual below is therefore written as

        (u . grad) u + grad(p) - div[ (nu + nut) (grad u + grad u^T) ] = 0

    with NO separate 2/3*k term, because that term is already inside p.
    `PhysicsConfig.pressure_includes_two_thirds_k = False` documents this
    choice explicitly (see config.py); if a future dataset instead provides
    a "true" static pressure with 2/3 k split out, flip that flag and add
    `+ (2/3) * grad(k)` to the residual -- the code path is marked below.

Differentiate w.r.t. the ACTUAL tensor the model consumed (bug found in
review)
----------------------------------------------------------------------------
Every function here takes the coordinate input as one combined `xyz`
tensor, shape [N,3], requires_grad=True, and internally calls
`torch.autograd.grad(output, xyz)` to get the full per-row Jacobian
[N,3] = [d(output)/dx, d(output)/dy, d(output)/dz] in a single call, then
slices columns out of the *result*.

This matters more than it looks: an earlier version took separate `x, y,
z` tensors and expected callers to pass in `xyz[:, 0]`, `xyz[:, 1]`,
`xyz[:, 2]` sliced *outside* this module. But the model consumes `xyz`
directly (e.g. its Fourier-feature layer computes `xyz @ B`), so a
freshly-sliced `x = xyz[:, 0]` is a *sibling* node of that computation in
the autograd graph, not an ancestor of the model's output -- PyTorch's
autograd walks backward from the output through the edges it actually
used, never reaches the unrelated `x` node, and `torch.autograd.grad`
either raises ("not used in the graph") or (with allow_unused=True)
silently returns None/zero. Differentiating w.r.t. the exact `xyz` object
that was actually fed to the model side-steps this entirely, and is also
required for the network's `sdf`/`local_height` input features to
contribute their (physically real) chain-rule term correctly -- see
ml/data.py's `EpochSampler._differentiable_geometry` docstring, which
computes those features FROM the same leaf `xyz` for exactly this reason.

Everything here uses torch.autograd.grad on a *forward* pass of the model
(xyz must be a leaf tensor, or at least a non-leaf with requires_grad=True,
that the model's forward pass actually consumed). All residual math is
done in float32 with autocast disabled (P26): mixed precision is only
used, if at all, on the plain data-loss forward passes, never here.
"""
from __future__ import annotations

from typing import Tuple

import torch


def _grad_wrt_xyz(y: torch.Tensor, xyz: torch.Tensor) -> torch.Tensor:
    """d(y)/d(xyz) for scalar-per-row y (shape [N]), xyz shape [N,3].
    Returns [N,3] = [dy/dx, dy/dy_coord, dy/dz] per row. One autograd call
    gives all three spatial partials at once (cheaper and, importantly,
    correct -- see module docstring).

    Handles the edge case where `y`'s true derivative w.r.t. (x,y,z) is a
    hard mathematical constant (most commonly exactly 0) rather than a
    further function of position -- e.g. a second derivative of an exactly
    linear (or exactly constant) intermediate quantity. In that case
    PyTorch's autograd correctly builds no further graph for it (there is
    nothing left to differentiate: the second derivative of a constant
    really is 0 everywhere), so `y.requires_grad` can be False even though
    `y` came from a computation that did, upstream, depend on `xyz`. Without
    this check `torch.autograd.grad` would raise ("does not require grad
    and does not have a grad_fn") on what is actually a perfectly valid
    zero -- this surfaced in ml/tests/test_physics.py's plane-Poiseuille
    exact solution, where v = w = 0 identically, making some second
    derivatives (e.g. d^2v/dy^2) hard zeros. This is a real property of the
    physics (not just that test): any output component that is locally
    exactly linear in some coordinate hits this. A trained network's
    outputs are nonlinear almost everywhere, but momentum_residual must not
    crash on the few points, or the toy fields, where it isn't.
    """
    if not y.requires_grad:
        return torch.zeros_like(xyz)
    ones = torch.ones_like(y)
    g = torch.autograd.grad(y, xyz, grad_outputs=ones, create_graph=True,
                             retain_graph=True, allow_unused=True)[0]
    if g is None:
        return torch.zeros_like(xyz)
    return g


def continuity_residual(u: torch.Tensor, v: torch.Tensor, w: torch.Tensor,
                         xyz: torch.Tensor) -> torch.Tensor:
    """div(u) = du/dx + dv/dy + dw/dz, evaluated pointwise via autograd.

    xyz [N,3] must be the same (requires_grad=True) tensor that was used to
    compute u, v, w.
    """
    du = _grad_wrt_xyz(u, xyz)
    dv = _grad_wrt_xyz(v, xyz)
    dw = _grad_wrt_xyz(w, xyz)
    return du[:, 0] + dv[:, 1] + dw[:, 2]


def momentum_residual(u: torch.Tensor, v: torch.Tensor, w: torch.Tensor, p: torch.Tensor,
                       nut: torch.Tensor, xyz: torch.Tensor,
                       nu: float, pressure_includes_two_thirds_k: bool = False,
                       k: torch.Tensor = None) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Steady RANS momentum residual, nut supervised (not solved for).

        (u.grad)u + grad p - div[(nu+nut)(grad u + grad u^T)] = 0

    Returns the three (x,y,z) component residuals, each shape [N].
    """
    du = _grad_wrt_xyz(u, xyz)  # columns: [du/dx, du/dy, du/dz]
    dv = _grad_wrt_xyz(v, xyz)
    dw = _grad_wrt_xyz(w, xyz)
    du_dx, du_dy, du_dz = du[:, 0], du[:, 1], du[:, 2]
    dv_dx, dv_dy, dv_dz = dv[:, 0], dv[:, 1], dv[:, 2]
    dw_dx, dw_dy, dw_dz = dw[:, 0], dw[:, 1], dw[:, 2]

    conv_u = u * du_dx + v * du_dy + w * du_dz
    conv_v = u * dv_dx + v * dv_dy + w * dv_dz
    conv_w = u * dw_dx + v * dw_dy + w * dw_dz

    dp = _grad_wrt_xyz(p, xyz)
    dp_dx, dp_dy, dp_dz = dp[:, 0], dp[:, 1], dp[:, 2]

    nu_eff = nu + nut

    # tau_ij = nu_eff * (du_i/dx_j + du_j/dx_i); need div_j(tau_ij) for i=x,y,z
    tau_xx = nu_eff * 2.0 * du_dx
    tau_xy = nu_eff * (du_dy + dv_dx)
    tau_xz = nu_eff * (du_dz + dw_dx)
    tau_yy = nu_eff * 2.0 * dv_dy
    tau_yz = nu_eff * (dv_dz + dw_dy)
    tau_zz = nu_eff * 2.0 * dw_dz

    g_xx = _grad_wrt_xyz(tau_xx, xyz)
    g_xy = _grad_wrt_xyz(tau_xy, xyz)
    g_xz = _grad_wrt_xyz(tau_xz, xyz)
    g_yy = _grad_wrt_xyz(tau_yy, xyz)
    g_yz = _grad_wrt_xyz(tau_yz, xyz)
    g_zz = _grad_wrt_xyz(tau_zz, xyz)

    div_tau_x = g_xx[:, 0] + g_xy[:, 1] + g_xz[:, 2]
    div_tau_y = g_xy[:, 0] + g_yy[:, 1] + g_yz[:, 2]
    div_tau_z = g_xz[:, 0] + g_yz[:, 1] + g_zz[:, 2]

    res_x = conv_u + dp_dx - div_tau_x
    res_y = conv_v + dp_dy - div_tau_y
    res_z = conv_w + dp_dz - div_tau_z

    if pressure_includes_two_thirds_k:
        if k is None:
            raise ValueError("k is required when pressure_includes_two_thirds_k=True")
        dk = _grad_wrt_xyz(k, xyz)
        res_x = res_x + (2.0 / 3.0) * dk[:, 0]
        res_y = res_y + (2.0 / 3.0) * dk[:, 1]
        res_z = res_z + (2.0 / 3.0) * dk[:, 2]

    return res_x, res_y, res_z


def wall_normal_flux(u: torch.Tensor, v: torch.Tensor, w: torch.Tensor,
                      nx: torch.Tensor, ny: torch.Tensor, nz: torch.Tensor) -> torch.Tensor:
    """u . n at wall-face points (impermeability, P24=B: u.n=0, no no-slip)."""
    return u * nx + v * ny + w * nz
