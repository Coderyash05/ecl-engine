"""Loan inputs for the lifetime hazard and the portfolio lifetime PD on one macro path.

Shared by Module 3 (ecl.lifetime.fit_lifetime) and Module 4 (scenario PDs, crisis replay):
- `components` / `loans_from`: v1.2.0 scorecard components and the `Loans` a projection needs;
- `origination_loans`: every loan at its first observed month (vintage backtest, replay);
- `aalen_johansen`: actual cumulative default / prepayment with censoring;
- `lifetime_pd`: year 1 = the 12-month PIT PD (Vasicek at the path's Z, floored, para 96);
  years 2+ = the hazard on the path, with the calibrated year-1 ratio carried (tau) and the
  annual floor (config pd.floor_lifetime_annual, an interpretation); the lifetime PD is not a
  mechanical function of the 12-month PD (para 45). Optional **default-odds multipliers** per
  variant implement a post-model adjustment such as CO-3 (para 131): computed on the same
  projection, so overlay and no-overlay results differ only by the overlay.

US data; not Indian risk estimates.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

from ecl.lifetime.cycle import vasicek_pd
from ecl.lifetime.hazard import (
    WOE_FEATURES,
    Loans,
    WoeMap,
    apply_annual_floor,
    carry_year1_ratio,
    cumulative,
    project,
    splice_year1,
)
from ecl.lifetime.paths import qidx
from ecl.pd.features import scorecard_frame
from ecl.pd.scorecard import WoEScorecard

if TYPE_CHECKING:
    from pathlib import Path

    import duckdb

    from ecl.lifetime.hazard import HazardModel
    from ecl.lifetime.paths import MacroPath


def read_state_hpi(path: Path) -> pd.DataFrame:
    """FHFA state index file (no header): state, year, quarter, index."""
    return pd.read_csv(path, header=None, names=["state", "yr", "qtr", "hpi"])


def components(sc: WoEScorecard, df: pd.DataFrame) -> dict:
    """v1.2.0 score components: delinquency-state coefficient, rest of the logit, WoE."""
    x = scorecard_frame(df)
    logit = sc.logit(x)
    state = x.dlq_state.fillna(0).astype(int).values
    dlq = np.array(sc.state_coefs["dlq_state"])[state]
    return {
        "logit": logit,
        "dlq": dlq,
        "rest": logit - dlq,
        "dlq_state": state,
        "woe": sc.woe(x)[WOE_FEATURES].values.astype(float),
    }


def loans_from(
    df: pd.DataFrame,
    comp: dict,
    path: MacroPath,
    age: ArrayLike,
    rm: ArrayLike,
    upb: ArrayLike,
    rate: ArrayLike,
    ltv: ArrayLike,
    ref_q: ArrayLike,
) -> Loans:
    """`Loans` for projection; property value = UPB / current LTV at the reference date."""
    ltv = np.asarray(ltv, dtype=float)
    upb = np.asarray(upb, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        value = np.where(ltv > 0, upb / (ltv / 100), np.nan)
    return Loans(
        age=np.asarray(age, float),
        rm=np.asarray(rm, float),
        upb=upb,
        rate=np.asarray(rate, float),
        value=value,
        ltv=ltv,
        state_idx=path.state_index(df.property_state.values),
        ref_q=np.asarray(ref_q, int),
        dlq=comp["dlq"],
        rest=comp["rest"],
        dlq_state=comp["dlq_state"],
        woe=comp["woe"],
    )


def woe_map(sc: WoEScorecard, feature: str) -> WoeMap:
    """A v1.2.0 WoE by bin (bins, then 'Special' and 'Missing' rows of the binning table)."""
    bv = sc.binning.get_binned_variable(feature)
    t = bv.binning_table.build()
    n = len(bv.splits) + 1
    return WoeMap(
        np.asarray(bv.splits, float),
        t["WoE"].iloc[:n].astype(float).values,
        float(t.loc[t.Bin == "Missing", "WoE"].iloc[0]),
    )


def origination_loans(
    con: duckdb.DuckDBPyConnection, orig_frame: pd.DataFrame, sc: WoEScorecard, path: MacroPath
) -> tuple:
    """Every loan at its first observed month: the `orig` table (hazard_data.
    create_origination_table) joined with the origination features (pd.origination), current LTV
    at the first month from the state HPI on `path`. Returns (frame, Loans)."""
    orig = con.execute("SELECT * FROM orig ORDER BY loan_id").df()
    orig = orig.drop(columns=["orig_ltv"]).merge(
        orig_frame.drop(columns=["vintage"]), on="loan_id", how="inner"
    )
    orig_q_month = pd.to_datetime(orig.first_payment_date) - pd.DateOffset(months=1)
    orig["orig_q"] = [qidx(d) for d in orig_q_month]
    orig["first_q"] = [qidx(d) for d in pd.to_datetime(orig.first_period)]
    st_idx = path.state_index(orig.property_state.values)
    with np.errstate(divide="ignore", invalid="ignore"):
        ov = orig.orig_upb / (orig.orig_ltv / 100)
        value_first = ov * path.hpi_ratio(st_idx, orig.orig_q.values, orig.first_q.values)
        orig["ltv_first"] = 100 * orig.upb_first / value_first
    loans = loans_from(
        orig,
        components(sc, orig),
        path,
        orig.age_first,
        orig.rm_first,
        orig.upb_first,
        orig.rate_first,
        orig.ltv_first,
        orig.first_q,
    )
    return orig, loans


def aalen_johansen(n_quarters: np.ndarray, last_event: np.ndarray, kmax: int) -> pd.DataFrame:
    """Actual cumulative incidence of default and prepayment by quarter since the start, with
    censoring (Aalen-Johansen for competing risks)."""
    rows, s, cd, cp = [], 1.0, 0.0, 0.0
    for k in range(1, kmax + 1):
        at_risk = np.sum(n_quarters >= k)
        if at_risk == 0:
            break
        d = np.sum((n_quarters == k) & (last_event == 1))
        p = np.sum((n_quarters == k) & (last_event == 2))
        cd += s * d / at_risk
        cp += s * p / at_risk
        s *= 1 - (d + p) / at_risk
        rows.append({"k": k, "at_risk": at_risk, "actual_default": cd, "actual_prepay": cp})
    return pd.DataFrame(rows)


def year_live(h_d: np.ndarray, h_p: np.ndarray) -> np.ndarray:
    """(n, years): the loan has at least one live quarter in the year."""
    a = h_d + h_p
    a = np.pad(a, ((0, 0), (0, (-a.shape[1]) % 4)))
    return a.reshape(len(a), -1, 4).sum(axis=2) > 0


def odds_scale(p: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Probability with its odds multiplied by m (m = 1: unchanged)."""
    return m * p / (1 - p + m * p)


