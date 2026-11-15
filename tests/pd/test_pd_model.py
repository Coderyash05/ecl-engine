"""Tests for Module 2b: sampling-weight correction, binning policy (monotonic WoE for
continuous features, natural categories for states), scorecard scoring."""

import math

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from ecl.pd import metrics
from ecl.pd.features import BY_NAME, NEVER_30DPD, dlq_state, scorecard_frame
from ecl.pd.sampling import inverse_sampling_weights, load_sample
from ecl.pd.scorecard import (
    BASE_ODDS,
    BASE_SCORE,
    FACTOR,
    OFFSET,
    PDO,
    WoEScorecard,
    category_groups,
    fit_binning,
    fit_scorecard,
    state_splits,
    vif_table,
    weighted_corr,
)

RNG = np.random.default_rng(7)


def synthetic(n: int = 40_000, seed: int = 7) -> pd.DataFrame:
    """Snapshot-like rows with all source columns; default risk driven by score, LTV, dpd."""
    rng = np.random.default_rng(seed)
    score = rng.normal(720, 50, n)
    ltv = rng.uniform(40, 100, n)
    dpd = rng.choice(["current", "30-59", "60-89"], n, p=[0.95, 0.04, 0.01])
    never = rng.random(n) < 0.85
    since = np.where(never, np.nan, rng.integers(0, 60, n))
    dti = np.where(rng.random(n) < 0.1, np.nan, rng.uniform(10, 50, n))
    logit = (
        -4.5
        - 0.02 * (score - 720)
        + 0.03 * (ltv - 70)
        + np.select([dpd == "30-59", dpd == "60-89"], [2.5, 4.0], 0.0)
        + np.where(never, -0.5, 2.0 / (1 + since / 3))
    )  # recent arrears are riskier
    y = rng.random(n) < 1 / (1 + np.exp(-logit))
    return pd.DataFrame(
        {
            "credit_score": score,
            "orig_ltv": ltv,
            "orig_cltv": ltv,
            "orig_dti": dti,
            "current_ltv": ltv * rng.uniform(0.8, 1.1, n),
            "orig_interest_rate": rng.uniform(3, 7, n),
            "rate_spread": rng.normal(0, 0.4, n),
            "loan_age": rng.integers(0, 120, n),
            "num_units": 1,
            "num_borrowers": rng.integers(1, 3, n),
            "months_since_30dpd": since,
            "max_dlq_12m": np.where(dpd == "current", 0, 1),
            "dpd_bucket": dpd,
            "harp_loan": rng.random(n) < 0.1,
            "ever_deferred": rng.random(n) < 0.02,
            "ever_modified": rng.random(n) < 0.02,
            "occupancy_status": rng.choice(["P", "I", "S"], n, p=[0.9, 0.07, 0.03]),
            "loan_purpose": rng.choice(["P", "C", "N"], n),
            "property_type": "SF",
            "channel": rng.choice(["R", "B", "C"], n),
            "first_time_homebuyer": rng.choice(["Y", "N"], n),
            "target_b18": y,
        }
    )


# ---------------------------------------------------------------- sampling weights


def test_inverse_sampling_weights():
    w = inverse_sampling_weights(pd.Series([True, False, False]), 0.2)
    assert list(w) == [1.0, 5.0, 5.0]


def test_weighted_fit_on_sample_recovers_population_scale():
    """All defaults + 10% of non-defaults with weight 10 -> PDs on the population scale."""
    n = 300_000
    x = RNG.normal(size=n)
    y = RNG.random(n) < 1 / (1 + np.exp(-(-4.0 + 1.0 * x)))
    keep = y | (RNG.random(n) < 0.10)
    w = inverse_sampling_weights(pd.Series(y[keep]), 0.10)
    fit = LogisticRegression().fit(x[keep, None], y[keep], sample_weight=w)
    p_all = fit.predict_proba(x[:, None])[:, 1]
    assert p_all.mean() == pytest.approx(y.mean(), rel=0.05)
    assert fit.intercept_[0] == pytest.approx(-4.0, abs=0.1)
    unweighted = LogisticRegression().fit(x[keep, None], y[keep])
    assert unweighted.predict_proba(x[:, None])[:, 1].mean() > 3 * y.mean()  # biased up


