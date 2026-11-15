# ECL measurement and prudential floors (ecl-0.1.0)

Discounted, probability-weighted ECL per loan and the prudential floors that set the final provision.
Code: `src/ecl/provisioning/{ecl,floors,run}.py` (`ecl run [--date]`). Parameters: `config/ecl.yaml`;
floor values: `config/rbi_2026.yaml`. Development log: `models/ecl/CHANGELOG.md`. US data, US dollars;
not Indian risk estimates.

## Measurement (paras 44-51)

Per loan and scenario, then probability-weighted (20 / 60 / 20, para 47):

| Stage | ECL |
|---|---|
| 1 | 12-month PD x LGD(year 1) x EAD(year 1) x DF(year 1) |
| 2 | sum over years to maturity of marginal PD x LGD x EAD x DF |
| 3 | LGD in default (at the months in the current default spell) x EAD now |

- **PD:** scenario 12-month PIT PD and lifetime term structure ([lifetime PD](pd_lifetime.md)), CO-3
  in the downside.
- **LGD / EAD:** [LGD and EAD](lgd_ead.md), CO-5 in the downside.
- **Discounting (paras 50-51, 44):** at the origination note rate as the EIR proxy (the contractual
  rate is allowed until 31 March 2030), with defaults at mid-year. A late but full payment is still a
  loss through discounting.
- **Weighting on ECL, not on inputs:** ECL is non-linear in the macro path, so weighting PDs or macro
  inputs would understate it.

## Prudential floors (paras 82, 90-92)

Floors apply per loan product category; categories are kept strictly separate (paras 82(4), 91-92).

| Category | Stage 1 | Stage 2 | Stage 3 (secured / unsecured portion) by duration in Stage 3 |
|---|---|---|---|
| Housing loans to individuals, item (xi)(a) | 0.25% | 1.50% | 0-1 y 10 / 25%; 1-2 y 20 / 100%; 2-3 y 30 / 100%; 3-4 y 40 / 100%; > 4 y 100% |
| Calamity-restructured standard advances, item (xiv) | 5% | 10% | 0-1 y 25 / 40%; 1-2 y 40 / 100%; 2-3 y 55 / 100%; 3-4 y 75 / 100%; > 4 y 100% |

- **Application (para 90):** Stages 1-2 at portfolio level per stage and category:
  max(model ECL, floor rate x stage exposure). Stage 3 per account: max(ECL, secured rate x secured
  portion + unsecured rate x unsecured portion).
- **Exposure:** EAD now (outstanding + accrued interest); secured portion from the HPI-indexed
  property value after the realisation haircut (para 6(24)).
- **Duration in Stage 3 (82(5)):** the unbroken run of Stage 3 months ending at the date: NPA months
  (from a 90+ month until arrears are cleared, para 8(10)) and restructured Stage 3 months together,
  so a loan modified while in default has been in Stage 3 since the default; a cure ends the run.
  Band edges are read as [from, to): exactly one year falls in the 1-2 year band (conservative; an
  interpretation marked `rbi_specified: false`).
- **PD floor (para 96):** 0.03% on the 12-month PD; see [point-in-time PD](pd_point_in_time.md).

## Results (2026-03-31)

| | Loans | Exposure | Model ECL | Provision | Coverage |
|---|---|---|---|---|---|
| Stage 1 | 333,110 | 78.5bn | 40.3m | 232.4m (floor binds) | 0.30% |
| Stage 2 | 8,138 | 2.0bn | 38.3m | 42.3m | 2.17% |
| Stage 3 | 7,693 | 1.8bn | 76.1m | 955.3m (floor binds on 7,395 accounts) | 52.0% |
| Total | 348,941 | 82.3bn | 154.7m | **1,229.9m** | **1.49%** |

The floors set most of the provision: model ECL is 13% of it. Restructured accounts are 65% of the
provision. 2023-03-31: provision 767.2m (1.34%). Output tables: `reports/summary/ecl_by_stage_*`,
`ecl_drivers_*`, `ecl_sensitivity_grid_*`, `ecl_stage_transition_*`.

## Diagnostics and sensitivities

Stage mix and the rules that fired; transition matrix to the quarter after each date (same scenario
paths, no look-ahead); share of next-12-month defaults that were in Stage 2 at the date; a grid of
restructuring readings x SICR thresholds 2.0 / 2.5 / 3.0 x LGD (champion, development fit); RBI
fallback LGD 65 / 70%; ECL at 100% of each scenario. The provision is driven by the regulatory
readings (restructuring, deferrals, LGD source), not by the PD, scenario or overlay parameters:
see the [validation report](../validation_report.md), section 10.

## Limitations

L-ECL4 (Stage 3 LGD not scenario-weighted), L-ECL5 (quarter-after staging reuses the date's
scenarios), L-ECL7 (2026-03 anticipation on 3 months of outcomes). Register:
[docs/limitations.md](../limitations.md).