# A variant maps (loan positions, n_quarters) -> default-odds multiplier (n, n_quarters) or None
Variant = Callable[[np.ndarray, int], np.ndarray] | None


def lifetime_pd(
    model: HazardModel,
    pf: pd.DataFrame,
    pcomp: dict,
    idx: np.ndarray,
    path: MacroPath,
    z_first: float,
    report_q: pd.Period,
    rho: float,
    floor12: float,
    floor_annual: float,
    tau: float,
    variants: dict[str, Variant] | None = None,
    chunk: int = 40_000,
) -> dict:
    """Spliced, floored lifetime PD of the reporting-date loans `idx` of `pf` on one path.

    `pf` needs loan_id, property_state, loan_age, rm, current_upb, rate, current_ltv and the
    scorecard columns (pcomp = components(sc, pf)). `variants` {name: multiplier function or
    None}: each variant's default odds are multiplied quarter by quarter (prepayment hazard
    unchanged, so default + prepayment < 1); the year-1 PIT PD's odds by the mean multiplier of
    year-1 quarters; the carried year-1 ratio is computed before any multiplier. Default:
    {'model': None}. Returns {variant: {'pd12', 'lifetime', 'lifetime_nofloor', 'hazard_y1',
    'bound_years', 'live_years', 'cum_year'}}."""
    variants = variants or {"model": None}
    ttc = 1 / (1 + np.exp(-pcomp["logit"][idx]))
    pd12_model = np.maximum(vasicek_pd(ttc, z_first, rho), floor12)
    n_q = int(np.ceil(pf.rm.values[idx].max() / 3))
    years = int(np.ceil(n_q / 4))
    keys = ["pd12", "lifetime", "lifetime_nofloor", "hazard_y1", "bound_years", "live_years"]
    out = {v: {k: np.zeros(len(idx)) for k in keys} for v in variants}
    for v in variants:
        out[v]["cum_year"] = np.zeros((len(idx), years), dtype=np.float32)
    rq = qidx(report_q)
    for a in range(0, len(idx), chunk):
        ii = idx[a : a + chunk]
        sl = slice(a, a + len(ii))
        sub = loans_from(
            pf.iloc[ii],
            {k: v[ii] for k, v in pcomp.items()},
            path,
            pf.loan_age.values[ii],
            pf.rm.values[ii],
            pf.current_upb.values[ii],
            pf.rate.values[ii],
            pf.current_ltv.values[ii],
            np.full(len(ii), rq),
        )
        hd0, hp = project(model, sub, path, n_q)
        y1 = cumulative(hd0, hp)[1][:, min(3, n_q - 1)]
        hd_c = carry_year1_ratio(hd0, hp, pd12_model[sl] / np.maximum(y1, 1e-12), tau)
        for name, fn in variants.items():
            hd, pd12 = hd_c, pd12_model[sl]
            if fn is not None:
                m = fn(ii, n_q)
                hd = np.minimum(odds_scale_keep_prepay(hd_c, hp, m), 1 - hp)
                pd12 = np.minimum(odds_scale(pd12, m[:, : min(4, n_q)].mean(axis=1)), 1.0)
            o = out[name]
            o["hazard_y1"][sl] = y1
            o["pd12"][sl] = pd12
            s0, cd0, cp0 = cumulative(hd, hp)
            o["lifetime_nofloor"][sl] = splice_year1(cd0, cp0, s0, pd12)[:, -1]
            hdf, bound = apply_annual_floor(hd, hp, floor_annual, first_year=1)
            s, cd, cp = cumulative(hdf, hp)
            spl = splice_year1(cd, cp, s, pd12)
            o["lifetime"][sl] = spl[:, -1]
            o["cum_year"][sl] = spl[:, np.minimum(np.arange(1, years + 1) * 4, n_q) - 1]
            o["bound_years"][sl] = bound[:, 1:].sum(axis=1)
            o["live_years"][sl] = year_live(hd, hp)[:, 1:].sum(axis=1)
    return out


def odds_scale_keep_prepay(h_d: np.ndarray, h_p: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Default hazard with its odds against survival multiplied by m, prepayment unchanged:
    odds = h_d / (1 - h_d - h_p) -> m x odds, i.e. h_d' = m h_d (1 - h_p) / (1 - h_p + (m-1) h_d).
    """
    return m * h_d * (1 - h_p) / (1 - h_p + (m - 1) * h_d)
