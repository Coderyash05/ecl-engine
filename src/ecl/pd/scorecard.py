"""Champion 12-month PD: weight-of-evidence (WoE) logistic scorecard.

How it works: each feature is cut into bins (optbinning). Continuous features: optimal bins with
a monotonic default rate where it makes business sense, each bin >= 5% of weighted snapshots.
Delinquency states, flags and categoricals: their natural categories, merged only when a category
is too small to estimate (< 0.5% of weighted snapshots AND < 500 defaults) — a 5% minimum would
erase the delinquency states that matter most for Stage 2 PDs. Missing values and "never 30+
dpd" get their own bins.
Each bin is replaced by its WoE = ln(share of non-defaults / share of defaults), so a higher
WoE means safer and every logistic coefficient on WoE should be negative. A logistic
regression on the WoE values gives log-odds of default. Features marked `dummy` (dlq_state)
enter as one indicator per bin instead (base = first bin, "never 30+ dpd"): each state has its
own coefficient, which should be positive and rise with severity, and the fitted PD of every
state equals its observed default rate in the training sample. Points rescale the log-odds:

    score = OFFSET + FACTOR x ln(odds good:bad),  FACTOR = PDO / ln 2,
    OFFSET = BASE_SCORE - FACTOR x ln(BASE_ODDS)   -> 600 points at 50:1, +20 points doubles odds

Feature selection (documented choices, not RBI-prescribed): drop IV < 0.02, flag IV > 0.5 as
suspiciously strong; drop the weaker of any pair with |corr(WoE)| > 0.7; then drop the highest
VIF while any VIF > 5; then drop any feature whose coefficient has the wrong (positive) sign.
Correlations and VIFs use the sampling weights, so they describe the population, not the
default-enriched sample.
"""

from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from optbinning import BinningProcess
from sklearn.linear_model import LogisticRegression

from ecl.pd.features import BY_NAME, NEVER_30DPD

MIN_BIN_SIZE = 0.05  # continuous features
STATE_MIN_SHARE, STATE_MIN_DEFAULTS = 0.005, 500  # state / flag / categorical: merge below both
IV_MIN, IV_SUSPICIOUS = 0.02, 0.5
CORR_MAX, VIF_MAX = 0.7, 5.0
BASE_SCORE, BASE_ODDS, PDO = 600, 50, 20
FACTOR = PDO / math.log(2)
OFFSET = BASE_SCORE - FACTOR * math.log(BASE_ODDS)
WOE_TRANSFORM = {"metric": "woe", "metric_special": "empirical", "metric_missing": "empirical"}


def _is_small(weight: float, defaults: float, total: float) -> bool:
    """Rare AND thin. The default count governs how stable a bin's WoE is, so a rare bin with
    enough defaults (60-89 dpd: 0.26% of snapshots, ~18,700 defaults) stands alone."""
    return weight < STATE_MIN_SHARE * total and defaults < STATE_MIN_DEFAULTS


def state_splits(
    v: pd.Series, y: pd.Series, w: pd.Series, splits: tuple[float, ...]
) -> tuple[list[float], list[str]]:
    """Natural bin edges of an ordered state feature after merging small bins.

    While any bin is small, the smallest one is merged into the adjacent bin with the closer
    default rate (its edge is removed). Returns the remaining edges and a note per merge."""
    ok = (v.notna() & (v != NEVER_30DPD)).values
    vv, yy, ww = v.values[ok].astype(float), y.values[ok].astype(float), w.values[ok]
    edges, notes, total = list(splits), [], float(w.sum())
    while edges:
        idx = np.digitize(vv, edges)
        wt = np.bincount(idx, ww, len(edges) + 1)
        ev = np.bincount(idx, ww * yy, len(edges) + 1)
        small = [i for i in range(len(wt)) if _is_small(wt[i], ev[i], total)]
        if not small:
            break
        i = min(small, key=lambda k: wt[k])
        rate = ev / np.maximum(wt, 1e-12)
        j = min(
            [k for k in (i - 1, i + 1) if 0 <= k < len(wt)], key=lambda k: abs(rate[k] - rate[i])
        )
        edge = edges.pop(min(i, j))
        notes.append(
            f"edge {edge:g} removed: bin with {wt[i] / total:.3%} of snapshots, "
            f"{ev[i]:,.0f} defaults"
        )
    return edges, notes


