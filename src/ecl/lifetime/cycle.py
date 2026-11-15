"""Credit-cycle index Z_t and the Vasicek point-in-time (PIT) conversion of the TTC PD.

What: v1.2.0 gives a through-the-cycle 12-month PD p (average over 2000-2016, crisis included).
The Vasicek single-factor model turns it into the PD conditional on the state of the economy:

    PD_PIT(p, Z) = Phi( (Phi^-1(p) - sqrt(rho) * b * Z) / sqrt(1 - rho) )

Z > 0 is a benign year, Z < 0 a stressed one; b is a loading (1 for every loan unless group
loadings are adopted; docs/methodology/pd_point_in_time.md). Averaged over Z ~ N(0, 1), PD_PIT equals p, so the TTC
PD is the cycle average and Z says where in the cycle a quarter is.

Why: RBI paras 47-49 require PDs that reflect current and forecast conditions; the TTC PD
over-predicts benign years by design. Z_t is *measured* each quarter by maximum likelihood from
the loans' realised 12-month defaults (the Z that best explains them given each loan's p); a
satellite regression (satellite.py) then links Z_t to macro drivers so scenarios can move it.

rho (asset correlation) mainly decides how a given shift is spread across PD levels: the same
Z moves a 0.5% PD proportionally much more than a 60% PD. It is identified from that
cross-section (profile likelihood with Z_t free in every quarter) and, separately, from the
requirement that Z_t has unit variance over the development cycle.

Inputs are cells (quarter x PD bin x group) with n loans, d defaults and the mean TTC PD:
aggregating loans with almost equal p loses nothing and keeps the fit fast.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike
from scipy.optimize import minimize_scalar
from scipy.stats import norm

if TYPE_CHECKING:
    from collections.abc import Iterable

Z_BOUND = 8.0
EPS = 1e-12
CHI2_1DF_95 = 3.84  # 95% critical value of chi-squared(1): likelihood-ratio interval


def vasicek_pd(p: ArrayLike, z: ArrayLike, rho: float, b: ArrayLike = 1.0) -> np.ndarray:
    """PD conditional on the systematic factor z (z > 0 benign)."""
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return norm.cdf((norm.ppf(p) - np.sqrt(rho) * np.asarray(b) * z) / np.sqrt(1 - rho))


def _loglik(
    probit_p: np.ndarray, n: np.ndarray, d: np.ndarray, z: float, rho: float, b: ArrayLike
) -> float:
    q = np.clip(norm.cdf((probit_p - np.sqrt(rho) * b * z) / np.sqrt(1 - rho)), EPS, 1 - EPS)
    return float(np.sum(d * np.log(q) + (n - d) * np.log1p(-q)))


def fit_z(
    p: ArrayLike, n: ArrayLike, d: ArrayLike, rho: float, b: ArrayLike = 1.0
) -> tuple[float, float]:
    """Maximum-likelihood Z for one quarter: the systematic shift that best explains the
    realised defaults d out of n loans with TTC PDs p. Returns (z, log-likelihood)."""
    probit_p = norm.ppf(np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS))
    n, d, b = (
        np.asarray(n, float),
        np.asarray(d, float),
        np.broadcast_to(np.asarray(b, float), probit_p.shape),
    )
    res = minimize_scalar(
        lambda z: -_loglik(probit_p, n, d, z, rho, b),
        bounds=(-Z_BOUND, Z_BOUND),
        method="bounded",
        options={"xatol": 1e-7},
    )
    return float(res.x), float(-res.fun)


def z_series(
    cells: pd.DataFrame,
    rho: float,
    n_col: str = "n",
    d_col: str = "d",
    p_col: str = "p",
    b_col: str | None = None,
) -> pd.DataFrame:
    """Z_t for every quarter (`obs_date`) of a cell table, with actual and fitted default rates.
    Cells with n = 0 are ignored."""
    rows = []
    for t, g in cells[cells[n_col] > 0].groupby("obs_date", sort=True):
        b = g[b_col].values if b_col else 1.0
        z, ll = fit_z(g[p_col].values, g[n_col].values, g[d_col].values, rho, b)
        n = g[n_col].sum()
        rows.append(
            {
                "obs_date": t,
                "z": z,
                "loglik": ll,
                "n": n,
                "defaults": g[d_col].sum(),
                "actual_rate": g[d_col].sum() / n,
                "ttc_pd": np.sum(g[n_col] * g[p_col]) / n,
                "pit_pd": np.sum(g[n_col] * vasicek_pd(g[p_col], z, rho, b)) / n,
            }
        )
    return pd.DataFrame(rows)


@dataclass
class RhoProfile:
    """Profile likelihood of the asset correlation rho: the table over the grid, the maximum and
    its likelihood-ratio interval."""

    table: pd.DataFrame  # rho, loglik, z_mean, z_var (over the quarters given)
    rho_hat: float
    ci: tuple[float, float]  # likelihood-ratio 95% interval (chi2(1) = 3.84)


def profile_rho(
    cells: pd.DataFrame, grid: Iterable[float], var_quarters: Iterable | None = None
) -> RhoProfile:
    """Profile log-likelihood of rho with Z_t free in every quarter of `cells`. Also reports
    the mean and variance of Z_t over `var_quarters` (default: all) for the unit-variance check."""
    rows = []
    for rho in grid:
        zs = z_series(cells, rho)
        sel = zs if var_quarters is None else zs[zs.obs_date.isin(var_quarters)]
        rows.append(
            {
                "rho": rho,
                "loglik": zs.loglik.sum(),
                "z_mean": sel.z.mean(),
                "z_var": sel.z.var(ddof=1),
            }
        )
    t = pd.DataFrame(rows)
    best = t.loc[t.loglik.idxmax()]
    inside = t[2 * (best.loglik - t.loglik) <= CHI2_1DF_95]
    return RhoProfile(t, float(best.rho), (float(inside.rho.min()), float(inside.rho.max())))


def rho_unit_variance(table: pd.DataFrame) -> float:
    """Route 2: the rho at which Var(Z_t) = 1 (linear interpolation on the profile grid);
    NaN if the variance does not cross 1 on the grid."""
    t = table.sort_values("rho")
    v = t.z_var.values - 1
    cross = np.where(np.sign(v[:-1]) != np.sign(v[1:]))[0]
    if len(cross) == 0:
        return float("nan")
    i = cross[0]
    r0, r1 = t.rho.values[i], t.rho.values[i + 1]
    return float(r0 + (r1 - r0) * (0 - v[i]) / (v[i + 1] - v[i]))


def predicted_by_group(
    cells: pd.DataFrame, z: pd.Series, rho: float, group_col: str, b_col: str | None = None
) -> pd.DataFrame:
    """Actual vs PIT-predicted default rate per quarter and group, for a given Z per quarter
    (`z` indexed by obs_date)."""
    c = cells[cells.n > 0].copy()
    zq = c.obs_date.map(z)
    b = c[b_col].values if b_col else 1.0
    c["pred_d"] = c.n * vasicek_pd(c.p, zq.values, rho, b)
    g = (
        c.groupby(["obs_date", group_col])
        .agg(n=("n", "sum"), defaults=("d", "sum"), pred=("pred_d", "sum"))
        .reset_index()
    )
    g["actual_rate"] = g.defaults / g.n
    g["pred_rate"] = g.pred / g.n
    return g.drop(columns="pred")
