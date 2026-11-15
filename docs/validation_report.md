# Validation report - housing-loan ECL engine (RBI ECL Directions 2026)

> **Developer self-validation, NOT independent validation.** Prepared by the developer of the
> models (Yash), as evidence for a later independent validation under ACPIR paras 97, 123 and
> 130. The developer, owner and validator are the same person. No finding below has been
> challenged by an independent function.
>
> **US data.** All results come from the Freddie Mac Single-Family Loan-Level sample (1999-2026
> vintages), FHFA, FRED, SPF and SEP data, in US dollars. They are **not Indian risk estimates**.

Date 2026-11-14. Code: models as in `config/models.yaml`; ECL run code `70e66da` (2026-03 re-run on
the Module 9 code with no overrides: identical results); report code `525dbd4`; governance and
backtest code `1881a92`. Structure: ACPIR para 130 (1)-(8), then backtesting, sensitivities,
limitations, overlays and findings.

## 1. Scope and summary (para 130(1))

| Model (inventory key) | Version | Tier | Output | Use |
|---|---|---|---|---|
| 12-month TTC PD (`pd_12m`) | pd12m-1.2.1 | 1 | PD per performing loan; PD at origination | Stage 1 ECL, SICR comparator |
| PIT conversion (`pd_pit`) | pdpit-0.2.1 | 2 | Cycle index Z, PIT 12m PD | all PDs per scenario |
| Lifetime PD (`pd_lifetime`) | pdlife-0.4.0 | 1 | Default / prepay hazards by quarter | Stage 2 ECL, SICR test |
| Macro scenarios (`macro_scenarios`) | scen-0.2.0 | 2 | Base / upside / downside paths, weights 20/60/20 | Annex 4 Table 5, PD and LGD paths |
| LGD and EAD (`lgd`) | lgd-0.2.0 | 1 | P(no cure) x severity; EAD; secured portion | all stages |
| Staging rules (`staging`) | ecl-0.1.0 | 1 | Stage and the rule that fired | Stage 1/2/3 |
| ECL and floors (`ecl_measurement`) | ecl-0.1.0 | 1 | Provision after floors | allowance |
| Reports and transition (`reporting`) | report-0.1.0 | 3 | Annex 4 Tables 1-9, IRACP, transition | disclosure |

No vendor models. Regulatory use: the ECL allowance under the ACPIR Directions (paras 25-108) and
the Annex 4 disclosures. Headline (2026-03-31): model ECL 154.7m, **provision 1,229.9m (1.49% of
82.3bn)**; 2023-03-31 767.2m (1.34%). The prudential floors set most of the provision, and
restructured accounts are 65% of it. Development challenges are recorded in the CHANGELOGs:
v1.0.0 PD binning defects, the crisis under-prediction behind CO-3 / CO-5, and the restructuring
readings of the RSA Directions.

## 2. Inputs (para 130(2))

- **Source and automation.** 56 Freddie Mac sample files (31 origination / 35 performance columns,
  Release 47) loaded by `ecl build-panel`. Every line is parsed against
  `config/freddie_layout.yaml`; no manual steps. Result: 1,375,000 loans and 76.0m loan-months;
  0 orphan loans and 0 duplicate loan-months (`reports/summary/qc_by_vintage.csv`). Macro:
  FHFA all-transactions state HPI, FRED GDP / HPI / mortgage rate / unemployment, SPF and SEP
  medians (checked against the PDF text).
- **Quality controls.** Release 47 sign convention for loss fields (recoveries negative), with the
  loss identity checked on every liquidation. Status XX loans are scored as current and flagged
  (3,358 at 2026-03); the run raises on any missing PD. HPI is missing for PR / GU / VI (2,332
  loans): current LTV is left NULL and handled by a WoE missing bin.
- **Transformations and assumptions.**
  - Current LTV is built from the state HPI.
  - Missing DTI goes to its own bin; HARP loans are kept.
  - The PD target is B-18 (relief defaults that cure within 18 months are relabelled); the
    default and staging definition is RBI 90+.
  - The origination quarter is taken as the first payment date minus one month (99.995%
    agreement).
  - COVID relief months are flagged, not dropped.
