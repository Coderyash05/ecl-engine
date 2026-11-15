"""Tests for the Module 1 panel builder (ecl.data.panel, `ecl build-panel`) on small hand-made files in the Freddie Mac layout.

Rows are built by column *name* from config/freddie_layout.yaml, so the tests follow the
configured layout rather than hard-coding column positions.
"""

import contextlib
import io
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
with open(ROOT / "config" / "freddie_layout.yaml") as _f:
    LAYOUT = yaml.safe_load(_f)

from ecl import cli
from ecl.data import panel as build_panel

# ---------------------------------------------------------------- helpers

ORIG_DEFAULTS = {
    "credit_score": "750",
    "first_payment_date": "201705",
    "maturity_date": "204704",
    "orig_ltv": "80",
    "orig_cltv": "80",
    "orig_dti": "36",
    "orig_upb": "200000",
    "orig_interest_rate": "4.25",
    "orig_loan_term": "360",
    "num_borrowers": "1",
    "occupancy_status": "P",
    "loan_purpose": "P",
    "property_type": "SF",
    "property_state": "PA",
    "channel": "R",
    "harp_indicator": "N",
}
FORBEARANCE = {"borrower_assistance_status": "F"}


def orig_line(loan_id: str, **vals: str) -> str:
    row = {**ORIG_DEFAULTS, "loan_id": loan_id, **vals}
    return "|".join(row.get(c, "") for c in LAYOUT["origination"])


def perf_line(loan_id: str, period: str, dlq: str, age: int, **vals: str) -> str:
    row = {
        "loan_id": loan_id,
        "reporting_period": period,
        "current_upb": "200000.00",
        "delinquency_status": dlq,
        "loan_age": str(age),
        "remaining_months": str(360 - age),
        "current_interest_rate": "4.250",
        **vals,
    }
    return "|".join(row.get(c, "") for c in LAYOUT["performance"])


def write_vintage(raw: Path, vintage: str, orig: list[str], perf: list[str]) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    (raw / f"sample_orig_{vintage}.txt").write_text("\n".join(orig) + "\n")
    (raw / f"sample_perf_{vintage}.txt").write_text("\n".join(perf) + "\n")


def run(tmp: Path, *extra: str) -> str:
    """Run `ecl build-panel` on tmp/raw, return what it logged."""
    argv = [
        "build-panel",
        "--raw-dir",
        str(tmp / "raw"),
        "--out",
        str(tmp / "out"),
        "--reports",
        str(tmp / "reports"),
        *extra,
    ]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(argv)
    return out.getvalue()


def views(tmp: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(tmp / "out" / "ecl.duckdb"), read_only=True)


# ---------------------------------------------------------------- fixture
# Vintage 2017:
# A: 00 -> 01 -> XX -> 00          never defaults; XX is "unknown"
# B: 00 -> 01 -> 02 -> 03 -> RA    defaults at 03 (201707)
# C: 00 -> 01 (forbearance F) -> 00
# D: 00 -> 02 with zero-balance 03 (short sale) -> default by termination
# E: 00 -> 00 with zero-balance 01 (prepaid)      -> not a default
# F: 00 -> deferral C -> deferral P                relief only in the C month
# G: 00 -> 01 (delinquency due to disaster Y)
# H: credit score 9999, VantageScore 9999, LTV 999, ELTV 999 -> NULL
# Q: HARP loan with a pre-HARP loan id
# Option B (PD training targets, 12- and 18-month cure windows):
# I: 03 F -> 04 F -> 00            relief default cured        -> relabelled
# K: 03 F -> 00 -> zb 03           cured but loss in window    -> still default
# L: 03 (no relief) -> 00          cured, but no relief        -> still default
# M: 03 F -> 00 ... 03 (2020)      relabelled, later real default
# N: 03 F, back to 00 at month 12  -> relabelled under B-12 and B-18
# O: 03 F, back to 00 at month 13  -> default under B-12, relabelled under B-18
# P: 03 F, back to 00 at month 19  -> default under B-12 and B-18
# Vintage 2018:
# Z: one current loan (multi-vintage views and idempotent rebuild)

PANEL_COLS = [
    "loan_id",
    "period",
    "dpd_bucket",
    "default_event",
    "first_default_period",
    "relief_flag",
    "months_dlq",
    "reo_acquired",
    "zb_code",
    "ever_deferred",
    "eltv",
    "relief_cured_b12",
    "default_event_b12",
    "first_default_period_b12",
    "relief_cured_b18",
    "default_event_b18",
    "first_default_period_b18",
]


