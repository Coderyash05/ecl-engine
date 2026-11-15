"""ECL measurement per loan and scenario (Module 7; RBI paras 25, 44-51).

What:
- discount factor for a default in year y (at mid-year): DF_y = (1 + r/12)^(-12 (y - 0.5)),
  r = the origination note rate (EIR at initial recognition proxy, paras 50-51; para 44: timing
  matters, so a later loss is worth less today);
- **Stage 1**: 12-month ECL = PD12 x LGD_1 x EAD_1 x DF_1 (para 25(1));
- **Stage 2**: lifetime ECL = sum_y marginal PD_y x LGD_y x EAD_y x DF_y (para 25(2)); the
  marginal PDs come from the spliced, floored lifetime PD (Module 3-4, not mechanically derived
  from the 12-month PD, para 45); LGD_y already discounts the workout to the default date;
- **Stage 3**: LGD in default (by months in default) x EAD now (para 25(3));
- each scenario's ECL is computed first, then probability-weighted (paras 47-48): weighting
  inputs instead would understate ECL whenever losses are convex in the macro factor.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike


def discount_factors(note_rate: ArrayLike, years: int, point: float = 0.5) -> np.ndarray:
    """(n, years) discount factors to the reporting date for defaults at year - 1 + point."""
    r = np.asarray(note_rate, float)[:, None] / 1200
    t = (np.arange(years) + point) * 12
    return (1 + r) ** -t[None, :]


def marginal_pd(cum_default_by_year: np.ndarray) -> np.ndarray:
    """Marginal default probability by year from cumulative default by year (n loans x years)."""
    c = np.asarray(cum_default_by_year, float)
    return np.diff(np.hstack([np.zeros((len(c), 1)), c]), axis=1)


def ecl_12m(
    pd12: ArrayLike, lgd_by_year: np.ndarray, ead_by_year: np.ndarray, df: np.ndarray
) -> np.ndarray:
    """12-month ECL = 12-month PD x LGD x EAD x discount factor of year 1 (Stage 1, para 25(1))."""
    return np.asarray(pd12) * lgd_by_year[:, 0] * ead_by_year[:, 0] * df[:, 0]


def ecl_lifetime(
    cum_default_by_year: np.ndarray,
    lgd_by_year: np.ndarray,
    ead_by_year: np.ndarray,
    df: np.ndarray,
) -> np.ndarray:
    """Lifetime ECL = sum over years of marginal PD x LGD x EAD x discount factor (Stages 2 and
    3, paras 25(2)-(3), 44, 46)."""
    k = min(cum_default_by_year.shape[1], lgd_by_year.shape[1], ead_by_year.shape[1], df.shape[1])
    m = marginal_pd(cum_default_by_year[:, :k])
    return (m * lgd_by_year[:, :k] * ead_by_year[:, :k] * df[:, :k]).sum(axis=1)


def weighted(per_scenario: dict[str, np.ndarray], weights: dict[str, float]) -> np.ndarray:
    """Probability-weighted ECL: sum_s w_s ECL_s (weights must sum to 1)."""
    if abs(sum(weights.values()) - 1) > 1e-9:
        raise ValueError("scenario weights must sum to 1")
    return sum(weights[k] * np.asarray(per_scenario[k], float) for k in weights)
