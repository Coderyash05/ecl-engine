"""Module 2b: candidate features for the 12-month TTC PD and how each model sees them.

No macro variables (Module 2 is through-the-cycle; macro sensitivity is Module 3).

Binning policy (v1.1.0, amended v1.2.0; documented choice, not RBI-prescribed) by feature `kind`:
- "numerical": continuous; optbinning optimal bins, each >= 5% of weighted snapshots, monotonic
  `trend` of the default rate where it makes business sense (score down -> PD up, LTV up -> PD up).
- "state": delinquency states, flags and counts; bins are the natural categories given by
  `splits`. A 5% minimum would erase them (60-89 dpd is 0.3% of snapshots with a 69% default rate).
- "categorical": one bin per category.
For "state" and "categorical" a category is merged into a neighbour only if it is both rare and
thin: under scorecard.STATE_MIN_SHARE of weighted snapshots AND under STATE_MIN_DEFAULTS defaults
(v1.2.0 amendment: the stability of a bin's default rate is governed by its default count, so a
rare state with thousands of defaults, like 60-89 dpd, keeps its bin).
`dummy` features enter the scorecard as one indicator per bin (base = first bin) instead of a
single WoE column, so each state gets its own coefficient and its own points.
`constraint` is the LightGBM monotone constraint (+1: PD rises with the feature).

`dlq_state` combines the delinquency features into one ordered state: never 30+ dpd / cured
13+ / 4-12 / 1-3 months ago / 30-59 dpd / 60-89 dpd. current_dpd, months_since_30dpd and
max_dlq_12m overlap by construction ("30+ dpd now" is the same loans in all three; WoE
correlations 0.6-0.9), and a sum of their WoEs cannot reproduce the default rate of each state.
All four are candidates; the correlation rule in scorecard.select_features keeps one.
From v1.2.0 dlq_state is dummy-coded (base = never 30+ dpd): one WoE coefficient scales all six
states by the same factor, which left 60-89 dpd under-predicted (62.7% vs 69.3% in v1.1.0).

Dropped from the candidates in v1.1.0: orig_interest_rate — it measures the rate era, not the
borrower (PSI 1.5-2.0 dev -> OOT); rate_spread (rate vs same-month average) carries the signal.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

NEVER_30DPD = -999  # scorecard: special bin "never 30+ dpd" (not missing)
NEVER_30DPD_LGBM = 999  # challenger: never delinquent = furthest from a delinquency
# channel: Freddie reported third-party loans as T before 2008 and as B (broker) /
# C (correspondent) after (disclosure change) -> one third-party category
THIRD_PARTY = "TPO"
THIRD_PARTY_CODES = ["T", "B", "C"]


@dataclass(frozen=True)
class Feature:
    """A candidate PD feature and its binning policy: kind (numerical / state / categorical),
    monotonic trend for the WoE bins, LightGBM monotone constraint, natural bin edges for
    state features, and whether the scorecard enters it as dummies."""

    name: str
    kind: str  # "numerical" | "state" | "categorical"
    trend: str = "auto"  # optbinning monotonic_trend (kind "numerical")
    constraint: int = 0  # LightGBM monotone constraint
    splits: tuple[float, ...] = ()  # natural bin edges (kind "state")
    dummy: bool = False  # scorecard: indicator per bin instead of one WoE column


FEATURES = [
    Feature("credit_score", "numerical", "descending", -1),
    Feature("orig_ltv", "numerical", "ascending", 1),
    Feature("orig_cltv", "numerical", "ascending", 1),
    Feature("orig_dti", "numerical", "ascending", 1),  # missing -> own bin (HARP)
    Feature("current_ltv", "numerical", "ascending", 1),  # missing -> own bin (PR/GU/VI)
    Feature("rate_spread", "numerical", "ascending", 1),
    Feature("loan_age", "numerical", "auto", 0),  # hazard is hump-shaped
    Feature("num_units", "state", constraint=1, splits=(1.5,)),  # 1 / 2+
    # 1 / 2+: before 2018Q2 Freddie coded 2 as "more than one borrower", so 2 vs 3+ is not usable
    Feature("num_borrowers", "state", constraint=-1, splits=(1.5,)),
    # never (special bin) / 0 / 1-3 / 4-12 / 13+ months since the last 30+ dpd month
    Feature("months_since_30dpd", "state", constraint=-1, splits=(0.5, 3.5, 12.5)),
    Feature("max_dlq_12m", "state", constraint=1, splits=(0.5, 1.5)),  # none / 30-59 / 60+
    # current / 30-59 / 60-89 (XX missing). 60-89 dpd is 0.26% of snapshots but has ~18,700
    # defaults and a 69% default rate: it keeps its bin (rare but not thin).
    Feature("current_dpd", "state", constraint=1, splits=(0.5, 1.5)),
    # 0 never / 1 cured 13+ / 2 cured 4-12 / 3 cured 1-3 months ago / 4 30-59 dpd / 5 60-89 dpd
    Feature("dlq_state", "state", constraint=1, splits=(0.5, 1.5, 2.5, 3.5, 4.5), dummy=True),
    Feature("harp_loan", "state", splits=(0.5,)),
    Feature("ever_deferred", "state", constraint=1, splits=(0.5,)),
    Feature("ever_modified", "state", constraint=1, splits=(0.5,)),
    Feature("occupancy_status", "categorical"),  # P / S / I
    Feature("loan_purpose", "categorical"),
    Feature("property_type", "categorical"),
    Feature("channel", "categorical"),  # R retail / TPO third party
    Feature("first_time_homebuyer", "categorical"),
]
BY_NAME = {f.name: f for f in FEATURES}
CATEGORICAL = [f.name for f in FEATURES if f.kind == "categorical"]
DELINQUENCY = [
    "dlq_state",
    "current_dpd",
    "months_since_30dpd",
    "max_dlq_12m",
    "ever_deferred",
    "ever_modified",
]
DLQ_STATE_LABELS = [
    "never 30+ dpd",
    "cured 13+ months",
    "cured 4-12 months",
    "cured 1-3 months",
    "30-59 dpd",
    "60-89 dpd",
]
DERIVED = ["current_dpd", "dlq_state"]  # built in _common from dpd_bucket
DPD_ORDINAL = {"current": 0, "30-59": 1, "60-89": 2}  # 'unknown' (XX) -> missing

# columns read from the PD dataset to build the features
SOURCE_COLUMNS = [f.name for f in FEATURES if f.name not in DERIVED] + ["dpd_bucket"]


def scorecard_frame(df: pd.DataFrame, names: list[str] | None = None) -> pd.DataFrame:
    """Raw dataset columns -> scorecard inputs (special code for 'never 30+ dpd')."""
    names = names or [f.name for f in FEATURES]
    x = _common(df)
    x["months_since_30dpd"] = x["months_since_30dpd"].fillna(NEVER_30DPD)
    return x[names]


def lgbm_frame(
    df: pd.DataFrame, names: list[str], categories: dict[str, list[str]] | None = None
) -> pd.DataFrame:
    """Raw dataset columns -> LightGBM inputs (categoricals as fixed pandas categories)."""
    x = _common(df)
    x["months_since_30dpd"] = x["months_since_30dpd"].fillna(NEVER_30DPD_LGBM)
    for c in CATEGORICAL:
        if c in names:
            cats = (categories or {}).get(c) or sorted(x[c].dropna().unique())
            x[c] = pd.Categorical(x[c], categories=cats)
    return x[names]


def _common(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["current_dpd"] = x["dpd_bucket"].map(DPD_ORDINAL).astype(float)
    x["dlq_state"] = dlq_state(x["current_dpd"], x["months_since_30dpd"])
    for c in ["harp_loan", "ever_deferred", "ever_modified"]:
        x[c] = x[c].astype(float)
    for c in CATEGORICAL:
        x[c] = x[c].astype(object).where(x[c].notna(), np.nan)
    x["channel"] = x["channel"].replace(dict.fromkeys(THIRD_PARTY_CODES, THIRD_PARTY))
    return x


def dlq_state(current_dpd: pd.Series, months_since_30dpd: pd.Series) -> pd.Series:
    """Ordered delinquency state 0-5 (DLQ_STATE_LABELS); missing if the dpd status is unknown."""
    m = months_since_30dpd.astype(float)
    cured = np.select([m.isna(), m > 12, m > 3], [0.0, 1.0, 2.0], 3.0)
    state = np.select(
        [current_dpd.isna(), current_dpd >= 2, current_dpd >= 1], [np.nan, 5.0, 4.0], cured
    )
    return pd.Series(state, index=current_dpd.index)
