# LGD and EAD - development log

US data (Freddie Mac, FHFA). Not Indian risk estimates. Methodology `docs/methodology/lgd_ead.md`;
parameters `config/lgd.yaml`; overlay CO-5 in `config/overlays.yaml`.

## lgd-0.1.0 (code `855423f`, 2026-11-14)

**Data.** 67,576 first RBI defaults (1999-2026): 42,948 cures, 21,213 liquidations (19,681 with
loss fields; 1,532 incomplete workouts excluded from severity), 1,885 excluded (96), 1,530
unresolved (censored; mostly 2025-26). Release 47 identity checked: actual loss = removal UPB +
delinquent accrued interest + expenses + recoveries (recoveries negative). Discounted severity
(note rate, default -> zero balance): mean 0.46 (undiscounted 0.39; Freddie loss / EAD 0.48).

**Models (development = defaults to 2016-12).** Cure logistic (121,917 rows, 38,791 defaults at
m = 0): no-cure rises with LTV and credit score, falls with a prior 30+ episode (-0.52) and relief
(-1.46); months in default +0.33 (3) to +1.00 (18). Severity fractional logit (18,356
liquidations): rises with LTV, falls with loan size, MI coverage, PUD / condo.

**Validation (actual / predicted LGD at default).**

| Group | Actual LGD | Predicted | Ratio |
|---|---|---|---|
| Development | 0.242 | 0.233 | 1.04 |
| 2000-06 defaults | 0.122 | 0.191 | 0.64 |
| **Crisis 2007-11** | 0.293 | 0.243 | **1.21** |
| 2012-16 | 0.193 | 0.232 | 0.83 |
| 2017-19 (OOT, resolved) | 0.058 | 0.138 | 0.42 |
| COVID 2020-21 (OOT) | 0.005 | 0.062 | 0.09 |
| 2022-26 (OOT) | 0.017 | 0.093 | 0.19 |

- Cure Gini 0.38 development, 0.58 OOT; severity Spearman 0.47 / 0.34.
- LTV bands: 0.73 (<= 60) to 1.06 (> 120); months in default calibrated in development (by
  construction), OOT no-cure 0.06 (m = 0) to 0.44 (m = 36) vs 0.26-0.47 predicted.
- **Crisis gap 1.21 > 1.10 -> CO-5 applied** (rule set by Yash): downside LGD x (1 + 0.207 s)
  in stressed default years; s = 0.46 (2026-03) / 0.52 (2023-03) -> factor 1.096 / 1.108.

**Realisation haircut** (para 6(24)): 1 - median(net sale proceeds / indexed value), 10,714 REO
sales = **47.7%** (by period 46-49%; 2022-26 35%). Includes distressed-sale discount and
property condition, not only selling costs.

**Results (performing loans; LGD = mean per loan; weighted = PD-weighted across scenarios).**

| As on | Loans | 12m LGD weighted | Lifetime LGD central / downside (no CO-5) / weighted | PD x EAD-weighted lifetime | Secured share | vs RBI fallback 65/70% |
|---|---|---|---|---|---|---|
| 2026-03-31 | 339,472 | 11.4% | 8.4% / 10.4% (9.7%) / 8.9% | 9.6% | 84% | 0.145 |
| 2023-03-31 | 272,908 | 11.4% | 8.0% / 10.0% (9.3%) / 8.4% | 9.4% | 87% | 0.143 |

Stage 3 (in default): 2026-03 2,235 loans, EAD-weighted LGD 12.8% (no-cure 0.45, severity 0.28),
rising with months in default; 2023-03 1,744 loans, 8.5%. LTV bands (2026-03, lifetime weighted):
6.2% (<= 60) to 14% (60-100) and 32-40% (> 100, few loans).

**Fallback comparison (para 97).** The modelled LGD is about 0.14-0.20 of the RBI fallback: US
loans at a median indexed LTV near 50%, with recoveries and MI, lose far less than 65%. Using the
fallback instead would raise ECL about 7x for the same PD and EAD. Module 8 floors will show
whether the floors, not the LGD, bind.

**Limitations (monitoring triggers).**
- **L-LGD1 out-of-time over-prediction (conservative, material).** Post-2017 defaults: LGD ratio
  0.42 (2017-19, fully resolved), 0.09 COVID, 0.19 2022-26; no-cure 17% actual vs 37% predicted
  in 2017-19. Post-crisis loss mitigation (modifications, deferrals) is not in the 2000-16
  development data; resolution bias adds to it for 2022-26. Trigger: owner decision on
  recalibration (summary of 2026-11-14); review annually.
- L-LGD2 resolution bias: incomplete workouts (7% of liquidations) and unresolved defaults
  excluded; cures resolve faster than liquidations, so recent periods look better than they are.
- L-LGD3 first default only; cure costs (modification, time value of the cure) not counted.
- L-LGD4 relief at default set to 0 in projection (conservative); prior 30+ episode lowers
  no-cure, so currently delinquent loans show a lower LGD than current ones (9.1% vs 11.4%, 12m).
