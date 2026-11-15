"""Severity checks for upside and downside against history (bands and windows from config).

What (model-owner decision 2026-11-14, docs/methodology/scenarios.md; config/scenarios.yaml
`severity_check`):
- **Primary: distance from the base.** A scenario's 1-year-forward HPI and GDP growth minus the
  base's, placed in the distribution of historical **4-quarter forecast errors** (actual -
  forecast):
  - GDP: errors of the SPF median (the source of the base), surveys whose 4 quarters ahead were
    observed by the reporting date;
  - HPI: no published forecast exists, so the errors of the scenario VAR's own 4-quarter forecast
    (coefficients of the estimation window, applied to every origin);
  - VAR GDP errors as a cross-check;
  - **the severity index itself** (`z_index_check`): the satellite-weighted sum of the HPI and GDP
    deviations, against the same weighting of the VAR errors. The regions are cut on this index,
    so it is the statistic the 20/60/20 partition controls; a single variable is diluted towards
    the median whenever the other variable carries part of the ranking.
  Bands: downside between the 5th and 20th percentile of the errors, upside 80th-95th.
- **Secondary: levels.** The 1-year-forward growth itself among historical 4-quarter outcomes
  from 1991 (the low-inflation period; nominal house-price growth before 1991 sits higher).
- Windows touching the excluded quarters (COVID) are dropped from every reference: those shocks
  are not in the VAR's residual pool either.
- Every reference uses only 4-quarter windows ending on or before the reporting quarter.

Why (paras 47-49): scenarios must be plausible, neither a stress test nor a near-copy of the base.
Distance from the base measures what the partition controls (the width of the scenarios around
the consensus); levels mix that width with the consensus itself (with a 3% HPI base, the central
scenario alone sat at the 26th percentile of 1976-2025 nominal history).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ecl.lifetime.macro import gdp_yoy
from ecl.scenarios.var import ANNUALISE, VAR, forecast


def percentile_of(value: float, history: pd.Series) -> float:
    """Empirical percentile (0-100) of `value` within `history`."""
    return float(100 * (np.asarray(history) <= value).mean())


def _band(scen: str, bands: dict) -> tuple:
    return tuple(bands[scen]) if scen in bands else (None, None)


def _window_ok(t: pd.Period, exclude: pd.PeriodIndex) -> bool:
    return not pd.period_range(t + 1, t + 4, freq="Q").isin(exclude).any()


def historical_one_year(macro: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """For every quarter t in start..end: HPI growth t -> t+4 and GDP growth over t+1..t+4
    (the Table 5 '1 year forward' statistic on history)."""
    lh = np.log(macro.hpi)
    g = gdp_yoy(macro.gdp_qoq_saar)
    out = pd.DataFrame({"hpi": 100 * (np.exp(lh.shift(-4) - lh) - 1), "gdp": g.shift(-4)})
    return out.loc[start:end].dropna()


def level_reference(
    macro: pd.DataFrame, start: str, report_q: pd.Period, exclude: pd.PeriodIndex
) -> pd.DataFrame:
    """Historical 1-year-forward outcomes, origins start..report_q-4, excluded windows dropped."""
    h = historical_one_year(macro, start, str(report_q - 4))
    return h[[_window_ok(t, exclude) for t in h.index]]


def spf_gdp_errors(
    drgdp: pd.DataFrame,
    macro: pd.DataFrame,
    start: str,
    report_q: pd.Period,
    exclude: pd.PeriodIndex,
) -> pd.Series:
    """SPF median 4-quarter GDP growth errors (actual - forecast), surveys start..report_q-4.
    Forecast = compounded drgdp3..6 (quarters 1-4 after the survey); actual = FRED history."""
    act = gdp_yoy(macro.gdp_qoq_saar)
    out = {}
    for t in drgdp.loc[start : report_q - 4].index:
        g = drgdp.loc[t, [f"drgdp{k}" for k in range(3, 7)]]
        if g.isna().any() or not _window_ok(t, exclude) or pd.isna(act.get(t + 4)):
            continue
        out[t] = act[t + 4] - 100 * (np.prod((1 + g.values / 100) ** 0.25) - 1)
    return pd.Series(out, dtype=float)


def var_errors(
    var: VAR, data: pd.DataFrame, start: str, report_q: pd.Period, exclude: pd.PeriodIndex
) -> pd.DataFrame:
    """4-quarter forecast errors of the VAR (actual - forecast), HPI and GDP growth (%),
    forecast origins start..report_q-4."""
    rows = {}
    for t in data.loc[start : report_q - 4].index:
        hist = data.loc[t - (var.p - 1) : t, var.names].values
        fut = data.loc[t + 1 : t + 4, var.names].values
        if np.isnan(hist).any() or np.isnan(fut).any() or not _window_ok(t, exclude):
            continue
        fc = forecast(var, hist, 4)
        rows[t] = {
            "hpi": 100 * (np.exp(fut[:, 0].sum() / ANNUALISE) - np.exp(fc[:, 0].sum() / ANNUALISE)),
            "gdp": 100
            * (np.prod((1 + fut[:, 1] / 100) ** 0.25) - np.prod((1 + fc[:, 1] / 100) ** 0.25)),
        }
    return pd.DataFrame(rows).T


def _row(scen: str, var: str, ref: str, dev: float, err: np.ndarray, bands: dict) -> dict:
    lo, hi = _band(scen, bands)
    pct = percentile_of(dev, err)
    q = np.percentile(err, [5, 20, 80, 95])
    return {
        "scenario": scen,
        "variable": var,
        "reference": ref,
        "deviation_from_base": dev,
        "historical_percentile": pct,
        "reference_n": len(err),
        "reference_p5": q[0],
        "reference_p20": q[1],
        "reference_p80": q[2],
        "reference_p95": q[3],
        "band_low": lo,
        "band_high": hi,
        "within_band": None if lo is None else bool(lo <= pct <= hi),
    }


def distance_check(fwd: dict, base: dict, refs: dict[str, pd.Series], bands: dict) -> pd.DataFrame:
    """Percentile of each scenario's deviation from the base among historical errors.
    fwd: {scenario: {'hpi': x, 'gdp': y}}; base: {'hpi', 'gdp'}; refs keyed 'variable:source';
    bands: {'downside': (lo, hi), 'upside': (lo, hi)} in percentiles."""
    rows = []
    for scen, vals in fwd.items():
        for key, err in refs.items():
            var = key.split(":")[0]
            rows.append(_row(scen, var, key, vals[var] - base[var], err, bands))
    return pd.DataFrame(rows)


def z_index_check(
    fwd: dict, base: dict, errors: pd.DataFrame, params: dict, bands: dict
) -> pd.DataFrame:
    """The distance check on the severity index: b_hpi x dHPI + b_gdp x dGDP (satellite
    coefficients) against the same combination of the VAR errors (`errors`: hpi, gdp)."""
    bh, bg = params["hpi_yoy[W]"], params["gdp_yoy[W]"]
    ez = bh * errors.hpi + bg * errors.gdp
    rows = []
    for scen, vals in fwd.items():
        dz = bh * (vals["hpi"] - base["hpi"]) + bg * (vals["gdp"] - base["gdp"])
        rows.append(_row(scen, "z_index", "z_index:var", dz, ez, bands))
    return pd.DataFrame(rows)


def plausibility(fwd: dict, hist1y: pd.DataFrame, bands: dict) -> pd.DataFrame:
    """Secondary check: percentile of each scenario's 1-year-forward HPI / GDP growth among
    historical outcomes, and whether the downside (upside) lies within its band."""
    rows = []
    for scen, vals in fwd.items():
        lo, hi = _band(scen, bands)
        for var, v in vals.items():
            pct = percentile_of(v, hist1y[var])
            rows.append(
                {
                    "scenario": scen,
                    "variable": var,
                    "value": v,
                    "historical_percentile": pct,
                    "reference_n": len(hist1y),
                    "band_low": lo,
                    "band_high": hi,
                    "within_band": None if lo is None else bool(lo <= pct <= hi),
                }
            )
    return pd.DataFrame(rows)