def test_load_sample_is_reproducible_and_weighted(tmp_path):
    n = 50_000
    df = pd.DataFrame(
        {
            "loan_id": [f"L{i}" for i in range(n)],
            "obs_date": pd.Timestamp("2010-03-01"),
            "target_b18": RNG.random(n) < 0.02,
            "credit_score": 700,
            "split": "dev_train",
        }
    )
    (tmp_path / "split=dev_train").mkdir()
    df.drop(columns="split").to_parquet(tmp_path / "split=dev_train" / "a.parquet")
    s1 = load_sample(tmp_path, "dev_train", ["credit_score"], rate=0.2, seed=1)
    s2 = load_sample(tmp_path, "dev_train", ["credit_score"], rate=0.2, seed=1)
    pd.testing.assert_frame_equal(s1, s2)
    assert s1.target_b18.sum() == df.target_b18.sum()  # every default kept
    assert s1.weight.sum() == pytest.approx(n, rel=0.03)  # weighted size = population
    assert set(s1.weight[~s1.target_b18]) == {5.0}
    s3 = load_sample(tmp_path, "dev_train", ["credit_score"], rate=0.2, seed=2)
    assert set(s1.loan_id) != set(s3.loan_id)


# ---------------------------------------------------------------- monotonic WoE


@pytest.fixture(scope="module")
def binned():
    df = synthetic()
    x = scorecard_frame(df)
    w = pd.Series(np.ones(len(df)))
    return fit_binning(
        x, df.target_b18, w, ["credit_score", "orig_ltv", "orig_dti", "months_since_30dpd"]
    )


def regular_bins(bp, name):
    t = bp.get_binned_variable(name).binning_table.build()
    return t[~t.Bin.astype(str).isin(["Special", "Missing"]) & (t.index != "Totals")]


def test_credit_score_event_rate_falls(binned):
    rates = regular_bins(binned, "credit_score")["Event rate"].astype(float).values
    assert len(rates) > 2 and np.all(np.diff(rates) < 0)


def test_ltv_event_rate_rises(binned):
    rates = regular_bins(binned, "orig_ltv")["Event rate"].astype(float).values
    assert len(rates) > 2 and np.all(np.diff(rates) > 0)


def test_min_bin_size(binned):
    t = regular_bins(binned, "credit_score")
    assert (t["Count (%)"].astype(float) >= 0.05 - 1e-9).all()


def test_never_30dpd_is_special_bin_not_missing(binned):
    t = binned.get_binned_variable("months_since_30dpd").binning_table.build()
    special = t[t.Bin.astype(str) == "Special"]
    missing = t[t.Bin.astype(str) == "Missing"]
    assert special.Count.iloc[0] > 0.8 * 40_000 and missing.Count.iloc[0] == 0
    assert NEVER_30DPD == -999


def test_missing_dti_has_own_bin(binned):
    t = binned.get_binned_variable("orig_dti").binning_table.build()
    assert t[t.Bin.astype(str) == "Missing"].Count.iloc[0] > 0


# ---------------------------------------------------------------- binning policy: states


