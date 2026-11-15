"""ECL backtest (Module 11; ACPIR para 131: post-implementation back-testing of predictions
against actual outcomes).

For the performing loans (Stage 1 and 2) of a reporting date, the probability-weighted 12-month
PD and 12-month ECL from the Modules 6-8 run are compared with what happened in the following
12 months:
- defaults: an RBI default month (90+ dpd / REO / loss-type termination; `default_event`, the
  ECL default definition) in (date, date + 12 months]; B-18 (`default_event_b18`, the PD model's
  development target) as a second count;
- losses: for those defaults, Freddie's actual loss at the zero-balance month (Release 47 sign:
  losses positive) up to the end of the data; cures and prepayments count as zero loss;
  defaults still unresolved at the data end are reported separately (censored).
The predicted ECL is discounted at the note rate and the realised loss is not, so the loss ratio
is indicative. US data (Freddie Mac sample); not Indian risk estimates.
"""

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


def outcomes(processed: Path, ids: pd.Series, start: str, end: str) -> pd.DataFrame:
    """Per loan: default in [start, end) (RBI and B-18), and for loans defaulting in the window
    the zero-balance code and actual loss up to the data end."""
    con = duckdb.connect()
    glob = (processed / "panel").as_posix() + "/*/*.parquet"
    con.register("ids", pd.DataFrame({"loan_id": ids.astype(str).values}))
    df = con.execute(f"""
        WITH p AS (
            SELECT p.* FROM read_parquet('{glob}', hive_partitioning=true) p
            JOIN ids USING (loan_id)),
        w AS (
            SELECT loan_id,
                BOOL_OR(default_event AND period >= DATE '{start}' AND period < DATE '{end}')
                    AS default_12m,
                BOOL_OR(default_event_b18 AND period >= DATE '{start}' AND period < DATE '{end}')
                    AS default_b18_12m,
                MIN(CASE WHEN default_event AND period >= DATE '{start}'
                         AND period < DATE '{end}' THEN period END) AS default_period,
                MAX(CASE WHEN zb_code IS NOT NULL THEN zb_code END) AS zb_code,
                MAX(CASE WHEN zb_code IS NOT NULL THEN period END) AS zb_period,
                SUM(CASE WHEN zb_code IS NOT NULL THEN COALESCE(actual_loss, 0) END) AS actual_loss,
                MAX(period) AS last_period
            FROM p GROUP BY 1),
        c AS (
            SELECT p.loan_id, BOOL_OR(p.months_dlq = 0 AND p.period > w.default_period) AS cured
            FROM p JOIN w USING (loan_id) WHERE w.default_12m GROUP BY 1)
        SELECT w.*, COALESCE(c.cured, FALSE) AS cured FROM w LEFT JOIN c USING (loan_id)
        ORDER BY w.loan_id
    """).df()
    con.close()
    return df


def ecl_backtest(
    res: pd.DataFrame, out: pd.DataFrame, loss_codes: list[str], data_end: str
) -> pd.DataFrame:
    """Predicted vs actual 12-month defaults and losses by stage (performing loans only).
    res: loan-level ECL output (stage, ead_now, pd12_weighted, ecl12_weighted);
    out: `outcomes` for the same loans."""
    d = res[res.stage < 3].merge(out, on="loan_id", how="left")
    d["default_12m"] = d.default_12m.fillna(False).astype(bool)
    d["default_b18_12m"] = d.default_b18_12m.fillna(False).astype(bool)
    liquidated = d.default_12m & d.zb_code.isin(loss_codes)
    resolved = liquidated | (d.default_12m & (d.cured | d.zb_code.notna()))
    d["realised_loss"] = np.where(liquidated, d.actual_loss.fillna(0), 0.0)
    d["unresolved"] = d.default_12m & ~resolved
    rows = []
    for name, g in [("Stage 1", d[d.stage == 1]), ("Stage 2", d[d.stage == 2]), ("Total", d)]:
        n = len(g)
        rows.append(
            {
                "segment": name,
                "loans": n,
                "ead": g.ead_now.sum(),
                "predicted_defaults": g.pd12_weighted.sum(),
                "actual_defaults_rbi": int(g.default_12m.sum()),
                "actual_defaults_b18": int(g.default_b18_12m.sum()),
                "pd_predicted": g.pd12_weighted.mean(),
                "default_rate_rbi": g.default_12m.mean(),
                "actual_to_predicted_rbi": g.default_12m.sum() / g.pd12_weighted.sum(),
                "actual_to_predicted_b18": g.default_b18_12m.sum() / g.pd12_weighted.sum(),
                "predicted_ecl12": g.ecl12_weighted.sum(),
                "realised_loss_to_data_end": g.realised_loss.sum(),
                "loss_ratio": g.realised_loss.sum() / g.ecl12_weighted.sum(),
                "defaults_liquidated": int((g.default_12m & g.zb_code.isin(loss_codes)).sum()),
                "defaults_cured_or_prepaid": int(
                    (g.default_12m & ~g.zb_code.isin(loss_codes) & ~g.unresolved).sum()
                ),
                "defaults_unresolved": int(g.unresolved.sum()),
                "ead_unresolved": g.loc[g.unresolved, "ead_now"].sum(),
                "data_end": data_end,
            }
        )
    return pd.DataFrame(rows)
