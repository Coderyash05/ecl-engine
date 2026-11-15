"""Module 12 rules (SYNTHETIC Indian book): DBIE parsing and splices, LTV caps, floating-rate
tenure extension and payment shock, PD term structure, scenario Z shift."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from ecl.india.engine import spread_hazard, z_shifted
from ecl.india.macro import (
    DataCheckError,
    cpi_linked,
    fiscal_to_period,
    gdp_yoy_chained,
    parse_inr,
    read_gdp_csv,
    splice,
)
from ecl.india.portfolio import (
    annuity,
    apply_ltv_caps,
    ltv_cap,
    months_to_repay,
    payment_shock,
    quantile_map,
    scheduled_balance,
    stock_multiplier,
)
from ecl.india.scenarios import z_index

CF = yaml.safe_load(
    (Path(__file__).parents[2] / "config/rbi_credit_facilities.yaml").read_text(encoding="utf-8")
)
CAPS = CF["ltv_individual_housing"]["bands"]  # verified para 111 values used by the generator


def test_ltv_caps_config_is_para_111_as_verified():
    """Credit Facilities Directions 2025 (updated as on 1 Oct 2026), para 111, page 55."""
    assert CF["updated_as_on"] == "2026-10-01" and CF["ltv_individual_housing"]["para"] == "111"
    assert [(b["up_to_lakh"], b["cap"]) for b in CAPS] == [(30, 90), (75, 80), (None, 75)]


def test_rbi_fiscal_quarters_map_to_calendar_quarters():
    assert fiscal_to_period("Q1.2022-23") == pd.Period("2022Q2")  # April-June 2022
    assert fiscal_to_period("Q3.2022-23") == pd.Period("2022Q4")
    assert fiscal_to_period("Q4.2022-23(P)") == pd.Period("2023Q1")  # January-March 2023


def test_splice_keeps_newest_level_and_chains_older_growth():
    q = pd.period_range("2010Q1", periods=6, freq="Q")
    old = pd.Series([100, 110, 121, 133.1, np.nan, np.nan], index=q)  # +10% per quarter
    new = pd.Series([np.nan, np.nan, 50, 52, 54, 56], index=q)  # rebased series from 2010Q3
    s, checks = splice([old, new])
    assert s.loc["2010Q3":].tolist() == [50, 52, 54, 56]  # newest base sets the level
    assert s.loc["2010Q2"] == pytest.approx(50 / 1.1)  # chained back on the older growth
    assert s.loc["2010Q1"] == pytest.approx(50 / 1.21)
    assert checks[0]["quarters"] == 2


def test_rbi_ltv_caps_by_ticket_size():
    caps = ltv_cap(np.array([10, 30, 30.01, 75, 120]), CAPS)
    assert caps.tolist() == [90, 90, 80, 80, 75]  # <= 30 lakh 90%, 30-75 lakh 80%, > 75 lakh 75%


def test_rate_rise_extends_tenure_with_fixed_emi_when_cap_allows():
    b, r0, n0 = 50.0, 8.0, 240
    emi = annuity(b, r0, n0)
    rem, shock = payment_shock(np.array([b]), 9.0, emi, np.array([360]))
    assert shock[0] == 0.0 and 240 < rem[0] <= 360  # EMI unchanged, tenure longer
    assert months_to_repay(np.array([b]), 8.0, emi)[0] == pytest.approx(240, abs=1e-6)


def test_emi_rises_when_the_retirement_cap_binds():
    b, r0, n0 = 50.0, 8.0, 240
    emi = annuity(b, r0, n0)
    rem, shock = payment_shock(np.array([b]), 10.0, emi, np.array([240]))
    assert rem[0] == 240 and shock[0] == pytest.approx(annuity(b, 10.0, 240) / emi - 1)
    assert shock[0] > 0.1


def test_rate_cut_keeps_emi_and_shortens_tenure_no_shock():
    emi = annuity(50.0, 8.0, 240)
    rem, shock = payment_shock(np.array([50.0]), 6.0, emi, np.array([300]))
    assert shock[0] == 0.0 and rem[0] < 240


def test_scheduled_balance_amortises_to_zero():
    assert scheduled_balance(100.0, 8.0, 240, 0) == pytest.approx(100.0)
    assert scheduled_balance(100.0, 8.0, 240, 240) == pytest.approx(0.0, abs=1e-9)
    assert 0 < scheduled_balance(100.0, 8.0, 240, 120) < 100


def test_quantile_map_keeps_rank_and_range():
    x = pd.Series([500, 600, 700, 800, np.nan])
    v = quantile_map(x, {0.0: 300, 0.5: 760, 1.0: 900})
    assert np.all(np.diff(v[:4]) > 0) and v[:4].min() >= 300 and v[:4].max() <= 900
    assert np.isnan(v[4])


def test_term_structure_year1_is_12m_pd_and_lifetime_total_is_kept():
    pd12, life = np.array([0.01, 0.02]), np.array([0.05, 0.02])
    cum = spread_hazard(pd12, life, np.array([10, 10]), 0.08)
    assert cum[:, 0] == pytest.approx(pd12)
    assert cum[:, -1] == pytest.approx(life, rel=1e-6)
    assert np.all(np.diff(cum, axis=1) >= -1e-15)


def test_z_shift_reproduces_us_points_and_is_monotone():
    z = {"downside": -0.5, "central": -0.2, "upside": 0.0}
    c, d, u = np.array([0.01]), np.array([0.02]), np.array([0.008])
    assert z_shifted(c, d, u, z, -0.2)[0] == pytest.approx(0.01)
    assert z_shifted(c, d, u, z, -0.6)[0] > z_shifted(c, d, u, z, -0.3)[0]  # worse Z, higher PD


def test_india_z_equals_long_run_at_long_run_hpi_growth():
    sat = {"hpi_yoy[W]": 0.0438}
    assert z_index(8.0, 8.0, sat, -0.207) == pytest.approx(-0.207)
    assert z_index(3.0, 8.0, sat, -0.207) < -0.207  # slower house-price growth = worse Z


# --- Module 12 follow-up: verified data loaders and calibration (2026-11-15) ---------------

GDP_HEADER = "src_file,tab,period,row_no,c1,c2,c3,c4,c5,c6,c7,c8,c9,c10,c11\n"


def _gdp_csv(tmp_path, base, rows):
    lines = [
        GDP_HEADER,
        f'f,t,p,1,"Quarterly Estimates of GDP (Base : {base})",,,,,,,,,,\n',
        "f,t,p,2,Item/ Year,Quarter,1. PFCE,,,,,,,,9. Gross Domestic Product\n",
    ]
    lines += [f'f,t,p,{i + 3},{fy},{q},"1",,,,,,,," {v}"\n' for i, (fy, q, v) in enumerate(rows)]
    p = tmp_path / "gdp.csv"
    p.write_text("".join(lines), encoding="utf-8")
    return p


def test_parse_inr_handles_indian_grouping_and_leading_space_negatives():
    assert parse_inr("61,62,845.93") == pytest.approx(6162845.93)
    assert parse_inr(" -67,532.54") == pytest.approx(-67532.54)
    assert parse_inr("12,36,604") == 1236604.0
    assert np.isnan(parse_inr("")) and np.isnan(parse_inr(None))


def test_gdp_parser_fills_fiscal_year_and_maps_quarters(tmp_path):
    rows = [("2022-23   ", "Q1", "61,62,845.93"), ("", "Q2", "60,45,123.20"),
            ("", "Q3", "68,28,275.97"), ("", "Q4", "71,40,756.36"),
            ("2023-24", "Q1", "-1,000.5")]  # fmt: skip
    exp = {"base": "2022-23", "first": "Q1.2022-23", "last": "Q1.2023-24", "rows": 5}
    s = read_gdp_csv(_gdp_csv(tmp_path, "2022-23", rows), exp)
    assert list(s.index.astype(str)) == ["2022Q2", "2022Q3", "2022Q4", "2023Q1", "2023Q2"]
    assert s.iloc[0] == pytest.approx(6162845.93) and s.iloc[-1] == pytest.approx(-1000.5)


def test_gdp_parser_fails_loudly_on_wrong_base_or_truncation(tmp_path):
    rows = [("2022-23", "Q1", "1"), ("", "Q2", "2")]
    with pytest.raises(DataCheckError, match="base"):
        read_gdp_csv(
            _gdp_csv(tmp_path, "2011-12", rows),
            {"base": "2022-23", "first": "Q1.2022-23", "last": "Q2.2022-23", "rows": 2},
        )
    with pytest.raises(DataCheckError, match="expected"):
        read_gdp_csv(
            _gdp_csv(tmp_path, "2022-23", rows),
            {"base": "2022-23", "first": "Q1.2022-23", "last": "Q4.2022-23", "rows": 4},
        )


def test_gdp_yoy_chained_switches_base_without_splicing_levels():
    q = pd.period_range("2021Q1", periods=12, freq="Q")
    old = pd.Series(100 * 1.02 ** np.arange(12), index=q)  # ~8.2% YoY
    new = pd.Series(500 * 1.01 ** np.arange(8), index=q[4:])  # different level, ~4.1% YoY
    out, st = gdp_yoy_chained(old, new, pd.Period("2023Q1"))
    assert out.loc["2023Q1"] == pytest.approx((1.02**4 - 1) * 100)
    assert out.loc["2023Q2"] == pytest.approx((1.01**4 - 1) * 100)  # new base growth, its own level
    assert st["overlap_quarters"] == 4 and st["chained_to"] == "2023Q4"


def test_cpi_link_ratio_is_the_mean_and_must_be_stable():
    m12 = pd.period_range("2024-01", "2025-12", freq="M")
    m24 = pd.period_range("2025-01", "2025-12", freq="M").append(
        pd.period_range("2026-01", "2026-03", freq="M")
    )
    c24 = pd.Series(100.0 + np.arange(len(m24)), index=m24)
    c12 = pd.Series(190.0, index=m12)
    c12[m24[:12]] = c24[m24[:12]] * 1.9
    out, st = cpi_linked(c12, c24, 2025, 0.05)
    assert st["ratio_mean"] == pytest.approx(1.9) and st["ratio_range"] == pytest.approx(
        0, abs=1e-12
    )
    assert out.loc["2026-01"] == pytest.approx(c24.loc["2026-01"] * 1.9)
    c12.loc["2025-06"] *= 1.1  # unstable link
    with pytest.raises(DataCheckError, match="unstable"):
        cpi_linked(c12, c24, 2025, 0.05)


def test_generator_ltv_never_exceeds_the_ticket_cap():
    amt = np.array([10, 30, 31, 75, 76, 200])
    us_ltv = np.array([97, 95, 95, 85, 80, np.nan])
    assert apply_ltv_caps(amt, us_ltv, CAPS).tolist() == [90, 90, 80, 80, 75, 75]
    assert apply_ltv_caps(np.array([20.0]), np.array([60.0]), CAPS).tolist() == [60.0]


def test_stock_multiplier_hits_the_gnpa_target():
    s, t = 0.0049, 0.008
    m = stock_multiplier(s, t)
    assert m * s / (1 - s + m * s) == pytest.approx(t)
    assert stock_multiplier(0.01, 0.005) < 1  # thinning when the US share is above target
