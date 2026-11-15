"""Lifetime PD (Module 3): competing-risk lifetime hazard, paths, floor, splice, SICR comparator.

Hand-built examples: each test states the rule it checks.
"""

import duckdb
import numpy as np
import pandas as pd
import pytest

from ecl.lifetime.hazard import (
    HazardModel,
    Loans,
    QuarterRows,
    WoeMap,
    amortised_balance,
    apply_annual_floor,
    carry_weight,
    carry_year1_ratio,
    cumulative,
    design,
    fit_mnl,
    free_parameters,
    horizon_bucket,
    project,
    quarter_rows,
    remaining_from,
    splice_year1,
)
from ecl.lifetime.hazard_data import create_life_table, quarters_sql
from ecl.lifetime.paths import Q0, long_run_path, qidx, revert, reverting_path, z_for_quarters

# ---------------------------------------------------------------- building blocks


def test_amortised_balance_matches_month_by_month_schedule():
    upb, rate, rm = 100_000.0, 6.0, 360
    r = rate / 1200
    pay = upb * r / (1 - (1 + r) ** -rm)
    b = upb
    for _ in range(12):
        b = b * (1 + r) - pay
    assert amortised_balance(upb, rate, rm, 12) == pytest.approx(b)
    assert amortised_balance(upb, rate, rm, 400) == pytest.approx(0.0, abs=1e-6)
    assert amortised_balance(1200.0, 0.0, 12, 6) == pytest.approx(600.0)


def test_horizon_buckets():
    assert horizon_bucket(np.array([1, 4, 5, 8, 9, 12, 13, 20, 21, 120])).tolist() == [
        0,
        0,
        1,
        1,
        2,
        2,
        3,
        3,
        4,
        4,
    ]


def test_survival_and_incidences_add_up_to_one():
    rng = np.random.default_rng(0)
    h_d, h_p = rng.uniform(0, 0.02, (5, 40)), rng.uniform(0, 0.05, (5, 40))
    s, cd, cp = cumulative(h_d, h_p)
    assert (s + cd + cp) == pytest.approx(np.ones_like(s))


def test_prepayment_lowers_lifetime_pd():
    """Para 51: loans that prepay cannot default later."""
    h_d = np.full((1, 120), 0.003)
    _, no_prepay, _ = cumulative(h_d, np.zeros_like(h_d))
    _, with_prepay, _ = cumulative(h_d, np.full_like(h_d, 0.03))
    assert with_prepay[0, -1] < no_prepay[0, -1]


def _rows(n, **kw):
    base = {
        "age_months": np.zeros(n),
        "k": np.ones(n, int),
        "dlq": np.zeros(n),
        "rest": np.zeros(n),
        "dlq_state": np.zeros(n, int),
        "woe": np.zeros((n, 8)),
        "dwoe_ltv": np.zeros(n),
        "dwoe_age": np.zeros(n),
        "dneg": np.zeros(n),
        "ltv": np.full(n, 70.0),
        "z": np.zeros(n),
        "incentive": np.full(n, -0.5),
        "hpi_yoy": np.zeros(n),
    }
    base.update(kw)
    return QuarterRows(**base)


def test_design_has_age_baseline_and_pooled_15_plus():
    r = _rows(3, age_months=np.array([0, 13 * 12, 25 * 12]))
    x, names = design(r)
    assert names[0] == "const" and "age_15+" in names
    assert x[2, names.index("age_15+")] == 1 and x[1, names.index("age_13")] == 1
    assert x[0, 1:16].sum() == 0  # age 0 is the base


def test_fit_mnl_recovers_coefficients():
    rng = np.random.default_rng(1)
    n = 200_000
    x = np.column_stack([np.ones(n), rng.normal(size=n)]).astype(np.float32)
    beta = np.array([[-4.0, 0.8], [-2.5, -0.4]])
    eta = np.column_stack([np.zeros(n), x @ beta.T])
    p = np.exp(eta) / np.exp(eta).sum(axis=1, keepdims=True)
    y = (rng.uniform(size=n)[:, None] > np.cumsum(p, axis=1)).sum(axis=1)
    m = fit_mnl(x, y, np.ones(n), ["const", "x"], "test")
    assert m.beta == pytest.approx(beta, abs=0.08)
    se = np.sqrt(np.diag(m.cov))
    assert np.all(np.abs(m.beta.ravel() - beta.ravel()) < 4 * se)


