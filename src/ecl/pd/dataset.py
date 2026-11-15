"""Module 2a: the 12-month PD modelling dataset (quarterly snapshots; no model fitting).

What it is: one row per loan per quarter-end (Mar/Jun/Sep/Dec) for loans not in default at
that date, with a 12-month default target and borrower, loan and payment-behaviour features.
It is a through-the-cycle (TTC) PD dataset, so it carries NO macro variables; macro
sensitivity is added in Module 3 (lifetime PD). RBI para 26 needs the PD at initial
recognition per loan, which the fitted model will provide from these features.

Targets (default in the 12 months after the snapshot, i.e. in (t, t+12m]):
    target_b18  primary: RBI 90+ default, except relief months cured within 18 months
                ("post-2014 relief adjustment": Freddie relief fields exist only from 2014, so
                before 2014 B-18 = A and crisis-era forbearance counts as default; conservative)
    target_b12  sensitivity: same with a 12-month cure window
    target_a    sensitivity: RBI 90+ default (paras 6(5), 8(1)), nothing relabelled
The population is "not in default under B-18"; elig_a / elig_b12 mark the rows that are also
default-free under A / B-12, and sensitivity default rates are computed on those rows.

Each quarter-end loan-month gets exactly one status, in this order (a waterfall):
    vintage_not_pd_ok              vintage has < 12 observation months with full labels
    in_default_a                   RBI default at the snapshot (90+, REO, loss termination)
    prior_default_b18              already defaulted under B-18 earlier
    terminated_at_snapshot         prepaid / RPL sale / defect (01, 16, 96) in that month
    before_dev_window              snapshot before 2000-01
    censored_window_after_data_end 12-month outcome + 18-month cure window ends after data end
    censored_lost_to_follow_up     loan stops reporting within 12 months with no termination
                                   code and no default in that window
    included
A loan that terminates with 01/16/96 before defaulting is a non-default up to termination.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

import duckdb
import pandas as pd

from ecl.data.hpi import (
    current_ltv_sql,
    hpi_fallback_sql,
    hpi_value_sql,
    load_hpi,
    orig_month_sql,
)

logger = logging.getLogger(__name__)

OUTCOME_MONTHS = 12
CURE_MONTHS = 18  # B-18 primary target
MIN_LABEL_MONTHS = 12  # same PD-OK rule as reports/summary/qc_by_vintage.csv
SNAPSHOT_MONTHS = (3, 6, 9, 12)
DEV_START = "2000-01-01"
SPLITS = [  # by observation date; oot3 runs to the last fully labelled date
    ("dev", "2016-12-31"),
    ("oot1", "2019-12-31"),
    ("oot2", "2021-12-31"),
    ("oot3", None),
]
HOLDOUT_SHARE = 0.20
SEED = 20261112
NON_DEFAULT_TERMINATIONS = ("01", "16", "96")

# Freddie "not available" codes for categorical fields -> NULL
CATEGORICAL_NA = {
    "occupancy_status": "'9'",
    "loan_purpose": "'9'",
    "property_type": "'99'",
    "channel": "'9'",
    "first_time_homebuyer": "'9'",
}
FEATURES = [
    "credit_score",
    "orig_ltv",
    "orig_cltv",
    "orig_dti",
    "harp_loan",
    "occupancy_status",
    "loan_purpose",
    "property_type",
    "num_units",
    "num_borrowers",
    "channel",
    "first_time_homebuyer",
    "orig_interest_rate",
    "rate_spread",
    "loan_age",
    "months_since_30dpd",
    "max_dlq_12m",
    "dpd_bucket",
    "ever_deferred",
    "ever_modified",
    "current_ltv",
]
STATUSES = [
    "vintage_not_pd_ok",
    "in_default_a",
    "prior_default_b18",
    "terminated_at_snapshot",
    "before_dev_window",
    "censored_window_after_data_end",
    "censored_lost_to_follow_up",
    "included",
]


def holdout_flags(
    loan_ids: list[str], seed: int = SEED, share: float = HOLDOUT_SHARE
) -> list[bool]:
    """Loan-level random holdout from a hash of (seed, loan_id): reproducible and independent
    of row order or of which vintages are processed together."""

    def u(lid: str) -> float:
        return int.from_bytes(hashlib.sha256(f"{seed}:{lid}".encode()).digest()[:8], "big") / 2**64

    return [u(lid) < share for lid in loan_ids]


def create_orig_table(con: duckdb.DuckDBPyConnection) -> None:
    """Table `orig`: origination month (first payment - 1 month) and same-month rate spread,
    over every loan in every vintage (view `loans_all` must exist)."""
    con.execute(f"""
        CREATE OR REPLACE TABLE orig AS
        SELECT loan_id, {orig_month_sql("first_payment_date")} AS orig_month,
               -- note rates have 3 decimals: the month mean is taken over an exact DECIMAL
               -- sum, so it does not depend on the order DuckDB's threads add the rows
               orig_interest_rate - AVG(CAST(orig_interest_rate AS DECIMAL(9, 3)))
                   OVER (PARTITION BY {orig_month_sql("first_payment_date")})::DOUBLE AS rate_spread
        FROM loans_all
    """)


def categorical_sql(alias: str = "l") -> dict[str, str]:
    """Categorical loan fields with Freddie 'not available' codes and blanks -> NULL."""
    return {c: f"NULLIF(NULLIF(trim({alias}.{c}), ''), {na})" for c, na in CATEGORICAL_NA.items()}


def split_sql(col: str) -> str:
    """SQL CASE expression assigning a snapshot to its time split (development, out-of-time
    periods) by the date in `col`."""
    cases = " ".join(f"WHEN {col} <= DATE '{end}' THEN '{name}'" for name, end in SPLITS if end)
    return f"CASE {cases} ELSE '{SPLITS[-1][0]}' END"


def window_cte(panel_file: str, term_codes: str, as_at: str | None = None) -> str:
    """`WITH w AS (...)`: per loan-month, the past-window behaviour features (months since 30+
    dpd, worst status in 12 months, ever modified) and the future dates the targets need.
    With `as_at`, only panel months up to that date are read (no look-ahead: scoring)."""
    where = f"WHERE period <= DATE '{as_at}'" if as_at else ""
    return f"""WITH w AS (
                SELECT loan_id, period, months_dlq, dpd_bucket, default_event, zb_code,
                    current_upb, loan_age, ever_deferred, remaining_months, current_rate,
                    first_default_period, first_default_period_b12, first_default_period_b18,
                    MIN(CASE WHEN default_event THEN period END) OVER fut     AS next_def_a,
                    MIN(CASE WHEN default_event_b12 THEN period END) OVER fut AS next_def_b12,
                    MIN(CASE WHEN default_event_b18 THEN period END) OVER fut AS next_def_b18,
                    MIN(CASE WHEN zb_code IN ({term_codes}) THEN period END) OVER fut AS next_term,
                    MAX(CASE WHEN months_dlq >= 1 THEN period END) OVER past  AS last_30dpd,
                    MAX(months_dlq) OVER (PARTITION BY loan_id ORDER BY period
                        RANGE BETWEEN INTERVAL 11 MONTH PRECEDING AND CURRENT ROW) AS max_dlq_12m,
                    COALESCE(BOOL_OR(modified) OVER past, FALSE)              AS ever_modified,
                    MAX(period) OVER (PARTITION BY loan_id)                   AS last_period,
                    MAX(zb_code) OVER (PARTITION BY loan_id)                  AS final_zb
                FROM read_parquet('{panel_file}') {where}
                WINDOW fut AS (PARTITION BY loan_id ORDER BY period
                               ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING),
                       past AS (PARTITION BY loan_id ORDER BY period
                               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
            )"""


def feature_sql(categorical: dict, ltv: str, fallback: str) -> str:
    """Feature columns of a snapshot row (s = window row, l = loan, o = origination month)."""
    return f"""l.credit_score, l.orig_ltv, l.orig_cltv, l.orig_dti, l.harp_loan,
                    {categorical["occupancy_status"]}                     AS occupancy_status,
                    {categorical["loan_purpose"]}                         AS loan_purpose,
                    {categorical["property_type"]}                        AS property_type,
                    NULLIF(l.num_units, 99)                               AS num_units,
                    NULLIF(l.num_borrowers, 99)                           AS num_borrowers,
                    {categorical["channel"]}                              AS channel,
                    {categorical["first_time_homebuyer"]}                 AS first_time_homebuyer,
                    l.orig_interest_rate, o.rate_spread, s.loan_age,
                    datediff('month', s.last_30dpd, s.period)             AS months_since_30dpd,
                    s.max_dlq_12m, s.dpd_bucket, s.ever_deferred, s.ever_modified,
                    {ltv}                                                 AS current_ltv,
                    {fallback}                                            AS hpi_fallback,
                    l.property_state, o.orig_month, s.current_upb"""


def score_unknown_status_as_current(df: pd.DataFrame) -> pd.DataFrame:
    """Status XX ('unknown') -> 'current' for scoring, flagged `dpd_status_unknown`."""
    out = df.copy()
    out["dpd_status_unknown"] = out.dpd_bucket.eq("unknown")
    out.loc[out.dpd_status_unknown, "dpd_bucket"] = "current"
    return out


def build_scoring_snapshot(
    processed: Path,
    as_at: str,
    hpi_path: Path | None,
    national_path: Path | None = None,
    exclude_prior_default: bool = True,
) -> pd.DataFrame:
    """Scoring-only snapshot: every live loan of every vintage at month `as_at` (YYYY-MM-01),
    with the PD dataset's features and no targets (Module 4 reporting dates; docs/methodology/scenarios.md).

    Population: observed in that month; not in RBI default (90+ / REO / loss termination, paras
    6(5), 8(1)); no earlier B-18 default; no zero-balance code in that month. Features use panel
    months up to `as_at` only. Adds remaining months (`rm`) and the note rate (`rate`) for the
    lifetime projection. Note: `first_default_period_b18` is a per-loan field whose relief cure
    can look up to 18 months ahead; it only removes loans already treated as defaulted.
    exclude_prior_default=False keeps loans that defaulted earlier and are out of default now
    (staging: para 77 curing; the PD dataset convention drops them).

    Delinquency status XX ('unknown': not yet reported, almost always a loan in its first months)
    is scored as 'current' and flagged `dpd_status_unknown`: the scorecard has no state for it
    (training snapshots never had it), there is no evidence of arrears, and the cured states
    still come from the observed history. Without this the loan's PD is missing."""
    con = duckdb.connect()
    for kind in ["loans", "panel"]:
        glob = (processed / kind).as_posix() + "/*/*.parquet"
        con.execute(
            f"CREATE VIEW {kind}_all AS SELECT * FROM read_parquet('{glob}', hive_partitioning=true)"
        )
    create_orig_table(con)
    if hpi_path is not None and hpi_path.exists():
        load_hpi(con, hpi_path, national_path)
        join_now, hpi_now = hpi_value_sql("l.property_state", "s.period", "h_now")
        join_orig, hpi_orig = hpi_value_sql("l.property_state", "o.orig_month", "h_orig")
        ltv = current_ltv_sql("s.current_upb", "l.orig_upb", "l.orig_ltv", hpi_now, hpi_orig)
        hpi_join, fallback = join_now + join_orig, hpi_fallback_sql("l.property_state")
    else:
        logger.warning(f"FHFA HPI file not found ({hpi_path}); current_ltv left NULL.")
        ltv, hpi_join, fallback = "CAST(NULL AS DOUBLE)", "", "CAST(NULL AS BOOLEAN)"
    term_codes = ", ".join(f"'{c}'" for c in NON_DEFAULT_TERMINATIONS)
    vintages = [
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT vintage FROM panel_all WHERE period <= DATE '{as_at}' ORDER BY 1"
        ).fetchall()
    ]
    parts = []
    for vintage in vintages:
        panel_file = (processed / "panel" / f"vintage={vintage}" / "data.parquet").as_posix()
        parts.append(
            con.execute(f"""
            {window_cte(panel_file, term_codes, as_at)}
            SELECT s.loan_id, {vintage} AS vintage, s.period AS obs_date,
                {feature_sql(categorical_sql("l"), ltv, fallback)},
                s.remaining_months AS rm, s.current_rate AS rate
            FROM w s
            JOIN loans_all l ON l.loan_id = s.loan_id AND l.vintage = {vintage}
            LEFT JOIN orig o ON o.loan_id = s.loan_id
            {hpi_join}
            WHERE s.period = DATE '{as_at}' AND NOT s.default_event
              AND ({not exclude_prior_default} OR COALESCE(s.first_default_period_b18 > s.period, TRUE))
              AND s.zb_code IS NULL
            ORDER BY s.loan_id
        """).df()
        )
    con.close()
    out = pd.concat(parts, ignore_index=True).sort_values("loan_id", ignore_index=True)
    out = score_unknown_status_as_current(out)
    logger.info(
        f"Scoring snapshot {as_at}: {len(out):,} loans, {out.vintage.nunique()} vintages, "
        f"{int(out.dpd_status_unknown.sum()):,} with status XX scored as current"
    )
    return out


