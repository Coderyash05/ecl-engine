"""Module 5 entry points: fit and validate LGD, then apply LGD / EAD on the reporting dates.

- `fit_lgd(cfg, root, log_state)`: defaults table (data.py), cure and severity models (models.py) on
  defaults up to 2016 (development), validation by period / vintage / LTV band / months in
  default, out-of-time check on 2017+ defaults, crisis-gap check, realisation haircut.
- `apply_lgd(date, ...)`: per loan and scenario, LGD and EAD by year, 12-month and PD-weighted
  lifetime LGD, probability-weighted across scenarios (downside with CO-3 PDs); secured /
  unsecured portion (para 6(24)); Stage 3 LGD by months in default; comparison with the RBI
  fallback LGD (para 97).
Outputs: models/lgd/ (artefacts, tables), reports/summary/lgd_* (aggregates),
data/processed/lgd/ (loan level, not in git). US data; not Indian risk estimates.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pandas as pd
from numpy.typing import ArrayLike
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

from ecl.ead.ead import ead_now, secured_portion
from ecl.lgd import data as ld
from ecl.lgd.apply import downturn_factor, lgd_by_year, pd_weighted, stage3_lgd
from ecl.lgd.models import CureModel, SeverityModel, cure_frame, save, severity_frame
from ecl.lifetime.paths import qidx
from ecl.lifetime.portfolio import components, lifetime_pd
from ecl.pd.dataset import build_scoring_snapshot
from ecl.scenarios.build import to_macro_path
from ecl.scenarios.overlay import severity_scale, stressed
from ecl.scenarios.run import build_scenarios
from ecl.scenarios.scenario_pd import SCEN, co3_variant, z_first, z_trough

if TYPE_CHECKING:
    from ecl.scenarios.run_pd import Inputs

logger = logging.getLogger(__name__)


def _period(years: pd.Series, periods: dict) -> np.ndarray:
    out = np.full(len(years), "other", dtype=object)
    for name, (a, b) in periods.items():
        out[(years >= a) & (years <= b)] = name
    return out


def _band(x: ArrayLike, bands: list[float], labels: list[str]) -> np.ndarray:
    return pd.cut(x, bands, labels=labels).astype(str).replace("nan", "missing").values


def validation_table(d: pd.DataFrame, by: str) -> pd.DataFrame:
    """Actual vs predicted at default (m = 0), resolved defaults: no-cure rate, severity of
    complete liquidations, LGD = no-cure x severity within the group."""
    rows = []
    for g, x in d.groupby(by):
        liq = x[x.loss_complete]
        r = {
            "breakdown": by,
            "group": g,
            "resolved_defaults": len(x),
            "liquidations_complete": len(liq),
            "actual_no_cure": x.y.mean(),
            "pred_no_cure": x.p_no_cure.mean(),
            "actual_severity": liq.severity.clip(0, 1).mean() if len(liq) else np.nan,
            "actual_severity_unclipped": liq.severity.mean() if len(liq) else np.nan,
            "pred_severity": liq.pred_severity.mean() if len(liq) else np.nan,
        }
        r["actual_lgd"] = r["actual_no_cure"] * r["actual_severity_unclipped"]
        r["pred_lgd"] = (x.p_no_cure * x.pred_severity).mean()
        r["actual_to_pred_lgd"] = r["actual_lgd"] / r["pred_lgd"]
        rows.append(r)
    return pd.DataFrame(rows)


def fit_lgd(cfg: dict, root: Path, log_state: pd.DataFrame) -> dict:
    """Fit and validate the LGD models (para 97): build the defaults table, fit the cure and
    severity models, recalibrate the cure intercept on recent workouts and write the
    coefficients, validation tables and fitted models to models/lgd/. Returns the fitted
    models and a summary."""
    out_dir = root / "models/lgd"
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = root / "reports/summary"
    d = ld.build_defaults(root / "data/processed", cfg)
    d = ld.add_loss(d, cfg["ead"]["accrued_interest_at_default_months"])
    d = ld.add_collateral(d, log_state)
    logger.info(f"Defaults: {len(d):,} ({d.outcome.value_counts().to_dict()})")
    fd = pd.to_datetime(d.fd)
    dev_end = pd.Timestamp(cfg["split"]["development_defaults_to"])
    d["sample"] = np.where(fd <= dev_end, "development", "oot")
    d["default_year"] = fd.dt.year

    rows = ld.observation_rows(d, cfg["cure_model"]["months_in_default"], log_state)
    rows["sample"] = np.where(pd.to_datetime(rows.fd) <= dev_end, "development", "oot")
    cm, sm_ = cfg["cure_model"], cfg["severity_model"]
    cure = CureModel(
        {"ltv": cm["ltv_knots"], "score": cm["score_knots"], "age": cm["age_knots"]},
        cm["months_in_default"],
    )
    dev_rows = rows[rows["sample"] == "development"]
    cure.fit(cure_frame(dev_rows), dev_rows.y.values, pd.factorize(dev_rows.loan_id)[0])
    liq = d[d.loss_complete & (d["sample"] == "development")]
    sev = SeverityModel(
        {"ltv": sm_["ltv_knots"], "size": sm_["size_knots"]}, sm_["property_groups"]
    ).fit(severity_frame(liq), liq.severity.values)
    # lgd-0.2.0 (owner decision option 2): recalibrate the cure intercept on fully resolved
    # defaults of the window at m = 0; the development fit (option 1) is kept as a sensitivity
    cure_opt1 = copy.deepcopy(cure)
    w0, w1 = cm["recalibration"]["window"]
    r0w = rows[(rows.m == 0) & pd.to_datetime(rows.fd).dt.year.between(w0, w1)]
    shift = cure.recalibrate(cure_frame(r0w), r0w.y.values)
    logger.info(f"Cure intercept shift {shift:+.3f} on {len(r0w):,} resolved defaults {w0}-{w1}")
    save(cure, out_dir / "cure_model.pkl")
    save(cure_opt1, out_dir / "cure_model_option1.pkl")
    save(sev, out_dir / "severity_model.pkl")
    pd.concat(
        [cure.coef_table().assign(model="cure"), sev.coef_table().assign(model="severity")]
    ).to_csv(out_dir / "coefficients.csv", index=False)

    # ---- validation at default (m = 0) ----
    res = d[d.outcome.isin(["cure", "liquidation"])].copy()
    res["y"] = res.outcome.eq("liquidation").astype(int)
    r0 = rows[rows.m == 0].set_index("loan_id")
    cf0 = cure_frame(r0.loc[res.loan_id].reset_index())
    res["p_no_cure"] = cure.p_no_cure(cf0)
    res["p_no_cure_opt1"] = cure_opt1.p_no_cure(cf0)
    res["pred_severity"] = sev.predict(severity_frame(res))
    res["period"] = _period(res.default_year, cfg["split"]["periods"])
    res["ltv_band"] = _band(res.ltv_d, cfg["ltv_bands"], cfg["ltv_labels"])
    res["vintage_band"] = pd.cut(
        res.vintage,
        [0, 2004, 2008, 2012, 2016, 2030],
        labels=["<=04", "05-08", "09-12", "13-16", "17+"],
    ).astype(str)

    def tables(x: pd.DataFrame, model: str) -> pd.DataFrame:
        return pd.concat(
            [validation_table(x, b) for b in ["sample", "period", "vintage_band", "ltv_band"]]
            + [
                validation_table(x[x["sample"] == "oot"], "default_year").assign(
                    breakdown="oot default_year"
                )
            ],
            ignore_index=True,
        ).assign(model=model)

    val = pd.concat(
        [
            tables(res, "lgd-0.2.0 recalibrated"),
            tables(res.assign(p_no_cure=res.p_no_cure_opt1), "option 1 development fit"),
        ],
        ignore_index=True,
    )
    val.to_csv(rep / "lgd_validation.csv", index=False)
    # months in default (Stage 3 conditional)
    rows["p"] = cure.p_no_cure(cure_frame(rows))
    by_m = (
        rows.groupby(["sample", "m"])
        .agg(rows_=("y", "size"), actual_no_cure=("y", "mean"), pred_no_cure=("p", "mean"))
        .reset_index()
    )
    by_m.to_csv(rep / "lgd_cure_by_months_in_default.csv", index=False)

    gini, spear = {}, {}
    for s in ["development", "oot"]:
        x = res[res["sample"] == s]
        gini[s] = float(2 * roc_auc_score(x.y, x.p_no_cure) - 1)
        lq = x[x.loss_complete]
        spear[s] = float(spearmanr(lq.severity, lq.pred_severity).statistic)
    per = val[(val.breakdown == "period") & (val.group == "crisis 2007-11")].set_index("model")
    crisis = per.loc["lgd-0.2.0 recalibrated"]
    reo = d[d.zb_code.isin(cfg["collateral"]["haircut_codes"]) & d.loss_complete]
    ratio = (-reo.nsp) / reo.value_zb
    ratio = ratio[np.isfinite(ratio) & (ratio > 0)]
    haircut = float(1 - ratio.median())
    hc_period = (
        reo.assign(
            r=(-reo.nsp) / reo.value_zb, p=_period(reo.default_year, cfg["split"]["periods"])
        )
        .groupby("p")
        .r.median()
        .rsub(1)
        .to_dict()
    )
    summary = {
        "version": cfg["version"],
        "defaults": len(d),
        "outcomes": d.outcome.value_counts().to_dict(),
        "liquidations_complete": int(d.loss_complete.sum()),
        "liquidations_incomplete": int((d.outcome.eq("liquidation") & ~d.loss_complete).sum()),
        "cure_gini": gini,
        "severity_spearman": spear,
        "cure_intercept_shift": shift,
        "recalibration_defaults": len(r0w),
        "recalibration_actual_no_cure": float(r0w.y.mean()),
        "crisis_actual_to_pred_lgd": float(crisis.actual_to_pred_lgd),
        "crisis_actual_to_pred_lgd_option1": float(
            per.loc["option 1 development fit"].actual_to_pred_lgd
        ),
        "crisis_gap_trigger": cfg["crisis_gap_trigger"],
        "crisis_gap": bool(crisis.actual_to_pred_lgd > cfg["crisis_gap_trigger"]),
        "realisation_haircut": haircut,
        "realisation_haircut_by_period": hc_period,
        "reo_sales_used": len(ratio),
        "dev_rows": len(dev_rows),
        "dev_liquidations": len(liq),
    }
    (out_dir / "fit_summary.json").write_text(json.dumps(summary, indent=2, default=float))
    return {
        "cure": cure,
        "cure_opt1": cure_opt1,
        "sev": sev,
        "summary": summary,
        "validation": val,
        "by_m": by_m,
    }


# ------------------------------------------------------------------ application


def stage3_snapshot(processed: Path, as_at: str) -> pd.DataFrame:
    """Loans in RBI default at month `as_at` (not terminated): months in the current default
    spell, status, prior 30+ episode and loan attributes."""
    con = duckdb.connect()
    for kind in ["loans", "panel"]:
        glob = (processed / kind).as_posix() + "/*/*.parquet"
        con.execute(
            f"CREATE VIEW {kind}_all AS SELECT * FROM read_parquet('{glob}', hive_partitioning=true)"
        )
    df = con.execute(f"""
        WITH cur AS (
            SELECT loan_id, current_upb, months_dlq, dlq_raw, loan_age, relief_flag, current_rate
            FROM panel_all WHERE period = DATE '{as_at}' AND default_event AND zb_code IS NULL),
        h AS (
            SELECT p.loan_id,
                MAX(CASE WHEN NOT p.default_event THEN p.period END) AS last_ok,
                MAX(CASE WHEN p.months_dlq = 0 THEN p.period END)   AS last_current,
                ARG_MAX(p.current_upb, p.period) FILTER (WHERE p.current_upb > 0)
                                                                     AS upb_last_pos
            FROM panel_all p JOIN cur USING (loan_id)
            WHERE p.period <= DATE '{as_at}' GROUP BY 1),
        pr AS (
            SELECT p.loan_id, BOOL_OR(p.months_dlq >= 1 AND p.period < h.last_current) AS prior
            FROM panel_all p JOIN h USING (loan_id) GROUP BY 1)
        SELECT c.*, h.last_ok, h.upb_last_pos, COALESCE(pr.prior, FALSE) AS prior_dlq,
            l.credit_score, l.orig_ltv, l.orig_upb, l.mi_pct, l.property_type, l.property_state,
            l.orig_interest_rate AS note_rate, l.vintage,
            (l.first_payment_date - INTERVAL 1 MONTH)::DATE AS orig_month
        FROM cur c JOIN h USING (loan_id) LEFT JOIN pr USING (loan_id)
        JOIN loans_all l USING (loan_id)
        ORDER BY c.loan_id
    """).df()
    con.close()
    at = pd.Timestamp(as_at)
    last_ok = pd.to_datetime(df.last_ok)
    start = (last_ok + pd.DateOffset(months=1)).fillna(at)
    df["months_in_default"] = (at.year - start.dt.year) * 12 + at.month - start.dt.month
    df["reo"] = df.dlq_raw.eq("RA")
    df["upb"] = np.where(df.current_upb > 0, df.current_upb, df.upb_last_pos)
    return df


def _loan_attrs(processed: Path, ids: pd.Series) -> pd.DataFrame:
    con = duckdb.connect()
    glob = (processed / "loans").as_posix() + "/*/*.parquet"
    con.register("ids", pd.DataFrame({"loan_id": ids.values}))
    a = con.execute(f"""SELECT l.loan_id, l.mi_pct, l.orig_upb
        FROM read_parquet('{glob}', hive_partitioning=true) l JOIN ids USING (loan_id)
        ORDER BY l.loan_id""").df()
    con.close()
    return a


def apply_lgd(
    date: str,
    cfg: dict,
    scen_cfg: dict,
    co3_cfg: dict,
    co5_cfg: dict,
    inp: Inputs,
    fitted: dict,
    root: Path,
    git: dict,
) -> dict:
    """LGD / EAD for the reporting date `date` (performing and Stage 3 loans), per scenario."""
    processed = root / "data/processed"
    rq = pd.Period(pd.Timestamp(date), freq="Q")
    tag = pd.Timestamp(date).strftime("%Y-%m")
    snap = f"{rq.year}-{rq.end_time.month:02d}-01"
    cure, sev = fitted["cure"], fitted["sev"]
    haircut = fitted["summary"]["realisation_haircut"]
    ecfg = cfg["ead"]
    rbi_fb = inp.rbi["lgd"]["fallback"]

    run, frames = build_scenarios(date, scen_cfg, inp.macro, inp.pit, git, root, write=False)
    weights = {k: run["scenarios"][k]["weight"] for k in SCEN}
    params = inp.pit["satellite"]["params"]
    paths = {
        k: to_macro_path(k, frames[k], params, inp.z_meas, rq, inp.log_state, inp.betas)
        for k in SCEN
    }
    pf = build_scoring_snapshot(processed, snap, root / scen_cfg["state_paths"]["file"])
    pf = pf.merge(_loan_attrs(processed, pf.loan_id), on="loan_id", how="left")
    pcomp = components(inp.sc, pf)
    pf["prior_dlq"] = pcomp["dlq_state"] > 0
    years = int(np.ceil(pf.rm.max() / 12))
    pdcfg = {
        "rho": inp.pit["rho"],
        "floor12": float(inp.rbi["pd"]["floor_12_month"]["value"]),
        "floor_annual": float(inp.rbi["pd"]["floor_lifetime_annual"]["value"]),
        "tau": float(inp.life_meta["carry_tau"]),
    }
    z_lr = float(inp.pit["long_run_z"])
    m = co3_cfg["calibration"]["m"]
    sand = pf.property_state.isin(["CA", "FL", "NV", "AZ"]).values
    m_loan = np.where(sand, m["CA/FL/NV/AZ"], m["other"]) if "other" in m else m["all"]
    s = severity_scale(
        z_lr,
        z_trough(paths["downside"], rq, scen_cfg["horizon_quarters"]),
        co3_cfg["calibration"]["z_min_replay"],
    )
    idx = np.arange(len(pf))
    per = {"loan_id": pf.loan_id.values}
    for k in SCEN:
        variants = {"model": None}
        if k == "downside":
            fn = co3_variant(paths[k], rq, m_loan, s)
            variants = {"co3": lambda ii, n_q, fn=fn: fn(ii, n_q, z_lr)}
        r = lifetime_pd(
            inp.model,
            pf,
            pcomp,
            idx,
            paths[k],
            z_first(paths[k], rq),
            rq,
            pdcfg["rho"],
            pdcfg["floor12"],
            pdcfg["floor_annual"],
            pdcfg["tau"],
            variants,
        )
        r = next(iter(r.values()))
        y = lgd_by_year(pf, cure, sev, paths[k], rq, min(years, r["cum_year"].shape[1]), ecfg)
        if k == "downside":  # CO-5: downturn LGD multiplier in stressed default years
            ny = y["lgd"].shape[1]
            q_def = qidx(rq) + np.floor((np.arange(ny) + ecfg["default_point_in_year"]) * 4)
            mask = stressed(paths[k], q_def.astype(int), z_lr)
            f = downturn_factor(mask, co5_cfg["ratio"], s)
            per["lgd12_downside_no_co5"] = y["lgd"][:, 0]
            per["lgd_life_downside_no_co5"] = pd_weighted(r["cum_year"], y["lgd"])
            y["lgd"] = np.minimum(y["lgd"] * f[None, :], 1.0)
            co5_info = {
                "factor_stressed_years": float(1 + (co5_cfg["ratio"] - 1) * s),
                "stressed_years": int(mask.sum()),
            }
        # option 1 (development fit) sensitivity: same severity, unshifted cure model
        y1 = lgd_by_year(pf, fitted["cure_opt1"], sev, paths[k], rq, y["lgd"].shape[1], ecfg)
        if k == "downside":
            y1["lgd"] = np.minimum(
                y1["lgd"] * downturn_factor(mask, co5_cfg["ratio_option1"], s)[None, :], 1.0
            )
        per[f"lgd12_{k}_opt1"] = y1["lgd"][:, 0]
        per[f"lgd_life_{k}_opt1"] = pd_weighted(r["cum_year"], y1["lgd"])
        per[f"lgd12_{k}"] = y["lgd"][:, 0]
        per[f"lgd_life_{k}"] = pd_weighted(r["cum_year"], y["lgd"])
        per[f"ead_life_{k}"] = pd_weighted(r["cum_year"], y["ead"])
        per[f"pd12_{k}"] = r["pd12"]
        per[f"pd_life_{k}"] = r["lifetime"]
        per[f"p_no_cure12_{k}"] = y["p_no_cure"][:, 0]
        per[f"severity12_{k}"] = y["severity"][:, 0]
        per[f"ltv_default12_{k}"] = y["ltv"][:, 0]
        logger.info(
            f"  {k}: LGD 12m {per[f'lgd12_{k}'].mean():.4f}, lifetime {per[f'lgd_life_{k}'].mean():.4f}"
        )
    df = pd.DataFrame(per)
    # probability-weighted (weights apply to expected loss: PD-weighted LGD across scenarios)
    for h, pdk in [("lgd12", "pd12"), ("lgd_life", "pd_life")]:
        wd = sum(weights[k] * df[f"{pdk}_{k}"] for k in SCEN)
        for sfx in ["", "_opt1"]:
            wn = sum(weights[k] * df[f"{pdk}_{k}"] * df[f"{h}_{k}{sfx}"] for k in SCEN)
            df[f"{h}_weighted{sfx}"] = np.where(wd > 0, wn / wd, df[f"{h}_central{sfx}"])
    # accrued interest on missed instalments: 30-59 dpd = 1, 60-89 dpd = 2 (dlq_state 4, 5)
    months_dlq = np.select([pcomp["dlq_state"] == 4, pcomp["dlq_state"] == 5], [1, 2], 0)
    df["ead_now"] = ead_now(pf.current_upb, pf.rate, months_dlq)
    with np.errstate(divide="ignore", invalid="ignore"):
        value_now = np.where(pf.current_ltv > 0, pf.current_upb / (pf.current_ltv / 100), np.nan)
    df["secured"], df["unsecured"] = secured_portion(df.ead_now, value_now, haircut)
    df["current_ltv"] = pf.current_ltv.values
    df["ltv_band"] = _band(pf.current_ltv, cfg["ltv_bands"], cfg["ltv_labels"])
    df["vintage"] = pf.vintage.values
    df["stage_hint"] = np.where(pcomp["dlq_state"] >= 4, "30+ dpd", "current")
    # fallback comparison: RBI 65% on the secured portion, 70% on the unsecured
    df["lgd_fallback"] = np.where(
        df.ead_now > 0,
        (rbi_fb["secured"] * df.secured + rbi_fb["unsecured"] * df.unsecured) / df.ead_now,
        rbi_fb["secured"],
    )

    # ---- Stage 3 (loans in default at the date) ----
    s3 = stage3_snapshot(processed, snap)
    orig_value = s3.orig_upb / (s3.orig_ltv / 100)
    ratio = ld.hpi_ratio(
        inp.log_state,
        s3.property_state,
        ld._q(s3.orig_month),
        ld._q([pd.Timestamp(snap)] * len(s3)),
    )
    s3["value_now"] = orig_value * ratio
    s3["ltv"] = 100 * s3.upb / s3.value_now
    s3["age"] = s3.loan_age
    s3["relief"] = s3.relief_flag.fillna(False)
    acc = np.where(s3.reo, s3.months_in_default + 3, s3.months_dlq.fillna(3))
    s3["ead_now"] = ead_now(s3.upb, s3.note_rate, acc)
    s3 = pd.concat([s3.reset_index(drop=True), stage3_lgd(s3, cure, sev)], axis=1)
    s3["lgd_opt1"] = stage3_lgd(s3, fitted["cure_opt1"], sev).lgd.values
    s3["secured"], s3["unsecured"] = secured_portion(s3.ead_now, s3.value_now, haircut)

    out = root / "data/processed/lgd"
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / f"performing_{tag}.parquet", index=False)
    s3.to_parquet(out / f"stage3_{tag}.parquet", index=False)

    rows = []
    for seg, groups in [
        ("all", [("all", df)]),
        ("ltv_band", list(df.groupby("ltv_band"))),
        ("dpd", list(df.groupby("stage_hint"))),
    ]:
        for val, g in groups:
            wl = g.pd_life_central * g.ead_now
            r_ = {
                "as_on": date,
                "population": "performing",
                "segment": seg,
                "value": val,
                "loans": len(g),
                "ead": g.ead_now.sum(),
                "secured_share": g.secured.sum() / g.ead_now.sum(),
            }
            for k in [*SCEN, "downside_no_co5", "weighted", "weighted_opt1"]:
                r_[f"lgd12_{k}"] = g[f"lgd12_{k}"].mean()
                r_[f"lgd_life_{k}"] = g[f"lgd_life_{k}"].mean()
            r_["lgd_change_vs_option1"] = (
                g.lgd_life_weighted.mean() / g.lgd_life_weighted_opt1.mean() - 1
            )
            r_["lgd_life_weighted_pd_ead_weighted"] = (wl * g.lgd_life_weighted).sum() / wl.sum()
            r_["lgd_fallback_pd_ead_weighted"] = (wl * g.lgd_fallback).sum() / wl.sum()
            r_["model_to_fallback"] = (
                r_["lgd_life_weighted_pd_ead_weighted"] / r_["lgd_fallback_pd_ead_weighted"]
            )
            rows.append(r_)
    s3["m_band"] = pd.cut(
        s3.months_in_default,
        [-1, 2, 5, 11, 23, 35, 1e9],
        labels=["0-2", "3-5", "6-11", "12-23", "24-35", "36+"],
    ).astype(str)
    for val, g in [("all", s3), *list(s3.groupby("m_band"))]:
        rows.append(
            {
                "as_on": date,
                "population": "stage 3 (in default)",
                "segment": "all" if val == "all" else "months_in_default",
                "value": val,
                "loans": len(g),
                "ead": g.ead_now.sum(),
                "secured_share": g.secured.sum() / g.ead_now.sum(),
                "lgd_stage3": (g.lgd * g.ead_now).sum() / g.ead_now.sum(),
                "lgd_stage3_opt1": (g.lgd_opt1 * g.ead_now).sum() / g.ead_now.sum(),
                "p_no_cure_stage3": g.p_no_cure.mean(),
                "severity_stage3": g.severity.mean(),
                "lgd_fallback_pd_ead_weighted": rbi_fb["secured"],
                "model_to_fallback": (g.lgd * g.ead_now).sum()
                / g.ead_now.sum()
                / rbi_fb["secured"],
            }
        )
    t = pd.DataFrame(rows)
    t.to_csv(root / "reports/summary" / f"lgd_ead_{tag}.csv", index=False)
    res = {
        "date": date,
        "performing": len(df),
        "stage3": len(s3),
        "haircut": haircut,
        "co3_s": s,
        "co5": co5_info,
        "all": t[(t.population == "performing") & (t.segment == "all")].iloc[0].to_dict(),
        "stage3_all": t[(t.population != "performing") & (t.segment == "all")].iloc[0].to_dict(),
    }
    (root / "models/lgd" / f"apply_{tag}.json").write_text(json.dumps(res, indent=2, default=float))
    return res
