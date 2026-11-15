"""Crisis replay R1-R3 and the CO-3 calibration (docs/methodology/scenarios.md; RBI paras 47, 131).

Loans of the 2005-2007 vintages (dev_holdout: not used in fitting) are projected from their first
observed month with the lifetime hazard alone (as in the Module 3 vintage backtest: no 12-month
splice), and the predicted cumulative default after 3 and 5 years is compared with the actual
(Aalen-Johansen). The replay is decomposed so that each link of the scenario machinery is tested:

| Step | Z | State house prices | Tests |
|---|---|---|---|
| R1 | measured Z | actual | the hazard model |
| R2 | satellite Z on actual HPI / GDP | actual | + the satellite (what a scenario uses) |
| R3 | satellite Z | national actual x state betas (no intercept), from the cut | + the state mapping |

CO-3 is calibrated on R3 (how a downside is produced): M such that the pooled 2006-07 predicted
5-year cumulative default equals the actual, applied in quarters with Z below its long-run value.
The 2005 vintage is held out of the calibration. A bootstrap over loans gives M's interval.

US data (Freddie Mac loans, FRED, FHFA); not Indian risk estimates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ecl.lifetime.hazard import cumulative, project
from ecl.lifetime.paths import MacroPath, _grid, satellite_z, z_for_quarters
from ecl.lifetime.portfolio import aalen_johansen, odds_scale_keep_prepay
from ecl.scenarios.overlay import multiplier, stressed
from ecl.scenarios.state_paths import project_states

if TYPE_CHECKING:
    from ecl.lifetime.hazard import HazardModel, Loans


def satellite_path(realised: MacroPath, macro: pd.DataFrame, params: dict) -> MacroPath:
    """R2: the realised path with Z replaced by the satellite on actual HPI and GDP growth."""
    grid = _grid()
    z_s = satellite_z(params, macro.hpi_yoy.reindex(grid), macro.gdp_yoy.reindex(grid))
    z_s = z_s.ffill().bfill()
    return MacroPath(
        "R2 satellite Z",
        z_for_quarters(z_s).ffill().bfill().values,
        realised.hpi_yoy,
        realised.mortgage30,
        realised.log_hpi,
        realised.states,
        z_s=z_s.values,
    )


def beta_state_path(
    r2: MacroPath, log_state: pd.DataFrame, macro: pd.DataFrame, betas: pd.Series, cut: str
) -> MacroPath:
    """R3: R2 with state indices observed to `cut`, then beta x actual national log growth."""
    grid = _grid()
    nat = np.log(macro.hpi).reindex(grid).ffill().bfill()
    st = project_states(log_state, nat, betas, pd.Period(cut, freq="Q"))
    st = st.reindex(columns=r2.states).ffill().bfill()
    return MacroPath(
        "R3 satellite Z + beta states",
        r2.z_q,
        r2.hpi_yoy,
        r2.mortgage30,
        st.T.values,
        r2.states,
        z_s=r2.z_s,
    )


@dataclass
class Replay:
    """Projected hazards of the replay loans on one path, 20 quarters (5 years)."""

    h_d: np.ndarray
    h_p: np.ndarray
    mask: np.ndarray  # stressed quarters (z_q < Z_lr)


def run_path(
    model: HazardModel, loans: Loans, first_q: np.ndarray, path: MacroPath, k: int, z_lr: float
) -> Replay:
    """Default and prepayment hazards of `loans` over `k` quarters from their first quarter on
    `path`, with the stressed-quarter mask used by the CO-3 multiplier."""
    h_d, h_p = project(model, loans, path, k)
    q = first_q[:, None] + np.arange(1, k + 1)[None, :]
    return Replay(h_d, h_p, stressed(path, q, z_lr))


def cum_default(r: Replay, m: float | np.ndarray = 1.0) -> np.ndarray:
    """(n, k) cumulative default with the odds multiplier M in stressed quarters."""
    hd = odds_scale_keep_prepay(r.h_d, r.h_p, multiplier(r.mask, m, 1.0))
    return cumulative(np.minimum(hd, 1 - r.h_p), r.h_p)[1]


def aj_default(
    n_quarters: np.ndarray, last_event: np.ndarray, k: int, w: np.ndarray | None = None
) -> float:
    """Aalen-Johansen cumulative default after k quarters, with optional loan weights
    (bootstrap counts)."""
    w = np.ones(len(n_quarters)) if w is None else w
    nq = np.minimum(n_quarters, k + 1)
    at_risk = np.cumsum(np.bincount(nq, w, minlength=k + 2)[::-1])[::-1]
    d = np.bincount(nq, w * (last_event == 1), minlength=k + 2)
    e = np.bincount(nq, w * (last_event > 0), minlength=k + 2)
    s, cd = 1.0, 0.0
    for j in range(1, k + 1):
        if at_risk[j] <= 0:
            break
        cd += s * d[j] / at_risk[j]
        s *= 1 - e[j] / at_risk[j]
    return float(cd)


def replay_table(
    paths: dict[str, Replay],
    orig: pd.DataFrame,
    groups: dict[str, np.ndarray],
    years: list[int],
    m: float | np.ndarray | None = None,
) -> pd.DataFrame:
    """Actual vs predicted cumulative default by group, horizon and replay step; with `m`, an
    extra column for R3 with the calibrated multiplier."""
    rows = []
    for g, ii in groups.items():
        for y in years:
            k = 4 * y
            act = aalen_johansen(orig.n_quarters.values[ii], orig.last_event.values[ii], k)
            if len(act) < k:
                continue
            row = {"group": g, "years": y, "loans": len(ii), "actual": act.actual_default.iloc[-1]}
            for name, r in paths.items():
                row[f"pred_{name}"] = cum_default(r)[ii, k - 1].mean()
                row[f"actual_to_{name}"] = row["actual"] / row[f"pred_{name}"]
            if m is not None:
                mm = m if np.ndim(m) == 0 else np.asarray(m)[ii]
                r3 = paths["R3"]
                sub = Replay(r3.h_d[ii], r3.h_p[ii], r3.mask[ii])
                row["pred_R3_CO3"] = cum_default(sub, mm)[:, k - 1].mean()
                row["actual_to_R3_CO3"] = row["actual"] / row["pred_R3_CO3"]
            rows.append(row)
    return pd.DataFrame(rows)


def m_grid_predictions(r: Replay, k: int, grid: np.ndarray) -> np.ndarray:
    """(n, len(grid)) per-loan cumulative default after k quarters at each M of the grid."""
    return np.column_stack([cum_default(Replay(r.h_d, r.h_p, r.mask), m)[:, k - 1] for m in grid])


def solve_on_grid(
    pred: np.ndarray, grid: np.ndarray, target: float, w: np.ndarray | None = None
) -> float:
    """M on the grid (log-linear interpolation) where the weighted mean prediction = target."""
    mean = pred.mean(axis=0) if w is None else (w @ pred) / w.sum()
    if target <= mean[0]:
        return float(grid[0])
    if target >= mean[-1]:
        return float(grid[-1])
    return float(np.exp(np.interp(target, mean, np.log(grid))))


def calibrate(
    r3: Replay,
    orig: pd.DataFrame,
    ii: np.ndarray,
    k: int,
    grid: np.ndarray,
    n_boot: int,
    seed: int,
    level: float,
) -> dict:
    """M for loans ii (pooled) at k quarters and its bootstrap interval over loans."""
    sub = Replay(r3.h_d[ii], r3.h_p[ii], r3.mask[ii])
    pred = m_grid_predictions(sub, k, grid)
    nq, ev = orig.n_quarters.values[ii], orig.last_event.values[ii]
    m_hat = solve_on_grid(pred, grid, aj_default(nq, ev, k))
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        w = np.bincount(rng.integers(0, len(ii), len(ii)), minlength=len(ii)).astype(float)
        boots.append(solve_on_grid(pred, grid, aj_default(nq, ev, k, w), w))
    a = (1 - level) / 2
    lo, hi = np.quantile(boots, [a, 1 - a])
    return {"m": m_hat, "lo": float(lo), "hi": float(hi), "loans": len(ii), "boot": n_boot}
