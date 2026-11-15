"""Training sample for the 12-month PD: every default plus a random share of non-defaults.

Why: dev_train has ~10M snapshots and ~1.2% defaults. Keeping all defaults and a fraction r of
non-defaults cuts the data ~6x with almost no loss of information about defaults. Each sampled
non-default gets weight 1/r (defaults weight 1), so weighted fits (binning, logistic
regression, LightGBM) reproduce the original population: the predicted PDs stay on the
original scale and need no prior-correction afterwards.

Selection is by md5(seed:loan_id:obs_date): reproducible and independent of row order.
"""

from pathlib import Path

import duckdb
import pandas as pd

NON_DEFAULT_RATE = 0.15
SAMPLE_SEED = 20261112


def sample_sql(target: str, rate: float, seed: int) -> str:
    """Boolean SQL: keep the row (all defaults, ~`rate` of non-defaults)."""
    u = f"(md5_number('{seed}:' || loan_id || ':' || obs_date::VARCHAR) % 1000000) / 1e6"
    return f"({target} OR {u} < {rate})"


def load_sample(
    dataset: Path,
    split: str,
    columns: list[str],
    target: str = "target_b18",
    population: str | None = None,
    rate: float = NON_DEFAULT_RATE,
    seed: int = SAMPLE_SEED,
) -> pd.DataFrame:
    """Rows of one split: all defaults + sampled non-defaults, with column `weight`."""
    where = [f"split = '{split}'", sample_sql(target, rate, seed)]
    if population:
        where.append(population)
    cols = ", ".join(dict.fromkeys(["loan_id", "obs_date", target, *columns]))
    df = duckdb.sql(f"""
        SELECT {cols} FROM read_parquet('{dataset.as_posix()}/*/*.parquet',
                                         hive_partitioning = true)
        WHERE {" AND ".join(where)}
        ORDER BY loan_id, obs_date
    """).df()
    df["weight"] = inverse_sampling_weights(df[target], rate)
    return df


def inverse_sampling_weights(y: pd.Series, rate: float) -> pd.Series:
    """1 for defaults, 1/rate for sampled non-defaults."""
    return y.astype(bool).map({True: 1.0, False: 1.0 / rate}).astype(float)


def load_split(
    dataset: Path, split: str, columns: list[str], population: str | None = None
) -> pd.DataFrame:
    """All rows of one split (no sampling), for evaluation."""
    where = f"split = '{split}'" + (f" AND {population}" if population else "")
    cols = ", ".join(dict.fromkeys(["loan_id", "obs_date", *columns]))
    return duckdb.sql(f"""
        SELECT {cols} FROM read_parquet('{dataset.as_posix()}/*/*.parquet',
                                         hive_partitioning = true)
        WHERE {where}
        ORDER BY loan_id, obs_date
    """).df()
