"""Lifetime PD (Module 3): competing-risk lifetime hazard, lifetime PD term structures, backtests.

Run: ecl train pd-lifetime

1. Person-quarter data from a 1-in-16 hash sample of PD snapshots as reference dates
   (independent of outcomes; hazard_data.py).
1a. Specification comparison: stage A, the refinancing incentive in the default equation
   (bands / none / >= 1pp indicator); stage B, prepayment seasoning (age ramp / young x
   incentive / both). Rules in `meta['selection']`.
2. Champion H2 (v1.2.0 score components x horizon, LTV change, Z, age, incentive) and
   challenger H1 (borrower effects re-estimated), weighted multinomial logit, fitted on the
   dev_train references (2000-2016); dev_holdout and OOT references are not used in fitting.
3. Year-1 splice check: the hazard's own 12-month default vs the 12-month PIT PD (pd_pit) and
   the actual rate, by delinquency state, TTC-PD decile and period; and by region (CO-3).
4. Cumulative default and prepayment curves vs actual (Aalen-Johansen) by vintage, 2003-2007
   and 2012-2016, dev_holdout loans projected from their first observed month with realised
   macro.
5. Lifetime PD of the 2023-12 portfolio: forward-looking (published macro, then reversion to
   long-run means; illustrative until Module 4) and long-run macro; year 1 spliced to the 12m
   PIT PD; floors: 0.03% on the 12-month PD and on every later year's conditional annual PD.
   Plus the SICR origination-side comparator (long-run macro, same remaining window).

Outputs: aggregates in reports/summary/pd_lifetime_* and models/pd_lifetime/ (tracked); per-loan
lifetime PDs in data/processed/lifetime_pd/ (not in git). US data: not Indian risk estimates.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pandas as pd
import yaml

from ecl.common import CODE_AND_REGULATORY_CONFIG, git_state, md_table, project_root
from ecl.lifetime.cells import SAND_STATES
from ecl.lifetime.cycle import vasicek_pd
from ecl.lifetime.hazard import (
    HB_LABELS,
    Loans,
    apply_annual_floor,
    carry_year1_ratio,
    cumulative,
    design,
    fit_mnl,
    horizon_bucket,
    project,
    quarter_rows,
    remaining_from,
    splice_year1,
)
from ecl.lifetime.hazard_data import (
    LABEL_END,
    create_life_table,
    create_origination_table,
    create_reference_table,
    sample_rows,
)
from ecl.lifetime.macro import load_macro
from ecl.lifetime.paths import long_run_path, qidx, realised_path, reverting_path
from ecl.lifetime.portfolio import (
    aalen_johansen,
    components,
    loans_from,
    read_state_hpi,
    woe_map,
    year_live,
)
from ecl.pd.dataset import holdout_flags
from ecl.pd.features import DLQ_STATE_LABELS, SOURCE_COLUMNS
from ecl.pd.origination import origination_frame
from ecl.pd.scorecard import WoEScorecard

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ecl.lifetime.hazard import HazardModel, QuarterRows
    from ecl.lifetime.paths import MacroPath

ROOT = project_root()

VERSION = "pdlife-0.4.0"
INTERIM = "pdlife-0.3.0"  # tau = inf candidate, kept for comparison
PREVIOUS = "pdlife-0.2.0"
TTC_MODEL = "pd12m-1.2.1"
PIT_MODEL = "pdpit-0.2.1"
PROCESSED = ROOT / "data" / "processed"
MODEL_DIR = ROOT / "models" / "pd_lifetime"
REPORTS = ROOT / "reports" / "summary"
OUT = PROCESSED / "lifetime_pd"
REPORT_DATE = "2023-12-01"  # last snapshot of the PD dataset
REVERT_QUARTERS = 8  # quarters over which the forward path reverts to the long run (para 49)
SPLICE_TOLERANCE = (0.8, 1.25)  # accepted year-1 hazard / 12-month PIT PD ratio per period
VINTAGES = [*range(2003, 2008), *range(2012, 2017)]
LTV_BANDS = [0, 60, 80, 90, 100, np.inf]
LTV_LABELS = ["<=60", "60-80", "80-90", "90-100", ">100"]
CURVE_YEARS = [1, 2, 3, 5, 8]
# Specification comparison (model owner, 2026-11-13; models/pd_lifetime/CHANGELOG.md): how the
# refinancing incentive enters the default equation, then prepayment seasoning
D_VARIANTS = [
    ("A0 incentive bands in default", {"default_incentive": "bands"}),
    ("A1 no incentive in default", {"default_incentive": "none"}),
    ("A2 incentive >= 1pp indicator in default", {"default_incentive": "ge1"}),
]
P_VARIANTS = [
    ("B1 + age ramp (prepay)", "age"),
    ("B2 + young x incentive (prepay)", "young"),
    ("B3 + both (prepay)", "both"),
]
LIFETIME_SAMPLE = 40_000  # reporting-date loans used to compare specifications
SAMPLE_SEED = 20261113
JUMP_TOLERANCE = (0.8, 1.25)  # accepted model / empirical ratio of the year-2 over year-1 jump
JUMP_LAST_REF = "2021-12-01"  # OOT references need 12 quarters of outcomes (to 2024-12)
C_VARIANT = ("C1 state-specific delinquency decay (default)", "state")  # chosen specification
TAU_GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, np.inf]  # fade of the year-1 ratio
# Model-owner decision (2026-11-13; models/pd_lifetime/CHANGELOG.md): tau = 3 years = the
# 12-quarter explicit macro forecast, so the carried cycle mismatch fades on the forecast's time
# scale (paras 49, 124). The development argmin (inf) failed OOT; the grid is still reported as a sensitivity.
CARRY_TAU = 3.0
PARSIMONY = 0.05  # smallest tau within 5% of the best development error
# Stage D (model-owner decision, 2026-11-13): prepayment refinement for the 2012-16 gap. Adopt D2 if it moves
# the 2012-16 vintage lifetime PD at origination or the 2023-12 lifetime PD by > 5% vs D1 and
# does not lower the dev_train log-likelihood; otherwise keep D1 and monitor the gap (limitation
# L4, docs/limitations.md).
E_VARIANTS = [
    ("D0 no prepayment seasoning", "none"),
    ("D1 age ramp + young x incentive (B3)", "both"),
    ("D2 D1 + incentive x age 2-5y", "both5"),
]
PREPAY_MATERIALITY = 0.05
PREPAY_VINTAGES = list(range(2012, 2017))
MIN_SEGMENT_DEFAULTS = 30  # cells used to estimate the fade (year-2 / year-3 defaults)
logger = logging.getLogger(__name__)


def rows_for(
    sample: pd.DataFrame, loans: Loans, pos: pd.Series, path: MacroPath, woe_maps: dict
) -> QuarterRows:
    """Hazard covariate rows of the sampled person-quarters `sample` (each reference loan at
    quarter k on `path`)."""
    idx = pos.loc[sample.ref_id].values
    return quarter_rows(loans.take(idx), path, sample.k.values, woe_maps)


def evaluate_rows(
    models: dict, rows: QuarterRows, sample: pd.DataFrame, label: str
) -> tuple[list, list]:
    """Weighted log-likelihood per row and actual vs predicted events by horizon bucket."""
    fit_rows, calib = [], []
    y, w = sample.event.values, sample.weight.values
    hb = horizon_bucket(sample.k.values)
    for name, m in models.items():
        x, _ = design(rows, m.spec, m.opts)
        pr = m.probs(x)
        ll = np.sum(w * np.log(np.clip(pr[np.arange(len(y)), y], 1e-300, None))) / w.sum()
        fit_rows.append(
            {
                "split": label,
                "model": name,
                "rows": len(y),
                "weighted_rows": w.sum(),
                "mean_loglik": ll,
            }
        )
        for j, lab in enumerate(HB_LABELS):
            m_ = hb == j
            for e, out in [(1, "default"), (2, "prepay")]:
                act = np.sum(w[m_] * (y[m_] == e))
                pred = np.sum(w[m_] * pr[m_, e])
                calib.append(
                    {
                        "split": label,
                        "model": name,
                        "horizon": lab,
                        "outcome": out,
                        "exposure_quarters": w[m_].sum(),
                        "actual": act,
                        "predicted": pred,
                        "actual_to_predicted": act / pred if pred > 0 else np.nan,
                    }
                )
    return fit_rows, calib


def summarise_year1(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Mean actual 12-month default, 12m PIT PD and hazard year-1 default per group."""
    out = (
        df.groupby(by, observed=True)
        .agg(
            n=("actual", "size"),
            actual=("actual", "mean"),
            pit12=("pit12", "mean"),
            hazard_h2=("hazard_h2", "mean"),
            hazard_h1=("hazard_h1", "mean"),
        )
        .reset_index()
    )
    out["hazard_to_pit"] = out.hazard_h2 / out.pit12
    out["actual_to_hazard"] = out.actual / out.hazard_h2
    out["actual_to_pit"] = out.actual / out.pit12
    out["within_tolerance"] = out.hazard_to_pit.between(*SPLICE_TOLERANCE)
    out.insert(0, "breakdown", " x ".join(by))
    if len(by) > 1:
        out = out.rename(columns={by[-1]: "segment"})
    else:
        out["segment"] = "all"
    return out


