"""PD at initial recognition, per loan (RBI para 26: SICR compares default risk now with the
risk at initial recognition, so the origination PD must be stored per loan).

Each loan is scored with the champion scorecard in its origination state: loan_age at its first
observed month, no delinquency history (dlq_state "never 30+ dpd"), current LTV =
origination LTV, not deferred, not modified.

Caveat for Module 6: the 12-month PD rises with seasoning (loan_age), so a relative-PD SICR test
comparing PD(t) with PD at origination must correct for the expected seasoning path before
applying a threshold, or every performing loan drifts towards Stage 2.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ecl.pd.dataset import categorical_sql, create_orig_table
from ecl.pd.features import SOURCE_COLUMNS, scorecard_frame
from ecl.pd.scorecard import WoEScorecard


def origination_frame(processed: Path) -> pd.DataFrame:
    """Every loan at origination with the scorecard features: origination attributes, loan age at
    the first observed month, current LTV = original LTV and a clean payment history (para 26:
    credit risk at initial recognition)."""
    con = duckdb.connect()
    for kind in ["loans", "panel"]:
        con.execute(f"""CREATE VIEW {kind}_all AS SELECT * FROM read_parquet(
            '{(processed / kind).as_posix()}/*/*.parquet', hive_partitioning = true)""")
    create_orig_table(con)
    cat = categorical_sql("l")
    df = con.execute(f"""
        WITH first_obs AS (
            SELECT loan_id, ARG_MIN(loan_age, period) AS loan_age
            FROM panel_all WHERE loan_age IS NOT NULL GROUP BY 1
        )
        SELECT l.loan_id, l.vintage, l.credit_score, l.orig_ltv, l.orig_cltv, l.orig_dti,
            l.harp_loan,
            {cat["occupancy_status"]} AS occupancy_status, {cat["loan_purpose"]} AS loan_purpose,
            {cat["property_type"]} AS property_type, {cat["channel"]} AS channel,
            {cat["first_time_homebuyer"]} AS first_time_homebuyer,
            NULLIF(l.num_units, 99) AS num_units, NULLIF(l.num_borrowers, 99) AS num_borrowers,
            o.rate_spread, COALESCE(f.loan_age, 0) AS loan_age,
            CAST(l.orig_ltv AS DOUBLE) AS current_ltv,
            CAST(NULL AS BIGINT) AS months_since_30dpd, 0 AS max_dlq_12m,
            'current' AS dpd_bucket, FALSE AS ever_deferred, FALSE AS ever_modified
        FROM loans_all l
        LEFT JOIN orig o USING (loan_id)
        LEFT JOIN first_obs f USING (loan_id)
        ORDER BY l.loan_id
    """).df()
    con.close()
    return df[["loan_id", "vintage", *SOURCE_COLUMNS]]


def score_at_origination(model: WoEScorecard, df: pd.DataFrame, version: str) -> pd.DataFrame:
    """PD and score at origination per loan with the model version: the comparator for the SICR
    test (para 26)."""
    x = scorecard_frame(df)
    return pd.DataFrame(
        {
            "loan_id": df.loan_id,
            "vintage": df.vintage,
            "pd_at_origination": model.predict_pd(x),
            "score_at_origination": model.score(x),
            "model_version": version,
        }
    )
