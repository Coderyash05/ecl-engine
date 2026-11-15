"""LGD = P(no cure | default) x severity given liquidation (docs/methodology/lgd_ead.md).

What (RBI paras 97, 99: own LGD estimate, independently validated):
- **Cure model** (logistic regression; statsmodels, standard errors clustered by loan because a
  default contributes one row per observation point): P(the default ends in liquidation) given,
  at the observation point,
  - indexed LTV (linear spline; the borrower's equity decides between cure and sale),
  - credit score at origination (spline), a prior 30+ dpd episode before the default spell,
  - loan age (spline), relief at default (forbearance / disaster / deferral: such defaults cure),
  - **months in default** (dummies 3-36): the cure probability falls with time in default,
    which gives Stage 3 loans an LGD conditional on months in default.
  Missing LTV / score: median value plus a missing flag.
- **Severity model** (fractional logit: GLM binomial with logit link on severity clipped to
  [0, 1]; Papke-Wooldridge quasi-likelihood, robust standard errors): discounted loss / EAD of
  liquidations given indexed LTV at default (spline), mortgage insurance coverage, property type
  and loan size.
Both models use only borrower / collateral variables; macro enters through indexed LTV, so a
scenario's state house-price path moves LGD.

US data (Freddie Mac); not Indian risk estimates.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm


def spline(x: np.ndarray, knots: list[float], name: str) -> tuple[list, list]:
    """Linear spline columns: x and (x - k)+ for each knot."""
    cols, names = [x], [name]
    for k in knots:
        cols.append(np.maximum(x - k, 0.0))
        names.append(f"{name}>{k:g}")
    return cols, names


def _fill(x: np.ndarray, value: float) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    miss = np.isnan(x)
    return np.where(miss, value, x), miss.astype(float)


@dataclass
class CureModel:
    """P(a default is not cured, i.e. ends in liquidation): logistic model of indexed LTV,
    credit score and loan age (linear splines), a prior 30+ dpd episode, relief at default and
    months in default (dummies). Fitted on resolved defaults; `intercept_shift` recalibrates
    the level to a recent workout window (para 97: own LGD estimate)."""

    knots: dict
    months: list[int]
    fill: dict = field(default_factory=dict)
    params: np.ndarray | None = None
    bse: np.ndarray | None = None
    names: list[str] = field(default_factory=list)
    intercept_shift: float = 0.0  # recalibration of the level (lgd-0.2.0); 0 = development fit

    def design(self, d: pd.DataFrame) -> np.ndarray:
        """d: ltv, credit_score, prior_dlq, age, relief, m."""
        ltv, ltv_m = _fill(d.ltv.values, self.fill["ltv"])
        sc, sc_m = _fill(d.credit_score.values, self.fill["credit_score"])
        cols, names = [np.ones(len(d))], ["const"]
        for x, kn, nm in [
            (ltv / 10, [k / 10 for k in self.knots["ltv"]], "ltv/10"),
            (sc / 100, [k / 100 for k in self.knots["score"]], "score/100"),
            (np.asarray(d.age, float) / 12, [k / 12 for k in self.knots["age"]], "age_years"),
        ]:
            c, n = spline(x, kn, nm)
            cols += c
            names += n
        cols += [ltv_m, sc_m, d.prior_dlq.astype(float).values, d.relief.astype(float).values]
        names += ["ltv missing", "score missing", "prior 30+ episode", "relief at default"]
        m = np.asarray(d.m)
        for mm in self.months[1:]:
            cols.append((m == mm).astype(float))
            names.append(f"months in default = {mm}")
        self.names = names
        return np.column_stack(cols)

    def fit(self, d: pd.DataFrame, y: np.ndarray, groups: np.ndarray) -> CureModel:
        """Fit on observation rows `d` with outcome `y` (1 = no cure); standard errors clustered
        by loan (`groups`)."""
        self.fill = {
            "ltv": float(np.nanmedian(d.ltv)),
            "credit_score": float(np.nanmedian(d.credit_score)),
        }
        x = self.design(d)
        res = sm.Logit(y, x).fit(disp=0, cov_type="cluster", cov_kwds={"groups": groups})
        self.params, self.bse = res.params, res.bse
        return self

    def p_no_cure(self, d: pd.DataFrame) -> np.ndarray:
        """P(no cure) per row of `d`, including the intercept shift."""
        return 1 / (1 + np.exp(-(self.design(d) @ self.params + self.intercept_shift)))

    def recalibrate(self, d: pd.DataFrame, y: np.ndarray) -> float:
        """Intercept shift so that the mean predicted no-cure on `d` equals the actual rate of
        `y` (the slopes are kept: only the level moves). Returns and stores the shift."""
        from scipy.optimize import brentq

        eta = self.design(d) @ self.params
        target = float(np.mean(y))
        self.intercept_shift = brentq(
            lambda c: float(np.mean(1 / (1 + np.exp(-(eta + c))))) - target, -10, 10
        )
        return self.intercept_shift

    def coef_table(self) -> pd.DataFrame:
        """Coefficients, standard errors and z statistics."""
        return pd.DataFrame(
            {"term": self.names, "coef": self.params, "se": self.bse, "z": self.params / self.bse}
        )


@dataclass
class SeverityModel:
    """Loss severity given liquidation (discounted loss / EAD): fractional logit of indexed LTV
    at default and loan size (linear splines), mortgage insurance and property type. LGD =
    P(no cure) x severity (paras 97, 99)."""

    knots: dict
    groups: dict
    fill: dict = field(default_factory=dict)
    params: np.ndarray | None = None
    bse: np.ndarray | None = None
    names: list[str] = field(default_factory=list)

    def design(self, d: pd.DataFrame) -> np.ndarray:
        """d: ltv, mi_pct, property_type, orig_upb."""
        ltv, ltv_m = _fill(d.ltv.values, self.fill["ltv"])
        cols, names = [np.ones(len(d))], ["const"]
        for x, kn, nm in [
            (ltv / 10, [k / 10 for k in self.knots["ltv"]], "ltv/10"),
            (
                np.asarray(d.orig_upb, float) / 1e5,
                [k / 1e5 for k in self.knots["size"]],
                "orig_upb/100k",
            ),
        ]:
            c, n = spline(x, kn, nm)
            cols += c
            names += n
        mi = np.nan_to_num(np.asarray(d.mi_pct, float), nan=0.0)
        cols += [ltv_m, (mi > 0).astype(float), mi / 10]
        names += ["ltv missing", "MI", "MI coverage/10pp"]
        grp = pd.Series(d.property_type).map(self.groups).fillna("OTHER").values
        for g in ["PU", "CO", "OTHER"]:
            cols.append((grp == g).astype(float))
            names.append(f"property {g} (vs SF)")
        self.names = names
        return np.column_stack(cols)

    def fit(self, d: pd.DataFrame, sev: np.ndarray) -> SeverityModel:
        """Fit the fractional logit (binomial GLM, robust errors) on severities clipped to [0,
        1]."""
        self.fill = {"ltv": float(np.nanmedian(d.ltv))}
        x = self.design(d)
        y = np.clip(sev, 0, 1)
        res = sm.GLM(y, x, family=sm.families.Binomial()).fit(cov_type="HC1")
        self.params, self.bse = res.params, res.bse
        return self

    def predict(self, d: pd.DataFrame) -> np.ndarray:
        """Predicted severity per row of `d`."""
        return 1 / (1 + np.exp(-(self.design(d) @ self.params)))

    def coef_table(self) -> pd.DataFrame:
        """Coefficients, standard errors and z statistics."""
        return pd.DataFrame(
            {"term": self.names, "coef": self.params, "se": self.bse, "z": self.params / self.bse}
        )


def save(obj: object, path: Path) -> None:
    """Pickle a fitted model to `path`."""
    path.write_bytes(pickle.dumps(obj))


def load(path: Path) -> object:
    """Load a pickled model from `path`."""
    return pickle.loads(path.read_bytes())


def cure_frame(rows: pd.DataFrame) -> pd.DataFrame:
    """Cure-model inputs from observation rows (data.observation_rows)."""
    return pd.DataFrame(
        {
            "ltv": rows.ltv_obs.values,
            "credit_score": rows.credit_score.values,
            "prior_dlq": rows.prior_dlq.values,
            "age": rows.age_obs.values,
            "relief": rows.relief_d.values,
            "m": rows.m.values,
        }
    )


def severity_frame(d: pd.DataFrame, ltv_col: str = "ltv_d") -> pd.DataFrame:
    """Severity-model inputs from a defaults table, with LTV taken from `ltv_col` (LTV at default
    by default)."""
    return pd.DataFrame(
        {
            "ltv": d[ltv_col].values,
            "mi_pct": d.mi_pct.values,
            "property_type": d.property_type.values,
            "orig_upb": d.orig_upb.values,
        }
    )