def build_pd_dataset(
    processed: Path,
    out: Path,
    reports: Path,
    hpi_path: Path | None,
    national_path: Path | None = None,
    seed: int = SEED,
) -> dict[str, pd.DataFrame]:
    """Build the 12-month PD modelling dataset from the loan-month panel: quarterly snapshots of
    loans not in default, with targets (default within the next 12 months under B-18, B-12 and
    the RBI 90+ definition), features and time splits. Writes the loan-level dataset to `out`
    (Parquet, one partition per split) and aggregate tables to `reports`; returns the
    aggregate tables."""
    con = duckdb.connect()
    panel_glob = (processed / "panel").as_posix() + "/*/*.parquet"
    loans_glob = (processed / "loans").as_posix() + "/*/*.parquet"
    con.execute(
        f"CREATE VIEW panel_all AS SELECT * FROM read_parquet('{panel_glob}', hive_partitioning=true)"
    )
    con.execute(
        f"CREATE VIEW loans_all AS SELECT * FROM read_parquet('{loans_glob}', hive_partitioning=true)"
    )

    data_end = con.execute("SELECT MAX(period) FROM panel_all").fetchone()[0]
    label_end = con.execute(
        f"SELECT (DATE '{data_end}' - INTERVAL {OUTCOME_MONTHS + CURE_MONTHS} MONTH)::DATE"
    ).fetchone()[0]
    vintages = con.execute(f"""
        SELECT vintage, datediff('month', MIN(period), DATE '{label_end}') + 1 >= {MIN_LABEL_MONTHS}
        FROM panel_all GROUP BY 1 ORDER BY 1
    """).fetchall()
    logger.info(f"Data end {data_end}; last fully labelled snapshot {label_end}")

    create_orig_table(con)

    # ---- HPI-indexed current LTV (state index; national fallback for PR/GU/VI) ----
    if hpi_path is not None and hpi_path.exists():
        n = load_hpi(con, hpi_path, national_path)
        logger.info(
            f"Loaded {n['state']:,} state HPI rows from {hpi_path.name}; "
            f"{n['national']:,} national rows"
        )
        if n["national"] == 0:
            logger.warning(
                f"national HPI file not found ({national_path}); loans in states missing "
                "from the state file keep current_ltv NULL (hpi_fallback = TRUE)."
            )
        join_now, hpi_now = hpi_value_sql("l.property_state", "s.period", "h_now")
        join_orig, hpi_orig = hpi_value_sql("l.property_state", "o.orig_month", "h_orig")
        hpi_join = join_now + join_orig
        ltv = current_ltv_sql("s.current_upb", "l.orig_upb", "l.orig_ltv", hpi_now, hpi_orig)
        fallback = hpi_fallback_sql("l.property_state")
    else:
        logger.warning(
            f"FHFA HPI file not found ({hpi_path}); current_ltv left NULL. Download the "
            "FHFA all-transactions state index (quarterly CSV) to data/macro/ and rerun."
        )
        ltv, hpi_join, fallback = "CAST(NULL AS DOUBLE)", "", "CAST(NULL AS BOOLEAN)"

    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    waterfall = []
    categorical = categorical_sql("l")
    term_codes = ", ".join(f"'{c}'" for c in NON_DEFAULT_TERMINATIONS)

    for vintage, pd_ok in vintages:
        panel_file = (processed / "panel" / f"vintage={vintage}" / "data.parquet").as_posix()
        con.execute(f"""
            CREATE OR REPLACE TABLE snaps AS
            {window_cte(panel_file, term_codes)}
            SELECT *,
                CASE
                    WHEN NOT {pd_ok} THEN 'vintage_not_pd_ok'
                    WHEN default_event THEN 'in_default_a'
                    WHEN first_default_period_b18 <= period THEN 'prior_default_b18'
                    WHEN zb_code IS NOT NULL THEN 'terminated_at_snapshot'
                    WHEN period < DATE '{DEV_START}' THEN 'before_dev_window'
                    WHEN period > DATE '{label_end}' THEN 'censored_window_after_data_end'
                    -- outcome unknown: stops reporting inside the window with no termination
                    -- code and no default seen (a default settles the outcome)
                    WHEN final_zb IS NULL
                         AND last_period < period + INTERVAL {OUTCOME_MONTHS} MONTH
                         AND COALESCE(next_def_a > period + INTERVAL {OUTCOME_MONTHS} MONTH, TRUE)
                        THEN 'censored_lost_to_follow_up'
                    ELSE 'included'
                END AS status,
                {split_sql("period")} AS split
            FROM w WHERE month(period) IN {SNAPSHOT_MONTHS}
        """)
        waterfall += con.execute(f"""
            SELECT {vintage} AS vintage, status, COUNT(*) AS snapshots,
                   COUNT(DISTINCT loan_id) AS loans
            FROM snaps GROUP BY ALL ORDER BY ALL
        """).fetchall()

        # loan-level 80/20 holdout within the development window
        dev_ids = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT loan_id FROM snaps WHERE status = 'included' AND split = 'dev' "
                "ORDER BY 1"
            ).fetchall()
        ]
        holdout = pd.DataFrame({"loan_id": dev_ids, "holdout": holdout_flags(dev_ids, seed)})
        con.register("holdout_df", holdout)

        horizon = f"s.period + INTERVAL {OUTCOME_MONTHS} MONTH"
        con.execute(f"""
            COPY (
                SELECT s.loan_id, {vintage} AS vintage, s.period AS obs_date,
                    CASE WHEN s.split = 'dev' AND h.holdout THEN 'dev_holdout'
                         WHEN s.split = 'dev' THEN 'dev_train' ELSE s.split END AS split,
                    COALESCE(s.next_def_b18 <= {horizon}, FALSE)          AS target_b18,
                    COALESCE(s.next_def_b12 <= {horizon}, FALSE)          AS target_b12,
                    COALESCE(s.next_def_a <= {horizon}, FALSE)            AS target_a,
                    COALESCE(s.first_default_period > s.period, TRUE)     AS elig_a,
                    COALESCE(s.first_default_period_b12 > s.period, TRUE) AS elig_b12,
                    COALESCE(s.next_term <= {horizon}
                        AND s.next_term < COALESCE(s.next_def_b18, DATE '9999-12-31'), FALSE)
                                                                          AS terminated_within_12m,
                    {feature_sql(categorical, ltv, fallback)}
                FROM snaps s
                JOIN loans_all l ON l.loan_id = s.loan_id AND l.vintage = {vintage}
                LEFT JOIN orig o ON o.loan_id = s.loan_id
                LEFT JOIN holdout_df h ON h.loan_id = s.loan_id
                {hpi_join}
                WHERE s.status = 'included'
                ORDER BY s.loan_id, s.period
            ) TO '{out.as_posix()}'
            (FORMAT PARQUET, PARTITION_BY (split), FILENAME_PATTERN 'v{vintage}_{{i}}',
             OVERWRITE_OR_IGNORE)
        """)
        con.unregister("holdout_df")
        n_inc = sum(r[2] for r in waterfall if r[0] == vintage and r[1] == "included")
        logger.info(
            f"  {vintage}: {n_inc:,} snapshots included" + ("" if pd_ok else " (vintage not PD-OK)")
        )

    tables = summarise(con, out, waterfall)
    reports.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(reports / f"pd_dataset_{name}.csv", index=False)
    con.close()
    return tables


