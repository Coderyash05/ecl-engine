# CHANGELOG - staging, ECL measurement, prudential floors (Modules 6-8)

US data (Freddie Mac sample, FHFA, FRED, SPF, SEP). **Not Indian risk estimates.** Design and RBI
text: `docs/methodology/staging.md`, `docs/methodology/measurement_floors.md`; parameters `config/ecl.yaml` (floor values from
`config/rbi_2026.yaml`). Amounts are in US dollars of the Freddie sample's UPB.

## ecl-0.1.0 - restructuring decisions (code `70e66da`, clean tree, 2026-11-14) - CURRENT RESULTS

Owner decisions 2026-11-14 (texts quoted in `docs/methodology/staging.md`):
1. **RSA 61 / 62 applied:** a miss after the implementation month blocks upgrades until a fresh
   restructuring (no clock restart). Freddie's modification flag is Y only in the month of a
   modification (earlier note "the flag persists" was wrong): later Y months are fresh
   restructurings and start a new monitoring period (2,602 loans have 2+ modifications). No
   stricter ECL rule on repeated restructuring in the ACPIR / RSA texts (RSA 6(10) defines
   "residual debt"); IRACP 84B (5% per repeated Chapter VI-A restructuring) is old-rules only.
2. **Deferrals split by cause:** calamity-linked (COVID window derived from the data: panel-wide
   deferral months > 2 x the 2023-25 monthly median = **2020-07 to 2022-04**; or the disaster flag
   within 12 months) and eligible (RSA 124J: current and not NPA before the hardship episode) ->
   calamity route, stays standard, category (xiv) floors 5% / 10% (ACPIR 82(4)(xiv); Stage 3
   table 25/40 ... 100, 82(5)); other / ineligible deferrals -> general restructuring (RSA 52 ->
   Stage 3; 124K). Floors added to `config/rbi_2026.yaml` (`advances_restructured_standard`,
   rbi_specified: true) with the owner's approval after quoting.

### Restructuring is the largest provision driver
| 2026-03 allowance by group | Loans | EAD (m) | Allowance (m) | Share |
|---|---|---|---|---|
| Restructured - modification | 3,594 | 813.8 | 549.5 | 44.7% |
| Restructured - general deferral | 2,083 | 477.5 | 204.8 | 16.6% |
| Calamity route (xiv) | 4,290 | 826.0 | 49.9 | 4.1% |
| Default / arrears not cleared | 2,355 | 604.8 | 193.8 | 15.8% |
| Other performing | 336,619 | 79,584.9 | 231.9 | 18.9% |
| **Total** | | 82,306.9 | **1,229.9** | |

Restructuring = **65% of the 2026 provision (804m) on 2.6% of exposure** (2023: 64%, 491m).

### Sequence of text-based fixes (each step adds one fix)
| Provision (m) | 2026-03 | 2023-03 |
|---|---|---|
| 0. Published (`b86ac3a`): duration = current default spell / restructured spell; default = 90+ month; clock restart | 740.9 | 486.5 |
| 1. Duration in Stage 3 = unbroken Stage 3 spell (82(5); RSA 53-54) | 904.7 (+163.8) | 579.7 (+93.2) |
| 2. + NPA until arrears cleared (8(10)) (`b998286`) | 914.0 (+9.3) | 586.5 (+6.8) |
| 3. + RSA 61 / 62, later modifications = fresh restructurings | 951.7 (+37.7) | 615.6 (+29.1) |
| 4. + deferrals split by cause = **new primary** | **1,229.9** (+278.2) | **767.2** (+151.6) |

Steps 0 and 2 reproduce the earlier published numbers exactly (`stage3_duration_steps` in the run
records). Total change 2026 +489.0m (+66%); 2023 +280.7m (+58%).

