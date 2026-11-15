# Model development log: 12-month TTC PD (`pd_12m`)

Part of the validation evidence (RBI ECL Directions 2026, paras 120-121, 130-131). One entry per
version: what was built, what was found wrong, what was changed and why. All results are on
**US Freddie Mac data** (target B-18) and are not Indian risk estimates.

Folder convention: `models/pd_12m/` holds the current version; superseded versions are kept
unchanged in `models/pd_12m/v<version>/`.

---

## v1.2.1 — 2026-11-15 — current, status: development (not independently validated)

Patch version: no change to features, bins, sample, target, splits or seed.

- **Reason.** `rate_spread` (note rate minus the average note rate of the origination month) was
  a DuckDB DOUBLE `AVG` window. DuckDB sums in parallel, in thread order, so the last digits of
  the average could differ between runs; this was one source of the run-to-run noise found when
  the outputs were regenerated (finding M-7, `docs/validation_report.md`).
- **Change.** The average is taken over an exact `DECIMAL(9, 3)` sum (every note rate has three
  decimals) and cast back to DOUBLE: order-independent (`pd/dataset.py`; test
  `tests/test_determinism.py`). Code commit `424af50`, together with ORDER BY on the sampling
  reads and the deterministic challenger.
- **Impact** (v1.2.0 committed outputs vs the 1.2.1 refit; this change and the ORDER BY together):
  champion and sensitivity-model coefficients differ < 1e-14 (relative), points ~2e-14;
  Gini / KS / mean PD / Brier < 2e-17 (absolute); bins and score PSI identical. Headlines
  unchanged: Gini 0.803 / 0.709 / 0.694 / 0.750, PSI 0.06 / 0.09 / 0.15.
- **Challenger** (LightGBM) made deterministic in the same commit: `deterministic=True`,
  `force_row_wise=True`, fixed bagging / feature / data seeds (the earlier fit gave 307 vs 298
  trees between runs); two fits are byte-identical. Gini 0.821 / 0.736 / 0.717 / 0.770 ->
  0.821 / 0.736 / 0.716 / 0.770; challenger score PSI 0.11 / 0.09 / 0.15 (unchanged at two decimals).
- Version comparison tables still compare against v1.1.0 (the last structurally different
  version); v1.2.0 artefacts are not archived separately (numerically identical; git `9ead9c0`).
- Downstream: pdpit-0.2.1 and pdlife-0.4.0 now take `pd12m-1.2.1` as their TTC input; their
  versions are unchanged (inputs identical within 1e-14).
- **Artefact label.** The committed artefacts (`metadata.json`, model cards of pd_12m / pd_pit /
  pd_lifetime, `pd_at_origination` in `data/`) were produced by the 1.2.0-labelled run at `424af50`
  (outputs commit `9ead9c0`) and still carry the `pd12m-1.2.0` label until the next fit. Their
  numbers are the 1.2.1 numbers: the label is the only difference. The relabelling rerun was not
  completed (owner decision 2026-11-15).

## v1.2.0 — 2026-11-12 — superseded by v1.2.1 (2026-11-15). Commit `6558138`

Code: git commit `6558138` (fitted from a clean tree; hash in `metadata.json` and the model card).
v1.1.0 = commit `4f71e0a`. Same data, sample, target, splits and seed as v1.1.0.

### Owner decisions on v1.1.0 (Yash, 2026-11-12)
1. **`dlq_state` approved** as the single delinquency feature.
2. **60-89 dpd bin approved**, through a **deliberate amendment of the binning policy**: a
   state / flag / categorical category is merged only if it is below 0.5% of weighted snapshots
   **AND** below 500 defaults (v1.1.0: OR, with an ad-hoc exemption for 60-89 dpd). Reason: the
   stability of a bin's WoE and default rate is governed by its number of defaults, not its share
   of snapshots; 60-89 dpd has 0.26% of snapshots but ~18,700 defaults. The `share_exempt`
   exception is removed — the rule itself now keeps the bin.

