"""FHFA house price index and HPI-indexed current LTV.

Why: Freddie Mac's estimated LTV (ELTV) only exists from 2017-04, so it is missing for most
loans before 2017. Indexing each loan's origination property value with the FHFA state HPI
gives one consistent current LTV for every month since 1999. The same number feeds the PD
model (Module 2), the Stage 2 collateral trigger (Module 6, RBI Annex 1: collateral value
falling with house prices) and LGD collateral (Module 5, RBI para 6(24): realistic realisable
value of collateral).

    orig_value     = orig_upb / (orig_ltv / 100)       first-lien LTV, not CLTV; HARP loans
                                                       above 100% are kept
    value(t)       = orig_value x HPI(quarter of t) / HPI(origination quarter)
    current_ltv(t) = 100 x current_upb(t) / value(t)

Documented choices:
  * Index: FHFA All-Transactions Index (sales prices + appraisal data), states, not seasonally
    adjusted, quarterly. File data/macro/hpi_at_state.csv, no header: state, year, quarter, index.
    A US series: it is not an Indian HPI.
  * Origination quarter: the origination date is not disclosed, so the quarter of
    (first_payment_date - 1 month) is used (approximation; agrees with period - loan_age for
    99.99% of loans).
  * Territories not in the state file (PR, GU, VI): fall back to the US national
    all-transactions index if data/macro/hpi_at_us.csv exists (rows: region, year, quarter,
    index; region USA / US / United States); `hpi_fallback` marks these loans. Without the
    national file their current LTV stays NULL.
"""

from pathlib import Path

import duckdb

from ecl.common import project_root

ROOT = project_root()
DEFAULT_HPI_PATH = ROOT / "data" / "macro" / "hpi_at_state.csv"
DEFAULT_NATIONAL_HPI_PATH = ROOT / "data" / "macro" / "hpi_at_us.csv"
NATIONAL_CODES = ("USA", "US", "UNITED STATES")


def _read_quarterly(con: duckdb.DuckDBPyConnection, table: str, path: Path) -> int:
    """Create `table(region, yr, qtr, hpi)` from a 4-column FHFA CSV (header row optional)."""
    con.execute(f"""
        CREATE OR REPLACE TABLE {table} AS
        SELECT upper(trim(column0))                 AS region,
               TRY_CAST(trim(column1) AS INT)       AS yr,
               TRY_CAST(trim(column2) AS INT)       AS qtr,
               TRY_CAST(trim(column3) AS DOUBLE)    AS hpi
        FROM read_csv('{path.as_posix()}', header=false, all_varchar=true, auto_detect=true)
        WHERE TRY_CAST(trim(column1) AS INT) IS NOT NULL      -- drops a header row
    """)
    n, bad_q, dupes = con.execute(f"""
        SELECT COUNT(*), COUNT(*) FILTER (qtr NOT BETWEEN 1 AND 4),
               COUNT(*) - COUNT(DISTINCT (region, yr, qtr)) FROM {table}
    """).fetchone()
    if n == 0 or bad_q or dupes:
        raise ValueError(
            f"{path.name}: expected FHFA HPI rows (region, year, quarter 1-4, index); "
            f"got {n} rows, {bad_q} bad quarters, {dupes} duplicate region-quarters."
        )
    return n


def load_hpi(
    con: duckdb.DuckDBPyConnection, path: Path, national_path: Path | None = None
) -> dict[str, int]:
    """Create tables `hpi(state, yr, qtr, hpi)` and `hpi_us(yr, qtr, hpi)` (empty if the
    national file is absent). Returns row counts."""
    n_state = _read_quarterly(con, "hpi_raw", path)
    con.execute("CREATE OR REPLACE TABLE hpi AS SELECT region AS state, yr, qtr, hpi FROM hpi_raw")
    con.execute("CREATE OR REPLACE TABLE hpi_us (yr INT, qtr INT, hpi DOUBLE)")
    n_us = 0
    if national_path is not None and national_path.exists():
        _read_quarterly(con, "hpi_us_raw", national_path)
        codes = ", ".join(f"'{c}'" for c in NATIONAL_CODES)
        con.execute(f"""INSERT INTO hpi_us
            SELECT yr, qtr, hpi FROM hpi_us_raw WHERE region IN ({codes})""")
        n_us = con.execute("SELECT COUNT(*) FROM hpi_us").fetchone()[0]
        if n_us == 0:
            raise ValueError(f"{national_path.name}: no rows with region in {NATIONAL_CODES}")
    return {"state": n_state, "national": n_us}


def orig_month_sql(first_payment_date: str) -> str:
    """Origination month approximation: first payment date minus one month."""
    return f"({first_payment_date} - INTERVAL 1 MONTH)::DATE"


def hpi_value_sql(state: str, date: str, alias: str) -> tuple[str, str]:
    """(join clause, value expression) for the HPI at `date`'s quarter: the state index, or the
    national index for states missing from the state file."""
    join = f"""
        LEFT JOIN hpi {alias}_s ON {alias}_s.state = {state}
            AND {alias}_s.yr = year({date}) AND {alias}_s.qtr = quarter({date})
        LEFT JOIN hpi_us {alias}_us ON {alias}_us.yr = year({date})
            AND {alias}_us.qtr = quarter({date})"""
    value = f"""CASE WHEN {state} IN (SELECT DISTINCT state FROM hpi) THEN {alias}_s.hpi
                     ELSE {alias}_us.hpi END"""
    return join, value


def hpi_fallback_sql(state: str) -> str:
    """TRUE when the loan's state is not in the FHFA state file (national index or NULL)."""
    return f"COALESCE({state} NOT IN (SELECT DISTINCT state FROM hpi), TRUE)"


def current_ltv_sql(
    current_upb: str, orig_upb: str, orig_ltv: str, hpi_now: str, hpi_orig: str
) -> str:
    """SQL expression for HPI-indexed current LTV (%); NULL if any input is missing."""
    return (
        f"100.0 * {current_upb} / NULLIF({orig_upb} / NULLIF({orig_ltv} / 100.0, 0)"
        f" * ({hpi_now}) / NULLIF({hpi_orig}, 0), 0)"
    )