def period_of(year: int) -> str:
    """Validation period label of a year."""
    return (
        "2000-06"
        if year <= 2006
        else "crisis 2007-11"
        if year <= 2011
        else "2012-16"
        if year <= 2016
        else "2017-19"
        if year <= 2019
        else "COVID 2020-21"
        if year <= 2021
        else "2022-23"
    )


@dataclass
class Ctx:
    """Everything the fits and checks share (built once)."""

    rho: float
    floor12: float
    floor_annual: float
    realised: object
    fwd: object
    lrp: object
    z_lr: float
    rq: pd.Period
    woe_maps: dict
    con: object
    ref: pd.DataFrame
    comp: dict
    ref_loans: Loans
    pos: pd.Series
    train: pd.DataFrame
    train_rows: object
    evals: dict  # split -> (sample, rows)
    chk_idx: np.ndarray  # references used in the year-1 check
    chk_pit12: np.ndarray
    orig: pd.DataFrame
    orig_loans: Loans
    hold: np.ndarray
    pf: pd.DataFrame
    pcomp: dict
    z_meas: pd.Series


def build_context() -> Ctx:
    """Load the inputs shared by every step: the PIT model, measured Z, macro history and the
    forward path, state HPI, the TTC scorecard, and the life, reference and origination tables
    with their projection inputs."""
    cfg = yaml.safe_load((ROOT / "config" / "rbi_2026.yaml").read_text(encoding="utf-8"))
    pit = json.loads((ROOT / "models" / "pd_pit" / "metadata.json").read_text())
    assert pit["version"] == PIT_MODEL, pit["version"]
    zq = pd.read_csv(ROOT / "models" / "pd_pit" / "z_by_quarter.csv")
    z_meas = pd.Series(zq.z_measured.values, index=pd.PeriodIndex(zq.quarter, freq="Q"))
    macro, _ = load_macro(ROOT / "data" / "macro")
    dev_q = slice(pit["estimation_quarters"][0], pit["estimation_quarters"][1])
    lr = {c: float(macro.loc[dev_q, c].mean()) for c in ["hpi_yoy", "gdp_yoy", "mortgage30"]}
    z_lr = float(pit["long_run_z"])
    hpi_state = read_state_hpi(ROOT / "data" / "macro" / "hpi_at_state.csv")
    realised = realised_path(macro, z_meas, hpi_state)
    for a in ["z_q", "hpi_yoy", "mortgage30"]:
        setattr(realised, a, pd.Series(getattr(realised, a)).ffill().bfill().values)
    rq = pd.Period(REPORT_DATE, freq="Q")
    fwd = reverting_path(
        macro, z_meas, hpi_state, pit["satellite"]["params"], lr, rq, REVERT_QUARTERS
    )
    sc = WoEScorecard.load(ROOT / "models" / "pd_12m" / "scorecard.pkl")
    woe_maps = {f: woe_map(sc, f) for f in ["current_ltv", "loan_age"]}

    logger.info("Life, reference and origination tables")
    con = duckdb.connect()
    create_life_table(con, PROCESSED)
    create_reference_table(con, PROCESSED / "pd_dataset")
    create_origination_table(con, PROCESSED)
    ref = con.execute(f"""SELECT ref_id, loan_id, obs_date, split, target_b18, current_upb,
        rm_ref, rate_ref, n_quarters, last_event, property_state,
        {", ".join(dict.fromkeys(SOURCE_COLUMNS))} FROM ref ORDER BY ref_id""").df()
    comp = components(sc, ref)
    ref_q = np.array([qidx(d) for d in pd.to_datetime(ref.obs_date)])
    ref_loans = loans_from(
        ref,
        comp,
        realised,
        ref.loan_age,
        ref.rm_ref,
        ref.current_upb,
        ref.rate_ref,
        ref.current_ltv,
        ref_q,
    )
    # the maps must reproduce the scorecard's WoE of current LTV and loan age
    assert np.allclose(woe_maps["current_ltv"](ref.current_ltv.values), comp["woe"][:, 1])
    assert np.allclose(woe_maps["loan_age"](ref.loan_age.values), comp["woe"][:, 5])
    pos = pd.Series(np.arange(len(ref)), index=ref.ref_id)
    logger.info(f"  {len(ref):,} reference dates ({ref.loan_id.nunique():,} loans)")
    train = sample_rows(con, "r.split = 'dev_train'")
    evals = {}
    for label, where in [
        ("dev_holdout", "r.split = 'dev_holdout'"),
        ("oot", "r.split IN ('oot1', 'oot2', 'oot3')"),
    ]:
        smp = sample_rows(con, where)
        evals[label] = (smp, rows_for(smp, ref_loans, pos, realised, woe_maps))
    chk_idx = np.where(ref.split.isin(["dev_holdout", "oot1", "oot2", "oot3"]).values)[0]
    ttc = 1 / (1 + np.exp(-comp["logit"][chk_idx]))
    zref = z_meas.reindex(
        pd.PeriodIndex(pd.to_datetime(ref.obs_date.values[chk_idx]), freq="Q")
    ).values

    orig = con.execute("SELECT * FROM orig ORDER BY loan_id").df()
    ofr = origination_frame(PROCESSED)
    orig = orig.drop(columns=["orig_ltv"]).merge(
        ofr.drop(columns=["vintage"]), on="loan_id", how="inner"
    )
    orig_q_month = pd.to_datetime(orig.first_payment_date) - pd.DateOffset(months=1)
    orig["orig_q"] = [qidx(d) for d in orig_q_month]
    orig["first_q"] = [qidx(d) for d in pd.to_datetime(orig.first_period)]
    st_idx = realised.state_index(orig.property_state.values)
    with np.errstate(divide="ignore", invalid="ignore"):
        ov = orig.orig_upb / (orig.orig_ltv / 100)
        value_first = ov * realised.hpi_ratio(st_idx, orig.orig_q.values, orig.first_q.values)
        orig["ltv_first"] = 100 * orig.upb_first / value_first
    orig_loans = loans_from(
        orig,
        components(sc, orig),
        realised,
        orig.age_first,
        orig.rm_first,
        orig.upb_first,
        orig.rate_first,
        orig.ltv_first,
        orig.first_q,
    )
    pf = con.execute(f"""SELECT s.loan_id, s.obs_date, s.current_upb, s.property_state,
            p.remaining_months AS rm, p.current_rate AS rate,
            {", ".join("s." + c for c in dict.fromkeys(SOURCE_COLUMNS))}
        FROM read_parquet('{(PROCESSED / "pd_dataset").as_posix()}/*/*.parquet',
                          hive_partitioning = true) s
        JOIN panel p ON p.loan_id = s.loan_id AND p.period = s.obs_date
        WHERE s.obs_date = DATE '{REPORT_DATE}' ORDER BY s.loan_id""").df()
    return Ctx(
        rho=pit["rho"],
        floor12=float(cfg["pd"]["floor_12_month"]["value"]),
        floor_annual=float(cfg["pd"]["floor_lifetime_annual"]["value"]),
        realised=realised,
        fwd=fwd,
        lrp=long_run_path(lr, z_lr, fwd.states),
        z_lr=z_lr,
        rq=rq,
        woe_maps=woe_maps,
        con=con,
        ref=ref,
        comp=comp,
        ref_loans=ref_loans,
        pos=pos,
        train=train,
        train_rows=rows_for(train, ref_loans, pos, realised, woe_maps),
        evals=evals,
        chk_idx=chk_idx,
        chk_pit12=vasicek_pd(ttc, zref, pit["rho"]),
        orig=orig,
        orig_loans=orig_loans,
        hold=np.array(holdout_flags(orig.loan_id.tolist())),
        pf=pf,
        pcomp=components(sc, pf),
        z_meas=z_meas,
    )


