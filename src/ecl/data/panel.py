"""
Module 1: build the loan-month panel from Freddie Mac sample files (Release 47 layout).

Usage:
    ecl build-panel                      # every vintage found in data/raw
    ecl build-panel --vintages 2005-2007 # rebuild a subset (e.g. 2005-2007,2017)

Inputs: <raw-dir>/sample_orig_YYYY.txt and sample_perf_YYYY.txt, one pair per vintage.
Every line of every file is checked for the configured column count before anything loads.

Outputs (one vintage at a time, so memory use is bounded by the largest vintage):
    <out>/loans/vintage=YYYY/data.parquet   one row per loan, origination features
    <out>/panel/vintage=YYYY/data.parquet   one row per loan per month, with staging fields
    <out>/ecl.duckdb                        views loans_all / panel_all over all vintages
    <reports>/qc_by_vintage.csv             QC summary, one row per vintage
    <reports>/first_defaults_by_year.csv    first defaults by calendar year (all vintages)
    (<reports> defaults to reports/summary/: aggregates only, tracked in git)
Rebuilding a vintage replaces its partition, so re-runs are idempotent.

Default definition (RBI ECL Directions 2026, para 6(5) and 8(1)) -- "Option A":
    more than 90 days overdue -> delinquency_status >= 03 (03 = 90-119 days) or RA.
    Loss-type terminations (zero balance codes 02, 03, 09, 15) also count.
    Monthly data cannot separate day 90 from day 91: status 03 is the documented proxy.
    -> default_event / first_default_period. Used for staging and Stage 3.

PD training targets (modelling choice, "Option B"; NOT the regulatory default definition):
    a default month is relabelled as non-default if the loan was under relief that month
    (forbearance F, deferral C, disaster Y), is back to current within n months, and has no
    loss-type termination in that window. These are payment pauses, not credit losses.
    -> relief_cured_b<n> / default_event_b<n> / first_default_period_b<n> for n in --cure-months.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import yaml

from ecl.common import project_root

if TYPE_CHECKING:
    import pandas as pd

ROOT = project_root()

logger = logging.getLogger(__name__)
PD_LABEL_MIN_MONTHS = 12  # months of observation points with fully observed labels


def load_layout() -> dict:
    """Freddie Mac file layout (Release 47) from config/freddie_layout.yaml."""
    with open(ROOT / "config" / "freddie_layout.yaml") as f:
        return yaml.safe_load(f)


def check_columns(path: Path, expected: list[str], name: str) -> None:
    """Count fields on every line (not just the first): null_padding would hide short lines."""
    counts = duckdb.sql(f"""
        SELECT len(line) - len(replace(line, '|', '')) + 1 AS n, COUNT(*) AS lines
        FROM read_csv('{path.as_posix()}', columns={{'line': 'VARCHAR'}}, delim=chr(1),
                      header=false, quote='', escape='', auto_detect=false)
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()
    if [n for n, _ in counts] != [len(expected)]:
        found = ", ".join(f"{lines:,} lines with {n}" for n, lines in counts)
        raise SystemExit(
            f"\n{name} file {path.name} does not have {len(expected)} columns on every line "
            f"(found: {found}).\n"
            "Fix config/freddie_layout.yaml to match the user guide's file layout."
        )


def read_sql(path: Path, cols: list[str]) -> str:
    """DuckDB read_csv expression for a pipe-delimited, header-less Freddie file with every
    column read as text (types are cast explicitly later)."""
    col_spec = "{" + ", ".join(f"'{c}': 'VARCHAR'" for c in cols) + "}"
    return (
        f"read_csv('{path.as_posix()}', delim='|', header=false, quote='', "
        f"columns={col_spec}, null_padding=true)"
    )


def parse_vintages(spec: str | None, available: list[str]) -> list[str]:
    """'2005-2007,2017' -> ['2005', '2006', '2007', '2017']; None -> all available."""
    if not spec:
        return available
    wanted = set()
    for part in spec.split(","):
        lo, _, hi = part.strip().partition("-")
        wanted.update(str(y) for y in range(int(lo), int(hi or lo) + 1))
    missing = sorted(wanted - set(available))
    if missing:
        raise SystemExit(f"No raw files for vintage(s): {', '.join(missing)}")
    return sorted(wanted)