def vintage_2017() -> tuple[list[str], list[str]]:
    orig = [orig_line(x) for x in "ABCDEFGIKLMNOP"] + [
        orig_line("H", credit_score="9999", vantage_score_4="9999", orig_ltv="999"),
        orig_line("Q", harp_indicator="Y", pre_harp_loan_id="F09Q10000001"),
    ]
    fb = FORBEARANCE
    perf = [
        perf_line("A", "201704", "00", 0),
        perf_line("A", "201705", "01", 1),
        perf_line("A", "201706", "XX", 2),
        perf_line("A", "201707", "00", 3),
        perf_line("B", "201704", "00", 0),
        perf_line("B", "201705", "01", 1),
        perf_line("B", "201706", "02", 2),
        perf_line("B", "201707", "03", 3),
        perf_line("B", "201708", "RA", 4),
        perf_line("C", "201704", "00", 0),
        perf_line("C", "201705", "01", 1, **fb),
        perf_line("C", "201706", "00", 2),
        perf_line("D", "201704", "00", 0),
        perf_line("D", "201705", "02", 1, zero_balance_code="03", zero_balance_date="201705"),
        perf_line("E", "201704", "00", 0),
        perf_line("E", "201705", "00", 1, zero_balance_code="01", zero_balance_date="201705"),
        perf_line("F", "201704", "00", 0),
        perf_line("F", "201705", "00", 1, payment_deferral="C"),
        perf_line("F", "201706", "00", 2, payment_deferral="P"),
        perf_line("G", "201704", "00", 0),
        perf_line("G", "201705", "01", 1, delinquency_due_to_disaster="Y"),
        perf_line("H", "201704", "00", 0, eltv="999"),
        perf_line("Q", "201704", "00", 0),
        perf_line("I", "201901", "03", 20, **fb),
        perf_line("I", "201902", "04", 21, **fb),
        perf_line("I", "201904", "00", 23),
        perf_line("K", "201901", "03", 20, **fb),
        perf_line("K", "201902", "00", 21),
        perf_line("K", "201903", "00", 22, zero_balance_code="03", zero_balance_date="201903"),
        perf_line("L", "201901", "03", 20),
        perf_line("L", "201902", "00", 21),
        perf_line("M", "201901", "03", 20, **fb),
        perf_line("M", "201902", "00", 21),
        perf_line("M", "202006", "03", 37),
        perf_line("N", "201901", "03", 20, **fb),
        perf_line("N", "202001", "00", 32),
        perf_line("O", "201901", "03", 20, **fb),
        perf_line("O", "202002", "00", 33),
        perf_line("P", "201901", "03", 20, **fb),
        perf_line("P", "202008", "00", 39),
    ]
    return orig, perf


def vintage_2018() -> tuple[list[str], list[str]]:
    return (
        [orig_line("Z", first_payment_date="201805")],
        [perf_line("Z", "201804", "00", 0), perf_line("Z", "201805", "00", 1)],
    )


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("panel")
    write_vintage(tmp / "raw", "2017", *vintage_2017())
    write_vintage(tmp / "raw", "2018", *vintage_2018())
    log = run(tmp)
    con = views(tmp)
    panel = {}
    for t in con.execute(f"SELECT {', '.join(PANEL_COLS)} FROM panel_all").fetchall():
        r = dict(zip(PANEL_COLS, t))
        panel[(r["loan_id"], r["period"].strftime("%Y%m"))] = r
    loans = {
        r[0]: r
        for r in con.execute(
            "SELECT loan_id, credit_score, orig_ltv, vantage_score_4, harp_loan, "
            "has_pre_harp_link FROM loans_all"
        ).fetchall()
    }
    con.close()
    qc = pd.read_csv(tmp / "reports" / "qc_by_vintage.csv").set_index("vintage")
    by_year = pd.read_csv(tmp / "reports" / "first_defaults_by_year.csv").set_index("year")
    return {"tmp": tmp, "panel": panel, "loans": loans, "log": log, "qc": qc, "by_year": by_year}


def row(built, loan, period):
    return built["panel"][(loan, period)]


# ---------------------------------------------------------------- layout (Release 47)


def test_layout_is_release_47_column_counts():
    assert len(LAYOUT["origination"]) == 31
    assert len(LAYOUT["performance"]) == 35


# ---------------------------------------------------------------- delinquency codes


def test_status_00_is_current_not_default(built):
    r = row(built, "A", "201704")
    assert (r["dpd_bucket"], r["default_event"], r["months_dlq"]) == ("current", False, 0)


def test_status_01_is_30_59_days_not_default(built):
    r = row(built, "A", "201705")
    assert (r["dpd_bucket"], r["default_event"], r["months_dlq"]) == ("30-59", False, 1)


def test_status_xx_is_unknown_and_not_default(built):
    r = row(built, "A", "201706")
    assert r["dpd_bucket"] == "unknown"
    assert r["months_dlq"] is None
    assert r["default_event"] is False


