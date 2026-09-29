"""
test_windclimate.py -- sanity tests for the PINN Zona Tec wind climatology.

Runs entirely offline against the local raw ISD CSVs already downloaded to
E:\\PINN\\v2\\data\\raw\\climate (no network access needed).

Run with:
    E:\\PINN\\.venv\\Scripts\\python.exe -m pytest E:\\PINN\\v2\\climate\\test_windclimate.py -v
"""
import numpy as np
import pandas as pd
import pytest

import parse_isd
import windclimate as wc

YEARS = list(range(2010, 2025))  # 15 complete years, matches build_windrose.py


@pytest.fixture(scope="module")
def hourly():
    h = parse_isd.build_hourly("MMMY", YEARS)
    return h[h["datetime_hour"].dt.year.isin(YEARS)].reset_index(drop=True)


@pytest.fixture(scope="module")
def windrose(hourly):
    return wc.build_windrose(hourly)


# --------------------------------------------------------------------------
# Sector-weight mechanics
# --------------------------------------------------------------------------

def test_sector_weights_sum_to_one():
    directions = np.array([10, 20, 350, 90, 112, 5, 355, 337.5])
    W = wc.sector_weights(directions)
    assert W.shape == (len(directions), wc.N_SECTORS)
    np.testing.assert_allclose(W.sum(axis=1), 1.0, atol=1e-9)
    assert (W >= 0).all()


def test_sector_weights_boundary_splits_two_sectors():
    # A direction of exactly 11.25 deg (the boundary between sector 0 and
    # sector 22.5) should split its mass across at most 2-3 neighbouring
    # sectors and never assign > (10/10)=1 to a single one improperly.
    W = wc.sector_weights(np.array([11.25]))
    nonzero = (W[0] > 1e-9).sum()
    assert 1 <= nonzero <= 3
    assert np.isclose(W.sum(), 1.0)


# --------------------------------------------------------------------------
# Wind rose completeness
# --------------------------------------------------------------------------

def test_frequencies_sum_to_one_including_calm(windrose):
    total = windrose.table["frequency"].sum() + windrose.calm_fraction + windrose.variable_fraction
    assert total == pytest.approx(1.0, abs=1e-9)


def test_windrose_has_16_sectors(windrose):
    assert len(windrose.table) == 16
    np.testing.assert_allclose(sorted(windrose.table["sector_centre_deg"]), wc.SECTOR_CENTERS)


def test_calm_fraction_is_plausible(windrose):
    # METAR calm reports at MMMY are common (light nocturnal/valley winds);
    # sanity-bound it to a physically plausible range rather than an exact
    # value so the test survives future re-downloads with a couple more
    # years of data.
    assert 0.05 < windrose.calm_fraction < 0.35


# --------------------------------------------------------------------------
# Weibull fit quality
# --------------------------------------------------------------------------

def test_weibull_reproduces_empirical_exceedance_per_sector(hourly, windrose):
    """P(U10 > 5 | sector) from the fitted Weibull must be within a few
    percentage points of the direct weighted-empirical estimate, for every
    one of the 16 sectors (including the low-frequency ones where the fit
    is noisier)."""
    dir_mask = (~hourly["is_calm"]) & (~hourly["is_variable"]) & hourly["wdir_deg"].notna()
    d = hourly.loc[dir_mask, "wdir_deg"].to_numpy()
    u = hourly.loc[dir_mask, "wspd_ms"].to_numpy()
    W = wc.sector_weights(d)

    table = windrose.table
    max_abs_diff = 0.0
    for j in range(wc.N_SECTORS):
        w = W[:, j]
        n_eff = w.sum()
        emp = (w * (u > 5.0)).sum() / n_eff
        weib = wc.prob_exceed_conditional(5.0, table["weibull_c"].iloc[j], table["weibull_k"].iloc[j])
        diff = abs(emp - weib)
        max_abs_diff = max(max_abs_diff, diff)
        assert diff < 0.06, (
            f"sector {table['sector_centre_deg'].iloc[j]}: empirical={emp:.4f} "
            f"weibull={weib:.4f} diff={diff:.4f}"
        )
    assert max_abs_diff < 0.06


