"""LGD modelling data: every first RBI default, how it resolved, and its economic loss.

What (docs/methodology/lgd_ead.md; RBI paras 6(5), 8(1), 44, 50-51):
- **Default** = the loan's first RBI default (target A: 90+ dpd, REO or loss-type termination).
- **Resolution** (config/lgd.yaml `resolution`):
  - liquidation: zero-balance code 02 / 03 / 09 / 15 at any time after default (also when the
    loan was current in between: the loss belongs to this default);
  - cure: back to current after default, or paid off / sold as re-performing (01 / 16), and no
    loss-type termination: economic loss 0 (modification costs and the time value of a cure are
    not counted: limitation);
  - excluded: defect repurchase (96); unresolved: still in default at data end (censored).
- **Economic loss of a liquidation** (Release 47 sign convention: recoveries and gains negative,
  losses and expenses positive; actual_loss = removal UPB + delinquent accrued interest +
  expenses + recoveries):
  - EAD at default = UPB at the default month + accrued interest on the unpaid instalments
    (months delinquent at default x note rate / 12; para 100: collateral is not netted);
  - net recovery = -(net sale proceeds + MI recoveries + non-MI recoveries) - total expenses,
    received at the zero-balance month;
  - discounted to the default month at the origination note rate (EIR proxy, paras 50-51; para
    44: a late recovery is a credit loss), so post-default interest accrual is replaced by the
    discounting;
  - severity = 1 - PV(net recovery) / EAD.
  A liquidation without loss fields is an incomplete workout: excluded from severity (bias
  recorded as a limitation).
- **Indexed LTV** at any month = UPB / (origination value x state HPI ratio) (ecl.data.hpi), the
  same collateral measure as the PD model and the secured portion (para 6(24)).

US data (Freddie Mac); not Indian risk estimates.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

from ecl.data.hpi import orig_month_sql


def _q(dates: ArrayLike) -> np.ndarray:
    d = pd.to_datetime(pd.Series(dates))
    return pd.PeriodIndex(d, freq="Q").astype(str).values if len(d) else np.array([])


def hpi_ratio(
    log_state: pd.DataFrame, states: ArrayLike, q_from: ArrayLike, q_to: ArrayLike
) -> np.ndarray:
    """HPI(state, q_to) / HPI(state, q_from) from the quarter x state table of log indices;
    NaN for states or quarters without an index."""
    st = pd.Series(states).values
    cols = {s: i for i, s in enumerate(log_state.columns)}
    rows = {str(q): i for i, q in enumerate(log_state.index)}
    a = log_state.values
    ci = np.array([cols.get(s, -1) for s in st], dtype=int)
    fi = np.array([rows.get(str(q), -1) for q in q_from], dtype=int)
    ti = np.array([rows.get(str(q), -1) for q in q_to], dtype=int)
    ok = (ci >= 0) & (fi >= 0) & (ti >= 0)
    out = np.full(len(st), np.nan)
    out[ok] = np.exp(a[ti[ok], ci[ok]] - a[fi[ok], ci[ok]])
    return out


def build_defaults(processed: Path, cfg: dict) -> pd.DataFrame:
    """One row per loan with an RBI default: loan attributes, default-month state, resolution
    and (for liquidations) the loss components."""
    r = cfg["resolution"]
    loss = ", ".join(f"'{c}'" for c in r["loss_codes"])
    cure = ", ".join(f"'{c}'" for c in r["cure_codes"])
    excl = ", ".join(f"'{c}'" for c in r["excluded_codes"])
    con = duckdb.connect()
    for kind in ["loans", "panel"]:
        glob = (processed / kind).as_posix() + "/*/*.parquet"
        con.execute(
            f"CREATE VIEW {kind}_all AS SELECT * FROM read_parquet('{glob}', hive_partitioning=true)"
        )
    df = con.execute(f"""
        WITH d AS (
            SELECT loan_id, MIN(first_default_period) AS fd FROM panel_all
            WHERE first_default_period IS NOT NULL GROUP BY 1),
        p AS (SELECT p.* , d.fd FROM panel_all p JOIN d USING (loan_id)),
        s AS (
            SELECT loan_id, fd,
                MIN(CASE WHEN period > fd AND months_dlq = 0 THEN period END) AS cure_period,
                MAX(CASE WHEN zb_code IS NOT NULL THEN period END)          AS zb_period,
                MAX(zb_code)                                                 AS zb_code,
                MAX(period)                                                  AS last_period,
                MAX(CASE WHEN period < fd AND months_dlq = 0 THEN period END) AS last_current,
                MAX(CASE WHEN period < fd AND months_dlq > 0 THEN period END) AS last_dlq_before
            FROM p GROUP BY 1, 2),
        pr AS (
            SELECT p.loan_id,
                BOOL_OR(p.months_dlq >= 1 AND p.period < s.last_current) AS prior_dlq
            FROM p JOIN s USING (loan_id) GROUP BY 1),
        at_d AS (
            SELECT loan_id, current_upb AS upb_d, months_dlq AS dlq_d, loan_age AS age_d,
                   relief_flag AS relief_d, dlq_raw AS status_d
            FROM p WHERE period = fd),
        upb_prev AS (
            SELECT p.loan_id, ARG_MAX(p.current_upb, p.period) AS upb_last_pos
            FROM p WHERE p.period <= p.fd AND p.current_upb > 0 GROUP BY 1),
        zb AS (
            SELECT loan_id, net_sale_proceeds AS nsp, mi_recoveries AS mi,
                   non_mi_recoveries AS nmi, total_expenses AS te, actual_loss AS al
            FROM panel_all WHERE zb_code IS NOT NULL)
        SELECT s.*, COALESCE(pr.prior_dlq, FALSE) AS prior_dlq,
            CASE WHEN at_d.upb_d > 0 THEN at_d.upb_d ELSE u.upb_last_pos END AS upb_d,
            at_d.dlq_d, at_d.age_d, COALESCE(at_d.relief_d, FALSE) AS relief_d, at_d.status_d,
            zb.nsp, zb.mi, zb.nmi, zb.te, zb.al,
            l.vintage, l.credit_score, l.orig_ltv, l.orig_upb, l.orig_interest_rate AS note_rate,
            l.mi_pct, l.property_type, l.property_state, l.first_payment_date,
            {orig_month_sql("l.first_payment_date")} AS orig_month,
            CASE WHEN s.zb_code IN ({loss}) THEN 'liquidation'
                 WHEN s.zb_code IN ({excl}) THEN 'excluded'
                 WHEN s.cure_period IS NOT NULL OR s.zb_code IN ({cure}) THEN 'cure'
                 ELSE 'unresolved' END AS outcome
        FROM s
        LEFT JOIN pr USING (loan_id)
        LEFT JOIN at_d USING (loan_id)
        LEFT JOIN upb_prev u USING (loan_id)
        LEFT JOIN zb USING (loan_id)
        JOIN loans_all l USING (loan_id)
        ORDER BY loan_id
    """).df()
    con.close()
    df["resolution_period"] = np.where(
        df.outcome == "liquidation",
        df.zb_period,
        df[["cure_period", "zb_period"]].min(axis=1),
    )
    df["resolution_period"] = pd.to_datetime(df.resolution_period)
    return df


def add_loss(df: pd.DataFrame, accrued_months_default: int) -> pd.DataFrame:
    """EAD at default, discounted net recovery and severity (liquidations with loss fields)."""
    r = df.note_rate.values / 1200
    dlq = np.nan_to_num(df.dlq_d.values.astype(float), nan=accrued_months_default)
    months_unpaid = np.clip(dlq, 0, None)
    df["ead_d"] = df.upb_d * (1 + r * months_unpaid)
    liq = df.outcome.eq("liquidation")
    complete = liq & df.al.notna()
    rec = -(df.nsp.fillna(0) + df.mi.fillna(0) + df.nmi.fillna(0)) - df.te.fillna(0)
    months = (
        (pd.to_datetime(df.zb_period).dt.year - pd.to_datetime(df.fd).dt.year) * 12
        + pd.to_datetime(df.zb_period).dt.month
        - pd.to_datetime(df.fd).dt.month
    )
    df["months_to_liquidation"] = np.where(liq, months, np.nan)
    df["discount_factor"] = (1 + r) ** -np.clip(df.months_to_liquidation.fillna(0), 0, None)
    df["net_recovery"] = np.where(complete, rec, np.nan)
    df["severity"] = np.where(complete, 1 - rec * df.discount_factor / df.ead_d, np.nan)
    df["severity_undiscounted"] = np.where(complete, 1 - rec / df.ead_d, np.nan)
    df["freddie_loss_rate"] = np.where(complete, df.al / df.ead_d, np.nan)
    df["loss_complete"] = complete
    df["realised_lgd"] = np.where(
        df.outcome.eq("cure"), 0.0, np.where(complete, df.severity, np.nan)
    )
    return df


def add_collateral(df: pd.DataFrame, log_state: pd.DataFrame) -> pd.DataFrame:
    """Indexed property value and LTV at default, and the indexed value at liquidation."""
    orig_value = df.orig_upb / (df.orig_ltv / 100)
    q_o = _q(df.orig_month)
    df["value_d"] = orig_value * hpi_ratio(log_state, df.property_state, q_o, _q(df.fd))
    df["ltv_d"] = 100 * df.upb_d / df.value_d
    zq = _q(df.zb_period.fillna(df.fd))
    df["value_zb"] = orig_value * hpi_ratio(log_state, df.property_state, q_o, zq)
    return df


def observation_rows(df: pd.DataFrame, months: list[int], log_state: pd.DataFrame) -> pd.DataFrame:
    """Cure-model rows: each resolved default observed at m months after default while still in
    default, i.e. before its first exit (m = 0 always). Indexed LTV, loan age and months in default at the observation;
    y = 1 if the default ends in liquidation (no cure)."""
    res = df[df.outcome.isin(["cure", "liquidation"])].copy()
    fd = pd.to_datetime(res.fd)
    # still in default = before the first exit from default (back to current, or zero balance)
    first_exit = pd.to_datetime(res[["cure_period", "zb_period"]].min(axis=1))
    parts = []
    for m in months:
        at = fd + pd.DateOffset(months=m)
        alive = (m == 0) | (at < first_exit)
        x = res[alive.values].copy()
        at = at[alive.values]
        x["m"] = m
        x["obs_period"] = at.values
        orig_value = x.orig_upb / (x.orig_ltv / 100)
        x["ltv_obs"] = (
            100
            * x.upb_d
            / (orig_value * hpi_ratio(log_state, x.property_state, _q(x.orig_month), _q(at)))
        )
        x["age_obs"] = x.age_d + m
        parts.append(x)
    out = pd.concat(parts, ignore_index=True)
    out["y"] = out.outcome.eq("liquidation").astype(int)
    return out
