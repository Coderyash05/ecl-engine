"""Module 10 rules: old-rules (IRACP) provision, loss-allowance reconciliation, transition."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from ecl.reporting.annex4 import reconciliation, transition
from ecl.reporting.iracp import old_rules_provision

IRACP = yaml.safe_load(Path("config/rbi_iracp_2025.yaml").read_text(encoding="utf-8"))
RBI = yaml.safe_load(Path("config/rbi_2026.yaml").read_text(encoding="utf-8"))


def _loan(**kw):
    base = {
        "ead_now": 100.0,
        "secured": 80.0,
        "unsecured": 20.0,
        "npa": False,
        "npa_years": np.nan,
        "calamity_events": 0,
        "calamity_written_back": False,
        "failed_monitoring": False,
    }
    return base | kw


def _old(rows):
    return old_rules_provision(pd.DataFrame(rows), IRACP)


def test_standard_housing_loan_is_0_25pct_iracp_80_1():
    r = _old([_loan()])
    assert r.asset_class[0] == "standard" and r.iracp_provision[0] == pytest.approx(0.25)


def test_substandard_15pct_and_unsecured_25pct_iracp_85_86():
    r = _old(
        [
            _loan(npa=True, npa_years=0.5),
            _loan(npa=True, npa_years=1.0, secured=10.0, unsecured=90.0),
        ]
    )
    assert r.asset_class.tolist() == [
        "substandard",
        "substandard",
    ]  # 12 months is still substandard
    assert r.iracp_provision.tolist() == pytest.approx([15.0, 25.0])  # realisable 10% = unsecured


def test_doubtful_secured_portion_by_years_in_doubtful_iracp_90_91():
    rows = [_loan(npa=True, npa_years=y) for y in (1.5, 2.5, 4.5)]  # doubtful 0.5 / 1.5 / 3.5 years
    r = _old(rows)
    assert r.asset_class.tolist() == ["doubtful D1", "doubtful D2", "doubtful D3"]
    assert r.iracp_provision.tolist() == pytest.approx([20 + 0.25 * 80, 20 + 0.40 * 80, 100.0])


def test_loss_when_realisable_value_below_10pct_iracp_68_2():
    r = _old([_loan(npa=True, npa_years=0.2, secured=5.0, unsecured=95.0)])
    assert r.asset_class[0] == "loss" and r.iracp_provision[0] == pytest.approx(100.0)


def test_calamity_and_failed_monitoring_additional_provisions_with_ceiling():
    r = _old(
        [
            _loan(calamity_events=2),  # 84A + 84B: 5% each -> 10% + 0.25%
            _loan(calamity_events=1, calamity_written_back=True),  # 84C written back
            _loan(npa=True, npa_years=0.5, failed_monitoring=True),  # RSA 64: 15% + 15%
            _loan(npa=True, npa_years=5, failed_monitoring=True),  # 100% + 15% -> ceiling 100%
        ]
    )
    assert r.iracp_provision.tolist() == pytest.approx([10.25, 0.25, 30.0, 100.0])


def test_reconciliation_moves_add_up_to_the_closing_balance():
    opening = pd.DataFrame(
        {
            "loan_id": list("abcd"),
            "stage": [1, 1, 2, 3],
            "ead_now": [100.0, 50.0, 80.0, 40.0],
            "allowance": [1.0, 0.5, 2.0, 10.0],
        }
    )
    closing = pd.DataFrame(
        {
            "loan_id": ["a", "b", "e"],
            "stage": [2, 1, 1],
            "ead_now": [95.0, 48.0, 70.0],
            "allowance": [3.0, 0.4, 0.2],
        }
    )
    info = pd.DataFrame(
        {
            "loan_id": list("abcde"),
            "zb_code": [None, None, "01", "09", None],
            "first_period": pd.to_datetime(["2010-01-01"] * 4 + ["2025-09-01"]),
        }
    )
    t = reconciliation(opening, closing, info, "2025-03-01").set_index("row")
    assert (
        t.loc["Transfer to Stage 2", "Stage 1 ECL"] == -1.0
        and t.loc["Transfer to Stage 2", "Stage 2 ECL"] == 1.0
    )
    assert t.loc["Matured or repaid", "Stage 2 ECL"] == -2.0  # c prepaid (zb 01)
    assert t.loc["Write-offs (loss-type terminations)", "Stage 3 ECL"] == -10.0  # d REO disposition
    assert t.loc["New financial assets originated during the year", "Stage 1 ECL"] == 0.2
    close = t.loc["Balance at the closing date"]
    assert close["Total ECL"] == pytest.approx(3.6) == close["check_closing_ecl_from_data"]
    assert close["Stage 2 ECL"] == pytest.approx(3.0) and close["Total gross"] == pytest.approx(
        213.0
    )


def test_transition_impact_and_cet1_addback_schedule_paras_107_108():
    cur = pd.DataFrame(
        {
            "stage": [1, 2, 3],
            "allowance": [30.0, 20.0, 150.0],
            "iracp_provision": [10.0, 10.0, 80.0],
        }
    )
    sched, t9, s = transition(cur, RBI)
    assert s["impact"] == 100.0  # max(0, 200 - 100)
    assert sched.max_addback_to_cet1_pre_tax.tolist() == pytest.approx([80.0, 60.0, 40.0, 20.0])
    assert t9.set_index("row").loc["Stage 3 adjustment", "adjustment"] == 70.0
    cur2 = cur.assign(iracp_provision=[100.0, 100.0, 100.0])
    assert transition(cur2, RBI)[2]["impact"] == 0.0  # ECL below old provisions: no add-back


def test_old_vs_ecl_segments_are_exclusive_and_sum_to_the_totals():
    from ecl.reporting.annex4 import old_vs_ecl_by_segment

    cur = pd.DataFrame(
        {
            "loan_id": list("abcdef"),
            "stage": [1, 2, 3, 3, 3, 1],
            "stage_rule": ["none", "sicr_pd", "default", "restructured", "restructured", "none"],
            "category": ["xi_a"] * 5 + ["xiv"],
            "modification_events": [0, 0, 0, 1, 0, 0],
            "npa_years": [np.nan, np.nan, 0.5, 2.5, 4.0, np.nan],
            "ead_now": [100.0] * 6,
            "secured": [90.0] * 6,
            "ecl_stage_model": [1.0] * 6,
            "allowance": [0.25, 2.0, 12.0, 52.0, 100.0, 5.0],
            "iracp_base": [0.25, 0.25, 15.0, 50.0, 100.0, 0.25],
            "iracp_additional": [0, 0, 0, 15.0, 0, 5.0],
            "iracp_provision": [0.25, 0.25, 15.0, 65.0, 100.0, 5.25],
            "stuck": [False, False, False, True, False, False],
        }
    )
    g = old_vs_ecl_by_segment(cur)
    body, total = g[g.segment != "Total"], g[g.segment == "Total"].iloc[0]
    assert body.loans.sum() == 6 and total.loans == 6  # every loan in exactly one row
    assert "other" not in set(body.segment)
    assert total.ecl_minus_iracp == pytest.approx(cur.allowance.sum() - cur.iracp_provision.sum())
    s3 = body.set_index(["segment", "npa_band"])
    assert s3.loc[("Stage 3 restructured - modification", "2-3"), "ecl_minus_iracp"] == -13.0
    assert s3.loc[("Stage 3 restructured - general deferral", "4+"), "ecl_minus_iracp"] == 0.0


def test_ecl_backtest_counts_defaults_losses_and_censoring():
    from ecl.validation.backtest import ecl_backtest

    res = pd.DataFrame(
        {
            "loan_id": ["a", "b", "c", "d", "e"],
            "stage": [1, 1, 2, 2, 3],
            "ead_now": [100.0] * 5,
            "pd12_weighted": [0.01, 0.01, 0.2, 0.2, 1.0],
            "ecl12_weighted": [0.1, 0.1, 5.0, 5.0, 50.0],
        }
    )
    out = pd.DataFrame(
        {
            "loan_id": ["a", "b", "c", "d", "e"],
            "default_12m": [False, True, True, True, True],
            "default_b18_12m": [False, False, True, True, True],
            "zb_code": [None, "09", None, "01", None],
            "actual_loss": [None, 30.0, None, 0.0, None],
            "cured": [False, False, False, False, False],
        }
    )
    t = ecl_backtest(res, out, ["02", "03", "09", "15"], "2026-03").set_index("segment")
    tot = t.loc["Total"]
    assert tot.loans == 4  # Stage 3 excluded
    assert tot.actual_defaults_rbi == 3 and tot.actual_defaults_b18 == 2
    assert tot.predicted_defaults == pytest.approx(0.42)
    assert tot.realised_loss_to_data_end == 30.0  # REO loss; prepaid after default = 0
    assert tot.defaults_liquidated == 1 and tot.defaults_cured_or_prepaid == 1
    assert tot.defaults_unresolved == 1 and tot.ead_unresolved == 100.0
