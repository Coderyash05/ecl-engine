# Limitations, overlays and findings register

One register for every known limitation, post-model adjustment and validation finding, with its
monitoring trigger (ACPIR para 131: explicit numerical triggers). Each model's entry in
`config/models.yaml` lists its limitations (by id, or in words for the PD models). Detail and measured values sit in the model
CHANGELOGs (`models/*/CHANGELOG.md`) and the [validation report](validation_report.md).
Developer self-validation; not independent. US data except I-1 to I-9 (SYNTHETIC India).

Direction: whether the limitation makes the provision too high (conservative) or too low
(non-conservative).

## Model limitations

| Id | Model | Limitation | Direction | Trigger |
|---|---|---|---|---|
| L-PIT1 | PIT PD | Crisis peak under-predicted and early (2.74% in 2008Q4 vs 3.33% in 2009Q1) | non-conservative in a crisis; covered in the downside by CO-3 | crisis replay outside tolerance on a refit |
| L-PIT2 | PIT PD | Out-of-time 2017-23 used for driver selection: not a fully clean test period | - | next refit: hold out the latest years |
| L-PIT3 | PIT PD | rho is the Basel benchmark (0.15), not identifiable from the data; Z is not N(0, 1) | - | sensitivity 0.10 / 0.20 reported |
| L1 | Lifetime PD | 60-89 dpd year-2 lifetime PD understated (0.55 dev / 0.60 OOT) | non-conservative, small (~30 defaults) | annual jump check < 0.8 with >= 100 year-2 defaults |
| L2 | Lifetime PD | TTC decile jump mis-fit (deciles 6 and 9: 0.73-0.82) | mixed | a decile with >= 100 year-2 defaults outside 0.8-1.25 twice |
| L3 | Lifetime PD | Carry fade tau = 3 set by decision, not identified on development data | - | OOT error at tau 3 more than 25% above the OOT optimum (now 7%) |
| L4 | Lifetime PD | 2012-16 vintages over-predicted (year-1 0.53-0.54) | conservative | prepay actual / predicted < 0.7 for the latest two vintages |
| L5 | Lifetime PD | Carried ratio not split into a persistent segment part and a fading cycle part (refinement not built) | - | with L2 / L3 |
| L6 | Scenarios | CO-3 front-loads defaults (2005 holdout 0.71 at 3 years) | conservative | re-test on any refit |
| L7 | Scenarios | CO-4 benchmark not mix-adjusted | - | CO-4 ratio > 1.25 after B-18 relabelling |
| L8 | Scenarios | Vasicek shift applied to delinquency prevalence (approximation) | - | default incidence remains the deciding rate |
| L9 | Scenarios | One backtest date (2023-03) | - | add each reporting date |
| L-LGD1 | LGD | Post-2017 LGD over-predicted (0.29-0.55) | conservative, immaterial after floors | Stage 1 model coverage > 0.20% or < 75% of Stage 3 accounts floored |
| L-LGD2 | LGD | Resolution bias: unresolved and incomplete workouts excluded | non-conservative for recent periods | resolved share of a period < 90% |
| L-LGD3 | LGD | First default only; cure costs not counted | non-conservative, small | - |
| L-LGD4 | LGD | Relief at default set to 0 in projection | conservative | - |
| L-LGD5 | LGD | Stage 3 LGD not scenario-weighted; CO-5 not applied to Stage 3 | immaterial (floors) | as L-LGD1 |
| L-LGD6 | LGD | Recoveries timed at zero balance; late insurance claims not discounted further | small | - |
| L-LGD7 | LGD | Realisation haircut 47.7% includes distressed-sale discounts | conservative for the secured portion | - |
| L-LGD8 | LGD | Development-period calibration 1.31 (level set on 2012-19) | - | at refit |
| L-ECL1 | Staging | Restructuring readings: RSA 124M timing not applied; calamity date proxied; category (xiv) kept for life; 1-29 day misses invisible | mostly conservative | RSA amendment; data with day-level arrears |
| L-ECL2 | Staging | Loan level = borrower level (para 76) | - | multi-loan borrower data |
| L-ECL3 | Staging | Stage 2 anticipates 33% of next-year defaults | - | < 30% with 12 months of outcomes |
| L-ECL4 | Measurement | Stage 3 LGD not scenario-weighted | immaterial | as L-LGD1 |
| L-ECL5 | Measurement | Quarter-after staging reuses the date's scenarios | diagnostic only | - |
| L-ECL7 | Measurement | 2026-03 anticipation measured on 3 months of outcomes | - | re-measure when the data extend |
| L-ECL8 | Staging | Arrears cleared proxied by status 00 | slightly lenient | as L-ECL1 |
| R-1 | Reporting | Dry run: the Directions use the balance sheet of 2027-03-31; 2026-03-31 is a dry run | - | real first application |
| R-2 | Reporting | CET1 add-back fractions applied pre-tax (no tax rate modelled) | - | - |
| R-3 | Reporting | Retained earnings (Table 9) and investments / commitments (Tables 1.B, 1.C, 3.B) not applicable | - | - |
| R-4 | Reporting | DPD buckets from monthly status (00 = current and 1-29 days) | - | - |
| R-5 | Reporting | Old rules: outstanding = EAD now; realisable value = secured portion; IRACP 68(1) erosion not applied | - | - |
| R-6 | Reporting | Table 3 write-offs = derecognition at loss-type zero-balance codes | - | - |
| R-7 | Reporting | 2023-03-31: no 2022 run, so no previous-year columns or Table 3 | - | - |
| R-8 | Reporting | The transition sign depends on the IRACP additional provisions (RSA 64, 84A / 84B): base rates alone give ECL 50.5m above IRACP | - | abs(ECL - IRACP) < 10% of the IRACP additional provisions -> report both RSA 64 readings |
| G-1 | Governance | User ids are free text; log retention depends on backups; a deleted tail is visible only against a run record's head hash | - | bank deployment: authenticated ids, write-once storage |
| G-2 | Governance | Overlay changes controlled by clean-tree git versioning, not by the maker-checker log | - | future enhancement |
| G-3 | Governance | Tiering not independently reviewed (para 121) | - | independent review |
| G-4 | Governance | Outputs are regenerated module by module; a code fix can leave downstream committed outputs stale (M-7) | - | a full clean-tree rerun does not reproduce the committed outputs (regression check before every results commit) |
| I-1 | India (synthetic) | GDP base change: the 2011-12 and 2022-23 NAS bases disagree on YoY growth in the overlap (correlation -0.008); growth chained, break at 2023Q2 | - | MoSPI back series on the 2022-23 base |
| I-2 | India (synthetic) | HPI 2022-23 re-basing: YoY growth inconsistent in the 2022-25 overlap (all-India correlation -0.14) | - | DBIE linked series |
| I-3 | India (synthetic) | US borrower behaviour: PD rank order, macro sensitivity and delinquency states are US; employment, payment-shock and LGD parameters are assumptions | - | - |
| I-4 | India (synthetic) | US lifetime PD over the US remaining life spread over the Indian tenure (constant hazard) | - | - |
| I-5 | India (synthetic) | No restructuring or calamity history in the synthetic book | - | - |
| I-6 | India (synthetic) | Path-independent rate mechanics (rate change measured from origination to the date) | - | - |
| I-7 | India (synthetic) | Equal city weights (random RBI HPI city, not the lending mix) | - | - |
| I-8 | India (synthetic) | Replicated delinquent loans (k = 1.64; 2,848 copies) share every attribute with their originals | - | - |
| I-9 | India (synthetic) | CPI April-May 2020 are MoSPI imputations (status F*), inside the excluded COVID window | - | - |

