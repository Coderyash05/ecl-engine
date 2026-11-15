# Macro scenarios - development log

US data (FRED, FHFA, SPF, SEP). Not Indian risk estimates. Methodology: `docs/methodology/scenarios.md`;
parameters: `config/scenarios.yaml`; outputs: `reports/summary/scenarios_*`.

## scen-0.1.0 (code `10c3bfd`, 2026-11-14) - scenarios and Table 5

**Sources as at the date (no look-ahead).** SPF 2026Q1 / 2023Q1 (released February); SEP
18 Mar 2026 / 22 Mar 2023, medians confirmed against the PDF text; GS10 and macro history cut at
the reporting quarter. Exception (V6): current-vintage FRED/FHFA history, and the reporting
quarter's GDP and HPI (published after the date) are used as if available at preparation.

**Base.** SPF GDP / unemployment / 10-year Treasury, annual averages held exactly
(minimum-curvature interpolation); mortgage = TBOND + spread (1.91 / 2.73 pp at the date -> 1.77
pp, the 2000-16 mean); HPI = VAR conditional on those paths. Long run: HPI 3.27%, GDP 2.06%
(2000-16, long-run Z -0.207); mortgage = SEP longer-run fed funds + 2.92 pp (1987-2019 ex-ZLB;
3.19 with ZLB) = 6.02% (2026) / 5.42% (2023); unemployment = SEP longer run (4.2 / 4.0).

| 1-year forward | 2026-03 HPI | 2026-03 GDP | 2023-03 HPI | 2023-03 GDP |
|---|---|---|---|---|
| Downside (20%) | 0.22 | 0.70 | -0.57 | -0.61 |
| Central (60%) | 2.64 | 2.20 | 1.83 | 0.88 |
| Upside (20%) | 4.86 | 3.31 | 4.02 | 2.00 |
| Realised (evaluation only) | - | - | 6.12 | 2.92 |

**Severity (primary: deviation from base vs historical 4-quarter forecast errors).**
- Z index (what the regions are cut on): downside 14.4 / 14.8th percentile, upside 86.7 / 86.4th:
  inside 5-20 and 80-95 on both dates.
- Single variables: downside HPI 15, GDP 16-18 (inside); upside HPI 85 (inside), **GDP 76-77
  (below 80)**. Cause: ranking on a combined index dilutes each variable towards the median.
- Secondary (levels, 1991+): upside HPI at the 40-51st and GDP at the 27-70th percentile; 2023
  downside GDP at the 3rd percentile (the SPF base itself sat at the 7th: a near-recession
  consensus).

**Cross-checks.** Base vs SEP (Q4/Q4 GDP, Q4 unemployment): 2026 close (2.2 vs 2.4; 4.5 vs 4.4);
2023 SPF more optimistic than the post-SVB SEP (GDP 1.4 vs 0.4 in 2023; unemployment 4.1 vs 4.5).

**Backtest preview (2023-03).** Realised 2023Q2-2026Q1 severity index at the 90th percentile of
the simulated paths; realised 1-year HPI 6.1% and GDP 2.9% above the upside scenario.

**Owner decisions on the scenarios (Yash, 2026-11-14).**
- **W1 Severity test.** The deciding test is the distance check on the **combined severity index**
  (the index the regions are cut on): pass on both dates. Single-variable percentiles are reported
  for information only. Recorded: upside GDP alone sits at the 76-77th percentile of SPF errors
  because the ranking is joint (part of the upside region is high-HPI / average-GDP paths) and
  historical GDP errors are skewed towards recessions (the downside tail is longer). No change to
  ranking or weights.
- **W2 State multipliers.** Beta-scaled state paths without intercepts amplify booms as well as
  busts (base 2026: CA +17%, NV +22% over 12 quarters vs national +8.5%). Accepted as a documented
  property: capping upswings only would bias the probability-weighted outcome (para 47).
- **W3 Backtest tracking.** The 2023-03 realised 2023Q2-2026Q1 outcome ranked at the 90th
  percentile of the simulated paths (above the upside). Tracked in the step-3 backtest.

## scen-0.2.0 (code `8cb4655`, 2026-11-14) - steps 2-3: crisis replay, CO-3, scenario PDs

**Crisis replay (dev_holdout loans; actual / predicted cumulative default).**

| Vintage, 5 years | R1 measured Z | R2 satellite Z | R3 + beta states | R3 + CO-3 |
|---|---|---|---|---|
| 2005 (held out) | 1.02 | 1.10 | 1.19 | **0.82** |
| 2006 | 1.15 | 1.25 | 1.30 | 0.91 |
| 2007 | 1.38 | 1.48 | 1.52 | 1.08 |
| 2006-07 sand states | 1.53 | 1.65 | **2.29** | 1.00 |
| 2006-07 other | 1.16 | 1.26 | 1.18 | 1.00 |

- Shortfall by link: hazard (R1, vintage effect), satellite (R2: replay trough -1.03 vs measured
  -1.25), state mapping (R3: sand states only; betas without intercepts under-state the bust).
- **CO-3 split sand / other** (both split rules fire): M = 3.06 [2.86, 3.28] sand, 1.21
  [1.16, 1.26] other (90% bootstrap, 500 draws). 2006 and 2007 at 5 years: 0.90-1.09, pass.
