"""Unit tests for ml/physics.py residuals.

Every test builds ONE combined leaf tensor `xyz` [N,3] (requires_grad=True)
and computes u,v,w,p from slices of THAT SAME tensor -- mirroring how the
real model consumes coordinates (it takes one combined xyz and internally
mixes its columns, e.g. via a Fourier-feature matmul) and how
physics.py's residual functions differentiate w.r.t. it. An earlier version
of this test (and of physics.py) used three independent x,y,z leaf tensors,
which passed in isolation but did not catch a real wiring bug: in the
actual training code, x/y/z were re-sliced from xyz *after* the model had
already consumed xyz directly, making them sibling (not ancestor) nodes of
the model's output in the autograd graph, so autograd.grad(output, x) would
not see the model's real dependency on x. Differentiating w.r.t. xyz
directly (as physics.py now does) and slicing the *result* sidesteps this.

1. continuity residual of a hand-crafted analytic divergence-free field
   (a curl of a vector potential -- div(curl A) == 0 identically) is ~0.
2. momentum residual of an exact NS solution (plane Poiseuille flow,
   laminar, nut=0) is small.
"""
import torch

from ml import physics


def test_continuity_residual_of_divergence_free_field_is_near_zero():
    torch.manual_seed(0)
    n = 2000
    xyz = (torch.rand(n, 3) * 4 - 2).requires_grad_(True)
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]

    # curl of A = (sin(y)*z, cos(x)*z, sin(x)*cos(y)) -- see test docstring;
    # analytically divergence-free for ANY smooth A.
    u = -torch.sin(x) * torch.sin(y) - torch.cos(x)
    v = torch.sin(y) - torch.cos(x) * torch.cos(y)
    w = -z * (torch.sin(x) + torch.cos(y))

    div = physics.continuity_residual(u, v, w, xyz)
    assert torch.max(torch.abs(div)).item() < 1e-5


def test_momentum_residual_of_plane_poiseuille_is_small():
    torch.manual_seed(0)
    n = 2000
    nu = 0.01
    umax = 1.0
    h = 1.0
    G = -2.0 * nu * umax / h ** 2  # dp/dx for the exact laminar solution

    xyz = torch.empty(n, 3)
    xyz[:, 0] = torch.rand(n) * 10 - 5
    xyz[:, 1] = torch.rand(n) * 2 * h - h
    xyz[:, 2] = torch.rand(n) * 4 - 2
    xyz.requires_grad_(True)
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]

    u = umax * (1.0 - (y / h) ** 2)
    v = torch.zeros_like(u)  # identically zero for this exact solution
    w = torch.zeros_like(u)
    p = G * x
    nut = torch.zeros_like(u)  # laminar: no turbulent viscosity

    rx, ry, rz = physics.momentum_residual(u, v, w, p, nut, xyz, nu=nu)
    assert torch.max(torch.abs(rx)).item() < 1e-3
    assert torch.max(torch.abs(ry)).item() < 1e-6
    assert torch.max(torch.abs(rz)).item() < 1e-6


def test_grad_wrt_freshly_sliced_coordinate_is_disconnected_from_model_like_output():
    """Regression test pinning down the wiring bug that motivated
    physics.py's xyz-based API (see module docstring): differentiating
    w.r.t. a coordinate re-sliced from xyz *independently* of how the
    output was actually computed does not work, because it is a sibling
    node in the graph, not an ancestor. This is why every function above
    takes the combined `xyz` tensor directly instead of separate x, y, z
    that a caller might re-slice on its own (as an earlier, buggy version
    of losses.py did).
    """
    xyz = torch.rand(10, 3, requires_grad=True)
    # 'out' depends on xyz only through a matmul mixing all columns (like
    # PINNMLP's Fourier layer, xyz @ B) -- not through any particular slice.
    W = torch.randn(3, 4)
    out = torch.tanh(xyz @ W).sum(dim=1)

    x_other = xyz[:, 0]  # a fresh, independent slice: a sibling, not an ancestor, of `out`
    raised = False
    try:
        torch.autograd.grad(out, x_other, grad_outputs=torch.ones_like(out), retain_graph=True)
    except RuntimeError:
        raised = True
    assert raised, "expected autograd to reject a coordinate that is not an ancestor of the output"

    # differentiating w.r.t. xyz itself (what physics.py actually does) works fine.
    g = torch.autograd.grad(out, xyz, grad_outputs=torch.ones_like(out), retain_graph=True)[0]
    assert g.shape == (10, 3)