def find_vintages(raw: Path) -> list[str]:
    """Vintages with both an origination and a performance file in `raw`; stops if a vintage has
    only one of the two."""
    orig = {
        m.group(1)
        for p in raw.glob("sample_orig_*.txt")
        if (m := re.fullmatch(r"sample_orig_(\d{4})\.txt", p.name))
    }
    perf = {
        m.group(1)
        for p in raw.glob("sample_perf_*.txt")
        if (m := re.fullmatch(r"sample_perf_(\d{4})\.txt", p.name))
    }
    unpaired = sorted(orig ^ perf)
    if unpaired:
        raise SystemExit(f"Missing orig or perf file for vintage(s): {', '.join(unpaired)}")
    return sorted(orig)


def write_partition(
    con: duckdb.DuckDBPyConnection, table: str, out: Path, kind: str, vintage: str
) -> None:
    """Write to a staging file, then swap it in, so a crash never leaves half a partition."""
    staging = out / "_staging" / f"{kind}_{vintage}.parquet"
    staging.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY {table} TO '{staging.as_posix()}' (FORMAT PARQUET)")
    target = out / kind / f"vintage={vintage}"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    staging.replace(target / "data.parquet")


def build_vintage(
    vintage: str, orig: Path, perf: Path, out: Path, layout: dict, cure_months: list[int]
) -> None:
    """Load one vintage, derive the panel fields (dpd bucket, RBI default event and first
    default, relief flags, B-n relabelling) and write the loans and panel partitions."""
    default_codes = ", ".join(f"'{c}'" for c in layout["default_zero_balance_codes"])
    con = duckdb.connect()
    con.execute(f"SET temp_directory = '{(out / '_staging' / 'spill').as_posix()}'")

    # ---- Loans: one row per loan, typed, sentinel codes -> NULL ----
    con.execute(f"""
        CREATE TABLE loans AS
        SELECT
            trim(loan_id)                                         AS loan_id,
            NULLIF(TRY_CAST(credit_score AS INT), 9999)           AS credit_score,
            NULLIF(TRY_CAST(vantage_score_4 AS INT), 9999)        AS vantage_score_4,
            strptime(trim(first_payment_date), '%Y%m')::DATE      AS first_payment_date,
            NULLIF(TRY_CAST(orig_ltv AS INT), 999)                AS orig_ltv,
            NULLIF(TRY_CAST(orig_cltv AS INT), 999)               AS orig_cltv,
            NULLIF(TRY_CAST(orig_dti AS INT), 999)                AS orig_dti,
            TRY_CAST(orig_upb AS DOUBLE)                          AS orig_upb,
            TRY_CAST(orig_interest_rate AS DOUBLE)                AS orig_interest_rate,
            TRY_CAST(orig_loan_term AS INT)                       AS orig_loan_term,
            TRY_CAST(num_borrowers AS INT)                        AS num_borrowers,
            TRY_CAST(num_units AS INT)                            AS num_units,
            TRY_CAST(mi_pct AS DOUBLE)                            AS mi_pct,
            trim(first_time_homebuyer)                            AS first_time_homebuyer,
            trim(occupancy_status)                                AS occupancy_status,
            trim(loan_purpose)                                    AS loan_purpose,
            trim(property_type)                                   AS property_type,
            trim(property_state)                                  AS property_state,
            trim(channel)                                         AS channel,
            COALESCE(trim(harp_indicator) = 'Y', FALSE)           AS harp_loan,
            COALESCE(trim(pre_harp_loan_id) <> '', FALSE)         AS has_pre_harp_link
        FROM {read_sql(orig, layout["origination"])}
    """)

    # ---- Panel: one row per loan-month ----
    con.execute(f"""
        CREATE TABLE panel AS
        SELECT
            trim(loan_id)                                         AS loan_id,
            strptime(trim(reporting_period), '%Y%m')::DATE        AS period,
            TRY_CAST(current_upb AS DOUBLE)                       AS current_upb,
            trim(delinquency_status)                              AS dlq_raw,
            TRY_CAST(trim(delinquency_status) AS INT)             AS months_dlq,
            trim(delinquency_status) = 'RA'                       AS reo_acquired,
            TRY_CAST(loan_age AS INT)                             AS loan_age,
            TRY_CAST(remaining_months AS INT)                     AS remaining_months,
            TRY_CAST(current_interest_rate AS DOUBLE)             AS current_rate,
            NULLIF(trim(zero_balance_code), '')                   AS zb_code,
            trim(modification_flag) = 'Y'                         AS modified,
            trim(payment_deferral) = 'C'                          AS payment_deferral,
            trim(payment_deferral) = 'P'                          AS deferral_prior,
            trim(delinquency_due_to_disaster) = 'Y'               AS disaster_dlq,
            NULLIF(trim(borrower_assistance_status), '')          AS assistance_status,
            NULLIF(TRY_CAST(eltv AS DOUBLE), 999)                 AS eltv,
            TRY_CAST(net_sale_proceeds AS DOUBLE)                 AS net_sale_proceeds,
            TRY_CAST(mi_recoveries AS DOUBLE)                     AS mi_recoveries,
            TRY_CAST(non_mi_recoveries AS DOUBLE)                 AS non_mi_recoveries,
            TRY_CAST(total_expenses AS DOUBLE)                    AS total_expenses,
            TRY_CAST(actual_loss AS DOUBLE)                       AS actual_loss,
            TRY_CAST(bankruptcy_cramdown_costs AS DOUBLE)         AS bankruptcy_cramdown_costs,
            NULLIF(trim(servicer_name), '')                       AS servicer_name
        FROM {read_sql(perf, layout["performance"])}
    """)

    # ---- Derived staging fields and PD training targets (one set per cure window) ----
    fwd_cols = ",\n".join(
        f"""
                COALESCE(BOOL_OR(months_dlq = 0) OVER (PARTITION BY loan_id ORDER BY period
                    RANGE BETWEEN INTERVAL 1 MONTH FOLLOWING
                              AND INTERVAL {n} MONTH FOLLOWING), FALSE) AS cures_in_{n},
                COALESCE(BOOL_OR(zb_code IN ({default_codes})) OVER (PARTITION BY loan_id
                    ORDER BY period RANGE BETWEEN CURRENT ROW
                              AND INTERVAL {n} MONTH FOLLOWING), FALSE) AS loss_in_{n}"""
        for n in cure_months
    )
    helper_cols = ", ".join(f"cures_in_{n}, loss_in_{n}" for n in cure_months)
    cured_cols = ",\n".join(
        f"""
                default_event AND relief_flag AND cures_in_{n}
                    AND NOT loss_in_{n}                           AS relief_cured_b{n}"""
        for n in cure_months
    )
    target_cols = ",\n".join(
        f"""
            default_event AND NOT relief_cured_b{n}               AS default_event_b{n},
            MIN(CASE WHEN default_event AND NOT relief_cured_b{n} THEN period END)
                OVER (PARTITION BY loan_id)                       AS first_default_period_b{n}"""
        for n in cure_months
    )
    con.execute(f"""
        CREATE TABLE panel_final AS
        WITH base AS (
            SELECT *,
                CASE
                    WHEN reo_acquired OR months_dlq >= 3 THEN '90+'
                    WHEN months_dlq = 2 THEN '60-89'
                    WHEN months_dlq = 1 THEN '30-59'
                    WHEN months_dlq = 0 THEN 'current'
                    ELSE 'unknown'
                END AS dpd_bucket,
                COALESCE(reo_acquired OR months_dlq >= 3
                    OR zb_code IN ({default_codes}), FALSE)       AS default_event,
                COALESCE(assistance_status = 'F', FALSE)
                    OR COALESCE(payment_deferral, FALSE)
                    OR COALESCE(disaster_dlq, FALSE)              AS relief_flag,
                -- feature only (not relief): Freddie keeps 'P' after a deferral month
                COALESCE(BOOL_OR(deferral_prior) OVER (PARTITION BY loan_id ORDER BY period
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), FALSE) AS ever_deferred
            FROM panel
        ),
        fwd AS (
            SELECT *, {fwd_cols}
            FROM base
        ),
        labelled AS (
            SELECT * EXCLUDE ({helper_cols}, deferral_prior), {cured_cols}
            FROM fwd
        )
        SELECT *,
            -- first default per loan: everything after this is post-default history
            MIN(CASE WHEN default_event THEN period END)
                OVER (PARTITION BY loan_id)                       AS first_default_period,
            {target_cols}
        FROM labelled
    """)

    write_partition(con, "loans", out, "loans", vintage)
    write_partition(con, "panel_final", out, "panel", vintage)

    # ---- One-line log per vintage, incl. how many defaults each option relabels ----
    n_loans = con.execute("SELECT COUNT(*) FROM loans").fetchone()[0]
    n_rows, n_def = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT CASE WHEN default_event THEN loan_id END) FROM panel_final"
    ).fetchone()
    parts = [f"{vintage}: {n_loans:,} loans, {n_rows:,} loan-months, A: {n_def:,} defaulted loans"]
    for n in cure_months:
        removed, moved = con.execute(f"""
            SELECT COUNT(*) FILTER (fa IS NOT NULL AND fb IS NULL),
                   COUNT(*) FILTER (fa IS NOT NULL AND fb > fa)
            FROM (SELECT DISTINCT loan_id, first_default_period AS fa,
                         first_default_period_b{n} AS fb FROM panel_final)""").fetchone()
        parts.append(f"B-{n} relabels {removed + moved:,} ({removed:,} never, {moved:,} later)")
    logger.info("  " + "; ".join(parts))
    con.close()


