"""Indian macro scenarios for the SYNTHETIC book (Module 12; paras 47-49, 124, Annex 4 Table 5).

Method (mirrors Module 4 where the Indian data allow it):
- a VAR(1) on three quarterly series - all-India HPI log growth (spliced RBI HPI, QoQ, per
  cent), real GDP YoY growth (chained across NAS bases) and CPI YoY inflation (linked CPI) -
  estimated on the VAR window without the COVID quarters (they would dominate the residuals:
  GDP YoY -23% / +23% in 2020Q2 / 2021Q2); 10,000 paths of 12 quarters by block bootstrap of the
  joint residuals, then linear reversion to the window means over 8 quarters (paras 49, 124);
- the severity index is the US satellite Z evaluated on Indian deviations from the Indian
  means: Z = Z_lr + b_HPI (HPI YoY - mean) + b_GDP (GDP YoY - mean) (US pdpit-0.2.1
  coefficients; Indian levels differ, so only deviations enter);
- paths are ranked by their 12-quarter mean Z and cut 20 / 60 / 20; each scenario is the mean
  path of its region; weights = region shares (unbiased, para 47); CPI is reported (Table 5),
  it moves no PD;
- repo rate: base flat at the rate in force on the reporting date; downside / upside shift by
  the 80th / 20th percentile of historical 4-quarter repo changes, ramped in over 4 quarters,
  held to the end of the horizon, then reverted to base over the reversion quarters.
SYNTHETIC context: real RBI / MoSPI series feeding a synthetic book; not Indian risk estimates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

VARS = ["hpi_g", "gdp_yoy", "cpi_yoy"]


def macro_frame(hpi: pd.Series, gdp_yoy: pd.Series, cpi: pd.Series) -> pd.DataFrame:
    """Quarterly frame: HPI QoQ log growth (%), GDP YoY (%), CPI YoY (%, quarterly mean index)."""
    hq = (np.log(hpi.dropna()).diff() * 100).rename("hpi_g")
    cq = cpi.groupby(cpi.index.asfreq("Q")).mean()
    cq = cq[cpi.groupby(cpi.index.asfreq("Q")).size() == 3]  # complete quarters only
    cy = (cq.pct_change(4) * 100).rename("cpi_yoy")
    return pd.concat([hq, gdp_yoy.rename("gdp_yoy"), cy], axis=1)


def var1(df: pd.DataFrame, use: pd.Series) -> dict:
    """OLS VAR(1) y_t = c + A y_{t-1} + e_t on pairs (t-1, t) with both quarters in `use`."""
    y, x = df.values[1:], df.values[:-1]
    ok = (use.values[1:] & use.values[:-1]) & ~np.isnan(y).any(1) & ~np.isnan(x).any(1)
    X = np.column_stack([np.ones(ok.sum()), x[ok]])
    B = np.linalg.lstsq(X, y[ok], rcond=None)[0]
    resid = y[ok] - X @ B
    return {"c": B[0], "A": B[1:].T, "resid": resid - resid.mean(0), "n": int(ok.sum())}


def simulate(var: dict, last: np.ndarray, mu: np.ndarray, cfg: dict, seed: int) -> np.ndarray:
    """(n, T, k) paths: VAR(1) with block-bootstrapped joint residuals for h quarters, then linear
    reversion to `mu` over `rev` quarters, then flat (4 extra quarters keep YoY defined)."""
    sc = cfg["scenarios"]
    n, h, rev, block = (
        sc["n_sims"],
        sc["horizon_quarters"],
        sc["reversion_quarters"],
        sc["block_quarters"],
    )
    e = var["resid"]
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(h / block))
    starts = rng.integers(0, len(e) - block + 1, size=(n, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n, nb * block)[:, :h]
    shocks = e[idx]  # (n, h, k)
    T = h + rev + 4
    out = np.empty((n, T, len(mu)))
    cur = np.repeat(last[None, :], n, axis=0)
    for t in range(h):
        cur = var["c"] + cur @ var["A"].T + shocks[:, t]
        out[:, t] = cur
    for j in range(rev):
        w = (j + 1) / rev
        out[:, h + j] = (1 - w) * out[:, h - 1] + w * mu
    out[:, h + rev :] = mu
    return out


def yoy_from_qoq(hist_g: np.ndarray, paths: np.ndarray) -> np.ndarray:
    """YoY growth (%) of simulated QoQ log growth, using the last 3 historical quarters."""
    full = np.hstack([np.repeat(hist_g[None, -3:], len(paths), axis=0), paths])
    s = np.array([full[:, t : t + 4].sum(1) for t in range(full.shape[1] - 3)]).T
    return (np.exp(s / 100) - 1) * 100


def z_index(
    hpi_yoy: ArrayLike,
    mu_hpi: float,
    sat: dict,
    z_lr: float,
    elasticity: float = 1.0,
    gdp_yoy: ArrayLike | None = None,
    mu_gdp: float = 0.0,
) -> np.ndarray:
    """Z from Indian deviations from their means (US satellite coefficients)."""
    z = z_lr + elasticity * sat["hpi_yoy[W]"] * (np.asarray(hpi_yoy) - mu_hpi)
    if gdp_yoy is not None:
        z = z + elasticity * sat["gdp_yoy[W]"] * (np.asarray(gdp_yoy) - mu_gdp)
    return z


def build(
    macro: pd.DataFrame,
    repo: pd.Series,
    repo_now: float,
    as_of: str,
    cfg: dict,
    sat: dict,
    z_lr: float,
    elasticity: float = 1.0,
) -> dict:
    """Scenario paths (quarterly) and Table 5 for India. `macro` = macro_frame(...)."""
    sc = cfg["scenarios"]
    q0 = pd.Period(pd.Timestamp(as_of), freq="Q")
    w0, w1 = (pd.Period(x, freq="Q") for x in sc["var_window"])
    x0, x1 = (pd.Period(x, freq="Q") for x in sc["exclude_quarters"])
    df = macro.loc[w0 : min(w1, q0), VARS].dropna()
    use = pd.Series(~((df.index >= x0) & (df.index <= x1)), index=df.index)
    var = var1(df, use)
    mu = df[use].mean().values
    mu_hpi_yoy = (np.exp(4 * mu[0] / 100) - 1) * 100
    h, rev = sc["horizon_quarters"], sc["reversion_quarters"]
    paths = simulate(var, df.values[-1], mu, cfg, cfg["seed"])
    hpi_yoy = yoy_from_qoq(df.hpi_g.values, paths[:, :, 0])
    z = z_index(hpi_yoy, mu_hpi_yoy, sat, z_lr, elasticity, paths[:, :, 1], mu[1])
    order = np.argsort(z[:, :h].mean(axis=1))
    sh = sc["shares"]
    n_d, n_u = int(sh["downside"] * len(order)), int(sh["upside"] * len(order))
    regions = {
        "downside": order[:n_d],
        "central": order[n_d : len(order) - n_u],
        "upside": order[len(order) - n_u :],
    }
    rp = sc["repo"]
    r = repo[(repo.index.year >= rp["shock_window"][0]) & (repo.index <= q0)]
    d4 = (r - r.shift(4)).dropna()
    shift = {
        "downside": float(np.percentile(d4, rp["downside_percentile"])),
        "central": 0.0,
        "upside": float(np.percentile(d4, rp["upside_percentile"])),
    }
    quarters = pd.period_range(q0 + 1, periods=h + rev, freq="Q")
    rows = []
    k = np.arange(1, h + rev + 1)
    for name, idx in regions.items():
        ramp = np.minimum(k / rp["ramp_quarters"], 1.0)
        back = np.clip((k - h) / rev, 0, 1)
        rows.append(
            pd.DataFrame(
                {
                    "quarter": quarters.astype(str),
                    "scenario": name,
                    "weight": sh[name],
                    "hpi_g": paths[idx, : h + rev, 0].mean(0),
                    "hpi_yoy": hpi_yoy[idx, : h + rev].mean(0),
                    "gdp_yoy": paths[idx, : h + rev, 1].mean(0),
                    "cpi_yoy": paths[idx, : h + rev, 2].mean(0),
                    "z": z[idx, : h + rev].mean(0),
                    "repo": repo_now + shift[name] * ramp * (1 - back),
                }
            )
        )
    paths_df = pd.concat(rows, ignore_index=True)

    def five_year(p: pd.DataFrame, col: str, lr: float) -> float:
        v = np.r_[p[col].values, np.full(max(0, 20 - len(p)), lr)][:20]
        return float(v.mean())

    t5 = []
    for name in regions:
        p = paths_df[paths_df.scenario == name]
        g5 = np.r_[p.hpi_g.values, np.full(max(0, 20 - len(p)), mu[0])][:20]
        t5.append(
            {
                "scenario": name,
                "weight": sh[name],
                "Real GDP growth 1-year forward (%)": float(p.gdp_yoy.iloc[3]),
                "Real GDP growth 5-year average (%)": five_year(p, "gdp_yoy", mu[1]),
                "HPI growth 1-year forward (%)": float(p.hpi_yoy.iloc[3]),
                "HPI growth 5-year average (%)": float((np.exp(g5.sum() / 100 / 5) - 1) * 100),
                "CPI inflation 1-year forward (%)": float(p.cpi_yoy.iloc[3]),
                "CPI inflation 5-year average (%)": five_year(p, "cpi_yoy", mu[2]),
                "Repo rate 1-year forward (%)": float(p.repo.iloc[3]),
                "Repo rate 5-year average (%)": five_year(p, "repo", repo_now),
                "Z 12-quarter mean": float(p.z.iloc[:h].mean()),
            }
        )
    return {
        "paths": paths_df,
        "table5": pd.DataFrame(t5),
        "var": {
            "window": [str(df.index.min()), str(df.index.max())],
            "excluded": [str(x0), str(x1)],
            "pairs_used": var["n"],
            "means": dict(zip(VARS, mu.round(3).tolist(), strict=True)),
            "hpi_yoy_mean": float(mu_hpi_yoy),
            "A": var["A"].round(3).tolist(),
        },
        "repo_shift_pp": shift,
        "repo_now": repo_now,
    }
