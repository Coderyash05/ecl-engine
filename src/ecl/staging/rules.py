"""Staging rules (Module 6): Stage 1 / 2 / 3 per loan with the rule that fired.

What (RBI paras 25-36, 76-78, 6(3), Annex 1; config/ecl.yaml `staging`):
- **Stage 3** (credit-impaired, para 25(3)): RBI default at the reporting date (`default`: 90+
  dpd or REO acquired; para 6(3)(i) non-performing status); an NPA whose arrears are not yet
  cleared (`default_arrears`: reached 90+ and not back to current, para 8(10)); or a
  restructured loan (Freddie modification =
  lender concession due to financial difficulty, para 6(3)(iii)) still in Stage 3 under the
  mapping chosen (`restructured`):
  - `text` (primary): stage from time and performance since modification
    (ecl.staging.restructured; paras 78, 80);
  - `stage3`: every modified loan Stage 3 (upper bound);
  - `stage2`: every modified loan at least Stage 2 (earlier interim rule).
- **Stage 2** (SICR since initial recognition, para 25(2)), any of:
  - `backstop_30dpd`: more than 30 days past due (paras 33-36; no rebuttals applied);
  - `restructured`: modified and in Stage 2 under the mapping (see above);
  - `sicr_pd`: forward-looking lifetime PD / origination-expected lifetime PD over the same
    remaining window >= ratio threshold AND difference >= absolute threshold (paras 26-27;
    thresholds not RBI-specified);
  - `collateral_ltv`: indexed LTV >= threshold (Annex 1: collateral value falling with house
    prices).
- **Stage 1** otherwise. Curing (para 77): a non-restructured loan out of default is restaged by
  the same rules each reporting date (no memory).
- Every loan records all rules that fired (`rules_fired`) and the highest-priority one
  (`stage_rule`), so each staging decision is auditable.
Loan level = borrower level here (one loan per borrower; para 76 approximation).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

STAGE2_RULES = ["backstop_30dpd", "restructured", "sicr_pd", "collateral_ltv"]


def sicr_pd_flag(
    pd_now: ArrayLike, pd_orig: ArrayLike, ratio: float, absolute: float
) -> np.ndarray:
    """Relative AND absolute increase of lifetime PD since initial recognition; False where the
    origination comparator is missing."""
    pd_now, pd_orig = np.asarray(pd_now, float), np.asarray(pd_orig, float)
    ok = np.isfinite(pd_orig) & (pd_orig > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(ok, pd_now / pd_orig, np.nan)
    return ok & (r >= ratio) & (pd_now - pd_orig >= absolute)


def restructured_flags(d: pd.DataFrame, mapping: str, state_col: str) -> tuple:
    """(Stage 3 flag, Stage 2 flag) from restructuring for one mapping."""
    mod = np.asarray(d.modified.fillna(False), bool)
    if mapping == "stage3":
        return mod, np.zeros(len(d), bool)
    if mapping == "stage2":
        return np.zeros(len(d), bool), mod
    if mapping == "text":
        state = d[state_col].to_numpy(float)
        return mod & (state == 3), mod & (state == 2)
    raise ValueError(f"unknown restructuring mapping {mapping}")


def stage_loans(
    d: pd.DataFrame,
    cfg: dict,
    ratio: float | None = None,
    restructured: str | None = None,
    state_col: str = "restr_state",
) -> pd.DataFrame:
    """d: in_default, dpd_bucket, modified, pd_life_now, pd_life_orig, current_ltv (and
    `state_col` for the text mapping). Returns stage (1/2/3), stage_rule, rules_fired."""
    st = cfg["staging"]
    ratio = st["sicr_pd"]["ratio_threshold"] if ratio is None else ratio
    restructured = st["restructured"]["treatment"] if restructured is None else restructured
    r3, r2 = restructured_flags(d, restructured, state_col)
    in_default = np.asarray(d.in_default, bool)
    arrears = (
        np.asarray(d.npa_arrears, bool) & ~in_default
        if st.get("npa_until_arrears_cleared") and "npa_arrears" in d
        else np.zeros(len(d), bool)
    )
    flags = {
        "default": in_default,
        "default_arrears": arrears,
        "backstop_30dpd": np.asarray(d.dpd_bucket.isin(st["backstop"]["dpd_buckets"]), bool),
        "restructured": r3 | r2,
        "sicr_pd": sicr_pd_flag(
            d.pd_life_now, d.pd_life_orig, ratio, st["sicr_pd"]["absolute_threshold"]
        ),
        "collateral_ltv": np.asarray(
            d.current_ltv.fillna(0) >= st["collateral"]["indexed_ltv_threshold"], bool
        ),
    }
    stage3 = flags["default"] | flags["default_arrears"] | r3
    s2 = {**flags, "restructured": r2}
    stage2 = ~stage3 & np.any([s2[r] for r in STAGE2_RULES], axis=0)
    stage = np.where(stage3, 3, np.where(stage2, 2, 1))
    names = np.array(["default", "default_arrears", *STAGE2_RULES])
    mat = np.column_stack([flags[n] for n in names])
    fired = [";".join(names[row]) if row.any() else "" for row in mat]
    first = np.where(mat.any(axis=1), names[mat.argmax(axis=1)], "none")
    rule = np.where(
        stage == 3,
        np.select(
            [flags["default"], flags["default_arrears"]],
            ["default", "default_arrears"],
            "restructured",
        ),
        np.where(stage == 2, first, "none"),
    )
    return pd.DataFrame({"stage": stage, "stage_rule": rule, "rules_fired": fired})


def transition_matrix(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """Stage at date t (rows) -> stage at t + 1 quarter (columns) by loan_id; loans gone at t+1
    (prepaid, liquidated, ...) in column 'exited'. Row shares."""
    m = a[["loan_id", "stage"]].merge(
        b[["loan_id", "stage"]], on="loan_id", how="left", suffixes=("_t", "_t1")
    )
    m["to"] = m.stage_t1.map(lambda x: "exited" if pd.isna(x) else f"Stage {int(x)}")
    t = pd.crosstab(m.stage_t.map(lambda x: f"Stage {x}"), m.to)
    return t.div(t.sum(axis=1), axis=0)
