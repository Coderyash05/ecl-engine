"""SYNTHETIC Indian housing-loan book at the reporting date, derived loan by loan from the US
(Freddie Mac) book (Module 12). Everything here is labelled synthetic: the borrowers, amounts and
rates are transformations of US loans under documented assumptions (config/india.yaml,
docs/india_adapter.md); they are not Indian risk estimates.

Per US loan (restructured / deferral / calamity-route US loans excluded: no restructuring
history is synthesised):
- CIBIL-style score: the US score's percentile mapped onto assumed CIBIL quantiles (300-900);
  FOIR = DTI; co-borrower = US num_borrowers >= 2;
- ticket size: the US original amount's percentile mapped onto a lognormal in Rs lakh;
- RBI LTV caps by ticket band (<= 30 lakh 90%, 30-75 lakh 80%, > 75 lakh 75%): origination LTV =
  min(US LTV, cap); property value = amount / LTV; indexed with the city RBI HPI;
- city: one of the RBI HPI cities (equal weights); tier 1 = HRA class X cities;
- employment, age at origination: random draws (seeded) with the configured shares;
- rate: repo-linked (EBLR) = repo in force + spread, at origination and now;
- tenure: original = min(configured original years, retirement age - age at origination); the
  balance now follows the Indian schedule at the origination rate times the US curtailment
  factor (US actual / US scheduled balance); loans past their Indian maturity are dropped;
- state at the date (dpd bucket, default, years in Stage 3) is the US loan's; the NPA and
  30-89 dpd stock is thinned (k < 1) or replicated (k > 1) by the calibration multiplier k so
  the book's GNPA matches the target; the PD level is scaled by the same k.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike
from scipy.stats import norm


def annuity(b: ArrayLike, r_annual_pct: ArrayLike, n_months: ArrayLike) -> np.ndarray:
    """Level monthly instalment (EMI) that repays balance `b` over `n_months` at `r_annual_pct` %
    a year (b / n at a zero rate)."""
    r = np.asarray(r_annual_pct, float) / 1200
    n = np.asarray(n_months, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(r > 0, b * r / (1 - (1 + r) ** -n), b / n)


def scheduled_balance(
    b0: ArrayLike, r_annual_pct: ArrayLike, n_months: ArrayLike, k_months: ArrayLike
) -> np.ndarray:
    """Balance after k payments of a level annuity."""
    r = np.asarray(r_annual_pct, float) / 1200
    n, k = np.asarray(n_months, float), np.clip(np.asarray(k_months, float), 0, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        f = np.where(r > 0, ((1 + r) ** n - (1 + r) ** k) / ((1 + r) ** n - 1), 1 - k / n)
    return b0 * np.clip(f, 0, 1)


def months_to_repay(b: ArrayLike, r_annual_pct: ArrayLike, emi: ArrayLike) -> np.ndarray:
    """Months needed to repay balance b at rate r with a fixed EMI (inf if EMI <= interest)."""
    r = np.asarray(r_annual_pct, float) / 1200
    with np.errstate(divide="ignore", invalid="ignore"):
        x = 1 - r * b / emi
        return np.where(x > 0, -np.log(np.where(x > 0, x, 1)) / np.log1p(r), np.inf)


def quantile_map(x: pd.Series, q: dict) -> np.ndarray:
    """Percentile of x within the book -> value by linear interpolation through target quantiles."""
    pct = x.rank(pct=True).to_numpy()
    ks = np.array(sorted(q))
    vs = np.array([q[k] for k in ks])
    return np.where(np.isnan(pct), np.nan, np.interp(pct, ks, vs))


def stock_multiplier(share: float, target: float) -> float:
    """Multiplier m on the delinquent stock so that its exposure share moves from `share` to
    `target`: m s / (1 - s + m s) = t  =>  m = t (1 - s) / (s (1 - t)). The PD level is scaled
    by the same m (steady state: NPA stock proportional to the default intensity)."""
    return target * (1 - share) / (share * (1 - target))


def apply_ltv_caps(amount_lakh: np.ndarray, ltv: np.ndarray, bands: list[dict]) -> np.ndarray:
    """Origination LTV within the cap of its ticket band (a missing LTV is set to the cap)."""
    cap = ltv_cap(np.asarray(amount_lakh, float), bands)
    ltv = np.asarray(ltv, float)
    return np.minimum(np.where(np.isnan(ltv), cap, ltv), cap)


def ltv_cap(amount_lakh: np.ndarray, bands: list[dict]) -> np.ndarray:
    """Maximum LTV (%) for each loan amount (Rs lakh) from the ticket-size bands (Credit
    Facilities Directions 2025, para 111)."""
    out = np.full(len(amount_lakh), np.nan)
    lo = -np.inf
    for b in bands:
        hi = np.inf if b["up_to_lakh"] is None else b["up_to_lakh"]
        m = (amount_lakh > lo) & (amount_lakh <= hi)
        out[m] = b["cap"]
        lo = hi
    return out


def payment_shock(
    balance: ArrayLike, rate_now: ArrayLike, emi_orig: ArrayLike, cap_months: ArrayLike
) -> tuple[np.ndarray, np.ndarray]:
    """Floating-rate mechanics on a rate change: the EMI stays fixed and the tenure extends up to
    the cap; if the cap binds, the EMI rises to repay within the cap. Returns (remaining months,
    EMI increase as a share of the original EMI, >= 0)."""
    need = months_to_repay(balance, rate_now, emi_orig)
    cap = np.maximum(cap_months, 1)
    binds = need > cap
    emi_new = np.where(binds, annuity(balance, rate_now, cap), emi_orig)
    remaining = np.where(binds, cap, np.ceil(need))
    return remaining, np.maximum(emi_new / emi_orig - 1, 0.0)


def build_book(
    us: pd.DataFrame,
    hpi: pd.DataFrame,
    repo_q: pd.Series,
    repo_now: float,
    as_of: str,
    cfg: dict,
    ltv_bands: list[dict],
) -> tuple[pd.DataFrame, dict]:
    """us: US loan-level ECL output joined with loans_all attributes. ltv_bands: RBI LTV caps
    by ticket size (Credit Facilities Directions 2025, para 111). Returns the synthetic book and
    build statistics."""
    pc = cfg["portfolio"]
    rng = np.random.default_rng(cfg["seed"])
    us = us.sort_values("loan_id").reset_index(drop=True)
    excl = (
        (us.modification_events.fillna(0) > 0)
        | (us.deferral_events.fillna(0) > 0)
        | us.restructured.astype(bool)
        | us.restructured_cal.astype(bool)
    )
    stats = {"us_loans": len(us), "excluded_restructured_or_deferred": int(excl.sum())}
    u = us[~excl].copy()
    n = len(u)
    # borrower
    u["cibil"] = np.round(quantile_map(u.credit_score, pc["cibil"]["target_quantiles"]))
    u["foir"] = u.orig_dti
    u["co_borrower"] = u.num_borrowers.fillna(1) >= 2
    emp = pc["employment"]
    u["self_employed"] = rng.random(n) < emp["self_employed_share"]
    lo, hi = pc["tenure"]["age_at_origination"]
    u["age_at_origination"] = rng.uniform(lo, hi, n).round(1)
    cities = [c for c in hpi.columns if c != "All India"]
    u["city"] = np.array(cities)[rng.integers(0, len(cities), n)]
    u["city_tier"] = np.where(u.city.isin(pc["cities"]["tier1"]), "tier 1", "tier 2")
    # amounts (Rs lakh): US percentile -> lognormal
    sd = float(np.log(u.orig_upb).std())
    pct = u.orig_upb.rank(pct=True).clip(1e-6, 1 - 1e-6)
    u["orig_amount_lakh"] = np.exp(np.log(pc["ticket_inr_lakh"]["median"]) + sd * norm.ppf(pct))
    cap = ltv_cap(u.orig_amount_lakh.to_numpy(), ltv_bands)
    u["ltv_cap"] = cap
    u["orig_ltv_in"] = apply_ltv_caps(u.orig_amount_lakh, u.orig_ltv, ltv_bands)
    if (u.orig_ltv_in > u.ltv_cap + 1e-9).any():
        raise ValueError("synthetic loan above its RBI LTV cap")
    u["property_value_orig_lakh"] = u.orig_amount_lakh / (u.orig_ltv_in / 100)
    # dates
    fpd = pd.to_datetime(u.first_payment_date.astype(str), errors="coerce")
    orig = (fpd - pd.DateOffset(months=1)).dt.to_period("M")
    now = pd.Period(pd.Timestamp(as_of), freq="M")
    u["loan_age_months"] = (now - orig).apply(lambda x: x.n).astype(int)
    oq = orig.dt.asfreq("Q")
    q_now = pd.Period(pd.Timestamp(as_of), freq="Q")
    # city HPI index ratio now / origination (flat before the first available quarter)
    idx_o, idx_n, flat = np.empty(n), np.empty(n), np.zeros(n, bool)
    for c in cities:
        m = (u.city == c).to_numpy()
        s = hpi[c].dropna()
        qo = oq[m].clip(lower=s.index.min())
        flat[m] = (oq[m] < s.index.min()).to_numpy()
        idx_o[m] = s.reindex(qo).to_numpy()
        idx_n[m] = s.loc[min(q_now, s.index.max())]
    u["hpi_flat_before_series"] = flat
    u["property_value_now_lakh"] = u.property_value_orig_lakh * idx_n / idx_o
    # rates: repo-linked
    first_q = repo_q.index.min()
    u["repo_orig"] = repo_q.reindex(oq.clip(lower=first_q)).to_numpy()
    sp = pc["rate"]["spread_pp"]
    u["rate_orig"] = u.repo_orig + sp
    u["rate_now"] = repo_now + sp
    # tenure and balance
    t = pc["tenure"]
    retire = np.where(
        u.self_employed, t["retirement_age"]["self_employed"], t["retirement_age"]["salaried"]
    )
    n_orig = np.minimum(t["original_years"], retire - u.age_at_origination) * 12
    u["tenure_orig_months"] = np.floor(n_orig)
    alive = u.loan_age_months < u.tenure_orig_months
    stats["dropped_matured_under_indian_tenure"] = int((~alive).sum())
    u = u[alive.to_numpy()].reset_index(drop=True)
    retire = np.where(
        u.self_employed, t["retirement_age"]["self_employed"], t["retirement_age"]["salaried"]
    )
    us_sched = scheduled_balance(
        u.orig_upb, u.orig_interest_rate, u.orig_loan_term, u.loan_age_months
    )
    curtail = np.clip(u.current_upb / np.where(us_sched > 0, us_sched, np.nan), 0, 1)
    curtail = np.nan_to_num(curtail, nan=1.0)
    in_sched = scheduled_balance(
        u.orig_amount_lakh, u.rate_orig, u.tenure_orig_months, u.loan_age_months
    )
    u["balance_lakh"] = in_sched * curtail
    u["emi_orig_lakh"] = annuity(u.orig_amount_lakh, u.rate_orig, u.tenure_orig_months)
    age_now = u.age_at_origination + u.loan_age_months / 12
    u["extension_cap_months"] = np.floor(
        np.minimum(t["max_years"] * 12 - u.loan_age_months, (retire - age_now) * 12)
    ).clip(lower=1)
    rem, shock = payment_shock(u.balance_lakh, u.rate_now, u.emi_orig_lakh, u.extension_cap_months)
    u["remaining_months"] = rem
    u["payment_shock"] = shock
    npa = u.stage_rule.isin(["default", "default_arrears"]).to_numpy()
    s0 = float(u.balance_lakh[npa].sum() / u.balance_lakh.sum())
    k = stock_multiplier(s0, pc["gnpa_target"])
    stats["us_npa_share_eligible"] = s0
    stats["pd_calibration_k"] = float(k)
    # GNPA calibration on INR exposure: the delinquent stock (NPA and 30-89 dpd) scales with the
    # default intensity, so each delinquent loan is kept with probability k (k < 1) or
    # replicated floor(k) or floor(k) + 1 times (k > 1; copies get the suffix '-cN')
    dlq = npa | u.dpd_bucket.isin(["30-59", "60-89"]).to_numpy()
    copies = np.where(dlq, np.floor(k) + (rng.random(len(u)) < k - np.floor(k)), 1).astype(int)
    u = u.loc[u.index.repeat(copies)].copy()
    u["copy_no"] = u.groupby(level=0).cumcount()
    u["loan_id"] = np.where(
        u.copy_no > 0, u.loan_id.astype(str) + "-c" + u.copy_no.astype(str), u.loan_id
    )
    u = u.reset_index(drop=True)
    stats["delinquent_loans_dropped"] = int((dlq & (copies == 0)).sum())
    stats["delinquent_copies_added"] = int(np.clip(copies - 1, 0, None).sum())
    # exposure (Rs crore) and collateral
    u["ead_now"] = u.balance_lakh / 100
    u["current_ltv"] = 100 * u.balance_lakh / u.property_value_now_lakh
    stats["k_applied_to_pd"] = float(k)
    stats["loans"] = len(u)
    return u, stats