### Deferral routes (loans with a deferral, not in default)
| | 2026-03 loans / EAD (m) | 2023-03 loans / EAD (m) |
|---|---|---|
| Calamity route (xiv): Stage 1 / 2 / 3 | 3,957 / 238 / 6; 807.2 | 4,768 / 364 / 6; 1,062.4 |
| General restructuring (deferral, no modification): Stage 1 / 2 / 3 | 115 / 232 / 1,876; 493.4 | 45 / 68 / 1,320; 280.4 |
| Modified loans that also had a deferral | 829; 190.9 | 541; 105.2 |

| Provision (m) | 2026-03 | 2023-03 |
|---|---|---|
| Deferrals unmapped (sensitivity) | 951.7 | 615.6 |
| **Split by cause (primary)** | **1,229.9** | **767.2** |
| All deferrals general restructuring (sensitivity) | 1,590.7 | 1,030.1 |
| All restructured Stage 3 / at least Stage 2 | 1,360.5 / 419.3 | 848.8 / 317.6 |

Of 6,962 calamity-linked deferral events in the 2026 loan histories, 1,684 failed 124J (status
before the relief episode 30-59: 616, 60-89: 245, 90+: 817) -> general restructuring. A quarter
are single-month relief runs: the calamity may have started earlier with a gap in relief, so
the test can misroute eligible loans to the stricter general route (conservative; limitation).

### Restructured loans (general route, not in default), 2026-03
| Reason | Loans |
|---|---|
| Stage 3: missed payment after implementation (RSA 61 / 62) | 2,885 (563 with a fresh restructuring) |
| Stage 3: < 12 months and < 10% repaid | 1,153 |
| Stage 3: 12 months met, < 10% repaid | 1,279 |
| Stage 3: < 12 months, repayment met | 7 |
| Stage 2: 10-20% repaid | 434 |
| Graduated (>= 20%, no miss): Stage 1 / 2 | 399 / 66 |

### Results (primary, code `70e66da`)
| | 2026-03 | 2023-03 | 2025-03 (opening for Table 3) |
|---|---|---|---|
| Loans S1 / S2 / S3 | 333,110 / 8,138 / 7,693 | 269,381 / 4,798 / 6,128 | |
| Stage 3 = default / arrears / restructured | 2,235 / 215 / 5,243 | 1,744 / 132 / 4,252 | |
| Model ECL (m) | 154.7 | 75.8 | 136.4 |
| Provision S1 / S2 / S3 (m) | 232.4 / 42.3 / 955.3 | 184.7 / 25.1 / 557.3 | |
| of which (xiv) floors S1 / S2 (m) | 38.0 / 4.6 | 49.5 / 7.2 | |
| **Provision (coverage)** | **1,229.9 (1.49%)** | **767.2 (1.34%)** | 1,125.9 (1.46%) |
| SICR 2.0 / 3.0 | 1,243.6 / 1,226.3 | 773.5 / 763.7 | |
| LGD option 1 / RBI fallback 65/70% | 1,244.7 / 1,765.0 | 773.3 / 1,042.8 | |
| Without CO-3 / CO-5: model ECL / provision | 145.6 / 1,226.7 | 69.9 / 765.4 | |
| Stage 2 anticipation (next-12m defaults that were Stage 2) | 3 months observed | 33% | |

- CO-3 / CO-5 add 9.1m (2026) / 5.9m (2023) to model ECL but 3.2m / 1.8m to the provision.
- Stage 2 floor: housing (xi)(a) does not bind at SICR 2.5; (xiv) binds (10%).

### Limitation changes
- L-ECL1 updated: RSA 124M timing (45 / 135 days) not applied; calamity occurrence date proxied
  by the start of the contiguous relief run (conservative); category (xiv) kept for the loan's
  life (no exit rule in the text; conservative); 1-29 day misses not observable (lenient).
- L-ECL3: 2023 anticipation 33% (was 36%): more defaults now come from restructured Stage 3.

## ecl-0.1.0 - Stage 3 checks (code `b998286`, clean tree, 2026-11-14) - superseded by the restructuring decisions above

Two checks with effect on the provision (owner request 2026-11-14). Both dates re-run.