def category_groups(v: pd.Series, y: pd.Series, w: pd.Series) -> tuple[list[list[str]], list[str]]:
    """One group per category; a small category joins the group with the closest default rate."""
    ok = v.notna().values
    g = (
        pd.DataFrame(
            {"v": v.values[ok], "w": w.values[ok], "e": (w.values * y.values.astype(float))[ok]}
        )
        .groupby("v")[["w", "e"]]
        .sum()
    )
    groups = [([c], r.w, r.e) for c, r in g.iterrows()]
    notes, total = [], float(w.sum())
    while len(groups) > 1:
        small = [i for i, (_, wt, ev) in enumerate(groups) if _is_small(wt, ev, total)]
        if not small:
            break
        i = min(small, key=lambda k: groups[k][1])
        cats, wt, ev = groups.pop(i)
        j = min(
            range(len(groups)), key=lambda k: abs(groups[k][2] / groups[k][1] - ev / max(wt, 1e-12))
        )
        notes.append(
            f"{'+'.join(cats)} merged with {'+'.join(groups[j][0])}: "
            f"{wt / total:.3%} of snapshots, {ev:,.0f} defaults"
        )
        groups[j] = (groups[j][0] + cats, groups[j][1] + wt, groups[j][2] + ev)
    return [sorted(c) for c, _, _ in groups], notes


def binning_policy(
    x: pd.DataFrame, y: pd.Series, w: pd.Series, names: list[str]
) -> tuple[dict, pd.DataFrame]:
    """optbinning parameters per feature (policy: see features.py) and the log of merges."""
    params, log = {}, []
    for n in names:
        f = BY_NAME[n]
        if f.kind == "numerical":
            params[n] = {"monotonic_trend": f.trend}
            continue
        if f.kind == "state":
            edges, notes = state_splits(x[n], y, w, f.splits)
            user = np.array(edges, dtype=float)
        else:
            edges, notes = category_groups(x[n], y, w)
            user = np.empty(len(edges), dtype=object)
            user[:] = [np.array(g, dtype=object) for g in edges]
            edges = edges if len(edges) > 1 else []
        log += [(n, note) for note in notes]
        if len(edges):  # fixed natural bins
            params[n] = {
                "user_splits": user,
                "user_splits_fixed": [True] * len(user),
                "monotonic_trend": None,
                "min_bin_size": None,
            }
        else:  # nothing large enough to stand alone -> one bin, IV 0
            params[n] = {"max_n_bins": 1}
            log.append((n, "single bin: no category large enough to stand alone"))
    return params, pd.DataFrame(log, columns=["feature", "merge"])


def fit_binning(x: pd.DataFrame, y: pd.Series, w: pd.Series, names: list[str]) -> BinningProcess:
    """Fit the WoE binning of every feature under the binning policy (minimum bin size, monotonic
    trends, natural state bins)."""
    params, _ = binning_policy(x, y, w, names)
    bp = BinningProcess(
        names,
        categorical_variables=[n for n in names if BY_NAME[n].kind == "categorical"],
        min_bin_size=MIN_BIN_SIZE,
        special_codes=[NEVER_30DPD],
        binning_fit_params=params,
        n_jobs=8,
    )
    return bp.fit(x[names], y.astype(int).values, sample_weight=w.values)


def iv_table(bp: BinningProcess) -> pd.DataFrame:
    """Information value per feature, flagged below the drop threshold or above the suspicious
    threshold."""
    s = bp.summary()[["name", "dtype", "n_bins", "iv", "gini"]].copy()
    s["iv_flag"] = np.select(
        [s.iv < IV_MIN, s.iv > IV_SUSPICIOUS],
        [f"drop: IV < {IV_MIN}", f"suspicious: IV > {IV_SUSPICIOUS}"],
        "",
    )
    return s.sort_values("iv", ascending=False).reset_index(drop=True)


def woe(bp: BinningProcess, x: pd.DataFrame) -> pd.DataFrame:
    """WoE-transformed features of `x`."""
    return bp.transform(x[list(bp.variable_names)], **WOE_TRANSFORM)


