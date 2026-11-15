"""Satellite regression: the credit-cycle index Z_t on macro drivers.

What: Z_t = a + sum_j beta_j * X_j,t + e_t, fitted on the development quarters. Scenarios
(Module 4) then supply X and the regression gives the Z path that moves the PIT PD (RBI paras
47-49: forward-looking, scenario-based).

Z_t is measured from defaults in (t, t+12m], i.e. calendar quarters t+1..t+4, so the macro has
to be aligned to that window. Two specifications are compared (docs/methodology/pd_point_in_time.md):

- W (window-aligned): each driver averaged over quarters t+1..t+4;
- L (explicit lags): each driver at quarter t or t-4 (lag chosen by BIC).

Controls against over-fitting on one cycle: few drivers, every coefficient must have its
economic sign (a wrong-sign driver is dropped, never forced), growth rates and changes only
(stationary), Newey-West standard errors (adjacent Z_t share 3 of 4 quarters of outcomes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import statsmodels.api as sm

from ecl.lifetime.macro import DRIVERS, window_mean

if TYPE_CHECKING:
    from collections.abc import Iterable

HAC_LAGS = 4
LAG_OPTIONS = (0, 4)


def term_name(driver: str, lag: int | str) -> str:
    """Column name of a driver term: 'x[W]' (window mean), 'x[t-k]' (lag k) or 'x[t]'."""
    return f"{driver}[W]" if lag == "W" else f"{driver}[t-{lag}]" if lag else f"{driver}[t]"


def driver_column(macro: pd.DataFrame, driver: str, lag: int | str) -> pd.Series:
    """Driver aligned to snapshot quarter t: window mean of t+1..t+4 ('W') or value at t-lag."""
    x = macro[driver]
    return window_mean(x) if lag == "W" else x.shift(lag)


@dataclass
class SatelliteFit:
    """Fitted macro satellite: Z_t regressed on macro drivers (OLS with HAC errors), with the
    kept and dropped terms."""

    alignment: str
    terms: list[tuple[str, object]]  # (driver, lag) kept
    params: pd.Series  # const + one per term
    tvalues: pd.Series
    r2: float
    bic: float
    sigma: float  # residual standard deviation
    nobs: int
    dropped: list[str] = field(default_factory=list)  # wrong-sign terms removed, in order

    def design(self, macro: pd.DataFrame) -> pd.DataFrame:
        """Design matrix of the kept terms for `macro`."""
        return pd.DataFrame(
            {term_name(d, lag): driver_column(macro, d, lag) for d, lag in self.terms},
            index=macro.index,
        )

    def predict(self, macro: pd.DataFrame) -> pd.Series:
        """Predicted Z for each quarter of `macro`."""
        x = sm.add_constant(self.design(macro), has_constant="add")
        return x[self.params.index] @ self.params

    def describe(self) -> str:
        """The fitted equation as text."""
        return (
            " + ".join(
                f"{self.params[term_name(d, lag)]:+.3f}*{term_name(d, lag)}"
                for d, lag in self.terms
            )
            or "(intercept only)"
        )


def fit_terms(
    z: pd.Series,
    macro: pd.DataFrame,
    terms: Iterable[tuple[str, int | str]],
    alignment: str,
    quarters: pd.Index,
) -> SatelliteFit:
    """OLS with HAC errors on the given quarters; wrong-sign terms are dropped one at a time
    (the most significant wrong sign first) until every sign is as expected."""
    terms, dropped = list(terms), []
    while True:
        x = pd.DataFrame(
            {term_name(d, lag): driver_column(macro, d, lag) for d, lag in terms}, index=macro.index
        )
        df = pd.concat([z.rename("z"), x], axis=1).loc[quarters].dropna()
        res = sm.OLS(df.z, sm.add_constant(df.drop(columns="z"), has_constant="add")).fit(
            cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS}
        )
        wrong = [
            (res.tvalues[term_name(d, lag)] * -DRIVERS[d], (d, lag))
            for d, lag in terms
            if np.sign(res.params[term_name(d, lag)]) != DRIVERS[d]
        ]
        if not wrong:
            return SatelliteFit(
                alignment,
                terms,
                res.params,
                res.tvalues,
                float(res.rsquared),
                float(res.bic),
                float(np.sqrt(res.scale)),
                int(res.nobs),
                dropped,
            )
        worst = max(wrong)[1]
        terms.remove(worst)
        dropped.append(term_name(*worst))


def fit_window(
    z: pd.Series, macro: pd.DataFrame, drivers: Iterable[str], quarters: pd.Index
) -> SatelliteFit:
    """Specification W: every driver averaged over the outcome window t+1..t+4."""
    return fit_terms(z, macro, [(d, "W") for d in drivers], "W", quarters)


def fit_lagged(
    z: pd.Series,
    macro: pd.DataFrame,
    drivers: Iterable[str],
    quarters: pd.Index,
    lags: Iterable[int] = LAG_OPTIONS,
) -> SatelliteFit:
    """Specification L: one lag per driver from `lags`, the combination with the lowest BIC
    after sign-constrained dropping. Every combination uses the same quarters (the macro
    history starts decades before 2000), so the BICs are comparable."""
    best = None
    for combo in product(lags, repeat=len(drivers)):
        fit = fit_terms(z, macro, list(zip(drivers, combo, strict=True)), "L", quarters)
        if best is None or fit.bic < best.bic:
            best = fit
    return best
