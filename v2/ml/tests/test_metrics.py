import numpy as np

from ml import metrics


def test_vdi_hit_rate_toy_arrays():
    obs = np.array([10.0, 10.0, 10.0, 10.0, 0.1, 0.1])
    pred = np.array([
        10.2,   # abs err 0.2 <= W(0.5) -> hit
        12.6,   # abs err 2.6 > W(0.5); rel err 26% > D(0.25) -> not hit
        10.4,   # abs err 0.4 <= W(0.5) -> hit
        13.0,   # abs err 3.0 > W(0.5); rel err 30% > D(0.25) -> not hit
        0.11,   # abs err 0.01 <= W(0.5) -> hit
        0.5,    # abs err 0.4 <= W(0.5) -> hit (even though rel err = 400%)
    ])
    # W = 0.05 * u_ref, u_ref = 10 -> W = 0.5
    rate = metrics.vdi_hit_rate(pred, obs, D=0.25, u_ref=10.0)
    expected_hits = np.array([True, False, True, False, True, True])
    assert np.isclose(rate, expected_hits.mean())


def test_vdi_hit_rate_all_hit_when_identical():
    obs = np.random.default_rng(0).uniform(1, 20, size=100)
    pred = obs.copy()
    rate = metrics.vdi_hit_rate(pred, obs, D=0.25, u_ref=10.0)
    assert rate == 1.0


def test_relative_l2_zero_for_identical_arrays():
    a = np.random.default_rng(1).normal(size=200)
    assert metrics.relative_l2(a, a) == 0.0


def test_mae_speedup_factor_zero_for_identical_fields():
    rng = np.random.default_rng(2)
    u = rng.normal(size=100)
    v = rng.normal(size=100)
    w = rng.normal(size=100)
    mae = metrics.mae_speedup_factor(u, v, w, u, v, w, u10=8.0)
    assert mae == 0.0