### Changes
| # | Change | Reason |
|---|---|---|
| 1 | **`dlq_state` enters as dummy variables** (base = never 30+ dpd); every other feature stays WoE. Each state has its own coefficient and its own points. Selection screens (IV, correlation, VIF) still use its WoE column. | v1.1.0 scaled all six states with one WoE coefficient: 60-89 dpd under-predicted on dev_holdout (62.7% vs 69.3%). |
| 2 | Binning policy: OR → AND (above). | Owner decision 2. |
| 3 | Fit records the git commit and a clean flag (code + regulatory config) in the model card and metadata. | Reproducibility; closes the v1.0.0 gap. |
| 4 | Candidate overlays CO-1 / CO-2 recorded with evidence, bias direction and monitoring triggers (para 131). **No overlay applied.** | Owner request. |

Effect of the AND rule on other features: `ever_modified` (0.11%, 670 defaults) now keeps its own
bin but has IV 0.007 and drops; `property_type` CP (0.27%, 178 defaults) still merges with PU;
`ever_deferred` still collapses to one bin (5 snapshots in development). Selected features are
unchanged from v1.1.0.

### Coefficients of dlq_state (log-odds vs never 30+ dpd) — rise monotonically
| State | Coefficient | Odds ratio |
|---|---|---|
| cured 13+ months | 0.553 | 1.7 |
| cured 4-12 months | 1.349 | 3.9 |
| cured 1-3 months | 2.203 | 9.0 |
| 30-59 dpd | 3.309 | 27.4 |
| 60-89 dpd | 5.318 | 204.0 |

All eight WoE coefficients negative; max VIF 1.18.

### Results (champion, target B-18)
| Split | Actual | Mean PD v1.1.0 → v1.2.0 | Gini v1.1.0 → v1.2.0 | Score PSI v1.1.0 → v1.2.0 |
|---|---|---|---|---|
| dev_holdout | 1.23% | 1.23% → 1.23% | 0.803 → 0.803 | – |
| OOT1 2017-19 | 0.49% | 0.72% → 0.72% | 0.714 → 0.709 | 0.05 → 0.06 |
| OOT2 2020-21 | 0.37% | 0.81% → 0.81% | 0.698 → 0.694 | 0.08 → 0.09 |
| OOT3 2022-23 | 0.45% | 0.60% → 0.59% | 0.753 → 0.750 | 0.13 → 0.15 |

Challenger unchanged (0.821 / 0.736 / 0.717 / 0.770; 0.716 for OOT2 after the deterministic refit, v1.2.1). The small OOT Gini loss (0.003-0.005) is
the price of fitting each state's 2000-2016 default rate exactly; state default rates move with
the cycle.

Calibration by state, actual vs predicted (%):
| State | dev_holdout | OOT1 | OOT2 |
|---|---|---|---|
| never 30+ dpd | 0.56 vs 0.57 | 0.22 vs 0.43 | 0.16 vs 0.37 |
| cured 13+ months | 1.53 vs 1.54 | 0.80 vs 0.90 | 0.44 vs 0.74 |
| cured 4-12 months | 4.12 vs 3.91 | 2.10 vs 2.39 | 1.07 vs 2.08 |
| cured 1-3 months | 9.21 vs 9.03 | 5.15 vs 5.74 | 2.46 vs 5.14 |
| 30-59 dpd | 24.96 vs 24.40 | 14.33 vs 16.24 | 9.17 vs 14.21 |
| 60-89 dpd | 69.28 vs 69.24 | 53.09 vs 56.45 | 17.00 vs 51.21 |

dev_holdout: actual / predicted 0.98-1.05 in every state (v1.1.0: 60-89 dpd 1.11, cured 13+
0.83). OOT over-prediction is the TTC level (below), plus COVID forbearance in OOT2 (CO-1).