- **2005 hold-out fails** (needs 0.8-1.25): national 0.71 (3y) / 0.82 (5y); sand 0.51 / 0.78;
  other 0.80 / 0.84. Over-prediction (conservative): 2005 needed no uplift (R3 0.98 / 1.19), and a
  uniform multiplier over stressed quarters front-loads its defaults into 2007-08. Calibrating on
  2005-07 pooled (sensitivity: M 2.82 / 1.15) still fails 2005 at 3 years (0.74; sand 0.55).
  Per V4 the multiplier is not accepted as is: **applied provisionally, owner decision pending**
  (config/overlays.yaml status applied_provisional).

**Scenario PDs** (per loan: data/processed/scenario_pd/; segments: reports/summary/scenario_pd_*).

| As on | Loans | 12m PD base / weighted | Lifetime base / weighted | Downside lifetime no CO-3 / CO-3 | s |
|---|---|---|---|---|---|
| 2026-03-31 | 339,472 | 0.63% / 0.66% | 5.41% / 5.64% | 6.57% / 7.24% | 0.46 |
| 2023-03-31 | 272,908 | 0.53% / 0.56% | 5.90% / 6.14% | 6.98% / 7.79% | 0.52 |

- Non-linearity uplift weighted / base: 12m 1.04-1.05, lifetime 1.04 (1.10 in the sand states,
  where CO-3 is 3x). CO-3 adds 0.02-0.03 pp to the weighted 12m PD and 0.13-0.16 pp to lifetime.
- 2024-26 vintages (27% of 2026-03 loans): lifetime 5.4% weighted, the largest downside
  sensitivity (uplift 1.07).

**Backtest 2023-03 (12-month, B-18).** Realised 0.470% vs weighted 0.561% (actual / predicted
0.84), base 0.88, upside 0.98, TTC 0.79; with measured Z of 2023Q1 1.01. The model is calibrated;
the gap is the macro outcome (W3: realised path at the 90th percentile, above the upside).
Segments: never-delinquent 0.71, LTV 80-100 0.64-0.71 (over-predicted), cured 1-3 months 1.11,
30-59 dpd 1.08, pre-2009 vintages 1.22.

**Early performance 2024-26 (V5).** CO-4 trigger fires: 2024 first-default incidence 1.34-2.04x
the PIT-adjusted 2000-16 benchmark (1.64 overall; 2012-16 benchmark 3.0), 2025 1.12; 2026 30+
dpd at age 0-5 months 1.56 (27 events). 30+ / 90+ stock lower than history (shorter time at 90+
than crisis-era foreclosure timelines). ~30% of 2024 early defaults are under relief; excluding
them about 1.15. Recorded as candidate CO-4 (config/overlays.yaml), not applied.

**Limitations (monitoring triggers).**
- **L6 CO-3 timing (owner decision 2026-11-14: CO-3 accepted as calibrated, option 1).** The 2005
  hold-out passes at 5 years nationally (0.82) but fails at 3 years (0.71) and in the sand states
  (0.51 at 3 years / 0.78 at 5 years): a flat multiplier over stressed quarters pulls defaults
  forward. Direction conservative. Consequence: the downside 12-month PD (Stage 1 ECL) is somewhat
  overstated; lifetime ECL is affected mainly through the timing of discounting. Trigger: re-test
  on any refit of the hazard, the satellite or the scenarios.
- CO-4 kept as a monitored candidate (ex-relief 2024 ratio ~1.15); re-test each reporting date.
- L7 benchmark not mix-adjusted (2024-26: higher FICO 755 vs 739, higher DTI 37.5 vs 33.4,
  LTV 74 vs 71). Trigger: CO-4 ratio > 1.25 after B-18 relief relabelling.
- L8 Vasicek shift applied to delinquency prevalence (approximation); default incidence is the
  deciding rate.
- L9 2023-03 backtest is one date: 12-month only; lifetime backtest needs Modules 5 and 7.

**Module 4 accepted (Yash, 2026-11-14).** CO-3 option 1 (accepted as calibrated, L6); CO-4
monitored candidate. Module done.

### Note (2026-11-14, code `0c42661`): status XX loans in the 2026-03 scoring snapshot
3,358 performing loans with delinquency status XX (not yet reported; almost all 2026
originations, ~1% of loans) had no PD; the step-3 averages (pandas mean) skipped them. Now
scored as current and flagged (`pd.dataset.build_scoring_snapshot`). Effect on the reported
2026-03 averages is small (new, low-risk loans); Module 4 outputs not re-run. Modules 6-8 use the
fixed snapshot. 2023-03 had no XX loans.

## Outputs regenerated 2026-11-15 (scen-0.2.0, no model change)

Full pipeline rerun from a clean tree at `424af50` (deterministic fits: LightGBM
deterministic, one BLAS thread in fit steps, ORDER BY on DuckDB reads, exact decimal rate average).
Finding M-7 / limitation G-4 in `docs/validation_report.md`.

Module 4 outputs re-run with the fixed scoring snapshot (see the note above). 2026-03: 12m PD base
0.64% -> 0.63% (weighted 0.66% unchanged); lifetime base / weighted 5.41% / 5.64% unchanged;
downside lifetime no CO-3 / CO-3 6.56% / 7.23% -> 6.57% / 7.24%. 2023-03 unchanged at published
precision; 2025-03 outputs committed for the first time.
