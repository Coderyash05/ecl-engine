"""Quarterly macro paths that drive the lifetime hazard: realised, reverting and long-run.

A path holds, for every calendar quarter (integer index q = 4 x year + quarter - 1):

- z_q: the credit-cycle index for defaults *in* quarter q. Z_s (cycle.py) measures defaults in
  the four quarters after snapshot s, so quarter q is covered by s = q-4 .. q-1; z_q is their
  mean. The same definition is used in estimation (measured Z_s) and projection (satellite Z_s).
- hpi_yoy, mortgage30: national house-price growth (prepayment) and the 30-year mortgage rate
  (refinancing incentive).
- log state HPI: log index per state, so that a loan's property value moves with its state's
  house prices (current LTV channel; RBI Annex 1: collateral value falling with house prices).
  Beyond the last published quarter the state indices grow at the path's national rate.

Path kinds (docs/methodology/pd_lifetime.md):
- realised: published data and measured Z (backtests);
- reverting: published data to the last quarter available, then each driver moves linearly
  to its long-run mean over `revert` quarters and stays there (para 124); Z from the
  satellite. An illustration; the reporting scenarios come from Module 4 (ecl.scenarios);
- long-run: every driver at its long-run mean from the start, Z at the long-run Z (SICR
  origination side: a macro-neutral comparison).

US data (FRED, FHFA); Indian paths plug in through the same roles (Module 12).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Iterable

Q0 = 1998 * 4  # index of 1998Q1
Q_END = 2070 * 4  # paths run to 2069Q4 (30-year horizon from 2039)


def qidx(period: str | pd.Period | pd.Timestamp) -> int:
    """Integer index of a quarter (year x 4 + quarter - 1), used to address path arrays."""
    p = pd.Period(period, freq="Q")
    return p.year * 4 + p.quarter - 1


@dataclass
class MacroPath:
    """One macro scenario path by quarter (index q - Q0): credit-cycle index Z, HPI growth,
    mortgage rate and state log HPI, from history through the forecast and the reversion to
    the long run (paras 47-49)."""

    name: str
    z_q: np.ndarray  # indexed by q - Q0
    hpi_yoy: np.ndarray
    mortgage30: np.ndarray
    log_hpi: np.ndarray  # (n_states, n_quarters)
    states: list[str]
    z_s: np.ndarray | None = None  # Z of the 12-month window after snapshot s (year-1 PIT PD)

    def at(self, arr: np.ndarray, q: np.ndarray) -> np.ndarray:
        """Values of `arr` at quarter indices `q` (clipped to the path)."""
        return arr[np.clip(q - Q0, 0, len(arr) - 1)]

    def state_index(self, codes: Iterable[str]) -> np.ndarray:
        """Row of each state code in log_hpi; -1 if the state has no index (PR, GU, VI)."""
        pos = {s: i for i, s in enumerate(self.states)}
        return np.array([pos.get(c, -1) for c in codes])

    def hpi_ratio(self, state_idx: np.ndarray, q_from: np.ndarray, q_to: np.ndarray) -> np.ndarray:
        """HPI(state, q_to) / HPI(state, q_from); NaN for states without an index."""
        n = self.log_hpi.shape[1]
        a = np.clip(q_from - Q0, 0, n - 1)
        b = np.clip(q_to - Q0, 0, n - 1)
        s = np.where(state_idx < 0, 0, state_idx)
        r = np.exp(self.log_hpi[s, b] - self.log_hpi[s, a])
        return np.where(state_idx < 0, np.nan, r)


def _grid() -> pd.PeriodIndex:
    return pd.period_range(
        pd.Period(year=Q0 // 4, quarter=1, freq="Q"),
        pd.Period(year=Q_END // 4 - 1, quarter=4, freq="Q"),
        freq="Q",
    )


def z_for_quarters(z_s: pd.Series) -> pd.Series:
    """z_q(q) = mean of Z_s for s = q-4 .. q-1 (the snapshots whose window contains q)."""
    return pd.concat([z_s.shift(k) for k in range(1, 5)], axis=1).mean(axis=1, skipna=True)


def state_log_hpi(hpi_state: pd.DataFrame, national_yoy: pd.Series) -> tuple[np.ndarray, list]:
    """Log state indices on the path grid; after each state's last quarter, grow at the
    national path rate (quarterly factor (1 + yoy/100)^(1/4))."""
    grid = _grid()
    g = np.log1p(national_yoy.reindex(grid).ffill().fillna(0).values / 100) / 4
    states = sorted(hpi_state.state.unique())
    out = np.full((len(states), len(grid)), np.nan)
    for i, s in enumerate(states):
        h = hpi_state[hpi_state.state == s]
        idx = pd.PeriodIndex(
            [pd.Period(year=y, quarter=q, freq="Q") for y, q in zip(h.yr, h.qtr, strict=True)]
        )
        v = pd.Series(np.log(h.hpi.values), index=idx).reindex(grid)
        last = v.last_valid_index()
        arr = v.values.copy()
        j = grid.get_loc(last)
        arr[j + 1 :] = arr[j] + np.cumsum(g[j + 1 :])
        first = v.first_valid_index()
        arr[: grid.get_loc(first)] = arr[grid.get_loc(first)]
        out[i] = arr
    return out, states


def satellite_z(params: dict, hpi_yoy: pd.Series, gdp_yoy: pd.Series) -> pd.Series:
    """Z_s from the window-aligned satellite: const + b_hpi x mean(hpi_yoy, s+1..s+4) +
    b_gdp x mean(gdp_yoy, s+1..s+4)."""

    def wmean(x: pd.Series) -> pd.Series:
        return pd.concat([x.shift(-k) for k in range(1, 5)], axis=1).mean(axis=1, skipna=False)

    return (
        params["const"]
        + params["hpi_yoy[W]"] * wmean(hpi_yoy)
        + params["gdp_yoy[W]"] * wmean(gdp_yoy)
    )


def revert(x: pd.Series, target: float, start: pd.Period, quarters: int) -> pd.Series:
    """Keep x up to `start`, then move linearly to `target` over `quarters`, then flat."""
    grid = _grid()
    out = x.reindex(grid).copy()
    x0 = out.loc[start]
    after = grid[grid > start]
    steps = np.arange(1, len(after) + 1)
    out.loc[after] = x0 + (target - x0) * np.minimum(steps / quarters, 1.0)
    return out


def realised_path(macro: pd.DataFrame, z_measured: pd.Series, hpi_state: pd.DataFrame) -> MacroPath:
    """Path of the realised history: measured Z, actual HPI growth and state indices (backtests
    and crisis replays)."""
    grid = _grid()
    z_q = z_for_quarters(z_measured.reindex(grid))
    log_hpi, states = state_log_hpi(hpi_state, macro.hpi_yoy)
    return MacroPath(
        "realised",
        z_q.values,
        macro.hpi_yoy.reindex(grid).values,
        macro.mortgage30.reindex(grid).values,
        log_hpi,
        states,
    )


def reverting_path(
    macro: pd.DataFrame,
    z_measured: pd.Series,
    hpi_state: pd.DataFrame,
    params: dict,
    lr: dict,
    report_q: pd.Period,
    quarters: int = 8,
) -> MacroPath:
    """Published data to the last available quarter of each driver, then linear reversion to
    the long-run means. Measured Z_s is used only for windows complete at the reporting date
    (s <= report_q - 4: no look-ahead); the satellite gives Z_s after that."""
    grid = _grid()
    cols = {}
    for c in ["hpi_yoy", "gdp_yoy", "mortgage30"]:
        x = macro[c].dropna()
        cols[c] = revert(x, lr[c], x.index.max(), quarters)
    z_sat = satellite_z(params, cols["hpi_yoy"], cols["gdp_yoy"])
    z_s = z_measured.reindex(grid).where(grid <= report_q - 4, z_sat)
    log_hpi, states = state_log_hpi(hpi_state, cols["hpi_yoy"])
    return MacroPath(
        "reverting",
        z_for_quarters(z_s).values,
        cols["hpi_yoy"].values,
        cols["mortgage30"].values,
        log_hpi,
        states,
        z_s=z_s.values,
    )


def long_run_path(lr: dict, z_lr: float, states: list[str]) -> MacroPath:
    """Every driver at its long-run mean; state indices all grow at the long-run rate."""
    n = len(_grid())
    g = np.log1p(lr["hpi_yoy"] / 100) / 4
    log_hpi = np.tile(np.arange(n) * g, (len(states), 1))
    return MacroPath(
        "long-run",
        np.full(n, z_lr),
        np.full(n, lr["hpi_yoy"]),
        np.full(n, lr["mortgage30"]),
        log_hpi,
        states,
        z_s=np.full(n, z_lr),
    )
