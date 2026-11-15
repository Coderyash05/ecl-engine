"""Base (central) forecast: SPF median paths + VAR-conditional house prices.

What (docs/methodology/scenarios.md):
- **Real GDP growth**: SPF median, quarterly SAAR for 4 quarters (`drgdp3..6`), then quarters
  interpolated (sources.smooth_quarterly) so that the level's calendar-year averages equal the SPF
  annual averages (`RGDPB..D`).
- **Unemployment**: SPF median, quarterly (`UNEMP3..6`) then annual averages (`UNEMPB..D`),
  starting from the actual rate in the reporting quarter.
- **30-year mortgage rate** = SPF 10-year Treasury path (`TBOND`, same interpolation, starting
  from actual GS10) + the mortgage-Treasury spread. The spread starts at its actual value in the
  reporting quarter and moves linearly over the 12 forecast quarters to its 2000-2016 mean.
- **National HPI**: the VAR's expectation given the three paths above (conditional forecast).
- **Long run**: HPI and GDP growth = 2000-2016 means (the Module 3 PIT calibration window,
  so long-run Z = -0.207); mortgage rate = SEP longer-run fed funds + the mortgage-fed funds
  spread (1987-2019, zero-lower-bound quarters excluded: a deliberate exception to window
  consistency: the rate moves prepayment only, not Z); unemployment = SEP longer
  run (reported only).

Why (paras 47-49, 124): an external consensus anchors the central view, so it is not "our model
says so"; the VAR fills the variable the surveys do not forecast (house prices) consistently
with them. US data; not Indian risk estimates.
"""

import numpy as np
import pandas as pd

from ecl.scenarios.sources import smooth_quarterly, spf_points
from ecl.scenarios.var import VAR, conditional_forecast


def ff_spread(macro: pd.DataFrame, start: str, end: str, zlb_below: float | None) -> dict:
    """Mean mortgage - fed funds spread (pp) over start..end; with `zlb_below`, quarters with fed
    funds below it (zero lower bound, config) are excluded."""
    m = macro.loc[start:end, ["mortgage30", "fedfunds"]].dropna()
    keep = m.fedfunds >= zlb_below if zlb_below is not None else pd.Series(True, index=m.index)
    s = (m.mortgage30 - m.fedfunds)[keep]
    return {"spread": float(s.mean()), "quarters": int(keep.sum()), "of": len(m)}


def treasury_spread(macro: pd.DataFrame, gs10: pd.Series, start: str, end: str) -> float:
    """Mean mortgage - 10-year Treasury spread (pp) over start..end."""
    s = (macro.mortgage30 - gs10.reindex(macro.index)).loc[start:end].dropna()
    return float(s.mean())


def spf_paths(
    rows: dict[str, pd.Series],
    survey: pd.Period,
    report_q: pd.Period,
    actual: dict[str, float],
    horizon: int,
) -> pd.DataFrame:
    """Quarterly SPF base for report_q+1..report_q+horizon.

    rows: SPF rows {'drgdp': medianGrowth RGDP, 'RGDP', 'UNEMP', 'TBOND': medianLevel sheets}.
    actual: the reporting quarter's observed 'unrate' and 'gs10' (path starting points).
    Returns columns gdp_g (SAAR %), unrate, tbond and a 'source' column (spf_quarterly /
    interpolated)."""
    if survey != report_q:
        raise ValueError(
            f"survey {survey} differs from the reporting quarter {report_q}: "
            "the quarter mapping assumes they coincide"
        )
    q_last = report_q + horizon
    end = pd.Period(year=q_last.year, quarter=4, freq="Q")
    # GDP: index level, 1 at the reporting quarter; quarterly growth from drgdp3..6
    g = rows["drgdp"]
    lvl, fixed = 1.0, {report_q: 1.0}
    for k in range(1, 5):
        lvl *= (1 + g[f"drgdp{k + 2}"] / 100) ** 0.25
        fixed[report_q + k] = lvl
    _, ann = spf_points(rows["RGDP"], "RGDP", survey)
    base_lvl = rows["RGDP"]["RGDP2"]  # SPF units -> index of the survey quarter
    gdp_lvl = smooth_quarterly(report_q, end, fixed, {y: v / base_lvl for y, v in ann.items()})
    gdp_g = 100 * ((gdp_lvl / gdp_lvl.shift(1)) ** 4 - 1)
    out = {"gdp_g": gdp_g}
    for var, key, col in [("UNEMP", "unrate", "unrate"), ("TBOND", "gs10", "tbond")]:
        q, ann = spf_points(rows[var], var, survey)
        fx = {report_q: actual[key], **{p: v for p, v in q.items() if p > report_q}}
        out[col] = smooth_quarterly(report_q, end, fx, ann)
    df = pd.DataFrame(out).loc[report_q + 1 : q_last]
    df["source"] = [
        "spf_quarterly" if k <= 4 else "interpolated_from_annual" for k in range(1, horizon + 1)
    ]
    return df


def mortgage_path(tbond: pd.Series, spread0: float, spread_lr: float) -> pd.Series:
    """TBOND + a spread moving linearly from spread0 (reporting quarter) to spread_lr at the
    last forecast quarter."""
    h = len(tbond)
    k = np.arange(1, h + 1)
    return tbond + spread0 + (spread_lr - spread0) * k / h


def base_forecast(
    var: VAR,
    var_hist: np.ndarray,
    spf: pd.DataFrame,
    mortgage: pd.Series,
    unrate0: float,
    mortgage0: float,
) -> np.ndarray:
    """(h, 4) base in VAR units: gdp_g, d_mort, d_unrate fixed at the SPF-based paths; hpi_g =
    the VAR's conditional expectation."""
    h = len(spf)
    d_mort = np.diff(np.r_[mortgage0, mortgage.values])
    d_unrate = np.diff(np.r_[unrate0, spf.unrate.values])
    return conditional_forecast(
        var, var_hist, h, {"gdp_g": spf.gdp_g.values, "d_mort": d_mort, "d_unrate": d_unrate}
    )


def sep_q4q4(frame: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """The base path on the SEP basis: GDP growth Q4/Q4 and the Q4 unemployment rate."""
    rows = []
    for y in years:
        q4, q4p = pd.Period(f"{y}Q4", freq="Q"), pd.Period(f"{y - 1}Q4", freq="Q")
        f = (1 + frame.gdp_g.loc[q4p + 1 : q4] / 100) ** 0.25
        rows.append({"year": y, "gdp_q4q4": 100 * (f.prod() - 1), "unrate_q4": frame.unrate[q4]})
    return pd.DataFrame(rows)