def test_excluded_terms_stay_at_zero_in_their_equation():
    """Design §2.1: HPI growth only in the prepayment equation, Z only in the default one."""
    rng = np.random.default_rng(2)
    n = 50_000
    r = _rows(n, z=rng.normal(size=n), hpi_yoy=rng.normal(5, 3, n))
    x, names = design(r)
    y = rng.choice(3, size=n, p=[0.9, 0.02, 0.08])
    varies = (x.std(axis=0) > 0) | (np.arange(x.shape[1]) == 0)  # synthetic: most are 0
    m = fit_mnl(x, y, np.ones(n), names, "H2", free=free_parameters(names) & varies)
    assert m.beta[0, names.index("hpi_yoy (per 10%)")] == 0.0
    assert m.beta[1, names.index("z")] == 0.0
    t = m.coef_table()
    assert not ((t.outcome == "default") & (t.term == "hpi_yoy (per 10%)")).any()


def test_default_incentive_options_change_only_the_default_equation():
    r = _rows(3, incentive=np.array([-2.0, 0.7, 1.4]))
    for opt, free_bands, has_ge1 in [
        ("bands", True, False),
        ("none", False, False),
        ("ge1", False, True),
    ]:
        x, names = design(r, "H2", {"default_incentive": opt})
        free = free_parameters(names, {"default_incentive": opt})
        band = names.index("incentive 0.5..1")
        assert free[0, band] == free_bands and free[1, band]  # prepay always has bands
        assert ("incentive >=1 [default]" in names) == has_ge1
        if has_ge1:
            j = names.index("incentive >=1 [default]")
            assert free[0, j] and not free[1, j] and x[:, j].tolist() == [0, 0, 1]


def test_prepayment_ramp_terms_enter_the_prepayment_equation_only():
    r = _rows(4, age_months=np.array([1, 7, 14, 30]), incentive=np.array([0.7] * 4))
    x, names = design(r, "H2", {"prepay_ramp": "both"})
    free = free_parameters(names, {"prepay_ramp": "both"})
    ramp = [i for i, nm in enumerate(names) if nm.endswith("[prepay]")]
    assert len(ramp) == 4 + 5 and not free[0, ramp].any() and free[1, ramp].all()
    assert x[0, names.index("age 0-2m [prepay]")] == 1
    assert x[2, names.index("age 12-17m [prepay]")] == 1
    young = names.index("young x incentive 0.5..1 [prepay]")
    assert x[:, young].tolist() == [1, 1, 1, 0]  # 30 months is not young
    x5, names5 = design(r, "H2", {"prepay_ramp": "both5"})
    mid = names5.index("age 2-5y x incentive 0.5..1 [prepay]")
    assert x5[:, mid].tolist() == [0, 0, 0, 1]  # only the 30-month loan
    assert set(names) < set(names5)
    free5 = free_parameters(names5, {"prepay_ramp": "both5"})
    assert free5.sum() == free.sum() + len(names5) - len(names)


def test_state_specific_decay_replaces_the_shared_fade_in_the_default_equation_only():
    r = _rows(3, dlq_state=np.array([0, 3, 4]), k=np.array([1, 6, 30]))
    x, names = design(r, "H2", {"dlq_decay": "state"})
    free = free_parameters(names, {"dlq_decay": "state"})
    shared = names.index("dlq x q1-4")
    assert not free[0, shared] and free[1, shared]  # prepayment keeps the shared fade
    j = names.index("dlq_state=3 x q5-8 [default]")
    assert free[0, j] and not free[1, j] and x[:, j].tolist() == [0, 1, 0]
    assert x[2, names.index("dlq_state=4 x q21+ [default]")] == 1
    assert len([n for n in names if n.startswith("dlq_state=")]) == 25