def summarise(
    con: duckdb.DuckDBPyConnection, out: Path, waterfall: list
) -> dict[str, pd.DataFrame]:
    """Aggregate tables only (no loan-level data): waterfall, per-split summary, DTI/HARP."""
    wf = pd.DataFrame(waterfall, columns=["vintage", "status", "snapshots", "loans"])
    wf = (
        wf.groupby("status")[["snapshots", "loans"]]
        .sum()
        .reindex(STATUSES, fill_value=0)
        .reset_index()
    )
    wf["share"] = wf.snapshots / wf.snapshots.sum()

    con.execute(f"""
        CREATE OR REPLACE VIEW ds AS
        SELECT * FROM read_parquet('{out.as_posix()}/*/*.parquet', hive_partitioning=true)
    """)
    missing = ", ".join(f"AVG(({f} IS NULL)::INT) AS missing_{f}" for f in FEATURES)
    order = (
        "CASE split WHEN 'dev_train' THEN 1 WHEN 'dev_holdout' THEN 2 WHEN 'oot1' THEN 3 "
        "WHEN 'oot2' THEN 4 ELSE 5 END"
    )
    by_split = con.execute(f"""
        SELECT split, MIN(obs_date) AS obs_start, MAX(obs_date) AS obs_end,
            COUNT(*) AS snapshots, COUNT(DISTINCT loan_id) AS loans,
            AVG(target_b18::INT) AS default_rate_b18,
            AVG(target_b12::INT) FILTER (elig_b12) AS default_rate_b12,
            AVG(target_a::INT) FILTER (elig_a) AS default_rate_a,
            SUM(target_b18::INT) AS defaults_b18,
            AVG(terminated_within_12m::INT) AS terminated_within_12m_share,
            {missing}
        FROM ds GROUP BY split ORDER BY {order}
    """).df()

    dti_harp = con.execute(f"""
        SELECT split, harp_loan, orig_dti IS NULL AS dti_missing,
            COUNT(*) AS snapshots, COUNT(DISTINCT loan_id) AS loans,
            AVG(target_b18::INT) AS default_rate_b18
        FROM ds GROUP BY split, harp_loan, dti_missing ORDER BY {order}, 2, 3
    """).df()
    # sanity check: indexed LTV should rise sharply in 2009-11 (price falls) and fall after 2013
    ltv_by_year = con.execute("""
        SELECT year(obs_date) AS year, COUNT(*) AS snapshots,
            MEDIAN(orig_ltv) AS median_orig_ltv,
            MEDIAN(current_ltv) AS median_current_ltv,
            QUANTILE_CONT(current_ltv, 0.9) AS p90_current_ltv,
            AVG((current_ltv > 100)::INT) FILTER (current_ltv IS NOT NULL) AS share_ltv_over_100,
            AVG((current_ltv IS NULL)::INT) AS missing_current_ltv,
            AVG(hpi_fallback::INT) AS hpi_fallback_share
        FROM ds GROUP BY 1 ORDER BY 1
    """).df()
    return {"waterfall": wf, "by_split": by_split, "dti_harp": dti_harp, "ltv_by_year": ltv_by_year}
