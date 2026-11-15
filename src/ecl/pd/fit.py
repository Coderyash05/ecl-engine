"""
Module 2b: fit and evaluate the 12-month TTC PD (target B-18).

Usage:
    ecl train pd-12m

Reads data/processed/pd_dataset/. Writes model artefacts to models/pd_12m/, aggregate tables
and the model card to reports/summary/pd_12m_*, and per-loan PD at origination to
data/processed/pd_at_origination/ (loan-level, gitignored). Logic lives in src/ecl/pd/.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ecl.common import CODE_AND_REGULATORY_CONFIG, git_state, md_table, project_root
from ecl.pd import challenger, metrics
from ecl.pd.features import (
    BY_NAME,
    CATEGORICAL,
    DELINQUENCY,
    DLQ_STATE_LABELS,
    FEATURES,
    SOURCE_COLUMNS,
    lgbm_frame,
    scorecard_frame,
)
from ecl.pd.origination import origination_frame, score_at_origination
from ecl.pd.sampling import NON_DEFAULT_RATE, SAMPLE_SEED, load_sample, load_split
from ecl.pd.scorecard import (
    BASE_ODDS,
    BASE_SCORE,
    CORR_MAX,
    IV_MIN,
    IV_SUSPICIOUS,
    MIN_BIN_SIZE,
    PDO,
    STATE_MIN_DEFAULTS,
    STATE_MIN_SHARE,
    VIF_MAX,
    binning_policy,
    fit_binning,
    fit_scorecard,
    iv_table,
    select_features,
    vif_table,
    weighted_corr,
    woe,
)

if TYPE_CHECKING:
    import lightgbm as lgb
    from numpy.typing import ArrayLike

    from ecl.pd.scorecard import WoEScorecard

ROOT = project_root()

VERSION = "pd12m-1.2.1"
PREVIOUS = "v1.1.0"  # superseded artefacts kept in models/pd_12m/v1.1.0/ (see CHANGELOG.md);
# 1.2.1 is a patch of 1.2.0 (numerically identical), so the comparison stays against v1.1.0
# Candidate overlays (para 131): monitoring triggers proposed by the developer, to be confirmed
# by the model owner / validation (Module 11). Not RBI values. No overlay is applied.
RELIEF_SHARE_TRIGGER = 0.15  # relief share of 30-89 dpd loan-months (2014-19 maximum: 7%)
OVER_PREDICTION_TRIGGER = 0.70  # actual / predicted default rate, 30-89 dpd
UNDER_PREDICTION_TRIGGER = 1.25  # actual / predicted default rate, ever-deferred loans
MIN_DEFAULTS_TRIGGER = 100  # defaults needed before a ratio is acted on
PROCESSED = ROOT / "data" / "processed"
DATASET = PROCESSED / "pd_dataset"
MODEL_DIR = ROOT / "models" / "pd_12m"
REPORTS = ROOT / "reports" / "summary"
EVAL_SPLITS = ["dev_holdout", "oot1", "oot2", "oot3"]
TARGET_COLS = ["target_b18", "target_b12", "target_a", "elig_a", "elig_b12"]
SENSITIVITIES = {"a": ("target_a", "elig_a"), "b12": ("target_b12", "elig_b12")}
logger = logging.getLogger(__name__)


def relief_share_by_year() -> pd.DataFrame:
    """Share of 30-89 dpd loan-months under forbearance / deferral / disaster relief, by year
    (relief fields exist from 2014): the leading indicator for the forbearance overlay."""
    import duckdb

    return duckdb.sql(f"""
        SELECT year(period) AS year, COUNT(*) AS loan_months_30_89_dpd,
               AVG(relief_flag::INT) AS relief_share
        FROM read_parquet('{(PROCESSED / "panel").as_posix()}/*/*.parquet', hive_partitioning = true)
        WHERE dpd_bucket IN ('30-59', '60-89') AND year(period) >= 2014
        GROUP BY 1 ORDER BY 1""").df()


def population_counts() -> tuple[int, int]:
    """Snapshots and B-18 defaults in the full dev_train population (to check the sample's
    weighted default rate)."""
    import duckdb

    return duckdb.sql(f"""SELECT COUNT(*), SUM(target_b18::INT) FROM read_parquet(
        '{DATASET.as_posix()}/*/*.parquet', hive_partitioning = true)
        WHERE split = 'dev_train'""").fetchall()[0]


def sample_report(train: pd.DataFrame) -> pd.DataFrame:
    """Development sample against its population: sizes, default rates, sampling rate, seed and
    weights."""
    pop_n, pop_d = population_counts()
    d = train.target_b18
    return pd.DataFrame(
        [
            {
                "population_snapshots": pop_n,
                "population_defaults": pop_d,
                "population_default_rate": pop_d / pop_n,
                "non_default_sampling_rate": NON_DEFAULT_RATE,
                "sample_seed": SAMPLE_SEED,
                "sample_rows": len(train),
                "sample_defaults": int(d.sum()),
                "sample_non_defaults": int((~d).sum()),
                "weight_defaults": 1.0,
                "weight_non_defaults": 1 / NON_DEFAULT_RATE,
                "weighted_rows": train.weight.sum(),
                "weighted_default_rate": np.average(d, weights=train.weight),
            }
        ]
    )


def evaluate(models: dict, cats: dict, base: dict) -> dict[str, pd.DataFrame]:
    """One pass over each evaluation split: metrics, calibration, Gini by year, PSI."""
    rows, calib, by_year, psi_rows, by_state, by_flag = [], [], [], [], [], []
    labels = np.array([*DLQ_STATE_LABELS, "dpd unknown"])
    champion, booster = models["champion"], models["challenger"]
    for split in EVAL_SPLITS:
        df = load_split(DATASET, split, SOURCE_COLUMNS + TARGET_COLS)
        logger.info(f"  scoring {split}: {len(df):,} snapshots")
        xs = scorecard_frame(df)
        preds = {
            "champion": champion.predict_pd(xs),
            "challenger": challenger.predict_pd(booster, lgbm_frame(df, champion.features, cats)),
        }
        score = champion.score(xs)
        y = df.target_b18.astype(int).values
        for name, p in preds.items():
            rows.append({"split": split, "model": name, "target": "b18", **summary(y, p)})
            t = metrics.calibration_table(y, p)
            calib.append(t.assign(split=split, model=name))
        # calibration by delinquency state: the PDs that drive Stage 2 and SICR
        state = labels[xs.dlq_state.fillna(len(DLQ_STATE_LABELS)).astype(int).values]
        st = (
            pd.DataFrame({"state": state, "y": y, **preds})
            .groupby("state")
            .agg(
                n=("y", "size"),
                defaults=("y", "sum"),
                actual_rate=("y", "mean"),
                pd_champion=("champion", "mean"),
                pd_challenger=("challenger", "mean"),
            )
            .reindex(labels)
            .dropna(subset=["n"])
            .reset_index()
        )
        st.insert(0, "split", split)
        by_state.append(st)
        # flags too rare in dev_train to get a bin: are these loans under-predicted?
        for flag in ["ever_modified", "ever_deferred"]:
            m = df[flag].fillna(False).values.astype(bool)
            by_flag.append(
                {
                    "split": split,
                    "flag": flag,
                    "n": int(m.sum()),
                    "defaults": int(y[m].sum()),
                    "actual_rate": y[m].mean() if m.any() else np.nan,
                    "pd_champion": preds["champion"][m].mean() if m.any() else np.nan,
                    "pd_challenger": preds["challenger"][m].mean() if m.any() else np.nan,
                }
            )
        year = pd.to_datetime(df.obs_date).dt.year.values
        by_year.append(pd.DataFrame({"year": year, "y": y, **preds}))
        # sensitivity models on their own target and population
        for key, (target, elig) in SENSITIVITIES.items():
            m = df[elig].values
            p = models[f"champion_{key}"].predict_pd(xs[m])
            rows.append(
                {
                    "split": split,
                    "model": f"champion_{key}",
                    "target": key,
                    **summary(df.loc[m, target].astype(int).values, p),
                }
            )
        # PSI dev_train -> split: champion score deciles, challenger PD deciles, each feature
        if split != "dev_holdout":
            psi_rows.append(
                (
                    split,
                    "score (champion)",
                    metrics.psi(
                        base["score"], metrics.shares(np.digitize(score, base["score_edges"]))
                    ),
                )
            )
            psi_rows.append(
                (
                    split,
                    "pd (challenger)",
                    metrics.psi(
                        base["lgbm"],
                        metrics.shares(np.digitize(preds["challenger"], base["lgbm_edges"])),
                    ),
                )
            )
            bins = champion.binning.transform(xs[champion.features], metric="bins")
            for f in champion.features:
                psi_rows.append(
                    (split, f, metrics.psi(base["features"][f], metrics.shares(bins[f])))
                )
        del df, xs
    yr = pd.concat(by_year)
    gby = (
        yr.groupby("year")
        .apply(
            lambda g: pd.Series(
                {
                    "snapshots": len(g),
                    "default_rate": g.y.mean(),
                    "gini_champion": metrics.gini(g.y, g.champion) if g.y.nunique() > 1 else np.nan,
                    "gini_challenger": metrics.gini(g.y, g.challenger)
                    if g.y.nunique() > 1
                    else np.nan,
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    psi = (
        pd.DataFrame(psi_rows, columns=["split", "item", "psi"])
        .pivot(index="item", columns="split", values="psi")
        .reset_index()
    )
    return {
        "metrics": pd.DataFrame(rows),
        "calibration": pd.concat(calib),
        "gini_by_year": gby,
        "psi": psi,
        "calibration_by_state": pd.concat(by_state),
        "calibration_by_flag": pd.DataFrame(by_flag),
    }


def coefficient_table(champion: WoEScorecard, iv: pd.DataFrame, vifs: pd.DataFrame) -> pd.DataFrame:
    """One row per WoE feature and one row per state of a dummy feature (base state = 0)."""
    rows = [("intercept", "", "", champion.intercept, "")]
    for f in champion.features:
        if f not in champion.state_coefs:
            rows.append((f, f, "", champion.coefs[f], "negative (on WoE)"))
            continue
        c = champion.state_coefs[f]
        labels = (
            DLQ_STATE_LABELS
            if f == "dlq_state" and len(c) == len(DLQ_STATE_LABELS)
            else champion.state_bins(f)
        )
        rows += [
            (f"{f}: {lab}", f, lab, v, "0 (base)" if i == 0 else "positive, rising")
            for i, (lab, v) in enumerate(zip(labels, c))
        ]
    t = pd.DataFrame(rows, columns=["term", "feature", "state", "coefficient", "expected_sign"])
    t["odds_ratio_vs_base"] = np.where(t.state != "", np.exp(t.coefficient), np.nan)
    t = (
        t.merge(iv[["name", "iv", "n_bins"]], left_on="feature", right_on="name", how="left")
        .merge(vifs, on="feature", how="left")
        .drop(columns=["name", "feature", "state"])
    )
    return t[["term", "coefficient", "odds_ratio_vs_base", "iv", "n_bins", "vif", "expected_sign"]]


def with_previous(by_state: pd.DataFrame) -> pd.DataFrame:
    """Calibration by delinquency state next to the superseded version's PD."""
    prev = pd.read_csv(MODEL_DIR / PREVIOUS / "calibration_by_state.csv")
    prev = prev[["split", "state", "pd_champion"]].rename(
        columns={"pd_champion": f"pd_champion_{PREVIOUS}"}
    )
    out = by_state.merge(prev, on=["split", "state"], how="left")
    out["actual_to_predicted"] = out.actual_rate / out.pd_champion
    return out