- **Sensitivity of material inputs** (section 10): LGD source (own estimate vs fallback), the
  restructuring and deferral readings, the SICR threshold, scenarios.

**Assessment:** inputs are reproducible and fully automated. The main input risk is the gap
between the B-18 PD target and the RBI 90+ ECL default definition (finding M-1).

## 3. Methodology (para 130(3))

| Component | Method | Soundness review |
|---|---|---|
| 12m PD | WoE logistic scorecard, 9 features, delinquency state as dummies; LightGBM challenger | Coefficients have the expected signs; max VIF 1.18; challenger only +0.02 Gini; TTC by design (para 45: lifetime not derived mechanically from it) |
| PIT | Vasicek one-factor shift, rho 0.15 (Basel benchmark); satellite Z on HPI and GDP YoY | Driver rule set ex ante; rho not identifiable from the data (L-PIT, sensitivity 0.10 / 0.20) |
| Lifetime PD | Competing-risk quarterly MNL (default / prepay / survive); year-1 spliced to PIT with a fading carry (tau = 3) | Para 45 satisfied (separate hazard); tau set by owner decision (L3) |
| Scenarios | SPF / SEP base; VAR-conditional HPI; 20/60/20 region means on a combined severity index | Mean reversion beyond 12 quarters (paras 49, 124); severity calibrated on a combined index (section 9) |
| LGD | P(no cure given months in default) x discounted severity (fractional logit on indexed LTV, MI, size, type); intercept recalibrated on 2012-19 | Para 99 own estimate; realisation haircut 47.7% for the secured portion (6(24)) |
| EAD | Amortisation schedule with prepayment; no netting (para 100) | - |
| Staging | 30+ dpd backstop; lifetime-PD ratio >= 2.5x and +0.5 pp against the seasoning-adjusted origination comparator (para 26); indexed LTV; RBI default until arrears cleared (8(10)); restructuring per RSA 52-62 (owner reading); calamity route per RSA VI-A | Every loan records the rule that fired; rules in config |
| Measurement | 12m (Stage 1) and lifetime (Stages 2-3) ECL per scenario, discounted at the note rate (para 51 transitional), probability-weighted | Note rate used as the EIR proxy (documented) |
| Floors | Per category (para 90-92): (xi)(a) 0.25% / 1.50%, (xiv) 5% / 10% at portfolio level; Stage 3 per account by duration and secured / unsecured portion | Values quoted from the Directions in `config/rbi_2026.yaml` |

The developer tests reviewed are those in the module CHANGELOGs. 223 unit tests cover each
regulatory rule with a hand-built example.

## 4. Use (para 130(4))

- **Intended use:** ECL allowance and Annex 4 disclosures for individual housing loans (item
  (xi)(a)), plus calamity-restructured standard advances (item (xiv)). The engine also computes
  the old-rules (IRACP 2025) provision for the transition (paras 107-108).
- **Not for:** Indian provisioning or capital figures. The parameters are estimated on US data;
  Module 12 (synthetic Indian portfolio) is the planned test of portability.
- **Compliance points:**
  - The PD floor of 0.03% (para 96) applies to the 12-month PD; the lifetime-annual floor is an
    interpretation and is marked `rbi_specified: false`.
  - The LGD is an own estimate that has not been independently validated. Para 97 expects
    validation before an own estimate replaces the 65 / 70% fallback, so a bank could not use
    lgd-0.2.0 today. The fallback provision is 1,765.0m (finding H-2).

## 5. Monitoring and maintenance (para 130(5))

Each model in `config/models.yaml` carries `monitoring` triggers (numerical, para 131) and a
`limitations` list. The main ones:

