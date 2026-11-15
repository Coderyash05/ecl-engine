"""Modules 6-8 rules: staging, ECL measurement, prudential floors (hand-built examples)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from ecl.pd.dataset import score_unknown_status_as_current
from ecl.provisioning.ecl import discount_factors, ecl_12m, ecl_lifetime, marginal_pd, weighted
from ecl.provisioning.floors import portfolio_floor, stage3_band_rates, stage3_floor
from ecl.staging.restructured import covid_window, restructuring_events, stage3_history
from ecl.staging.rules import sicr_pd_flag, stage_loans, transition_matrix

CFG = yaml.safe_load(Path("config/ecl.yaml").read_text(encoding="utf-8"))
RBI = yaml.safe_load(Path("config/rbi_2026.yaml").read_text(encoding="utf-8"))


def _loan(**kw) -> dict:
    base = {
        "in_default": False,
        "dpd_bucket": "current",
        "modified": False,
        "pd_life_now": 0.02,
        "pd_life_orig": 0.02,
        "current_ltv": 60.0,
        "restr_state": np.nan,
        "npa_arrears": False,
    }
    return {**base, **kw}


def _stage(rows, **kw) -> pd.DataFrame:
    return stage_loans(pd.DataFrame(rows), CFG, **kw)


def test_a_loan_45_days_past_due_is_stage_2_by_the_backstop():
    s = _stage([_loan(dpd_bucket="30-59")])
    assert s.stage[0] == 2 and s.stage_rule[0] == "backstop_30dpd"


def test_a_loan_90_days_past_due_is_stage_3():
    s = _stage([_loan(in_default=True, dpd_bucket="90+")])
    assert s.stage[0] == 3 and s.stage_rule[0] == "default"


def test_sicr_needs_both_relative_and_absolute_increase():
    rows = [
        _loan(pd_life_now=0.03, pd_life_orig=0.01),  # x3, +2pp -> SICR
        _loan(pd_life_now=0.003, pd_life_orig=0.001),  # x3 but +0.2pp -> no
        _loan(pd_life_now=0.04, pd_life_orig=0.02),  # x2, +2pp -> no at 2.5
        _loan(pd_life_now=0.04, pd_life_orig=np.nan),
    ]  # no comparator -> no
    s = _stage(rows)
    assert s.stage.tolist() == [2, 1, 1, 1]
    assert _stage(rows, ratio=2.0).stage.tolist() == [2, 1, 2, 1]  # sensitivity
    assert sicr_pd_flag([0.025], [0.01], 2.5, 0.005)[0]  # exactly at both thresholds


def test_collateral_trigger_at_indexed_ltv_100():
    s = _stage([_loan(current_ltv=100.0), _loan(current_ltv=99.9), _loan(current_ltv=np.nan)])
    assert s.stage.tolist() == [2, 1, 1]
    assert s.stage_rule[0] == "collateral_ltv"


def test_restructured_mappings_text_upper_bound_and_interim():
    rows = [
        _loan(modified=True, restr_state=3),
        _loan(modified=True, restr_state=2),
        _loan(modified=True, restr_state=1),
    ]
    s = _stage(rows)  # primary: text mapping (state from time and performance since modification)
    assert s.stage.tolist() == [3, 2, 1]
    assert s.stage_rule.tolist() == ["restructured", "restructured", "none"]
    assert _stage(rows, restructured="stage3").stage.tolist() == [3, 3, 3]  # upper bound
    assert _stage(rows, restructured="stage2").stage.tolist() == [2, 2, 2]  # interim rule


def _hist(upb, dlq_months=(), start="2020-01-01", status=None, events=(0,)):
    """Monthly history of one loan: UPB, status bucket per month (default: current, or 30-59 in
    dlq_months), RBI default when 90+, restructuring event months (default: the first month)."""
    n = len(upb)
    status = status or ["30-59" if i in dlq_months else "current" for i in range(n)]
    return pd.DataFrame(
        {
            "loan_id": "L",
            "period": pd.date_range(start, periods=n, freq="MS"),
            "current_upb": upb,
            "dpd_bucket": status,
            "default_event": [s == "90+" for s in status],
            "restr_event": [i in events for i in range(n)],
        }
    )


RSA = CFG["staging"]["restructured"]["text_mapping"]


def _state(h, mode="text", npa=True, rule="no_upgrade", fresh=True):
    return stage3_history(h, RSA, mode, npa, "restr_event", rule, fresh)


def test_modified_loan_is_stage_3_until_10pct_repaid_and_12_months_after_first_payment():
    upb = [100 - i for i in range(40)]  # 1% of the base a month; first payment = month 1
    assert _state(_hist(upb[:12])).restr_state[0] == 3  # 11% repaid but 11 months after payment
    r = _state(_hist(upb[:14]))  # month 13: 12 months after the first payment, 13% repaid
    assert r.restr_state[0] == 2 and r.months_after_first_payment[0] == 12
    assert r.repaid_on_clock[0] == pytest.approx(0.13)


def test_stage_2_to_1_at_20pct_repaid_on_the_same_clock_no_second_period():
    upb = [100 - i for i in range(40)]
    assert _state(_hist(upb[:20])).restr_state[0] == 2  # 19% repaid
    assert _state(_hist(upb[:21])).restr_state[0] == 1  # 20% repaid at month 20


def test_slow_repayment_keeps_stage_3_after_12_months():
    upb = [100 - 0.5 * i for i in range(40)]  # 10% repaid only at month 20
    assert _state(_hist(upb[:20])).restr_state[0] == 3
    assert _state(_hist(upb[:21])).restr_state[0] == 2


def test_restart_sensitivity_missed_payment_restarts_clock_and_base():
    upb = [100 - i for i in range(60)]
    r = _state(_hist(upb[:16], dlq_months={14}), rule="restart")  # Stage 2 at 13, miss at 14
    assert r.restr_state[0] == 3 and r.restarts[0] == 1
    assert r.years_s3[0] == pytest.approx(1 / 12)  # Stage 3 again since month 14
    # new clock from month 15 (base 85): Stage 2 needs month 28 (12 after payment) and UPB <= 76.5
    assert _state(_hist(upb[:28], dlq_months={14}), rule="restart").restr_state[0] == 3
    assert _state(_hist(upb[:29], dlq_months={14}), rule="restart").restr_state[0] == 2


def test_rsa_61_a_miss_blocks_upgrade_until_a_fresh_restructuring():
    upb = [100 - i for i in range(60)]
    r = _state(_hist(upb[:40], dlq_months={5}))  # miss in month 5 of the monitoring period
    assert r.restr_state[0] == 3 and r.stuck[0]  # 39% repaid, still Stage 3
    r = _state(_hist(upb[:16], dlq_months={14}))  # default after upgrade (RSA 62)
    assert r.restr_state[0] == 3 and r.stuck[0]
    # a later modification (fresh restructuring) at month 20 starts a new monitoring period:
    # base 80; Stage 2 at month 33 (12 months after first payment, 16% repaid); Stage 1 at 36
    h = _hist(upb[:34], dlq_months={5}, events=(0, 20))
    r = _state(h)
    assert r.restr_state[0] == 2 and not r.stuck[0] and r.events[0] == 2
    assert _state(_hist(upb[:33], dlq_months={5}, events=(0, 20))).restr_state[0] == 3
    assert _state(_hist(upb[:37], dlq_months={5}, events=(0, 20))).restr_state[0] == 1


def test_the_implementation_month_itself_is_not_tested_for_a_miss():
    status = ["90+"] + ["current"] * 13
    r = _state(_hist([100 - i for i in range(14)], status=status))
    assert r.restr_state[0] == 2 and not r.stuck[0]


def test_graduated_loan_is_left_to_ordinary_staging():
    upb = [100 - i for i in range(30)]
    r = _state(_hist(upb, dlq_months={25}))  # graduated at month 20; later miss not restructuring
    assert r.restr_state[0] == 1 and not r.stage3[0]


def test_npa_stays_in_default_until_arrears_are_cleared_para_8_10():
    status = ["current", "30-59", "60-89", "90+", "60-89", "30-59"]
    r = _state(_hist([100] * 6, status=status, events=()))
    assert r.npa[0] and r.npa_arrears[0] and r.stage3[0]
    assert r.years_s3[0] == pytest.approx(2 / 12)  # Stage 3 since the 90+ month
    assert not _state(_hist([100] * 7, status=[*status, "current"], events=())).npa[0]
    assert not _state(_hist([100] * 6, status=status, events=()), npa=False).npa[0]  # 90+ only
    s = _stage([_loan(npa_arrears=True, dpd_bucket="30-59")])
    assert s.stage[0] == 3 and s.stage_rule[0] == "default_arrears"


def test_duration_in_stage_3_runs_from_the_default_before_the_modification_para_82_5():
    status = ["90+"] * 6 + ["current"] * 12  # 90+ for 6 months, modified at month 6 (cured)
    r = _state(_hist([100.0] * 18, status=status, events=(6,)))
    assert r.restr_state[0] == 3 and r.years_s3[0] == pytest.approx(17 / 12)
    assert r.years_restr_s3[0] == pytest.approx(11 / 12)  # published: from the modification


def test_a_cure_before_the_modification_starts_a_new_stage_3_spell():
    status = ["90+"] * 3 + ["current"] * 15  # back to current at month 3, modified at month 6
    r = _state(_hist([100.0] * 18, status=status, events=(6,)))
    assert r.years_s3[0] == pytest.approx(11 / 12)


def test_upper_and_lower_bound_mappings():
    upb = [100 - i for i in range(30)]
    assert _state(_hist(upb), mode="stage3").years_s3[0] == pytest.approx(29 / 12)  # never leaves
    r = _state(_hist(upb), mode="stage2")
    assert r.restr_state[0] == 2 and not r.stage3[0]


def test_cured_loan_returns_to_stage_1_without_sicr_para_77():
    # out of default now, no SICR, not restructured: Stage 1 (no memory of the default)
    s = _stage([_loan(pd_life_now=0.02, pd_life_orig=0.015)])
    assert s.stage[0] == 1 and s.rules_fired[0] == ""


def test_every_rule_that_fired_is_recorded():
    s = _stage([_loan(dpd_bucket="60-89", current_ltv=120.0, pd_life_now=0.2, pd_life_orig=0.01)])
    assert s.rules_fired[0] == "backstop_30dpd;sicr_pd;collateral_ltv"
    assert s.stage_rule[0] == "backstop_30dpd"  # priority order


def test_transition_matrix_row_shares_and_exits():
    a = pd.DataFrame({"loan_id": list("abcd"), "stage": [1, 1, 2, 2]})
    b = pd.DataFrame({"loan_id": list("abc"), "stage": [1, 2, 3]})
    t = transition_matrix(a, b)
    assert t.loc["Stage 1", "Stage 2"] == 0.5
    assert t.loc["Stage 2", "exited"] == 0.5 and t.loc["Stage 2", "Stage 3"] == 0.5


def test_discounting_and_12m_vs_lifetime_ecl():
    df = discount_factors(np.array([12.0]), 2)  # 1% a month
    assert df[0, 0] == pytest.approx(1.01**-6) and df[0, 1] == pytest.approx(1.01**-18)
    cum = np.array([[0.02, 0.05]])
    lgd = np.array([[0.3, 0.4]])
    ead = np.array([[100.0, 90.0]])
    assert marginal_pd(cum).tolist() == [[0.02, pytest.approx(0.03)]]
    assert ecl_12m([0.02], lgd, ead, df)[0] == pytest.approx(0.02 * 0.3 * 100 * df[0, 0])
    life = 0.02 * 0.3 * 100 * df[0, 0] + 0.03 * 0.4 * 90 * df[0, 1]
    assert ecl_lifetime(cum, lgd, ead, df)[0] == pytest.approx(life)


def test_ecl_is_weighted_after_computation_per_scenario():
    e = weighted({"down": np.array([10.0]), "up": np.array([2.0])}, {"down": 0.25, "up": 0.75})
    assert e[0] == pytest.approx(4.0)
    with pytest.raises(ValueError):
        weighted({"a": np.array([1.0])}, {"a": 0.9})


def test_stage1_and_stage2_floors_at_portfolio_level():
    s1 = RBI["floors"]["housing_loan_to_individuals"]["stage_1"]["value"]
    f = portfolio_floor(np.array([10.0, 5.0]), np.array([4000.0, 6000.0]), s1)  # 0.25%
    assert f["floor"] == pytest.approx(25.0) and f["provision"] == 25.0 and f["binds"]
    f2 = portfolio_floor(np.array([300.0]), np.array([10_000.0]), 0.015)
    assert f2["provision"] == 300.0 and not f2["binds"]


def test_stage3_floor_by_years_and_portion_with_from_to_convention():
    s3 = RBI["floors"]["housing_loan_to_individuals"]["stage_3"]
    bands, conv = s3["bands"], s3["band_boundaries"]["convention"]
    rs, ru = stage3_band_rates(np.array([0.5, 1.0, 3.5, 4.0]), bands, conv)
    assert rs.tolist() == [0.10, 0.20, 0.40, 1.00]  # exactly 1.0 year -> 1-2 year band
    assert ru.tolist() == [0.25, 1.00, 1.00, 1.00]
    f = stage3_floor(
        np.array([5.0]), np.array([80.0]), np.array([20.0]), np.array([0.5]), bands, conv
    )
    assert f.floor[0] == pytest.approx(0.10 * 80 + 0.25 * 20) and f.provision[0] == 13.0


def test_unreported_status_xx_is_scored_as_current_and_flagged():
    df = pd.DataFrame({"dpd_bucket": ["unknown", "30-59", "current"]})
    out = score_unknown_status_as_current(df)
    assert out.dpd_bucket.tolist() == ["current", "30-59", "current"]
    assert out.dpd_status_unknown.tolist() == [True, False, False]
    assert df.dpd_bucket[0] == "unknown"  # input not modified


def test_covid_window_is_the_run_around_the_peak_above_twice_the_baseline():
    idx = pd.date_range("2019-01-01", "2025-12-01", freq="MS")
    n = pd.Series(10.0, index=idx)
    n[(idx >= "2020-07-01") & (idx <= "2021-12-01")] = 500.0
    n[idx == "2022-01-01"] = 15.0  # below 2 x baseline (10): window ends 2021-12
    n[idx == "2017-01-01"] = 0.0
    assert covid_window(n, [2023, 2025], 2) == (
        pd.Timestamp("2020-07-01"),
        pd.Timestamp("2021-12-01"),
    )


def _ev(loan, status, defer, relief, disaster=None, mod=None, start="2020-01-01"):
    n = len(status)
    return pd.DataFrame(
        {
            "loan_id": loan,
            "period": pd.date_range(start, periods=n, freq="MS"),
            "dpd_bucket": status,
            "default_event": [x == "90+" for x in status],
            "modified": mod or [False] * n,
            "payment_deferral": defer,
            "relief_flag": relief,
            "disaster_dlq": disaster or [False] * n,
            "current_upb": 100.0,
        }
    )


def test_deferral_routes_calamity_eligible_ineligible_and_general_rsa_124j():
    win = (pd.Timestamp("2020-07-01"), pd.Timestamp("2022-06-01"))
    f, t = False, True
    # A: current before the COVID forbearance episode (Apr-Jun), deferral in Jul 2020 -> calamity
    a = _ev(
        "A",
        ["current"] * 3 + ["60-89"] * 3 + ["current"] * 2,
        [f] * 6 + [t, f],
        [f] * 3 + [t] * 4 + [f],
    )
    # B: 60-89 dpd before the episode began -> ineligible -> general restructuring (RSA 124K)
    b = _ev(
        "B",
        ["current", "current", "60-89"] + ["60-89"] * 3 + ["current"] * 2,
        [f] * 6 + [t, f],
        [f] * 3 + [t] * 4 + [f],
    )
    # C: deferral outside the window, no disaster flag -> general restructuring
    c = _ev("C", ["current"] * 8, [f] * 6 + [t, f], [f] * 6 + [t, f], start="2024-01-01")
    # D: modification -> general restructuring
    d = _ev("D", ["current"] * 8, [f] * 8, [f] * 8, mod=[f] * 4 + [t] + [f] * 3)
    ev = restructuring_events(pd.concat([a, b, c, d], ignore_index=True), win, 12)
    g = ev.groupby("loan_id")[["calamity_event", "general_event"]].any()
    assert g.loc["A"].tolist() == [True, False]
    assert g.loc["B"].tolist() == [False, True]
    assert g.loc["C"].tolist() == [False, True]
    assert g.loc["D"].tolist() == [False, True]
