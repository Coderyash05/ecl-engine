# Model card: 12-month PD (pd12m-1.2.0)

**Code version.** git commit `424af508bb1265bfd5c040b5030b7788546640ae` (code and regulatory config committed); fitted 2026-11-15.

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
2023-12-01 (data end 2026-06-01). Development 2000-2016 (80% train / 20%
loan-level holdout), out-of-time OOT1 2017-19, OOT2 2020-21, OOT3 2022-23.

**Target.** B-18: RBI 90+ default (paras 6(5), 8(1)) within 12 months, except relief months
(forbearance / deferral / disaster) cured within 18 months with no loss — a post-2014 relief
adjustment (relief fields exist only from 2014). Sensitivities: A (RBI 90+, nothing relabelled)
and B-12.

**Training sample.** All 127,975 defaults + 15% of
non-defaults (seed 20261112); non-default weight 6.667, so PDs stay on
the population scale (weighted default rate 1.2361% vs
population 1.2356%).

**Champion.** WoE logistic scorecard (optbinning). Binning policy: continuous features get
optimal bins of at least 5% of weighted snapshots with monotonic trends where
they make business sense; delinquency states, flags and categoricals keep their natural
categories, merged only if a category is below 0.5% of weighted snapshots
**and** below 500 defaults (the default count governs how stable a bin's
default rate is, so 60-89 dpd — 0.26% of snapshots, ~18,700 defaults — keeps its bin). Missing
values get their own bin. Selection: IV < 0.02 dropped, IV > 0.5 flagged;
|corr| > 0.7 and VIF > 5.0 dropped (both weighted to the population); wrong-sign
coefficients dropped. Points: 600 at odds 50:1, 20 points to double the
odds (documented choice). No macro variables.