def weighted_corr(w_df: pd.DataFrame, weights: np.ndarray | None = None) -> pd.DataFrame:
    """(Weighted) correlation matrix of the WoE features."""
    c = np.atleast_2d(np.cov(w_df.values, rowvar=False, aweights=weights))
    sd = np.sqrt(np.diag(c))
    return pd.DataFrame(c / np.outer(sd, sd), index=w_df.columns, columns=w_df.columns)


def select_features(
    iv: pd.DataFrame, w_df: pd.DataFrame, weights: np.ndarray | None = None
) -> tuple[list[str], pd.DataFrame]:
    """IV -> correlation -> VIF. Returns kept features and a log of every decision."""
    log = []
    kept = []
    cm = weighted_corr(w_df[list(iv.name[iv.iv >= IV_MIN])], weights).abs()
    for r in iv.itertuples():
        if r.iv < IV_MIN:
            log.append((r.name, "dropped", f"IV {r.iv:.4f} < {IV_MIN}"))
            continue
        corr = {k: cm.loc[r.name, k] for k in kept}
        clash = [k for k, c in corr.items() if c > CORR_MAX]
        if clash:
            log.append(
                (r.name, "dropped", f"|corr| {corr[clash[0]]:.2f} with {clash[0]} (higher IV)")
            )
            continue
        kept.append(r.name)
    while len(kept) > 1:
        vifs = vif_table(w_df[kept], weights)
        worst = vifs.iloc[0]
        if worst.vif <= VIF_MAX:
            break
        kept.remove(worst.feature)
        log.append((worst.feature, "dropped", f"VIF {worst.vif:.1f} > {VIF_MAX}"))
    log += [(k, "kept", "") for k in kept]
    return kept, pd.DataFrame(log, columns=["feature", "decision", "reason"])


def vif_table(w_df: pd.DataFrame, weights: np.ndarray | None = None) -> pd.DataFrame:
    """VIF per feature = 1 / (1 - R2 of the feature on the others) = diagonal of the inverse
    (weighted) correlation matrix."""
    vifs = np.diag(np.linalg.inv(weighted_corr(w_df, weights).values))
    return (
        pd.DataFrame({"feature": w_df.columns, "vif": vifs})
        .sort_values("vif", ascending=False)
        .reset_index(drop=True)
    )


def state_index(bp: BinningProcess, x: pd.DataFrame, f: str) -> np.ndarray:
    """Bin number of a dummy-coded state feature (0 = base bin); -1 where the state is missing."""
    v = x[f].values.astype(float)
    return np.where(np.isnan(v), -1, np.digitize(v, bp.get_binned_variable(f).splits))


def design_matrix(
    bp: BinningProcess, x: pd.DataFrame, feats: list[str]
) -> tuple[np.ndarray, list[tuple[str, int]]]:
    """Regression columns: WoE for ordinary features (key (f, 0)); for a dummy feature one
    indicator per non-base bin (key (f, bin number))."""
    w = woe(bp, x)
    cols, keys = [], []
    for f in feats:
        if not BY_NAME[f].dummy:
            cols.append(w[f].values)
            keys.append((f, 0))
            continue
        idx = state_index(bp, x, f)
        if (idx < 0).any():
            raise ValueError(f"{f}: missing values cannot be dummy-coded")
        for k in range(1, len(bp.get_binned_variable(f).splits) + 1):
            cols.append((idx == k).astype(float))
            keys.append((f, k))
    return np.column_stack(cols), keys