### Check (a): when does the "Duration in Stage 3" start? (para 82(5); NPA upgrade para 8(10))
Findings in the published run (`b86ac3a`):
1. **Loans in default:** duration = the current run of 90+ months. A loan that partly caught up
   (90+ -> 30-89 dpd) left default and Stage 3, and its clock restarted on re-entry. Para 8(10):
   an NPA "may be upgraded as 'standard' asset only if the entire arrears of interest and
   principal are repaid" -> the NPA (and Stage 3) persists until the loan is back to current.
   **Correctness bug, non-conservative -> fixed** (new rule `default_arrears`).
2. **Restructured loans:** duration counted from the modification. 2,810 (2026) / 2,446 (2023)
   modified loans had defaulted before the modification; when there is no cure in between they
   have been Stage 3 since the default. **Non-conservative -> fixed:** duration = the unbroken
   run of Stage 3 months (NPA incl. arrears not cleared, or restructured Stage 3) ending at the
   date; a cure (back to current, not restructured) ends the run.

| Provision (m) | 2026-03 | 2023-03 |
|---|---|---|
| 0. Published (`b86ac3a`) | 740.9 | 486.5 |
| 1. Duration = unbroken Stage 3 spell | 904.7 (+163.8) | 579.7 (+93.2) |
| 2. + NPA until arrears cleared, para 8(10) = **new primary** | **914.0** (+9.3) | **586.5** (+6.8) |

| Stage 3 duration bands (accounts) | 0-1y | 1-2y | 2-3y | 3-4y | > 4y |
|---|---|---|---|---|---|
| 2026 published | 2,606 | 697 | 342 | 532 | 1,212 |
| 2026 primary | 1,919 | 975 | 501 | 282 | 1,869 |
| 2023 published | 1,926 | 902 | 434 | 298 | 951 |
| 2023 primary | 1,093 | 469 | 1,409 | 416 | 1,218 |

2026 decomposition of the floor change (step 0 -> 2): restructured Stage 3 loans 378.8m ->
499.5m (2,511 of 3,096 have a longer duration; median 3.3 -> 4.6 years); loans in default
110.6m -> 156.7m (521 of 2,235 longer: earlier restructured Stage 3 time or 30-89 dpd months no
longer break the run); arrears not cleared (new Stage 3) 215 loans (2023: 132), floor 14.1m.

### Check (b): payment deferrals
Freddie payment deferral (status C): missed instalments moved to a non-interest-bearing balance
due at payoff, granted to borrowers with a COVID or disaster hardship. That reads as a
"rescheduling of repayment ... due to the borrower's financial difficulty" (ACPIR 6(3)(iii)),
i.e. a concession. Primary still maps the modification flag only (owner instruction); the
sensitivity `text_deferral` starts the same RSA clock at the first deferral month.

| | 2026-03 | 2023-03 |
|---|---|---|
| Deferral-only loans not in default (EAD) | 6,424 (1.30bn) | 6,571 (1.34bn) |
| Their stage now: S1 / S2 / S3 | 5,452 / 943 / 29 | 5,919 / 625 / 27 |
| If restructured: Stage 3 / Stage 2 / graduated | 3,310 / 1,999 / 1,115 | 5,581 / 615 / 375 |
| **Provision primary -> deferrals as restructuring** | **914.0 -> 1,487.1m (+63%)** | **586.5 -> 996.8m (+70%)** |

The deferred balance is part of the base but is not repaid until payoff, so the 10% / 20% tests
are slow to pass; deferrals from 2020-21 are > 4 years old by 2026 (100% floor band). **Owner
decision needed:** map deferrals as restructuring (para 6(3)(iii)) or keep modification-only
and record why a deferral is not a concession.

### Results (primary, code `b998286`)

