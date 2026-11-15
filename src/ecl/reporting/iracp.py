"""Old-rules (IRACP 2025) provision per loan, for the ECL transition (Module 10; ACPIR 107-108).

Rules (config/rbi_iracp_2025.yaml, quoted from docs/reference/RBI-IRACP-Directions-2025.pdf and
the RSA Directions 2025):
- NPA: 90+ dpd / REO, kept until the entire arrears are paid (IRACP 69 -> back to current);
  a restructured account is NPA from the restructuring until upgraded (RSA 52-54, 58, 61, 62).
  This is the same population as ECL Stage 3 (default, default_arrears, restructured Stage 3);
  calamity resolutions (RSA Chapter VI-A) stay standard (IRACP 62A, 62B).
- Categories by time as NPA (IRACP 5(2), 5(12), 63): substandard <= 12 months, then doubtful;
  loss if the realisable value of the security is below 10% of the outstanding (68(2)).
- Provisions: standard individual housing 0.25% (80(1)); substandard 15% (85), 25% if an
  unsecured exposure (86, 5(13): realisable value <= 10% of outstanding); doubtful: 100% of the
  unsecured portion (90) plus 25 / 40 / 100% of the secured portion by years in doubtful (91);
  loss 100% (95).
- Additional specific provisions: 5% per Chapter VI-A resolution (84A, 84B), written back after
  20% of the debt is repaid without NPA or another restructuring (84C); 15% for accounts that
  failed the monitoring period or defaulted after upgrade (RSA 64 for paras 61, 62); ceiling 100%.
Data mapping: outstanding = EAD now (UPB + accrued interest); realisable value = secured portion
(HPI-indexed value after the realisation haircut, ACPIR 6(24)); 68(1) erosion test not applied
(last assessed value not in the data). US data, not Indian risk estimates.
"""

import numpy as np
import pandas as pd


def _band(years: np.ndarray, bands: list[dict]) -> np.ndarray:
    out = np.full(len(years), np.nan)
    for b in bands:
        hi = np.inf if b["years_to"] is None else b["years_to"]
        m = (years >= b["years_from"]) & (years < hi)
        out[m] = b["rate"]
    return out


def old_rules_provision(df: pd.DataFrame, rc: dict) -> pd.DataFrame:
    """Per loan: asset class and IRACP provision. df columns: ead_now, secured, unsecured, npa
    (bool), npa_years (time as NPA, years), calamity_events (Chapter VI-A resolutions),
    calamity_written_back (bool, 84C), failed_monitoring (bool, RSA 61 / 62)."""
    ead = df.ead_now.to_numpy(float)
    sec = np.minimum(df.secured.to_numpy(float), ead)
    uns = np.maximum(ead - sec, 0.0)
    npa = df.npa.to_numpy(bool)
    years = np.nan_to_num(df.npa_years.to_numpy(float), nan=0.0)
    cat, pr = rc["categories"], rc["provision_rates"]
    with np.errstate(divide="ignore", invalid="ignore"):
        rv_share = np.where(ead > 0, sec / ead, 1.0)
    loss = npa & (rv_share < cat["loss"]["realisable_below_share"])
    sub = npa & ~loss & (years * 12 <= cat["substandard_max_months"])
    doubt = npa & ~loss & ~sub
    unsecured_exp = rv_share <= cat["unsecured_exposure"]["realisable_max_share"]
    years_doubtful = years - cat["substandard_max_months"] / 12
    sec_rate = _band(np.maximum(years_doubtful, 0.0), pr["doubtful_secured_portion"]["bands"])
    prov = np.select(
        [loss, sub & unsecured_exp, sub, doubt],
        [
            pr["loss"]["value"] * ead,
            pr["substandard_unsecured"]["value"] * ead,
            pr["substandard"]["value"] * ead,
            pr["doubtful_unsecured_portion"]["value"] * uns + sec_rate * sec,
        ],
        pr["standard_individual_housing"]["value"] * ead,
    )
    add = rc["additional_specific"]
    n_cal = df.calamity_events.fillna(0).to_numpy(float)
    wb = df.calamity_written_back.fillna(False).to_numpy(bool)
    extra = np.where(wb, 0.0, add["calamity_resolution"]["value"] * n_cal) * ead
    extra += np.where(
        df.failed_monitoring.to_numpy(bool) & npa, add["failed_monitoring"]["value"] * ead, 0.0
    )
    total = np.minimum(prov + extra, add["ceiling"]["value"] * ead)
    asset_class = np.select(
        [loss, sub, doubt & (years_doubtful < 1), doubt & (years_doubtful < 3), doubt],
        ["loss", "substandard", "doubtful D1", "doubtful D2", "doubtful D3"],
        "standard",
    )
    return pd.DataFrame(
        {
            "asset_class": asset_class,
            "iracp_base": prov,
            "iracp_additional": total - prov,
            "iracp_provision": total,
        },
        index=df.index,
    )
