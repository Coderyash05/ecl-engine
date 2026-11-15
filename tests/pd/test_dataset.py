"""Tests for the Module 2a PD dataset: target window, censoring waterfall, splits, features.

The panel is built with `ecl build-panel` from hand-made Release 47 files, so these tests
also exercise the Module 1 -> Module 2a hand-off.
"""

import contextlib
import logging
from datetime import date

import duckdb
import pandas as pd
import pytest

from ecl.pd.dataset import build_pd_dataset, holdout_flags
from tests.data.test_panel import orig_line, perf_line, run, write_vintage


def months(start: str, end: str) -> list[str]:
    return [
        p.strftime("%Y%m")
        for p in pd.period_range(f"{start[:4]}-{start[4:]}", f"{end[:4]}-{end[4:]}", freq="M")
    ]


def loan_rows(loan: str, start: str, end: str, special: dict | None = None) -> list[str]:
    """Monthly rows, current (00) unless `special[YYYYMM]` overrides dlq or other fields."""
    special = special or {}
    rows = []
    for age, p in enumerate(months(start, end)):
        vals = dict(special.get(p, {}))
        rows.append(perf_line(loan, p, vals.pop("dlq", "00"), age, **vals))
    return rows


FB = {"borrower_assistance_status": "F"}

# Data end 2026-06 (T4), so the last fully labelled snapshot is 2023-12 (12 + 18 months).
# Vintage 2005 file:
# T1 PA, rate 4.0: 30-59 in 2005-05; UPB 198,000 in 2006-06; RBI default 2007-03 (no relief);
#    current again 2007-04..06 -> prior B-18 default
# T2 relief default 2016-02 (F), cured next month; prepaid 2017-01
# T3 rate 5.0, LTV 150 (HARP-style, kept), same origination month as T1: prepaid 2005-09
# T4 current 2023-01..2026-06 (no termination): 2024+ snapshots are censored by date
# T5 stops reporting after 2010-08 with no termination code: lost to follow-up
# T7 2017-01..2021-12, modified in 2018-01 only, prepaid 2021-12
# T8 Puerto Rico (not in the FHFA state file) -> national index fallback; prepaid 2006-12
# T1, T3 and T8 have first payment 2005-02 -> origination quarter 2005Q1
# Vintage 1999 file: T6 1999-01..2000-06, prepaid 2000-06
# Vintage 2024 file: T9 2024-01..2026-06 -> vintage not PD-OK


@contextlib.contextmanager
def captured_log(name: str = "ecl.pd.dataset"):
    """Messages logged by `name` inside the block (works in module-scoped fixtures)."""
    lines: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: lines.append(record.getMessage())
    logger = logging.getLogger(name)
    level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield lines
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pd")
    fp = {"first_payment_date": "200502"}
    v2005_orig = [
        orig_line("T1", orig_interest_rate="4.0", **fp),
        orig_line("T2"),
        orig_line("T3", orig_interest_rate="5.0", orig_ltv="150", **fp),
        orig_line("T4"),
        orig_line("T5"),
        orig_line("T7"),
        orig_line("T8", property_state="PR", orig_interest_rate="4.5", **fp),
    ]
    v2005_perf = (
        loan_rows(
            "T1",
            "200501",
            "200706",
            {
                "200505": {"dlq": "01"},
                "200606": {"current_upb": "198000.00"},
                "200703": {"dlq": "03"},
            },
        )
        + loan_rows(
            "T2",
            "201501",
            "201701",
            {"201602": {"dlq": "03", **FB}, "201701": {"zero_balance_code": "01"}},
        )
        + loan_rows("T3", "200501", "200509", {"200509": {"zero_balance_code": "01"}})
        + loan_rows("T4", "202301", "202606")
        + loan_rows("T5", "201001", "201008")
        + loan_rows(
            "T7",
            "201701",
            "202112",
            {"201801": {"modification_flag": "Y"}, "202112": {"zero_balance_code": "01"}},
        )
        + loan_rows("T8", "200501", "200612", {"200612": {"zero_balance_code": "01"}})
    )
    write_vintage(tmp / "raw", "2005", v2005_orig, v2005_perf)
    write_vintage(
        tmp / "raw",
        "1999",
        [orig_line("T6")],
        loan_rows("T6", "199901", "200006", {"200006": {"zero_balance_code": "01"}}),
    )
    write_vintage(tmp / "raw", "2024", [orig_line("T9")], loan_rows("T9", "202401", "202606"))
    run(tmp)

    hpi = tmp / "hpi.csv"
    hpi.write_text("PA,2005,1,100\nPA,2006,2,110\n")  # no header, like FHFA
    national = tmp / "hpi_us.csv"
    national.write_text(
        "region,yr,qtr,index\nUSA,2005,1,100\nUSA,2006,2,120\nEast North Central,2005,1,100\n"
    )
    with captured_log() as log:
        tables = build_pd_dataset(
            tmp / "out", tmp / "out" / "pd_dataset", tmp / "reports_pd", hpi, national
        )
    df = duckdb.sql(f"""SELECT * FROM read_parquet(
        '{(tmp / "out" / "pd_dataset").as_posix()}/*/*.parquet', hive_partitioning=true)""").df()
    df["obs"] = pd.to_datetime(df.obs_date).dt.strftime("%Y%m")
    rows = {(r.loan_id, r.obs): r for r in df.itertuples()}
    return {"tmp": tmp, "df": df, "rows": rows, "tables": tables, "log": log}