| | 2026-03 | 2023-03 |
|---|---|---|
| Loans S1 / S2 / S3 | 334,629 / 8,766 / 5,546 | 270,592 / 5,110 / 4,605 |
| Stage 3 = default / arrears not cleared / restructured | 2,235 / 215 / 3,096 | 1,744 / 132 / 2,729 |
| Model ECL S1 / S2 / S3 (m) | 40.6 / 42.9 / 70.2 | 27.1 / 20.0 / 27.8 |
| Provision S1 / S2 / S3 (m) | 197.1 / 42.9 / 674.0 | 138.3 / 20.0 / 428.1 |
| Stage 3 floor binds | 5,227 of 5,546 | 4,475 of 4,605 |
| **Total model ECL -> provision (m)** | **153.7 -> 914.0** (0.19% -> 1.11%) | **75.0 -> 586.5** (0.13% -> 1.02%) |
| (b) all modified Stage 3 / (c) at least Stage 2 | 1,023.4 / 375.5 | 691.6 / 256.7 |
| SICR 2.0 / 3.0 | 925.3 / 910.2 | 590.8 / 584.0 |
| LGD option 1 | 930.6 (+1.8%) | 593.4 (+1.2%) |
| RBI fallback LGD 65/70% | 1,503.1 | 892.5 |
| Stage 2 model coverage at SICR 2.0 / 2.5 / 3.0 (floor 1.50%) | **1.35%** / 2.04% / 2.44% | **1.49%** / 1.97% / 2.33% |
| Stage 2 anticipation (next-12m defaults that were Stage 2) | 66% (3 months observed) | 36% |

Floors now raise model ECL 5.9x (2026) / 7.8x (2023); Stage 3 is 74% / 73% of the provision.
The Stage 2 floor still binds only at SICR 2.0 (and under (c) at 2.5 in 2023: 1.494%).

### RSA Directions text check (file added 2026-11-14; quotes in docs/methodology/staging.md)
The owner's reading agrees with paras 6(4), 6(8), 6(14), 6(16), 52 and 58 (one clock, 10% / 20%
of principal incl. interest capitalisation, 12 months from the first payment, any default);
paras 59 / 60 do not apply. Paras 53-54 (an NPA restructured keeps its classification and NPA
ageing) support check (a). Two findings for the owner:
1. **Para 61:** a miss during the monitoring period does **not** restart the clock - upgrade
   then needs a fresh restructuring or change in ownership (not identifiable in Freddie data, so
   such loans would stay Stage 3); para 62: a default after upgrade, before the end of the
   specified period, needs a fresh resolution plan. 354 (2026) / 270 (2023) modified loans
   upgraded after a restart; Stage 3 floors for them ~ **+44m / +34m**. Not changed (owner's
   explicit rule); decision needed.
2. **Deferrals:** 6(12) defines restructuring as concessions for financial difficulty, incl.
   "alteration of payment period / payable amount" - a payment deferral fits. Two readings:
   general restructuring (Stage 3 via 52: provision 1,487.1m / 996.8m) or the calamity route
   (Chapter VI-A; COVID was an SDRF-notified disaster in India): stays standard with the ACPIR
   82(4)(xiv) floors 5% Stage 1 / 10% Stage 2 (~ +76m / +73m on the deferral-only loans; the
   values are not in `config/rbi_2026.yaml` and would need adding).

### Limitation changes
- L-ECL6 (Stage 3 years = current default spell) **closed** by check (a).
- New L-ECL8: "entire arrears repaid" is proxied by status 00 (0-29 days late counts as cleared;
  slightly lenient). Model ECL of a Stage 3 loan not 90+ at the date (arrears not cleared,
  restructured) is its lifetime ECL from the performing PD model, not LGD in default; immaterial
  while the account floor binds (94% / 97% of Stage 3 accounts). Months missing from the panel
  do not break a Stage 3 run.
- L-ECL1 (iii) deferrals: now quantified above; decision pending.

## ecl-0.1.0 - RSA restructuring mapping, results superseded by the Stage 3 checks above (code `b86ac3a`; 2023-03 run on `6606aed`, which only adds the `--date` CLI option; clean tree, 2026-11-14)

