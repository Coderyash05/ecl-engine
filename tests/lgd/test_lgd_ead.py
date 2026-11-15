"""Module 5 LGD / EAD rules: hand-built examples (methodology: docs/methodology/lgd_ead.md)."""

import numpy as np
import pandas as pd
import pytest

from ecl.ead.ead import accrued_interest, ead_at_default, ead_now, secured_portion
from ecl.lgd.apply import downturn_factor, pd_weighted, stage3_lgd
from ecl.lgd.data import add_loss, observation_rows
from ecl.lgd.models import CureModel, SeverityModel, spline


def _default(**kw) -> pd.DataFrame:
    base = {
        "loan_id": "A",
        "fd": pd.Timestamp("2009-01-01"),
        "upb_d": 100_000.0,
        "dlq_d": 3,
        "note_rate": 6.0,
        "outcome": "liquidation",
        "zb_period": pd.Timestamp("2010-01-01"),
        "cure_period": pd.NaT,
        "nsp": -60_000.0,
        "mi": -10_000.0,
        "nmi": 0.0,
        "te": 5_000.0,
        "al": 1.0,
    }
    base.update(kw)
    return pd.DataFrame([base])


def test_severity_discounts_net_recovery_at_the_note_rate():
    d = add_loss(_default(), 3)
    ead = 100_000 * (1 + 0.005 * 3)  # three unpaid instalments of interest
    pv = (60_000 + 10_000 - 5_000) * 1.005**-12  # recoveries negative, expenses positive
    assert d.ead_d[0] == pytest.approx(ead)
    assert d.severity[0] == pytest.approx(1 - pv / ead)
    assert d.severity_undiscounted[0] == pytest.approx(1 - 65_000 / ead)
    assert d.realised_lgd[0] == pytest.approx(d.severity[0])


def test_cure_has_zero_loss_and_incomplete_workout_is_excluded():
    cure = add_loss(_default(outcome="cure", zb_period=pd.NaT, al=np.nan), 3)
    assert cure.realised_lgd[0] == 0.0 and np.isnan(cure.severity[0])
    incomplete = add_loss(_default(al=np.nan), 3)
    assert not incomplete.loss_complete[0] and np.isnan(incomplete.realised_lgd[0])


def test_observation_rows_only_while_still_in_default():
    log_state = pd.DataFrame(
        {"AA": np.zeros(40)}, index=pd.period_range("2005Q1", periods=40, freq="Q")
    )
    d = _default(
        outcome="cure",
        cure_period=pd.Timestamp("2009-05-01"),
        zb_period=pd.NaT,
        resolution_period=pd.Timestamp("2009-05-01"),
        orig_upb=100_000.0,
        orig_ltv=80.0,
        property_state="AA",
        orig_month=pd.Timestamp("2005-01-01"),
        age_d=48,
    )
    r = observation_rows(d, [0, 3, 6, 12], log_state)
    assert r.m.tolist() == [0, 3]  # cured in month 4
    assert (r.y == 0).all()
    assert r.ltv_obs.iloc[0] == pytest.approx(80.0)  # flat HPI: UPB / value
    assert r.age_obs.tolist() == [48, 51]


def test_ead_at_default_is_scheduled_balance_before_missed_instalments_plus_interest():
    # zero-rate loan: 120 months left, 1,000 a month
    e = ead_at_default(120_000.0, 0.0, 120, 18, 3)
    assert e == pytest.approx(120_000 - 15 * 1_000)
    e6 = ead_at_default(100_000.0, 6.0, 360, 3, 3)  # default after 3 months: nothing paid
    assert e6 == pytest.approx(100_000 + accrued_interest(100_000, 6.0, 3))
    assert ead_now(100_000.0, 6.0, 0) == 100_000.0


def test_secured_portion_uses_realisable_value_and_never_nets_ead():
    sec, uns = secured_portion(
        np.array([100.0, 100.0, 100.0]), np.array([300.0, 150.0, np.nan]), 0.5
    )
    assert sec.tolist() == [100.0, 75.0, 0.0]
    assert uns.tolist() == [0.0, 25.0, 100.0]  # missing value: fully unsecured


def test_pd_weighted_lgd_uses_marginal_default_probabilities():
    cum = np.array([[0.01, 0.03, 0.04]])  # marginal 0.01, 0.02, 0.01
    lgd = np.array([[0.1, 0.4, 0.2]])
    assert pd_weighted(cum, lgd)[0] == pytest.approx((0.001 + 0.008 + 0.002) / 0.04)