| Area | Trigger | Current reading |
|---|---|---|
| PD discrimination | Gini on latest labelled 12 months < 0.65 | 0.75 (OOT3) |
| PD stability | score PSI > 0.25 (review), 0.10-0.25 (watch) | 0.15 (OOT2) - watch |
| PIT calibration | actual / weighted PD outside 0.8-1.25 at the 12-month backtest | 0.84 (2023-03, B-18) |
| ECL defaults | actual / predicted 12m defaults outside 0.8-1.25 | RBI 1.11, B-18 0.88 (2023-03) |
| Stage 2 anticipation | < 30% with >= 12 months of outcomes (L-ECL3) | 33% (2023-03) |
| LGD | actual / predicted by default period outside 0.8-1.25 (>= 200 resolved) | 0.55 (2017-19) - fires; conservative, immaterial while floors bind |
| Floors | Stage 1 model coverage > 0.20% or < 75% of Stage 3 floored | 0.05%; 94-97% |
| CO-4 | 2024-26 vintage actual / expected > 1.25 with >= 20 events | 1.64 raw, ~1.15 ex-relief - monitored |
| Transition | abs(ECL - IRACP) < 10% of the IRACP additional provisions (R-8) | 51.8m vs 10.2m - not fired |

Open issues and actions are in the findings table (section 13).

## 6. Access and change controls (para 130(6); Annex 3)

- **Version control.** Everything lives in a git repository (local, single developer). Each
  model fit and ECL run records its git commit and a clean-tree flag in its outputs. The rule
  is: commit the code, run from a clean tree, then commit the results.
- **Configuration.** RBI values live only in `config/rbi_2026.yaml` and
  `config/rbi_iracp_2025.yaml`, each with its paragraph reference. A change to
  `rbi_2026.yaml` needs the owner's explicit approval. Developer choices are marked
  `rbi_specified: false`.
- **Manual overrides (Module 9; Annex 3 1(5), 3(2)-(4)).**
  - `ecl governance` with `ecl.governance.overrides`.
  - A maker proposes an override (account, new stage, reason, designation, effective date); a
    different checker approves it; revocations need two users as well.
  - Each step is one appended line in a hash-chained JSON-lines log. Editing, deleting or
    reordering a line breaks the chain, and the log refuses further writes.
  - The next ECL run applies approved overrides and records the log head hash. Outputs keep the
    system stage next to the overridden one (Annex 4 "Manual overrides" table).
  - Moving a system NPA out of Stage 3 needs an explicit NPA exception (Annex 3 3(2)).
- **Gaps (finding M-6):**
  - User IDs are free text, not authenticated.
  - The log sits under `data/` (gitignored, because it holds Freddie loan ids), so its 3-year
    retention depends on backups.
  - Deleting the tail of the log is detected only against the head hash stored in a run record.
  - There is no segregation of duties: one person develops, owns and validates.

## 7. Model inventory (para 130(7); paras 120-121)

`config/models.yaml` lists 8 entries:
- PD 12m, PIT, lifetime PD, scenarios, LGD / EAD, staging rules, ECL and floors, reporting.

Each entry records the para-120 fields: owner, developers, users, intended use, tier and
rationale, dependencies, version, git hash, validation status, limitations, overlays and
monitoring. `ecl governance inventory` checks four things: every required field is
present, dependencies resolve to models or files without cycles, overlays exist in
`config/overlays.yaml`, and each code commit exists in git. It currently reports no findings.

Tiering criteria (para 121; developer criteria in `config/governance.yaml`) are output
materiality. The floors mute PD and scenario effects on the provision, so `pd_pit` and
`macro_scenarios` are tier 2 for now. Para 121's independent review of the tiering has not
taken place.

## 8. Tests (para 130(8))

- **Quantitative:** discrimination (Gini, KS) and calibration on development, holdout and three
  OOT periods. Also:
  - PIT backtests by period and segment;
  - lifetime vintage curves and jump checks;
  - crisis replay of the 2005-07 vintages;
  - LGD actual / predicted by default period;
  - scenario severity against historical forecast errors;
  - 12-month ECL backtest;
  - Stage 2 anticipation;
  - sensitivity grids.
