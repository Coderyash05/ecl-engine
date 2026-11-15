"""Exposure at default and the secured portion (RBI paras 100, 6(24)).

What:
- **EAD at a future default** (performing loans): the contractual amortising balance at the
  default point, before the missed instalments (a 90-dpd default has three unpaid instalments,
  so the balance is the one three months earlier), plus the interest accrued on those
  instalments. Prepayment enters through survival (Module 3 hazard), which the PD already
  carries; conditional on default the balance follows the schedule (no curtailments).
- **EAD now** (any loan at the reporting date): current UPB + accrued interest on the months
  delinquent (0 for a current loan).
- **Collateral is never netted from EAD** (para 100); it enters LGD and the secured portion.
- **Secured portion** (para 6(24): "portion covered by the realistic realisable value of
  collateral"): realisable value = HPI-indexed property value x (1 - realisation haircut), the
  haircut measured from REO sales in the data; secured = min(EAD, realisable value), unsecured =
  EAD - secured. Module 8 applies the Stage 3 floors to each portion.

US data (Freddie Mac, FHFA); not Indian risk estimates.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike

from ecl.lifetime.hazard import amortised_balance


def accrued_interest(upb: ArrayLike, note_rate: ArrayLike, months: ArrayLike) -> np.ndarray:
    """Interest on `months` unpaid instalments (simple, note rate % a year)."""
    return np.asarray(upb, float) * np.asarray(note_rate, float) / 1200 * np.clip(months, 0, None)


def ead_now(upb: ArrayLike, note_rate: ArrayLike, months_dlq: ArrayLike) -> np.ndarray:
    """Current UPB + interest accrued on the delinquent months."""
    m = np.nan_to_num(np.asarray(months_dlq, float), nan=0.0)
    return np.asarray(upb, float) + accrued_interest(upb, note_rate, m)


def ead_at_default(
    upb: ArrayLike,
    note_rate: ArrayLike,
    rm: ArrayLike,
    months_ahead: ArrayLike,
    accrued_months: int,
) -> np.ndarray:
    """EAD if the loan defaults `months_ahead` months after the reporting date: scheduled balance
    at (months_ahead - accrued_months) plus `accrued_months` of interest. Arrays broadcast
    (loans x years)."""
    n = np.maximum(np.asarray(months_ahead, float) - accrued_months, 0)
    bal = amortised_balance(
        np.asarray(upb, float), np.asarray(note_rate, float), np.asarray(rm, float), n
    )
    return bal + accrued_interest(bal, note_rate, accrued_months)


def secured_portion(
    ead: ArrayLike, indexed_value: ArrayLike, haircut: float
) -> tuple[np.ndarray, np.ndarray]:
    """(secured, unsecured) = (min(EAD, value x (1 - haircut)), remainder); a missing value
    leaves the whole EAD unsecured."""
    ead = np.asarray(ead, float)
    real = np.nan_to_num(np.asarray(indexed_value, float) * (1 - haircut), nan=0.0)
    sec = np.clip(np.minimum(ead, real), 0, None)
    return sec, ead - sec
