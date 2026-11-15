"""Origination side of the SICR test (para 26): the lifetime PD expected at initial recognition
over the loan's remaining window.

What (see docs/methodology/staging.md and docs/methodology/pd_lifetime.md):
- each loan is projected with the lifetime hazard from its first observed month, with its
  origination features (never delinquent, LTV at the first month), on the **long-run macro path**
  (every driver at its 2000-2016 mean, Z at its long-run value): the macro-neutral expectation at
  initial recognition;
- annual floor as for the current side; the PD of default from the reporting date to maturity,
  conditional on being alive at the reporting date (`remaining_from`).
So the comparator is seasoning-neutral: it is what the loan's age and remaining term implied at
origination, and the current side differs from it only through the change in risk.
US data; not Indian risk estimates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ecl.lifetime.hazard import apply_annual_floor, cumulative, project, remaining_from

if TYPE_CHECKING:
    from ecl.lifetime.hazard import HazardModel, Loans
    from ecl.lifetime.paths import MacroPath


def origination_expected_remaining(
    model: HazardModel,
    orig: pd.DataFrame,
    orig_loans: Loans,
    lrp: MacroPath,
    loan_ids: pd.Series,
    report_month: pd.Timestamp,
    floor_annual: float,
    chunk: int = 40_000,
) -> np.ndarray:
    """Origination-expected lifetime PD from `report_month` to maturity for `loan_ids` (NaN for
    loans without an origination record)."""
    pos = pd.Series(np.arange(len(orig)), index=orig.loan_id)
    oi = pos.reindex(loan_ids.values).values
    has = ~np.isnan(oi)
    oi = np.where(has, oi, 0).astype(int)
    first = pd.to_datetime(orig.first_period.values[oi])
    months = (report_month.year * 12 + report_month.month) - (first.year * 12 + first.month)
    out = np.full(len(loan_ids), np.nan)
    sel = np.where(has)[0]
    n_q = int(np.ceil(orig.rm_first.max() / 3))
    for a in range(0, len(sel), chunk):
        ii = sel[a : a + chunk]
        sub = orig_loans.take(oi[ii])
        sub.state_idx = lrp.state_index(orig.property_state.values[oi[ii]])
        hd, hp = project(model, sub, lrp, n_q)
        hd, _ = apply_annual_floor(hd, hp, floor_annual)
        s, cd, _ = cumulative(hd, hp)
        out[ii] = remaining_from(cd, s, np.floor(np.asarray(months)[ii] / 3).astype(int))
    return out