def create_views(out: Path) -> duckdb.DuckDBPyConnection:
    """Persistent views over every vintage partition; new partitions are picked up by the glob."""
    con = duckdb.connect(str(out / "ecl.duckdb"))
    for kind in ["loans", "panel"]:
        con.execute(f"""
            CREATE OR REPLACE VIEW {kind}_all AS
            SELECT * FROM read_parquet('{(out / kind).as_posix()}/*/*.parquet',
                                       hive_partitioning = true)
        """)
    return con


def qc_by_vintage(
    con: duckdb.DuckDBPyConnection, cure_months: list[int], loss_codes: str
) -> pd.DataFrame:
    """QC summary, one row per vintage, from the views (so it covers every built vintage)."""
    first_cols = ", ".join(f"ANY_VALUE(first_default_period_b{n}) AS fb{n}" for n in cure_months)
    rate_cols = ", ".join(
        f"AVG((fb{n} IS NOT NULL)::INT) AS ever_default_b{n}" for n in cure_months
    )
    max_cure = max(cure_months)
    return con.execute(f"""
        WITH lp AS (
            SELECT vintage, loan_id,
                ANY_VALUE(first_default_period) AS fa, {first_cols},
                -- COALESCE: zb_code is NULL on most rows, and AVG would skip NULLs
                COALESCE(BOOL_OR(zb_code IN {loss_codes}), FALSE)       AS loss_term,
                COALESCE(BOOL_OR(zb_code IN {loss_codes}
                                 AND actual_loss IS NOT NULL), FALSE)   AS loss_amt,
                COALESCE(BOOL_OR(zb_code = '01'), FALSE)                AS prepaid
            FROM panel_all GROUP BY ALL
        ),
        lp_agg AS (
            SELECT vintage, COUNT(*) AS perf_loans,
                AVG((fa IS NOT NULL)::INT) AS ever_default_a, {rate_cols},
                SUM(loss_term::INT) AS loss_terminations,
                SUM(loss_amt::INT) AS loss_with_actual_loss,
                AVG(prepaid::INT) AS prepay_share
            FROM lp GROUP BY 1
        ),
        pm AS (
            SELECT vintage, COUNT(*) AS loan_months,
                MIN(period) AS first_period, MAX(period) AS last_period,
                COUNT(*) - COUNT(DISTINCT (loan_id, period)) AS duplicate_loan_months,
                AVG(relief_flag::INT) AS relief_month_share,
                AVG((eltv IS NULL)::INT) AS missing_eltv
            FROM panel_all GROUP BY 1
        ),
        ln AS (
            SELECT vintage, COUNT(*) AS loans,
                AVG(harp_loan::INT) AS harp_share,
                AVG((credit_score IS NULL)::INT) AS missing_credit_score,
                AVG((orig_ltv IS NULL)::INT) AS missing_orig_ltv,
                AVG((orig_dti IS NULL)::INT) AS missing_orig_dti
            FROM loans_all GROUP BY 1
        ),
        orphans AS (
            SELECT p.vintage, COUNT(*) AS orphan_loans
            FROM (SELECT DISTINCT vintage, loan_id FROM lp) p
            ANTI JOIN loans_all l ON p.vintage = l.vintage AND p.loan_id = l.loan_id
            GROUP BY 1
        ),
        data_end AS (SELECT MAX(last_period) AS d FROM pm)
        SELECT ln.vintage, ln.loans, pm.loan_months, pm.first_period, pm.last_period,
            COALESCE(orphans.orphan_loans, 0) AS orphan_loans, pm.duplicate_loan_months,
            lp_agg.* EXCLUDE (vintage, perf_loans),
            pm.relief_month_share, ln.harp_share,
            ln.missing_credit_score, ln.missing_orig_ltv, ln.missing_orig_dti, pm.missing_eltv,
            -- observation months whose 12-month outcome and {max_cure}-month cure window are
            -- fully observed before the data end
            GREATEST(0, datediff('month', pm.first_period,
                data_end.d - INTERVAL {12 + max_cure} MONTH) + 1) AS months_full_label,
            months_full_label >= {PD_LABEL_MIN_MONTHS} AS pd_training_ok
        FROM ln
        JOIN pm USING (vintage)
        JOIN lp_agg USING (vintage)
        LEFT JOIN orphans USING (vintage)
        CROSS JOIN data_end
        ORDER BY ln.vintage
    """).df()


