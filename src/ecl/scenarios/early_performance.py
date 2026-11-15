"""Early-performance check of the 2024-26 vintages (candidate overlay CO-4, config/overlays.yaml).

What: neither the scorecard nor the hazard saw these vintages (originated at 6-7% mortgage rates).
Over the months observed by the reporting date, their 30+ dpd and 90+ dpd rates (stock: share of
observed loan-months in that status, defaulted loans included) and first-default rate (incidence
of the first RBI default, paras 6(5), 8(1), among loans not yet in default) by vintage and loan
age are compared with what history implies at the same
ages:
- benchmark = the development-era vintages (config: 2000-2016) at the same loan age;
- point-in-time adjustment: for each age a, the benchmark's TTC rate p_a solves
  sum_q n_q x Vasicek(p_a, Z_q) = benchmark events over the benchmark's observation quarters;
  the expected count for a 2024-26 cell is sum_q n_q x Vasicek(p_a, Z_q) over its own quarters.
  Z_q = satellite Z on actual macro (the Module 3 PIT model, rho from pd_pit). Applying the
  Vasicek shift to delinquency prevalence is an approximation, recorded as such;
- the trigger (config): actual / expected above the threshold in any vintage x loan-age band with
  at least the minimum number of events -> record **CO-4** (candidate overlay, para 131).
The benchmark is not mix-adjusted (credit score, LTV); the mix of both groups is reported.

US data (Freddie Mac); not Indian risk estimates.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import brentq

from ecl.lifetime.cycle import vasicek_pd

RATES = {"dpd30": "n", "dpd90": "n", "default": "n_risk"}  # rate -> its denominator


def cell_counts(
    con: duckdb.DuckDBPyConnection, vintages: tuple, as_at: str, max_age: int
) -> pd.DataFrame:
    """Loan-months by vintage, loan age (months) and calendar quarter (view `panel_all`): observed
    (n), 30+ and 90+ dpd among them; at risk of a first default (n_risk: not defaulted before the
    month) and first RBI defaults."""
    lo, hi = vintages
    return con.execute(f"""
        SELECT vintage, loan_age, year(period) * 4 + quarter(period) - 1 AS q,
               COUNT(*) AS n,
               SUM((months_dlq >= 1)::INT) AS dpd30,
               SUM((months_dlq >= 3)::INT) AS dpd90,
               SUM((first_default_period IS NULL OR period <= first_default_period)::INT)
                   AS n_risk,
               SUM(COALESCE(period = first_default_period, FALSE)::INT) AS "default"
        FROM panel_all
        WHERE vintage BETWEEN {lo} AND {hi} AND period <= DATE '{as_at}'
          AND loan_age BETWEEN 0 AND {max_age}
        GROUP BY ALL ORDER BY ALL
    """).df()


def ttc_rate(n: np.ndarray, z: np.ndarray, events: float, rho: float) -> float:
    """p with sum n x Vasicek(p, z) = events (0 if no events)."""
    if events <= 0:
        return 0.0
    f = lambda p: float(np.sum(n * vasicek_pd(p, z, rho))) - events
    return brentq(f, 1e-9, 1 - 1e-9)


def expected_counts(
    bench: pd.DataFrame, target: pd.DataFrame, z_q: pd.Series, rho: float
) -> pd.DataFrame:
    """Expected events per target row (vintage, loan_age, q) from the benchmark's age profile,
    PIT-adjusted to each row's quarter."""
    out = target.copy()
    zb = z_q.reindex(bench.q).values
    zt = z_q.reindex(target.q).values
    for rate, den in RATES.items():
        out[f"exp_{rate}"] = 0.0
        for a, g in bench.assign(z=zb).groupby("loan_age"):
            p = ttc_rate(g[den].values, g.z.values, g[rate].sum(), rho)
            m = (target.loan_age == a).values
            out.loc[m, f"exp_{rate}"] = target[den].values[m] * vasicek_pd(p, zt[m], rho)
    return out


def summarise(
    cells: pd.DataFrame, band_months: int, threshold: float, min_events: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Actual vs expected by vintage x loan age (monthly detail) and by vintage x age band with
    the CO-4 trigger flag."""
    cells = cells.copy()
    cells["age_band"] = (cells.loan_age // band_months) * band_months
    detail, bands = [], []
    for keys, out in [(["vintage", "loan_age"], detail), (["vintage", "age_band"], bands)]:
        g = cells.groupby(keys).sum(numeric_only=True).reset_index()
        for rate, den in RATES.items():
            out.append(
                g.assign(
                    rate=rate,
                    n=g[den],
                    actual=g[rate],
                    expected=g[f"exp_{rate}"],
                    actual_rate=g[rate] / g[den],
                    expected_rate=g[f"exp_{rate}"] / g[den],
                    actual_to_expected=g[rate] / g[f"exp_{rate}"],
                )[
                    [
                        *keys,
                        "rate",
                        "n",
                        "actual",
                        "expected",
                        "actual_rate",
                        "expected_rate",
                        "actual_to_expected",
                    ]
                ]
            )
    detail, bands = pd.concat(detail), pd.concat(bands)
    bands["trigger"] = (bands.actual_to_expected > threshold) & (bands.actual >= min_events)
    return detail.reset_index(drop=True), bands.reset_index(drop=True)


def mix(con: duckdb.DuckDBPyConnection, groups: dict[str, tuple]) -> pd.DataFrame:
    """Origination mix of each vintage group (view `loans_all`)."""
    rows = []
    for name, (lo, hi) in groups.items():
        r = con.execute(f"""
            SELECT COUNT(*) AS loans, AVG(NULLIF(credit_score, 9999)) AS credit_score,
                   AVG(NULLIF(orig_ltv, 999)) AS orig_ltv, AVG(NULLIF(orig_dti, 999)) AS orig_dti,
                   -- note rates have 3 decimals: an exact DECIMAL sum (order-independent)
                   AVG(CAST(orig_interest_rate AS DECIMAL(9, 3)))::DOUBLE AS note_rate
            FROM loans_all WHERE vintage BETWEEN {lo} AND {hi}
        """).df()
        rows.append(r.assign(group=name))
    return pd.concat(rows, ignore_index=True)