def test_differentiable_sdf_feature_matches_finite_difference_and_detaching_breaks_it():
    """Review point (d): a model-like wrapper g(xyz) whose output depends on
    (x,y,z) partly through an engineered geometric feature sdf(x,y,z) (as
    PINNMLP's sdf/local_height inputs do). The correctly-chained residual
    must match a finite-difference divergence of the full black-box
    composite; detaching sdf from the graph (the bug found in review, fixed
    in ml/data.py's EpochSampler) breaks that match by exactly the dropped
    chain-rule term.
    """
    from ml import synthetic

    b = synthetic.Building(xc=0.0, yc=0.0, hx=10.0, hy=8.0, H=20.0)

    def g(xyz, detach_sdf):
        x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
        sdf = synthetic.torch_scene_sdf(x, y, z, [b])
        if detach_sdf:
            sdf = sdf.detach()
        u = torch.sin(x) + 0.5 * sdf
        v = torch.cos(y) - 0.3 * sdf
        w = 0.1 * z * sdf
        return u, v, w

    torch.manual_seed(0)
    n = 500
    xyz0 = torch.rand(n, 3) * 40 - 20
    xyz0[:, 2] = torch.rand(n) * 30  # z >= 0

    xyz = xyz0.clone().requires_grad_(True)
    u, v, w = g(xyz, detach_sdf=False)
    res_chained = physics.continuity_residual(u, v, w, xyz)

    # finite-difference divergence of the actual black-box composite (ground truth)
    h = 1e-4
    with torch.no_grad():
        def bump(dim):
            p = xyz0.clone(); p[:, dim] += h
            m = xyz0.clone(); m[:, dim] -= h
            return p, m
        xp, xm = bump(0); yp, ym = bump(1); zp, zm = bump(2)
        du_dx_fd = (g(xp, False)[0] - g(xm, False)[0]) / (2 * h)
        dv_dy_fd = (g(yp, False)[1] - g(ym, False)[1]) / (2 * h)
        dw_dz_fd = (g(zp, False)[2] - g(zm, False)[2]) / (2 * h)
    res_fd = du_dx_fd + dv_dy_fd + dw_dz_fd

    # Use a robust (99th percentile) statistic, not the strict max: the box
    # SDF has measure-zero kinks (edges/corners) where it is not actually
    # differentiable, so a handful of the 500 random points can land close
    # enough to one that the symmetric finite difference (which sees both
    # sides of the kink) and the analytic one-sided subgradient disagree by
    # more than a generic smooth-field tolerance would allow. Away from
    # those kinks (the vast majority of points) they agree tightly.
    err = torch.abs(res_chained - res_fd)
    assert torch.quantile(err, 0.99).item() < 5e-2
    assert torch.median(err).item() < 5e-3

    # detached: autograd silently drops d(u)/d(sdf) * d(sdf)/d(x,y,z)
    xyz2 = xyz0.clone().requires_grad_(True)
    u2, v2, w2 = g(xyz2, detach_sdf=True)
    res_detached = physics.continuity_residual(u2, v2, w2, xyz2)
    err_detached = torch.abs(res_detached - res_fd)
    assert torch.median(err_detached).item() > 0.1


def test_polygon_prism_geometry_matches_analytic_box_sdf():
    """M3(b) design review: PolygonPrismGeometry (arbitrary-footprint,
    log-sum-exp smooth-min over buildings) must reduce to the exact box SDF
    for a rectangular footprint, AND -- unlike GridGeometry -- must have
    smooth, finite, generally NON-zero second derivatives (the whole point
    of using an analytic smooth-min instead of a piecewise-linear grid)."""
    from ml import features, synthetic

    b0 = synthetic.Building(xc=-30.0, yc=-20.0, hx=15.0, hy=10.0, H=25.0)
    b1 = synthetic.Building(xc=25.0, yc=15.0, hx=12.5, hy=12.5, H=18.0)
    buildings = [b0, b1]

    def as_polygon(b):
        verts = [(b.xc - b.hx, b.yc - b.hy), (b.xc + b.hx, b.yc - b.hy),
                  (b.xc + b.hx, b.yc + b.hy), (b.xc - b.hx, b.yc + b.hy)]
        return (verts, b.H)

    poly_geo = features.PolygonPrismGeometry([as_polygon(b0), as_polygon(b1)], k_smooth=0.25)
    analytic = features.AnalyticBoxGeometry(buildings)

    torch.manual_seed(3)
    n = 1000
    x = torch.rand(n) * 160 - 80
    y = torch.rand(n) * 160 - 80
    z = torch.rand(n) * 55 + 0.5

    with torch.no_grad():
        sdf_a, h_a = analytic.sdf_and_height(x, y, z)
        sdf_p, h_p = poly_geo.sdf_and_height(x, y, z)

    err = torch.abs(sdf_a - sdf_p)
    # away from the smooth-min's own blending region (where two buildings'
    # sdf values are close), the small k_smooth makes this near-exact.
    assert torch.median(err).item() < 0.05
    assert torch.quantile(err, 0.95).item() < 1.0

    # smooth, non-zero, finite second derivatives (unlike a piecewise-linear
    # grid, which has zero-or-singular second derivatives almost everywhere)
    xyz = torch.stack([x, y, z], dim=1).requires_grad_(True)
    sdf, _ = poly_geo.sdf_and_height(xyz[:, 0], xyz[:, 1], xyz[:, 2])
    g = torch.autograd.grad(sdf.sum(), xyz, create_graph=True)[0]
    g2 = torch.autograd.grad(g[:, 0].sum(), xyz, create_graph=True)[0]
    assert torch.isfinite(g2).all()
    assert torch.max(torch.abs(g2)).item() > 1e-6  # not trivially/identically zero


