"""Challenger 12-month PD: gradient-boosted trees (LightGBM).

Same features as the champion scorecard, raw values instead of WoE, with monotone constraints
matching the scorecard's business-sense trends (features.Feature.constraint), so the model
cannot learn e.g. "higher credit score -> higher PD". Trained on the same weighted sample;
early stopping on dev_holdout log-loss. Its role is benchmarking: how much predictive power
the transparent scorecard gives up.
"""

from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd

from ecl.pd.features import BY_NAME, CATEGORICAL

PARAMS = {
    "objective": "binary",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 2000,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "monotone_constraints_method": "advanced",
    "verbose": -1,
    "num_threads": 8,
    # reproducible: identical trees on every run (row-wise histograms, fixed reduction order)
    "deterministic": True,
    "force_row_wise": True,
}
MAX_ROUNDS, EARLY_STOP = 3000, 100


def fit_lgbm(
    x_tr: pd.DataFrame,
    y_tr: pd.Series,
    w_tr: pd.Series,
    x_val: pd.DataFrame,
    y_val: pd.Series,
    seed: int,
) -> lgb.Booster:
    """Challenger: LightGBM classifier on the same features as the scorecard, with monotone
    constraints and early stopping on the development holdout (benchmark of the champion's
    rank ordering, not used for ECL)."""
    names = list(x_tr.columns)
    params = {
        **PARAMS,
        "seed": seed,
        "bagging_seed": seed,
        "feature_fraction_seed": seed,
        "data_random_seed": seed,
        "monotone_constraints": [BY_NAME[n].constraint for n in names],
    }
    cats = [n for n in names if n in CATEGORICAL]
    d_tr = lgb.Dataset(
        x_tr, y_tr.astype(int), weight=w_tr, categorical_feature=cats, free_raw_data=False
    )
    d_val = lgb.Dataset(x_val, y_val.astype(int), reference=d_tr, categorical_feature=cats)
    return lgb.train(
        params,
        d_tr,
        num_boost_round=MAX_ROUNDS,
        valid_sets=[d_val],
        valid_names=["dev_holdout"],
        callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)],
    )


def predict_pd(model: lgb.Booster, x: pd.DataFrame) -> np.ndarray:
    """Challenger PD at the best (early-stopping) iteration."""
    return model.predict(x, num_iteration=model.best_iteration)