def test_carry_weight_fades_from_full_to_none():
    assert carry_weight(np.array([1, 2, 3]), 0).tolist() == [1, 0, 0]
    assert carry_weight(np.array([1, 2, 3]), np.inf).tolist() == [1, 1, 1]
    assert carry_weight(np.array([2, 3]), 1.0) == pytest.approx([np.exp(-1), np.exp(-2)])


def test_calibrated_splice_scales_later_years_by_the_faded_year1_ratio():
    """Year-1 ratio PIT / hazard = 2: year 2 hazards scaled by 2**exp(-1/tau), year 1 untouched."""
    h_d, h_p = np.full((1, 12), 0.002), np.full((1, 12), 0.02)
    out = carry_year1_ratio(h_d, h_p, np.array([2.0]), 1.0)
    assert out[0, :4] == pytest.approx(0.002)
    assert out[0, 4:8] == pytest.approx(0.002 * 2 ** np.exp(-1))
    assert out[0, 8:] == pytest.approx(0.002 * 2 ** np.exp(-2))
    assert carry_year1_ratio(h_d, h_p, np.array([100.0]), np.inf)[0, 5] == pytest.approx(0.008)


def test_clustered_errors_account_for_repeated_loans():
    """Rows of the same loan are not independent: duplicating every row within its cluster
    leaves the coefficients unchanged and the clustered SE equal to the original SE."""
    rng = np.random.default_rng(3)
    n = 40_000
    x = np.column_stack([np.ones(n), rng.normal(size=n)]).astype(np.float32)
    y = rng.choice(3, size=n, p=[0.9, 0.03, 0.07])
    one = fit_mnl(x, y, np.ones(n), ["const", "x"], "t", cluster=np.arange(n))
    dup = fit_mnl(
        np.repeat(x, 2, axis=0),
        np.repeat(y, 2),
        np.full(2 * n, 0.5),
        ["const", "x"],
        "t",
        cluster=np.repeat(np.arange(n), 2),
    )
    assert dup.beta == pytest.approx(one.beta, abs=1e-6)
    assert np.sqrt(np.diag(dup.cov)) == pytest.approx(np.sqrt(np.diag(one.cov)), rel=1e-4)


# ---------------------------------------------------------------- projection


def _loans(rm, n=1):
    return Loans(
        age=np.zeros(n),
        rm=np.full(n, float(rm)),
        upb=np.full(n, 1e5),
        rate=np.full(n, 5.0),
        value=np.full(n, 1.25e5),
        ltv=np.full(n, 80.0),
        state_idx=np.zeros(n, int),
        ref_q=np.full(n, qidx("2020Q4")),
        dlq=np.zeros(n),
        rest=np.zeros(n),
        dlq_state=np.zeros(n, int),
        woe=np.zeros((n, 8)),
    )


LTV_WOE = WoeMap(np.array([30.0, 60.0, 80.0, 95.0]), np.array([1.5, 0.8, 0.2, -0.4, -1.4]), -0.3)
AGE_WOE = WoeMap(np.array([3.0, 12.0, 36.0]), np.array([1.0, 0.4, -0.1, -0.25]), 0.0)
MAPS = {"current_ltv": LTV_WOE, "loan_age": AGE_WOE}


def _model():
    names = design(_rows(1))[1]
    beta = np.zeros((2, len(names)))
    beta[:, 0] = [-6.0, -4.0]
    return HazardModel("H2", names, beta, woe_maps=MAPS)


def test_horizon_stops_at_contractual_maturity():
    """Para 46(1): no default or prepayment after the loan's remaining term."""
    path = long_run_path({"hpi_yoy": 3.0, "mortgage30": 6.0}, 0.0, ["CA"])
    h_d, h_p = project(_model(), _loans(rm=12), path, 8)
    assert np.all(h_d[0, :4] > 0) and np.all(h_d[0, 4:] == 0) and np.all(h_p[0, 4:] == 0)