def overlay_section(by_state: pd.DataFrame, by_flag: pd.DataFrame, relief: pd.DataFrame) -> str:
    """Known limitations recorded as candidate overlays (para 131): evidence, direction of the
    bias and a monitoring trigger. Nothing is applied to the PDs."""
    dl = by_state[
        by_state.state.isin(["30-59 dpd", "60-89 dpd"]) & (by_state.split != "dev_holdout")
    ]
    dl = dl[
        ["split", "state", "n", "defaults", "actual_rate", "pd_champion", "actual_to_predicted"]
    ]
    fl = by_flag[by_flag.flag == "ever_deferred"].copy()
    fl["actual_to_predicted"] = fl.actual_rate / fl.pd_champion
    fl = fl[["split", "n", "defaults", "actual_rate", "pd_champion", "actual_to_predicted"]]
    return f"""## Known limitations recorded as candidate overlays (RBI para 131)
**No overlay is applied to the PDs.** Each item records the evidence, the direction of the bias
and a monitoring trigger. The trigger levels are proposed by the developer and are not RBI
values; they are to be confirmed by the model owner and validation (Module 11). If a trigger is
hit, an overlay needs its own justification, calculation and approval (Annex 4 Table 6).

### CO-1: delinquent loans in a mass-forbearance period (COVID, OOT2)
- **Evidence** (30-59 and 60-89 dpd snapshots, target B-18):

{md_table(dl)}

  Share of 30-89 dpd loan-months under relief (forbearance / deferral / disaster), by year:

{md_table(relief)}
- **Direction:** PD too high (conservative) for 30-89 dpd loans while relief is widespread:
  arrears under forbearance that cure within 18 months are not defaults under B-18, and the
  development window has almost no such loans (relief fields start in 2014).
- **Monitoring trigger:** relief share of 30-89 dpd loan-months above
  {RELIEF_SHARE_TRIGGER:.0%} in a quarter (leading), or actual / predicted default rate of
  30-89 dpd loans below {OVER_PREDICTION_TRIGGER:.2f} in two consecutive labelled quarters with
  at least {MIN_DEFAULTS_TRIGGER} defaults (lagging).

### CO-2: loans with a payment deferral (ever_deferred)
- **Evidence** (the flag has 5 snapshots in development, so the model cannot see it):

{md_table(fl)}
- **Direction:** PD too low outside mass-relief periods (OOT1: deferral granted to a borrower
  in difficulty); too high when deferral is granted widely (OOT2). The binding risk is the
  under-prediction.
- **Monitoring trigger:** actual / predicted default rate of ever-deferred loans above
  {UNDER_PREDICTION_TRIGGER:.2f} over the last four labelled quarters with at least
  {MIN_DEFAULTS_TRIGGER} defaults; and at any refit, add ever_deferred as a candidate once it
  has {STATE_MIN_DEFAULTS} defaults in the development sample (binning policy).
"""