def first_defaults_by_year(
    con: duckdb.DuckDBPyConnection, cure_months: list[int], loss_codes: str
) -> pd.DataFrame:
    """First defaults by calendar year, all vintages combined, under A and each B-n."""
    targets = [("a", "first_default_period")] + [
        (f"b{n}", f"first_default_period_b{n}") for n in cure_months
    ]
    union = " UNION ALL ".join(
        f"SELECT year({col}) AS yr, '{name}' AS target FROM "
        f"(SELECT DISTINCT loan_id, {col} FROM panel_all) WHERE {col} IS NOT NULL"
        for name, col in targets
    )
    pivot = ", ".join(
        f"COUNT(*) FILTER (target = '{name}') AS first_defaults_{name}" for name, _ in targets
    )
    return (
        con.execute(f"""
        WITH d AS ({union}),
        dy AS (SELECT yr, {pivot} FROM d GROUP BY 1),
        act AS (SELECT year(period) AS yr, COUNT(DISTINCT loan_id) AS loans_observed,
                       COUNT(*) FILTER (zb_code IN {loss_codes}) AS loss_terminations
                FROM panel_all GROUP BY 1)
        SELECT act.yr AS year, act.loans_observed, dy.* EXCLUDE (yr), act.loss_terminations
        FROM act LEFT JOIN dy USING (yr) ORDER BY 1
    """)
        .df()
        .fillna(0)
    )