def test_rising_house_prices_lower_ltv_and_raise_its_woe():
    path = long_run_path({"hpi_yoy": 10.0, "mortgage30": 6.0}, 0.0, ["CA"])
    r = quarter_rows(_loans(rm=360), path, np.array([4]), MAPS)
    assert r.ltv[0] < 80 and r.dwoe_ltv[0] > 0 and r.dneg[0] == 0


def test_ltv_effect_saturates_like_the_score():
    """Decades of house-price growth cannot lower the hazard without bound: below the lowest
    LTV bin the WoE, and so the LTV term, stays flat."""
    path = long_run_path({"hpi_yoy": 6.0, "mortgage30": 6.0}, 0.0, ["CA"])
    r = quarter_rows(_loans(rm=360, n=2), path, np.array([60, 100]), MAPS)
    assert r.ltv[1] < r.ltv[0] < 30
    assert r.dwoe_ltv[0] == r.dwoe_ltv[1] == pytest.approx(1.5 - (-0.4))


def test_seasoning_moves_the_loan_age_woe_along_the_projection():
    """The score's loan-age effect is updated as the loan ages (it is not frozen at the
    reference age): a new loan's WoE falls from 1.0 towards the seasoned -0.25."""
    path = long_run_path({"hpi_yoy": 3.0, "mortgage30": 6.0}, 0.0, ["CA"])
    r = quarter_rows(_loans(rm=360, n=3), path, np.array([1, 3, 20]), MAPS)
    assert r.dwoe_age.tolist() == pytest.approx([0.0, 0.4 - 1.0, -0.25 - 1.0])


def test_negative_equity_term_only_above_100():
    path = long_run_path({"hpi_yoy": -20.0, "mortgage30": 6.0}, 0.0, ["CA"])
    r = quarter_rows(_loans(rm=360), path, np.array([8]), MAPS)
    assert r.ltv[0] > 100 and r.dneg[0] == pytest.approx(r.ltv[0] - 100)


# ---------------------------------------------------------------- floor and splice


def test_annual_floor_lifts_low_years_only():
    """Each future year's conditional annual PD >= 0.03% (pd.floor_lifetime_annual)."""
    h_d = np.array([[1e-5] * 4 + [1e-3] * 4])
    h_p = np.full_like(h_d, 0.02)
    out, bound = apply_annual_floor(h_d, h_p, 0.0003)
    s = np.cumprod(1 - out[:, :4] - h_p[:, :4], axis=1)
    prev = np.hstack([[[1.0]], s[:, :3]])
    assert np.sum(prev * out[:, :4]) == pytest.approx(0.0003, rel=1e-4)
    assert out[0, 4:] == pytest.approx(h_d[0, 4:])
    assert bound.tolist() == [[True, False]]


def test_floor_can_skip_year_one():
    h_d = np.full((1, 8), 1e-6)
    out, bound = apply_annual_floor(h_d, np.zeros_like(h_d), 0.0003, first_year=1)
    assert out[0, :4] == pytest.approx(h_d[0, :4]) and bound.tolist() == [[False, True]]


def test_splice_reproduces_12m_pd_and_keeps_later_conditional_risk():
    h_d, h_p = np.full((1, 12), 0.002), np.full((1, 12), 0.03)
    s, cd, cp = cumulative(h_d, h_p)
    pd12 = np.array([0.02])
    out = splice_year1(cd, cp, s, pd12)
    assert out[0, 3] == pytest.approx(0.02)
    cond_hazard = (cd[0, -1] - cd[0, 3]) / s[0, 3]
    assert out[0, -1] == pytest.approx(0.02 + (1 - 0.02 - cp[0, 3]) * cond_hazard)


def test_sicr_comparator_is_seasoning_neutral():
    """An unchanged loan: PD expected at origination over [j, maturity] given alive at j equals
    a fresh projection over the same remaining quarters (constant hazards)."""
    k, j = 40, 12
    h_d, h_p = np.full((1, k), 0.003), np.full((1, k), 0.02)
    s, cd, _ = cumulative(h_d, h_p)
    from_orig = remaining_from(cd, s, np.array([j]))
    _, fresh, _ = cumulative(h_d[:, : k - j], h_p[:, : k - j])
    assert from_orig[0] == pytest.approx(fresh[0, -1])
    assert remaining_from(cd, s, np.array([0]))[0] == pytest.approx(cd[0, -1])