def version_change(mets: pd.DataFrame, psi: pd.DataFrame) -> pd.DataFrame:
    """Gini, mean PD and score PSI of this version against the superseded one."""
    prev = pd.read_csv(MODEL_DIR / PREVIOUS / "metrics.csv")
    key = ["split", "model"]
    cols = [*key, "default_rate", "gini", "mean_pd"]
    c = mets.loc[mets.target == "b18", cols].merge(
        prev.loc[prev.target == "b18", [*key, "gini", "mean_pd"]], on=key, suffixes=("", "_prev")
    )
    c["delta_gini"] = c.gini - c.gini_prev
    c["delta_mean_pd"] = c.mean_pd - c.mean_pd_prev
    item = {"champion": "score (champion)", "challenger": "pd (challenger)"}
    old_psi = pd.read_csv(MODEL_DIR / PREVIOUS / "psi.csv").set_index("item")
    new_psi = psi.set_index("item")
    for name, src in [("psi", new_psi), ("psi_prev", old_psi)]:
        c[name] = [
            src.loc[item[m], s] if s in src.columns else np.nan for s, m in zip(c.split, c.model)
        ]
    return c


def summary(y: ArrayLike, p: ArrayLike, w: ArrayLike | None = None) -> dict:
    """Count, defaults, default rate, mean PD, Gini, KS and Brier score."""
    return {
        "n": len(y),
        "defaults": int(np.sum(y)),
        "default_rate": np.average(y, weights=w),
        "mean_pd": np.average(p, weights=w),
        "gini": metrics.gini(y, p, w),
        "ks": metrics.ks(y, p, w),
        "brier": metrics.brier(y, p, w),
    }