def test_status_02_is_60_89_days_not_default(built):
    r = row(built, "B", "201706")
    assert (r["dpd_bucket"], r["default_event"]) == ("60-89", False)


def test_status_03_is_default_more_than_90_days(built):
    """RBI para 6(5)/8(1): >90 days overdue = NPA; Freddie 03 = 90-119 days."""
    r = row(built, "B", "201707")
    assert (r["dpd_bucket"], r["default_event"]) == ("90+", True)


def test_status_ra_reo_acquired_is_default(built):
    r = row(built, "B", "201708")
    assert r["reo_acquired"] is True and r["default_event"] is True and r["dpd_bucket"] == "90+"


def test_first_default_period_is_first_03_month_on_every_row(built):
    for p in ["201704", "201705", "201706", "201707", "201708"]:
        assert row(built, "B", p)["first_default_period"] == date(2017, 7, 1)


def test_never_defaulted_loan_has_no_first_default(built):
    assert row(built, "A", "201707")["first_default_period"] is None


# ---------------------------------------------------------------- terminations


def test_zero_balance_03_short_sale_is_default(built):
    r = row(built, "D", "201705")
    assert r["zb_code"] == "03" and r["default_event"] is True
    assert r["first_default_period"] == date(2017, 5, 1)


def test_zero_balance_01_prepaid_is_not_default(built):
    r = row(built, "E", "201705")
    assert r["zb_code"] == "01" and r["default_event"] is False
    assert r["first_default_period"] is None


# ---------------------------------------------------------------- relief and flags


def test_forbearance_month_flagged_as_relief(built):
    assert row(built, "C", "201705")["relief_flag"] is True
    assert row(built, "C", "201704")["relief_flag"] is False
    assert row(built, "C", "201706")["relief_flag"] is False


def test_disaster_delinquency_flagged_as_relief(built):
    assert row(built, "G", "201705")["relief_flag"] is True


def test_payment_deferral_current_period_flagged_as_relief(built):
    assert row(built, "F", "201705")["relief_flag"] is True


def test_payment_deferral_prior_period_is_feature_not_relief(built):
    assert row(built, "F", "201705")["ever_deferred"] is False
    r = row(built, "F", "201706")
    assert r["relief_flag"] is False and r["ever_deferred"] is True


def test_harp_flags(built):
    *_, harp, link = built["loans"]["Q"]
    assert harp is True and link is True
    *_, harp, link = built["loans"]["A"]
    assert harp is False and link is False


# ---------------------------------------------------------------- Option B PD targets


def test_relief_default_cured_within_window_is_relabelled(built):
    for p in ["201901", "201902"]:
        r = row(built, "I", p)
        assert r["default_event"] is True  # RBI definition unchanged
        assert r["relief_cured_b12"] is True and r["relief_cured_b18"] is True
        assert r["default_event_b12"] is False and r["default_event_b18"] is False
    r = row(built, "I", "201901")
    assert r["first_default_period"] == date(2019, 1, 1)
    assert r["first_default_period_b12"] is None and r["first_default_period_b18"] is None


def test_relief_cure_with_loss_termination_in_window_stays_default(built):
    r = row(built, "K", "201901")
    assert r["relief_cured_b12"] is False and r["default_event_b12"] is True
    assert r["first_default_period_b12"] == date(2019, 1, 1)


def test_cured_default_without_relief_stays_default(built):
    r = row(built, "L", "201901")
    assert r["default_event_b12"] is True and r["default_event_b18"] is True


def test_later_default_after_relabelled_episode_counts(built):
    r = row(built, "M", "201901")
    assert r["first_default_period"] == date(2019, 1, 1)
    assert r["first_default_period_b12"] == date(2020, 6, 1)


def test_cure_at_month_12_is_inside_both_windows(built):
    r = row(built, "N", "201901")
    assert r["relief_cured_b12"] is True and r["relief_cured_b18"] is True


def test_cure_at_month_13_only_inside_18_month_window(built):
    r = row(built, "O", "201901")
    assert r["relief_cured_b12"] is False and r["relief_cured_b18"] is True
    assert r["first_default_period_b12"] == date(2019, 1, 1)
    assert r["first_default_period_b18"] is None


def test_cure_at_month_19_is_outside_both_windows(built):
    r = row(built, "P", "201901")
    assert r["relief_cured_b12"] is False and r["relief_cured_b18"] is False
    assert r["first_default_period_b18"] == date(2019, 1, 1)


def test_log_reports_relabelling_per_option(built):
    # Defaulted loans: B D I K L M N O P = 9.
    # B-12 relabels I, N (never), M (later); B-18 also relabels O (never).
    assert (
        "2017: 16 loans, 40 loan-months, A: 9 defaulted loans; "
        "B-12 relabels 3 (2 never, 1 later); B-18 relabels 4 (3 never, 1 later)"
    ) in built["log"]