Inputs: PD lifetime pdlife-0.4.0, scenarios scen-0.2.0 (CO-3), LGD lgd-0.2.0 (CO-5; option 1 =
lgd-0.1.0 cure model as sensitivity). Run: `ecl run [--date YYYY-MM-DD]`
(~25 min for both dates and the quarter after each). Records `models/ecl/ecl_{2026-03,2023-03}.json`;
tables `reports/summary/ecl_{by_stage,drivers,sensitivity_grid,stage_transition}_*.csv`.

History within ecl-0.1.0 (development, not accepted): first results `b7e6241` (code `9278c4f`)
used a strict reading with no specified period (every modified loan Stage 3) and an unverified
2019 illustration; superseded by the owner's RSA Directions mapping below. The strict result is
kept as sensitivity (b); the illustration is removed.

### Fixes made before the results
- **Status XX (not yet reported) loans had no PD** (3,358 performing loans on 2026-03, almost all
  2026 originations): the scorecard has no delinquency state for XX. Now scored as current and
  flagged `dpd_status_unknown` (`pd.dataset.build_scoring_snapshot`); the ECL run fails on any
  missing PD. Module 4's 2026-03 averages had skipped these loans (pandas mean ignores NaN,
  ~1% of loans, all new and low-risk): recorded in `models/scenarios/CHANGELOG.md`; not re-run.
  2023-03 had none.
- Transition matrix in the JSON is now rows = stage at the date (`transition_from_to`).

### Restructuring mapping (owner reading of the RSA Directions 2025, 2026-11-14)
ACPIR paras 6(3)(iii), 77-81 quoted in docs/methodology/staging.md. **RSA Directions 2025 paras 6(4), 6(8),
6(14), 6(16), 52, 58-60: quotes pending** - the file
`docs/reference/RBI-Stressed-Assets-Directions-2025.pdf` is not in the repository at this run.
The mapping implements the owner's reading:
- one clock from the modification month (monitoring period 10% and specified period 20% both
  start at implementation of the resolution plan; no second period);
- Stage 3 -> 2: >= 10% of the post-modification debt repaid (base = Current Actual UPB at
  modification = interest-bearing + non-interest-bearing UPB, checked on the raw 2010 file) and
  >= 12 months since the first post-modification payment (para 58 proviso), no missed payment;
- Stage 2 -> 1: >= 20% repaid, no missed payment, no SICR (ordinary staging after graduation);
- missed payment = status 01+ or RBI default -> Stage 3, clock and base restart;
- paras 59 (MSME) and 60 (>= Rs 100 crore, rating) do not apply to individual housing loans.

| Provision (m) | **(a) RSA mapping, primary** | (b) all modified Stage 3 | (c) modified at least Stage 2 |
|---|---|---|---|
| 2026-03 | **740.9** | 848.1 | 364.9 |
| 2023-03 | **486.5** | 589.6 | 249.0 |

Modified loans not in default at the date (2026-03 / 2023-03): 4,000 / 3,517 loans, EAD 865m /
678m; median 48 / 41 months since modification; 88% / 91% current now; 55% / 52% missed a
payment (30+) at some point since modification.

| Restructuring state and reason | 2026-03 | 2023-03 |
|---|---|---|
| Graduated (>= 20% repaid, no miss on the clock) -> ordinary staging: Stage 1 / Stage 2 | 423 / 90 | 396 / 42 |
| Stage 2 (>= 10%, < 20% repaid) | 333 | 312 |
| Stage 3: time met, < 10% repaid | 1,446 (637 after a restart) | 1,152 (539) |
| Stage 3: < 12 months after first payment and < 10% repaid | 1,702 (1,148 after a restart) | 1,611 (939) |
| Stage 3: < 12 months, repayment met | 6 | 4 |
| **Stage 3 total** | **3,154** | **2,767** |

% of the UPB at modification repaid by the date (all modified loans not in default):

| Repaid | <= 0% | 0-5% | 5-10% | 10-15% | 15-20% | 20-30% | 30-50% | > 50% | median |
|---|---|---|---|---|---|---|---|---|---|
| 2026-03 | 390 | 1,683 | 795 | 242 | 248 | 213 | 260 | 169 | 4.6% |
| 2023-03 | 280 | 1,779 | 399 | 316 | 171 | 240 | 264 | 68 | 2.7% |