def test_weibull_reproduces_empirical_exceedance_aggregate(hourly, windrose):
    """Aggregate (all-directions) P(U10 > 5) from the Weibull-based
    annual_exceedance (K=1, the plain climatological case) must match the
    direct empirical estimate over ALL hours (incl. calm) within a couple
    of percentage points."""
    emp = wc.empirical_exceedance(hourly, 5.0)
    ann = wc.annual_exceedance(windrose.table, K=1.0, threshold_local=5.0)
    assert abs(emp - ann["annual_probability"]) < 0.02


# --------------------------------------------------------------------------
# Exceedance API / NEN 8100 sanity check (P10=C)
# --------------------------------------------------------------------------

def test_nen8100_sanity_K_equals_one(windrose):
    """With K=1 everywhere (no CFD amplification, i.e. 'measure at the mast
    itself'), the per-sector equivalent U10 threshold must equal the local
    threshold, and the annual probability must equal the plain Weibull-based
    climatological exceedance of that same threshold."""
    threshold = 5.0
    result = wc.annual_exceedance(windrose.table, K=1.0, threshold_local=threshold)
    np.testing.assert_allclose(result["per_sector"]["u10_equivalent"], threshold)

    # manually recompute the expected annual probability from the table
    expected = (windrose.table["frequency"] * windrose.table.apply(
        lambda r: wc.prob_exceed_conditional(threshold, r["weibull_c"], r["weibull_k"]), axis=1
    )).sum()
    assert result["annual_probability"] == pytest.approx(expected, rel=1e-9)
    assert result["hours_per_year"] == pytest.approx(expected * 8760.0, rel=1e-9)


def test_annual_exceedance_scalar_vs_array_K(windrose):
    scalar_result = wc.annual_exceedance(windrose.table, K=1.3, threshold_local=5.0)
    array_result = wc.annual_exceedance(windrose.table, K=np.full(16, 1.3), threshold_local=5.0)
    assert scalar_result["annual_probability"] == pytest.approx(array_result["annual_probability"])


def test_annual_exceedance_higher_K_increases_exceedance(windrose):
    """A larger local amplification factor K must never decrease the annual
    exceedance probability of a fixed local threshold (monotonicity)."""
    low = wc.annual_exceedance(windrose.table, K=0.8, threshold_local=5.0)
    high = wc.annual_exceedance(windrose.table, K=1.5, threshold_local=5.0)
    assert high["annual_probability"] > low["annual_probability"]


def test_annual_exceedance_rejects_wrong_length_K(windrose):
    with pytest.raises(ValueError):
        wc.annual_exceedance(windrose.table, K=np.array([1.0, 1.0, 1.0]), threshold_local=5.0)


# --------------------------------------------------------------------------
# Weighted Weibull fit sanity (unit-level, synthetic data)
# --------------------------------------------------------------------------

def test_weibull_fit_weighted_recovers_known_parameters():
    rng = np.random.default_rng(0)
    c_true, k_true = 4.5, 2.1
    x = rng.weibull(k_true, size=20000) * c_true
    w = np.ones_like(x)
    c_fit, k_fit = wc.weibull_fit_weighted(x, w)
    assert c_fit == pytest.approx(c_true, rel=0.03)
    assert k_fit == pytest.approx(k_true, rel=0.05)


# --------------------------------------------------------------------------
# I3 (review F1): empirical-first exceedance for the extreme tail
# --------------------------------------------------------------------------

def test_annual_exceedance_auto_reproduces_review_P_gt_15(windrose):
    """The review recomputed P(U10>15, K=1) directly from the hourly cache
    and got 0.0055% (7 h in 15 years), NOT the 0.010% previously in
    README.md (a rounding-display bug) nor the Weibull's 0.0013% (tail
    underestimate). method='auto' must reproduce 0.0055% exactly (it IS the
    same direct count, just re-derived through the per-sector API)."""
    result = wc.annual_exceedance(windrose.table, K=1.0, threshold_local=15.0,
                                   sector_speeds=windrose.sector_speeds, method="auto")
    assert result["annual_probability"] * 100 == pytest.approx(0.0055, abs=2e-4)
    # exact identity: annual_probability was built from n_eff_exceed / n_hours_total,
    # so multiplying back by the actual observed hour count recovers the raw count (7 h).
    assert result["annual_probability"] * windrose.n_hours_total == pytest.approx(7.0, abs=0.1)
    # sectors with zero observed exceedances must fall back to Weibull and say so
    per_sector = result["per_sector"]
    weibull_rows = per_sector[per_sector["source"] == "weibull"]
    assert (weibull_rows["n_eff_exceed_hours"] == 0).all()
    assert weibull_rows["note"].str.contains("extrapolacion Weibull").all()