- **Qualitative:**
  - Regulatory text is quoted for every rule (`docs/methodology/`, `docs/regulatory_mapping.md`).
  - Owner decisions are recorded with their dates.
  - 223 unit tests, at least one hand-built example per rule. They cover staging, floors,
    restructuring (RSA 58 / 61 / 62), the calamity route, IRACP classes, reconciliation,
    transition, the override controls and the inventory.
  - ruff clean.
- **Rationale:** results are reported on both dates (2026-03-31 and 2023-03-31) and against the
  primary and alternative readings of the text, so the impact of each judgement is visible.

## 9. Backtesting (para 131)

**12-month PD (B-18 target).**

| Sample | Gini | Mean PD / actual |
|---|---|---|
| Dev holdout | 0.803 | 1.23% / 1.23% |
| OOT1 2017-19 | 0.709 | 0.72% / 0.49% |
| OOT2 2020-21 | 0.694 | 0.81% / 0.37% |
| OOT3 2022-23 | 0.750 | 0.59% / 0.45% |

Holdout calibration by delinquency state is 0.98-1.05. The OOT gap in the level is by design:
the model is TTC.

**PIT (actual / PIT PD by period).**

| Pre-crisis | Crisis | Recovery | OOT1 | COVID | OOT3 |
|---|---|---|---|---|---|
| 1.02 | 1.06 | 0.87 | 0.86 | 0.77 | 1.15 |

The scenario-weighted backtest at 2023-03-31 gives 0.84. At the realised Z it is 1.01: the gap
comes from the macro outcome (realised path at the 90th percentile).

**Lifetime PD.**
- Year-1 hazard / PIT 0.92-1.09 in every period.
- Jump-check flags 5 / 5 (dev / OOT). Recently delinquent and cured states fall within
  0.8-1.25, except 60-89 dpd (L1).
- Crisis vintages are under-predicted: the 2007 vintage reaches a 5-year cumulative default of
  10.2% predicted vs 14.1% actual.
- Crisis replay with CO-3: the 2006-07 vintages land at 0.90-1.09 at 5 years. The 2005 hold-out
  gives 0.82 at 5 years and 0.71 at 3 years (fails, conservative: L6).

**LGD (actual / predicted, lgd-0.2.0).**

| Development | 2000-06 | Crisis 2007-11 | 2012-16 | 2017-19 | OOT 2017+ |
|---|---|---|---|---|---|
| 1.31 | 0.84 | 1.51 | 1.05 | 0.55 | 0.29 |

The crisis gap of 1.51 is covered by CO-5 in the downside. Post-2017 losses are over-predicted
(L-LGD1, conservative).

**Scenarios.** Downside and upside sit at the 14-15th and 86-87th percentiles of the combined
severity index (inside the 5-20 and 80-95 bands) on both dates. The upside GDP alone sits at the
76-77th percentile; the combined severity index passes. The realised 2023Q2-2026Q1 path ranked at
the 90th percentile, above the upside.

**ECL backtest, 2023-03-31 performing loans, next 12 months**
(`reports/summary/validation_ecl_backtest_2023-03.csv`; `ecl backtest`).

| | Stage 1 | Stage 2 | Total |
|---|---|---|---|
| Loans | 269,381 | 4,798 | 274,179 |
| Predicted defaults (weighted 12m PD) | 1,005 | 546 | 1,551 |
| Actual RBI 90+ defaults (actual / predicted) | 1,008 (1.00) | 708 (**1.30**) | 1,716 (**1.11**) |
| Actual B-18 defaults (actual / predicted) | 769 (0.76) | 589 (1.08) | 1,358 (0.88) |
| Predicted 12m ECL (m) | 26.9 | 9.9 | 36.8 |
| Realised loss on those defaults to 2026-06 (m) | 2.2 | 1.0 | 3.2 (**0.09**) |
| Defaults liquidated / cured or prepaid / unresolved | 72 / 911 / 25 | 46 / 644 / 18 | 118 / 1,555 / 43 |

