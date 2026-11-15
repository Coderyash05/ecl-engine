"""Score every PD snapshot with the TTC model and aggregate to cells for the cycle index.

Why: Z_t is fitted per quarter on ~250k snapshots. The Vasicek likelihood only needs, per
quarter, how many loans had (almost) the same TTC PD and how many of them defaulted, so the
20.9M scored snapshots are reduced to cells of (quarter, delinquency state, sand-state flag,
TTC-PD bin) with n, defaults and the mean PD. Bins are 0.02 wide on the logit scale (about 2%
relative PD), so replacing each loan's PD by its cell mean changes nothing material.

The data are scored one year at a time (laptop memory). Cells are derived from loan-level data
and stay in data/ (gitignored); only quarterly aggregates go to reports/.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pandas as pd

from ecl.pd.features import SOURCE_COLUMNS, scorecard_frame
from ecl.pd.scorecard import WoEScorecard

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

LOGIT_BIN = 0.02
SAND_STATES = ("CA", "FL", "NV", "AZ")  # largest 2006-12 house-price falls (Module 2a check)
GROUPS = {0: "never 30+ dpd", 1: "cured", 2: "cured", 3: "cured", 4: "30-89 dpd", 5: "30-89 dpd"}


def score_year(dataset: Path, model: WoEScorecard, year: int) -> pd.DataFrame:
    """All snapshots of one observation year (every split), scored with the TTC model."""
    cols = ", ".join(
        dict.fromkeys(
            [
                "loan_id",
                "obs_date",
                "target_b18",
                "target_a",
                "elig_a",
                "property_state",
                *SOURCE_COLUMNS,
            ]
        )
    )
    df = duckdb.sql(f"""
        SELECT {cols} FROM read_parquet('{dataset.as_posix()}/*/*.parquet',
                                         hive_partitioning = true)
        WHERE year(obs_date) = {year}
        ORDER BY loan_id, obs_date
    """).df()
    x = scorecard_frame(df)
    return pd.DataFrame(
        {
            "obs_date": pd.to_datetime(df.obs_date).values,
            "dlq_state": x.dlq_state.values,
            "sand": df.property_state.isin(SAND_STATES).values,
            "pd": model.predict_pd(x),
            "d": df.target_b18.astype(int).values,
            "elig_a": df.elig_a.astype(bool).values,
            "d_a": df.target_a.fillna(False).astype(int).values,
        }
    )


def to_cells(scored: pd.DataFrame) -> pd.DataFrame:
    """Aggregate scored snapshots to (obs_date, dlq_state, sand, logit bin) cells."""
    s = scored[scored.dlq_state.notna() & scored.pd.notna()].copy()
    s["lbin"] = np.round(np.log(s.pd / (1 - s.pd)) / LOGIT_BIN).astype(int)
    s["pd_a"] = np.where(s.elig_a, s.pd, 0.0)
    s["n_a"] = s.elig_a.astype(int)
    s["d_a"] = np.where(s.elig_a, s.d_a, 0)
    g = (
        s.groupby(["obs_date", "dlq_state", "sand", "lbin"])
        .agg(
            n=("pd", "size"),
            d=("d", "sum"),
            sum_pd=("pd", "sum"),
            n_a=("n_a", "sum"),
            d_a=("d_a", "sum"),
            sum_pd_a=("pd_a", "sum"),
        )
        .reset_index()
    )
    g["p"] = g.sum_pd / g.n
    g["p_a"] = np.where(g.n_a > 0, g.sum_pd_a / g.n_a.clip(lower=1), np.nan)
    g["dlq_state"] = g.dlq_state.astype(int)
    g["group"] = g.dlq_state.map(GROUPS)
    return g.drop(columns=["sum_pd", "sum_pd_a"])


def build_cells(dataset: Path, model: WoEScorecard, years: Iterable[int]) -> pd.DataFrame:
    """Score every PD snapshot of the given years with the TTC model and aggregate them to
    cells (snapshot date x delinquency state x sand state x PD logit bin) of snapshots,
    defaults and summed PD: the input of the credit-cycle index fit."""
    out = []
    for y in years:
        scored = score_year(dataset, model, y)
        logger.info(f"  {y}: {len(scored):,} snapshots scored")
        out.append(to_cells(scored))
        del scored
    return pd.concat(out, ignore_index=True)