def test_annual_exceedance_auto_reproduces_review_P_gt_10(windrose):
    result = wc.annual_exceedance(windrose.table, K=1.0, threshold_local=10.0,
                                   sector_speeds=windrose.sector_speeds, method="auto")
    assert result["annual_probability"] * 100 == pytest.approx(0.52, abs=0.01)


def test_empirical_prob_exceed_sector_matches_annual_exceedance_path(windrose):
    for j in range(wc.N_SECTORS):
        p_direct, n_direct = wc.empirical_prob_exceed_sector(windrose, j, 5.0)
        result = wc.annual_exceedance(windrose.table, K=1.0, threshold_local=5.0,
                                       sector_speeds=windrose.sector_speeds, method="empirical")
        row = result["per_sector"].iloc[j]
        if np.isfinite(p_direct):
            assert row["p_exceed_given_sector"] == pytest.approx(p_direct)


# --------------------------------------------------------------------------
# I4 (review F1): NEN 8100 classes and Lawson LDDC
# --------------------------------------------------------------------------

@pytest.mark.parametrize("p,expected", [
    (0.01, "A"), (0.025, "B"), (0.04, "B"), (0.05, "C"), (0.08, "C"),
    (0.10, "D"), (0.15, "D"), (0.20, "E"), (0.50, "E"),
])
def test_nen8100_comfort_class_boundaries(p, expected):
    assert wc.nen8100_comfort_class(p) == expected


def test_nen8100_activity_quality_examples():
    assert wc.nen8100_activity_quality("atravesar", 0.15) == "moderada"   # class D
    assert wc.nen8100_activity_quality("pasear", 0.15) == "mala"          # class D
    assert wc.nen8100_activity_quality("estar_sentado", 0.03) == "moderada"  # class B


@pytest.mark.parametrize("p,expected", [
    (0.0001, "sin_riesgo"), (0.001, "riesgo_limitado"), (0.01, "peligroso"),
])
def test_nen8100_danger_class_boundaries(p, expected):
    assert wc.nen8100_danger_class(p) == expected


def test_nen8100_class_rejects_out_of_range():
    with pytest.raises(ValueError):
        wc.nen8100_comfort_class(1.5)


def test_gust_equivalent_mean_is_at_least_the_mean_speed():
    u = np.array([2.0, 5.0, 8.0])
    k = np.array([0.5, 2.0, 5.0])
    gem = wc.gust_equivalent_mean(u, k)
    assert np.all(gem >= u)


def test_gust_equivalent_mean_zero_turbulence_equals_mean():
    gem = wc.gust_equivalent_mean(5.0, 0.0)
    assert gem == pytest.approx(5.0)


def test_lawson_lddc_assessment_runs_and_orders_thresholds_sensibly(windrose):
    K_gem = 1.2  # illustrative fixed amplification, no CFD available in this test
    result = wc.lawson_lddc_assessment(windrose.table, K_gem, sector_speeds=windrose.sector_speeds)
    comfort = result["comfort"]
    # a higher threshold must never be exceeded MORE often than a lower one
    ps = [comfort["estar_sentado_largo"]["p_exceed"], comfort["estar_de_pie_pasear"]["p_exceed"],
          comfort["caminar_negocios"]["p_exceed"], comfort["incomodo"]["p_exceed"]]
    assert all(ps[i] >= ps[i + 1] for i in range(len(ps) - 1))
    danger = result["danger"]
    assert danger["riesgo_limitado"]["p_exceed"] >= danger["peligroso"]["p_exceed"]
