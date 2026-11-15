"""State house-price paths from a national path, by state betas.

What: for each state s, quarterly log growth of the state index is regressed on national
quarterly log growth: g_s,t = alpha_s + beta_s x g_nat,t + u_s,t (OLS, FHFA All-Transactions
indices, design window 2000-2016). In a scenario, beyond the last quarter observed at the
reporting date, each state grows at beta_s x the national growth; the intercepts are dropped
so the national path is the single scenario input.

Why (RBI para 124: variables "tailored to ... geography"; Annex 1: collateral value falling with
house prices): the hazard sees house prices through each loan's current LTV. With equal growth
(every state = national), a national scenario carries no regional stress: in 2007-11 the
national FHFA index fell ~19% while Nevada fell ~79 log points. Sand states have betas of
2.1-2.5, Texas ~0.4 (docs/methodology/scenarios.md).

US data (FHFA); the Indian adapter uses RBI city indices against the all-India index.
"""

import numpy as np
import pandas as pd


def state_wide(hpi_state: pd.DataFrame) -> pd.DataFrame:
    """Quarter x state table of log state indices from the long file (state, yr, qtr, hpi)."""
    per = pd.PeriodIndex(
        [
            pd.Period(year=y, quarter=q, freq="Q")
            for y, q in zip(hpi_state.yr, hpi_state.qtr, strict=True)
        ]
    )
    w = pd.DataFrame(
        {"per": per, "state": hpi_state.state.values, "log_hpi": np.log(hpi_state.hpi.values)}
    )
    return w.pivot(index="per", columns="state", values="log_hpi").sort_index()


def fit_betas(log_state: pd.DataFrame, log_nat: pd.Series, start: str, end: str) -> pd.DataFrame:
    """alpha, beta, R^2 and number of quarters per state (quarterly log growth, OLS)."""
    gs = log_state.diff().loc[start:end]
    gn = log_nat.diff().reindex(gs.index)
    rows = {}
    for st in gs.columns:
        ok = gs[st].notna() & gn.notna()
        x, y = gn[ok].values, gs[st][ok].values
        beta, alpha = np.polyfit(x, y, 1)
        r2 = float(np.corrcoef(x, y)[0, 1] ** 2)
        rows[st] = {"alpha": alpha, "beta": beta, "r2": r2, "quarters": int(ok.sum())}
    return pd.DataFrame(rows).T


def project_states(
    log_state: pd.DataFrame, log_nat_path: pd.Series, betas: pd.Series, cut: pd.Period
) -> pd.DataFrame:
    """State log indices on the index of `log_nat_path`: observed up to `cut` (no data after the
    reporting quarter is used), then log growth = beta x national log growth. Quarters before a
    state's first observation hold its first value."""
    idx = log_nat_path.index
    g_nat = log_nat_path.diff().fillna(0.0)
    obs = log_state.loc[:cut].reindex(idx)
    out = {}
    for st in log_state.columns:
        v = obs[st].copy()
        last = v.last_valid_index()
        if last is None:
            out[st] = v
            continue
        after = idx > last
        v[after] = v[last] + (betas[st] * g_nat[after]).cumsum()
        first = v.first_valid_index()
        v[idx < first] = v[first]
        out[st] = v
    return pd.DataFrame(out, index=idx)