- Repayment, not time, keeps loans in Stage 3: a modified 30-40-year schedule repays ~1-2% of
  principal a year early on, so 10% takes years. <= 0% = UPB higher than at modification (later
  capitalisation; later modifications are not identifiable).
- Restructured Stage 3 provision ~385m (2026) / ~242m (2023), 44% / 36% of their EAD: years in
  Stage 3 run from the modification (or re-entry), so long-standing modifications reach the 3-4y
  (40%) and > 4y (100%) floor bands.

### Results (primary: RSA mapping, SICR 2.5 + 0.5 pp, champion LGD)

| | 2026-03 | 2023-03 |
|---|---|---|
| Loans S1 / S2 / S3 | 334,629 / 8,923 / 5,389 | 270,592 / 5,204 / 4,511 |
| Stage 3 = default / restructured | 2,235 / 3,154 | 1,744 / 2,767 |
| Stage 2 rule: backstop / sicr_pd / restructured / LTV | 3,726 / 4,859 / 333 / 5 | 2,256 / 2,619 / 312 / 17 |
| Model ECL S1 / S2 / S3 (m) | 40.6 / 44.2 / 68.8 | 27.1 / 20.5 / 27.4 |
| Model coverage S1 / S2 / S3 | 0.05 / 2.07 / 5.1% | 0.05 / 1.98 / 2.9% |
| Provision S1 / S2 / S3 (m) | 197.1 / 44.2 / 499.6 | 138.3 / 20.5 / 327.7 |
| Floor binds | S1 yes; S2 no; S3 5,027 of 5,389 accounts | S1 yes; S2 no; S3 4,360 of 4,511 |
| **Total model ECL -> provision (m)** | **153.7 -> 740.9** (0.19% -> 0.90%) | **75.0 -> 486.5** (0.13% -> 0.85%) |
| RBI fallback LGD 65/70%: model -> provision (m) | 1,069.8 -> 1,375.3 | 622.2 -> 817.7 |

- Origination comparator available for every performing loan (0 missing).
- Transition to the quarter after (rows = stage at the date): S1 stays 96.6% / 97.3%; S2 -> S1
  26.7% / 35.7%, -> S3 6.6% / 5.5%; S3 stays 91.9% / 89.9%.
- Stage 2 anticipation (share of next-12m RBI defaults that were Stage 2 at the date): **2023-03
  38%** (backstop 80%, sicr_pd 20%); Stage 2 or 3: 52%; 48% came from Stage 1. 12-month default
  rate Stage 1 0.39%, Stage 2 16.1%, restructured Stage 3 10.3%. 2026-03: 72% with only 3 months
  of outcomes (not comparable).

### Floors drive the provision
- Model ECL -> provision: **2026-03 153.7m -> 740.9m (4.8x); 2023-03 75.0m -> 486.5m (6.5x)**;
  with modified loans at least Stage 2 (c): 2023 75.1m -> 249.0m (3.3x), 2026 153.8m -> 364.9m.
- Stage 1: the 0.25% floor binds on both dates (model 0.05%): 156m / 111m of uplift.
- Stage 3: account floors bind on 93% / 97% of accounts (model coverage 5.1% / 2.9% vs provision
  37% / 35%): the floor bands, not the LGD, set the Stage 3 provision.
- Stage 2: the floor does not bind in the primary run (margin below).

### Stage 2 floor margin (grid `ecl_sensitivity_grid_*.csv`)
The 1.51% seen earlier was under (c), where low-coverage modified loans sat in Stage 2.