@dataclass
class WoEScorecard:
    """Champion 12-month TTC PD model: logistic regression on WoE-binned features, with dummy
    coefficients for state features entered as dummies (the delinquency state). Stores the
    binning, coefficients and the feature-selection log."""

    binning: BinningProcess
    features: list[str]
    intercept: float
    coefs: dict[str, float]  # WoE features: one coefficient each
    selection_log: list[tuple[str, str, str]] = field(default_factory=list)
    # dummy features: coefficient per bin, base bin first (= 0)
    state_coefs: dict[str, list[float]] = field(default_factory=dict)

    def woe(self, x: pd.DataFrame) -> pd.DataFrame:
        """WoE values of the model's features."""
        return woe(self.binning, x)[self.features]

    def logit(self, x: pd.DataFrame) -> np.ndarray:
        """Intercept + coefficient x WoE (+ the coefficient of the loan's state for dummy
        features). A missing state cannot be scored: NaN."""
        w = self.woe(x)
        z = np.full(len(x), self.intercept)
        for f in self.features:
            if f in self.state_coefs:
                z += np.array([*self.state_coefs[f], np.nan])[state_index(self.binning, x, f)]
            else:
                z += self.coefs[f] * w[f].values
        return z

    def states_monotonic(self) -> bool:
        """Dummy coefficients are positive and rise with the order of the states."""
        return all(np.all(np.diff(c) > 0) for c in self.state_coefs.values())

    def state_bins(self, f: str) -> list[str]:
        """Bin labels of dummy feature `f`, in coefficient order (base bin first)."""
        t = self.binning.get_binned_variable(f).binning_table.build()
        return [str(b) for b in t["Bin"].iloc[: len(self.state_coefs[f])]]

    def predict_pd(self, x: pd.DataFrame) -> np.ndarray:
        """12-month TTC PD = logistic(logit(x))."""
        return 1.0 / (1.0 + np.exp(-self.logit(x)))

    def score(self, x: pd.DataFrame) -> np.ndarray:
        """Points: ln(odds good:bad) = -logit(PD)."""
        return OFFSET - FACTOR * self.logit(x)

    def points_table(self) -> pd.DataFrame:
        """Points per bin: -(beta x WoE + intercept / n) x FACTOR + OFFSET / n; for a dummy
        feature beta x WoE is replaced by the coefficient of the state."""
        n = len(self.features)
        rows = []
        for f in self.features:
            t = self.binning.get_binned_variable(f).binning_table.build()
            t = t[t.index != "Totals"]
            states = self.state_coefs.get(f)
            for i, (_, b) in enumerate(t.iterrows()):
                w = float(b["WoE"]) if b["WoE"] != "" else 0.0
                if states is not None and i >= len(states):
                    continue  # special / missing: not scored for states
                logit = states[i] if states is not None else self.coefs[f] * w
                pts = -(logit + self.intercept / n) * FACTOR + OFFSET / n
                label = b["Bin"] if isinstance(b["Bin"], str) else " / ".join(map(str, b["Bin"]))
                rows.append((f, label, b["Count"], b["Event rate"], w, pts))
        return pd.DataFrame(
            rows, columns=["feature", "bin", "count", "event_rate", "woe", "points"]
        )

    def save(self, path: Path) -> None:
        """Pickle the scorecard to `path`."""
        path.write_bytes(pickle.dumps(self))

    @staticmethod
    def load(path: Path) -> WoEScorecard:
        """Load a pickled scorecard from `path`."""
        return pickle.loads(path.read_bytes())


def fit_scorecard(x: pd.DataFrame, y: pd.Series, w: pd.Series, features: list[str]) -> WoEScorecard:
    """Bin the chosen features, fit an unpenalised weighted logistic regression on WoE (dummy
    features: on bin indicators), and drop wrong-sign WoE features (coefficient >= 0) one at a
    time until all signs are as expected. Dummy coefficients are checked with
    WoEScorecard.states_monotonic(), never forced."""
    log = []
    feats = list(features)
    while True:
        bp = fit_binning(x, y, w, feats)
        xd, keys = design_matrix(bp, x, feats)
        lr = LogisticRegression(C=np.inf, max_iter=5000, tol=1e-8)  # unpenalised
        lr.fit(xd, y.astype(int).values, sample_weight=w.values)
        coefs = {f: c for (f, k), c in zip(keys, lr.coef_[0]) if not BY_NAME[f].dummy}
        states = {
            f: [0.0, *[c for (g, _), c in zip(keys, lr.coef_[0]) if g == f]]
            for f in feats
            if BY_NAME[f].dummy
        }
        wrong = [f for f, c in coefs.items() if c >= 0]
        if not wrong:
            return WoEScorecard(bp, feats, float(lr.intercept_[0]), coefs, log, states)
        worst = max(wrong, key=lambda f: coefs[f])
        log.append((worst, "dropped", f"wrong sign: coefficient {coefs[worst]:+.3f} >= 0"))
        feats.remove(worst)