**Delinquency state.** current_dpd, months_since_30dpd and max_dlq_12m overlap by construction
(correlations below), so one ordered state, `dlq_state`, combines them: never 30+ dpd / cured
13+ / 4-12 / 1-3 months ago / 30-59 dpd / 60-89 dpd. It has the highest IV and the other three
are dropped by the correlation rule (screens use its WoE; the VIF shown for it is the WoE
column's). IV > 0.5 is expected for a behavioural state observed at the snapshot
date (a 60-89 dpd loan is one missed payment from default); it is not target leakage.
`dlq_state` enters the regression as **dummy variables** (base = never 30+ dpd), every other
feature as WoE: each state has its own coefficient and its own points, and the fitted PD of each
state equals its default rate in the training sample. Dummy coefficients rise monotonically
with severity: **True**.

**Changes from v1.1.0** (see models/pd_12m/CHANGELOG.md): dlq_state dummy-coded instead of
one WoE column (one coefficient scaled all six states; 60-89 dpd was under-predicted); binning
policy amended from "rare or thin" to "rare and thin".

**Challenger.** LightGBM on the same features with matching monotone constraints, early
stopping on dev_holdout (298 trees).

## Features (IV, selection)
| name | n_bins | iv | iv_flag | decision | reason |
|---|---|---|---|---|---|
| dlq_state | 6 | 2.0679 | suspicious: IV > 0.5 | kept |  |
| months_since_30dpd | 4 | 1.9348 | suspicious: IV > 0.5 | dropped | |corr| 0.99 with dlq_state (higher IV) |
| max_dlq_12m | 3 | 1.7827 | suspicious: IV > 0.5 | dropped | |corr| 0.90 with dlq_state (higher IV) |
| current_dpd | 3 | 1.6374 | suspicious: IV > 0.5 | dropped | |corr| 0.75 with dlq_state (higher IV) |
| credit_score | 15 | 0.7861 | suspicious: IV > 0.5 | kept |  |
| current_ltv | 16 | 0.5971 | suspicious: IV > 0.5 | kept |  |
| orig_cltv | 9 | 0.2603 |  | dropped | |corr| 0.73 with current_ltv (higher IV) |
| orig_ltv | 10 | 0.2556 |  | dropped | |corr| 0.75 with current_ltv (higher IV) |
| rate_spread | 11 | 0.2532 |  | kept |  |
| orig_dti | 13 | 0.2315 |  | kept |  |
| num_borrowers | 2 | 0.1097 |  | kept |  |
| loan_age | 13 | 0.1048 |  | kept |  |
| loan_purpose | 3 | 0.0645 |  | kept |  |
| channel | 2 | 0.0631 |  | kept |  |
| harp_loan | 2 | 0.0136 | drop: IV < 0.02 | dropped | IV 0.0136 < 0.02 |
| property_type | 4 | 0.0122 | drop: IV < 0.02 | dropped | IV 0.0122 < 0.02 |
| ever_modified | 2 | 0.0067 | drop: IV < 0.02 | dropped | IV 0.0067 < 0.02 |
| first_time_homebuyer | 2 | 0.0038 | drop: IV < 0.02 | dropped | IV 0.0038 < 0.02 |
| occupancy_status | 3 | 0.0026 | drop: IV < 0.02 | dropped | IV 0.0026 < 0.02 |
| num_units | 2 | 0.0008 | drop: IV < 0.02 | dropped | IV 0.0008 < 0.02 |
| ever_deferred | 1 | 0.0000 | drop: IV < 0.02 | dropped | IV 0.0000 < 0.02 |

## Categories merged by the binning policy
| feature | merge |
|---|---|
| ever_deferred | edge 0.5 removed: bin with 0.000% of snapshots, 1 defaults |
| ever_deferred | single bin: no category large enough to stand alone |
| property_type | CP merged with PU: 0.273% of snapshots, 178 defaults |

## Delinquency features: correlation of WoE (weighted)
| feature | dlq_state | current_dpd | months_since_30dpd | max_dlq_12m | ever_modified |
|---|---|---|---|---|---|
| dlq_state | 1.0000 | 0.7528 | 0.9913 | 0.8973 | 0.0629 |
| current_dpd | 0.7528 | 1.0000 | 0.7388 | 0.5999 | 0.0176 |
| months_since_30dpd | 0.9913 | 0.7388 | 1.0000 | 0.8906 | 0.0627 |
| max_dlq_12m | 0.8973 | 0.5999 | 0.8906 | 1.0000 | 0.0528 |
| ever_modified | 0.0629 | 0.0176 | 0.0627 | 0.0528 | 1.0000 |

## Coefficients (WoE features: negative; dlq_state dummies: positive and rising)
| term | coefficient | odds_ratio_vs_base | iv | n_bins | vif | expected_sign |
|---|---|---|---|---|---|---|
| intercept | -4.9789 | nan | nan | nan | nan |  |
| dlq_state: never 30+ dpd | 0.0000 | 1.0000 | 2.0679 | 6 | 1.0655 | 0 (base) |
| dlq_state: cured 13+ months | 0.5532 | 1.7388 | 2.0679 | 6 | 1.0655 | positive, rising |
| dlq_state: cured 4-12 months | 1.3489 | 3.8534 | 2.0679 | 6 | 1.0655 | positive, rising |
| dlq_state: cured 1-3 months | 2.2028 | 9.0499 | 2.0679 | 6 | 1.0655 | positive, rising |
| dlq_state: 30-59 dpd | 3.3087 | 27.3506 | 2.0679 | 6 | 1.0655 | positive, rising |
| dlq_state: 60-89 dpd | 5.3182 | 204.0181 | 2.0679 | 6 | 1.0655 | positive, rising |
| credit_score | -0.4920 | nan | 0.7861 | 15 | 1.1204 | negative (on WoE) |
| current_ltv | -0.8603 | nan | 0.5971 | 16 | 1.1801 | negative (on WoE) |
| rate_spread | -0.2485 | nan | 0.2532 | 11 | 1.1347 | negative (on WoE) |
| orig_dti | -0.4394 | nan | 0.2315 | 13 | 1.0913 | negative (on WoE) |
| num_borrowers | -0.6513 | nan | 0.1097 | 2 | 1.0290 | negative (on WoE) |
| loan_age | -0.6596 | nan | 0.1048 | 13 | 1.0529 | negative (on WoE) |
| loan_purpose | -0.5426 | nan | 0.0645 | 3 | 1.0435 | negative (on WoE) |
| channel | -0.3116 | nan | 0.0631 | 2 | 1.0358 | negative (on WoE) |

## Calibration by delinquency state (target B-18)
| split | state | n | defaults | actual_rate | pd_champion | pd_challenger | pd_champion_v1.1.0 | actual_to_predicted |
|---|---|---|---|---|---|---|---|---|
| dev_holdout | never 30+ dpd | 2359360.0000 | 13282.0000 | 0.0056 | 0.0057 | 0.0056 | 0.0054 | 0.9818 |
| dev_holdout | cured 13+ months | 108824.0000 | 1660.0000 | 0.0153 | 0.0154 | 0.0155 | 0.0184 | 0.9937 |
| dev_holdout | cured 4-12 months | 50265.0000 | 2071.0000 | 0.0412 | 0.0391 | 0.0406 | 0.0480 | 1.0527 |
| dev_holdout | cured 1-3 months | 31026.0000 | 2858.0000 | 0.0921 | 0.0903 | 0.0931 | 0.1010 | 1.0207 |
| dev_holdout | 30-59 dpd | 29209.0000 | 7292.0000 | 0.2496 | 0.2440 | 0.2505 | 0.2480 | 1.0230 |
| dev_holdout | 60-89 dpd | 6621.0000 | 4587.0000 | 0.6928 | 0.6924 | 0.6974 | 0.6269 | 1.0006 |
| oot1 | never 30+ dpd | 3325334.0000 | 7196.0000 | 0.0022 | 0.0043 | 0.0031 | 0.0041 | 0.5008 |
| oot1 | cured 13+ months | 167645.0000 | 1347.0000 | 0.0080 | 0.0090 | 0.0099 | 0.0111 | 0.8888 |
| oot1 | cured 4-12 months | 56310.0000 | 1180.0000 | 0.0210 | 0.0239 | 0.0259 | 0.0301 | 0.8757 |
| oot1 | cured 1-3 months | 32059.0000 | 1651.0000 | 0.0515 | 0.0574 | 0.0636 | 0.0658 | 0.8978 |
| oot1 | 30-59 dpd | 26641.0000 | 3817.0000 | 0.1433 | 0.1624 | 0.1780 | 0.1676 | 0.8820 |
| oot1 | 60-89 dpd | 4562.0000 | 2422.0000 | 0.5309 | 0.5645 | 0.6015 | 0.4935 | 0.9405 |
| oot2 | never 30+ dpd | 1921532.0000 | 2985.0000 | 0.0016 | 0.0037 | 0.0027 | 0.0035 | 0.4234 |
| oot2 | cured 13+ months | 127380.0000 | 559.0000 | 0.0044 | 0.0074 | 0.0086 | 0.0091 | 0.5954 |
| oot2 | cured 4-12 months | 61626.0000 | 661.0000 | 0.0107 | 0.0208 | 0.0235 | 0.0262 | 0.5167 |
| oot2 | cured 1-3 months | 32138.0000 | 789.0000 | 0.0246 | 0.0514 | 0.0598 | 0.0592 | 0.4777 |
| oot2 | 30-59 dpd | 17107.0000 | 1569.0000 | 0.0917 | 0.1421 | 0.1657 | 0.1472 | 0.6455 |
| oot2 | 60-89 dpd | 8367.0000 | 1422.0000 | 0.1700 | 0.5121 | 0.5751 | 0.4438 | 0.3319 |
| oot3 | never 30+ dpd | 1908258.0000 | 3674.0000 | 0.0019 | 0.0035 | 0.0024 | 0.0033 | 0.5548 |
| oot3 | cured 13+ months | 170674.0000 | 765.0000 | 0.0045 | 0.0060 | 0.0074 | 0.0075 | 0.7434 |
| oot3 | cured 4-12 months | 44943.0000 | 723.0000 | 0.0161 | 0.0173 | 0.0203 | 0.0220 | 0.9295 |
| oot3 | cured 1-3 months | 21649.0000 | 988.0000 | 0.0456 | 0.0432 | 0.0523 | 0.0500 | 1.0575 |
| oot3 | 30-59 dpd | 15380.0000 | 2200.0000 | 0.1430 | 0.1300 | 0.1539 | 0.1348 | 1.1004 |
| oot3 | 60-89 dpd | 2947.0000 | 1416.0000 | 0.4805 | 0.5105 | 0.5665 | 0.4402 | 0.9412 |

## Loans with flags that are rare in development (not in the model)
| split | flag | n | defaults | actual_rate | pd_champion | pd_challenger |
|---|---|---|---|---|---|---|
| dev_holdout | ever_modified | 2771 | 192 | 0.0693 | 0.0812 | 0.0958 |
| dev_holdout | ever_deferred | 3 | 0 | 0.0000 | 0.0711 | 0.0944 |
| oot1 | ever_modified | 5079 | 161 | 0.0317 | 0.0309 | 0.0306 |
| oot1 | ever_deferred | 1766 | 214 | 0.1212 | 0.0908 | 0.0989 |
| oot2 | ever_modified | 2627 | 50 | 0.0190 | 0.0309 | 0.0314 |
| oot2 | ever_deferred | 27308 | 586 | 0.0215 | 0.0428 | 0.0475 |
| oot3 | ever_modified | 3937 | 122 | 0.0310 | 0.0231 | 0.0232 |
| oot3 | ever_deferred | 45648 | 1193 | 0.0261 | 0.0234 | 0.0263 |

## Known limitations recorded as candidate overlays (RBI para 131)
**No overlay is applied to the PDs.** Each item records the evidence, the direction of the bias
and a monitoring trigger. The trigger levels are proposed by the developer and are not RBI
values; they are to be confirmed by the model owner and validation (Module 11). If a trigger is
hit, an overlay needs its own justification, calculation and approval (Annex 4 Table 6).

### CO-1: delinquent loans in a mass-forbearance period (COVID, OOT2)
- **Evidence** (30-59 and 60-89 dpd snapshots, target B-18):

| split | state | n | defaults | actual_rate | pd_champion | actual_to_predicted |
|---|---|---|---|---|---|---|
| oot1 | 30-59 dpd | 26641.0000 | 3817.0000 | 0.1433 | 0.1624 | 0.8820 |
| oot1 | 60-89 dpd | 4562.0000 | 2422.0000 | 0.5309 | 0.5645 | 0.9405 |
| oot2 | 30-59 dpd | 17107.0000 | 1569.0000 | 0.0917 | 0.1421 | 0.6455 |
| oot2 | 60-89 dpd | 8367.0000 | 1422.0000 | 0.1700 | 0.5121 | 0.3319 |
| oot3 | 30-59 dpd | 15380.0000 | 2200.0000 | 0.1430 | 0.1300 | 1.1004 |
| oot3 | 60-89 dpd | 2947.0000 | 1416.0000 | 0.4805 | 0.5105 | 0.9412 |

  Share of 30-89 dpd loan-months under relief (forbearance / deferral / disaster), by year:

| year | loan_months_30_89_dpd | relief_share |
|---|---|---|
| 2014 | 52133 | 0.0050 |
| 2015 | 48083 | 0.0103 |
| 2016 | 46462 | 0.0113 |
| 2017 | 48864 | 0.0734 |
| 2018 | 46604 | 0.0412 |
| 2019 | 49112 | 0.0182 |
| 2020 | 75036 | 0.5791 |
| 2021 | 32553 | 0.3353 |
| 2022 | 32335 | 0.2153 |
| 2023 | 38436 | 0.1520 |
| 2024 | 47664 | 0.0839 |
| 2025 | 51750 | 0.0501 |
| 2026 | 27439 | 0.0312 |
- **Direction:** PD too high (conservative) for 30-89 dpd loans while relief is widespread:
  arrears under forbearance that cure within 18 months are not defaults under B-18, and the
  development window has almost no such loans (relief fields start in 2014).
- **Monitoring trigger:** relief share of 30-89 dpd loan-months above
  15% in a quarter (leading), or actual / predicted default rate of
  30-89 dpd loans below 0.70 in two consecutive labelled quarters with
  at least 100 defaults (lagging).

### CO-2: loans with a payment deferral (ever_deferred)
- **Evidence** (the flag has 5 snapshots in development, so the model cannot see it):

| split | n | defaults | actual_rate | pd_champion | actual_to_predicted |
|---|---|---|---|---|---|
| dev_holdout | 3 | 0 | 0.0000 | 0.0711 | 0.0000 |
| oot1 | 1766 | 214 | 0.1212 | 0.0908 | 1.3351 |
| oot2 | 27308 | 586 | 0.0215 | 0.0428 | 0.5017 |
| oot3 | 45648 | 1193 | 0.0261 | 0.0234 | 1.1164 |
- **Direction:** PD too low outside mass-relief periods (OOT1: deferral granted to a borrower
  in difficulty); too high when deferral is granted widely (OOT2). The binding risk is the
  under-prediction.
- **Monitoring trigger:** actual / predicted default rate of ever-deferred loans above
  1.25 over the last four labelled quarters with at least
  100 defaults; and at any refit, add ever_deferred as a candidate once it
  has 500 defaults in the development sample (binning policy).


## Change from v1.1.0 (target B-18; psi = score/PD PSI dev_train -> split)
| split | model | default_rate | gini | mean_pd | gini_prev | mean_pd_prev | delta_gini | delta_mean_pd | psi | psi_prev |
|---|---|---|---|---|---|---|---|---|---|---|
| dev_train (sample, weighted) | champion | 0.0124 | 0.8006 | 0.0124 | 0.8003 | 0.0124 | 0.0003 | -0.0000 | nan | nan |
| dev_train (sample, weighted) | challenger | 0.0124 | 0.8225 | 0.0124 | 0.8223 | 0.0124 | 0.0003 | 0.0000 | nan | nan |
| dev_holdout | champion | 0.0123 | 0.8031 | 0.0123 | 0.8031 | 0.0123 | -0.0000 | -0.0000 | nan | nan |
| dev_holdout | challenger | 0.0123 | 0.8208 | 0.0123 | 0.8206 | 0.0123 | 0.0002 | 0.0000 | nan | nan |
| oot1 | champion | 0.0049 | 0.7089 | 0.0072 | 0.7136 | 0.0072 | -0.0048 | -0.0000 | 0.0578 | 0.0519 |
| oot1 | challenger | 0.0049 | 0.7360 | 0.0064 | 0.7358 | 0.0063 | 0.0002 | 0.0000 | 0.1078 | 0.1054 |
| oot2 | champion | 0.0037 | 0.6936 | 0.0081 | 0.6982 | 0.0081 | -0.0046 | -0.0000 | 0.0870 | 0.0768 |
| oot2 | challenger | 0.0037 | 0.7162 | 0.0080 | 0.7167 | 0.0080 | -0.0005 | 0.0000 | 0.0900 | 0.0896 |
| oot3 | champion | 0.0045 | 0.7500 | 0.0059 | 0.7530 | 0.0060 | -0.0030 | -0.0001 | 0.1517 | 0.1313 |
| oot3 | challenger | 0.0045 | 0.7702 | 0.0056 | 0.7704 | 0.0055 | -0.0002 | 0.0000 | 0.1519 | 0.1550 |

## PSI dev_train -> OOT
| item | oot1 | oot2 | oot3 |
|---|---|---|---|
| channel | 0.0184 | 0.0159 | 0.0087 |
| credit_score | 0.0674 | 0.0820 | 0.0782 |
| current_ltv | 0.1013 | 0.3024 | 0.4832 |
| dlq_state | 0.0052 | 0.0116 | 0.0268 |
| loan_age | 0.1512 | 0.3208 | 0.3072 |
| loan_purpose | 0.0351 | 0.0338 | 0.0526 |
| num_borrowers | 0.0193 | 0.0330 | 0.0475 |
| orig_dti | 0.1472 | 0.1687 | 0.2347 |
| pd (challenger) | 0.1078 | 0.0900 | 0.1519 |
| rate_spread | 0.0255 | 0.0169 | 0.0161 |
| score (champion) | 0.0578 | 0.0870 | 0.1517 |

## Gini by split
| split | challenger | champion |
|---|---|---|
| dev_holdout | 0.8208 | 0.8031 |
| dev_train (sample, weighted) | 0.8225 | 0.8006 |
| oot1 | 0.7360 | 0.7089 |
| oot2 | 0.7162 | 0.6936 |
| oot3 | 0.7702 | 0.7500 |

## Metrics
| split | model | target | n | defaults | default_rate | mean_pd | gini | ks | brier |
|---|---|---|---|---|---|---|---|---|---|
| dev_train (sample, weighted) | champion | b18 | 1661784 | 127975 | 0.0124 | 0.0124 | 0.8006 | 0.6321 | 0.0102 |
| dev_train (sample, weighted) | challenger | b18 | 1661784 | 127975 | 0.0124 | 0.0124 | 0.8225 | 0.6537 | 0.0099 |
| dev_holdout | champion | b18 | 2585305 | 31750 | 0.0123 | 0.0123 | 0.8031 | 0.6368 | 0.0101 |
| dev_holdout | challenger | b18 | 2585305 | 31750 | 0.0123 | 0.0123 | 0.8208 | 0.6527 | 0.0099 |
| dev_holdout | champion_a | a | 2585289 | 31853 | 0.0123 | 0.0123 | 0.8024 | 0.6358 | 0.0101 |
| dev_holdout | champion_b12 | b12 | 2585305 | 31764 | 0.0123 | 0.0123 | 0.8032 | 0.6369 | 0.0101 |
| oot1 | champion | b18 | 3612551 | 17613 | 0.0049 | 0.0072 | 0.7089 | 0.5473 | 0.0044 |
| oot1 | challenger | b18 | 3612551 | 17613 | 0.0049 | 0.0064 | 0.7360 | 0.5689 | 0.0043 |
| oot1 | champion_a | a | 3609845 | 42072 | 0.0117 | 0.0072 | 0.5406 | 0.3884 | 0.0109 |
| oot1 | champion_b12 | b12 | 3612535 | 21764 | 0.0060 | 0.0072 | 0.6623 | 0.5000 | 0.0055 |
| oot2 | champion | b18 | 2168150 | 7985 | 0.0037 | 0.0081 | 0.6936 | 0.5374 | 0.0041 |
| oot2 | challenger | b18 | 2168150 | 7985 | 0.0037 | 0.0080 | 0.7162 | 0.5548 | 0.0042 |
| oot2 | champion_a | a | 2135934 | 30199 | 0.0141 | 0.0076 | 0.6507 | 0.4813 | 0.0119 |
| oot2 | champion_b12 | b12 | 2166181 | 11705 | 0.0054 | 0.0081 | 0.6789 | 0.5189 | 0.0054 |
| oot3 | champion | b18 | 2163851 | 9766 | 0.0045 | 0.0059 | 0.7500 | 0.5872 | 0.0040 |
| oot3 | challenger | b18 | 2163851 | 9766 | 0.0045 | 0.0056 | 0.7702 | 0.6046 | 0.0040 |
| oot3 | champion_a | a | 2113398 | 11371 | 0.0054 | 0.0056 | 0.7211 | 0.5583 | 0.0047 |
| oot3 | champion_b12 | b12 | 2154106 | 9778 | 0.0045 | 0.0059 | 0.7454 | 0.5814 | 0.0040 |

## Sensitivity (champion refitted on other targets)
| split | target | n | default_rate | mean_pd | gini | gini_b18 | delta_gini | mean_pd_b18 | delta_mean_pd |
|---|---|---|---|---|---|---|---|---|---|
| dev_holdout | a | 2585289 | 0.0123 | 0.0123 | 0.8024 | 0.8031 | -0.0007 | 0.0123 | 0.0001 |
| dev_holdout | b12 | 2585305 | 0.0123 | 0.0123 | 0.8032 | 0.8031 | 0.0001 | 0.0123 | 0.0000 |
| oot1 | a | 3609845 | 0.0117 | 0.0072 | 0.5406 | 0.7089 | -0.1682 | 0.0072 | 0.0000 |
| oot1 | b12 | 3612535 | 0.0060 | 0.0072 | 0.6623 | 0.7089 | -0.0466 | 0.0072 | 0.0000 |
| oot2 | a | 2135934 | 0.0141 | 0.0076 | 0.6507 | 0.6936 | -0.0428 | 0.0081 | -0.0006 |
| oot2 | b12 | 2166181 | 0.0054 | 0.0081 | 0.6789 | 0.6936 | -0.0147 | 0.0081 | -0.0001 |
| oot3 | a | 2113398 | 0.0054 | 0.0056 | 0.7211 | 0.7500 | -0.0289 | 0.0059 | -0.0004 |
| oot3 | b12 | 2154106 | 0.0045 | 0.0059 | 0.7454 | 0.7500 | -0.0046 | 0.0059 | -0.0001 |

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