| Stage 2 model coverage (floor 1.50%) | SICR 2.0 | 2.5 | 3.0 |
|---|---|---|---|
| 2026, (a), champion LGD | **1.37% (binds)** | 2.07% | 2.47% |
| 2026, (a), option-1 LGD | 1.77% | 2.68% | 3.20% |
| 2023, (a), champion LGD | **1.499% (binds)** | 1.98% | 2.35% |
| 2023, (a), option-1 LGD | 1.95% | 2.58% | 3.04% |
| 2026, (c), champion LGD | **1.34% (binds)** | 1.81% | 2.02% |
| 2023, (c), champion LGD | **1.30% (binds)** | 1.51% | 1.60% |

The Stage 2 floor binds only at SICR ratio 2.0 with the champion LGD, never with option-1 LGD.
Total provision across SICR 2.0 / 2.5 / 3.0 (primary): 2026 751.4 / 740.9 / 737.1m; 2023 490.6 /
486.5 / 484.0m (<= 1.4%).

### Materiality of the LGD recalibration (L-LGD1, lgd-0.2.0 vs option 1)
| | Model ECL champion -> option 1 | Provision champion -> option 1 |
|---|---|---|
| 2026-03, primary (a) | 153.7 -> 192.5m (+25%) | 740.9 -> 758.5m (**+2.4%**) |
| 2023-03, primary (a) | 75.0 -> 95.3m (+27%) | 486.5 -> 493.7m (**+1.5%**) |
| 2026-03, (c) | 153.8 -> 192.6m | 364.9 -> 385.4m (+5.6%) |
| 2023-03, (c) | 75.1 -> 95.4m | 249.0 -> 257.8m (+3.5%) |

The recalibration moves model ECL by a quarter but the final provision by 1.5-2.4% (primary)
because the Stage 1 and Stage 3 floors bind; only Stage 2 passes model ECL through.
**L-LGD1 is not material to the provision** at present; it is material to the model ECL and
would matter if the floors stopped binding. Trigger: re-assess if Stage 1 model coverage
exceeds 0.20% or fewer than 75% of Stage 3 accounts are floored.

### Limitations (monitoring triggers)
- **L-ECL1 Restructuring mapping:** (i) RSA text checked (Stage 3 checks section): clock
  restart after a miss is less conservative than para 61 (decision pending); (ii) status 00
  covers 0-29 days late, so 1-29 day misses are not detected (slightly lenient vs "any default");
  (iii) **COVID / disaster payment deferrals are not mapped as restructuring** (modification flag
  only): 12,324 loans had a deferral and no modification flag (6,825 observed at 2026-03); if a
  deferral is a concession for financial difficulty (ACPIR 6(3)(iii)) they would be restructured;
  (iv) only the first modification is identifiable (a later one does not restart the clock;
  its capitalisation lowers the repaid share, so the loan stays Stage 3 - conservative);
  (v) first post-modification payment = the month after the modification month.
  Trigger: RSA file added; any re-modification flag in a later Freddie release.
- **L-ECL2 Para 76 approximation:** loan level = borrower level (one loan per borrower in the
  data). Trigger: any multi-loan borrower data (synthetic Indian portfolio, Module 12).
- **L-ECL3 Stage 2 anticipation 38% (2023; 52% Stage 2 or 3):** 48% of defaults come from Stage 1
  (fast roll from current). Not a staging bug (backstop and SICR test as configured); thresholds are owner
  choices. Trigger: anticipation < 30% on a later date with >= 12 months of outcomes, or the
  Stage 2 / Stage 1 default-rate ratio < 20 (2023: 41).
- **L-ECL4 Stage 3 LGD is not scenario-weighted** (LGD in default by months in default, current
  collateral). Immaterial while the floors bind on > 90% of accounts. Trigger: as L-LGD1.
- **L-ECL5 Quarter-after staging reuses the reporting date's scenario paths** (no look-ahead;
  stale macro); transition shares are diagnostic only.
- ~~L-ECL6 Stage 3 years for loans in default = current default spell~~ - closed by the Stage 3
  checks (code `b998286`): duration = unbroken Stage 3 spell, NPA until arrears cleared.
- **L-ECL7 2026-03 anticipation has 3 months of outcomes** - re-measure when data extend.
