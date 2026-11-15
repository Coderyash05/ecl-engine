"""Person-quarter data for the competing-risk lifetime hazard (docs/methodology/pd_lifetime.md).

Loans are followed forward, quarter by quarter, from **reference dates**: a random 1-in-16
sample of the quarterly snapshots of the PD dataset, drawn by a hash of (loan, date). The draw
must not depend on how the loan's life ends. An earlier design (one random snapshot per loan)
did: loans that default or prepay early have few snapshots, so each of them was far more likely
to be drawn, and both hazards came out inflated (development log, pd_lifetime). A loan can have
several reference dates; their follow-ups overlap, so standard errors are clustered by loan.
In each quarter k after the reference date the loan either

- defaults (first B-18 default, as in Module 2; RBI paras 6(5), 8(1)),
- prepays (zero balance code 01 more than 3 months before contractual maturity), or
- survives.

A loan leaves the risk set at its first default or prepayment. It is censored (no event) at
maturity (code 01 within 3 months of maturity), at an RPL securitisation (16) or defect
repurchase (96), when its records end, or at the label horizon 2024-12 (the last month with
B-18 outcomes, as for the 12-month PD dataset). Loss terminations (02/03/09/15) always come
after the default date, so they never appear as separate events.

The same exits, measured from the loan's first observed month, give the actual cumulative
default and prepayment curves by vintage (backtest).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from ecl.pd.features import SOURCE_COLUMNS

if TYPE_CHECKING:
    import pandas as pd

LABEL_END = "2024-12-01"  # last outcome month (12-month labels end with 2023-12 snapshots)
MATURITY_MONTHS = 3  # code 01 this close to maturity = matured, not prepaid
REF_SEED = 20261113
REF_RATE = 1 / 16  # share of snapshots used as reference dates
SURVIVE_RATE = 0.10  # share of survive rows kept for fitting (weight 10)
PREPAY_RATE = 0.50  # share of prepayment rows kept (weight 2); defaults all kept


def create_life_table(con: duckdb.DuckDBPyConnection, processed: Path) -> None:
    """Table `life`: one row per loan with its first / last observed month and how it left."""
    con.execute(f"""
        CREATE OR REPLACE VIEW panel AS SELECT * FROM read_parquet(
            '{(processed / "panel").as_posix()}/*/data.parquet', hive_partitioning = true)
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE life AS
        WITH per_loan AS (
            SELECT loan_id, min(period) AS first_period, max(period) AS last_period,
                   max(first_default_period_b18) AS default_period
            FROM panel GROUP BY loan_id),
        zb AS (
            SELECT loan_id, period AS zb_period, zb_code, remaining_months AS rm_zb
            FROM panel WHERE zb_code IS NOT NULL)
        SELECT p.loan_id, p.first_period, p.last_period, p.default_period, z.zb_period,
               z.zb_code, z.rm_zb,
               CASE WHEN p.default_period IS NOT NULL THEN 'default'
                    WHEN z.zb_code = '01' AND coalesce(z.rm_zb, 999) > {MATURITY_MONTHS}
                         THEN 'prepay'
                    WHEN z.zb_code IS NOT NULL THEN 'censored'
                    ELSE 'data_end' END AS exit_kind,
               CASE WHEN p.default_period IS NOT NULL THEN p.default_period
                    WHEN z.zb_code IS NOT NULL THEN z.zb_period
                    ELSE p.last_period END AS exit_period
        FROM per_loan p LEFT JOIN zb z USING (loan_id)
    """)
    # beyond the label horizon nothing is observed: censor there
    con.execute(f"""
        UPDATE life SET exit_kind = 'data_end', exit_period = DATE '{LABEL_END}'
        WHERE exit_period > DATE '{LABEL_END}'
    """)


def quarters_sql(ref: str, ref_date: str) -> str:
    """Number of quarter rows a loan contributes after `ref_date`, and the event in the last
    one (1 default, 2 prepay, 0 none). Event quarters: ceil(months / 3). Censored loans
    contribute the quarters they were seen alive in full."""
    m = f"date_diff('month', {ref}.{ref_date}, l.exit_period)"
    return f"""
        CASE WHEN l.exit_kind IN ('default', 'prepay') THEN CAST(ceil({m} / 3.0) AS INT)
             WHEN l.exit_kind = 'censored' THEN CAST(floor(({m} - 1) / 3.0) AS INT)
             ELSE CAST(floor({m} / 3.0) AS INT) END AS n_quarters,
        CASE l.exit_kind WHEN 'default' THEN 1 WHEN 'prepay' THEN 2 ELSE 0 END AS last_event
    """


def create_reference_table(
    con: duckdb.DuckDBPyConnection, dataset: Path, seed: int = REF_SEED, rate: float = REF_RATE
) -> None:
    """Table `ref`: a hash sample of PD snapshots (independent of outcomes) with scoring
    inputs, remaining term, note rate and the number of follow-up quarters."""
    cols = ", ".join(
        f"s.{c}"
        for c in dict.fromkeys(
            [*SOURCE_COLUMNS, "current_upb", "property_state", "target_b18", "split"]
        )
    )
    con.execute(f"""
        CREATE OR REPLACE TABLE ref AS
        WITH snaps AS (
            SELECT * FROM read_parquet('{dataset.as_posix()}/*/*.parquet',
                                       hive_partitioning = true)
            WHERE (md5_number('{seed}:' || loan_id || ':' || obs_date::VARCHAR) % 1000000)
                  / 1e6 < {rate})
        SELECT row_number() OVER (ORDER BY s.loan_id, s.obs_date) AS ref_id,
               s.loan_id, s.obs_date, {cols}, p.remaining_months AS rm_ref,
               p.current_rate AS rate_ref, {quarters_sql("s", "obs_date")}
        FROM snaps s
        JOIN panel p ON p.loan_id = s.loan_id AND p.period = s.obs_date
        JOIN life l ON l.loan_id = s.loan_id
    """)


def sample_rows(
    con: duckdb.DuckDBPyConnection,
    where: str,
    rate: float = SURVIVE_RATE,
    prepay_rate: float = PREPAY_RATE,
    seed: int = REF_SEED,
) -> pd.DataFrame:
    """Person-quarter rows (ref_id, loan_id, k, event, weight) of the references matching
    `where`: every default quarter, a `prepay_rate` sample of prepayment quarters and a `rate`
    sample of survive quarters, weighted by the inverse sampling rate. Sorted by loan (the
    cluster for standard errors)."""
    u = f"(md5_number('{seed}:' || ref_id::VARCHAR || ':' || k::VARCHAR) % 1000000) / 1e6"
    return con.execute(f"""
        WITH rows AS (
            SELECT r.ref_id, r.loan_id, k.k::INT AS k,
                   CASE WHEN k.k = r.n_quarters THEN r.last_event ELSE 0 END AS event
            FROM ref r, range(1, r.n_quarters + 1) AS k(k)
            WHERE {where} AND r.n_quarters > 0)
        SELECT ref_id, loan_id, k, event,
               CASE event WHEN 1 THEN 1.0 WHEN 2 THEN {1 / prepay_rate} ELSE {1 / rate} END
                   AS weight
        FROM rows
        WHERE event = 1 OR (event = 2 AND {u} < {prepay_rate}) OR (event = 0 AND {u} < {rate})
        ORDER BY loan_id, ref_id, k
    """).df()


def create_origination_table(con: duckdb.DuckDBPyConnection, processed: Path) -> None:
    """Table `orig`: each loan at its first observed month (inputs to project it from
    origination) with its exit, for the vintage backtest and the SICR comparator."""
    con.execute(f"""
        CREATE OR REPLACE TABLE orig AS
        WITH first_row AS (
            SELECT p.loan_id, p.period, p.loan_age, p.remaining_months, p.current_rate,
                   p.current_upb
            FROM panel p JOIN life l ON l.loan_id = p.loan_id AND p.period = l.first_period)
        SELECT f.loan_id, f.period AS first_period, f.loan_age AS age_first,
               f.remaining_months AS rm_first, f.current_rate AS rate_first,
               f.current_upb AS upb_first, o.orig_upb, o.orig_ltv, o.property_state,
               o.vintage, o.first_payment_date,
               {quarters_sql("f", "period")}
        FROM first_row f
        JOIN read_parquet('{(processed / "loans").as_posix()}/*/data.parquet',
                          hive_partitioning = true) o USING (loan_id)
        JOIN life l ON l.loan_id = f.loan_id
    """)
