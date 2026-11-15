"""Competing-risk discrete-time hazard for lifetime PD (docs/methodology/pd_lifetime.md; RBI paras 45, 46(1), 51).

What: for a loan alive at the start of quarter k after its reference date, a multinomial logit
gives the probabilities of default, prepayment and survival in that quarter:

    log(h_d / h_s) = x' b_d        log(h_p / h_s) = x' b_p

Lifetime PD is the cumulative incidence of default, sum_k S(k-1) h_d(k), where
S(k) = prod_{j<=k} (1 - h_d(j) - h_p(j)): prepayment removes loans before they can default
(para 51: expected cash flows include prepayment), and the sum runs to the contractual
maturity (para 46(1)).

Covariates (champion "H2"):
- loan-age baseline: one level per year of age 0-14, ages 15+ pooled (flat to maturity);
- v1.2.0 score components at the reference date, each with its own coefficient per horizon
  bucket (quarters 1-4, 5-8, 9-12, 13-20, 21+): the delinquency-state part and the rest of
  the logit. How fast their information fades is estimated, not assumed (para 45);
- change in current LTV since the reference date (scheduled amortisation and the state HPI
  path), entered as the change in the v1.2.0 WoE of current LTV: the LTV effect saturates
  exactly as in the score (flat below 27% LTV). A linear LTV change was tried first and
  extrapolated without bound over 30-year horizons: projected from origination, decades of
  house-price growth pushed the hazard ever lower, so the SICR comparator (origination side)
  drifted below the current side by 1.2x-1.6x with loan age for unchanged loans. Plus the change
  in negative equity (LTV above 100), which the WoE's top bin (>= 94%) does not separate;
- change in the v1.2.0 WoE of loan age since the reference date. The score's loan-age effect
  (12-month PD rises with seasoning) would otherwise stay frozen at the reference age: projected
  from origination it keeps a young loan's low-risk WoE for its whole life, and the SICR
  comparator came out ~1.4x below the current side for unchanged loans;
- the credit-cycle index z_q of the quarter (paths.py);
- refinancing incentive (note rate - 30-year mortgage rate) in bands, and national HPI growth.

Specification options (`opts`, compared in ecl.lifetime.fit_lifetime):
- default_incentive: how the incentive enters the *default* equation - "bands" (as the
  prepayment equation), "none", or "ge1" (one indicator, incentive >= 1 pp). The bands act as a
  level shift learned when most loans had an incentive: in 2022-23 (89% of loans below -1 pp)
  they lowered the default hazard by ~0.4 log-odds and the year-1 check fell to 0.70;
- prepay_ramp: seasoning of prepayment - "none", "age" (quarter-of-age steps inside the first
  two years), "young" (incentive bands x loan younger than 2 years), "both", or "both5" (both,
  plus incentive bands x loan aged 2-5 years: the 2012-16 over-prediction lasts into year 3).
- dlq_decay: how the delinquency information fades with horizon in the *default* equation -
  "shared" (the v1.2.0 state coefficient x one weight per horizon bucket, the same fade for every
  state) or "state" (one coefficient per delinquency state and horizon bucket). With the shared
  fade (0.91 -> 0.29), year 2 of recently delinquent or cured loans came out 23-39% too low
  relative to year 1 (jump check, pdlife-0.2.0).
Terms tagged [default] / [prepay] enter only that equation.

Calibrated splice (`carry_year1_ratio`): year 1 of the lifetime curve is the 12m PIT PD; the
loan's year-1 ratio PIT / hazard is carried into later years with a weight exp(-(y-1)/tau) that
fades to 1. tau is estimated on development references (fit to the empirical year-2 and year-3
marginal default by segment), not chosen by hand.

Challenger "H1" re-estimates the borrower effects instead of using the score: delinquency-
state dummies by horizon bucket and the WoE of the eight other v1.2.0 features.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

if TYPE_CHECKING:
    from ecl.lifetime.paths import MacroPath

HB_LABELS = ["q1-4", "q5-8", "q9-12", "q13-20", "q21+"]
AGE_YEARS = 15  # age years 0..14 + pooled 15+
INC_EDGES = [-1.0, 0.0, 0.5, 1.0, 1.5, 2.0]
INC_LABELS = ["<-1", "-1..0", "0..0.5", "0.5..1", "1..1.5", "1.5..2", ">=2"]
INC_BASE = 1  # [-1, 0): no incentive
MIN_STEP = 1e-4  # Newton line search: smallest step fraction tried
WOE_FEATURES = [
    "credit_score",
    "current_ltv",
    "rate_spread",
    "orig_dti",
    "num_borrowers",
    "loan_age",
    "loan_purpose",
    "channel",
]
N_DLQ_STATES = 6
OUTCOMES = ["default", "prepay"]
# Terms kept out of an equation (docs/methodology/pd_lifetime.md): national HPI growth acts on prepayment only
# (its default effect runs through Z and the LTV change); the cycle index Z acts on default only.
EXCLUDED = {"default": {"hpi_yoy (per 10%)"}, "prepay": {"z"}}
DEFAULT_OPTS = {"default_incentive": "bands", "prepay_ramp": "none", "dlq_decay": "shared"}
CARRY_CLIP = (0.25, 4.0)  # bounds on the carried year-1 ratio PIT / hazard
RAMP_AGES = [(0, 3), (3, 6), (6, 9), (12, 18)]  # months; bases: 9-11 (year 0), 18-23 (year 1)
YOUNG_MONTHS = 24
MID_MONTHS = 60  # "both5": incentive x age 2-5 years


def free_parameters(names: list[str], opts: dict | None = None) -> np.ndarray:
    """(2, p) mask of estimated coefficients: EXCLUDED terms, terms tagged for the other
    equation, and (unless default_incentive == "bands") the incentive bands in the default
    equation are fixed at zero."""
    opts = {**DEFAULT_OPTS, **(opts or {})}

    def free(nm: str, out: str) -> bool:
        if nm in EXCLUDED[out]:
            return False
        other = "prepay" if out == "default" else "default"
        if nm.endswith(f"[{other}]"):
            return False
        if out == "default" and nm.startswith("incentive ") and not nm.endswith("]"):
            return opts["default_incentive"] == "bands"
        if out == "default" and nm.startswith("dlq x "):
            return opts["dlq_decay"] == "shared"
        return True

    return np.array([[free(nm, out) for nm in names] for out in OUTCOMES])


def horizon_bucket(k: np.ndarray) -> np.ndarray:
    """Horizon bucket of quarter k after the reference date: 1-4, 5-8, 9-12, 13-20, 21+ (labels
    HB_LABELS)."""
    return np.select([k <= 4, k <= 8, k <= 12, k <= 20], [0, 1, 2, 3], 4)


def amortised_balance(upb: ArrayLike, rate: ArrayLike, rm: ArrayLike, n: ArrayLike) -> np.ndarray:
    """Scheduled balance after n more monthly payments of a level-payment loan with balance
    upb, note rate (% a year) and rm months to maturity."""
    upb, rate, rm, n = (np.asarray(a, dtype=float) for a in (upb, rate, rm, n))
    r = rate / 1200
    n = np.minimum(n, rm)
    with np.errstate(divide="ignore", invalid="ignore"):
        g_n, g_rm = (1 + r) ** n, (1 + r) ** rm
        b = np.where(r > 0, upb * (g_rm - g_n) / (g_rm - 1), upb * (1 - n / rm))
    return np.where(rm > 0, np.clip(b, 0, None), 0.0)


@dataclass
class QuarterRows:
    """Covariates of loan-quarters (one row each)."""

    age_months: np.ndarray  # loan age at the start of the quarter
    k: np.ndarray  # quarters since the reference date (1, 2, ...)
    dlq: np.ndarray  # v1.2.0 delinquency-state coefficient at the reference date
    rest: np.ndarray  # v1.2.0 logit minus dlq
    dlq_state: np.ndarray  # 0-5
    woe: np.ndarray  # (n, 8) WoE of WOE_FEATURES at the reference date
    dwoe_ltv: np.ndarray  # WoE(current LTV(q)) - WoE(current LTV(reference))
    dwoe_age: np.ndarray  # WoE(loan age(q)) - WoE(loan age(reference))
    dneg: np.ndarray  # change in max(LTV - 100, 0) since the reference, pp
    ltv: np.ndarray  # current LTV(q), pp (NaN if unknown)
    z: np.ndarray  # credit-cycle index of the quarter
    incentive: np.ndarray  # note rate - mortgage rate, pp
    hpi_yoy: np.ndarray  # national HPI growth, %


def design(
    r: QuarterRows, spec: str = "H2", opts: dict | None = None
) -> tuple[np.ndarray, list[str]]:
    """Design matrix (float32) and column names."""
    opts = {**DEFAULT_OPTS, **(opts or {})}
    n = len(r.k)
    cols, names = [np.ones(n)], ["const"]
    age_year = np.minimum(r.age_months // 12, AGE_YEARS).astype(int)
    for a in range(1, AGE_YEARS + 1):
        cols.append((age_year == a).astype(float))
        names.append(f"age_{a}" + ("+" if a == AGE_YEARS else ""))
    hb = horizon_bucket(r.k)
    if spec == "H2":
        for comp, v in [("dlq", r.dlq), ("rest", r.rest)]:
            for j, lab in enumerate(HB_LABELS):
                cols.append(v * (hb == j))
                names.append(f"{comp} x {lab}")
        if opts["dlq_decay"] == "state":
            for s in range(1, N_DLQ_STATES):
                for j, lab in enumerate(HB_LABELS):
                    cols.append(((r.dlq_state == s) & (hb == j)).astype(float))
                    names.append(f"dlq_state={s} x {lab} [default]")
    else:
        for s in range(1, N_DLQ_STATES):
            for j, lab in enumerate(HB_LABELS):
                cols.append(((r.dlq_state == s) & (hb == j)).astype(float))
                names.append(f"dlq_state={s} x {lab}")
        for i, f in enumerate(WOE_FEATURES):
            cols.append(r.woe[:, i])
            names.append(f"woe {f}")
    cols += [r.dwoe_ltv, r.dneg / 10, r.dwoe_age, r.z]
    names += ["d WoE(current LTV)", "d negative equity (per 10pp)", "d WoE(loan age)", "z"]
    band = np.digitize(r.incentive, INC_EDGES)
    for b, lab in enumerate(INC_LABELS):
        if b != INC_BASE:
            cols.append((band == b).astype(float))
            names.append(f"incentive {lab}")
    if opts["default_incentive"] == "ge1":
        cols.append((r.incentive >= 1).astype(float))
        names.append("incentive >=1 [default]")
    if opts["prepay_ramp"] in ("age", "both", "both5"):
        for a, b in RAMP_AGES:
            cols.append(((r.age_months >= a) & (r.age_months < b)).astype(float))
            names.append(f"age {a}-{b - 1}m [prepay]")
    if opts["prepay_ramp"] in ("young", "both", "both5"):
        young = r.age_months < YOUNG_MONTHS
        for b, lab in enumerate(INC_LABELS):
            if b > INC_BASE:
                cols.append(((band == b) & young).astype(float))
                names.append(f"young x incentive {lab} [prepay]")
    if opts["prepay_ramp"] == "both5":
        mid = (r.age_months >= YOUNG_MONTHS) & (r.age_months < MID_MONTHS)
        for b, lab in enumerate(INC_LABELS):
            if b > INC_BASE:
                cols.append(((band == b) & mid).astype(float))
                names.append(f"age 2-5y x incentive {lab} [prepay]")
    cols.append(r.hpi_yoy / 10)
    names.append("hpi_yoy (per 10%)")
    return np.column_stack(cols).astype(np.float32), names


@dataclass
class WoeMap:
    """A v1.2.0 WoE as a function of the raw value (bin splits, WoE per bin, missing)."""

    splits: np.ndarray
    woe: np.ndarray  # len(splits) + 1
    missing: float

    def __call__(self, v: np.ndarray) -> np.ndarray:
        """WoE value of each element of `v` (missing values get the missing-bin WoE)."""
        v = np.asarray(v, dtype=float)
        w = self.woe[np.digitize(np.nan_to_num(v, nan=0.0), self.splits)]
        return np.where(np.isnan(v), self.missing, w)


@dataclass
class HazardModel:
    """Competing-risk discrete-time hazard: a multinomial logit of default and prepayment against
    survival, per quarter (paras 45-46, 51). `beta` holds one row per outcome; `cov` is the
    loan-clustered sandwich covariance."""

    spec: str
    names: list[str]
    beta: np.ndarray  # (2, p): default, prepay vs survive
    cov: np.ndarray | None = None  # (2p, 2p) sandwich covariance
    meta: dict = field(default_factory=dict)
    woe_maps: dict | None = None  # {"current_ltv": WoeMap, "loan_age": WoeMap}
    opts: dict = field(default_factory=lambda: dict(DEFAULT_OPTS))
    free: np.ndarray | None = None  # (2, p) estimated coefficients

    def probs(self, x: np.ndarray) -> np.ndarray:
        """(n, 3): survive, default, prepay."""
        eta = x.astype(np.float64) @ self.beta.T
        eta = np.column_stack([np.zeros(len(x)), eta])
        eta -= eta.max(axis=1, keepdims=True)
        e = np.exp(eta)
        return e / e.sum(axis=1, keepdims=True)

    def coef_table(self) -> pd.DataFrame:
        """Coefficients by outcome with standard errors and z statistics (NaN where a parameter
        is fixed)."""
        p = len(self.names)
        se = np.sqrt(np.diag(self.cov)) if self.cov is not None else np.full(2 * p, np.nan)
        free = self.free if self.free is not None else free_parameters(self.names, self.opts)
        rows = []
        for j, out in enumerate(OUTCOMES):
            for i, nm in enumerate(self.names):
                if not free[j, i]:
                    continue
                b, s = self.beta[j, i], se[j * p + i]
                rows.append({"outcome": out, "term": nm, "coef": b, "se": s, "z": b / s})
        return pd.DataFrame(rows)

    def save(self, path: Path) -> None:
        """Pickle the model to `path`."""
        path.write_bytes(pickle.dumps(self))

    @staticmethod
    def load(path: Path) -> HazardModel:
        """Load a pickled model from `path`."""
        return pickle.loads(path.read_bytes())


def fit_mnl(
    x: np.ndarray,
    y: np.ndarray,
    w: np.ndarray,
    names: list[str],
    spec: str,
    max_iter: int = 50,
    tol: float = 1e-8,
    chunk: int = 250_000,
    cluster: np.ndarray | None = None,
    free: np.ndarray | None = None,
    opts: dict | None = None,
) -> HazardModel:
    """Weighted multinomial logit by Newton-Raphson (classes 1, 2 vs 0), with a sandwich
    covariance (rows are a weighted sample), clustered by `cluster` if given (rows must then
    be sorted by cluster). `free` (2, p) marks the estimated coefficients; the others stay
    at zero (default: free_parameters(names))."""
    n, p = x.shape
    opts = {**DEFAULT_OPTS, **(opts or {})}
    free = free_parameters(names, opts) if free is None else free
    act = free.ravel()
    beta = np.zeros((2, p))
    share = np.array([np.sum(w * (y == c)) for c in range(3)]) / w.sum()
    beta[:, 0] = np.log(share[1:] / share[0])

    def pass_(beta: np.ndarray, need_h: bool = True) -> tuple[float, np.ndarray, np.ndarray]:
        ll, g, h = 0.0, np.zeros(2 * p), np.zeros((2 * p, 2 * p))
        for a in range(0, n, chunk):
            xc = x[a : a + chunk].astype(np.float64)
            yc, wc = y[a : a + chunk], w[a : a + chunk]
            m = HazardModel(spec, names, beta)
            pr = m.probs(xc)
            ll += np.sum(wc * np.log(np.clip(pr[np.arange(len(yc)), yc], 1e-300, None)))
            for j in range(2):
                r = wc * ((yc == j + 1) - pr[:, j + 1])
                g[j * p : (j + 1) * p] += xc.T @ r
                if need_h:
                    for k in range(2):
                        d = wc * pr[:, j + 1] * ((j == k) - pr[:, k + 1])
                        h[j * p : (j + 1) * p, k * p : (k + 1) * p] -= (xc * d[:, None]).T @ xc
        return ll, g, h

    ll, g, h = pass_(beta)
    for it in range(max_iter):
        # damped Newton: a small ridge keeps the solve stable if a step saturates the
        # probabilities; steps are capped at 5 log-odds per coefficient
        a_ = -h[np.ix_(act, act)]
        ridge = 1e-10 * np.trace(a_) / len(a_)
        try:
            sub = np.linalg.solve(a_ + ridge * np.eye(len(a_)), g[act])
        except np.linalg.LinAlgError:
            sub = np.linalg.lstsq(
                a_ + 1e-6 * np.trace(a_) / len(a_) * np.eye(len(a_)), g[act], rcond=None
            )[0]
        step = np.zeros(2 * p)
        step[act] = sub * min(1.0, 5.0 / max(np.abs(sub).max(), 1e-12))
        step = step.reshape(2, p)
        t = 1.0
        while True:
            ll_new, g_new, h_new = pass_(beta + t * step)
            if ll_new >= ll - 1e-9 or t < MIN_STEP:
                break
            t /= 2
        beta = beta + t * step
        done = abs(ll_new - ll) < tol * max(1.0, abs(ll))
        ll, g, h = ll_new, g_new, h_new
        if done:
            break
    # sandwich: H^-1 M H^-1, M = sum over clusters of (summed weighted scores)^2
    meat = np.zeros((2 * p, 2 * p))
    model = HazardModel(spec, names, beta)
    bounds = [*range(0, n, chunk), n]
    if cluster is not None:  # move chunk edges to the next change of cluster
        change = np.flatnonzero(np.r_[True, cluster[1:] != cluster[:-1]])
        inner = change[np.searchsorted(change, bounds[1:-1]).clip(max=len(change) - 1)]
        bounds = sorted({0, n, *inner.tolist()})
    for a, b in pairwise(bounds):
        xc = x[a:b].astype(np.float64)
        yc, wc = y[a:b], w[a:b]
        pr = model.probs(xc)
        u = np.hstack([xc * (wc * ((yc == j + 1) - pr[:, j + 1]))[:, None] for j in range(2)])
        if cluster is not None:
            starts = np.flatnonzero(np.r_[True, cluster[a + 1 : b] != cluster[a : b - 1]])
            u = np.add.reduceat(u, starts, axis=0)
        meat += u.T @ u
    hinv = np.linalg.inv(-h[np.ix_(act, act)])
    cov = np.zeros((2 * p, 2 * p))
    cov[np.ix_(act, act)] = hinv @ meat[np.ix_(act, act)] @ hinv
    model.cov = cov
    model.opts, model.free = opts, free
    model.meta = {
        "loglik": ll,
        "iterations": it + 1,
        "rows": int(n),
        "weighted_rows": float(w.sum()),
    }
    return model


# ---------------------------------------------------------------- projection


@dataclass
class Loans:
    """Loans at a reference date (one entry each)."""

    age: np.ndarray  # loan age (months) at the reference date
    rm: np.ndarray  # months to maturity at the reference date
    upb: np.ndarray
    rate: np.ndarray  # note rate, %
    value: np.ndarray  # property value at the reference date (NaN if unknown)
    ltv: np.ndarray  # current LTV at the reference date, pp (NaN if unknown)
    state_idx: np.ndarray  # row in the path's log_hpi (-1: no index)
    ref_q: np.ndarray  # quarter index of the reference date
    dlq: np.ndarray
    rest: np.ndarray
    dlq_state: np.ndarray
    woe: np.ndarray  # (n, 8)

    def __len__(self) -> int:
        return len(self.age)

    def take(self, idx: ArrayLike) -> Loans:
        """The loans at positions `idx`."""
        return Loans(**{f: getattr(self, f)[idx] for f in self.__dataclass_fields__})


def quarter_rows(loans: Loans, path: MacroPath, k: np.ndarray, woe_maps: dict) -> QuarterRows:
    """Covariates of quarter k (array, one per loan) after each loan's reference date."""
    q = loans.ref_q + k
    bal = amortised_balance(loans.upb, loans.rate, loans.rm, 3 * k)
    value = loans.value * path.hpi_ratio(loans.state_idx, loans.ref_q, q)
    with np.errstate(divide="ignore", invalid="ignore"):
        ltv = 100 * bal / value
    known = ~(np.isnan(ltv) | np.isnan(loans.ltv))
    lw, aw = woe_maps["current_ltv"], woe_maps["loan_age"]
    dwoe = np.where(known, lw(ltv) - lw(loans.ltv), 0.0)
    age_q = loans.age + 3 * (k - 1)
    dneg = np.where(known, np.maximum(ltv - 100, 0) - np.maximum(loans.ltv - 100, 0), 0.0)
    return QuarterRows(
        age_months=age_q,
        k=k,
        dlq=loans.dlq,
        rest=loans.rest,
        dlq_state=loans.dlq_state,
        woe=loans.woe,
        dwoe_ltv=dwoe,
        dwoe_age=aw(age_q) - aw(loans.age),
        dneg=dneg,
        ltv=ltv,
        z=path.at(path.z_q, q),
        incentive=loans.rate - path.at(path.mortgage30, q),
        hpi_yoy=path.at(path.hpi_yoy, q),
    )


