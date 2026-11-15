# Model development log: PIT conversion of the 12-month PD (`pd_pit`)

Part of the validation evidence (RBI ECL Directions 2026, paras 47-49, 120-121, 130-131).
Methodology: `docs/methodology/pd_point_in_time.md`. All results are on **US Freddie Mac data and US macro
series**; they are not Indian risk estimates.

---

## v0.2.1 — 2026-11-13 — current (status: development; not independently validated)

Code: commit `dcdca6e`. **Satellite, ρ and all PDs are unchanged from v0.2.0**; only the driver
rule changed, together with its table and metadata.

### Conflict and amendment (Yash, decision T1)
In v0.2.0 GDP failed the amended driver rule. It lowered the OOT1+OOT3 error by 0.2% against
the required 5%, yet it was in the owner-specified final specification. The rule is amended a
second time:
- every driver needs the expected sign and \|HAC t\| ≥ 2 in sample;
- **core drivers specified ex ante in the design** (HPI, GDP: "Primary" in design §1.4) may not
  **worsen** the out-of-sample error by more than 5%;
- **optional additions** (Fed funds) must **improve** it by at least 5%.

Result (`driver_rule.csv`): HPI passes (t 3.97, error −26%). GDP passes (t 3.71, error −0.2%,
no worse). Fed funds fails (t −1.02) and remains a reported sensitivity. Final drivers pass:
**True**.

Reason for the asymmetry: a driver chosen on economic grounds before looking at the data
should not have to earn its place on a short, already-used OOT window (2017-23). A driver added
after looking at the data must earn it.

---

## v0.2.0 — 2026-11-13 — superseded by v0.2.1 (driver-rule change only)

Code: commit `8beeccd` (fitted from a clean tree). Decisions S1-S4 of Yash after the review of
v0.1.0 (owner decisions after the review).

### Changes
| # | Change | Reason |
|---|---|---|
| 1 | **Fed funds change dropped from Z.** Final satellite: Z = −0.546 + 0.0438 × HPI YoY[W] + 0.0946 × GDP YoY[W] (R² 0.77, residual sd 0.18). The Fed funds specification is kept as a reported sensitivity | In sample HAC t −1.0; its OOT gain came from 2022-23 only |
| 2 | **Driver rule amended** (open question 3): a driver is kept only if it has the expected sign, \|HAC t\| ≥ 2 in sample and ≥ 5% lower OOT1+OOT3 error than the same specification without it | Owner decision |
| 3 | **ρ = 0.15 is a benchmark** (Basel residential mortgage): not identifiable from this data, chosen by the group backtest; 0.10 and 0.20 reported as sensitivities. The candidate-selection machinery of v0.1.0 is removed | Owner decision |
| 4 | Backtest reported **with and without the 0.03% floor** | Separates the floor's effect from model error |
| 5 | Candidate overlay **CO-3** (sand states) recorded, with a quarterly monitoring table `sand_states_by_quarter.csv` | Owner decision |

**OOT 2017-2023 has now been used for driver selection** (the Fed funds decision and the driver
rule both use OOT1+OOT3 errors), so it is not a fully clean test period. A clean test needs data
after 2023 with 12-month outcomes, or the independent validation of Module 11.

### Driver rule: GDP does not pass, but stays by owner decision
| Specification | Driver | HAC t | OOT error with / without | Reduction | Passes |
|---|---|---|---|---|---|
| HPI + GDP + Fed funds | HPI | 4.13 | 0.166 / 0.264 | 37% | yes |
| | GDP | 3.12 | 0.166 / 0.176 | 5.6% | yes |
| | Fed funds | −1.02 | 0.166 / 0.176 | 5.4% | **no** (t) |
| **HPI + GDP (final)** | HPI | 3.97 | 0.176 / 0.239 | 26% | yes |
| | GDP | 3.71 | 0.176 / 0.176 | **0.2%** | **no** (gain) |

Applied literally, the amended rule would drop GDP and leave HPI alone. The final specification
named by the owner (HPI + GDP) is kept, and the conflict is **open for the owner to resolve**.
For comparison, HPI only: OOT1+3 error 0.176 (the same), development error 0.144 (vs 0.126), COVID
0.43 (vs 0.32), crisis peak in 2009Q3 (late; with GDP 2008Q4, early). GDP improves the
in-sample fit and the timing, but not the 2017-23 level.

### Correlation sensitivity (final satellite refitted for each ρ)
| ρ | Worst group error | OOT1+3 never / cured / 30-89 dpd | Mean PIT 2009 | Mean PIT 2018 |
|---|---|---|---|---|
| 0.10 | 0.145 | 0.86 / 1.25 / 1.04 | 2.41% | 0.53% |
| **0.15** | **0.139** | **0.89 / 1.22 / 0.99** | **2.44%** | **0.52%** |
| 0.20 | 0.148 | 0.91 / 1.19 / 0.94 | 2.46% | 0.52% |

The portfolio level hardly moves with ρ; the split between groups does.