def psi_baseline(
    train: pd.DataFrame, champion: WoEScorecard, booster: lgb.Booster, cats: list[str]
) -> dict:
    """dev_train distributions for the PSI: score bins of the champion and the challenger, and
    the WoE bins of every feature."""
    xs = scorecard_frame(train)
    w = train.weight.values
    score = champion.score(xs)
    p_lgbm = challenger.predict_pd(booster, lgbm_frame(train, champion.features, cats))
    s_edges = metrics.weighted_quantile_edges(score, w)
    l_edges = metrics.weighted_quantile_edges(p_lgbm, w)
    bins = champion.binning.transform(xs[champion.features], metric="bins")
    return {
        "score_edges": s_edges,
        "score": metrics.shares(np.digitize(score, s_edges), w),
        "lgbm_edges": l_edges,
        "lgbm": metrics.shares(np.digitize(p_lgbm, l_edges), w),
        "features": {f: metrics.shares(bins[f], w) for f in champion.features},
    }


def model_card(
    meta: dict,
    sample: pd.DataFrame,
    iv: pd.DataFrame,
    coefs: pd.DataFrame,
    mets: pd.DataFrame,
    sens: pd.DataFrame,
    merges: pd.DataFrame,
    dlq_corr: pd.DataFrame,
    by_state: pd.DataFrame,
    by_flag: pd.DataFrame,
    change: pd.DataFrame,
    psi: pd.DataFrame,
    relief: pd.DataFrame,
) -> str:
    """Markdown model card of the 12-month PD model."""
    m = mets[mets.target == "b18"].pivot(index="split", columns="model", values="gini")
    git = meta["git"]
    tree = (
        "code and regulatory config committed"
        if git["clean"]
        else "WITH UNCOMMITTED CHANGES - not reproducible from this commit"
    )
    return f"""# Model card: 12-month PD ({VERSION})

**Code version.** git commit `{git["commit"]}` ({tree}); fitted {meta["trained_at"][:10]}.

**Purpose.** 12-month through-the-cycle probability of default for performing housing loans
(Stage 1 ECL, PD input to lifetime PD in Module 3, PD at initial recognition for SICR, RBI paras
25-27, 45, 96). Estimated on **US Freddie Mac data** — not an Indian risk estimate.

**These PDs are through-the-cycle.** The model has no macro variables and is developed on
2000-2016, which includes the 2007-11 housing crisis. Its level is the average over that cycle,
so it **over-predicts benign out-of-time periods by design** (mean PD vs actual: metrics table,
OOT1-OOT3) and would under-predict a crisis. This is not a calibration defect and is not
corrected here: Module 3 converts the TTC PD to point-in-time with the macro scenarios. The TTC
PDs must not be used as point-in-time PDs for ECL.

**Data.** Freddie Mac Single-Family Loan-Level sample, vintages 1999-2023 (2024-26 excluded:
not PD-OK). Quarterly snapshots of loans not in default; observation dates 2000-01 to
{meta["label_end"]} (data end {meta["data_end"]}). Development 2000-2016 (80% train / 20%
loan-level holdout), out-of-time OOT1 2017-19, OOT2 2020-21, OOT3 2022-23.

**Target.** B-18: RBI 90+ default (paras 6(5), 8(1)) within 12 months, except relief months
(forbearance / deferral / disaster) cured within 18 months with no loss — a post-2014 relief
adjustment (relief fields exist only from 2014). Sensitivities: A (RBI 90+, nothing relabelled)
and B-12.

**Training sample.** All {sample.sample_defaults[0]:,} defaults + {NON_DEFAULT_RATE:.0%} of
non-defaults (seed {SAMPLE_SEED}); non-default weight {1 / NON_DEFAULT_RATE:.3f}, so PDs stay on
the population scale (weighted default rate {sample.weighted_default_rate[0]:.4%} vs
population {sample.population_default_rate[0]:.4%}).

**Champion.** WoE logistic scorecard (optbinning). Binning policy: continuous features get
optimal bins of at least {MIN_BIN_SIZE:.0%} of weighted snapshots with monotonic trends where
they make business sense; delinquency states, flags and categoricals keep their natural
categories, merged only if a category is below {STATE_MIN_SHARE:.1%} of weighted snapshots
**and** below {STATE_MIN_DEFAULTS} defaults (the default count governs how stable a bin's
default rate is, so 60-89 dpd — 0.26% of snapshots, ~18,700 defaults — keeps its bin). Missing
values get their own bin. Selection: IV < {IV_MIN} dropped, IV > {IV_SUSPICIOUS} flagged;
|corr| > {CORR_MAX} and VIF > {VIF_MAX} dropped (both weighted to the population); wrong-sign
coefficients dropped. Points: {BASE_SCORE} at odds {BASE_ODDS}:1, {PDO} points to double the
odds (documented choice). No macro variables.

**Delinquency state.** current_dpd, months_since_30dpd and max_dlq_12m overlap by construction
(correlations below), so one ordered state, `dlq_state`, combines them: never 30+ dpd / cured
13+ / 4-12 / 1-3 months ago / 30-59 dpd / 60-89 dpd. It has the highest IV and the other three
are dropped by the correlation rule (screens use its WoE; the VIF shown for it is the WoE
column's). IV > {IV_SUSPICIOUS} is expected for a behavioural state observed at the snapshot
date (a 60-89 dpd loan is one missed payment from default); it is not target leakage.
`dlq_state` enters the regression as **dummy variables** (base = never 30+ dpd), every other
feature as WoE: each state has its own coefficient and its own points, and the fitted PD of each
state equals its default rate in the training sample. Dummy coefficients rise monotonically
with severity: **{meta["dlq_state_coefficients_monotonic"]}**.

**Changes from {PREVIOUS}** (see models/pd_12m/CHANGELOG.md): dlq_state dummy-coded instead of
one WoE column (one coefficient scaled all six states; 60-89 dpd was under-predicted); binning
policy amended from "rare or thin" to "rare and thin".

**Challenger.** LightGBM on the same features with matching monotone constraints, early
stopping on dev_holdout ({meta["lgbm_best_iteration"]} trees).

## Features (IV, selection)
{md_table(iv[["name", "n_bins", "iv", "iv_flag", "decision", "reason"]])}

## Categories merged by the binning policy
{md_table(merges)}

## Delinquency features: correlation of WoE (weighted)
{md_table(dlq_corr)}

## Coefficients (WoE features: negative; dlq_state dummies: positive and rising)
{md_table(coefs)}

## Calibration by delinquency state (target B-18)
{md_table(by_state)}

## Loans with flags that are rare in development (not in the model)
{md_table(by_flag)}

{overlay_section(by_state, by_flag, relief)}

## Change from {PREVIOUS} (target B-18; psi = score/PD PSI dev_train -> split)
{md_table(change)}

## PSI dev_train -> OOT
{md_table(psi)}

## Gini by split
{md_table(m.reset_index())}

## Metrics
{md_table(mets)}

## Sensitivity (champion refitted on other targets)
{md_table(sens)}

## Limitations
- US mortgage data and US house prices; Indian portfolios need recalibration (Module 12).
- TTC by construction (see top): mean PD exceeds the actual rate in every OOT split. Rank
  ordering holds; the level needs the point-in-time conversion of Module 3.
- Forbearance periods and deferred loans: see candidate overlays CO-1 and CO-2 above.
- The delinquency-state coefficients are fixed at their 2000-2016 values; state default rates
  move with the cycle (calibration by state, OOT splits).
- Relief fields exist only from 2014: B-18 equals A before 2014.
- Missing DTI is almost entirely HARP loans; HARP flag and missing-DTI bin overlap.
- Current LTV is indexed with FHFA state HPI (all-transactions, NSA); PR/GU/VI have no index
  (missing bin). Origination quarter approximated by first payment date - 1 month.
- 12-month PD rises with seasoning: SICR (Module 6) must adjust for loan age before applying a
  relative-PD threshold to PD at origination.
- Snapshots of the same loan are correlated; holdout is loan-level, OOT is by date.
- Not independently validated (RBI para 97/120-121: validation pending, Module 11).
"""


