"""Scenario PDs (Module 4): CO-3 multiplier, replay calibration, early performance (hand-built)."""

import numpy as np
import pandas as pd
import pytest

from ecl.lifetime.paths import Q0, MacroPath
from ecl.lifetime.portfolio import aalen_johansen, odds_scale, odds_scale_keep_prepay
from ecl.scenarios.early_performance import summarise, ttc_rate
from ecl.scenarios.overlay import multiplier, severity_scale, stressed
from ecl.scenarios.replay import Replay, aj_default, calibrate, cum_default
from ecl.scenarios.scenario_pd import segment_table


def _path(z: np.ndarray) -> MacroPath:
    n = len(z)
    return MacroPath("t", z, np.zeros(n), np.zeros(n), np.zeros((1, n)), ["AA"], z_s=z)


def test_severity_scale_zero_at_long_run_one_at_replay_trough_and_capped():
    assert severity_scale(-0.2, -0.2, -1.0) == 0.0
    assert severity_scale(-0.2, -1.0, -1.0) == 1.0
    assert severity_scale(-0.2, -0.6, -1.0) == pytest.approx(0.5)
    assert severity_scale(-0.2, -2.0, -1.0) == 1.0  # deeper than the crisis: no extrapolation
    assert severity_scale(-0.2, 0.3, -1.0) == 0.0  # benign downside: no uplift


def test_multiplier_only_in_stressed_quarters():
    p = _path(np.array([0.0, -0.5, -0.1, -0.9]))
    mask = stressed(p, Q0 + np.arange(4), z_lr=-0.2)
    assert mask.tolist() == [False, True, False, True]
    m = multiplier(np.tile(mask, (2, 1)), np.array([2.0, 3.0]), s=0.5)
    assert np.allclose(m[0], [1, 2**0.5, 1, 2**0.5]) and np.allclose(m[1], [1, 3**0.5, 1, 3**0.5])
    assert np.allclose(multiplier(mask[None], 2.0, 0.0), 1.0)  # s = 0: base and upside unchanged


def test_odds_multiplier_keeps_prepayment_and_hazards_below_one():
    h_d, h_p = np.array([0.02, 0.3, 0.6]), np.array([0.05, 0.6, 0.39])
    out = odds_scale_keep_prepay(h_d, h_p, 3.0)
    odds = lambda d: d / (1 - d - h_p)
    assert np.allclose(odds(out), 3 * odds(h_d))
    assert (out + h_p < 1).all()
    assert np.allclose(odds_scale_keep_prepay(h_d, h_p, 1.0), h_d)
    assert odds_scale(0.5, 3.0) == pytest.approx(0.75)


def test_weighted_aalen_johansen_matches_the_module3_estimator():
    rng = np.random.default_rng(1)
    nq = rng.integers(1, 25, 500)
    ev = rng.integers(0, 3, 500)
    ref = aalen_johansen(nq, ev, 20).actual_default.iloc[-1]
    assert aj_default(nq, ev, 20) == pytest.approx(ref)
    w = rng.integers(0, 3, 500).astype(float)  # bootstrap counts = repeating loans
    rep = np.repeat(np.arange(500), w.astype(int))
    assert aj_default(nq, ev, 20, w) == pytest.approx(aj_default(nq[rep], ev[rep], 20))


def test_calibration_recovers_a_known_multiplier():
    n, k, m_true = 4000, 8, 2.5
    h_d = np.full((n, k), 0.01)
    h_p = np.full((n, k), 0.02)
    mask = np.zeros((n, k), bool)
    mask[:, 4:] = True
    r = Replay(h_d, h_p, mask)
    # actual = the model with m_true: simulate exits quarter by quarter
    rng = np.random.default_rng(0)
    hd_t = odds_scale_keep_prepay(h_d, h_p, multiplier(mask, m_true, 1.0))
    u = rng.random((n, k))
    ev = np.where(u < hd_t, 1, np.where(u < hd_t + h_p, 2, 0))
    first = np.where((ev > 0).any(axis=1), (ev > 0).argmax(axis=1) + 1, k + 5)
    last = np.where(first <= k, ev[np.arange(n), np.minimum(first, k) - 1], 0)
    orig = pd.DataFrame({"n_quarters": first, "last_event": last})
    grid = np.exp(np.linspace(0, np.log(10), 300))
    c = calibrate(r, orig, np.arange(n), k, grid, n_boot=50, seed=1, level=0.9)
    assert c["lo"] < m_true < c["hi"]
    assert cum_default(r, c["m"])[:, -1].mean() == pytest.approx(
        aj_default(first, last, k), rel=1e-3
    )


def test_ttc_rate_inverts_the_vasicek_sum():
    from ecl.lifetime.cycle import vasicek_pd

    n, z = np.array([1000.0, 2000.0]), np.array([-1.0, 0.5])
    events = float(np.sum(n * vasicek_pd(0.01, z, 0.15)))
    assert ttc_rate(n, z, events, 0.15) == pytest.approx(0.01, rel=1e-6)
    assert ttc_rate(n, z, 0.0, 0.15) == 0.0


def test_co4_trigger_needs_ratio_and_minimum_events():
    cells = pd.DataFrame(
        {
            "vintage": [2024, 2024, 2025],
            "loan_age": [1, 7, 1],
            "q": [0, 0, 0],
            "n": [1000.0, 1000.0, 1000.0],
            "n_risk": [1000.0, 1000.0, 1000.0],
            "dpd30": [30.0, 10.0, 30.0],
            "dpd90": [0.0, 0.0, 0.0],
            "default": [25.0, 5.0, 25.0],
            "exp_dpd30": [20.0, 10.0, 30.0],
            "exp_dpd90": [0.0, 0.0, 0.0],
            "exp_default": [10.0, 1.0, 25.0],
        }
    )
    _, bands = summarise(cells, band_months=6, threshold=1.25, min_events=20)
    t = bands.set_index(["vintage", "age_band", "rate"]).trigger
    assert t[(2024, 0, "dpd30")] and t[(2024, 0, "default")]
    assert not t[(2024, 6, "default")]  # ratio 5 but only 5 events
    assert not t[(2025, 0, "default")]  # ratio 1


def test_segment_table_uplift_is_weighted_over_base():
    df = pd.DataFrame({"pd12_base": [0.01, 0.02], "pd12_weighted": [0.012, 0.03]})
    seg = pd.DataFrame({"region": ["a", "b"]})
    t = segment_table(df, seg, ["pd12_base", "pd12_weighted"]).set_index(["segment", "value"])
    assert t.loc[("all", "all"), "pd12_uplift_weighted_vs_base"] == pytest.approx(0.021 / 0.015)
    assert t.loc[("region", "b"), "pd12_uplift_weighted_vs_base"] == pytest.approx(1.5)