### Backtest (ρ = 0.15, satellite Z, realised macro), with and without the floor
| Period | Actual | PIT | PIT floored | Actual / PIT | Actual / PIT floored | Floor binds (share of snapshots) |
|---|---|---|---|---|---|---|
| Pre-crisis 2000-06 | 0.75% | 0.73% | 0.73% | 1.02 | 1.02 | 7.2% |
| Crisis 2007-11 | 2.09% | 1.98% | 1.98% | 1.06 | 1.06 | 0.7% |
| Recovery 2012-16 | 0.75% | 0.86% | 0.86% | 0.87 | 0.87 | 5.3% |
| Benign 2017-19 | 0.49% | 0.57% | 0.57% | 0.86 | 0.86 | 4.8% |
| COVID 2020-21 | 0.36% | 0.47% | 0.47% | 0.77 | 0.76 | 25.6% |
| 2022-23 | 0.45% | 0.39% | 0.39% | 1.15 | 1.15 | 11.3% |

- **The floor binds for many loans but moves the portfolio rate very little:** at most +0.75%
  relative, in COVID. The loans it lifts have tiny PDs. The deviations from 1 are model error,
  not floor effects.
- **Crisis peak:** predicted 2.74% in 2008Q4 vs actual 3.33% in 2009Q1. The peak is 18% too low
  and one quarter early; 2009Q1-Q3 lie below the 90% band.

### Candidate overlays (para 131) — recorded, not applied
| ID | Evidence | Direction | Monitoring trigger (proposal, not an RBI value) |
|---|---|---|---|
| CO-3 regional downturn (sand states CA/FL/NV/AZ) | Crisis 2007-11, actual / predicted **1.38** (other states 0.95); 2022-23: 1.22 | PD too low in regional downturns; a single national factor misses the regional cycle, even with state-HPI current LTV in the TTC model | Regional actual / predicted > 1.25 for two consecutive labelled quarters with ≥ 100 defaults (`sand_states_by_quarter.csv`). Regional backtest to be re-run after the hazard model |

CO-1 (COVID forbearance) and CO-2 (ever_deferred) of `pd_12m` still apply. In the PIT layer
30-89 dpd loans in OOT2 show actual / predicted 0.52.

---

## v0.1.0 — 2026-11-13 — superseded by v0.2.0 (first version, for review)

Code: commit `9ad3957`. TTC input: `pd12m-1.2.0`. Target B-18. Satellite estimated on
snapshot quarters 2000Q1-2016Q4; out of time 2017Q1-2023Q4.

### Asset correlation (decision 2)
| | Result |
|---|---|
| Profile likelihood (Z_t free every quarter) | Rises monotonically as ρ → 0: maximum at the grid edge (0.01) in 2000-2023, 2000-2012 and 2000-2016 |
| Unit variance of Z_t over 2000-2016 | ρ = 0.026 (at ρ = 0.15, Var(Z) = 0.14 and mean Z = −0.22) |
| Group backtest, worst group mean \|log(A/P)\|, measured Z | 0.10: 0.145 · **0.15: 0.139** · 0.20: 0.148 |
| Chosen | **ρ = 0.15** (lowest group error; also the fall-back) |

Readings:
1. **ρ̂ is not identified as an interior estimate.** With Z free, ρ affects the cross-section
   only through the stretch 1/√(1−ρ) of the probit scale. The likelihood prefers no stretch, i.e.
   the limit ρ → 0 with √ρ·Z fixed, which is a pure shift Φ(Φ⁻¹(p) − c_t). The TTC model's ranking
   within a quarter is already calibrated. The boundary estimate is treated as "not identified" and
   leaves the candidate set. **Amendment to the developer definition of "unstable" (§10 default 2):
   an estimate on the grid boundary counts as unstable** (the 95% interval had zero width, so the
   width rule alone would have accepted it).
2. **The residual cycle is small.** v1.2.0 already contains current LTV (HPI-indexed) and the
   delinquency state, so part of the cycle is in the TTC PD: its mean rises from 0.81% (2006)
   to 1.94% (2010). Z_t measures what is left, and it has far less variance than a ρ = 0.15
   world implies. **Consequence:** Z is not N(0, 1), and the long-run Z is the development mean
   (−0.22), not 0. Mean reversion of the macro drivers (design M1) handles this automatically
   (Z_LR = α + β′·mean X ≈ mean Z). Nothing may assume E[PIT] = TTC through Z ~ N(0, 1).
3. **The two criteria disagree.** The likelihood (dominated by the 90% of snapshots that are never
   delinquent) wants no stretch; the group pattern wants ρ ≈ 0.15. This is the single-factor
   restriction showing. Under the agreed rule the group backtest decides.

### Delinquency groups (D1 vs D2)
At ρ = 0.15, measured Z, OOT1 + OOT3, actual / predicted: never 30+ dpd **0.89**, cured **1.22**,
30-89 dpd **0.99**. All are inside 0.8-1.25, so **D1 (single Z) stands** under the default rule.
Cured loans are close to the upper edge. With satellite Z, never 30+ dpd is 0.79 (just outside),
but that includes the macro-mapping error.