def fit_pd_model() -> None:
    """Fit the champion scorecard and the LightGBM challenger, evaluate them on every split,
    score every loan at origination (para 26) and save the artefacts and model card."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    cols = SOURCE_COLUMNS + TARGET_COLS

    logger.info("Loading dev_train sample")
    train = load_sample(DATASET, "dev_train", cols)
    sample = sample_report(train)
    logger.info(f"  {len(train):,} rows, {int(train.target_b18.sum()):,} defaults")

    logger.info("Binning all candidate features")
    x, y, w = scorecard_frame(train), train.target_b18, train.weight
    names = [f.name for f in FEATURES]
    merges = binning_policy(x, y, w, names)[1]
    bp_all = fit_binning(x, y, w, names)
    iv = iv_table(bp_all)
    woe_all = woe(bp_all, x)
    dlq = [n for n in DELINQUENCY if int(iv.loc[iv.name == n, "n_bins"].iloc[0]) > 1]
    dlq_corr = weighted_corr(woe_all[dlq], w.values).reset_index(names="feature")
    kept, sel = select_features(iv, woe_all, w.values)
    del woe_all
    logger.info(f"  kept after IV/corr/VIF: {kept}")

    logger.info("Fitting champion scorecard")
    champion = fit_scorecard(x, y, w, kept)
    sel = pd.concat(
        [
            sel[~sel.feature.isin([s[0] for s in champion.selection_log])],
            pd.DataFrame(champion.selection_log, columns=sel.columns),
        ]
    )
    iv = iv.merge(sel, left_on="name", right_on="feature", how="left").drop(columns="feature")
    vifs = vif_table(champion.woe(x), w.values)
    coefs = coefficient_table(champion, iv, vifs)
    logger.info(
        f"  final features: {champion.features}; dlq_state dummies rising: "
        f"{champion.states_monotonic()}"
    )

    logger.info("Fitting challenger (LightGBM)")
    cats = {c: sorted(train[c].dropna().unique()) for c in CATEGORICAL if c in champion.features}
    hold = load_split(DATASET, "dev_holdout", cols)
    booster = challenger.fit_lgbm(
        lgbm_frame(train, champion.features, cats),
        y,
        w,
        lgbm_frame(hold, champion.features, cats),
        hold.target_b18,
        seed=SAMPLE_SEED,
    )
    del hold
    logger.info(f"  best iteration {booster.best_iteration}")

    models = {"champion": champion, "challenger": booster}
    for key, (target, elig) in SENSITIVITIES.items():
        logger.info(f"Sensitivity: refitting champion on target {key}")
        tr = load_sample(DATASET, "dev_train", cols, target=target, population=elig)
        models[f"champion_{key}"] = fit_scorecard(
            scorecard_frame(tr), tr[target], tr.weight, champion.features
        )

    logger.info("Evaluating")
    base = psi_baseline(train, champion, booster, cats)
    ev = evaluate(models, cats, base)
    train_rows = [
        {
            "split": "dev_train (sample, weighted)",
            "model": name,
            "target": "b18",
            **summary(y.astype(int).values, p, w.values),
        }
        for name, p in [
            ("champion", champion.predict_pd(x)),
            (
                "challenger",
                challenger.predict_pd(booster, lgbm_frame(train, champion.features, cats)),
            ),
        ]
    ]
    mets = pd.concat([pd.DataFrame(train_rows), ev["metrics"]], ignore_index=True)
    b18 = mets[mets.model == "champion"].set_index("split")[["gini", "mean_pd"]]
    sens = mets[mets.model.str.startswith("champion_")].copy()
    sens = sens.join(b18, on="split", rsuffix="_b18")
    sens["delta_gini"] = sens.gini - sens.gini_b18
    sens["delta_mean_pd"] = sens.mean_pd - sens.mean_pd_b18
    sens = sens[
        [
            "split",
            "target",
            "n",
            "default_rate",
            "mean_pd",
            "gini",
            "gini_b18",
            "delta_gini",
            "mean_pd_b18",
            "delta_mean_pd",
        ]
    ]

    change = version_change(mets, ev["psi"])
    by_state = with_previous(ev["calibration_by_state"])
    relief = relief_share_by_year()

    logger.info("PD at origination for every loan")
    orig = score_at_origination(champion, origination_frame(PROCESSED), VERSION)
    out = PROCESSED / "pd_at_origination"
    out.mkdir(parents=True, exist_ok=True)
    orig.to_parquet(out / "data.parquet", index=False)
    logger.info(
        f"  {len(orig):,} loans; median PD at origination {orig.pd_at_origination.median():.4%}"
    )

    logger.info("Saving artefacts")
    data_end = str(pd.read_csv(REPORTS / "pd_dataset_by_split.csv").obs_end.max())[:10]
    meta = {
        "version": VERSION,
        "trained_at": datetime.now(UTC).isoformat(),
        "git": git_state(ROOT, CODE_AND_REGULATORY_CONFIG),
        "target": "target_b18",
        "features": champion.features,
        "dummy_features": list(champion.state_coefs),
        "dlq_state_coefficients_monotonic": champion.states_monotonic(),
        "previous_version": PREVIOUS,
        "binning": {
            "min_bin_size_continuous": MIN_BIN_SIZE,
            "state_min_share": STATE_MIN_SHARE,
            "state_min_defaults": STATE_MIN_DEFAULTS,
        },
        "non_default_sampling_rate": NON_DEFAULT_RATE,
        "sample_seed": SAMPLE_SEED,
        "label_end": data_end,
        "data_end": "2026-06-01",
        "lgbm_best_iteration": booster.best_iteration,
        "lgbm_params": challenger.PARAMS,
        "lgbm_monotone_constraints": {f: BY_NAME[f].constraint for f in champion.features},
        "scaling": {"base_score": BASE_SCORE, "base_odds": BASE_ODDS, "pdo": PDO},
    }
    champion.save(MODEL_DIR / "scorecard.pkl")
    booster.save_model(str(MODEL_DIR / "lgbm.txt"), num_iteration=booster.best_iteration)
    for key in SENSITIVITIES:
        models[f"champion_{key}"].save(MODEL_DIR / f"scorecard_target_{key}.pkl")
    (MODEL_DIR / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    tables = {
        "sample": sample,
        "iv": iv,
        "coefficients": coefs,
        "metrics": mets,
        "calibration": ev["calibration"],
        "gini_by_year": ev["gini_by_year"],
        "psi": ev["psi"],
        "sensitivity": sens,
        "points": champion.points_table(),
        "binning_merges": merges,
        "delinquency_corr": dlq_corr,
        "calibration_by_state": by_state,
        "calibration_by_flag": ev["calibration_by_flag"],
        "version_change": change,
        "relief_share_by_year": relief,
    }
    for name, df in tables.items():
        df.to_csv(REPORTS / f"pd_12m_{name}.csv", index=False)
        df.to_csv(MODEL_DIR / f"{name}.csv", index=False)
    card = model_card(
        meta,
        sample,
        iv,
        coefs,
        mets,
        sens,
        merges,
        dlq_corr,
        by_state,
        ev["calibration_by_flag"],
        change,
        ev["psi"],
        relief,
    )
    (MODEL_DIR / "model_card.md").write_text(card, encoding="utf-8")
    (REPORTS / "pd_12m_model_card.md").write_text(card, encoding="utf-8")
    logger.info("Done")
