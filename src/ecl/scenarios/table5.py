"""Annex 4 Table 5: macroeconomic assumptions per scenario (RBI ECL Directions 2026, Annex 4).

Table 5 ("to be submitted to RBI only") lists, for the central, upside and downside economic
assumptions, a "1 year forward" and a "5-year average" value per indicator, "As on March 31".
The Directions do not define the statistics; our definitions (docs/methodology/scenarios.md):

| Indicator | 1 year forward | 5-year average |
|---|---|---|
| National HPI growth | index change over the 4 quarters after the reporting date | annualised growth over quarters 1-20 (geometric) |
| Real GDP growth | growth over quarters 1-4 | annualised growth over quarters 1-20 |
| 30-year mortgage rate | average level over quarters 1-4 | average over quarters 1-20 |
| Unemployment rate | average over quarters 1-4 | average over quarters 1-20 |

The 5-year average includes the 8 reversion quarters (13-20). US data, not Indian.
"""

import numpy as np
import pandas as pd

INDICATORS = [
    "National HPI growth (FHFA, %)",
    "Real GDP growth (%)",
    "30-year mortgage rate (%)",
    "Unemployment rate (%)",
]
SCENARIO_LABELS = {
    "central": "Central economic assumptions",
    "upside": "Upside economic assumptions",
    "downside": "Downside economic assumptions",
}


def indicator_values(frame: pd.DataFrame, report_q: pd.Period) -> dict:
    """{indicator: (1 year forward, 5-year average)} from a scenario frame (build.extend)."""
    q = report_q
    f1 = pd.period_range(q + 1, q + 4, freq="Q")
    f5 = pd.period_range(q + 1, q + 20, freq="Q")
    gdp_f = (1 + frame.gdp_g / 100) ** 0.25
    return {
        INDICATORS[0]: (
            100 * (np.exp(frame.log_hpi[q + 4] - frame.log_hpi[q]) - 1),
            100 * (np.exp((frame.log_hpi[q + 20] - frame.log_hpi[q]) / 5) - 1),
        ),
        INDICATORS[1]: (100 * (gdp_f[f1].prod() - 1), 100 * (gdp_f[f5].prod() ** (1 / 5) - 1)),
        INDICATORS[2]: (frame.mortgage30[f1].mean(), frame.mortgage30[f5].mean()),
        INDICATORS[3]: (frame.unrate[f1].mean(), frame.unrate[f5].mean()),
    }


def table5(
    frames: dict[str, pd.DataFrame], weights: dict[str, float], report_q: pd.Period
) -> pd.DataFrame:
    """Long table: scenario, weight, horizon ('1 year forward' / '5-year average'), indicators."""
    rows = []
    for scen in ["central", "upside", "downside"]:
        vals = indicator_values(frames[scen], report_q)
        for i, hz in enumerate(["1 year forward", "5-year average"]):
            rows.append(
                {
                    "as_on": report_q.end_time.date().isoformat(),
                    "scenario": SCENARIO_LABELS[scen],
                    "weight": weights[scen],
                    "horizon": hz,
                    **{k: v[i] for k, v in vals.items()},
                }
            )
    return pd.DataFrame(rows)