### Satellite (decision 3, correction A)
| Spec | Terms | R² | OOT1+3 error | Note |
|---|---|---|---|---|
| **W, chosen** | const −0.598; HPI YoY +0.044 (t 4.1); GDP YoY +0.117 (t 3.1); Fed funds Δ4q −0.034 (t −1.0) | 0.78 | **0.166** | all signs as expected |
| W without Fed funds | HPI +0.044, GDP +0.095 | 0.77 | 0.176 | |
| L (lags t / t−4) | HPI[t] +0.044, GDP[t] +0.068; Fed funds dropped (wrong sign) | 0.69 | 0.221 | |
| W unemployment challenger | HPI +0.045, unemployment Δ −0.161 | 0.86 | 0.202 | best in sample; COVID error 0.49 |

- **W vs L:** W wins clearly (0.166 vs 0.221); the window-aligned specification is also the
  forward-looking one.
- **Fed funds kept under W** by the agreed rule (expected sign; OOT error 0.176 → 0.166). Caveats
  for the reviewer:
  - in-sample HAC t = −1.0, i.e. not significant in sample;
  - the gain comes from 2022-23 (OOT3 error 0.138 → 0.097, the rate-hike period), while 2017-19
    gets slightly worse (0.201 → 0.212);
  - under L its sign is wrong and it is dropped.
- Coefficients 2000-2012 vs 2000-2016: HPI 0.039 / 0.044, GDP 0.135 / 0.117, Fed funds −0.053 /
  −0.034, so stable.
- AR challenger: Z_{t−4} coefficient 0.42 (t 3.7). It absorbs most of the HPI effect (0.044 →
  0.015). It is not used (design §1.4: scenarios must drive Z).
- Stationarity (68 overlapping quarters): Z_t, HPI and GDP window means are inconclusive (ADF does
  not reject a unit root; KPSS does not reject stationarity). The residual is inconclusive (ADF
  p 0.04, KPSS p 0.04); its autocorrelation is expected from the overlap (MA(3)). Low power, as
  anticipated; the signs and the out-of-time test carry the weight.

### Backtest (ρ = 0.15, satellite Z with realised macro)
| Period | Actual | TTC | PIT | Actual / PIT | Inside 90% band | Floor binds |
|---|---|---|---|---|---|---|
| Pre-crisis 2000-06 | 0.75% | 1.00% | 0.73% | 1.03 | 93% | 7.0% |
| Crisis 2007-11 | 2.09% | 1.61% | 1.98% | 1.05 | 85% | 0.7% |
| Recovery 2012-16 | 0.75% | 1.04% | 0.87% | 0.86 | 90% | 5.1% |
| Benign 2017-19 (OOT1) | 0.49% | 0.72% | 0.58% | 0.84 | 67% | 4.5% |
| COVID 2020-21 (OOT2) | 0.36% | 0.80% | 0.46% | 0.78 | 75% | 27.0% |
| 2022-23 (OOT3) | 0.45% | 0.59% | 0.41% | 1.08 | 100% | 9.1% |

"Floor binds" is the share of snapshots whose 12-month PIT PD is below 0.03% (para 96),
computed at cell level. Average of quarters.

Findings:
1. **The PIT conversion fixes the level problem of v1.2.0**: actual/TTC 0.68-0.75 in benign
   periods becomes actual/PIT 0.84-1.08.
2. **The crisis peak is under-predicted and early.** Predicted peak 2.83% in 2008Q4 vs actual
   3.33% in 2009Q1; 2009Q1-Q3 are below the band (measured Z −1.37, satellite −0.97).
3. **Benign years are over-predicted** (2017-19: 0.84); only 67% of OOT1 quarters are inside the band.
4. **Sand states:** CA/FL/NV/AZ in the crisis, actual / predicted **1.38** (other states 0.95). A
   national factor misses the regional cycle, even with state-HPI current LTV in the TTC model.
   Candidate fixes for review: a regional loading, or a sand-state overlay (para 131).
5. **COVID:**
   - Under B-18, 2020Q2 has measured Z = +1.30. The TTC PD jumps to 1.46% because many loans
     are 30-89 dpd under forbearance, yet only 0.45% default.
   - Under target A, Z for 2019Q3-2020Q1 is −2.2 to −2.5, deeper than the 2009 trough. This is the
     relief relabelling, not the economy.
   - 30-89 dpd loans: actual / predicted 0.52 in OOT2. This is CO-1 again, now in the PIT layer.
6. **The PD floor binds often in benign periods:** up to 46% of snapshots in 2021Q1. The floor
   will be a material driver of Stage 1 ECL for this portfolio in good years.

## TTC input relabelled 2026-11-15 (no change to this model)

The TTC input is now `pd12m-1.2.1` (patch: exact decimal `rate_spread` average; inputs
identical within 1e-14; `models/pd_12m/CHANGELOG.md`, finding M-7). Version unchanged.
