"""Scenario-weighted 12-month and lifetime PD for a reporting date (docs/methodology/scenarios.md).

What (RBI paras 45-49, 96, 124, 131):
- each scenario's frame (run.build_scenarios) becomes a hazard MacroPath (build.to_macro_path):
  satellite Z on the scenario's HPI / GDP, state house prices by betas, scenario mortgage rate;
- per loan: 12-month PIT PD (Vasicek at the scenario's Z for the 12 months after the date,
  floored at 0.03%, para 96) and lifetime PD (lifetime.portfolio.lifetime_pd: year 1 = PIT PD,
  later years from the hazard with the calibrated carry, annual floor);
- the downside is computed with and without CO-3 (overlay.py), on the same projection;
- probability-weighted PD = sum of weight x scenario PD (downside with CO-3); the base path is the
  mean forecast, so weighted / base = the non-linearity uplift (Jensen's inequality).
In Module 7 the weights apply to ECL (PD x LGD x EAD per scenario); the weighted PDs here are for
reporting and for the SICR current side (para 26).

US data; not Indian risk estimates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ecl.lifetime.cells import SAND_STATES
from ecl.lifetime.paths import MacroPath, qidx
from ecl.lifetime.portfolio import lifetime_pd
from ecl.pd.features import DLQ_STATE_LABELS
from ecl.scenarios.overlay import multiplier, severity_scale, stressed

if TYPE_CHECKING:
    from collections.abc import Callable

    from ecl.lifetime.hazard import HazardModel

SCEN = ["downside", "central", "upside"]


def z_first(path: MacroPath, report_q: pd.Period) -> float:
    """Z of the 12-month window after the reporting date (year-1 PIT PD)."""
    return float(path.at(path.z_s, np.array([qidx(report_q)]))[0])


def z_trough(path: MacroPath, report_q: pd.Period, h: int) -> float:
    """Lowest quarterly Z over the forecast quarters 1..h."""
    q = qidx(report_q) + np.arange(1, h + 1)
    return float(path.at(path.z_q, q).min())


def co3_variant(
    path: MacroPath, report_q: pd.Period, m: float | np.ndarray, s: float
) -> Callable[[np.ndarray, int, float], np.ndarray]:
    """Multiplier function for lifetime_pd: M^s in the path's stressed quarters. `m` scalar or
    per loan of the whole portfolio (indexed by the positions passed in)."""
    rq = qidx(report_q)

    def fn(ii: np.ndarray, n_q: int, z_lr: float) -> np.ndarray:
        mask = np.broadcast_to(stressed(path, rq + np.arange(1, n_q + 1), z_lr), (len(ii), n_q))
        mm = m if np.ndim(m) == 0 else np.asarray(m)[ii]
        return multiplier(mask, mm, s)

    return fn


def segments(pf: pd.DataFrame, pcomp: dict, ltv_bands: list, ltv_labels: list) -> pd.DataFrame:
    """Reporting segments per loan: delinquency state, LTV band, region, vintage band."""
    vb = np.where(
        pf.vintage >= 2024,
        "2024-26",
        np.where(pf.vintage >= 2017, "2017-23", np.where(pf.vintage >= 2009, "2009-16", "<=2008")),
    )
    return pd.DataFrame(
        {
            "dlq_state": np.array(DLQ_STATE_LABELS)[pcomp["dlq_state"]],
            "ltv_band": pd.cut(pf.current_ltv, ltv_bands, labels=ltv_labels)
            .astype(str)
            .replace("nan", "missing")
            .values,
            "region": np.where(pf.property_state.isin(SAND_STATES), "CA/FL/NV/AZ", "other"),
            "vintage_band": vb,
        }
    )


def scenario_pds(
    model: HazardModel,
    pf: pd.DataFrame,
    pcomp: dict,
    paths: dict[str, MacroPath],
    weights: dict[str, float],
    report_q: pd.Period,
    pdcfg: dict,
    co3: dict,
) -> tuple[pd.DataFrame, dict]:
    """Per-loan PDs (12m and lifetime) per scenario and weighted, plus CO-3 details.
    pdcfg: rho, floor12, floor_annual, tau, z_lr, horizon. co3: m (scalar or per loan),
    z_min_replay."""
    idx = np.arange(len(pf))
    z_lr, h = pdcfg["z_lr"], pdcfg["horizon"]
    z_trough_down = z_trough(paths["downside"], report_q, h)
    s = severity_scale(z_lr, z_trough_down, co3["z_min_replay"])
    out = {"loan_id": pf.loan_id.values}
    info = {
        "z_lr": z_lr,
        "z_min_replay": co3["z_min_replay"],
        "z_min_downside": z_trough_down,
        "s": s,
    }
    for name, path in paths.items():
        variants = {"model": None}
        if name == "downside":
            fn = co3_variant(path, report_q, co3["m"], s)
            variants["co3"] = lambda ii, n_q, fn=fn: fn(ii, n_q, z_lr)
        res = lifetime_pd(
            model,
            pf,
            pcomp,
            idx,
            path,
            z_first(path, report_q),
            report_q,
            pdcfg["rho"],
            pdcfg["floor12"],
            pdcfg["floor_annual"],
            pdcfg["tau"],
            variants,
        )
        for v, r in res.items():
            tag = name if v == "model" else f"{name}_co3"
            out[f"pd12_{tag}"] = r["pd12"]
            out[f"lifetime_{tag}"] = r["lifetime"]
        info[f"z_first_{name}"] = z_first(path, report_q)
    df = pd.DataFrame(out)
    for kind in ["pd12", "lifetime"]:
        df[f"{kind}_weighted"] = sum(
            weights[k] * df[f"{kind}_{'downside_co3' if k == 'downside' else k}"] for k in SCEN
        )
        df[f"{kind}_weighted_no_co3"] = sum(weights[k] * df[f"{kind}_{k}"] for k in SCEN)
    return df, info


def segment_table(df: pd.DataFrame, seg: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Mean PDs by segment (all, then each segment variable), with the non-linearity uplift."""
    x = pd.concat([df[cols], seg], axis=1)
    rows = []
    for var in ["all", *seg.columns]:
        groups = [("all", x)] if var == "all" else list(x.groupby(var))
        for val, g in groups:
            rows.append({"segment": var, "value": val, "loans": len(g), **g[cols].mean().to_dict()})
    t = pd.DataFrame(rows)
    for kind in ["pd12", "lifetime"]:
        if f"{kind}_base" in t:
            t[f"{kind}_uplift_weighted_vs_base"] = t[f"{kind}_weighted"] / t[f"{kind}_base"]
    return t


def backtest_table(
    df: pd.DataFrame, seg: pd.DataFrame, labels: pd.DataFrame, pd_cols: list[str]
) -> pd.DataFrame:
    """Predicted 12-month PD per scenario vs realised 12-month default (B-18 and RBI 90+) by
    segment, for loans with an observed outcome (labels: loan_id, target_b18, target_a)."""
    x = pd.concat([df[["loan_id", *pd_cols]], seg], axis=1).merge(labels, on="loan_id")
    rows = []
    for var in ["all", *seg.columns]:
        groups = [("all", x)] if var == "all" else list(x.groupby(var))
        for val, g in groups:
            r = {
                "segment": var,
                "value": val,
                "loans": len(g),
                "actual_b18": g.target_b18.mean(),
                "actual_a": g.target_a.mean(),
                "defaults_b18": int(g.target_b18.sum()),
            }
            for c in pd_cols:
                r[c] = g[c].mean()
                r[f"actual_b18_to_{c}"] = r["actual_b18"] / r[c]
            rows.append(r)
    return pd.DataFrame(rows)