- L-LGD5 Stage 3 LGD is not scenario-weighted (reporting-date LTV); CO-5 not applied to Stage 3.
- L-LGD6 recoveries and expenses timed at the zero-balance month; MI claims paid later are not
  discounted further.
- L-LGD7 realisation haircut 47.7% includes distressed-sale discounts; a pure sale-cost haircut
  would raise the secured portion.

## lgd-0.2.0 (code `fd27c5e`, 2026-11-14) - cure intercept recalibrated (owner decision, option 2)

**Decision (Yash).** Option 2, with the recalibration window **2012-2019** (not 2017-19 alone):
the structural change in US loss mitigation dates from about 2010-12; 2017-19 workouts resolved
during the COVID foreclosure moratoria and the 2020-22 house-price surge (temporary,
cure-inflating). CO-5 kept for the downside. Option 1 (development fit) kept as a sensitivity.
Materiality to be reassessed after the Module 8 floors.

**Recalibration.** Intercept shift -0.469 (slopes unchanged) so that the mean predicted no-cure
at default equals the actual 36.5% on 15,054 fully resolved 2012-19 defaults.

| Actual / predicted LGD | Option 1 | lgd-0.2.0 |
|---|---|---|
| Development (2000-16) | 1.04 | 1.31 |
| 2000-06 | 0.64 | 0.84 |
| 2012-16 | 0.83 | 1.05 |
| 2017-19 | 0.42 | 0.55 |
| Crisis 2007-11 | 1.21 | **1.51** |
| OOT 2017+ | 0.21 | 0.29 |

**CO-5 ratio recomputed against the model in use: 1.207 -> 1.507** (mechanism unchanged; the lower
predicted level widens the crisis gap). Downside factor in stressed years 1.23 (2026-03, s = 0.46)
/ 1.27 (2023-03, s = 0.52).

**LGD change (performing loans, mean per loan; option 1 in brackets).**

| As on | 12m weighted | Lifetime central | Lifetime downside (no CO-5) | Lifetime weighted | Change vs option 1 | Stage 3 (EAD-weighted) |
|---|---|---|---|---|---|---|
| 2026-03-31 | 9.1% (11.4%) | 6.3% | 8.6% (7.4%) | 6.9% (8.8%) | **-22%** | 10.3% (12.8%) |
| 2023-03-31 | 9.1% (11.4%) | 6.0% | 8.3% (7.1%) | 6.5% (8.4%) | **-22%** | 6.6% (8.5%) |

PD x EAD-weighted lifetime LGD 7.7% / 7.5%; model / RBI fallback 0.12 / 0.11. (2026-03 row regenerated
2026-11-15; see the note at the end.)

**Limitation L-LGD1 updated.** The remaining OOT over-prediction (0.55 on 2017-19, 0.29 on all
post-2017) is now conservative by design (crisis-inclusive slopes, 2012-19 level); reassess after
Module 8 (floors may bind regardless). L-LGD8: development-period calibration is now 1.31 (the
level is set for 2012-19, not for the crisis-heavy development sample).

### Materiality after Module 8 floors (ecl-0.1.0)
Option 1 vs lgd-0.2.0: model ECL +25% (2026-03) / +27% (2023-03) but final provision **+2.4% /
+1.5%** (primary RSA restructuring mapping, code `b86ac3a`; after the Stage 3 checks, code
`b998286`: +1.8% / +1.2%; +5.6% / +3.5% with modified loans at
least Stage 2):
the Stage 1 and Stage 3 floors bind, only Stage 2 passes model ECL through. L-LGD1 is not
material to the provision at present. Trigger: re-assess if Stage 1 model coverage > 0.20% or
< 75% of Stage 3 accounts are floored. Details `models/ecl/CHANGELOG.md`.

## Outputs regenerated 2026-11-15 (lgd-0.2.0, no model change)

Full pipeline rerun from a clean tree at `424af50` (deterministic fits: LightGBM
deterministic, one BLAS thread in fit steps, ORDER BY on DuckDB reads, exact decimal rate average).
Finding M-7 / limitation G-4 in `docs/validation_report.md`.

The committed 2026-03 application (`apply_2026-03.json`, `reports/summary/lgd_ead_2026-03.csv`)
predated the XX scoring fix (`0c42661`, 3,358 loans scored as current). Regenerated 2026-03
(performing loans): lifetime central 6.4% -> 6.3%, downside 8.7% -> 8.6% (no CO-5 7.5% -> 7.4%),
weighted 7.0% -> 6.9% (option 1 8.9% -> 8.8%), PD x EAD-weighted 7.6% -> 7.7%; 12m weighted 9.1%,
change vs option 1 -22%, Stage 3 10.3% and the fallback ratio 0.12 unchanged. The ECL runs
already used the fixed snapshot, so the provision is unchanged. 2023-03 unchanged (no XX loans);
2025-03 outputs committed for the first time. The lgd-0.1.0 table above is left as history.