def snap(built, loan, obs):
    return built["rows"][(loan, obs)]


# ---------------------------------------------------------------- snapshots and waterfall


def test_only_quarter_end_snapshots(built):
    assert set(pd.to_datetime(built["df"].obs_date).dt.month) <= {3, 6, 9, 12}


def test_waterfall_counts(built):
    wf = built["tables"]["waterfall"].set_index("status").snapshots.to_dict()
    assert wf == {
        "vintage_not_pd_ok": 10,  # T9: 2024-03 .. 2026-06
        "in_default_a": 1,  # T1 2007-03
        "prior_default_b18": 1,  # T1 2007-06
        "terminated_at_snapshot": 4,  # T3 2005-09, T6 2000-06, T7 2021-12, T8 2006-12
        "before_dev_window": 4,  # T6 1999
        "censored_window_after_data_end": 10,  # T4 2024-03 .. 2026-06
        "censored_lost_to_follow_up": 2,  # T5 2010-03, 2010-06
        "included": 49,  # 42 + T8 2005-03 .. 2006-09
    }
    assert len(built["df"]) == 49


def test_last_labelled_snapshot_is_data_end_minus_30_months(built):
    t4 = built["df"][built["df"].loan_id == "T4"]
    assert sorted(t4.obs) == ["202303", "202306", "202309", "202312"]
    assert "Data end 2026-06-01; last fully labelled snapshot 2023-12-01" in built["log"]


def test_loan_in_default_or_after_default_is_excluded(built):
    assert ("T1", "200703") not in built["rows"] and ("T1", "200706") not in built["rows"]


def test_vintage_not_pd_ok_is_excluded(built):
    assert "T9" not in set(built["df"].loan_id)


# ---------------------------------------------------------------- targets


def test_default_exactly_12_months_ahead_is_in_window(built):
    assert snap(built, "T1", "200603").target_b18  # default 2007-03
    assert snap(built, "T1", "200606").target_b18


def test_default_13_months_ahead_is_outside_window(built):
    assert not snap(built, "T1", "200512").target_b18


def test_relief_cured_default_counts_only_under_a(built):
    r = snap(built, "T2", "201503")
    assert r.target_a and not r.target_b12 and not r.target_b18
    assert r.elig_a


def test_snapshot_after_relief_cured_default_stays_in_b18_population(built):
    r = snap(built, "T2", "201603")
    assert not r.elig_a and r.elig_b12 and not r.target_b18


def test_prepayment_before_default_is_non_default(built):
    for obs in ["200503", "200506"]:
        r = snap(built, "T3", obs)
        assert not r.target_b18 and not r.target_a and r.terminated_within_12m


# ---------------------------------------------------------------- splits


def test_split_boundaries(built):
    assert snap(built, "T6", "200003").split in {"dev_train", "dev_holdout"}
    assert snap(built, "T2", "201612").split in {"dev_train", "dev_holdout"}
    assert snap(built, "T7", "201703").split == "oot1"
    assert snap(built, "T7", "201912").split == "oot1"
    assert snap(built, "T7", "202003").split == "oot2"
    assert snap(built, "T7", "202109").split == "oot2"
    assert snap(built, "T4", "202303").split == "oot3"


def test_holdout_is_loan_level_and_seeded(built):
    dev = built["df"][built["df"].split.isin(["dev_train", "dev_holdout"])]
    for loan, g in dev.groupby("loan_id"):
        assert g.split.nunique() == 1
        assert (g.split.iloc[0] == "dev_holdout") == holdout_flags([loan])[0]