## Post-model adjustments (para 131; Annex 4 Table 6)

Defined in `config/overlays.yaml`.

| Id | Overlay | Status | Effect | Removal / review trigger |
|---|---|---|---|---|
| CO-1 | COVID mass forbearance: 60-89 dpd PD too high (OOT2 17% actual vs 51% predicted) | candidate, not applied | would lower the PD | relief share of 30-89 dpd > 15% in a quarter, or actual / predicted < 0.70 for two quarters |
| CO-2 | Ever-deferred loans: PD too low (OOT1 12.1% vs 9.1%) | candidate, not applied | would raise the PD | actual / predicted > 1.25 over four quarters with >= 100 defaults |
| CO-3 | Downside crisis multiplier on default odds, M = 3.06 sand states / 1.21 elsewhere | **applied** (accepted as calibrated; L6) | model ECL +6.3%, provision +0.3% (with CO-5) | a regional factor or satellite that passes the replay without M; M interval includes 1 |
| CO-4 | 2024-26 vintages early defaults 1.64x (about 1.15 excluding relief) | candidate, monitored | - | ratio > 1.25 after relief cures |
| CO-5 | Downturn LGD in the downside, ratio 1.507 x severity scale | **applied** | included in CO-3's effect | refit with a crisis ratio <= 1.10 |