CURE_MONTHS = (12, 18)  # cure windows of the Option B PD training targets (B-12, B-18)


def build_panel(
    raw_dir: Path,
    out: Path,
    reports: Path,
    vintages: str | None = None,
    cure_months: list[int] | tuple[int, ...] = CURE_MONTHS,
) -> None:
    """Check every raw file, build each vintage (all found in `raw_dir`, or the subset
    `vintages`, e.g. "2005-2007" or "2005,2017"), refresh the DuckDB views in `out` and write the
    QC tables to `reports`."""
    cure_months = list(cure_months)
    layout = load_layout()
    loss_codes = "(" + ", ".join(f"'{c}'" for c in layout["default_zero_balance_codes"]) + ")"
    vintages = parse_vintages(vintages, find_vintages(raw_dir))

    # ---- Column check on every file before loading anything ----
    logger.info(f"Checking columns in {2 * len(vintages)} files ...")
    for v in vintages:
        check_columns(raw_dir / f"sample_orig_{v}.txt", layout["origination"], "Origination")
        check_columns(raw_dir / f"sample_perf_{v}.txt", layout["performance"], "Performance")
    logger.info(
        f"  all files have {len(layout['origination'])} origination / "
        f"{len(layout['performance'])} performance columns"
    )

    logger.info("Building vintages (cure windows: " + ", ".join(map(str, cure_months)) + "):")
    for v in vintages:
        build_vintage(
            v,
            raw_dir / f"sample_orig_{v}.txt",
            raw_dir / f"sample_perf_{v}.txt",
            out,
            layout,
            cure_months,
        )
    shutil.rmtree(out / "_staging", ignore_errors=True)

    con = create_views(out)
    reports.mkdir(parents=True, exist_ok=True)
    qc = qc_by_vintage(con, cure_months, loss_codes)
    qc.to_csv(reports / "qc_by_vintage.csv", index=False)
    by_year = first_defaults_by_year(con, cure_months, loss_codes)
    by_year.to_csv(reports / "first_defaults_by_year.csv", index=False)
    con.close()

    logger.info(f"\nWrote {out / 'loans'}, {out / 'panel'} and views in {out / 'ecl.duckdb'}")
    logger.info(
        f"Wrote {reports / 'qc_by_vintage.csv'} ({len(qc)} vintages) and "
        f"{reports / 'first_defaults_by_year.csv'}"
    )
