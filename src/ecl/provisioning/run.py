"""Modules 6-8 entry point: staging, ECL measurement and prudential floors per reporting date.

`run_ecl(cfg, scen_cfg, lgd_cfg, overlays, inp, root, git)` for each reporting date in
config/scenarios.yaml and the quarter after it (transition matrix):
1. Portfolio as at the month: every live loan out of default (cured prior defaults included,
   para 77) from the scoring snapshot, plus loans in RBI default (Stage 3 candidates).
2. Per scenario (base paths of Module 4; CO-3 in the downside): 12-month and lifetime PD with
   the marginal PD by year; LGD and EAD by year (Module 5; CO-5 in the downside); ECL per
   scenario, then probability-weighted.
3. Origination-expected lifetime PD over the remaining window (staging/comparator.py); staging
   with the rule that fired (staging/rules.py).
4. Floors (floors/floors.py): Stage 1-2 portfolio level per stage, Stage 3 per account.
5. Sensitivities: SICR ratio 2.0 / 3.0; restructured = Stage 3; RBI fallback LGD 65/70%;
   Module 5 option-1 LGD. Diagnostics: stage-transition matrix (quarter after the date) and
   Stage 2 anticipation of next-12-month defaults.
Outputs: reports/summary/ecl_* (aggregates), models/ecl/ (run records), data/processed/ecl/
(loan level, not in git). US data; not Indian risk estimates.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pandas as pd
import yaml

from ecl.ead.ead import ead_now, secured_portion
from ecl.governance.overrides import OverrideLog, apply_overrides
from ecl.lgd import data as ld
from ecl.lgd.apply import downturn_factor, lgd_by_year, stage3_lgd
from ecl.lgd.models import load
from ecl.lgd.run import stage3_snapshot
from ecl.lifetime.cells import SAND_STATES
from ecl.lifetime.hazard_data import create_life_table, create_origination_table
from ecl.lifetime.paths import long_run_path, qidx
from ecl.lifetime.portfolio import components, lifetime_pd, origination_loans
from ecl.pd.dataset import build_scoring_snapshot
from ecl.pd.features import DLQ_STATE_LABELS
from ecl.pd.origination import origination_frame
from ecl.provisioning.ecl import discount_factors, ecl_12m, ecl_lifetime, weighted
from ecl.provisioning.floors import portfolio_floor, stage3_floor
from ecl.scenarios.build import to_macro_path
from ecl.scenarios.overlay import severity_scale, stressed
from ecl.scenarios.run import build_scenarios
from ecl.scenarios.scenario_pd import SCEN, co3_variant, z_first, z_trough
from ecl.staging.comparator import origination_expected_remaining
from ecl.staging.restructured import (
    TOL,
    covid_window,
    performance_summary,
    restructuring_events,
    stage3_history,
)
from ecl.staging.rules import stage_loans, transition_matrix

if TYPE_CHECKING:
    from ecl.scenarios.run_pd import Inputs

logger = logging.getLogger(__name__)


def _attrs(processed: Path, ids: pd.Series) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("ids", pd.DataFrame({"loan_id": ids.values}))
    loans = (processed / "loans").as_posix() + "/*/*.parquet"
    a = con.execute(f"""SELECT l.loan_id, l.mi_pct, l.orig_upb
        FROM read_parquet('{loans}', hive_partitioning=true) l JOIN ids USING (loan_id)
        ORDER BY l.loan_id""").df()
    con.close()
    return a


def _stage3_candidate_history(processed: Path, as_at: str) -> pd.DataFrame:
    """Monthly rows of every loan observed at the reporting month (not terminated) that has a
    default, modification, payment deferral or other relief month up to it, from the month
    before the first such month: UPB, status bucket, RBI default, modification, deferral,
    relief and disaster flags."""
    con = duckdb.connect()
    panel = (processed / "panel").as_posix() + "/*/*.parquet"
    h = con.execute(f"""
        WITH p AS (SELECT * FROM read_parquet('{panel}', hive_partitioning=true)
                   WHERE period <= DATE '{as_at}'),
        live AS (SELECT loan_id FROM p WHERE period = DATE '{as_at}' AND zb_code IS NULL),
        f AS (SELECT p.loan_id, MIN(period) AS first_event FROM p JOIN live USING (loan_id)
              WHERE default_event OR modified OR payment_deferral OR relief_flag GROUP BY 1)
        SELECT p.loan_id, p.period, p.current_upb, p.dpd_bucket,
               COALESCE(p.default_event, FALSE) AS default_event,
               COALESCE(p.modified, FALSE) AS modified,
               COALESCE(p.payment_deferral, FALSE) AS payment_deferral,
               COALESCE(p.relief_flag, FALSE) AS relief_flag,
               COALESCE(p.disaster_dlq, FALSE) AS disaster_dlq
        FROM p JOIN f USING (loan_id)
        WHERE p.period >= f.first_event - INTERVAL 1 MONTH
        ORDER BY p.loan_id, p.period""").df()
    con.close()
    return h


def _deferral_months(processed: Path) -> pd.Series:
    """Panel-wide payment-deferral months by calendar month (for the COVID window)."""
    con = duckdb.connect()
    panel = (processed / "panel").as_posix() + "/*/*.parquet"
    m = con.execute(f"""SELECT period, COUNT(*) AS n
        FROM read_parquet('{panel}', hive_partitioning=true) WHERE payment_deferral
        GROUP BY 1 ORDER BY 1""").df()
    con.close()
    return m.set_index(pd.to_datetime(m.period)).n


# variant suffix -> (event column, mode, NPA persists (None = config), miss rule (None = config),
# fresh restructurings). The step variants reproduce earlier published definitions.
STAGE3_VARIANTS = {
    "": ("ev_primary", "text", None, None, True),
    "_b": ("ev_primary", "stage3", None, None, True),
    "_c": ("ev_primary", "stage2", None, None, True),
    "_unm": ("mod_event", "text", None, None, True),
    "_allg": ("ev_all_general", "text", None, None, True),
    "_cal": ("calamity_event", "text", None, None, True),
    "_pub": ("mod_event", "text", None, "restart", False),
    "_s1": ("mod_event", "text", False, "restart", False),
}


def _stage3_columns(processed: Path, snap: str, scfg: dict, window: tuple) -> pd.DataFrame:
    """Per candidate loan: NPA-with-arrears flag (para 8(10)), restructuring state, duration in
    Stage 3 (para 82(5)) and calamity route, for the primary mapping, the sensitivities and the
    earlier published definitions (ecl.staging.restructured)."""
    tm = scfg["restructured"]["text_mapping"]
    lookback = scfg["deferrals"]["calamity_link"]["disaster_lookback_months"]
    ev = restructuring_events(_stage3_candidate_history(processed, snap), window, lookback)
    ev["ev_primary"] = ev.general_event
    ev["ev_all_general"] = ev.mod_event | ev.deferral_event
    out = None
    for sfx, (col, mode, npa, rule, fresh) in STAGE3_VARIANTS.items():
        v = stage3_history(
            ev,
            tm,
            mode,
            scfg["npa_until_arrears_cleared"] if npa is None else npa,
            col,
            tm["miss_during_monitoring"] if rule is None else rule,
            fresh,
        )
        keep = ["years_s3", "restr_state", "restructured", "events"]
        if sfx == "":
            keep += [
                "npa_arrears",
                "stuck",
                "months_after_first_payment",
                "repaid_on_clock",
                "restarts",
            ]
        if sfx == "_pub":
            keep += ["years_restr_s3"]
        v = v[["loan_id", *keep]].rename(columns={c: f"{c}{sfx}" for c in keep})
        out = v if out is None else out.merge(v, on="loan_id", how="left")
    perf = performance_summary(ev, snap, "ev_primary")
    perf["years_since_modification"] = perf.months_since_modification / 12
    by_loan = ev.groupby("loan_id").agg(
        deferral_events=("deferral_event", "sum"),
        calamity_linked=("calamity_link", "sum"),
        modification_events=("mod_event", "sum"),
    )
    return out.merge(perf, on="loan_id", how="left").merge(by_loan, on="loan_id", how="left")


class Context:
    """Everything shared by the dates: models, origination loans, long-run path."""

    def __init__(
        self, cfg: dict, scen_cfg: dict, lgd_cfg: dict, overlays: dict, inp: Inputs, root: Path
    ):
        self.cfg, self.scen_cfg, self.lgd_cfg, self.root = cfg, scen_cfg, lgd_cfg, root
        self.inp = inp
        self.co3 = overlays["CO-3"]
        self.co5 = overlays["CO-5"]
        md = root / "models/lgd"
        self.cure, self.cure1, self.sev = (
            load(md / "cure_model.pkl"),
            load(md / "cure_model_option1.pkl"),
            load(md / "severity_model.pkl"),
        )
        self.lgd_summary = json.loads((md / "fit_summary.json").read_text())
        self.haircut = self.lgd_summary["realisation_haircut"]
        rbi = inp.rbi
        self.floor12 = float(rbi["pd"]["floor_12_month"]["value"])
        self.floor_annual = float(rbi["pd"]["floor_lifetime_annual"]["value"])
        self.floors = rbi["floors"]["housing_loan_to_individuals"]
        # loan product categories (para 90-92): housing (xi)(a); calamity-restructured (xiv)
        self.floor_sets = {
            "xi_a": self.floors,
            "xiv": rbi["floors"]["advances_restructured_standard"],
        }
        self.fallback = rbi["lgd"]["fallback"]
        processed = root / "data/processed"
        con = duckdb.connect()
        create_life_table(con, processed)
        create_origination_table(con, processed)
        self.orig, self.orig_loans = origination_loans(
            con, origination_frame(processed), inp.sc, inp.realised
        )
        con.close()
        pit = inp.pit
        dev = slice(*pit["estimation_quarters"])
        lr = {c: float(inp.macro.loc[dev, c].mean()) for c in ["hpi_yoy", "gdp_yoy", "mortgage30"]}
        self.lrp = long_run_path(lr, float(pit["long_run_z"]), inp.realised.states)
        logger.info(f"Origination loans {len(self.orig):,}; long-run path {lr}")
        cl = cfg["staging"]["deferrals"]["calamity_link"]
        self.covid_window = covid_window(
            _deferral_months(processed), cl["baseline_years"], cl["multiplier"]
        )
        logger.info(f"COVID deferral window {[str(d.date()) for d in self.covid_window]}")
        gov = yaml.safe_load((root / "config/governance.yaml").read_text(encoding="utf-8"))
        ov = gov["overrides"]
        self.override_log = OverrideLog(root / ov["log_path"], ov["allowed"])
        self.override_info: dict = {}


def measure_date(
    ctx: Context,
    frames: dict,
    weights: dict,
    rq_paths: pd.Period,
    rq: pd.Period,
    measure: bool = True,
) -> pd.DataFrame:
    """Per-loan PDs, staging inputs and (if measure) ECL per scenario at quarter rq, with the
    scenario paths built as at rq_paths (rq_paths = rq on a reporting date; the quarter after
    reuses them)."""
    inp = ctx.inp
    processed = ctx.root / "data/processed"
    snap = f"{rq.year}-{rq.end_time.month:02d}-01"
    params = inp.pit["satellite"]["params"]
    paths = {
        k: to_macro_path(k, frames[k], params, inp.z_meas, rq_paths, inp.log_state, inp.betas)
        for k in SCEN
    }
    pf = build_scoring_snapshot(
        processed,
        snap,
        ctx.root / ctx.scen_cfg["state_paths"]["file"],
        exclude_prior_default=False,
    )
    pf = pf.merge(_attrs(processed, pf.loan_id), on="loan_id", how="left")
    pcomp = components(inp.sc, pf)
    pf["prior_dlq"] = pcomp["dlq_state"] > 0
    z_lr = float(inp.pit["long_run_z"])
    m = ctx.co3["calibration"]["m"]
    sand = pf.property_state.isin(SAND_STATES).values
    m_loan = np.where(sand, m["CA/FL/NV/AZ"], m["other"])
    s = severity_scale(
        z_lr,
        z_trough(paths["downside"], rq, ctx.scen_cfg["horizon_quarters"]),
        ctx.co3["calibration"]["z_min_replay"],
    )
    idx = np.arange(len(pf))
    tau = float(inp.life_meta["carry_tau"])
    out = {"loan_id": pf.loan_id.values}
    secured_now = None
    for k in SCEN:
        variants = {"model": None}
        if k == "downside":
            fn = co3_variant(paths[k], rq, m_loan, s)
            variants = {"co3": lambda ii, n_q, fn=fn: fn(ii, n_q, z_lr), "model": None}
        rv = lifetime_pd(
            inp.model,
            pf,
            pcomp,
            idx,
            paths[k],
            z_first(paths[k], rq),
            rq,
            inp.pit["rho"],
            ctx.floor12,
            ctx.floor_annual,
            tau,
            variants,
        )
        r = rv["co3"] if k == "downside" else rv["model"]
        r0 = rv["model"]  # no CO-3 (Annex 4 Table 6: before post-model adjustments)
        if np.isnan(r["pd12"]).any() or np.isnan(r["lifetime"]).any():
            raise ValueError(f"{rq} {k}: missing PD for {int(np.isnan(r['pd12']).sum())} loans")
        out[f"pd12_{k}"], out[f"pd_life_{k}"] = r["pd12"], r["lifetime"]
        if not measure:
            continue
        years = r["cum_year"].shape[1]
        ecfg = ctx.lgd_cfg["ead"]
        y = lgd_by_year(pf, ctx.cure, ctx.sev, paths[k], rq, years, ecfg)
        y1 = lgd_by_year(pf, ctx.cure1, ctx.sev, paths[k], rq, years, ecfg)
        lgd0 = y["lgd"].copy()  # no CO-5
        if k == "downside":
            q_def = qidx(rq) + np.floor((np.arange(years) + ecfg["default_point_in_year"]) * 4)
            mask = stressed(paths[k], q_def.astype(int), z_lr)
            y["lgd"] = np.minimum(y["lgd"] * downturn_factor(mask, ctx.co5["ratio"], s), 1.0)
            y1["lgd"] = np.minimum(
                y1["lgd"] * downturn_factor(mask, ctx.co5["ratio_option1"], s), 1.0
            )
        df = discount_factors(
            pf.orig_interest_rate.values, years, ctx.cfg["measurement"]["default_point_in_year"]
        )
        if secured_now is None:
            with np.errstate(divide="ignore", invalid="ignore"):
                value_now = np.where(
                    pf.current_ltv > 0, pf.current_upb / (pf.current_ltv / 100), np.nan
                )
            months_dlq = np.select([pf.dpd_bucket == "30-59", pf.dpd_bucket == "60-89"], [1, 2], 0)
            e_now = ead_now(pf.current_upb, pf.rate, months_dlq)
            sec, uns = secured_portion(e_now, value_now, ctx.haircut)
            secured_now = (e_now, sec, uns)
            fb = np.where(
                e_now > 0,
                (ctx.fallback["secured"] * sec + ctx.fallback["unsecured"] * uns) / e_now,
                ctx.fallback["secured"],
            )
        lgd_fb = np.repeat(fb[:, None], years, axis=1)
        for tag, lgd in [("", y["lgd"]), ("_opt1", y1["lgd"]), ("_fallback", lgd_fb)]:
            out[f"ecl12_{k}{tag}"] = ecl_12m(r["pd12"], lgd, y["ead"], df)
            out[f"ecl_life_{k}{tag}"] = ecl_lifetime(r["cum_year"], lgd, y["ead"], df)
        out[f"ecl12_{k}_noov"] = ecl_12m(r0["pd12"], lgd0, y["ead"], df)
        out[f"ecl_life_{k}_noov"] = ecl_lifetime(r0["cum_year"], lgd0, y["ead"], df)
        out[f"lgd12_{k}"] = y["lgd"][:, 0]
        logger.info(
            f"  {rq} {k}: PD12 {r['pd12'].mean():.4f}, lifetime {r['lifetime'].mean():.4f}, "
            f"ECL life {out[f'ecl_life_{k}'].sum() / 1e6:,.1f}m"
        )
    w = weights
    res = pd.DataFrame(out)
    res["pd12_weighted"] = weighted({k: res[f"pd12_{k}"] for k in SCEN}, w)
    res["pd_life_now"] = weighted({k: res[f"pd_life_{k}"] for k in SCEN}, w)
    if measure:
        for h in ["ecl12", "ecl_life"]:
            for tag in ["", "_opt1", "_fallback", "_noov"]:
                res[f"{h}_weighted{tag}"] = weighted({k: res[f"{h}_{k}{tag}"] for k in SCEN}, w)
        res["lgd12_weighted"] = weighted({k: res[f"lgd12_{k}"] for k in SCEN}, w)
        res["ead_now"], res["secured"], res["unsecured"] = secured_now
    res["pd12_ttc"] = 1 / (1 + np.exp(-np.asarray(pcomp["logit"], float)))  # Module 2 TTC
    res["pd_life_orig"] = origination_expected_remaining(
        inp.model,
        ctx.orig,
        ctx.orig_loans,
        ctx.lrp,
        pf.loan_id,
        pd.Timestamp(snap),
        ctx.floor_annual,
    )
    keep = [
        "vintage",
        "property_state",
        "current_ltv",
        "dpd_bucket",
        "ever_modified",
        "current_upb",
        "orig_interest_rate",
        "credit_score",
        "dpd_status_unknown",
    ]
    res = pd.concat([res, pf[keep].reset_index(drop=True)], axis=1)
    res["dlq_state"] = np.array(DLQ_STATE_LABELS)[pcomp["dlq_state"]]
    res["in_default"] = False
    res["modified"] = res.ever_modified.astype(bool)

    # Stage 3 candidates: loans in RBI default at the month
    s3 = stage3_snapshot(processed, snap)
    ov = s3.orig_upb / (s3.orig_ltv / 100)
    s3["value_now"] = ov * ld.hpi_ratio(
        inp.log_state,
        s3.property_state,
        ld._q(s3.orig_month),
        ld._q([pd.Timestamp(snap)] * len(s3)),
    )
    s3["ltv"] = 100 * s3.upb / s3.value_now
    s3["age"], s3["relief"] = s3.loan_age, s3.relief_flag.fillna(False)
    acc = np.where(s3.reo, s3.months_in_default + 3, s3.months_dlq.fillna(3))
    s3["ead_now"] = ead_now(s3.upb, s3.note_rate, acc)
    s3["secured"], s3["unsecured"] = secured_portion(s3.ead_now, s3.value_now, ctx.haircut)
    l3 = stage3_lgd(s3, ctx.cure, ctx.sev)
    s3["lgd3"] = l3.lgd.values
    s3["lgd3_opt1"] = stage3_lgd(s3, ctx.cure1, ctx.sev).lgd.values
    s3["lgd3_fallback"] = np.where(
        s3.ead_now > 0,
        (ctx.fallback["secured"] * s3.secured + ctx.fallback["unsecured"] * s3.unsecured)
        / s3.ead_now,
        ctx.fallback["secured"],
    )
    t3 = pd.DataFrame(
        {
            "loan_id": s3.loan_id,
            "in_default": True,
            "modified": False,
            "dpd_bucket": "90+",
            "current_ltv": s3.ltv,
            "vintage": s3.vintage,
            "property_state": s3.property_state,
            "current_upb": s3.upb,
            "orig_interest_rate": s3.note_rate,
            "credit_score": s3.credit_score,
            "dlq_state": "in default",
            "ead_now": s3.ead_now,
            "secured": s3.secured,
            "unsecured": s3.unsecured,
            "months_in_default": s3.months_in_default,
            "ecl3": s3.lgd3 * s3.ead_now,
            "ecl3_opt1": s3.lgd3_opt1 * s3.ead_now,
            "ecl3_fallback": s3.lgd3_fallback * s3.ead_now,
            "lgd3": s3.lgd3,
        }
    )
    res = pd.concat([res, t3], ignore_index=True)
    res = res.merge(
        _stage3_columns(processed, snap, ctx.cfg["staging"], ctx.covid_window),
        on="loan_id",
        how="left",
    )
    for c in ["npa_arrears", "stuck", *[f"restructured{x}" for x in STAGE3_VARIANTS]]:
        res[c] = res[c].fillna(False).astype(bool)
    # primary: restructured = general restructuring event; calamity route -> category (xiv)
    res["modified"] = res.restructured
    res["category"] = np.where(res.restructured_cal & ~res.restructured, "xiv", "xi_a")
    res["category_housing"] = "xi_a"
    # published definition (code b86ac3a): default spell only / restructured spell only
    res["years_old"] = np.where(res.in_default, res.months_in_default / 12, res.years_restr_s3_pub)
    res = pd.concat([res, stage_loans(res, ctx.cfg)], axis=1)
    return res


def provisions(
    res: pd.DataFrame,
    ctx: Context,
    stage_col: str = "stage",
    tag: str = "",
    years_col: str = "years_s3",
    cat_col: str = "category",
    per_loan: bool = False,
) -> dict | tuple[dict, pd.Series, pd.Series]:
    """Model ECL by stage, floors and final provision for one staging and one ECL variant.

    Floors per loan product category (para 90-92: housing (xi)(a); calamity-restructured
    standard (xiv)): Stages 1-2 on a portfolio basis per stage and category, Stage 3 per account
    by duration in Stage 3 (`years_col`, para 82(5); a loan in default without it falls back to
    its current default spell). Model ECL of a Stage 3 loan not 90+ at the date (restructured or
    arrears not cleared) = its lifetime ECL. per_loan: also return the allowance per loan (a
    portfolio floor uplift is allocated pro rata to exposure; presentation only)."""
    st = res[stage_col].to_numpy()
    ecl = np.where(
        st == 1,
        res[f"ecl12_weighted{tag}"].fillna(0),
        np.where(st == 2, res[f"ecl_life_weighted{tag}"].fillna(0), 0.0),
    )
    s3_ecl = res[f"ecl3{tag}"].fillna(0) if f"ecl3{tag}" in res else res["ecl3"].fillna(0)
    perf3 = (st == 3) & ~res.in_default.to_numpy(bool)
    ecl = np.where(st == 3, np.where(perf3, res[f"ecl_life_weighted{tag}"].fillna(0), s3_ecl), ecl)
    ecl = ecl.astype(float)
    ead = res.ead_now.to_numpy(float)
    cats = res[cat_col].to_numpy()
    yrs = res[years_col].to_numpy(float)
    in_d = res.in_default.to_numpy(bool)
    years = np.where(np.isnan(yrs) & in_d, res.months_in_default.to_numpy(float) / 12, yrs)
    allow = ecl.copy()
    out = {}
    for stage in (1, 2):
        m_all = st == stage
        agg = {"model_ecl": 0.0, "floor": 0.0, "provision": 0.0, "exposure": 0.0, "binds": False}
        by_cat = {}
        for c, fl in ctx.floor_sets.items():
            m = m_all & (cats == c)
            if not m.any():
                continue
            f = portfolio_floor(ecl[m], ead[m], fl[f"stage_{stage}"]["value"])
            if f["binds"] and f["exposure"] > 0:
                allow[m] = ecl[m] + (f["floor"] - f["model_ecl"]) * ead[m] / f["exposure"]
            by_cat[c] = {**f, "loans": int(m.sum())}
            for k in ["model_ecl", "floor", "provision", "exposure"]:
                agg[k] += f[k]
            agg["binds"] = agg["binds"] or (c == "xi_a" and f["binds"])
        out[f"stage{stage}"] = {**agg, "loans": int(m_all.sum()), "by_category": by_cat}
    m3 = st == 3
    f3_floor = np.zeros(len(res))
    for c, fl in ctx.floor_sets.items():
        m = m3 & (cats == c)
        if not m.any():
            continue
        s3c = fl["stage_3"]
        f3 = stage3_floor(
            ecl[m],
            res.secured.to_numpy(float)[m],
            res.unsecured.to_numpy(float)[m],
            np.nan_to_num(years[m], nan=0.0),
            s3c["bands"],
            s3c["band_boundaries"]["convention"],
        )
        f3_floor[m] = f3.floor.to_numpy()
        allow[m] = f3.provision.to_numpy()
    out["stage3"] = {
        "model_ecl": float(ecl[m3].sum()),
        "floor": float(f3_floor[m3].sum()),
        "provision": float(allow[m3].sum()),
        "binds_accounts": int((f3_floor[m3] > ecl[m3]).sum()),
        "accounts": int(m3.sum()),
        "exposure": float(ead[m3].sum()),
        "accounts_xiv": int((m3 & (cats == "xiv")).sum()),
    }
    tot_e = sum(out[s]["exposure"] for s in ["stage1", "stage2", "stage3"])
    out["total"] = {
        "model_ecl": sum(out[s]["model_ecl"] for s in ["stage1", "stage2", "stage3"]),
        "provision": sum(out[s]["provision"] for s in ["stage1", "stage2", "stage3"]),
        "exposure": tot_e,
    }
    for s in ["stage1", "stage2", "stage3", "total"]:
        out[s]["coverage_model"] = out[s]["model_ecl"] / out[s]["exposure"]
        out[s]["coverage_provision"] = out[s]["provision"] / out[s]["exposure"]
    if per_loan:
        return out, allow, ecl
    return out


def anticipation(processed: Path, res: pd.DataFrame, as_at: str, months: int) -> dict:
    """Share of the next-`months` RBI defaults (among loans not in default at the date) that
    were Stage 2 at the date; default rate by stage. Outcomes observed only to data end."""
    con = duckdb.connect()
    panel = (processed / "panel").as_posix() + "/*/*.parquet"
    d = con.execute(f"""SELECT loan_id, MIN(period) AS next_default, MAX(period) AS data_end
        FROM read_parquet('{panel}', hive_partitioning=true)
        WHERE period > DATE '{as_at}' AND period <= DATE '{as_at}' + INTERVAL {months} MONTH
          AND default_event GROUP BY 1 ORDER BY 1""").df()
    end = con.execute(f"SELECT MAX(period) FROM read_parquet('{panel}')").fetchone()[0]
    con.close()
    p = res[~res.in_default].merge(d[["loan_id"]].assign(defaulted=True), on="loan_id", how="left")
    p["defaulted"] = p.defaulted.fillna(False).astype(bool)
    dfl = p[p.defaulted]
    obs = min(
        months,
        (pd.Timestamp(end).year - pd.Timestamp(as_at).year) * 12
        + pd.Timestamp(end).month
        - pd.Timestamp(as_at).month,
    )
    return {
        "months_observed": int(obs),
        "defaults": len(dfl),
        "share_stage2_at_date": float((dfl.stage == 2).mean()) if len(dfl) else None,
        "share_stage2_by_rule": dfl[dfl.stage == 2]
        .stage_rule.value_counts(normalize=True)
        .to_dict()
        if len(dfl)
        else {},
        "default_rate_stage1": float(p[p.stage == 1].defaulted.mean()),
        "default_rate_stage2": float(p[p.stage == 2].defaulted.mean()),
        "stage2_share_of_loans": float((p.stage == 2).mean()),
    }


# restructuring mapping -> (stage_loans mapping, state col, years col, restructured col, category)
MAPPINGS = {
    "text": ("text", "restr_state", "years_s3", "restructured", "category"),
    "stage3": ("stage3", "restr_state", "years_s3_b", "restructured", "category"),
    "stage2": ("stage2", "restr_state", "years_s3_c", "restructured", "category"),
    "deferrals_unmapped": (
        "text",
        "restr_state_unm",
        "years_s3_unm",
        "restructured_unm",
        "category_housing",
    ),
    "deferrals_all_general": (
        "text",
        "restr_state_allg",
        "years_s3_allg",
        "restructured_allg",
        "category_housing",
    ),
}


def _sensitivity_grid(res: pd.DataFrame, ctx: Context, date: str) -> tuple:
    """Provisions by stage for restructuring mapping x SICR ratio x LGD (config
    `sensitivity_grid`), and the summary sensitivities (each mapping at the primary SICR ratio
    and champion LGD; each SICR ratio under the primary mapping)."""
    cfg = ctx.cfg
    g = cfg["sensitivity_grid"]
    primary_map = cfg["staging"]["restructured"]["treatment"]
    primary_ratio = cfg["staging"]["sicr_pd"]["ratio_threshold"]
    rows, sens = [], {}
    for mp in g["restructured"]:
        arg, scol, ycol, mcol, ccol = MAPPINGS[mp]
        view = res.assign(modified=res[mcol])
        for ratio in g["sicr_ratios"]:
            alt = stage_loans(view, cfg, ratio=ratio, restructured=arg, state_col=scol)
            for lg in g["lgd"]:
                pv = provisions(
                    res.assign(stage=alt.stage.values), ctx, tag=lg, years_col=ycol, cat_col=ccol
                )
                row = {
                    "as_on": date,
                    "restructured": mp,
                    "sicr_ratio": ratio,
                    "lgd": "option1" if lg else "champion",
                }
                for k in ["stage1", "stage2", "stage3", "total"]:
                    b = pv[k]
                    row[f"{k}_loans"] = b.get("loans", b.get("accounts"))
                    for f in ["exposure", "model_ecl", "provision", "coverage_model"]:
                        row[f"{k}_{f}"] = b[f]
                    row[f"{k}_coverage_provision"] = b["coverage_provision"]
                row["stage2_floor_binds"] = pv["stage2"]["binds"]
                row["stage3_floor_binds_accounts"] = pv["stage3"]["binds_accounts"]
                rows.append(row)
                if lg == "" and ratio == primary_ratio:
                    sens[f"restructured_{mp}"] = {
                        "stage_mix": alt.stage.value_counts().sort_index().to_dict(),
                        "by_stage": pv,
                    }
                if lg == "" and mp == primary_map and ratio != primary_ratio:
                    sens[f"sicr_ratio_{ratio}"] = {
                        "stage_mix": alt.stage.value_counts().sort_index().to_dict(),
                        **pv["total"],
                    }
    return pd.DataFrame(rows), sens


def stage3_duration_steps(res: pd.DataFrame, ctx: Context) -> dict:
    """Sequence of text-based fixes and their provisions (each step adds one fix):
    0 published (b86ac3a): duration = current default spell / restructured spell; default = 90+
      month; first modification only; a miss restarts the clock;
    1 duration = unbroken Stage 3 spell (para 82(5); RSA 53-54);
    2 + NPA until arrears are cleared (para 8(10)) (code b998286);
    3 + RSA 61 / 62 (a miss blocks upgrades until a fresh restructuring; later modifications are
      fresh restructurings);
    4 + deferrals split by cause: calamity route (xiv) / general restructuring (primary)."""
    bands = [-np.inf, 1, 2, 3, 4, np.inf]
    labels = ["0-1y", "1-2y", "2-3y", "3-4y", ">4y"]
    no_arrears = res.assign(npa_arrears=False)
    steps = [
        (
            "0_published",
            no_arrears,
            "restr_state_pub",
            "restructured_pub",
            "years_old",
            "category_housing",
        ),
        (
            "1_unbroken_spell",
            no_arrears,
            "restr_state_s1",
            "restructured_s1",
            "years_s3_s1",
            "category_housing",
        ),
        (
            "2_para_8_10",
            res,
            "restr_state_pub",
            "restructured_pub",
            "years_s3_pub",
            "category_housing",
        ),
        (
            "3_rsa_61_fresh_restructuring",
            res,
            "restr_state_unm",
            "restructured_unm",
            "years_s3_unm",
            "category_housing",
        ),
        ("4_deferral_split_primary", res, "restr_state", "restructured", "years_s3", "category"),
    ]
    out = {}
    for name, frame, scol, mcol, ycol, ccol in steps:
        st = stage_loans(frame.assign(modified=frame[mcol]), ctx.cfg, state_col=scol).stage.values
        pv = provisions(res.assign(stage=st), ctx, years_col=ycol, cat_col=ccol)
        m3 = st == 3
        y = res.loc[m3, ycol].fillna(res.loc[m3, "months_in_default"] / 12)
        out[name] = {
            "stage_mix": pd.Series(st).value_counts().sort_index().to_dict(),
            "stage3_provision": pv["stage3"]["provision"],
            "total_provision": pv["total"]["provision"],
            "stage3_duration_bands": pd.cut(y, bands, labels=labels, right=False)
            .value_counts()
            .reindex(labels)
            .to_dict(),
        }
    return out


def deferral_summary(res: pd.DataFrame) -> dict:
    """Loans with a payment deferral, not in default at the date, by route: calamity route
    (category (xiv), standard), general restructuring (deferral event, no modification), and
    modified loans that also had a deferral."""
    live = res[~res.in_default & (res.deferral_events.fillna(0) > 0)]
    mod = live.modification_events.fillna(0) > 0
    route = np.select(
        [live.category == "xiv", ~mod & live.restructured, mod],
        ["calamity route (xiv)", "general restructuring (deferral)", "modified (general)"],
        "other",
    )
    g = live.assign(route=route).groupby(["route", "stage"])
    return {
        "by_route_stage": g.agg(loans=("loan_id", "size"), ead=("ead_now", "sum"))
        .reset_index()
        .to_dict(orient="records"),
        "calamity_linked_loans": int((live.calamity_linked.fillna(0) > 0).sum()),
    }


def restructuring_summary(res: pd.DataFrame, rcfg: dict) -> dict:
    """Restructured loans (general route) not in default at the date: final stage and
    restructuring state with the reason (missed payment -> RSA 61 block / repayment / time),
    fresh restructurings, and % repaid since the first restructuring."""
    tm = rcfg["text_mapping"]
    m = res[res.modified.fillna(False).astype(bool) & ~res.in_default].copy()
    if not len(m):
        return {"loans": 0}
    r2, mo = tm["stage2_repaid"], tm["stage2_months_after_first_payment"]
    rep_ok = m.repaid_on_clock >= r2 - TOL
    time_ok = m.months_after_first_payment >= mo
    m["reason"] = np.select(
        [
            m.restr_state == 1,
            m.restr_state == 2,
            m.stuck,
            ~rep_ok & ~time_ok,
            ~rep_ok,
            ~time_ok,
        ],
        [
            f"graduated: >= {tm['stage1_repaid']:.0%} repaid, no missed payment",
            f"Stage 2: >= {r2:.0%} and < {tm['stage1_repaid']:.0%} repaid",
            "Stage 3: missed payment after implementation (RSA 61 / 62)",
            f"Stage 3: < {mo} months and < {r2:.0%} repaid",
            f"Stage 3: < {r2:.0%} repaid (time met)",
            f"Stage 3: < {mo} months (repayment met)",
        ],
        "other",
    )
    m["fresh_restructuring"] = m.events > 1
    by = (
        m.groupby(["restr_state", "reason", "fresh_restructuring", "stage"])
        .agg(loans=("loan_id", "size"), ead=("ead_now", "sum"))
        .reset_index()
    )
    bands = [-np.inf, 0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, np.inf]
    labels = ["<=0%", "0-5%", "5-10%", "10-15%", "15-20%", "20-30%", "30-50%", ">50%"]

    def dist(x: pd.Series) -> dict:
        return pd.cut(x, bands, labels=labels).value_counts().reindex(labels).to_dict()

    return {
        "loans": len(m),
        "ead": float(m.ead_now.sum()),
        "months_since_modification_quartiles": m.months_since_modification.quantile(
            [0.25, 0.5, 0.75]
        ).tolist(),
        "share_missed_payment_since_modification": float(m.dlq30_since_modification.mean()),
        "share_current_now": float((m.dpd_bucket == "current").mean()),
        "restructuring_state": m.restr_state.value_counts().sort_index().to_dict(),
        "final_stage": m.stage.value_counts().sort_index().to_dict(),
        "by_reason": by.to_dict(orient="records"),
        "repaid_since_modification": dist(m.repaid_since_modification),
        "repaid_on_current_clock": dist(m.repaid_on_clock),
        "repaid_since_modification_quartiles": m.repaid_since_modification.quantile(
            [0.25, 0.5, 0.75]
        ).tolist(),
    }


def report_date(
    date: str, res: pd.DataFrame, nxt: pd.DataFrame, ctx: Context, weights: dict, git: dict
) -> dict:
    """Final provisions for one reporting date: model ECL and floors per stage (paras 82, 90-92),
    sensitivities, stage transitions to the next quarter and the drivers table. Writes the
    loan-level result to data/processed/ecl/ and the aggregate tables to reports/summary/;
    returns the run record."""
    root, cfg = ctx.root, ctx.cfg
    tag = pd.Timestamp(date).strftime("%Y-%m")
    rep = root / "reports/summary"
    out_dir = root / "data/processed/ecl"
    out_dir.mkdir(parents=True, exist_ok=True)
    base, res["allowance"], res["ecl_stage_model"] = provisions(res, ctx, per_loan=True)
    noov, res["allowance_noov"], res["ecl_stage_model_noov"] = provisions(
        res, ctx, tag="_noov", per_loan=True
    )
    res.to_parquet(out_dir / f"ecl_{tag}.parquet", index=False)
    grid, sens = _sensitivity_grid(res, ctx, date)
    grid.to_csv(rep / f"ecl_sensitivity_grid_{tag}.csv", index=False)
    sens["lgd_fallback_65_70"] = provisions(res, ctx, tag="_fallback")["total"]
    sens["lgd_option1"] = provisions(res, ctx, tag="_opt1")["total"]
    sens["no_overlays_co3_co5"] = {k: noov[k] for k in ["stage1", "stage2", "stage3", "total"]}
    per_scen = {}
    for k in SCEN:
        r2 = res.copy()
        r2["ecl12_weighted"], r2["ecl_life_weighted"] = r2[f"ecl12_{k}"], r2[f"ecl_life_{k}"]
        per_scen[k] = provisions(r2, ctx)["total"]

    # stage mix, rules, drivers
    mix = res.groupby("stage").agg(loans=("loan_id", "size"), ead=("ead_now", "sum"))
    mix["share_loans"], mix["share_ead"] = mix.loans / mix.loans.sum(), mix.ead / mix.ead.sum()
    rules = res[res.stage > 1].groupby(["stage", "stage_rule"]).size().rename("loans")
    fired = res.rules_fired.str.get_dummies(sep=";").sum().rename("loans_with_rule")
    fired = fired[fired.index != ""]
    st = res.stage.values
    s3_ecl = np.where(res.in_default, res.ecl3, res.ecl_life_weighted)
    res["ecl_model"] = np.where(
        st == 1, res.ecl12_weighted, np.where(st == 2, res.ecl_life_weighted, s3_ecl)
    ).astype(float)
    res["ltv_band"] = (
        pd.cut(res.current_ltv, cfg["ltv_bands"], labels=cfg["ltv_labels"])
        .astype(str)
        .replace("nan", "missing")
    )
    res["region"] = np.where(res.property_state.isin(SAND_STATES), "CA/FL/NV/AZ", "other")
    res["vintage_band"] = pd.cut(
        res.vintage, [0, 2008, 2016, 2023, 2030], labels=["<=2008", "2009-16", "2017-23", "2024-26"]
    ).astype(str)
    drv = []
    for var in ["stage_rule", "ltv_band", "region", "vintage_band", "dlq_state"]:
        g = (
            res.groupby(["stage", var])
            .agg(loans=("loan_id", "size"), ead=("ead_now", "sum"), ecl=("ecl_model", "sum"))
            .reset_index()
        )
        g["coverage"] = g.ecl / g.ead
        drv.append(g.rename(columns={var: "value"}).assign(driver=var))
    drv = pd.concat(drv, ignore_index=True)
    drv.insert(0, "as_on", date)
    drv.to_csv(rep / f"ecl_drivers_{tag}.csv", index=False)

    rows = []
    for s in ["stage1", "stage2", "stage3", "total"]:
        b = base[s]
        rows.append(
            {
                "as_on": date,
                "stage": s,
                "loans": b.get("loans", b.get("accounts")),
                "exposure": b["exposure"],
                "model_ecl": b["model_ecl"],
                "floor": b.get("floor"),
                "floor_binds": b.get("binds", b.get("binds_accounts")),
                "provision": b["provision"],
                "coverage_model": b["coverage_model"],
                "coverage_provision": b["coverage_provision"],
            }
        )
    tab = pd.DataFrame(rows)
    tab.to_csv(rep / f"ecl_by_stage_{tag}.csv", index=False)
    trans = transition_matrix(res, nxt) if nxt is not None else None
    if trans is not None:
        trans.to_csv(rep / f"ecl_stage_transition_{tag}.csv")
    ant = anticipation(
        root / "data/processed",
        res,
        f"{pd.Timestamp(date):%Y-%m}-01",
        cfg["anticipation"]["horizon_months"],
    )
    record = {
        "as_on": date,
        "version": cfg["version"],
        "git": git,
        "weights": weights,
        "by_stage": base,
        "stage_mix": mix.reset_index().to_dict(orient="records"),
        "stage_rules": {f"{a} {b}": int(v) for (a, b), v in rules.items()},
        "rules_fired_any": fired.to_dict(),
        "sicr_comparator_missing": int(res.pd_life_orig.isna().sum() - res.in_default.sum()),
        "sensitivities": sens,
        "restructuring": restructuring_summary(res, cfg["staging"]["restructured"]),
        "stage3_duration_steps": stage3_duration_steps(res, ctx),
        "deferrals": deferral_summary(res),
        "covid_window": [str(d.date()) for d in ctx.covid_window],
        "per_scenario_100pct": per_scen,
        "transition_from_to": trans.round(4).to_dict(orient="index") if trans is not None else None,
        "anticipation": ant,
        "overrides": ctx.override_info.get(date),
    }
    (root / "models/ecl").mkdir(parents=True, exist_ok=True)
    (root / "models/ecl" / f"ecl_{tag}.json").write_text(
        json.dumps(record, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    )
    return record


def run_ecl(
    cfg: dict, scen_cfg: dict, lgd_cfg: dict, overlays: dict, inp: Inputs, root: Path, git: dict
) -> dict:
    """Staging, ECL measurement and prudential floors (Modules 6-8) for every reporting date in
    the scenarios config, with approved manual overrides applied (Annex 3). Returns the run
    record per date."""
    ctx = Context(cfg, scen_cfg, lgd_cfg, overlays, inp, root)
    out = {}
    for date in scen_cfg["base"]["dates"]:
        rq = pd.Period(pd.Timestamp(date), freq="Q")
        run, frames = build_scenarios(date, scen_cfg, inp.macro, inp.pit, git, root, write=False)
        weights = {k: run["scenarios"][k]["weight"] for k in SCEN}
        logger.info(f"ECL as on {date}")
        res = measure_date(ctx, frames, weights, rq, rq, measure=True)
        # Module 9: approved manual overrides (maker-checker log) apply from this run on
        head = ctx.override_log.verify()
        res, info = apply_overrides(res, ctx.override_log.active(date))
        ctx.override_info[date] = {"log_head_hash": head, **info}
        logger.info(f"Overrides applied {len(info['applied'])}, rejected {len(info['rejected'])}")
        nxt = None
        if cfg["transition"]["quarter_after"]:
            logger.info(f"Staging the quarter after ({rq + 1})")
            nxt = measure_date(ctx, frames, weights, rq, rq + 1, measure=False)
        out[date] = report_date(date, res, nxt, ctx, weights, git)
    return out
