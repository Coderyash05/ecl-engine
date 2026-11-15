"""Finding M-1 check: double credit of relief cures (Module 11).

The 12-month PD target B-18 removes relief defaults (COVID forbearance, deferral, disaster) that
cure within 18 months. The LGD cure model's level is recalibrated on all fully resolved
2012-19 defaults (lgd-0.2.0), which include those same relief cures, so the cure credit is
partly taken twice: once in the PD (fewer defaults) and once in the LGD (more cures among the
defaults that remain). The check re-does the intercept recalibration without the B-18
relabelled defaults and measures the change in projected no-cure (relief at default = 0, as in
the projection; L-LGD4). Because ECL is proportional to P(no cure) for a given severity, the
ratio is the effect on model ECL of Stages 1-2. US data; not Indian risk estimates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ecl.lgd.models import cure_frame

if TYPE_CHECKING:
    from ecl.lgd.models import CureModel


def relief_cure_double_count(
    rows0: pd.DataFrame, relabelled: pd.Series, cure_dev: CureModel
) -> dict:
    """rows0: cure-model rows at m = 0 for the recalibration window (with `y` = no cure);
    relabelled: bool per row, default relabelled by B-18; cure_dev: development cure model
    (option 1, before recalibration)."""
    relabelled = relabelled.fillna(False).astype(bool).to_numpy()
    s_all = cure_dev.recalibrate(cure_frame(rows0), rows0.y.values)
    keep = rows0[~relabelled]
    s_ex = cure_dev.recalibrate(cure_frame(keep), keep.y.values)
    eta = cure_dev.design(cure_frame(rows0.assign(relief_d=False))) @ cure_dev.params
    p_all = 1 / (1 + np.exp(-(eta + s_all)))
    p_ex = 1 / (1 + np.exp(-(eta + s_ex)))
    return {
        "window_defaults": len(rows0),
        "b18_relabelled": int(relabelled.sum()),
        "no_cure_actual_all": float(rows0.y.mean()),
        "no_cure_actual_excl": float(keep.y.mean()),
        "no_cure_actual_relabelled": float(rows0.y[relabelled].mean())
        if relabelled.any()
        else None,
        "shift_all": float(s_all),
        "shift_excl": float(s_ex),
        "projected_no_cure_all": float(p_all.mean()),
        "projected_no_cure_excl": float(p_ex.mean()),
        "ecl_ratio": float(p_ex.mean() / p_all.mean()),
    }