# ---------------------------------------------------------------- sentinels


def test_sentinel_codes_become_null(built):
    _, score, ltv, vantage, *_ = built["loans"]["H"]
    assert score is None and ltv is None and vantage is None
    assert row(built, "H", "201704")["eltv"] is None


# ---------------------------------------------------------------- multi-vintage output


def test_views_cover_all_vintages(built):
    assert ("Z", "201804") in built["panel"]
    assert set(built["loans"]) >= {"A", "Z"}


def test_partition_layout(built):
    out = built["tmp"] / "out"
    for kind in ["loans", "panel"]:
        for v in ["2017", "2018"]:
            assert (out / kind / f"vintage={v}" / "data.parquet").exists()
    assert not (out / "_staging").exists()


def test_rebuild_subset_is_idempotent(built):
    tmp = built["tmp"]
    con = views(tmp)
    before = con.execute("SELECT vintage, COUNT(*) FROM panel_all GROUP BY 1 ORDER BY 1").fetchall()
    con.close()
    log = run(tmp, "--vintages", "2018")
    assert "2018:" in log and "2017:" not in log
    con = views(tmp)
    after = con.execute("SELECT vintage, COUNT(*) FROM panel_all GROUP BY 1 ORDER BY 1").fetchall()
    con.close()
    assert after == before
    assert len(list((tmp / "out" / "panel" / "vintage=2018").iterdir())) == 1


def test_parse_vintages():
    available = [str(y) for y in range(1999, 2027)]
    assert build_panel.parse_vintages("2005-2007,2017", available) == [
        "2005",
        "2006",
        "2007",
        "2017",
    ]
    assert build_panel.parse_vintages(None, available) == available
    with pytest.raises(SystemExit, match="1990"):
        build_panel.parse_vintages("1990", available)


# ---------------------------------------------------------------- QC tables


def test_qc_by_vintage_counts(built):
    qc = built["qc"]
    assert list(qc.index) == [2017, 2018]
    r = qc.loc[2017]
    assert (r.loans, r.loan_months, r.orphan_loans, r.duplicate_loan_months) == (16, 40, 0, 0)
    assert r.ever_default_a == pytest.approx(9 / 16)
    assert r.ever_default_b12 == pytest.approx(7 / 16)  # A minus I, N
    assert r.ever_default_b18 == pytest.approx(6 / 16)  # also minus O
    assert (r.loss_terminations, r.loss_with_actual_loss) == (2, 0)  # D, K
    assert r.prepay_share == pytest.approx(1 / 16)  # E
    assert r.harp_share == pytest.approx(1 / 16)  # Q


def test_qc_pd_training_flag(built):
    # Data end 2020-08; full labels need 12 + 18 months -> observation months up to 2018-02.
    r = built["qc"].loc[2017]  # first period 2017-04
    assert r.months_full_label == 11 and not r.pd_training_ok
    assert built["qc"].loc[2018].months_full_label == 0


def test_first_defaults_by_year(built):
    y = built["by_year"]
    assert y.loc[2017, "first_defaults_a"] == 2  # B, D
    assert y.loc[2019, "first_defaults_a"] == 7  # I K L M N O P
    assert y.loc[2019, "first_defaults_b12"] == 4  # K L O P
    assert y.loc[2019, "first_defaults_b18"] == 3  # K L P
    assert y.loc[2020, "first_defaults_b12"] == 1  # M


# ---------------------------------------------------------------- input checks


def test_origination_column_mismatch_raises(tmp_path):
    write_vintage(
        tmp_path / "raw", "2017", [orig_line("A") + "|EXTRA"], [perf_line("A", "201704", "00", 0)]
    )
    with pytest.raises(SystemExit, match="Origination file sample_orig_2017.txt"):
        run(tmp_path)


def test_performance_column_mismatch_on_later_line_raises(tmp_path):
    good = perf_line("A", "201704", "00", 0)
    bad = perf_line("A", "201705", "00", 1).rsplit("|", 1)[0]  # drop last column
    write_vintage(tmp_path / "raw", "2017", [orig_line("A")], [good, bad])
    with pytest.raises(SystemExit, match="1 lines with 34"):
        run(tmp_path)


def test_unpaired_vintage_raises(tmp_path):
    write_vintage(tmp_path / "raw", "2017", [orig_line("A")], [perf_line("A", "201704", "00", 0)])
    (tmp_path / "raw" / "sample_orig_2018.txt").write_text(orig_line("Z") + "\n")
    with pytest.raises(SystemExit, match="2018"):
        run(tmp_path)