The default count is well calibrated in Stage 1. Stage 2 is under-predicted on the RBI
definition, because the PD target B-18 relabels relief defaults that cure (finding M-1). Losses
are about a tenth of the 12-month ECL: 91% of these defaults cured or prepaid, and post-2017 LGD
is over-predicted (L-LGD1). The predicted ECL is discounted and the realised loss is not, so this
ratio is indicative only. Stage 2 anticipation: 33% of the next-12-month defaults were in
Stage 2 at the date (L-ECL3). The 2026-03 anticipation has only 3 months of outcomes (L-ECL7).

## 10. Sensitivities

Provision (m); primary 2026-03 1,229.9, 2023-03 767.2.

| Sensitivity | 2026-03 | 2023-03 | Change 2026 |
|---|---|---|---|
| SICR ratio 2.0 / 3.0 (primary 2.5) | 1,243.6 / 1,226.3 | 773.5 / 763.7 | +1.1% / -0.3% |
| LGD option 1 (development fit) | 1,244.7 | 773.3 | +1.2% |
| RBI fallback LGD 65 / 70% | 1,765.0 | 1,042.8 | **+43.5%** |
| Restructured: every account Stage 3 (upper bound) | 1,360.5 | 848.8 | +10.6% |
| Restructured: every account at least Stage 2 (lower bound) | 419.3 | 317.6 | -65.9% |
| Deferrals unmapped (modifications only) | 951.7 | 615.6 | **-22.6%** |
| All deferrals general restructuring | 1,590.7 | 1,030.1 | **+29.3%** |
| Without CO-3 and CO-5 (model ECL 145.6 / 69.9m) | 1,226.7 | 765.4 | -0.3% |
| 100% downside / central / upside | 1,251.6 / 1,225.9 / 1,220.9 | 778.8 / 765.0 / 762.6 | +1.8% / -0.3% / -0.7% |
| Old rules without RSA 64 (transition impact) | IRACP 1,223.4, impact +6.5m | IRACP 812.5, impact 0 | - |

Reading: the provision is driven by the regulatory readings (restructuring, deferrals, LGD
source), not by the PD, scenario or overlay parameters. The floors absorb those parameters at
Stages 1 and 3.

## 11. Limitations and monitoring triggers

| Id | Limitation | Direction | Trigger |
|---|---|---|---|
| L1 | 60-89 dpd year-2 lifetime PD understated (0.55 / 0.60) | non-conservative, small (~30 defaults) | annual jump check < 0.8 with >= 100 year-2 defaults |
| L2 | TTC decile jump mis-fit (deciles 6, 9: 0.73-0.82) | mixed | decile with >= 100 year-2 defaults outside 0.8-1.25 twice |
| L3 | Carry fade tau = 3 by decision, not identified | - | OOT error at tau 3 > 25% above OOT optimum (now 7%) |
| L4 | 2012-16 vintages over-predicted (year-1 0.53-0.54) | conservative | prepay actual / predicted < 0.7 for latest two vintages |
| L5 | Carry not split into segment and cycle parts (refinement not built) | - | with L2 / L3 |
| L6 | CO-3 front-loads defaults (2005 hold-out 0.71 at 3 years) | conservative | re-test on any refit |
| L7 | CO-4 benchmark not mix-adjusted | - | CO-4 ratio > 1.25 after B-18 relabelling |
| L8 | Vasicek shift on delinquency prevalence (approximation) | - | default incidence remains the deciding rate |
| L9 | One backtest date (2023-03) | - | add each reporting date |
| L-LGD1 | Post-2017 LGD over-predicted (0.29-0.55) | conservative, immaterial after floors | Stage 1 model coverage > 0.20% or < 75% of Stage 3 floored |
| L-LGD2 | Resolution bias (unresolved / incomplete workouts excluded) | non-conservative for recent periods | resolved share of a period < 90% |
| L-LGD3 | First default only; cure costs not counted | non-conservative, small | - |
| L-LGD4 | Relief at default set to 0 in projection | conservative | - |
| L-LGD5 | Stage 3 LGD not scenario-weighted; CO-5 not on Stage 3 | immaterial (floors) | as L-LGD1 |
| L-LGD6 | Recoveries timed at zero balance; late MI claims not discounted further | small | - |
| L-LGD7 | Realisation haircut 47.7% includes distressed discounts | conservative for the secured portion | - |
| L-LGD8 | Development-period calibration 1.31 (level set on 2012-19) | - | at refit |
| L-ECL1 | Restructuring readings: RSA 124M timing not applied; calamity date proxy; (xiv) kept for life; 1-29 day misses invisible | mostly conservative | RSA amendment; data with day-level arrears |
| L-ECL2 | Loan level = borrower level (para 76) | - | multi-loan borrower data (Module 12) |
| L-ECL3 | Stage 2 anticipation 33% | - | < 30% with 12 months of outcomes |
| L-ECL4 | Stage 3 LGD not scenario-weighted | immaterial | as L-LGD1 |
| L-ECL5 | Quarter-after staging reuses the date's scenarios | diagnostic only | - |
| L-ECL7 | 2026-03 anticipation on 3 months | - | re-measure when data extend |
| L-ECL8 | Arrears cleared proxied by status 00 | slightly lenient | as L-ECL1 |
| R-1 to R-8 | Reporting: dry-run date, pre-tax add-back, n/a tables, DPD buckets, IRACP data proxies, write-off proxy, no 2022 run, transition sign depends on RSA 64 / 84A | see `models/reporting/CHANGELOG.md` | R-8 trigger in section 5 |
| G-4 | Outputs are regenerated module by module; a code fix can leave downstream committed outputs stale (M-7) | - | a full clean-tree rerun does not reproduce the committed outputs (regression check before every results commit) |