def test_nested_sdf_grid_geometry_reads_real_geometry_output_if_present():
    """If the real geometry pipeline's output exists (M3), the loader must
    actually find and use it instead of silently falling back -- this is
    exactly the bug the design review caught (wrong assumed filename/keys).
    Skips if the geometry pipeline hasn't been run in this environment.
    """
    import os
    from ml import features

    # "var2" (not "base"/"var1" -- both of those names collide with
    # ml.synthetic's OWN smoke-test variants, which must keep taking
    # priority for synthetic cases; var2/var3 are real-geometry-only names)
    variant = "var2"
    scenario_dir = r"E:\PINN\v2\geometry\out\H_best"
    npz_path = os.path.join(scenario_dir, f"sdf_grid_{variant}.npz")
    h_path = os.path.join(scenario_dir, "height_raster_smooth_s5.npy")
    h_meta = os.path.join(scenario_dir, "height_raster_smooth_s5_meta.json")
    if not (os.path.exists(npz_path) and os.path.exists(h_path) and os.path.exists(h_meta)):
        import pytest
        pytest.skip("real geometry output not present in this environment")

    source = features.resolve_geometry_source(variant)
    assert isinstance(source, features.NestedSDFGridGeometry)

    x = torch.tensor([0.0, 50.0, -50.0])
    y = torch.tensor([0.0, 50.0, -50.0])
    z = torch.tensor([1.75, 1.75, 1.75])  # pedestrian layer
    sdf, h = source.sdf_and_height(x, y, z)
    assert torch.isfinite(sdf).all()
    assert torch.isfinite(h).all()
    assert (h >= 0).all()


def test_grid_geometry_matches_analytic_sdf_within_grid_resolution(tmp_path):
    """GridGeometry (the real-geometry integration point: a precomputed SDF
    volume + height raster queried with grid_sample) must agree with the
    exact AnalyticBoxGeometry it was built from, to within grid resolution.
    This is the test the geometry-grid loader is checked against before any
    real .npz from the geometry pipeline exists.
    """
    from ml import features, synthetic

    buildings = [synthetic.Building(xc=-30.0, yc=-20.0, hx=15.0, hy=10.0, H=25.0),
                 synthetic.Building(xc=25.0, yc=15.0, hx=12.5, hy=12.5, H=18.0)]

    spacing = 1.0
    bounds = ((-80.0, 80.0), (-80.0, 80.0), (0.0, 60.0))
    npz_path = tmp_path / "base_sdf.npz"
    features.GridGeometry.build_from_analytic(buildings, npz_path, bounds, spacing_m=spacing)

    analytic = features.AnalyticBoxGeometry(buildings)
    grid = features.GridGeometry(str(npz_path))

    torch.manual_seed(7)
    n = 2000
    x = torch.rand(n) * 150 - 75  # stay inside the grid bounds (with margin)
    y = torch.rand(n) * 150 - 75
    z = torch.rand(n) * 55 + 0.5

    with torch.no_grad():
        sdf_a, h_a = analytic.sdf_and_height(x, y, z)
        sdf_g, h_g = grid.sdf_and_height(x, y, z)

    sdf_err = torch.abs(sdf_a - sdf_g)
    h_err = torch.abs(h_a - h_g)
    # linear interpolation error is bounded by local curvature * spacing^2
    # away from kinks (box edges/corners), and by O(spacing) right at a kink;
    # a few grid spacings is a safe, documented tolerance for a 1 m grid.
    assert torch.median(sdf_err).item() < 0.5 * spacing
    assert torch.quantile(sdf_err, 0.95).item() < 3.0 * spacing
    assert torch.median(h_err).item() < 0.5 * spacing

    # and the grid source must remain differentiable w.r.t. (x,y,z)
    x2 = x.clone().requires_grad_(True)
    y2 = y.clone().requires_grad_(True)
    z2 = z.clone().requires_grad_(True)
    sdf_g2, _ = grid.sdf_and_height(x2, y2, z2)
    g = torch.autograd.grad(sdf_g2.sum(), [x2, y2, z2])
    assert all(torch.isfinite(gi).all() for gi in g)


def test_wall_normal_flux_zero_for_tangential_field():
    n = 500
    torch.manual_seed(1)
    nx = torch.zeros(n)
    ny = torch.zeros(n)
    nz = torch.ones(n)  # ground normal
    u = torch.randn(n)
    v = torch.randn(n)
    w = torch.zeros(n)  # tangential to the ground: no vertical component
    flux = physics.wall_normal_flux(u, v, w, nx, ny, nz)
    assert torch.max(torch.abs(flux)).item() < 1e-6
