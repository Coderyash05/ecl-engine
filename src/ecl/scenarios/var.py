"""Small VAR on the scenario drivers: conditional base forecast and simulated dispersion.

What: a vector autoregression (VAR) on four quarterly US series,
- hpi_g: national house-price growth, annualised log change (400 x dlog USSTHPI);
- gdp_g: real GDP growth, quarter on quarter, seasonally adjusted annual rate (as published);
- d_mort: change in the 30-year mortgage rate (pp);
- d_unrate: change in the unemployment rate (pp).
Each variable is regressed on two lags of all four plus a constant (OLS; equation by equation
is efficient because every equation has the same regressors).

Why (RBI paras 47-48, 124; docs/methodology/scenarios.md):
- **Conditional base.** Published forecasts (SPF) give GDP, unemployment and a long rate, but no
  house prices. `conditional_forecast` fills HPI with its expectation *given* the published paths
  of the other variables ("hard conditions": the shocks that make the constrained variables hit
  their published paths exactly, at the smallest Mahalanobis distance, and their implications
  for HPI).
- **Dispersion.** `simulate_deviations` propagates block-bootstrapped residuals through the VAR
  dynamics from a zero starting deviation. Adding them to the base keeps the simulation mean at
  the base, so the scenarios built from regions of the simulated distribution are unbiased by
  construction (para 47).

US data; the Indian adapter (Module 12) maps roles to Indian series.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

VAR_VARS = ["hpi_g", "gdp_g", "d_mort", "d_unrate"]
ANNUALISE = 400  # quarterly log change -> annualised % (4 quarters x 100)


def var_data(macro: pd.DataFrame) -> pd.DataFrame:
    """Quarterly VAR variables from the quarterly macro table (macro.load_macro)."""
    return pd.DataFrame(
        {
            "hpi_g": ANNUALISE * np.log(macro["hpi"]).diff(),
            "gdp_g": macro["gdp_qoq_saar"],
            "d_mort": macro["mortgage30"].diff(),
            "d_unrate": macro["unrate"].diff(),
        }
    )


@dataclass
class VAR:
    """Vector autoregression y_t = c + sum_i A_i y_(t-1-i) + e_t on the macro drivers (OLS per
    equation), used to simulate scenario paths around the base."""

    names: list[str]
    const: np.ndarray  # (n,)
    A: np.ndarray  # (p, n, n): y_t = c + sum_i A[i] @ y_{t-1-i} + e_t
    sigma: np.ndarray  # (n, n) residual covariance (dof-adjusted)
    resid: np.ndarray  # (T, n)
    index: pd.PeriodIndex  # quarters of the residuals

    @property
    def p(self) -> int:
        """Lag order."""
        return self.A.shape[0]

    @property
    def n(self) -> int:
        """Number of variables."""
        return self.A.shape[1]

    def max_abs_eigenvalue(self) -> float:
        """Stability: the largest modulus of the companion matrix (< 1 = stable)."""
        n, p = self.n, self.p
        comp = np.zeros((n * p, n * p))
        comp[:n] = np.hstack(list(self.A))
        comp[n:, :-n] = np.eye(n * (p - 1))
        return float(np.abs(np.linalg.eigvals(comp)).max())


def fit_var(
    data: pd.DataFrame, start: str, end: str, p: int, exclude: list[str] | None = None
) -> VAR:
    """OLS VAR(p) with constant on quarters start..end; quarters in `exclude` (e.g. COVID) are
    dropped as equations, but stay available as lags only if not excluded themselves."""
    d = data[VAR_VARS]
    lagged = pd.concat([d.shift(i + 1).add_suffix(f"_l{i + 1}") for i in range(p)], axis=1)
    rows = d.loc[start:end].index
    if exclude:
        drop = pd.PeriodIndex(exclude, freq="Q")
        rows = rows[~rows.isin(drop)]
        bad = np.zeros(len(rows), dtype=bool)
        for i in range(p):  # a lag inside the excluded set is also dropped
            bad |= (rows - (i + 1)).isin(drop)
        rows = rows[~bad]
    y = d.loc[rows].values
    x = np.column_stack([np.ones(len(rows)), lagged.loc[rows].values])
    if np.isnan(y).any() or np.isnan(x).any():
        raise ValueError("missing values inside the VAR estimation window")
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    n = len(VAR_VARS)
    sigma = resid.T @ resid / (len(rows) - x.shape[1])
    A = np.stack([beta[1 + i * n : 1 + (i + 1) * n].T for i in range(p)])
    return VAR(VAR_VARS, beta[0], A, sigma, resid, rows)


def forecast(var: VAR, hist: np.ndarray, h: int) -> np.ndarray:
    """Unconditional forecast (h, n) from the last p observations `hist` (p, n), oldest first."""
    buf = [row for row in hist[-var.p :]]
    out = []
    for _ in range(h):
        y = var.const + sum(var.A[i] @ buf[-1 - i] for i in range(var.p))
        out.append(y)
        buf.append(y)
    return np.array(out)


def ma_coefficients(var: VAR, h: int) -> np.ndarray:
    """Psi_0..Psi_{h-1} (h, n, n): response of y_{t+j} to the shock e_t."""
    n = var.n
    psi = [np.eye(n)]
    for j in range(1, h):
        psi.append(sum(var.A[i] @ psi[j - 1 - i] for i in range(min(var.p, j))))
    return np.array(psi)


def conditional_forecast(
    var: VAR, hist: np.ndarray, h: int, fixed: dict[str, np.ndarray]
) -> np.ndarray:
    """Forecast (h, n) in which each variable in `fixed` follows its given path exactly and the
    others take their expectation given those paths (Gaussian shocks e ~ N(0, sigma)):
    e* = Omega R' (R Omega R')^-1 (target - unconditional), Omega = I_h kron sigma."""
    n = var.n
    base = forecast(var, hist, h)
    psi = ma_coefficients(var, h)
    m = np.zeros((h * n, h * n))  # stacked y deviations = m @ stacked shocks
    for t in range(h):
        for k in range(t + 1):
            m[t * n : (t + 1) * n, k * n : (k + 1) * n] = psi[t - k]
    rows, target = [], []
    for name, path in fixed.items():
        j = var.names.index(name)
        path = np.asarray(path, dtype=float)
        if len(path) != h:
            raise ValueError(f"{name}: path of length {len(path)}, expected {h}")
        for t in range(h):
            rows.append(t * n + j)
            target.append(path[t] - base[t, j])
    if not rows:
        return base
    omega = np.kron(np.eye(h), var.sigma)
    mr = m[rows]
    e = omega @ mr.T @ np.linalg.solve(mr @ omega @ mr.T, np.array(target))
    return base + (m @ e).reshape(h, n)


def simulate_deviations(
    var: VAR, h: int, n_sims: int, rng: np.random.Generator, block: int
) -> np.ndarray:
    """(n_sims, h, n) deviations from a path: residuals (centred) drawn in contiguous blocks of
    `block` quarters (keeps the clustering of crisis shocks), propagated through the VAR
    dynamics from zero initial deviations, without the constant."""
    res = var.resid - var.resid.mean(axis=0)
    t_len = len(res)
    n_blocks = int(np.ceil(h / block))
    starts = rng.integers(0, t_len - block + 1, size=(n_sims, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_sims, -1)[:, :h]
    shocks = res[idx]  # (n_sims, h, n)
    out = np.zeros_like(shocks)
    for t in range(h):
        y = shocks[:, t].copy()
        for i in range(var.p):
            if t - 1 - i >= 0:
                y += out[:, t - 1 - i] @ var.A[i].T
        out[:, t] = y
    return out
