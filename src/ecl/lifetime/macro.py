"""US macro series (FRED) -> one quarterly table of cycle drivers.

Why: the credit-cycle index Z_t (cycle.py) is quarterly, so every driver must be on calendar
quarters before it can enter the satellite regression (RBI paras 47-49: forward-looking
information). Each FRED frequency is reduced to quarters in the way that keeps its meaning:

- weekly rates (MORTGAGE30US): mean of the weeks dated in the quarter (>= 10 weeks);
- monthly rates (UNRATE, FEDFUNDS): mean of the available months (>= 2 of 3; a missing month
  such as UNRATE 2025-10, which was not published, is listed in the QC table);
- quarterly series (USSTHPI, A191RL1Q225SBEA): as published.

Drivers are growth rates or changes, never levels (levels are non-stationary):
- hpi_yoy: house prices, % change on the same quarter a year earlier (also removes the
  seasonality of the NSA index);
- gdp_yoy: real GDP, % change over four quarters, compounded from the quarterly annualised
  rates: prod (1 + g/100)^(1/4) - 1;
- ff_chg4, unrate_chg4, mort_chg4: change over four quarters, percentage points.

All series are US data (not Indian); roles map to Indian series in Module 12.
"""

from pathlib import Path

import numpy as np
import pandas as pd

# FRED file -> (column name, frequency, minimum observations for a complete quarter)
SERIES = {
    "USSTHPI": ("hpi", "Q", 1),
    "A191RL1Q225SBEA": ("gdp_qoq_saar", "Q", 1),
    "MORTGAGE30US": ("mortgage30", "W", 10),
    "UNRATE": ("unrate", "M", 2),
    "FEDFUNDS": ("fedfunds", "M", 2),
}
# driver role -> column of the quarterly table; expected sign on Z (Z > 0 = benign)
DRIVERS = {
    "hpi_yoy": +1,
    "gdp_yoy": +1,
    "ff_chg4": -1,
    "unrate_chg4": -1,
}


def read_fred(path: Path) -> pd.Series:
    """One FRED CSV (header `observation_date,<ID>` or the older `DATE,<ID>`); '.' or blank
    values become NaN."""
    df = pd.read_csv(path, na_values=[".", ""], keep_default_na=True)
    date_col = "observation_date" if "observation_date" in df.columns else "DATE"
    value_col = next(c for c in df.columns if c != date_col)
    s = pd.Series(
        pd.to_numeric(df[value_col], errors="coerce").values,
        index=pd.to_datetime(df[date_col]),
        name=value_col,
    )
    return s.sort_index()


def to_quarterly(s: pd.Series, min_obs: int) -> tuple[pd.Series, pd.DataFrame]:
    """Mean of the non-missing observations in each calendar quarter; quarters with fewer than
    `min_obs` observations are dropped. Returns the series and a QC table of short quarters."""
    q = s.index.to_period("Q")
    g = s.groupby(q)
    mean, count, total = g.mean(), g.count(), g.size()
    short = pd.DataFrame(
        {"quarter": count.index.astype(str), "observations": count.values, "rows": total.values}
    )[(count < min_obs).values | (count < total).values]
    return mean[count >= min_obs], short


def load_macro(macro_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Quarterly table (PeriodIndex) of the raw series and the drivers, plus a QC table."""
    cols, qc = {}, []
    for fred_id, (name, freq, min_obs) in SERIES.items():
        s = read_fred(macro_dir / f"{fred_id}.csv")
        q, short = to_quarterly(s, min_obs) if freq != "Q" else (_as_quarters(s), None)
        cols[name] = q
        qc.append(
            {
                "series": fred_id,
                "column": name,
                "frequency": freq,
                "first": str(q.index.min()),
                "last": str(q.index.max()),
                "quarters": int(q.notna().sum()),
                "short_or_gappy_quarters": ""
                if short is None or short.empty
                else "; ".join(
                    f"{r.quarter} ({r.observations}/{r.rows})" for r in short.itertuples()
                ),
                "missing_values": int(s.isna().sum()),
            }
        )
    m = pd.DataFrame(cols).sort_index()
    m["hpi_yoy"] = 100 * (m["hpi"] / m["hpi"].shift(4) - 1)
    m["gdp_yoy"] = gdp_yoy(m["gdp_qoq_saar"])
    m["ff_chg4"] = m["fedfunds"] - m["fedfunds"].shift(4)
    m["unrate_chg4"] = m["unrate"] - m["unrate"].shift(4)
    m["mort_chg4"] = m["mortgage30"] - m["mortgage30"].shift(4)
    return m, pd.DataFrame(qc)


def gdp_yoy(qoq_saar: pd.Series) -> pd.Series:
    """Four-quarter growth (%) from quarterly annualised growth rates (%)."""
    factor = (1 + qoq_saar / 100) ** 0.25
    return 100 * (factor.rolling(4).apply(np.prod, raw=True) - 1)


def window_mean(x: pd.Series, start: int = 1, end: int = 4) -> pd.Series:
    """Mean of x over quarters t+start..t+end, indexed by t (alignment W: the 12-month outcome
    window of a snapshot taken in quarter t)."""
    return pd.concat([x.shift(-k) for k in range(start, end + 1)], axis=1).mean(
        axis=1, skipna=False
    )


def _as_quarters(s: pd.Series) -> pd.Series:
    out = s.copy()
    out.index = out.index.to_period("Q")
    return out
