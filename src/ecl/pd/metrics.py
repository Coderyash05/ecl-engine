"""Discrimination, calibration and stability metrics for PD models.

Gini = 2 x AUC - 1 (rank ordering); KS = max gap between the cumulative score distributions
of defaults and non-defaults; Brier = mean squared error of the PD (calibration + sharpness).
PSI = sum (actual% - expected%) x ln(actual% / expected%) over bins: < 0.10 stable,
0.10-0.25 moderate shift, > 0.25 significant shift (industry rule of thumb, not RBI).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike
from sklearn.metrics import roc_auc_score, roc_curve

PSI_EPS = 1e-6


def gini(y: ArrayLike, p: ArrayLike, w: ArrayLike | None = None) -> float:
    """Gini coefficient = 2 x AUC - 1 (rank ordering), optionally weighted."""
    return 2 * roc_auc_score(y, p, sample_weight=w) - 1


def ks(y: ArrayLike, p: ArrayLike, w: ArrayLike | None = None) -> float:
    """Kolmogorov-Smirnov statistic: maximum gap between the cumulative score distributions of
    defaults and non-defaults."""
    fpr, tpr, _ = roc_curve(y, p, sample_weight=w)
    return float(np.max(tpr - fpr))


def brier(y: ArrayLike, p: ArrayLike, w: ArrayLike | None = None) -> float:
    """Brier score: (weighted) mean squared error of the PD."""
    return float(np.average((np.asarray(p) - np.asarray(y, dtype=float)) ** 2, weights=w))


def calibration_table(y: ArrayLike, p: ArrayLike, n_bins: int = 10) -> pd.DataFrame:
    """Predicted vs actual default rate by decile of predicted PD."""
    d = pd.DataFrame({"y": np.asarray(y, dtype=float), "p": p})
    d["decile"] = pd.qcut(d.p.rank(method="first"), n_bins, labels=range(1, n_bins + 1))
    return (
        d.groupby("decile", observed=True)
        .agg(n=("y", "size"), mean_pd=("p", "mean"), default_rate=("y", "mean"))
        .reset_index()
    )


def weighted_quantile_edges(x: ArrayLike, w: ArrayLike, n_bins: int = 10) -> np.ndarray:
    """Inner bin edges of `n_bins` equal-weight bins of `x` (duplicates removed)."""
    order = np.argsort(x)
    cw = np.cumsum(np.asarray(w)[order])
    qs = np.searchsorted(cw / cw[-1], np.linspace(0, 1, n_bins + 1)[1:-1])
    return np.unique(np.asarray(x)[order][qs])


def psi(expected: pd.Series, actual: pd.Series) -> float:
    """PSI between two distributions given as shares indexed by bin."""
    e, a = expected.align(actual, fill_value=0)
    e, a = e.clip(lower=PSI_EPS), a.clip(lower=PSI_EPS)
    return float(((a - e) * np.log(a / e)).sum())


def shares(labels: ArrayLike, w: ArrayLike | None = None) -> pd.Series:
    """(Weighted) share of each label, for PSI."""
    s = pd.Series(
        np.ones(len(labels)) if w is None else np.asarray(w),
        index=pd.Index(np.asarray(labels, dtype=str)),
    )
    s = s.groupby(level=0).sum()
    return s / s.sum()