### Known limitations
1. **Through-the-cycle by design.** Development 2000-2016 includes the 2007-11 crisis and there
   are no macro variables, so benign OOT periods are over-predicted (mean PD 0.59-0.81% vs actual
   0.37-0.49%). Module 3 converts to point-in-time; these PDs are not point-in-time PDs.
2. Low-risk deciles over-predicted in relative terms on dev_holdout (decile 1: 0.07% vs 0.03%);
   decile 9 under-predicted (1.29% vs 1.56%). Unchanged from v1.1.0.
3. PSI of current_ltv (0.10-0.48), loan_age (0.15-0.32) and orig_dti (0.15-0.23): real portfolio
   change, not coding artefacts.

### Candidate overlays (para 131) — recorded, not applied
| ID | Evidence | Direction | Monitoring trigger (developer proposal, not an RBI value) |
|---|---|---|---|
| CO-1 COVID / mass forbearance | OOT2 60-89 dpd 17.0% actual vs 51.2% predicted (ratio 0.33); 30-59 dpd ratio 0.65. Relief share of 30-89 dpd loan-months 58% (2020), 34% (2021) vs ≤ 7% in 2014-19. | PD too high (conservative) for delinquent loans under widespread relief. | Relief share of 30-89 dpd loan-months > 15% in a quarter (leading), or actual/predicted for 30-89 dpd < 0.70 in two consecutive labelled quarters with ≥ 100 defaults (lagging). |
| CO-2 ever_deferred | OOT1 12.1% actual vs 9.1% predicted (1,766 snapshots, ratio 1.34); OOT2 ratio 0.50; OOT3 1.12. Flag has 5 snapshots in development. | PD too low outside mass-relief periods (the binding risk). | actual/predicted > 1.25 over the last four labelled quarters with ≥ 100 defaults; at any refit add ever_deferred as a candidate once it has 500 defaults in development. |

Full evidence tables in the model card and `relief_share_by_year.csv`.

### PD at origination
Regenerated: 1,375,000 loans, median 0.28% (v1.1.0: 0.28%). v1.1.0 values kept in
`data/processed/pd_at_origination_v1.1.0/` (loan-level, not in git).

---

## v1.1.0 — 2026-11-12 — superseded by v1.2.0. Commit `4f71e0a`. Artefacts: `models/pd_12m/v1.1.0/` keeps the three tables the
v1.2.0 fit compares against (calibration by state, metrics, PSI); the full set is not retained in the repository

Refit approved by Yash after the review of v1.0.0. Same data, sample, target, splits and seed.

### Changes
| # | Change | Reason (defect in v1.0.0) |
|---|---|---|
| 1 | **Binning policy by feature type.** Continuous features (credit_score, current_ltv, orig_ltv, orig_cltv, orig_dti, rate_spread, loan_age): optimal bins, minimum 5% of weighted snapshots. Delinquency states, flags, counts and categoricals: natural categories, merged only if a category has < 0.5% of weighted snapshots or < 500 defaults. | Defect 1: the 5% minimum erased the delinquency states. |
| 2 | **`orig_interest_rate` removed** from the candidates; `rate_spread` kept. | Defect 2: era proxy (PSI 1.5-2.0). |
| 3 | **`channel` recoded** to retail (R) vs third party (T, B, C merged). | Defect 3: Freddie coding change in 2008 (PSI 0.8-1.1). |
| 4 | `num_borrowers` fixed at 1 vs 2+ (it was already split at 1.5 in v1.0.0; now enforced). | Before 2018Q2 Freddie coded 2 as "more than one borrower". |
| 5 | Correlation and VIF screens now use the sampling weights. | The unweighted sample is default-enriched, which overstates correlations between delinquency features (e.g. 0.84 vs 0.74). No selection decision changed because of this. |