def test_stage3_months_in_default_and_reo():
    cure = CureModel({"ltv": [80], "score": [700], "age": [24]}, [0, 3, 6, 12])
    cure.fill = {"ltv": 80.0, "credit_score": 700.0}
    cure.design(
        pd.DataFrame(
            {
                "ltv": [1.0],
                "credit_score": [1.0],
                "prior_dlq": [0],
                "age": [1.0],
                "relief": [0],
                "m": [0],
            }
        )
    )
    cure.params = np.zeros(len(cure.names))
    cure.params[cure.names.index("months in default = 6")] = 1.0
    sev = SeverityModel({"ltv": [80], "size": [200_000]}, {"SF": "SF"})
    sev.fill = {"ltv": 80.0}
    sev.design(
        pd.DataFrame({"ltv": [1.0], "mi_pct": [0], "property_type": ["SF"], "orig_upb": [1.0]})
    )
    sev.params = np.zeros(len(sev.names))
    d = pd.DataFrame(
        {
            "ltv": [90.0] * 3,
            "credit_score": [700] * 3,
            "prior_dlq": [False] * 3,
            "age": [60] * 3,
            "relief": [False] * 3,
            "months_in_default": [7, 1, 40],
            "reo": [False, False, True],
            "mi_pct": [0] * 3,
            "property_type": ["SF"] * 3,
            "orig_upb": [200_000] * 3,
        }
    )
    out = stage3_lgd(d, cure, sev)
    assert out.m_used.tolist() == [6, 0, 12]  # last observation point reached
    assert out.p_no_cure[0] == pytest.approx(1 / (1 + np.exp(-1)))
    assert out.p_no_cure[2] == 1.0  # REO acquired: cannot cure
    assert out.lgd[1] == pytest.approx(0.25)  # 0.5 x 0.5 with zero coefficients


def test_cure_model_recovers_ltv_and_time_in_default_effects():
    rng = np.random.default_rng(0)
    n = 20_000
    d = pd.DataFrame(
        {
            "ltv": rng.uniform(40, 140, n),
            "credit_score": rng.uniform(600, 800, n),
            "prior_dlq": rng.random(n) < 0.3,
            "age": rng.uniform(6, 120, n),
            "relief": rng.random(n) < 0.1,
            "m": rng.choice([0, 3, 6], n),
        }
    )
    eta = -4 + 0.04 * d.ltv + 0.5 * (d.m == 6) - 1.5 * d.relief
    d.loc[:199, "ltv"] = np.nan  # missing values occur in the data (missing flags)
    d.loc[200:399, "credit_score"] = np.nan
    y = (rng.random(n) < 1 / (1 + np.exp(-eta))).astype(int)
    cm = CureModel({"ltv": [80], "score": [700], "age": [24]}, [0, 3, 6]).fit(
        d, y.values, np.arange(n)
    )
    c = cm.coef_table().set_index("term").coef
    assert c["ltv/10"] == pytest.approx(0.4, abs=0.1)
    assert c["months in default = 6"] == pytest.approx(0.5, abs=0.15)
    assert c["relief at default"] == pytest.approx(-1.5, abs=0.3)


def test_downturn_factor_only_in_stressed_years_and_scaled():
    f = downturn_factor(np.array([True, False]), ratio=1.2, s=0.5)
    assert f.tolist() == [pytest.approx(1.1), 1.0]
    assert downturn_factor(np.array([True]), 1.2, 0.0)[0] == 1.0  # base / upside: s = 0


def test_spline_columns():
    cols, names = spline(np.array([50.0, 90.0]), [60, 80], "x")
    assert names == ["x", "x>60", "x>80"]
    assert cols[2].tolist() == [0.0, 10.0]


def test_intercept_recalibration_hits_the_target_rate_and_keeps_slopes():
    rng = np.random.default_rng(2)
    n = 5_000
    d = pd.DataFrame(
        {
            "ltv": rng.uniform(40, 140, n),
            "credit_score": rng.uniform(600, 800, n),
            "prior_dlq": rng.random(n) < 0.3,
            "age": rng.uniform(6, 120, n),
            "relief": rng.random(n) < 0.1,
            "m": np.zeros(n),
        }
    )
    d.loc[:49, "ltv"] = np.nan
    d.loc[50:99, "credit_score"] = np.nan
    y = (rng.random(n) < 0.5).astype(int)
    cm = CureModel({"ltv": [80], "score": [700], "age": [24]}, [0]).fit(d, y, np.arange(n))
    slopes = cm.params.copy()
    target = np.r_[np.ones(300), np.zeros(700)]  # 30% no-cure in the recalibration window
    shift = cm.recalibrate(d.iloc[:1000], target)
    assert cm.p_no_cure(d.iloc[:1000]).mean() == pytest.approx(0.30, abs=1e-6)
    assert shift < 0 and np.allclose(cm.params, slopes)