## 12. Overlays (para 131; Annex 4 Table 6)

| Id | Overlay | Status | Effect | Removal / review trigger |
|---|---|---|---|---|
| CO-1 | COVID mass forbearance - 60-89 dpd PD too high (OOT2 17% vs 51%) | candidate, not applied | would lower PD | relief share of 30-89 dpd > 15% in a quarter, or actual / predicted < 0.70 two quarters |
| CO-2 | ever_deferred PD too low (OOT1 12.1% vs 9.1%) | candidate, not applied | would raise PD | actual / predicted > 1.25 over four quarters with >= 100 defaults |
| CO-3 | Downside crisis multiplier on default odds, M = 3.06 sand states / 1.21 other | **applied** (accepted as calibrated, L6) | model ECL +6.3%; provision +0.3% (with CO-5) | regional factor or satellite that passes the replay without M; M interval includes 1 |
| CO-4 | 2024-26 vintages early defaults 1.64x (ex-relief ~1.15) | candidate, monitored | - | ratio > 1.25 after relief cures |
| CO-5 | Downturn LGD in the downside, ratio 1.507 x severity scale | **applied** | included above | refit with crisis ratio <= 1.10 |

The governance fields in `config/overlays.yaml` record `approvals: []`. The two-approver rule
for overlays is not yet enforced in code (only stage overrides go through the Module 9 log),
which is finding L-4.

## 13. Findings