### Decisions taken during the refit (confirmed by the model owner for v1.2.0)
1. **New combined feature `dlq_state`** (never 30+ dpd / cured 13+ / 4-12 / 1-3 months ago /
   30-59 dpd / 60-89 dpd). The three delinquency features overlap by construction — "30+ dpd
   now" is the same set of loans in each — with weighted WoE correlations of 0.60-0.89. A sum of
   their WoEs cannot reproduce the default rate of each state. Tested on the training sample
   (weighted; actual vs predicted default rate, %):

   | Feature set | Gini | 30-59 dpd (24.5) | 60-89 dpd (69.2) | cured 1-3m (9.1) | cured 4-12m (3.9) | cured 13+m (1.5) | max VIF |
   |---|---|---|---|---|---|---|---|
   | months_since_30dpd only (what the IV/correlation rule picks from the three) | 0.7995 | 30.5 | 35.1 | 10.1 | 4.8 | 1.8 | 1.3 |
   | months_since_30dpd + current_dpd | 0.7993 | 31.7 | 48.4 | 5.9 | 3.3 | 1.6 | 2.6 |
   | all three | 0.7989 | 27.6 | 60.4 | 6.9 | 5.0 | 1.0 | 8.1 |
   | current_dpd + max_dlq_12m | 0.7974 | 26.2 | 64.0 | 6.4 | 5.1 | 0.9 | 1.9 |
   | **dlq_state (chosen)** | **0.8003** | **24.9** | **62.7** | **10.2** | **4.8** | **1.8** | **1.1** |

   `dlq_state` is months_since_30dpd with its "delinquent now" bin split by current dpd. It has
   the highest IV (2.07), so the standard rule keeps it and drops months_since_30dpd (|corr|
   0.99), max_dlq_12m (0.90) and current_dpd (0.75). No exception to the selection rules is needed.
2. **60-89 dpd keeps its own bin although it is 0.26% of weighted snapshots** (below the 0.5%
   share threshold): it has 18,720 defaults and a 69% default rate, and it is the state the fix
   exists for. The 500-defaults threshold still applies to it. Applying the share threshold
   literally would merge it with 30-59 dpd (both predicted at ~33%).
3. Categories merged or collapsed by the thresholds: `property_type` CP joined PU (0.27%, 178
   defaults); `ever_modified` (0.11% of snapshots, 670 defaults) and `ever_deferred` (5
   snapshots; the flag only exists from 2016-11) collapse to one bin and drop out. Check on
   OOT: these loans are not systematically under-predicted (`calibration_by_flag.csv`),
   because `dlq_state` captures most of their risk; the one exception is ever_deferred in OOT1
   (12.1% actual vs 9.1% predicted, 1,766 snapshots).

### Results (champion, target B-18)
| Split | Actual | Mean PD v1.0.0 → v1.1.0 | Gini v1.0.0 → v1.1.0 | Challenger Gini v1.0.0 → v1.1.0 | Score PSI v1.0.0 → v1.1.0 |
|---|---|---|---|---|---|
| dev_holdout | 1.23% | 1.23% → 1.23% | 0.786 → 0.803 | 0.830 → 0.821 | – |
| OOT1 2017-19 | 0.49% | 0.49% → 0.72% | 0.702 → 0.714 | 0.744 → 0.736 | 0.31 → 0.05 |
| OOT2 2020-21 | 0.37% | 0.45% → 0.81% | 0.675 → 0.698 | 0.719 → 0.717 | 0.45 → 0.08 |
| OOT3 2022-23 | 0.45% | 0.42% → 0.60% | 0.719 → 0.753 | 0.771 → 0.770 | 0.50 → 0.13 |

Calibration by delinquency state (actual vs predicted): dev_holdout 30-59 dpd 25.0% vs 24.8%;
60-89 dpd 69.3% vs 62.7%; cured 13+ months 1.5% vs 1.8% (v1.0.0: 25.0 vs 10.7; 69.3 vs 13.0;
1.5 vs 6.8). Full table: `calibration_by_state.csv`.