# ---------------------------------------------------------------- paths


def test_z_of_a_quarter_averages_the_four_windows_covering_it():
    z_s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert z_for_quarters(z_s).iloc[4] == pytest.approx(2.5)


def test_reversion_reaches_long_run_mean_on_schedule():
    """Para 124: mean reversion beyond the forecast horizon."""
    idx = pd.period_range("2020Q1", "2023Q4", freq="Q")
    x = pd.Series(np.full(len(idx), 10.0), index=idx)
    r = revert(x, 2.0, pd.Period("2023Q4"), 8)
    assert r.loc["2024Q4"] == pytest.approx(6.0)
    assert r.loc["2025Q4"] == pytest.approx(2.0) and r.loc["2030Q1"] == pytest.approx(2.0)


def test_forward_path_uses_no_measured_z_after_the_reporting_date_window():
    """Measured Z_s needs outcomes to s+4: at a reporting date only s <= report - 4 is known."""
    idx = pd.period_range("1998Q1", "2026Q2", freq="Q")
    macro = pd.DataFrame({"hpi_yoy": 4.0, "gdp_yoy": 2.0, "mortgage30": 6.0}, index=idx)
    z = pd.Series(0.0, index=pd.period_range("2000Q1", "2023Q4", freq="Q"))
    z.loc["2023Q1":] = 99.0  # known only after the reporting date
    hpi = pd.DataFrame({"state": "CA", "yr": [2000, 2026], "qtr": [1, 2], "hpi": [100, 200]})
    params = {"const": 0.0, "hpi_yoy[W]": 0.0, "gdp_yoy[W]": 0.0}
    p = reverting_path(
        macro, z, hpi, params, {"hpi_yoy": 4, "gdp_yoy": 2, "mortgage30": 6}, pd.Period("2023Q4")
    )
    assert np.nanmax(p.z_q[qidx("2023Q1") - Q0 : qidx("2026Q1") - Q0]) < 1.0


# ---------------------------------------------------------------- person-quarter coding


@pytest.mark.parametrize(
    "kind, months, expected",
    [
        ("default", 7, (3, 1)),  # default in month 7 -> event in quarter 3
        ("prepay", 6, (2, 2)),
        ("censored", 7, (2, 0)),  # code 16/96 in month 7: alive through month 6
        ("data_end", 7, (2, 0)),  # last seen alive in month 7: two full quarters
    ],
)
def test_quarter_rows_and_event_coding(kind, months, expected):
    con = duckdb.connect()
    con.execute("""CREATE TABLE r AS SELECT DATE '2020-03-01' AS d""")
    con.execute(f"""CREATE TABLE l AS SELECT '{kind}' AS exit_kind,
                    DATE '2020-03-01' + INTERVAL {months} MONTH AS exit_period""")
    got = con.execute(f"SELECT {quarters_sql('r', 'd')} FROM r, l").fetchone()
    assert got == expected


def test_life_table_splits_prepayment_from_maturity(tmp_path):
    panel = pd.DataFrame(
        {
            "loan_id": ["A", "A", "B", "B", "C", "D"],
            "period": pd.to_datetime(
                ["2020-01-01", "2020-02-01", "2020-01-01", "2020-02-01", "2020-01-01", "2020-01-01"]
            ),
            "first_default_period_b18": pd.to_datetime(
                [None, None, None, None, "2020-01-01", None]
            ),
            "zb_code": [None, "01", None, "01", None, "16"],
            "remaining_months": [200, 199, 3, 2, 100, 100],
        }
    )
    d = tmp_path / "panel" / "vintage=2019"
    d.mkdir(parents=True)
    panel.to_parquet(d / "data.parquet")
    con = duckdb.connect()
    create_life_table(con, tmp_path)
    kinds = dict(con.execute("SELECT loan_id, exit_kind FROM life").fetchall())
    assert kinds == {"A": "prepay", "B": "censored", "C": "default", "D": "censored"}
