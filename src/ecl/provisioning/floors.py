"""Prudential floors on ECL (Module 8; RBI paras 82(4)-(5), 90).

What (values from config/rbi_2026.yaml `floors.housing_loan_to_individuals`, item (xi)(a)):
- **Stages 1 and 2: portfolio level per stage** (para 90): provision = max(sum of model ECL,
  floor rate x sum of exposure) for the stage (0.25% Stage 1, 1.50% Stage 2, para 82(4));
- **Stage 3: per account** (para 90) by years in Stage 3 (para 82(5)): floor = secured rate x
  secured portion + unsecured rate x unsecured portion; bands [from, to) as configured (a loan at
  exactly 1.0 year is in the 1-2 year band: the conservative convention; rbi_specified: false);
  provision = max(model ECL, floor);
- reports where the floor binds; a portfolio floor uplift is allocated to loans pro rata to
  exposure (presentation only).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike


def portfolio_floor(ecl: np.ndarray, exposure: np.ndarray, rate: float) -> dict:
    """Stage 1 / Stage 2 floor at portfolio level."""
    model, base = float(np.sum(ecl)), float(np.sum(exposure))
    floor = rate * base
    return {
        "model_ecl": model,
        "floor": floor,
        "provision": max(model, floor),
        "binds": floor > model,
        "exposure": base,
    }


def stage3_band_rates(years: np.ndarray, bands: list[dict], convention: str) -> tuple:
    """(secured rate, unsecured rate) per loan for its years in Stage 3."""
    y = np.asarray(years, float)
    sec = np.full(len(y), np.nan)
    uns = np.full(len(y), np.nan)
    for b in bands:
        lo, hi = b["years_from"], b["years_to"]
        hi = np.inf if hi is None else hi
        m = (y >= lo) & (y < hi) if convention == "[from, to)" else (y > lo) & (y <= hi)
        if convention != "[from, to)" and lo == 0:
            m |= y == 0
        sec[m], uns[m] = b["secured"], b["unsecured"]
    if np.isnan(sec).any():
        raise ValueError("years in Stage 3 outside the configured bands")
    return sec, uns


def stage3_floor(
    ecl: ArrayLike,
    secured: ArrayLike,
    unsecured: ArrayLike,
    years: ArrayLike,
    bands: list[dict],
    convention: str,
) -> pd.DataFrame:
    """Per-account Stage 3 floor and provision."""
    rs, ru = stage3_band_rates(years, bands, convention)
    floor = rs * np.asarray(secured, float) + ru * np.asarray(unsecured, float)
    ecl = np.asarray(ecl, float)
    return pd.DataFrame(
        {
            "floor": floor,
            "provision": np.maximum(ecl, floor),
            "binds": floor > ecl,
            "rate_secured": rs,
            "rate_unsecured": ru,
        }
    )