## Validation findings

| Id | Rating | Finding | Status / action |
|---|---|---|---|
| H-1 | High | The provision rests on the developer's reading of the RSA Directions: restructured accounts are 65% of the 2026 provision; the readings move it by -23% to +29% (deferral mapping) or -66% to +11% (restructuring mapping) | Model-owner decision 2026-11-14: requires compliance review; open until reviewed |
| H-2 | High | No independent validation (developer, owner and validator are one person); OOT 2017-23 used for PIT driver selection | Independent validation (para 97 before the own LGD replaces the fallback; para 130) |
| M-1 | Medium | PD target B-18 vs RBI 90+ default: 2023 backtest RBI 1.11 overall, Stage 2 1.30. Relief cures credited in both the PD target and the cure-model recalibration: +1.7% of Stage 1-2 model ECL | Keep and monitor (< 5% retrain threshold). Trigger: Stage 2 RBI actual / predicted > 1.25 at the next backtest |
| M-2 | Medium | Transition sign depends on the IRACP additional provisions (R-8) | Use actual RSA 64 / 84A balances at the real first application |
| M-3 | Medium | Stage 2 anticipates only 33% of next-year defaults (L-ECL3) | Review SICR thresholds or add behavioural triggers if < 30% |
| M-4 | Medium | Crisis vintages under-predicted by the lifetime PD (2007: 10.2% vs 14.1%), covered only in the downside by CO-3 | Regional factor in the hazard (CO-3 removal trigger) |
| M-5 | Medium | Floors set 87% of the provision: model weaknesses are hidden while the floors bind | Monitor the floor triggers; report model ECL alongside |
| M-6 | Medium | Override control gaps (G-1) | Recorded as a limitation of a local tool (model-owner decision 2026-11-14) |
| M-7 | Medium | Committed outputs were stale: 2026-03 scenario-PD and LGD summaries predated the fix for loans with unavailable delinquency status (XX); the LightGBM challenger and some sums were not bit-reproducible (G-4) | Fixed 2026-11-15: deterministic fits (pd12m-1.2.1), every output regenerated from one clean-tree run, headlines unchanged. Prevention: a full clean-tree rerun must reproduce the committed outputs before any results commit |
| L-1 | Low | Upside GDP at the 76-77th percentile of forecast errors (combined index passes) | None |
| L-2 | Low | PIT over-predicts in COVID (0.77) and recovery (0.86); OOT3 1.15 | CO-1 trigger |
| L-3 | Low | LGD post-2017 over-predicted (conservative; ECL loss ratio 0.09) | L-LGD1 trigger |
| L-4 | Low | Overlay approvals not enforced by the override log (G-2) | Future enhancement |
| L-5 | Low | Tiering not independently reviewed (G-3) | Independent review |
