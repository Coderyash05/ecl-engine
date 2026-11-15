"""Apply the LGD and EAD models to a reporting-date portfolio on a scenario path.

What (docs/methodology/lgd_ead.md):
- **Performing loans** (Stages 1-2): for each future year y, a default at mid-year is assumed;
  - EAD_y = scheduled balance at the default point + accrued interest (ead.ead_at_default);
  - indexed LTV at default = EAD-balance / (property value now x the scenario's state HPI ratio
    from the reporting quarter to the default quarter) (para 6(24); RBI Annex 1);
  - LGD_y = P(no cure | m = 0, LTV_y, score, prior 30+ episode, age at default, no relief) x
    severity(LTV_y, MI, property type, size). Relief at default is set to 0 (it is unknown in
    advance; relief defaults cure more, so this is conservative).
  - lifetime LGD = sum_y marginal PD_y x LGD_y / sum_y marginal PD_y (PD-weighted; for
    reporting; Module 7 uses LGD_y directly).
- **Loans in default at the reporting date** (Stage 3): P(no cure) at their months in default
  (capped at the last observation point), LTV now; REO-acquired loans cannot cure (P = 1).
- The downside uses the same mechanics: no separate downturn overlay.

US data; not Indian risk estimates.
"""

import numpy as np
import pandas as pd

from ecl.ead.ead import ead_at_default
from ecl.lgd.models import CureModel, SeverityModel
from ecl.lifetime.paths import MacroPath, qidx


def lgd_by_year(
    pf: pd.DataFrame,
    cure: CureModel,
    sev: SeverityModel,
    path: MacroPath,
    report_q: pd.Period,
    years: int,
    ecfg: dict,
) -> dict[str, np.ndarray]:
    """(n, years) arrays: ead, ltv, p_no_cure, severity, lgd for a default in each year.
    pf needs current_upb, rate (note), rm, current_ltv, property_state, credit_score, prior_dlq,
    loan_age, mi_pct, property_type, orig_upb."""
    n = len(pf)
    t = (np.arange(years) + ecfg["default_point_in_year"]) * 12  # months ahead
    acc = ecfg["accrued_interest_at_default_months"]
    ead = ead_at_default(
        pf.current_upb.values[:, None],
        pf.rate.values[:, None],
        pf.rm.values[:, None],
        t[None, :],
        acc,
    )
    bal = ead / (1 + pf.rate.values[:, None] / 1200 * acc)  # balance before accrued interest
    with np.errstate(divide="ignore", invalid="ignore"):
        value_now = np.where(pf.current_ltv > 0, pf.current_upb / (pf.current_ltv / 100), np.nan)
    st = path.state_index(pf.property_state.values)
    rq = qidx(report_q)
    q_def = rq + np.floor(t / 3).astype(int)
    ratio = np.column_stack([path.hpi_ratio(st, np.full(n, rq), np.full(n, q)) for q in q_def])
    ltv = 100 * bal / (value_now[:, None] * ratio)
    alive = t[None, :] < pf.rm.values[:, None]
    out = {k: np.zeros((n, years)) for k in ["p_no_cure", "severity"]}
    for y in range(years):
        cf = pd.DataFrame(
            {
                "ltv": ltv[:, y],
                "credit_score": pf.credit_score.values,
                "prior_dlq": pf.prior_dlq.values,
                "age": pf.loan_age.values + t[y],
                "relief": np.zeros(n),
                "m": np.zeros(n),
            }
        )
        out["p_no_cure"][:, y] = cure.p_no_cure(cf)
        sf = pd.DataFrame(
            {
                "ltv": ltv[:, y],
                "mi_pct": pf.mi_pct.values,
                "property_type": pf.property_type.values,
                "orig_upb": pf.orig_upb.values,
            }
        )
        out["severity"][:, y] = sev.predict(sf)
    out["lgd"] = out["p_no_cure"] * out["severity"]
    out["ead"] = np.where(alive, ead, 0.0)
    out["ltv"] = ltv
    return out


def pd_weighted(cum_default_by_year: np.ndarray, x_by_year: np.ndarray) -> np.ndarray:
    """sum_y marginal PD_y x x_y / sum_y marginal PD_y (x = LGD or EAD), per loan."""
    k = min(cum_default_by_year.shape[1], x_by_year.shape[1])
    c = cum_default_by_year[:, :k].astype(float)
    mpd = np.diff(np.hstack([np.zeros((len(c), 1)), c]), axis=1)
    w = mpd.sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(w > 0, (mpd * x_by_year[:, :k]).sum(axis=1) / w, x_by_year[:, 0])


def stage3_lgd(d: pd.DataFrame, cure: CureModel, sev: SeverityModel) -> pd.DataFrame:
    """LGD of loans in default at the reporting date. d: ltv, credit_score, prior_dlq, age,
    relief, months_in_default, reo, mi_pct, property_type, orig_upb."""
    months = np.array(cure.months)
    m = months[np.searchsorted(months, d.months_in_default.values, side="right") - 1]
    cf = pd.DataFrame(
        {
            "ltv": d.ltv.values,
            "credit_score": d.credit_score.values,
            "prior_dlq": d.prior_dlq.values,
            "age": d.age.values,
            "relief": d.relief.astype(float).values,
            "m": m,
        }
    )
    pnc = np.where(d.reo.values, 1.0, cure.p_no_cure(cf))
    s = sev.predict(d[["ltv", "mi_pct", "property_type", "orig_upb"]])
    return pd.DataFrame({"p_no_cure": pnc, "severity": s, "lgd": pnc * s, "m_used": m})


def downturn_factor(mask: np.ndarray, ratio: float, s: float) -> np.ndarray:
    """CO-5 (para 131): LGD multiplier 1 + (ratio - 1) x s in stressed default years, 1 otherwise
    (ratio = crisis-period actual / predicted LGD; s = the downside's CO-3 severity scale)."""
    return np.where(mask, 1 + (ratio - 1) * s, 1.0)