def cells(spec: list[tuple[object, int, int]]) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(value, rows, defaults) per cell -> value, target, unit weights."""
    v = np.concatenate([np.full(n, val, dtype=object) for val, n, _ in spec])
    y = np.concatenate([np.r_[np.ones(d, bool), np.zeros(n - d, bool)] for _, n, d in spec])
    return pd.Series(v), pd.Series(y), pd.Series(np.ones(len(v)))


def test_delinquency_states_keep_their_own_bins_below_5pct():
    """30-59 dpd (2% of snapshots) and 60-89 dpd (1%) are far below the 5% minimum used for
    continuous features, but each must keep its own bin and its own default rate."""
    v, y, w = cells([(0, 97_000, 800), (1, 2_000, 600), (2, 1_000, 700)])
    x = pd.DataFrame({"current_dpd": v.astype(float)})
    bp = fit_binning(x, y, w, ["current_dpd"])
    rates = regular_bins(bp, "current_dpd")["Event rate"].astype(float).values
    np.testing.assert_allclose(rates, [800 / 97_000, 0.30, 0.70])


def test_state_is_merged_only_if_rare_and_thin():
    """v1.2.0 amendment: merge only below 0.5% of snapshots AND below 500 defaults."""
    # 60-89: 0.3% of snapshots and 400 defaults -> joins 30-59 (closer default rate)
    v, y, w = cells([(0, 392_800, 3_000), (1, 6_000, 1_500), (2, 1_200, 400)])
    edges, notes = state_splits(v.astype(float), y, w, (0.5, 1.5))
    assert edges == [0.5] and len(notes) == 1
    # rare (0.3%) but 800 defaults -> kept: the default count governs WoE stability
    v, y, w = cells([(0, 392_800, 3_000), (1, 6_000, 1_500), (2, 1_200, 800)])
    assert state_splits(v.astype(float), y, w, (0.5, 1.5))[0] == [0.5, 1.5]
    # thin (100 defaults) but 4% of snapshots -> kept
    v, y, w = cells([(0, 90_000, 900), (1, 6_000, 600), (2, 4_000, 100)])
    assert state_splits(v.astype(float), y, w, (0.5, 1.5))[0] == [0.5, 1.5]


def test_flag_with_too_few_cases_collapses_to_one_bin():
    v, y, w = cells([(0, 99_900, 1_200), (1, 100, 20)])
    x = pd.DataFrame({"ever_modified": v.astype(float)})
    assert state_splits(x.ever_modified, y, w, (0.5,))[0] == []
    assert len(regular_bins(fit_binning(x, y, w, ["ever_modified"]), "ever_modified")) == 1


def test_small_category_joins_category_with_closest_default_rate():
    # CP: 0.3% of snapshots, default rate 0.6% -> joins PU (1.0%), not MH (2.4%)
    v, y, w = cells(
        [("SF", 800_000, 10_000), ("PU", 150_000, 1_500), ("MH", 47_000, 1_130), ("CP", 3_000, 20)]
    )
    groups, notes = category_groups(v, y, w)
    assert sorted(groups) == [["CP", "PU"], ["MH"], ["SF"]] and len(notes) == 1


def test_num_borrowers_is_one_vs_two_plus():
    """Before 2018Q2 Freddie coded 2 as 'more than one borrower': 2 and 3+ share a bin."""
    assert BY_NAME["num_borrowers"].splits == (1.5,)
    v, y, w = cells([(1, 40_000, 800), (2, 55_000, 550), (3, 5_000, 20)])
    x = pd.DataFrame({"num_borrowers": v.astype(float)})
    bp = fit_binning(x, y, w, ["num_borrowers"])
    out = bp.transform(pd.DataFrame({"num_borrowers": [1.0, 2.0, 3.0, 5.0]}), metric="woe")
    woe = out.num_borrowers.values
    assert woe[1] == woe[2] == woe[3] and woe[0] < woe[1]


def test_channel_is_retail_vs_third_party():
    """Freddie reported third-party loans as T before 2008 and as B / C after."""
    df = synthetic(n=8)
    df["channel"] = ["R", "T", "B", "C", "R", "T", "B", None]
    ch = scorecard_frame(df).channel
    assert list(ch[:7]) == ["R", "TPO", "TPO", "TPO", "R", "TPO", "TPO"] and pd.isna(ch[7])


def test_dlq_state_combines_current_dpd_and_months_since_30dpd():
    dpd = pd.Series([0, 0, 0, 0, 0, 1, 2, np.nan])
    months = pd.Series([np.nan, 40, 13, 12, 1, 0, 0, 0])
    # never / cured 13+ / cured 13+ / cured 4-12 / cured 1-3 / 30-59 / 60-89 / dpd unknown
    np.testing.assert_array_equal(dlq_state(dpd, months), [0, 1, 1, 2, 3, 4, 5, np.nan])


def test_orig_interest_rate_is_not_a_candidate():
    assert "orig_interest_rate" not in BY_NAME


def test_weighted_correlation_and_vif_match_replicated_rows():
    rng = np.random.default_rng(3)
    a = rng.normal(size=500)
    df = pd.DataFrame({"a": a, "b": a + rng.normal(size=500), "c": rng.normal(size=500)})
    wts = rng.integers(1, 5, 500)
    rep = df.loc[df.index.repeat(wts)].reset_index(drop=True)
    np.testing.assert_allclose(
        weighted_corr(df, wts.astype(float)).values,
        np.corrcoef(rep.values, rowvar=False),
        atol=1e-3,
    )
    v_w = vif_table(df, wts.astype(float)).set_index("feature").vif
    v_r = vif_table(rep).set_index("feature").vif
    np.testing.assert_allclose(v_w[df.columns], v_r[df.columns], rtol=1e-6)


# ---------------------------------------------------------------- scorecard scoring


@pytest.fixture(scope="module")
def card():
    df = synthetic(n=300_000)
    x = scorecard_frame(df)
    model = fit_scorecard(
        x, df.target_b18, pd.Series(np.ones(len(df))), ["credit_score", "orig_ltv", "dlq_state"]
    )
    return model, x


def test_scorecard_separates_delinquency_states(card):
    model, x = card
    p = pd.Series(model.predict_pd(x)).groupby(x.dlq_state.values).mean()
    assert p[5.0] > p[4.0] > p[0.0]


def test_all_coefficients_negative_on_woe(card):
    model, _ = card
    assert set(model.coefs) == {"credit_score", "orig_ltv"}
    assert all(c < 0 for c in model.coefs.values())


def test_dlq_state_enters_as_dummies_rising_with_severity(card):
    """Base = never 30+ dpd (coefficient 0); each worse state has a larger coefficient."""
    model, _ = card
    assert BY_NAME["dlq_state"].dummy
    c = model.state_coefs["dlq_state"]
    assert c[0] == 0.0 and len(c) == len(model.binning.get_binned_variable("dlq_state").splits) + 1
    assert model.states_monotonic()


def test_dummies_reproduce_default_rate_of_every_state():
    """Maximum likelihood with an indicator per state: mean PD = default rate in each state."""
    df = synthetic(n=300_000)
    x = scorecard_frame(df)
    model = fit_scorecard(
        x, df.target_b18, pd.Series(np.ones(len(df))), ["credit_score", "orig_ltv", "dlq_state"]
    )
    g = (
        pd.DataFrame({"y": df.target_b18.values, "p": model.predict_pd(x)})
        .groupby(np.digitize(x.dlq_state, model.binning.get_binned_variable("dlq_state").splits))
        .mean()
    )
    np.testing.assert_allclose(g.p, g.y, rtol=2e-3)


def test_state_points_and_missing_state(card):
    model, x = card
    pts = model.points_table()
    p = pts[pts.feature == "dlq_state"].points.values
    assert len(p) == len(model.state_coefs["dlq_state"]) and np.all(np.diff(p) < 0)
    row = x.iloc[[0]].copy()
    row["dlq_state"] = np.nan
    assert np.isnan(model.predict_pd(row)[0])


def test_scoring_is_reproducible(card, tmp_path):
    model, x = card
    p1, p2 = model.predict_pd(x), model.predict_pd(x)
    np.testing.assert_array_equal(p1, p2)
    model.save(tmp_path / "m.pkl")
    np.testing.assert_array_equal(WoEScorecard.load(tmp_path / "m.pkl").predict_pd(x), p1)


def test_points_scaling(card):
    model, x = card
    p, s = model.predict_pd(x), model.score(x)
    np.testing.assert_allclose(s, OFFSET + FACTOR * np.log((1 - p) / p), rtol=1e-9)
    assert OFFSET + FACTOR * math.log(BASE_ODDS) == pytest.approx(BASE_SCORE)
    assert FACTOR * math.log(2 * BASE_ODDS) - FACTOR * math.log(BASE_ODDS) == pytest.approx(PDO)


def test_points_table_sums_to_score(card):
    model, x = card
    pts = model.points_table()
    row = x.iloc[[0]]
    w = model.woe(row).iloc[0]
    total = 0.0
    for f in model.features:
        t = pts[pts.feature == f]
        total += t.loc[(t.woe - w[f]).abs().idxmin(), "points"]
    assert total == pytest.approx(model.score(row)[0], abs=1e-6)


# ---------------------------------------------------------------- metrics


def test_metrics_basics():
    y = np.array([0, 0, 1, 1])
    assert metrics.gini(y, [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1.0)
    assert metrics.ks(y, [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1.0)
    assert metrics.brier(y, [0, 0, 1, 1]) == 0
    s = pd.Series([0.5, 0.5], index=["a", "b"])
    assert metrics.psi(s, s) == pytest.approx(0)