def project(
    model: HazardModel, loans: Loans, path: MacroPath, n_quarters: int, chunk: int = 5000
) -> tuple[np.ndarray, np.ndarray]:
    """Default and prepayment hazards (n, n_quarters). Quarters after contractual maturity
    have zero hazard (the loan is repaid)."""
    n = len(loans)
    h_d = np.zeros((n, n_quarters))
    h_p = np.zeros((n, n_quarters))
    ks = np.arange(1, n_quarters + 1)
    for a in range(0, n, chunk):
        sub = loans.take(slice(a, a + chunk))
        m = len(sub)
        rep = sub.take(np.repeat(np.arange(m), n_quarters))
        rows = quarter_rows(rep, path, np.tile(ks, m), model.woe_maps)
        x, _ = design(rows, model.spec, model.opts)
        pr = model.probs(x).reshape(m, n_quarters, 3)
        alive = ks[None, :] <= np.ceil(sub.rm / 3)[:, None]
        h_d[a : a + m] = pr[:, :, 1] * alive
        h_p[a : a + m] = pr[:, :, 2] * alive
    return h_d, h_p


def cumulative(h_d: np.ndarray, h_p: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Survival S(k) and cumulative incidences of default and prepayment after k quarters."""
    s = np.cumprod(1 - h_d - h_p, axis=1)
    s_prev = np.hstack([np.ones((len(s), 1)), s[:, :-1]])
    return s, np.cumsum(s_prev * h_d, axis=1), np.cumsum(s_prev * h_p, axis=1)


def apply_annual_floor(
    h_d: np.ndarray, h_p: np.ndarray, floor: float, first_year: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Raise each year's default hazards so that the conditional annual PD (default in the year
    given alive at its start) is at least `floor` (config pd.floor_lifetime_annual,
    rbi_specified: false). Years without any live quarter are left alone. Returns the floored
    hazards and a (n, years) mask of where the floor bound."""
    h_d = h_d.copy()
    n, k = h_d.shape
    years = int(np.ceil(k / 4))
    bound = np.zeros((n, years), dtype=bool)
    for y in range(first_year, years):
        sl = slice(4 * y, min(4 * y + 4, k))
        live = (h_d[:, sl] + h_p[:, sl]).sum(axis=1) > 0
        for _ in range(3):
            surv = np.cumprod(1 - h_d[:, sl] - h_p[:, sl], axis=1)
            prev = np.hstack([np.ones((n, 1)), surv[:, :-1]])
            pd_y = np.sum(prev * h_d[:, sl], axis=1)
            low = live & (pd_y < floor * (1 - 1e-9)) & (pd_y > 0)
            if not low.any():
                break
            bound[low, y] = True
            scale = np.where(low, floor / np.where(pd_y > 0, pd_y, 1), 1.0)
            h_d[:, sl] = np.minimum(h_d[:, sl] * scale[:, None], 1 - h_p[:, sl])
    return h_d, bound


def carry_weight(years: np.ndarray, tau: float) -> np.ndarray:
    """Weight of the year-1 ratio in year y (y = 1, 2, ...): 1 in year 1, exp(-(y-1)/tau) after;
    tau = 0 carries nothing, tau = inf carries the full ratio."""
    years = np.asarray(years, dtype=float)
    if tau == 0:
        return (years <= 1).astype(float)
    if np.isinf(tau):
        return np.ones_like(years)
    return np.where(years <= 1, 1.0, np.exp(-(years - 1) / tau))


def carry_year1_ratio(
    h_d: np.ndarray, h_p: np.ndarray, ratio: np.ndarray, tau: float
) -> np.ndarray:
    """Calibrated splice: scale the default hazards of years 2+ by ratio ** w(y), where ratio
    = 12m PIT PD / hazard year-1 default (clipped to CARRY_CLIP) and w fades with tau. Year 1
    is untouched (it is replaced by the PIT PD in `splice_year1`)."""
    k = h_d.shape[1]
    w = carry_weight(np.arange(k) // 4 + 1, tau)
    w[:4] = 0.0
    r = np.clip(np.nan_to_num(ratio, nan=1.0), *CARRY_CLIP)
    scaled = h_d * r[:, None] ** w[None, :]
    return np.minimum(scaled, 1 - h_p)


def splice_year1(
    cif_d: np.ndarray, cif_p: np.ndarray, s: np.ndarray, pd12: np.ndarray
) -> np.ndarray:
    """Lifetime cumulative default with year 1 replaced by the 12-month PIT PD:
    years 2+ are the hazard's PD conditional on surviving year 1, applied to the loans that
    survive year 1 (1 - PD12 - hazard's year-1 prepayment)."""
    k4 = min(3, cif_d.shape[1] - 1)
    d4, p4, s4 = cif_d[:, k4], cif_p[:, k4], s[:, k4]
    surv1 = np.clip(1 - pd12 - p4, 0, None)
    out = np.empty_like(cif_d)
    with np.errstate(divide="ignore", invalid="ignore"):
        shape1 = np.where(d4[:, None] > 0, cif_d[:, : k4 + 1] / d4[:, None], 0.0)
        cond = np.where(s4[:, None] > 0, (cif_d[:, k4 + 1 :] - d4[:, None]) / s4[:, None], 0.0)
    out[:, : k4 + 1] = pd12[:, None] * shape1
    out[:, k4 + 1 :] = pd12[:, None] + surv1[:, None] * cond
    return out


def remaining_from(cif_d: np.ndarray, s: np.ndarray, j: np.ndarray) -> np.ndarray:
    """PD of default after quarter j until the end, conditional on being alive at quarter j
    (j = 0: from the reference date)."""
    n, k = cif_d.shape
    rows = np.arange(n)
    jj = np.clip(j, 0, k)
    d_j = np.where(jj > 0, cif_d[rows, np.maximum(jj - 1, 0)], 0.0)
    s_j = np.where(jj > 0, s[rows, np.maximum(jj - 1, 0)], 1.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(s_j > 0, (cif_d[:, -1] - d_j) / s_j, 0.0)
