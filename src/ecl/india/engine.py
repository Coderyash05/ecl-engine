"""ECL on the SYNTHETIC Indian book with the engine's rules (Module 12). Not Indian risk estimates.

Per loan and Indian scenario s (downside / central / upside):
- PD: the US model's rank order and macro sensitivity are kept. For each loan the US engine gives
  12-month and lifetime PDs under the three US scenarios; logit PD is taken as linear in the
  scenario's Z (slope from the US downside vs upside), evaluated at the Indian scenario Z (12m:
  year-1 mean Z; lifetime: 12-quarter mean). The PD is then multiplied by the GNPA calibration k,
  the employment multiplier (normalised to a book average of 1) and the payment-shock multiplier
  1 + beta x (EMI increase under the scenario's repo path). 12-month PD >= 0.03% (para 96).
  The lifetime PD therefore comes from the US hazard model, not from the 12-month PD (para 45).
- Term structure: year-1 marginal PD = 12-month PD; the remaining lifetime PD is spread over the
  remaining Indian tenure with a constant conditional hazard and the assumed prepayment rate.
- EAD by year: scheduled balance under the scenario rate with the extended tenure (para 100).
- LGD by year: P(no cure) x severity; severity = 1 - realisable value (HPI-indexed along the
  scenario path, less the haircut, discounted over the recovery time) / EAD, at least the
  minimum loss rate. Stage 3 (in default): LGD in default with the Stage 3 P(no cure).
- Discounting at the current contractual rate (para 51 transitional EIR proxy).
- ECL: 12-month (Stage 1), lifetime (Stage 2, Stage 3 not 90+), LGD x EAD (Stage 3 in default);
  scenario ECLs probability-weighted (paras 47-48); staging and floors with the US engine code
  (ecl.staging.rules.stage_loans, ecl.provisioning.run.provisions; housing (xi)(a) floors).
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

from ecl.india.portfolio import payment_shock, scheduled_balance
from ecl.provisioning.ecl import discount_factors, ecl_12m, ecl_lifetime, weighted
from ecl.provisioning.run import provisions
from ecl.staging.rules import stage_loans

SCEN = ("downside", "central", "upside")
PD_CAP = 0.999  # upper bound on a stressed / scaled PD (keeps logits finite)


def _logit(p: ArrayLike) -> np.ndarray:
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _expit(x: ArrayLike) -> np.ndarray:
    return 1 / (1 + np.exp(-x))


def z_shifted(
    us_central: ArrayLike, us_down: ArrayLike, us_up: ArrayLike, z_us: dict, z_in: float
) -> np.ndarray:
    """US per-loan PD moved to the Indian scenario Z: logit linear in Z through the US
    downside / upside points, anchored at the US central scenario."""
    slope = (_logit(us_up) - _logit(us_down)) / (z_us["upside"] - z_us["downside"])
    return _expit(_logit(us_central) + slope * (z_in - z_us["central"]))


def spread_hazard(pd12: np.ndarray, life: np.ndarray, years: np.ndarray, cpr: float) -> np.ndarray:
    """Cumulative default by year (n, Ymax): year 1 = pd12; years 2..Y share the remaining
    lifetime PD with a constant conditional hazard h and prepayment cpr (bisection on h)."""
    n, ymax = len(pd12), int(np.nanmax(years))
    rest = np.clip(life - pd12, 0, None)
    s1 = (1 - pd12) * (1 - cpr)
    m = np.clip(years - 1, 0, None)

    def total(h: np.ndarray) -> np.ndarray:
        a = (1 - h) * (1 - cpr)
        return h * s1 * np.where(np.abs(1 - a) > 1e-12, (1 - a**m) / (1 - a), m)

    lo, hi = np.zeros(n), np.ones(n)
    for _ in range(50):
        mid = (lo + hi) / 2
        up = total(mid) < rest
        lo, hi = np.where(up, mid, lo), np.where(up, hi, mid)
    h = (lo + hi) / 2
    marg = np.zeros((n, ymax))
    marg[:, 0] = pd12
    surv = s1.copy()
    for y in range(1, ymax):
        active = y < years
        marg[:, y] = np.where(active, surv * h, 0.0)
        surv = surv * (1 - h) * (1 - cpr)
    return np.cumsum(marg, axis=1)


def measure(
    book: pd.DataFrame, scen: dict, cfg: dict, ecl_cfg: dict, rbi: dict, z_us: dict, p: dict
) -> tuple:
    """ECL, staging and provision for the synthetic book under parameters p (base values from
    config/india.yaml, overridden for sensitivities). Returns (loan-level frame, provisions)."""
    b = book.copy()
    pc, lg = cfg["portfolio"], cfg["lgd"]
    paths = scen["paths"]
    w = {s: float(paths[paths.scenario == s].weight.iloc[0]) for s in SCEN}
    h = cfg["scenarios"]["horizon_quarters"]
    floor12 = float(rbi["pd"]["floor_12_month"]["value"])
    se = b.self_employed.to_numpy(bool)
    m_se = p["pd_multiplier_self_employed"]
    share = pc["employment"]["self_employed_share"]
    m_emp = np.where(se, m_se, 1.0) / (share * m_se + (1 - share))
    k = p["k"]
    # values for all scenarios
    ymax = int(min(np.ceil(b.extension_cap_months.max() / 12), 40))
    df_ = discount_factors(b.rate_now, ymax)
    v_now = b.property_value_now_lakh.to_numpy() / 100  # Rs crore
    haircut = p["realisation_haircut"]
    out = {}
    for s in SCEN:
        ps = paths[paths.scenario == s]
        z1, z12 = float(ps.z.iloc[:4].mean()), float(ps.z.iloc[:h].mean())
        r_s = float(ps.repo.iloc[:4].mean()) + pc["rate"]["spread_pp"] + p.get("repo_shift", 0.0)
        rem, shock = payment_shock(b.balance_lakh, r_s, b.emi_orig_lakh, b.extension_cap_months)
        mult = k * p.get("pd_level", 1.0) * m_emp * (1 + p["pd_beta"] * shock)
        pd12 = z_shifted(b.pd12_central, b.pd12_downside, b.pd12_upside, z_us["z1"], z1)
        life = z_shifted(b.pd_life_central, b.pd_life_downside, b.pd_life_upside, z_us["z12"], z12)
        pd12 = np.clip(pd12 * mult, floor12, PD_CAP)
        life = np.clip(np.maximum(life * mult, pd12), 0, PD_CAP)
        years = np.clip(np.ceil(rem / 12), 1, ymax)
        cum = spread_hazard(pd12, life, years, p["prepayment_cpr"])
        # EAD by year (Rs crore) under the scenario rate and extended tenure
        ead = np.column_stack(
            [scheduled_balance(b.balance_lakh / 100, r_s, rem, 12 * y) for y in range(ymax)]
        )
        g = np.r_[ps.hpi_g.values, np.full(max(0, 4 * ymax - len(ps)), ps.hpi_g.values[-1])]
        hpi_fac = np.exp(np.cumsum(g[: 4 * ymax]) / 100)[3::4]  # end of each year
        hpi_fac = np.r_[1.0, hpi_fac[:-1]]  # value at the start of year y
        v = v_now[:, None] * hpi_fac[None, :]
        df_rec = (1 + r_s / 1200) ** (-12 * lg["years_to_recovery"])
        with np.errstate(divide="ignore", invalid="ignore"):
            sev = 1 - (1 - haircut) * v * df_rec / ead
        sev = np.where(ead > 0, np.clip(sev, lg["min_loss_rate"], 1), 0.0)
        if p.get("fallback_lgd"):
            fb = rbi["lgd"]["fallback"]
            sec = np.minimum((1 - haircut) * v, ead)
            with np.errstate(divide="ignore", invalid="ignore"):
                lgd = np.where(
                    ead > 0, (fb["secured"] * sec + fb["unsecured"] * (ead - sec)) / ead, 0
                )
        else:
            lgd = p["p_no_cure"] * sev
        out[s] = {
            "pd12": pd12,
            "life": life,
            "ecl12": ecl_12m(pd12, lgd, ead, df_),
            "ecl_life": ecl_lifetime(cum, lgd, ead, df_),
            "lgd12": lgd[:, 0],
            "shock": shock,
            "rem": rem,
        }
    b["pd12_weighted"] = weighted({s: out[s]["pd12"] for s in SCEN}, w)
    b["pd_life_now"] = weighted({s: out[s]["life"] for s in SCEN}, w)
    b["ecl12_weighted"] = weighted({s: out[s]["ecl12"] for s in SCEN}, w)
    b["ecl_life_weighted"] = weighted({s: out[s]["ecl_life"] for s in SCEN}, w)
    b["lgd12_weighted"] = weighted({s: out[s]["lgd12"] for s in SCEN}, w)
    b["payment_shock_central"] = out["central"]["shock"]
    b["remaining_months_central"] = out["central"]["rem"]
    for s in SCEN:
        b[f"ecl12_{s}"], b[f"ecl_life_{s}"] = out[s]["ecl12"], out[s]["ecl_life"]
    b["pd12_ttc"] = np.clip(b.pd12_ttc * k * p.get("pd_level", 1.0) * m_emp, floor12, PD_CAP)
    b["pd_life_orig"] = b.pd_life_orig * k * p.get("pd_level", 1.0) * m_emp  # level, not a change
    # collateral split now (ACPIR 6(24)): realisable value after the haircut
    ead_now = b.ead_now.to_numpy()
    b["secured"] = np.minimum((1 - haircut) * v_now, ead_now)
    b["unsecured"] = ead_now - b.secured
    # Stage 3 in default: LGD in default
    with np.errstate(divide="ignore", invalid="ignore"):
        sev0 = np.where(ead_now > 0, 1 - (1 - haircut) * v_now / ead_now, 0)
    sev0 = np.clip(sev0, lg["min_loss_rate"], 1)
    if p.get("fallback_lgd"):
        fb = rbi["lgd"]["fallback"]
        b["lgd3"] = np.where(
            ead_now > 0, (fb["secured"] * b.secured + fb["unsecured"] * b.unsecured) / ead_now, 0
        )
    else:
        b["lgd3"] = p["stage3_p_no_cure"] * sev0
    b["ecl3"] = np.where(b.in_default, b.lgd3 * ead_now, np.nan)
    # staging with the engine's rules (no restructuring in the synthetic book)
    b["modified"] = False
    b["restr_state"] = np.nan
    b["category"] = "xi_a"
    st = stage_loans(b, ecl_cfg)
    b[["stage", "stage_rule", "rules_fired"]] = st[["stage", "stage_rule", "rules_fired"]].values
    b["stage"] = b.stage.astype(int)
    ctx = SimpleNamespace(floor_sets={"xi_a": rbi["floors"]["housing_loan_to_individuals"]})
    prov, b["allowance"], b["ecl_stage_model"] = provisions(b, ctx, per_loan=True)
    return b, prov
