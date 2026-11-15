"""Module 11 quantitative checks (entry points for `ecl backtest` / `ecl validate`).

- `ecl_backtest_report`: a reporting date's 12-month PD and ECL against the following 12 months
  (ACPIR para 131: post-implementation backtesting) -> reports/summary/
  validation_ecl_backtest_{YYYY-MM}.csv.
- `m1_check`: finding M-1 (docs/validation_report.md) - relief cures credited twice, once in the
  B-18 PD target and once in the LGD cure model -> reports/summary/
  validation_m1_relief_cures.json.

US data (Freddie Mac sample); not Indian risk estimates.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from ecl.lgd import data as ld
from ecl.lgd.models import load
from ecl.scenarios.run_pd import load_inputs
from ecl.validation.backtest import ecl_backtest, outcomes
from ecl.validation.relief_cures import relief_cure_double_count

logger = logging.getLogger(__name__)

US_DATA_NOTE = "# US data (Freddie Mac sample) - not Indian risk estimates; amounts in US dollars\n"


def m1_check(root: Path, lgd: dict) -> dict:
    """Relief-cure double count on the cure-model recalibration window: rows at m = 0 with the
    B-18 relabel flag of each first default, scored with the development cure model. Writes
    reports/summary/validation_m1_relief_cures.json and returns the result."""
    scen = yaml.safe_load((root / "config/scenarios.yaml").read_text(encoding="utf-8"))
    log_state = load_inputs(scen, root).log_state
    d = ld.build_defaults(root / "data/processed", lgd)
    d = ld.add_loss(d, lgd["ead"]["accrued_interest_at_default_months"])
    d = ld.add_collateral(d, log_state)
    rows = ld.observation_rows(d, lgd["cure_model"]["months_in_default"], log_state)
    glob = (root / "data/processed/panel").as_posix() + "/*/*.parquet"
    flag = duckdb.sql(
        f"SELECT loan_id, relief_cured_b18 FROM read_parquet('{glob}', hive_partitioning=true) "
        "WHERE default_event AND period = first_default_period ORDER BY loan_id"
    ).df()
    w0, w1 = lgd["cure_model"]["recalibration"]["window"]
    r0 = rows[(rows.m == 0) & pd.to_datetime(rows.fd).dt.year.between(w0, w1)]
    r0 = r0.merge(flag, on="loan_id", how="left")
    m1 = relief_cure_double_count(
        r0, r0.relief_cured_b18, load(root / "models/lgd/cure_model_option1.pkl")
    )
    (root / "reports/summary/validation_m1_relief_cures.json").write_text(json.dumps(m1, indent=2))
    return m1


def ecl_backtest_report(root: Path, date: str, lgd: dict) -> pd.DataFrame:
    """ECL backtest of reporting date `date` over the next 12 months (para 131): predicted vs
    realised defaults and losses by stage. Writes the CSV and returns the table."""
    ts = pd.Timestamp(date)
    res = pd.read_parquet(root / f"data/processed/ecl/ecl_{ts:%Y-%m}.parquet")
    start = (ts + pd.offsets.MonthBegin(1)).date()
    end = (pd.Timestamp(start) + pd.DateOffset(months=12)).date()
    out = outcomes(root / "data/processed", res.loan_id, str(start), str(end))
    data_end = f"{out.last_period.max():%Y-%m}"
    bt = ecl_backtest(res, out, lgd["resolution"]["loss_codes"], data_end)
    bt.insert(0, "window", f"{start} to {end} (exclusive)")
    bt.insert(0, "as_on", f"{ts.date()}")
    p = root / f"reports/summary/validation_ecl_backtest_{ts:%Y-%m}.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        fh.write(US_DATA_NOTE)
        bt.to_csv(fh, index=False)
    return bt