def test_holdout_flags_share_and_determinism():
    ids = [f"F05Q1{i:07d}" for i in range(20_000)]
    a = holdout_flags(ids)
    assert a == holdout_flags(list(ids))
    assert 0.19 < sum(a) / len(a) < 0.21
    assert a != holdout_flags(ids, seed=1)


# ---------------------------------------------------------------- features


def test_payment_behaviour_features(built):
    r = snap(built, "T1", "200503")
    assert pd.isna(r.months_since_30dpd) and r.max_dlq_12m == 0
    r = snap(built, "T1", "200506")
    assert r.months_since_30dpd == 1 and r.max_dlq_12m == 1 and r.dpd_bucket == "current"
    r = snap(built, "T1", "200606")
    assert r.months_since_30dpd == 13 and r.max_dlq_12m == 0


def test_rate_spread_vs_same_origination_month(built):
    assert snap(built, "T1", "200503").rate_spread == pytest.approx(-0.5)
    assert snap(built, "T3", "200503").rate_spread == pytest.approx(0.5)


def test_ever_modified_persists(built):
    assert not snap(built, "T7", "201712").ever_modified
    assert snap(built, "T7", "201803").ever_modified
    assert snap(built, "T7", "202109").ever_modified


def test_current_ltv_indexed_to_state_hpi(built):
    # value = 200,000 / 0.80 x 110 / 100 = 275,000; LTV = 198,000 / 275,000 = 72%
    assert snap(built, "T1", "200606").current_ltv == pytest.approx(72.0)
    assert pd.isna(snap(built, "T1", "200609").current_ltv)  # no HPI for 2006Q3


def test_origination_quarter_is_first_payment_minus_one_month(built):
    assert snap(built, "T1", "200503").orig_month == pd.Timestamp(2005, 1, 1)


def test_ltv_above_100_is_kept(built):
    assert snap(built, "T3", "200503").orig_ltv == 150


def test_territory_falls_back_to_national_index(built):
    # value = 200,000 / 0.80 x 120 / 100 = 300,000; LTV = 200,000 / 300,000
    r = snap(built, "T8", "200606")
    assert r.hpi_fallback and r.current_ltv == pytest.approx(200 / 3)
    assert not snap(built, "T1", "200606").hpi_fallback


def test_territory_without_national_file_keeps_ltv_null(built):
    tmp = built["tmp"]
    with captured_log() as log:
        build_pd_dataset(
            tmp / "out",
            tmp / "pd_no_us",
            tmp / "reports_no_us",
            tmp / "hpi.csv",
            tmp / "missing_us.csv",
        )
    assert any(line.startswith("national HPI file not found") for line in log)
    df = duckdb.sql(f"""SELECT loan_id, current_ltv, hpi_fallback FROM read_parquet(
        '{(tmp / "pd_no_us").as_posix()}/*/*.parquet')""").df()
    t8 = df[df.loan_id == "T8"]
    assert t8.hpi_fallback.all() and t8.current_ltv.isna().all()


def test_missing_hpi_file_leaves_current_ltv_null(built):
    tmp = built["tmp"]
    with captured_log() as log:
        build_pd_dataset(
            tmp / "out", tmp / "pd_no_hpi", tmp / "reports_no_hpi", tmp / "missing.csv"
        )
    assert any(line.startswith("FHFA HPI file not found") for line in log)
    df = duckdb.sql(
        f"SELECT current_ltv FROM read_parquet('{(tmp / 'pd_no_hpi').as_posix()}/*/*.parquet')"
    ).df()
    assert df.current_ltv.isna().all()


# ---------------------------------------------------------------- summary tables


def test_summary_by_split(built):
    s = built["tables"]["by_split"].set_index("split")
    assert s.snapshots.sum() == 49
    assert s.loc["oot1", "snapshots"] == 12 and s.loc["oot2", "snapshots"] == 7
    assert s.loc["oot3", "obs_end"] == pd.Timestamp(date(2023, 12, 1))
    assert {"missing_orig_dti", "missing_current_ltv"} <= set(s.columns)


def test_ltv_by_year_table(built):
    t = built["tables"]["ltv_by_year"].set_index("year")
    assert t.loc[2006, "median_current_ltv"] > 0
    assert t.loc[2005, "hpi_fallback_share"] > 0  # T8 in PR
    assert (built["tmp"] / "reports_pd" / "pd_dataset_ltv_by_year.csv").exists()


def test_dti_harp_table_present(built):
    t = built["tables"]["dti_harp"]
    assert {"harp_loan", "dti_missing", "snapshots", "default_rate_b18"} <= set(t.columns)
    assert (built["tmp"] / "reports_pd" / "pd_dataset_dti_harp.csv").exists()
