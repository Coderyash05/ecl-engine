# Macro scenarios and scenario-weighted PDs (scen-0.2.0)

Three probability-weighted macro scenarios per reporting date, the crisis replay behind the downside
overlay CO-3, and the scenario-weighted 12-month and lifetime PDs. Code: `src/ecl/scenarios/`
(`ecl scenarios`, `ecl crisis-replay`, `ecl scenario-pd`). Parameters: `config/scenarios.yaml`,
`config/overlays.yaml`. Development log: `models/scenarios/CHANGELOG.md`. US data (FRED, FHFA, SPF,
SEP); US scenarios, not Indian ones.

## RBI basis

- **Para 47:** ECL "shall reflect an unbiased and probability-weighted amount, determined by
  evaluating a range of possible outcomes" - neither a worst case nor a best case.
- **Para 48:** multiple scenarios, each linking the ECL components to macro variables.
- **Para 49:** weights from historical experience and expert judgement, under governance.
- **Para 124:** probabilities from careful analysis with a justified review frequency; variables
  "tailored to portfolio, segmentation, or geography"; forecasts extrapolated beyond standard
  horizons with documented mean-reversion timing.
- **Para 131:** post-model adjustments (PMAs) documented with justification, calculation and
  validation triggers.
- **Annex 4 Table 5:** central, upside and downside assumptions, "1 year forward" and "5-year
  average" per indicator.

The Directions set no number of scenarios beyond Table 5's three, no weights, severity or reversion
speed: every number here is a documented choice in `config/scenarios.yaml`, not an RBI value.

## Method

**Reporting dates.** 2026-03-31 (primary: the last Indian financial-year end before the 2027-04-01
effective date, run in parallel) and 2023-03-31 (backtest, with forecasts published by 2023Q1: no
look-ahead). Current-vintage FRED / FHFA history is used (revisions documented).

**Variables.** National HPI growth and real GDP growth drive the credit-cycle index Z (the
[PIT satellite](pd_point_in_time.md)); the 30-year mortgage rate drives prepayment; state house-price
indices move each loan's current LTV; unemployment is reported only.

**Base.** Philadelphia Fed SPF median forecasts for GDP, unemployment and the 10-year Treasury (annual
averages held exactly); mortgage rate = Treasury + spread converging to the 2000-2016 mean; HPI
conditional on those paths from the VAR. The Fed SEP is a cross-check (medians confirmed against the
PDF text).

**VAR and scenarios.** A VAR(2) on HPI growth, GDP growth and the changes in the mortgage rate and
unemployment (OLS per equation, 1976Q1-2019Q4, ending before COVID) simulates 10,000 paths around
the base (block bootstrap of the residuals, 4-quarter blocks). Paths
are ranked by a severity index (mean satellite Z over 12 quarters) and cut into regions 20 / 60 / 20;
each scenario is the conditional mean of its region, and its weight is the region's probability, so
the weighted outcome is unbiased by construction (para 47).

**Severity check.** The downside and upside must sit inside the 5th-20th and 80th-95th percentiles of
historical 4-quarter forecast errors on the combined severity index (the index the regions are cut
on): 14-15th and 86-87th percentile on both dates. Single-variable percentiles are reported for
information (upside GDP alone sits at the 76-77th: the ranking is joint and GDP errors are skewed to
recessions).

**State paths.** Each state's quarterly log HPI growth = beta x national growth (betas fitted
2000-2016, intercepts dropped so the national path is the single scenario input). Sand states have
betas of 2.1-2.5; the multipliers amplify booms as well as busts, accepted because capping only the
upswing would bias the weighted outcome.

**Horizon and reversion (para 124).** 12-quarter explicit forecast, linear reversion over 8 quarters
to the long run, then flat. Long run: HPI 3.27% and GDP 2.06% (2000-2016 means, long-run Z -0.207);
mortgage rate = SEP longer-run federal funds rate + 2.92 pp (6.02% in 2026), a deliberate exception
because the 2000-2016 rate mean (zero-lower-bound era) would create a spurious refinancing incentive.

**Weighting.** PDs and ECL are computed per scenario and weighted on ECL (Module 7), not on macro
inputs: ECL is convex in the macro path, so weighted ECL exceeds base ECL (Jensen's inequality), which
is the point of para 47, not a bias.

## Crisis replay and overlay CO-3 (para 131)

The 2005-07 holdout vintages are replayed through 2007-09 in three steps: R1 measured Z, R2 satellite
Z on the realised macro, R3 adding beta-derived state house prices. The model alone under-predicts
the 2006-07 vintages, so CO-3 is a **downside-only multiplier on the default odds** in quarters with
Z below its long-run value, scaled by the downside's severity relative to the crisis and capped at the
crisis value. Calibrated on 2006-07 at 5 years (tolerance 0.9-1.1), with 2005 held out (0.8-1.25):
**M = 3.06 in the sand states (CA, FL, NV, AZ), 1.21 elsewhere**. 2006-07 land at 0.90-1.09; the 2005
holdout gives 0.82 at 5 years and 0.71 at 3 years (fails on timing in the conservative direction:
limitation L6). Accepted as calibrated (model owner, 2026-11-14). CO-5 (downturn LGD in the downside)
is described in [LGD and EAD](lgd_ead.md).

## Scenario-weighted PDs

Per loan and scenario: 12-month PIT PD, lifetime PD term structure (with CO-3 in the downside) and the
long-run-macro comparator for SICR. 2026-03-31 weighted: 12-month 0.66%, lifetime 5.64%. Backtest
2023-03-31: actual / weighted 12-month default 0.84 (1.01 at the realised Z): the gap is the macro
outcome, which ranked at the 90th percentile of the simulated paths, above the upside.

**Early-performance check (candidate CO-4).** The 2024-26 vintages are compared with the PIT-adjusted
age profile of benchmark vintages: actual / expected 1.64 (about 1.15 excluding relief cures); CO-4
stays a monitored candidate, not applied.

## Limitations

L6 (CO-3 front-loads defaults), L7 (CO-4 benchmark not mix-adjusted), L8 (Vasicek shift on
delinquency prevalence is an approximation), L9 (one backtest date). Register:
[docs/limitations.md](../limitations.md).
