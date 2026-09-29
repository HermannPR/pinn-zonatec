"""Unit tests for ml/baselines.py.

Uses the actual synthetic generator (no torch needed) since its velocity
field is, by construction, exactly self-similar in U10 (u_star scales
linearly with U10, and every field is a function of u_star and geometry
only) -- this makes it a strong, exact check for the speed-rescaling
baseline: rescaling case A's field by (U_H_B / U_H_A) should reproduce case
B's own field almost exactly, at the same points.
"""
import numpy as np

from ml import baselines


class _FakeCase:
    """Minimal stand-in for ml.data.CaseData: only the attributes
    _rescale_by_speed actually reads."""

    def __init__(self, arrays, u_h, h_ref):
        self.arrays = arrays
        self.u_h = u_h
        self.h_ref = h_ref


def test_rescale_by_speed_matches_true_self_similar_field():
    from ml import synthetic

    buildings = synthetic.VARIANTS["base"]
    theta = 45.0
    rng = np.random.default_rng(0)
    n = 500
    x = rng.uniform(-90, 90, n)
    y = rng.uniform(-90, 90, n)
    z = rng.uniform(0.5, 55, n)
    sdf = synthetic.scene_sdf(x, y, z, buildings)
    mask = sdf > 0.5
    x, y, z = x[mask], y[mask], z[mask]

    u_star_a = synthetic.u_star_from_u10(4.0)
    u_star_b = synthetic.u_star_from_u10(12.0)
    ua, va, wa = synthetic.velocity_field(x, y, z, theta, u_star_a, buildings)
    ub, vb, wb = synthetic.velocity_field(x, y, z, theta, u_star_b, buildings)
    pa = synthetic.pressure_field(ua, va, wa, z, u_star_a)
    pb = synthetic.pressure_field(ub, vb, wb, z, u_star_b)

    h_ref = synthetic.H_REF
    u_h_a = float(synthetic.log_law(np.array(h_ref), u_star_a))
    u_h_b = float(synthetic.log_law(np.array(h_ref), u_star_b))

    src = _FakeCase({"u": ua, "v": va, "w": wa, "p": pa,
                      "k": np.zeros_like(ua), "nut": np.zeros_like(ua)}, u_h_a, h_ref)
    tgt = _FakeCase({}, u_h_b, h_ref)

    rescaled = baselines._rescale_by_speed(src, tgt, src.arrays)

    assert np.allclose(rescaled["u"], ub, atol=1e-4, rtol=1e-3)
    assert np.allclose(rescaled["v"], vb, atol=1e-4, rtol=1e-3)
    assert np.allclose(rescaled["w"], wb, atol=1e-4, rtol=1e-3)
    assert np.allclose(rescaled["p"], pb, atol=1e-3, rtol=1e-3)


def test_rescale_by_speed_is_identity_when_speeds_match():
    src = _FakeCase({"u": np.array([1.0, 2.0]), "v": np.array([0.5, -0.5]),
                      "w": np.array([0.0, 0.1]), "p": np.array([0.1, 0.2]),
                      "k": np.array([0.01, 0.02]), "nut": np.array([0.001, 0.002])},
                     u_h=5.0, h_ref=25.0)
    tgt = _FakeCase({}, u_h=5.0, h_ref=25.0)
    out = baselines._rescale_by_speed(src, tgt, src.arrays)
    for f in baselines.FIELDS:
        assert np.allclose(out[f], src.arrays[f])