### Findings / open issues in v1.1.0
1. **OOT level is now over-predicted** (mean PD 0.60-0.81% vs actual 0.37-0.49%). This is the
   through-the-cycle level (development 2000-2016 includes 2007-11) showing once the calendar
   proxy `orig_interest_rate` is gone; v1.0.0's OOT match was produced by that proxy, not by
   borrower risk. The challenger shows the same level shift. Rank ordering improved. The level is
   to be handled by the point-in-time conversion in Module 3, not by re-adding an era variable.
2. 60-89 dpd is still under-predicted on dev_holdout (62.7% vs 69.3%) and 30-59 dpd is
   over-predicted in OOT1 (16.8% vs 14.3%): one coefficient scales all six states.
3. OOT2 (COVID): 60-89 dpd actual 17% vs predicted 44% — forbearance months that cured within 18
   months are not defaults under B-18. Gini by year dips in 2019-20 (0.65-0.67).
4. Low-risk deciles on dev_holdout remain over-predicted in relative terms (decile 1: 0.07% vs
   0.03%), decile 9 under-predicted (1.25% vs 1.58%).
5. PSI of current_ltv (0.10-0.48) and loan_age (0.15-0.32) remains: real portfolio change
   (house prices, seasoning), not a coding artefact.
6. The challenger receives the same coarse features as the champion (dlq_state rather than raw
   months since delinquency), so its Gini fell by 0.001-0.009; the champion-challenger gap is now
   0.017-0.022 (was 0.04-0.05).

### PD at origination
Regenerated: 1,375,000 loans, median 0.28% (v1.0.0: 0.30%). v1.0.0 values kept in
`data/processed/pd_at_origination_v1.0.0/` (loan-level, not in git).

---

## v1.0.0 — 2026-11-12 — superseded, never used. Artefacts: not retained in the repository.

First fit. WoE scorecard with a 5% minimum bin size for every feature; 10 features
(months_since_30dpd, credit_score, orig_interest_rate, current_ltv, rate_spread, orig_dti,
channel, num_borrowers, loan_age, loan_purpose); LightGBM challenger on the same features.
Gini B-18: holdout 0.786, OOT1 0.702, OOT2 0.675, OOT3 0.719.

### Defects found in review (reason for withdrawal)
1. **Delinquency states erased by the 5% minimum bin size.** 30-59 dpd is 1.1% and 60-89 dpd
   0.26% of snapshots, so neither could form a bin: current_dpd, max_dlq_12m, ever_deferred and
   ever_modified got a single bin (IV 0) and months_since_30dpd was reduced to "ever vs never".
   dev_holdout, actual vs predicted: 60-89 dpd 69.3% vs 13.0%; 30-59 dpd 25.0% vs 10.7%; cured
   13+ months ago 1.5% vs 6.8%. OOT1: 60-89 dpd 53% vs 4.5%. Impact: Stage 2 PDs and any
   PD-based SICR test would be badly wrong for exactly the delinquent loans.
2. **`orig_interest_rate` is an era proxy.** PSI dev → OOT 1.65 / 1.97 / 1.49: the level of
   mortgage rates identifies the origination period, not the borrower. `rate_spread` (rate
   minus the same-month average) carries the loan-level signal.
3. **`channel` coding change.** Freddie reported third-party originations as `T` before 2008 and
   as `B` / `C` afterwards: PSI 0.79 / 0.96 / 1.09 from a disclosure change, not a risk change.

Score PSI dev → OOT 0.31 / 0.45 / 0.50, driven by 2 and 3.

### Note on reproducibility
The v1.0.0 pickles are kept as evidence together with their tables and model card. Scoring
them needs the v1.0.0 feature code (channel not recoded, orig_interest_rate present), which is
not preserved because the project was not yet under version control. The repository has been
under git since v1.1.0 (commit `4f71e0a`), which closes this gap from v1.1.0 onwards.