def fit(ctx: Ctx, spec: str, opts: dict) -> HazardModel:
    """Fit the competing-risk hazard `spec` with options `opts` on the dev_train rows (standard
    errors clustered by loan)."""
    x, names = design(ctx.train_rows, spec, opts)
    m = fit_mnl(
        x,
        ctx.train.event.values,
        ctx.train.weight.values,
        names,
        spec,
        cluster=pd.factorize(ctx.train.loan_id)[0],
        opts=opts,
    )
    m.woe_maps = ctx.woe_maps
    return m


def fit_tables(ctx: Ctx, models: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Log-likelihood and calibration-by-horizon tables of `models` on the dev_train rows and
    every evaluation sample (holdout, out of time)."""
    fr, cb = evaluate_rows(models, ctx.train_rows, ctx.train, "dev_train")
    for label, (smp, rows) in ctx.evals.items():
        f2, c2 = evaluate_rows(models, rows, smp, label)
        fr += f2
        cb += c2
    return pd.DataFrame(fr), pd.DataFrame(cb)


def year1_frame(ctx: Ctx, models: dict) -> pd.DataFrame:
    """Hazard 12-month default vs 12m PIT PD vs actual, for holdout and OOT references."""
    idx = ctx.chk_idx
    ref = ctx.ref
    out = {}
    for name, m in models.items():
        hd, hp = project(m, ctx.ref_loans.take(idx), ctx.realised, 4)
        out[f"hazard_{name.lower()}"] = cumulative(hd, hp)[1][:, 3]
    full_year = (ref.n_quarters.values[idx] >= 4) | (ref.last_event.values[idx] > 0)
    yr = pd.to_datetime(ref.obs_date.values[idx]).year
    ttc = 1 / (1 + np.exp(-ctx.comp["logit"][idx]))
    df = pd.DataFrame(
        {
            "period": [period_of(y) for y in yr],
            "dlq_state": np.array(DLQ_STATE_LABELS)[ctx.comp["dlq_state"][idx]],
            "ttc_decile": pd.qcut(ttc, 10, labels=False) + 1,
            "region": np.where(
                np.isin(ref.property_state.values[idx], SAND_STATES), "CA/FL/NV/AZ", "other states"
            ),
            "actual": ref.target_b18.values[idx].astype(float),
            "pit12": ctx.chk_pit12,
            **out,
        }
    )
    return df[full_year]


def vintage_tables(
    ctx: Ctx, models: dict, regions: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cumulative default and prepayment curves, actual (Aalen-Johansen) vs predicted on the
    realised macro path, for the dev_holdout loans of each vintage (and by region for
    2005-07). Returns (curves, summary)."""
    curves, summary = [], []
    label_end_q = qidx(LABEL_END)
    sand = np.isin(ctx.orig.property_state.values, SAND_STATES)
    for v in VINTAGES:
        for region in ["all", "CA/FL/NV/AZ", "other states"]:
            if region != "all" and not (regions and 2005 <= v <= 2007):
                continue
            m = ctx.hold & (ctx.orig.vintage.values == v)
            if region != "all":
                m &= sand if region == "CA/FL/NV/AZ" else ~sand
            ii = np.where(m)[0]
            kmax = int(label_end_q - np.quantile(ctx.orig.first_q.values[ii], 0.99))
            act = aalen_johansen(
                ctx.orig.n_quarters.values[ii], ctx.orig.last_event.values[ii], kmax
            )
            for name, mdl in models.items():
                hd, hp = project(mdl, ctx.orig_loans.take(ii), ctx.realised, kmax)
                _, cd, cp = cumulative(hd, hp)
                act[f"pred_default_{name}"] = cd.mean(axis=0)[: len(act)]
                act[f"pred_prepay_{name}"] = cp.mean(axis=0)[: len(act)]
            act.insert(0, "region", region)
            act.insert(0, "vintage", v)
            act["loans"] = len(ii)
            curves.append(act)
            for y in CURVE_YEARS:
                r = act[act.k == 4 * y]
                if len(r):
                    summary.append(
                        {
                            "vintage": v,
                            "region": region,
                            "years": y,
                            **r.drop(columns=["vintage", "region", "k"]).iloc[0].to_dict(),
                        }
                    )
    summary = pd.DataFrame(summary)
    for name in models:
        summary[f"actual_to_pred_default_{name}"] = (
            summary.actual_default / summary[f"pred_default_{name}"]
        )
        summary[f"actual_to_pred_prepay_{name}"] = (
            summary.actual_prepay / summary[f"pred_prepay_{name}"]
        )
    return pd.concat(curves, ignore_index=True), summary


def vintage_errors(summary: pd.DataFrame, name: str) -> dict:
    """Mean |logger.info(actual / predicted)| over vintages (all regions pooled = 'all')."""
    s = summary[summary.region == "all"]
    d = s[s.years.isin([1, 2, 3, 5])]
    p = s[s.years.isin([1, 2, 3])]
    return {
        "vintage_default_error": float(
            np.mean(np.abs(np.log(d.actual_default / d[f"pred_default_{name}"])))
        ),
        "vintage_prepay_error_y1_3": float(
            np.mean(np.abs(np.log(p.actual_prepay / p[f"pred_prepay_{name}"])))
        ),
        "prepay_y1_2012_16_actual": float(
            s[(s.years == 1) & (s.vintage >= 2012)].actual_prepay.mean()
        ),
        "prepay_y1_2012_16_pred": float(
            s[(s.years == 1) & (s.vintage >= 2012)][f"pred_prepay_{name}"].mean()
        ),
    }


def portfolio_lifetime(
    ctx: Ctx,
    model: HazardModel,
    path: MacroPath,
    z_first: float,
    idx: np.ndarray,
    tau: float = 0.0,
    chunk: int = 40_000,
) -> dict:
    """Spliced, floored lifetime PD of the reporting-date loans `idx` on one macro path; with
    tau > 0 the year-1 ratio PIT / hazard is carried into later years (calibrated splice)."""
    pf, pc = ctx.pf, ctx.pcomp
    ttc = 1 / (1 + np.exp(-pc["logit"][idx]))
    pd12 = np.maximum(vasicek_pd(ttc, z_first, ctx.rho), ctx.floor12)
    n_q = int(np.ceil(pf.rm.values[idx].max() / 3))
    years = int(np.ceil(n_q / 4))
    res = {
        k: np.zeros(len(idx))
        for k in ["lifetime", "lifetime_nofloor", "hazard_y1", "bound_years", "live_years"]
    }
    cum_year = np.zeros((len(idx), years), dtype=np.float32)
    for a in range(0, len(idx), chunk):
        ii = idx[a : a + chunk]
        sl = slice(a, a + len(ii))
        sub = loans_from(
            pf.iloc[ii],
            {k: v[ii] for k, v in pc.items()},
            path,
            pf.loan_age.values[ii],
            pf.rm.values[ii],
            pf.current_upb.values[ii],
            pf.rate.values[ii],
            pf.current_ltv.values[ii],
            np.full(len(ii), qidx(ctx.rq)),
        )
        hd, hp = project(model, sub, path, n_q)
        y1 = cumulative(hd, hp)[1][:, min(3, n_q - 1)]
        res["hazard_y1"][sl] = y1
        hd = carry_year1_ratio(hd, hp, pd12[sl] / np.maximum(y1, 1e-12), tau)
        s0, cd0, cp0 = cumulative(hd, hp)
        res["lifetime_nofloor"][sl] = splice_year1(cd0, cp0, s0, pd12[sl])[:, -1]
        hdf, bound = apply_annual_floor(hd, hp, ctx.floor_annual, first_year=1)
        s, cd, cp = cumulative(hdf, hp)
        spl = splice_year1(cd, cp, s, pd12[sl])
        res["lifetime"][sl] = spl[:, -1]
        cum_year[sl] = spl[:, np.minimum(np.arange(1, years + 1) * 4, n_q) - 1]
        res["bound_years"][sl] = bound[:, 1:].sum(axis=1)
        res["live_years"][sl] = year_live(hd, hp)[:, 1:].sum(axis=1)
    return {"pd12": pd12, **res, "cum_year": cum_year}


def z_first(ctx: Ctx) -> dict:
    """Z of the 12-month window after the reporting date (satellite on the path)."""
    return {
        "forward": float(ctx.fwd.at(ctx.fwd.z_s, np.array([qidx(ctx.rq)]))[0]),
        "long-run": ctx.z_lr,
    }


def variant_row(
    ctx: Ctx, stage: str, name: str, model: HazardModel, sample_idx: np.ndarray
) -> dict:
    """One row of the specification comparison: fit statistics, year-1 hazard / PIT ratio by
    period, vintage errors and the portfolio lifetime PD of a candidate model."""
    fs, _ = fit_tables(ctx, {"H2": model})
    y1 = year1_frame(ctx, {"H2": model})
    per = y1.groupby("period").agg(
        pit12=("pit12", "mean"), hazard=("hazard_h2", "mean"), actual=("actual", "mean")
    )
    ratio = per.hazard / per.pit12
    _, vs = vintage_tables(ctx, {"H2": model}, regions=False)
    lt = portfolio_lifetime(ctx, model, ctx.fwd, z_first(ctx)["forward"], sample_idx)
    return {
        "stage": stage,
        "variant": name,
        **model.opts,
        "terms": int(model.free.sum()),
        **{f"loglik_{r.split}": r.mean_loglik for r in fs.itertuples()},
        **{f"y1_hazard_to_pit[{p}]": v for p, v in ratio.items()},
        "y1_all_within_tolerance": bool(ratio.between(*SPLICE_TOLERANCE).all()),
        "y1_max_abs_log": float(np.abs(np.log(ratio)).max()),
        **vintage_errors(vs, "H2"),
        "lifetime_pd_2023_12_sample": float(lt["lifetime"].mean()),
    }


def jump_analysis(ctx: Ctx, model: HazardModel, taus: Iterable[float]) -> pd.DataFrame:
    """Year-2 and year-3 marginal default (conditional on surviving the previous year) and the
    year-2 / year-1 jump, model vs empirical (Aalen-Johansen), by delinquency state and TTC
    decile, for development (dev_holdout) and OOT references with 12 quarters of outcomes.
    Model: year 1 = 12m PIT PD (splice); later years = hazard, scaled by the year-1 ratio
    PIT / hazard faded with tau (calibrated splice; tau = 0: plain splice)."""
    ref = ctx.ref
    obs = pd.to_datetime(ref.obs_date.values)
    keep = (ref.split.values == "dev_holdout") | (
        ref.split.isin(["oot1", "oot2", "oot3"]).values & (obs <= pd.Timestamp(JUMP_LAST_REF))
    )
    idx = np.where(keep)[0]
    hd, hp = project(model, ctx.ref_loans.take(idx), ctx.realised, 12)
    y1_haz = cumulative(hd, hp)[1][:, 3]
    ttc = 1 / (1 + np.exp(-ctx.comp["logit"][idx]))
    zref = ctx.z_meas.reindex(pd.PeriodIndex(obs[idx], freq="Q")).values
    pit12 = vasicek_pd(ttc, zref, ctx.rho)
    base = pd.DataFrame(
        {
            "sample": np.where(
                ref.split.values[idx] == "dev_holdout", "development holdout 2000-16", "OOT 2017-21"
            ),
            "dlq_state": np.array(DLQ_STATE_LABELS)[ctx.comp["dlq_state"][idx]],
            "ttc_decile": pd.qcut(ttc, 10, labels=False) + 1,
            "n_quarters": ref.n_quarters.values[idx],
            "last_event": ref.last_event.values[idx],
            "pit12": pit12,
            "y1_hazard": y1_haz,
        }
    )
    groups = [
        (smp, by, seg, g.index.values)
        for smp, g0 in base.groupby("sample")
        for by in ["dlq_state", "ttc_decile"]
        for seg, g in g0.groupby(by)
    ]
    emp = {}
    for smp, by, seg, ii in groups:
        g = base.loc[ii]
        aj = aalen_johansen(g.n_quarters.values, g.last_event.values, 12)
        if len(aj) < 12:
            continue
        d4, d8, d12 = (aj.actual_default.iloc[i] for i in (3, 7, 11))
        s4 = 1 - d4 - aj.actual_prepay.iloc[3]
        s8 = 1 - d8 - aj.actual_prepay.iloc[7]
        emp[(smp, by, seg)] = {
            "references": len(g),
            "year2_defaults": int(np.sum(g.n_quarters.between(5, 8) & (g.last_event == 1))),
            "year3_defaults": int(np.sum(g.n_quarters.between(9, 12) & (g.last_event == 1))),
            "y1_actual": d4,
            "y2_cond_actual": (d8 - d4) / s4,
            "y3_cond_actual": (d12 - d8) / s8,
        }
    rows = []
    for tau in taus:
        hdc = carry_year1_ratio(hd, hp, pit12 / np.maximum(y1_haz, 1e-12), tau)
        s_, cd, _ = cumulative(hdc, hp)
        for smp, by, seg, ii in groups:
            if (smp, by, seg) not in emp:
                continue
            e = emp[(smp, by, seg)]
            y2 = (cd[ii, 7].mean() - cd[ii, 3].mean()) / s_[ii, 3].mean()
            y3 = (cd[ii, 11].mean() - cd[ii, 7].mean()) / s_[ii, 7].mean()
            jump_a = e["y2_cond_actual"] / e["y1_actual"] if e["y1_actual"] > 0 else np.nan
            jump_m = y2 / base.pit12.values[ii].mean()
            rows.append(
                {
                    "tau": tau,
                    "sample": smp,
                    "breakdown": by,
                    "segment": str(seg),
                    **e,
                    "y1_model_pit": base.pit12.values[ii].mean(),
                    "y1_hazard": base.y1_hazard.values[ii].mean(),
                    "y2_cond_model": y2,
                    "y3_cond_model": y3,
                    "jump_actual": jump_a,
                    "jump_model": jump_m,
                    "model_to_actual": jump_m / jump_a,
                    "y3_model_to_actual": y3 / e["y3_cond_actual"],
                    "flag": not (JUMP_TOLERANCE[0] <= jump_m / jump_a <= JUMP_TOLERANCE[1]),
                }
            )
    return pd.DataFrame(rows)


def fade_objective(ja: pd.DataFrame) -> pd.DataFrame:
    """Mean squared log error of the year-2 and year-3 conditional default, model vs empirical,
    over segments with >= MIN_SEGMENT_DEFAULTS defaults in that year; by tau and sample."""
    out = []
    for (tau, smp), g in ja.groupby(["tau", "sample"]):
        e2 = np.log(g.y2_cond_model / g.y2_cond_actual)[g.year2_defaults >= MIN_SEGMENT_DEFAULTS]
        e3 = np.log(g.y3_cond_model / g.y3_cond_actual)[g.year3_defaults >= MIN_SEGMENT_DEFAULTS]
        out.append(
            {
                "tau": tau,
                "sample": smp,
                "cells_y2": len(e2),
                "cells_y3": len(e3),
                "mse_log": float(np.mean(np.r_[e2.values, e3.values] ** 2)),
                "jump_flags": int(g.flag.sum()),
                "segments": len(g),
            }
        )
    return pd.DataFrame(out)


def prepay_row(ctx: Ctx, name: str, model: HazardModel, sample_idx: np.ndarray) -> dict:
    """Stage D: fit, vintage prepayment error, 2012-16 vintage prepay/default (realised macro),
    lifetime PD at origination of the 2012-16 vintage holdout loans (long-run macro, full term,
    annual floor, no splice) and the 2023-12 lifetime PD (sample, forward path, tau = CARRY_TAU)."""
    fs, _ = fit_tables(ctx, {"H2": model})
    _, vs = vintage_tables(ctx, {"H2": model}, regions=False)
    s = vs[(vs.region == "all") & vs.vintage.isin(PREPAY_VINTAGES)]
    ii = np.where(ctx.hold & np.isin(ctx.orig.vintage.values, PREPAY_VINTAGES))[0]
    n_q = int(np.ceil(ctx.orig.rm_first.values[ii].max() / 3))
    life = []
    for a in range(0, len(ii), 20_000):
        jj = ii[a : a + 20_000]
        sub = ctx.orig_loans.take(jj)
        sub.state_idx = ctx.lrp.state_index(ctx.orig.property_state.values[jj])
        hd, hp = project(model, sub, ctx.lrp, n_q)
        hd, _ = apply_annual_floor(hd, hp, ctx.floor_annual)
        life.append(cumulative(hd, hp)[1][:, -1])
    lt = portfolio_lifetime(ctx, model, ctx.fwd, z_first(ctx)["forward"], sample_idx, tau=CARRY_TAU)
    row = {
        "stage": "D: prepayment refinement",
        "variant": name,
        **model.opts,
        "terms": int(model.free.sum()),
        **{f"loglik_{r.split}": r.mean_loglik for r in fs.itertuples()},
        **vintage_errors(vs, "H2"),
        "loans_2012_16": len(ii),
        "lifetime_pd_2012_16_at_orig": float(np.concatenate(life).mean()),
        "lifetime_pd_2023_12_sample": float(lt["lifetime"].mean()),
    }
    for y in [1, 3, 5]:
        sy = s[s.years == y]
        row[f"prepay_y{y}_2012_16_actual_to_pred"] = float(
            sy.actual_prepay.sum() / sy.pred_prepay_H2.sum()
        )
        row[f"default_y{y}_2012_16_actual_to_pred"] = float(
            sy.actual_default.sum() / sy.pred_default_H2.sum()
        )
    return row


def fit_lifetime_pd() -> None:
    """Specification comparison, final hazard models, jump check and splice calibration,
    vintage curves, portfolio lifetime PDs and the SICR comparator; writes the model, tables and
    model card."""
    git = git_state(ROOT, CODE_AND_REGULATORY_CONFIG)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    ctx = build_context()
    rng = np.random.default_rng(SAMPLE_SEED)
    sample_idx = np.sort(rng.choice(len(ctx.pf), LIFETIME_SAMPLE, replace=False))

    logger.info("Specification comparison, stage A: refinancing incentive in the default equation")
    rows, fitted = [], {}
    for name, opts in D_VARIANTS:
        fitted[name] = fit(ctx, "H2", {**opts, "prepay_ramp": "none"})
        rows.append(variant_row(ctx, "A: default incentive", name, fitted[name], sample_idx))
        logger.info(
            f"  {name}: y1 2022-23 {rows[-1].get('y1_hazard_to_pit[2022-23]', np.nan):.3f}, "
            f"lifetime {rows[-1]['lifetime_pd_2023_12_sample']:.4f}"
        )
    a = pd.DataFrame(rows)
    ok = a[a.y1_all_within_tolerance]
    best_a = (
        (ok if len(ok) else a)
        .sort_values(["vintage_default_error" if len(ok) else "y1_max_abs_log"])
        .iloc[0]
    )
    chosen_d = best_a.default_incentive
    logger.info(f"  chosen: {best_a.variant}")

    logger.info("Specification comparison, stage B: prepayment seasoning")
    rows = [{**best_a.to_dict(), "stage": "B: prepayment seasoning"}]
    for name, ramp in P_VARIANTS:
        fitted[name] = fit(ctx, "H2", {"default_incentive": chosen_d, "prepay_ramp": ramp})
        rows.append(variant_row(ctx, "B: prepayment seasoning", name, fitted[name], sample_idx))
        logger.info(
            f"  {name}: prepay error {rows[-1]['vintage_prepay_error_y1_3']:.3f}, "
            f"loglik {rows[-1]['loglik_dev_train']:.5f}"
        )
    b = pd.DataFrame(rows)
    base_ll = b.iloc[0].loglik_dev_train
    eligible = b[b.loglik_dev_train >= base_ll]
    best_b = eligible.sort_values("vintage_prepay_error_y1_3").iloc[0]
    opts = {"default_incentive": chosen_d, "prepay_ramp": best_b.prepay_ramp}
    logger.info(f"  chosen: {opts}")
    shared = fitted[best_b.variant] if best_b.variant in fitted else fitted[best_a.variant]

    logger.info("Specification comparison, stage C: delinquency decay in the default equation")
    name_c, decay = C_VARIANT
    fitted[name_c] = fit(ctx, "H2", {**opts, "dlq_decay": decay})
    rows = [
        {
            **best_b.to_dict(),
            "stage": "C: delinquency decay",
            "variant": f"C0 shared fade ({best_b.variant})",
        },
        variant_row(ctx, "C: delinquency decay", name_c, fitted[name_c], sample_idx),
    ]
    for r_, m_ in zip(rows, [shared, fitted[name_c]], strict=True):
        j0 = jump_analysis(ctx, m_, [0.0])
        r_["dlq_decay"] = m_.opts["dlq_decay"]
        r_["jump_flags_dlq_state"] = int(j0[j0.breakdown == "dlq_state"].flag.sum())
        r_["jump_flags_ttc_decile"] = int(j0[j0.breakdown == "ttc_decile"].flag.sum())
        r_["jump_max_abs_log"] = float(np.abs(np.log(j0.model_to_actual)).max())
    c = pd.DataFrame(rows)
    opts = {**opts, "dlq_decay": decay}
    logger.info(
        f"  {name_c}: jump flags {rows[1]['jump_flags_dlq_state']} (states) / "
        f"{rows[1]['jump_flags_ttc_decile']} (deciles); shared: {rows[0]['jump_flags_dlq_state']}"
        f" / {rows[0]['jump_flags_ttc_decile']}"
    )

    logger.info("Specification comparison, stage D: prepayment refinement (2012-16 gap)")
    rows = []
    for name, ramp in E_VARIANTS:
        if ramp == opts["prepay_ramp"]:
            fitted[name] = fitted[name_c]
        else:
            fitted[name] = fit(ctx, "H2", {**opts, "prepay_ramp": ramp})
        rows.append(prepay_row(ctx, name, fitted[name], sample_idx))
        logger.info(
            f"  {name}: loglik {rows[-1]['loglik_dev_train']:.5f}, prepay error "
            f"{rows[-1]['vintage_prepay_error_y1_3']:.3f}, 2012-16 y1 prepay act/pred "
            f"{rows[-1]['prepay_y1_2012_16_actual_to_pred']:.2f}, lifetime 2012-16 "
            f"{rows[-1]['lifetime_pd_2012_16_at_orig']:.4f}, 2023-12 "
            f"{rows[-1]['lifetime_pd_2023_12_sample']:.4f}"
        )
    d = pd.DataFrame(rows)
    ref_d = d[d.prepay_ramp == opts["prepay_ramp"]].iloc[0]
    for k in ["lifetime_pd_2012_16_at_orig", "lifetime_pd_2023_12_sample"]:
        d[f"change_{k}_vs_D1"] = d[k] / ref_d[k] - 1
    cand = d[d.prepay_ramp == "both5"].iloc[0]
    material = (
        max(
            abs(cand.change_lifetime_pd_2012_16_at_orig_vs_D1),
            abs(cand.change_lifetime_pd_2023_12_sample_vs_D1),
        )
        > PREPAY_MATERIALITY
    )
    adopt_d2 = bool(material and cand.loglik_dev_train >= ref_d.loglik_dev_train)
    chosen_d = cand if adopt_d2 else ref_d
    logger.info(f"  D2 material: {material}; adopted: {adopt_d2}")
    opts = {**opts, "prepay_ramp": chosen_d.prepay_ramp}
    comparison = pd.concat([a, b, c, d], ignore_index=True)
    comparison["chosen"] = (comparison.stage == "D: prepayment refinement") & (
        comparison.variant == chosen_d.variant
    )

    logger.info("Final champion H2 and challenger H1")
    models = {"H2": fitted[chosen_d.variant], "H1": fit(ctx, "H1", opts)}
    h2 = models["H2"]
    coefs = pd.concat([m.coef_table().assign(model=k) for k, m in models.items()])
    fit_summary, calib = fit_tables(ctx, models)
    chk_df = year1_frame(ctx, models)
    splice = pd.concat(
        [
            summarise_year1(chk_df, by)
            for by in [["period", "dlq_state"], ["period", "ttc_decile"], ["period"]]
        ],
        ignore_index=True,
    )
    regional_y1 = summarise_year1(chk_df, ["period", "region"])
    logger.info("Year-2 / year-1 jump check and calibrated-splice fade")
    ja = jump_analysis(ctx, h2, TAU_GRID)
    tau_table = fade_objective(ja)
    dev_obj = tau_table[tau_table["sample"].str.startswith("development")].set_index("tau")
    residual = bool(ja[ja.tau == 0].flag.any())
    tau_dev = float(dev_obj.mse_log.idxmin())
    tau_pars = float(
        dev_obj.index[dev_obj.mse_log <= (1 + PARSIMONY) * dev_obj.mse_log.min()].min()
    )
    tau = CARRY_TAU if residual else 0.0
    jumps = pd.concat(
        [
            jump_analysis(ctx, shared, [0.0]).assign(model=f"{PREVIOUS} shared fade"),
            ja[ja.tau == 0].assign(model=f"{VERSION} state decay, plain splice"),
            ja[np.isinf(ja.tau)].assign(model=f"{INTERIM} carry tau=inf"),
            ja[ja.tau == tau].assign(model=f"{VERSION} carry tau={tau:g}"),
        ],
        ignore_index=True,
    )
    logger.info(
        f"  residual flags after state decay: {residual}; tau = {tau} (development argmin "
        f"{tau_dev}, parsimony rule {tau_pars})"
    )
    logger.info("Vintage curves")
    curves, curve_summary = vintage_tables(ctx, models)

    logger.info(f"Lifetime PDs of the {REPORT_DATE[:7]} portfolio")
    pf = ctx.pf
    all_idx = np.arange(len(pf))
    zf = z_first(ctx)
    per_loan = {
        "loan_id": pf.loan_id.values,
        "dlq_state": np.array(DLQ_STATE_LABELS)[ctx.pcomp["dlq_state"]],
        "ltv_band": pd.cut(pf.current_ltv, LTV_BANDS, labels=LTV_LABELS)
        .astype(str)
        .replace("nan", "missing")
        .values,
        "ttc_pd_12m": 1 / (1 + np.exp(-ctx.pcomp["logit"])),
        "loan_age": pf.loan_age.values,
    }
    curve_store = {}
    for pname, path in [("forward", ctx.fwd), ("long-run", ctx.lrp)]:
        r = portfolio_lifetime(ctx, h2, path, zf[pname], all_idx, tau=tau)
        for k in ["pd12", "hazard_y1", "lifetime", "lifetime_nofloor"]:
            per_loan[f"{k}_{pname}"] = r[k]
        per_loan[f"floor_bound_years_{pname}"] = r["bound_years"]
        per_loan[f"live_years_after_y1_{pname}"] = r["live_years"]
        curve_store[pname] = r["cum_year"]
        logger.info(f"  {pname}: mean lifetime PD {r['lifetime'].mean():.4f}")

    logger.info("SICR origination-side comparator (long-run macro, same remaining window)")
    orig = ctx.orig
    opos = pd.Series(np.arange(len(orig)), index=orig.loan_id)
    oi = opos.reindex(pf.loan_id).values
    has_orig = ~np.isnan(oi)
    oi = np.where(has_orig, oi, 0).astype(int)
    obs = pd.to_datetime(pf.obs_date)
    first = pd.to_datetime(orig.first_period.values[oi])
    months_since_first = (obs.dt.year * 12 + obs.dt.month).values - (first.year * 12 + first.month)
    comp_o = np.full(len(pf), np.nan)
    sel = np.where(has_orig)[0]
    n_qo = int(np.ceil(orig.rm_first.max() / 3))
    for a_ in range(0, len(sel), 40_000):
        ii = sel[a_ : a_ + 40_000]
        sub = ctx.orig_loans.take(oi[ii])
        sub.state_idx = ctx.lrp.state_index(orig.property_state.values[oi[ii]])
        hd, hp = project(h2, sub, ctx.lrp, n_qo)
        hd, _ = apply_annual_floor(hd, hp, ctx.floor_annual)
        s, cd, _ = cumulative(hd, hp)
        comp_o[ii] = remaining_from(cd, s, np.floor(months_since_first[ii] / 3).astype(int))
    per_loan["orig_expected_remaining_lr"] = comp_o
    pl = pd.DataFrame(per_loan)

    out_file = OUT / f"report_date={REPORT_DATE[:7]}.parquet"
    prev_file = OUT / f"report_date={REPORT_DATE[:7]}_{PREVIOUS}.parquet"
    interim_file = OUT / f"report_date={REPORT_DATE[:7]}_{INTERIM}.parquet"
    if out_file.exists() and not prev_file.exists():
        out_file.replace(prev_file)  # keep the previous version's PDs
    elif out_file.exists() and not interim_file.exists():
        out_file.replace(interim_file)  # keep the tau = inf candidate's PDs
    change = pd.DataFrame()
    if prev_file.exists():
        prev = pd.read_parquet(
            prev_file, columns=["loan_id", "lifetime_forward", "lifetime_long-run"]
        )
        m = pl.merge(prev, on="loan_id", suffixes=("", "_prev"))
        if interim_file.exists():
            m = m.merge(
                pd.read_parquet(interim_file, columns=["loan_id", "lifetime_forward"]).rename(
                    columns={"lifetime_forward": "lifetime_forward_interim"}
                ),
                on="loan_id",
                how="left",
            )
        rows = []
        for seg in ["all", "dlq_state", "ltv_band"]:
            groups = [("all", m)] if seg == "all" else list(m.groupby(seg))
            for val, g in groups:
                rows.append(
                    {
                        "segment": seg,
                        "value": val,
                        "loans": len(g),
                        f"lifetime_forward_{PREVIOUS}": g.lifetime_forward_prev.mean(),
                        f"lifetime_forward_{VERSION}": g.lifetime_forward.mean(),
                        f"lifetime_forward_{INTERIM}": (
                            g.lifetime_forward_interim.mean()
                            if "lifetime_forward_interim" in g
                            else np.nan
                        ),
                        "change_forward": g.lifetime_forward.mean() / g.lifetime_forward_prev.mean()
                        - 1,
                        f"lifetime_long_run_{PREVIOUS}": g["lifetime_long-run_prev"].mean(),
                        f"lifetime_long_run_{VERSION}": g["lifetime_long-run"].mean(),
                    }
                )
        change = pd.DataFrame(rows)
    pl.to_parquet(out_file, index=False)

    lt_rows = []
    for seg in ["dlq_state", "ltv_band"]:
        for val, g in pl.groupby(seg):
            ii = g.index.values
            for pname in ["forward", "long-run"]:
                cy = curve_store[pname][ii].mean(axis=0)
                lt_rows.append(
                    {
                        "segment": seg,
                        "value": val,
                        "macro": pname,
                        "loans": len(ii),
                        **{
                            f"cum_pd_y{y}": float(cy[y - 1])
                            for y in [1, 2, 3, 5, 10, 15, 20, 25, 30]
                            if y <= len(cy)
                        },
                    }
                )
    lifetime_curves = pd.DataFrame(lt_rows)
    summ = []
    for seg in ["all", "dlq_state", "ltv_band"]:
        groups = [("all", pl)] if seg == "all" else list(pl.groupby(seg))
        for val, g in groups:
            row = {"segment": seg, "value": val, "loans": len(g), "ttc_pd_12m": g.ttc_pd_12m.mean()}
            for pname in ["forward", "long-run"]:
                row[f"pd12_{pname}"] = g[f"pd12_{pname}"].mean()
                row[f"hazard_y1_{pname}"] = g[f"hazard_y1_{pname}"].mean()
                row[f"lifetime_{pname}"] = g[f"lifetime_{pname}"].mean()
                row[f"floor_effect_{pname}"] = (
                    g[f"lifetime_{pname}"].mean() / g[f"lifetime_nofloor_{pname}"].mean() - 1
                )
                row[f"floor_bound_share_loan_years_{pname}"] = g[
                    f"floor_bound_years_{pname}"
                ].sum() / max(g[f"live_years_after_y1_{pname}"].sum(), 1)
                row[f"floor_bound_share_loans_{pname}"] = (
                    g[f"floor_bound_years_{pname}"] > 0
                ).mean()
            row["orig_expected_remaining_lr"] = g.orig_expected_remaining_lr.mean()
            row["current_to_orig_ratio_median"] = (
                g.lifetime_forward / g.orig_expected_remaining_lr
            ).median()
            summ.append(row)
    lifetime_summary = pd.DataFrame(summ)
    pl["age_band"] = pd.cut(
        pl.loan_age, [-1, 24, 48, 96, 1000], labels=["0-2y", "2-4y", "4-8y", "8y+"]
    ).astype(str)
    sicr = (
        pl.assign(
            ratio_lr=pl["lifetime_long-run"] / pl.orig_expected_remaining_lr,
            ratio_fwd=pl.lifetime_forward / pl.orig_expected_remaining_lr,
        )
        .groupby(["dlq_state", "age_band"])
        .agg(
            loans=("ratio_lr", "size"),
            median_ratio_long_run=("ratio_lr", "median"),
            median_ratio_forward=("ratio_fwd", "median"),
            p90_ratio_long_run=("ratio_lr", lambda r: r.quantile(0.9)),
        )
        .reset_index()
    )

    meta = {
        "version": VERSION,
        "previous_version": PREVIOUS,
        "ttc_model": TTC_MODEL,
        "pit_model": PIT_MODEL,
        "trained_at": datetime.now(UTC).isoformat(),
        "git": git,
        "target": "target_b18",
        "rho": ctx.rho,
        "z_long_run": ctx.z_lr,
        "options": opts,
        "carry_tau": tau,
        "carry_tau_development_argmin": tau_dev,
        "carry_tau_parsimony_rule": tau_pars,
        "carry_rule": (
            "owner decision 2026-11-13: tau = 3 years, the 12-quarter explicit macro forecast "
            "(open question #5), so the carried cycle mismatch fades on the forecast's time "
            "scale (paras 49, 124); applied only if the jump check flags a segment after the "
            "state-specific decay. Secondary: smallest tau within 5% of the best development "
            "error (rule set after seeing the results) = "
            f"{tau_pars:g}; development argmin = {tau_dev:g} (failed OOT)"
        ),
        "prepay_refinement": {
            "materiality": PREPAY_MATERIALITY,
            "d2_material": bool(material),
            "d2_adopted": adopt_d2,
        },
        "revert_quarters": REVERT_QUARTERS,
        "report_date": REPORT_DATE,
        "label_end": LABEL_END,
        "floors": {"pd_12m": ctx.floor12, "lifetime_annual": ctx.floor_annual},
        "models": {k: {"terms": int(m.free.sum()), **m.meta} for k, m in models.items()},
        "selection": {
            "stage_A": "all periods' year-1 hazard/PIT within tolerance, then the "
            "lowest vintage default error",
            "stage_B": "dev_train log-likelihood not below the stage-A choice, then "
            "the lowest vintage prepayment error (years 1-3)",
            "stage_C": "state-specific delinquency decay in the default equation "
            "(owner decision 2026-11-13); shared fade reported",
            "stage_D": "D2 (incentive x age 2-5y) adopted only if it moves the "
            "2012-16 vintage lifetime PD at origination or the 2023-12 "
            "lifetime PD by > 5% vs D1 and does not lower the dev_train "
            "log-likelihood",
        },
        "splice_tolerance": SPLICE_TOLERANCE,
        "jump_tolerance": JUMP_TOLERANCE,
        "lifetime_sample_for_comparison": LIFETIME_SAMPLE,
        "data_note": "US Freddie Mac data and US macro (FRED); not Indian risk estimates",
    }
    tables = {
        "spec_comparison": comparison,
        "coefficients": coefs,
        "fit_summary": fit_summary,
        "calibration_by_horizon": calib,
        "splice_check": splice,
        "regional_year1": regional_y1,
        "jump_check": jumps,
        "carry_tau_sensitivity": tau_table,
        "vintage_curves": curves,
        "vintage_summary": curve_summary,
        "lifetime_curves": lifetime_curves,
        "lifetime_summary": lifetime_summary,
        "lifetime_change": change,
        "sicr_comparator": sicr,
    }
    for name, t in tables.items():
        t.to_csv(REPORTS / f"pd_lifetime_{name}.csv", index=False)
        t.to_csv(MODEL_DIR / f"{name}.csv", index=False)
    for k, m in models.items():
        m.save(MODEL_DIR / f"hazard_{k}.pkl")
    (MODEL_DIR / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    card = model_card(meta, tables)
    (MODEL_DIR / "model_card.md").write_text(card, encoding="utf-8")
    (REPORTS / "pd_lifetime_model_card.md").write_text(card, encoding="utf-8")
    logger.info("Done")


def model_card(meta: dict, t: dict[str, pd.DataFrame]) -> str:
    """Markdown model card of the lifetime PD model."""
    state = (
        "code and regulatory config committed"
        if meta["git"]["clean"]
        else "WITH UNCOMMITTED CHANGES - not reproducible from this commit"
    )
    co = t["coefficients"]
    return f"""# Model card: lifetime PD, competing-risk hazard ({meta["version"]}) — for review

**Code version.** git commit `{meta["git"]["commit"]}` ({state}); fitted {meta["trained_at"][:10]}.
Inputs: TTC `{meta["ttc_model"]}`, PIT `{meta["pit_model"]}` (rho {meta["rho"]}).
Methodology: `docs/methodology/pd_lifetime.md`. Development log: `models/pd_lifetime/CHANGELOG.md`.
**US data — not Indian risk estimates.**

Quarterly multinomial logit (default / prepay / survive) from a 1-in-16 hash sample of PD
snapshots as reference dates, fitted on dev_train references 2000-2016; outcomes to
{meta["label_end"][:7]}. Lifetime PD = cumulative incidence of default to contractual maturity
with prepayment as a competing risk (paras 46(1), 51). Year 1 is spliced to the 12-month PIT PD.
Every later year's conditional annual PD is floored at {meta["floors"]["lifetime_annual"]:.2%}
(config `pd.floor_lifetime_annual`, `rbi_specified: false`: para 96 sets the floor on "the
12-month PD"; extending it to later years is an interpretation).

**Specification chosen:** {meta["options"]} — stage A: {meta["selection"]["stage_A"]}; stage B:
{meta["selection"]["stage_B"]}; stage C: {meta["selection"]["stage_C"]}; stage D:
{meta["selection"]["stage_D"]} (D2 material: {meta["prepay_refinement"]["d2_material"]}, adopted:
{meta["prepay_refinement"]["d2_adopted"]}).

The forward-looking path is **illustrative** (published macro, then linear reversion over
{meta["revert_quarters"]} quarters to the 2000-2016 means); Module 4 supplies the scenarios.

## Specification comparison
{md_table(t["spec_comparison"])}

## Fit
{md_table(t["fit_summary"])}

## Coefficients, champion H2 (loan-clustered sandwich SE)
{md_table(co[co.model == "H2"].drop(columns="model"))}

## Calibration by horizon (actual / predicted events)
{md_table(t["calibration_by_horizon"])}

## Year-1 splice check
{md_table(t["splice_check"])}

## Year-2 / year-1 jump check (flag: model / actual outside {meta["jump_tolerance"]})
Calibrated splice: tau = {meta["carry_tau"]} ({meta["carry_rule"]}).

{md_table(t["carry_tau_sensitivity"])}

{md_table(t["jump_check"])}

## Regional year-1 (CO-3)
{md_table(t["regional_year1"])}

## Vintage curves (dev_holdout loans, realised macro)
{md_table(t["vintage_summary"])}

## Lifetime PD of the {meta["report_date"][:7]} portfolio
{md_table(t["lifetime_summary"])}

### Change from {meta["previous_version"]}
{md_table(t["lifetime_change"])}

{md_table(t["lifetime_curves"])}

## SICR comparator (long-run macro both sides)
{md_table(t["sicr_comparator"])}
"""
