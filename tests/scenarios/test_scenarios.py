"""Module 4 scenario machinery: hand-built examples (methodology: docs/methodology/scenarios.md)."""

import numpy as np
import pandas as pd
import pytest

from ecl.scenarios.build import extend, partition, severity, yoy_paths
from ecl.scenarios.severity import percentile_of, plausibility
from ecl.scenarios.state_paths import fit_betas, project_states
from ecl.scenarios.table5 import INDICATORS, indicator_values
from ecl.scenarios.var import (
    VAR,
    VAR_VARS,
    conditional_forecast,
    fit_var,
    forecast,
    simulate_deviations,
)

IDX = pd.period_range("1500Q1", periods=2000, freq="Q")
BANDS = {"downside": (5, 20), "upside": (80, 95)}


def _var_series(a1: np.ndarray, n: int = 2000, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    y = np.zeros((n, 4))
    for t in range(1, n):
        y[t] = 0.1 + a1 @ y[t - 1] + rng.normal(0, 1, 4)
    return pd.DataFrame(y, index=IDX[:n], columns=VAR_VARS)


def test_var_recovers_known_coefficients():
    a1 = np.diag([0.5, 0.3, -0.2, 0.4])
    v = fit_var(_var_series(a1), "1501Q1", "1999Q4", p=1)
    assert np.allclose(v.A[0], a1, atol=0.1)  # sampling error ~0.03-0.09
    assert v.max_abs_eigenvalue() < 1


def test_var_excludes_quarters_and_their_lags():
    d = _var_series(np.diag([0.5] * 4))
    v_all = fit_var(d, "1501Q1", "1599Q4", p=2)
    v_ex = fit_var(d, "1501Q1", "1599Q4", exclude=["1590Q1"], p=2)
    assert len(v_all.index) - len(v_ex.index) == 3  # 1990Q1 and the 2 quarters using it
    assert not v_ex.index.isin(pd.PeriodIndex(["1590Q1", "1590Q2", "1590Q3"], freq="Q")).any()


def _toy_var() -> VAR:
    sigma = np.array([[1.0, 0.5, 0, 0], [0.5, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]])
    return VAR(
        VAR_VARS,
        np.zeros(4),
        np.array([np.diag([0.5, 0.5, 0.5, 0.5])]),
        sigma,
        np.random.default_rng(0).normal(size=(200, 4)),
        IDX[:200],
    )


def test_conditional_forecast_hits_fixed_paths_and_moves_correlated_variable():
    v = _toy_var()
    hist = np.zeros((1, 4))
    target = np.full(3, 2.0)
    out = conditional_forecast(
        v, hist, 3, {"gdp_g": target, "d_mort": np.zeros(3), "d_unrate": np.zeros(3)}
    )
    assert np.allclose(out[:, 1], target)
    assert (out[:, 0] > 0).all()  # hpi shock correlated +0.5 with gdp
    assert np.allclose(conditional_forecast(v, hist, 3, {}), forecast(v, hist, 3))


def test_simulated_deviations_have_mean_near_zero_and_follow_dynamics():
    v = _toy_var()
    d = simulate_deviations(v, 12, 20_000, np.random.default_rng(3), block=4)
    assert d.shape == (20_000, 12, 4)
    assert np.abs(d.mean(axis=0)).max() < 0.05


def test_partition_weights_and_unbiasedness():
    rng = np.random.default_rng(5)
    paths = rng.normal(size=(1000, 12, 4))
    sev = paths[:, :, 0].mean(axis=1)
    p = partition(paths, sev, (0.2, 0.6, 0.2))
    assert [p[k]["n"] for k in ["downside", "central", "upside"]] == [200, 600, 200]
    weighted = sum(p[k]["weight"] * p[k]["path"] for k in p)
    assert np.allclose(weighted, paths.mean(axis=0))  # unbiased by construction
    assert p["downside"]["severity"] < p["central"]["severity"] < p["upside"]["severity"]


def _hist() -> pd.DataFrame:
    idx = pd.period_range("2020Q1", "2025Q4", freq="Q")
    return pd.DataFrame(
        {
            "hpi": 100 * np.exp(np.arange(len(idx)) * 0.01),
            "gdp_qoq_saar": 2.0,
            "mortgage30": 5.0,
            "unrate": 4.0,
        },
        index=idx,
    )


def test_extend_reverts_linearly_over_eight_quarters():
    q = pd.Period("2025Q4", freq="Q")
    fc = np.zeros((12, 4))
    fc[:, 1] = 5.0  # GDP 5% SAAR during the forecast
    lr = {"hpi_yoy": 3.0, "gdp_yoy": 3.0, "mortgage30": 6.0, "unrate": 5.0}
    f = extend(_hist(), fc, lr, q, 8, end=pd.Period("2035Q4", freq="Q"))
    assert f.gdp_g[q + 12] == 5.0
    assert f.gdp_g[q + 13] == pytest.approx(4.75)  # 5 -> 3 over 8 quarters: first step
    assert f.gdp_g[q + 20] == pytest.approx(3.0) and f.gdp_g[q + 30] == pytest.approx(3.0)
    assert f.mortgage30[q + 12] == 5.0 and f.mortgage30[q + 20] == pytest.approx(6.0)
    assert f.hpi_yoy[q + 40] == pytest.approx(3.0)


def test_extend_refuses_missing_reporting_quarter():
    h = _hist()
    h.loc[pd.Period("2025Q4", freq="Q"), "unrate"] = np.nan
    with pytest.raises(ValueError):
        extend(
            h,
            np.zeros((12, 4)),
            {"hpi_yoy": 3, "gdp_yoy": 2, "mortgage30": 6, "unrate": 5},
            pd.Period("2025Q4", freq="Q"),
            8,
        )


def test_table5_one_year_forward_and_averages():
    q = pd.Period("2025Q4", freq="Q")
    fc = np.zeros((12, 4))
    fc[:, 0] = 400 * np.log(1.01)  # index +1% a quarter
    fc[:, 1] = 2.0
    f = extend(
        _hist(),
        fc,
        {"hpi_yoy": 4.06, "gdp_yoy": 2.0, "mortgage30": 5.0, "unrate": 4.0},
        q,
        8,
        end=pd.Period("2035Q4", freq="Q"),
    )
    v = indicator_values(f, q)
    assert v[INDICATORS[0]][0] == pytest.approx(4.06, abs=0.01)
    assert v[INDICATORS[1]][0] == pytest.approx(2.0, abs=1e-9)
    assert v[INDICATORS[2]] == (5.0, 5.0)


def test_yoy_from_quarterly_rates():
    sims = np.full((2, 4), 400 * np.log(1.01))
    y = yoy_paths(np.full(3, 400 * np.log(1.01)), sims, "hpi")
    assert np.allclose(y, 100 * (1.01**4 - 1))
    g = yoy_paths(np.full(3, 2.0), np.full((1, 4), 2.0), "gdp")
    assert np.allclose(g, 2.0)


def test_severity_is_the_satellite_at_mean_growth():
    p = {"const": -0.5, "hpi_yoy[W]": 0.04, "gdp_yoy[W]": 0.1}
    z = severity(p, np.full((1, 12), 5.0), np.full((1, 12), 2.0))
    assert z[0] == pytest.approx(-0.5 + 0.2 + 0.2)


def _states():
    idx = pd.period_range("2000Q1", "2010Q4", freq="Q")
    nat = pd.Series(np.cumsum(np.r_[0, np.sin(np.arange(len(idx) - 1))]) * 0.01, index=idx)
    st = pd.DataFrame({"AA": nat, "BB": 2 * nat, "CC": 0.5 * nat}, index=idx)
    return nat, st


def test_betas_recover_state_amplitude():
    nat, st = _states()
    b = fit_betas(st, nat, "2000Q2", "2010Q4")
    assert b.beta.round(6).tolist() == [1.0, 2.0, 0.5]


def test_project_states_uses_no_data_after_the_cut():
    nat, st = _states()
    cut = pd.Period("2006Q4", freq="Q")
    b = pd.Series({"AA": 1.0, "BB": 2.0, "CC": 0.5})
    p1 = project_states(st, nat, b, cut)
    st2 = st.copy()
    st2.loc[cut + 1 :] = 99.0  # data after the reporting quarter
    p2 = project_states(st2, nat, b, cut)
    assert np.allclose(p1.values, p2.values)
    assert np.allclose(p1.AA, nat)  # beta 1 reproduces the national path
    assert np.allclose(p1.BB, st.BB)  # beta 2 reproduces a state at 2x


def test_plausibility_band():
    hist = pd.DataFrame({"hpi": np.arange(100.0), "gdp": np.arange(100.0)})
    assert percentile_of(9.0, hist.hpi) == 10.0
    t = plausibility({"downside": {"hpi": 9.0, "gdp": 2.0}}, hist, BANDS)
    assert t.set_index("variable").within_band.to_dict() == {"hpi": True, "gdp": False}


# --- sources, base and severity checks ------------------------------------------------


def test_smooth_quarterly_hits_fixed_points_and_annual_averages():
    from ecl.scenarios.sources import smooth_quarterly

    q = pd.Period("2026Q1", freq="Q")
    fixed = {q: 4.0, q + 1: 4.2, q + 2: 4.4, q + 3: 4.6, q + 4: 4.8}
    s = smooth_quarterly(q, pd.Period("2028Q4", freq="Q"), fixed, {2027: 5.0, 2028: 5.5})
    assert all(s[k] == pytest.approx(v) for k, v in fixed.items())
    assert s.loc["2027Q1":"2027Q4"].mean() == pytest.approx(5.0)
    assert s.loc["2028Q1":"2028Q4"].mean() == pytest.approx(5.5)


def test_smooth_quarterly_reproduces_a_linear_path():
    from ecl.scenarios.sources import smooth_quarterly

    q = pd.Period("2026Q1", freq="Q")
    lin = pd.Series(np.arange(12) * 0.1, index=pd.period_range(q, periods=12, freq="Q"))
    s = smooth_quarterly(
        q,
        q + 11,
        {q: 0.0, q + 1: 0.1},
        {2027: lin["2027Q1":"2027Q4"].mean(), 2028: lin["2028Q1":"2028Q4"].mean()},
    )
    assert np.allclose(s.values, lin.values)


def test_spf_survey_released_after_the_date_is_refused():
    from ecl.scenarios.sources import spf_release_bound, spf_row, spf_survey_as_at

    spf = pd.DataFrame({"x": [1.0, 2.0, 3.0]}, index=pd.period_range("2022Q4", periods=3, freq="Q"))
    as_at = pd.Timestamp("2023-03-31")
    assert spf_release_bound(pd.Period("2023Q1", freq="Q")) == pd.Timestamp("2023-02-28")
    assert spf_survey_as_at(spf, as_at) == pd.Period("2023Q1", freq="Q")
    with pytest.raises(ValueError):
        spf_row(spf, pd.Period("2023Q2", freq="Q"), as_at)


def test_gs10_uses_no_month_after_the_date(tmp_path):
    from ecl.scenarios.sources import read_gs10

    f = tmp_path / "GS10.csv"
    months = pd.date_range("2022-10-01", "2023-06-01", freq="MS")
    pd.DataFrame(
        {
            "observation_date": months.strftime("%Y-%m-%d"),
            "GS10": np.arange(len(months), dtype=float),
        }
    ).to_csv(f, index=False)
    q = read_gs10(f, pd.Timestamp("2023-03-31"))
    assert q.index.max() == pd.Period("2023Q1", freq="Q")
    assert q[pd.Period("2023Q1", freq="Q")] == pytest.approx(4.0)  # Jan-Mar = 3, 4, 5


def test_mortgage_path_spread_moves_linearly_to_its_mean():
    from ecl.scenarios.base import mortgage_path

    tb = pd.Series(np.full(12, 4.0))
    m = mortgage_path(tb, spread0=2.7, spread_lr=1.8)
    assert m.iloc[-1] == pytest.approx(5.8) and m.iloc[0] == pytest.approx(4.0 + 2.7 - 0.9 / 12)


def test_ff_spread_excludes_zero_lower_bound_quarters():
    from ecl.scenarios.base import ff_spread

    idx = pd.period_range("2000Q1", periods=4, freq="Q")
    m = pd.DataFrame(
        {"mortgage30": [6.0, 6.0, 4.0, 4.0], "fedfunds": [3.0, 3.0, 0.1, 0.1]}, index=idx
    )
    assert ff_spread(m, "2000Q1", "2000Q4", zlb_below=0.5)["spread"] == pytest.approx(3.0)
    assert ff_spread(m, "2000Q1", "2000Q4", zlb_below=None)["spread"] == pytest.approx(3.45)


def test_spf_paths_refuses_a_survey_from_another_quarter():
    from ecl.scenarios.base import spf_paths

    with pytest.raises(ValueError):
        spf_paths({}, pd.Period("2022Q4", freq="Q"), pd.Period("2023Q1", freq="Q"), {}, 12)


def test_distance_check_bands():
    from ecl.scenarios.severity import distance_check

    err = pd.Series(np.arange(-50.0, 50.0))  # percentile = value + 50
    t = distance_check(
        {"downside": {"gdp": -40.0}, "upside": {"gdp": 20.0}},
        {"gdp": 0.0},
        {"gdp:test": err},
        BANDS,
    )
    ok = t.set_index("scenario").within_band.to_dict()
    assert ok == {"downside": True, "upside": False}  # pct 11 in 5-20; pct 71 < 80


def test_z_index_check_combines_deviations_with_satellite_weights():
    from ecl.scenarios.severity import z_index_check

    err = pd.DataFrame({"hpi": np.arange(-50.0, 50.0), "gdp": np.zeros(100)})
    p = {"hpi_yoy[W]": 0.04, "gdp_yoy[W]": 0.1}
    t = z_index_check(
        {"downside": {"hpi": -40.0, "gdp": 0.0}}, {"hpi": 0.0, "gdp": 0.0}, err, p, BANDS
    )
    assert t.deviation_from_base[0] == pytest.approx(-1.6)
    assert t.historical_percentile[0] == pytest.approx(11.0) and bool(t.within_band[0])


def test_level_reference_drops_windows_touching_excluded_quarters():
    from ecl.scenarios.severity import level_reference

    idx = pd.period_range("2018Q1", "2023Q4", freq="Q")
    m = pd.DataFrame({"hpi": np.exp(np.arange(len(idx)) * 0.01), "gdp_qoq_saar": 2.0}, index=idx)
    excl = pd.period_range("2020Q1", "2021Q2", freq="Q")
    h = level_reference(m, "2018Q1", pd.Period("2023Q4", freq="Q"), excl)
    assert not any(pd.period_range(t + 1, t + 4, freq="Q").isin(excl).any() for t in h.index)
    assert pd.Period("2019Q3", freq="Q") not in h.index and pd.Period("2021Q2", freq="Q") in h.index