| Id | Rating | Finding | Evidence | Action / owner decision needed |
|---|---|---|---|---|
| H-1 | **High** | The provision rests on the developer's reading of the RSA Directions: restructured accounts are 65% of the 2026 provision, and the readings move it by -23% to +29% (deferral mapping) or -66% to +11% (restructuring mapping) | Section 10; `models/ecl/CHANGELOG.md` | **Owner decision 2026-11-14: requires compliance review; no change.** Open until reviewed |
| H-2 | **High** | No independent validation; the developer, owner and validator are one person; OOT 2017-23 was used for PIT driver selection | This report | Independent validation (para 97 before the own LGD replaces the fallback; para 130) |
| M-1 | Medium | PD target B-18 vs RBI 90+ ECL default: 2023 backtest RBI 1.11 overall, **Stage 2 1.30**; B-18 0.88 / 1.08. Relief cures are credited in both the PD target and the LGD cure model's 2012-19 recalibration. **Quantified:** 869 of 15,054 window defaults are B-18 relabelled (no-cure 2%); excluding them moves the intercept shift from -0.469 to -0.439 and the projected no-cure by **+1.7%**, so Stage 1-2 model ECL rises about 1.7% (< 5% threshold; about +1.3m on 78.6m at 2026-03, smaller after floors) | Section 9; `reports/summary/validation_m1_relief_cures.json` (`ecl validate`) | **Owner decision 2026-11-14: keep and monitor.** The double count is below the 5% retrain threshold, so no retrain. Trigger: Stage 2 RBI actual / predicted > 1.25 on the next backtest |
| M-2 | Medium | The transition sign depends on the IRACP additional provisions (RSA 64 15%, 84A / 84B 5%): base rates alone give ECL 50.5m above IRACP | `models/reporting/CHANGELOG.md` (R-8) | Use actual RSA 64 / 84A balances at the real first application |
| M-3 | Medium | Stage 2 anticipates only 33% of next-year defaults (46% come from Stage 1 fast rolls, 2023-03) | L-ECL3 | Review the SICR thresholds or add behavioural triggers if < 30% |
| M-4 | Medium | Crisis vintages under-predicted by the lifetime PD (2007: 10.2% vs 14.1%), covered only in the downside by CO-3 | Section 9 | Regional factor in the hazard (CO-3 removal trigger) |
| M-5 | Medium | Floors set 87% of the provision (model ECL 154.7m vs 1,229.9m): model weaknesses (L-LGD1, M-4) are hidden while the floors bind | Sections 3, 10 | Monitor the floor triggers; report model ECL alongside |
| M-6 | Medium | Override control gaps: user IDs not authenticated; log retention depends on backups; tail deletion detected only against run records | Section 6 | **Owner decision 2026-11-14: recorded as a limitation of a local tool** (G-1); a bank deployment links user IDs to authenticated identities and write-once storage |
| M-7 | Medium | Committed outputs were stale: the 2026-03 scenario-PD and LGD summaries (`models/scenarios/scenario_pd_2026-03.json`, `models/lgd/apply_2026-03.json`, `reports/summary/scenario_pd_2026-03.csv`, `lgd_ead_2026-03.csv`) predated the fix for loans with status XX (3,358 loans scored as current), the 2025-03 scenario / LGD outputs were never committed, and the LightGBM challenger was not reproducible (multithreaded histograms). A full rerun also showed last-digit float noise (parallel DuckDB sums, BLAS threads). The provision was not affected (Modules 6-8 already used the fixed snapshot) | Full rerun from a clean tree 2026-11-15 vs committed outputs: weighted lifetime LGD 2026-03 7.0% -> 6.9% (option 1 8.9% -> 8.8%); 12m PD base 0.64% -> 0.63%; downside lifetime 6.56% / 7.23% -> 6.57% / 7.24%; challenger OOT2 Gini 0.717 -> 0.716; every headline unchanged | **Fixed:** deterministic fits (LightGBM deterministic, one BLAS thread in fit steps, ORDER BY on DuckDB reads, exact decimal rate average - released as patch version **pd12m-1.2.1**, `models/pd_12m/CHANGELOG.md`, inventory updated); all outputs regenerated from one clean-tree run. **Prevention:** a full clean-tree rerun must reproduce the committed outputs (output-by-output regression check) before any results commit (limitation G-4) |
| L-1 | Low | Upside GDP at the 76-77th percentile of forecast errors (combined index passes) | Section 9 | None (the combined severity index passes) |
| L-2 | Low | PIT over-predicts in COVID (0.77) and recovery (0.86); OOT3 1.15 | Section 9 | CO-1 trigger |
| L-3 | Low | LGD post-2017 over-predicted (conservative; ECL loss ratio 0.09) | Section 9 | L-LGD1 trigger |
| L-4 | Low | Overlay approvals (two approvers) recorded as empty; not enforced by the Module 9 log | Section 12 | **Owner decision 2026-11-14:** overlay changes are controlled by clean-tree git versioning recorded in each run (config commit + clean flag); full maker-checker for overlays is a future enhancement (G-2) |
| L-5 | Low | Tiering not independently reviewed (para 121) | Section 7 | Independent review |

US data throughout; not Indian risk estimates.
