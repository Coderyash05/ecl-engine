# Model development log: lifetime PD, competing-risk hazard (`pd_lifetime`)

Part of the validation evidence (RBI ECL Directions 2026, paras 45, 46(1), 51, 120-121,
130-131). Methodology: `docs/methodology/pd_lifetime.md`. All results are on **US Freddie Mac data and US macro series**; they are not Indian risk
estimates.

---

## v0.4.0 — 2026-11-13 — current; Module 3 complete (status: development; not independently validated)

Code: commit `7e8b12e` (fitted from a clean tree). PIT input `pdpit-0.2.1`. Options
`{default_incentive: ge1, prepay_ramp: both, dlq_decay: state}`, calibrated splice with
**`carry_tau = 3`**. Owner decisions U2 and U3 (Yash) after the review of v0.3.0. Stages A-C reproduced their v0.3.0 choices.

### Fade length τ = 3 years (decision U2)
- **Primary reason.** τ equals the 12-quarter explicit macro forecast. That horizon was set in
  open question #5 before these results. The carried cycle mismatch then fades on the same time
  scale as the macro forecast (paras 49, 124).
  - Weight of the carried ratio: 0.72 in year 2, 0.51 in year 3, 0.37 in year 4 (the first
    year after the forecast).
  - It is still 0.26 in year 5, when the reversion is complete, and 0.10 in year 8. So the
    carry has **not fully faded** by the end of reversion.
- **Secondary reason.** A development-only parsimony rule gives the same answer: the smallest τ
  within 5% of the best development error is 3 (0.0307 vs 0.0294 at ∞). That rule was set
  after seeing the v0.3.0 results.
- **Rejected:**
  - τ = ∞: fails OOT (error 0.062, the worst on the grid) and conflicts with mean reversion.
  - τ = 2: chosen on OOT data.
  - τ = 0: restores the Stage 2 understatement (cured 1-3 months 0.77-0.79, 30-59 dpd 0.74-0.76).
- **OOT error at τ = 3:** 0.039, 7% above the OOT optimum (0.036 at τ = 1.5-2). The full grid
  is in `pd_lifetime_carry_tau_sensitivity.csv` and in the v0.3.0 entry.

### Jump check, model / empirical year-2 conditional default (flag outside 0.8-1.25)
| Segment | v0.2.0 shared fade dev · OOT | State decay, plain splice | v0.3.0 τ = ∞ | **v0.4.0 τ = 3** |
|---|---|---|---|---|
| never 30+ dpd | 1.08 · 1.09 | 1.04 · 1.04 | 0.95 · 0.81 | **0.97 · 0.85** |
| cured 13+ months | 0.86 · 1.19 | 0.95 · 1.30 | 0.89 · 0.90 | **0.90 · 0.97** |
| cured 4-12 months | 0.65 · 0.73 | 0.91 · 1.04 | 0.98 · 1.03 | **0.95 · 1.01** |
| cured 1-3 months | 0.65 · 0.63 | 0.79 · 0.77 | 0.92 · 0.90 | **0.88 · 0.85** |
| 30-59 dpd | 0.73 · 0.75 | 0.74 · 0.76 | 0.88 · 0.98 | **0.83 · 0.90** |
| 60-89 dpd (≈30 year-2 defaults) | 0.95 · 1.05 | 0.51 · 0.53 | 0.57 · 0.63 | **0.55 · 0.60** |
| TTC decile 1 | 1.21 · 3.24 | 1.17 · 3.08 | 0.79 · 1.38 | **0.87 · 1.71** |
| decile 2 | 0.64 · 2.46 | 0.62 · 2.35 | 0.46 · 1.21 | **0.49 · 1.44** |
| decile 3 | 1.74 · 1.97 | 1.68 · 1.89 | 1.30 · 1.07 | **1.38 · 1.23** |
| decile 5 | 1.57 · 1.34 | 1.52 · 1.29 | 1.26 · 0.84 | **1.31 · 0.93** |
| decile 6 | 0.85 · 1.03 | 0.82 · 1.00 | 0.70 · 0.69 | **0.73 · 0.75** |
| decile 9 | 0.89 · 0.89 | 0.87 · 0.88 | 0.81 · 0.75 | **0.82 · 0.77** |
| other deciles (4, 7, 8, 10) | 0.77-1.36 | 0.81-1.31 | 0.75-1.05 | **0.85-1.11** |
| **Flags (of 16)** | **7 · 9** | **7 · 8** | **6 · 5** | **5 · 5** |

- **The original Stage 2 problem is fixed.** Every recently delinquent and cured state other
  than 60-89 dpd is now within tolerance in both samples: they were 23-39% too low in v0.2.0.
- **Residual flags at τ = 3:**
  - 60-89 dpd in both samples (L1);
  - development: TTC deciles 2, 3, 5, 6;
  - OOT: deciles 1, 2, 6, 9.
- **The decile flags mostly change direction between samples.**
  - Decile 1 is 0.87 in development and 1.71 in OOT; decile 2 is 0.49 and 1.44.
  - Low deciles rest on 9-75 year-2 defaults per cell.
  - The exceptions are decile 6 (0.73 / 0.75, 66 / 98 defaults) and decile 9 in OOT (0.77,
    230 defaults). Both are consistently somewhat low.

### Prepayment refinement for the 2012-16 gap (decision U3)
D2 adds incentive bands × loan age 2-5 years, because the over-prediction lasts into year 3.
Rule, stated in the code before the run: adopt D2 if it moves the 2012-16 vintage lifetime PD
at origination (holdout loans, long-run macro, full term) or the 2023-12 lifetime PD (40k
sample, τ = 3) by more than 5% against D1, and does not lower the dev_train log-likelihood.

| | D0 no seasoning | **D1 age ramp + young × incentive (B3, kept)** | D2 D1 + incentive × age 2-5y |
|---|---|---|---|
| Terms | 87 | 96 | 101 |
| Log-lik dev_train · OOT | −0.19977 · −0.16540 | −0.19963 · −0.16505 | −0.19941 · −0.16463 |
| Vintage prepay error (years 1-3) | 0.410 | 0.282 | 0.281 |
| 2012-16 prepay actual / predicted, year 1 · 3 · 5 | 0.47 · 0.66 · 0.83 | 0.54 · 0.71 · 0.86 | 0.54 · 0.73 · 0.89 |
| 2012-16 **default** actual / predicted, year 1 · 3 · 5 | 0.54 · 0.72 · 0.81 | 0.53 · 0.70 · 0.79 | 0.53 · 0.70 · 0.78 |
| Lifetime PD at origination, 2012-16 vintages (49,948 holdout loans) | 6.27% (−3.7%) | 6.51% | 6.47% (**−0.6%**) |
| 2023-12 lifetime PD (sample) | 5.46% (+1.3%) | 5.39% | 5.20% (**−3.5%**) |

- **D2 is not material:** at most 3.5%, below the 5% threshold. It is **not adopted**, and L4
  stays a monitored limitation.
- **Materiality figure recorded:** the best prepayment refinement tested moves lifetime PD by
  ≤ 3.5%. Even the existing ramp against none moves it by ≤ 3.7%.
- **D2 does improve the likelihood** (OOT −0.16505 → −0.16463), but the 2012-16 year-1 gap is
  unchanged (0.54). The gap persists into years 3-5, so it is not a seasoning problem.
- **Direction of L4 corrected.** v0.2.0 said the gap "understates lifetime PD". Defaults of the
  same vintages are over-predicted by about as much (0.53 at year 1). The gap looks like an
  era-wide over-prediction of both exits, so the net effect on lifetime PD is not clearly
  downward.

### 2023-12 lifetime PD by delinquency state (297,213 loans, forward path illustrative)
| Segment | v0.2.0 | v0.3.0 (τ = ∞) | **v0.4.0 (τ = 3)** | v0.4.0 vs v0.2.0 |
|---|---|---|---|---|
| All | 5.50% | 4.84% | **5.34%** | −3% |
| never 30+ dpd | 4.63% | 3.75% | **4.32%** | −7% |
| cured 13+ months | 7.29% | 6.84% | **7.94%** | +9% |
| cured 4-12 months | 11.84% | 15.41% | **14.63%** | +24% |
| cured 1-3 months | 19.04% | 25.05% | **21.96%** | +15% |
| 30-59 dpd | 34.72% | 39.70% | **34.87%** | +0% |
| 60-89 dpd | 74.80% | 71.85% | **69.35%** | −7% |

- Long-run path: 5.34% → 5.19%.
- The annual floor binds for 0.07% of loans.

### Other checks
- **Year-1 hazard / PIT by period:**

  | 2000-06 | 2012-16 | 2017-19 | 2022-23 | COVID 2020-21 | crisis 2007-11 |
  |---|---|---|---|---|---|
  | 0.92 | 1.05 | 1.00 | 0.92 | 1.09 | 0.99 |

  All are within 0.8-1.25.
- **Vintage curves:** unchanged from v0.3.0, because they use the hazard without the carry.
  - 2007 vintage 5y: 10.2% predicted vs 14.1% actual (1.38).
  - CO-3 sand states 5y: 1.36 (2006) and 1.70 (2007); other states 1.06 and 1.26.
  - 2012-16 vintages are over-predicted (actual / predicted 0.46-0.89), the same pattern as L4.
- **SICR comparator:** seasoning-neutral (long-run macro on both sides).

### Known limitations and monitoring triggers (developer proposals; not RBI values)
- **L1: 60-89 dpd year 2 understated** (0.55 dev / 0.60 OOT; about 30 year-2 defaults).
  - **Materiality: small, because these loans realise most of their risk in year 1.**
    - 2023-12: 513 loans (0.17% of the portfolio).
    - 12m PD 55.4% of a lifetime PD of 69.4%, so 80% of the lifetime PD falls in year 1.
    - The year-2 marginal PD is 3.4 pp.
  - **If year 2 were raised to the empirical level** (÷ 0.55-0.60):
    - the segment's lifetime PD rises by about 2.3-2.8 pp (+3-4%);
    - the portfolio mean rises by about 0.005 pp (< 0.1% of 5.34%).
  - **Evidence is thin:** the year-2 estimate rests on 29-30 defaults per sample.
  - Trigger: review if below 0.8 with ≥ 100 year-2 defaults in the annual jump check.
- **L2: TTC decile mis-fit** (deciles 1-3 change direction between samples; deciles 6 and 9
  are consistently 0.73-0.82).
  - Trigger: review if any decile with ≥ 100 year-2 defaults is outside 0.8-1.25 in two
    consecutive annual checks. Decile 9 OOT (230 defaults, 0.77) is the first such reading.
- **L3: the fade length is set by decision, not identified by development data** (development
  argmin ∞).
  - Trigger: at each annual recalibration, re-estimate the τ grid; review if OOT error at
    τ = 3 exceeds the OOT optimum by more than 25%. It is 7% now.
- **L4: 2012-16 vintages over-predicted for both prepayment and default** (year-1 actual /
  predicted 0.54 / 0.53).
  - Materiality of the tested refinement: ≤ 3.5% of lifetime PD.
  - Trigger: review if year-1 vintage prepay actual / predicted is below 0.7 for the latest two
    vintages with ≥ 3 years of data.
- **L5 (candidate refinement, not built):** split the carried year-1 ratio into two parts:
  - a **persistent segment-level component** (structural hazard misfit, e.g. by delinquency
    state or decile), carried for the whole life;
  - a **fading cycle component** with τ tied to the forecast horizon.

  This would address L2 and part of L1 without carrying the cycle mismatch for life.
  - **Residual carry with τ = 3:** the cycle part of the carried ratio still has weight 0.26 in
    year 5, when the macro reversion ends, and 0.10 in year 8.
  - So part of the reporting-date cycle mismatch outlives the forecast and reversion window.
    This is accepted with τ = 3 (decision U2).
  - The split would let the cycle component fade fully, e.g. to zero by the end of reversion,
    while the structural component persists.

---

## v0.3.0 — 2026-11-13 — superseded by v0.4.0 (τ = ∞ candidate, rejected: fails OOT)

Code: commit `639b483` (fitted from a clean tree). PIT input `pdpit-0.2.1`. Options
`{default_incentive: ge1, prepay_ramp: both, dlq_decay: state}`, calibrated splice with
`carry_tau = inf` (the development estimate; see "Open decision" below).
Follows the owner's decision after the review of v0.2.0: fix the cause first, then calibrate only
what is left. Stages A and B reproduced their v0.2.0 choices
(A2 incentive ≥ 1 pp; B3 both prepayment ramps).

### The problem being fixed (pdlife-0.2.0)
With the year-1 splice, year 2 was understated relative to year 1 for recently delinquent and
cured loans by **23-39%** (year-2 conditional default, model / empirical: cured 4-12 months
0.65 dev / 0.73 OOT, cured 1-3 months 0.65 / 0.63, 30-59 dpd 0.73 / 0.75), and overstated for
the low-risk TTC deciles in OOT (deciles 1-3: 2.0-3.2). Cause investigated: the default
equation used **one fade for all delinquency states** (the v1.2.0 state coefficient × a weight
per horizon bucket, 0.91 → 0.29), so every state lost its delinquency information at the same speed.

### Step 1 — cause: state-specific delinquency decay (stage C)
The default equation gets one coefficient per delinquency state × horizon bucket (5 × 5 = 25
terms replace the 5 shared weights; 96 terms in all). Jump check, model / empirical year-2
conditional default (flag outside 0.8-1.25):

| Segment | v0.2.0 shared fade dev · OOT | v0.3.0 state decay, plain splice dev · OOT | v0.3.0 + carry (τ = ∞) dev · OOT |
|---|---|---|---|
| never 30+ dpd | 1.08 · 1.09 | 1.04 · 1.04 | 0.95 · 0.81 |
| cured 13+ months | 0.86 · 1.19 | 0.95 · **1.30** | 0.89 · 0.90 |
| cured 4-12 months | **0.65 · 0.73** | 0.91 · 1.04 | 0.98 · 1.03 |
| cured 1-3 months | **0.65 · 0.63** | **0.79 · 0.77** | 0.92 · 0.90 |
| 30-59 dpd | **0.73 · 0.75** | **0.74 · 0.76** | 0.88 · 0.98 |
| 60-89 dpd (≈30 year-2 defaults) | 0.95 · 1.05 | **0.51 · 0.53** | **0.57 · 0.63** |
| TTC decile 1 (lowest risk) | 1.21 · **3.24** | 1.17 · **3.08** | **0.79** · **1.38** |
| decile 2 | **0.64 · 2.46** | **0.62 · 2.35** | **0.46** · 1.21 |
| decile 3 | **1.74 · 1.97** | **1.68 · 1.89** | **1.30** · 1.07 |
| deciles 4-10 | 0.77-1.57 | 0.81-1.52 | 0.69-1.26 |
| **Flags (of 16)** | **7 · 9** | **7 · 8** | **6 · 5** |

Development = dev_holdout references 2000-16; OOT = references 2017-01..2021-12 (three years
of outcomes needed). Low deciles have 9-75 year-2 defaults per cell and 60-89 dpd ≈ 30: wide
sampling error.

- State decay **fixes cured 4-12 months** and narrows the gap for cured 1-3 months (35% → 22%). It leaves
  30-59 dpd unchanged and **breaks 60-89 dpd** (0.95 → 0.51; the separate coefficients for this
  state rest on few defaults beyond year 1). It does nothing for the decile pattern, which is
  about the level of the year-1 PIT PD, not the delinquency fade.
- Log-likelihood gain is small: OOT −0.1651 → −0.1650 for 20 extra parameters.
- Residual flags remained, so step 2 (the calibrated splice) applied.

### Step 2 — calibrated splice for what is left
The loan's year-1 ratio PIT / hazard (clipped 0.25-4) is carried into years 2+ with weight
exp(−(y−1)/τ), fading to 1. τ was estimated on development references: the value on the grid
{0, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, ∞} that minimises the mean squared log error of the
year-2 and year-3 conditional default by segment (cells with ≥ 30 defaults). OOT was used only
to validate it.

| τ (years) | 0 | 0.5 | 1 | 1.5 | 2 | 3 | 5 | **∞** |
|---|---|---|---|---|---|---|---|---|
| Development error | 0.0451 | 0.0427 | 0.0376 | 0.0344 | 0.0325 | 0.0307 | 0.0296 | **0.0294** |
| OOT error | 0.0552 | 0.0488 | 0.0395 | 0.0363 | **0.0363** | 0.0389 | 0.0443 | 0.0623 |
| Flags dev · OOT | 7 · 8 | 6 · 6 | 6 · 4 | 5 · 5 | 5 · 6 | 5 · 5 | 5 · 5 | 6 · 5 |

- **Estimated fade length: τ = ∞, at the edge of the grid.** The development error is flat
  beyond about 3 years (3 → ∞ improves it by 4%), so the length is not identified there.
- **OOT validation fails for τ = ∞.** It has the worst OOT error on the grid: 0.062, against
  0.036 at τ = 1.5-2, 71% higher. OOT prefers τ = 1.5-2.
- **Why ∞ fails out of sample.** It carries each loan's year-1 ratio to maturity, so the
  reporting date's cycle mismatch is kept for life. In OOT the never-delinquent ratio PIT /
  hazard is about 0.85, and that understates every later year (never 30+ dpd: 0.81).
- **Conflict with mean reversion.** Carrying a cycle-dependent ratio for life conflicts with
  the mean reversion beyond the forecast horizon (para 49, para 124).

### Change in the 2023-12 lifetime PD (297,213 loans; forward path illustrative)
| Segment | v0.2.0 | v0.3.0 (τ = ∞) | Change |
|---|---|---|---|
| All | 5.50% | **4.84%** | −12% |
| never 30+ dpd | 4.63% | 3.75% | −19% |
| cured 13+ months | 7.29% | 6.84% | −6% |
| cured 4-12 months | 11.84% | 15.41% | +30% |
| cured 1-3 months | 19.04% | 25.05% | +32% |
| 30-59 dpd | 34.72% | 39.70% | +14% |
| 60-89 dpd | 74.80% | 71.85% | −4% |

Long-run path: 5.34% → 4.83%.
- **Delinquent and cured loans rise:** the fix for the jump flags.
- **Never-delinquent loans fall:** mostly the carry of the year-1 ratio (12m PIT 0.22% vs
  hazard 0.26%, ratio 0.85) for their whole life.
- **This fall depends on τ.** With τ = 1.5-2 it would be much smaller; the per-τ lifetime PD
  is not yet computed.

### Other checks
- **Year-1 splice check:** unchanged in nature (hazard / PIT 0.92-1.09 by period).
- **Vintage curves:** essentially unchanged; they use the hazard without the carry.
  - 2007 vintage 5y: 10.2% predicted vs 14.1% actual.
  - CO-3 sand states: 1.36 / 1.70 (2006 / 2007 at 5 years).
  - Median actual / predicted by year: 1.16 / 1.09 / 1.01 / 0.98 / 1.06.
- **SICR comparator:** still seasoning-neutral by construction (long-run macro on both sides).
  - Median ratio for never-delinquent loans 0.36-0.70.
  - Cured 13+ months 0.66-1.31.
  - 30-59 dpd 3.0-5.5.
- **Annual floor (0.03%):** binds for 1.4% of loans in at least one year (0.06% of loan-years).

### Known limitations (residual after both steps) and monitoring triggers
Developer proposals, not RBI values; they are not in `config/rbi_2026.yaml`.
- **L1: 60-89 dpd year 2 understated** (0.57 dev / 0.63 OOT with the carry; about 30 year-2
  defaults per sample).
  - Effect: the year-1 PIT PD already gives 55-72% for these loans, so the effect on lifetime
    PD is bounded.
  - Trigger: re-run the jump check annually; review if 60-89 dpd year 2 is below 0.8 with
    ≥ 100 year-2 defaults.
- **L2: low-risk TTC deciles 1-3 mis-fit** (dev 0.46-1.30, OOT 1.07-1.38 with the carry;
  9-43 year-2 defaults per cell).
  - Trigger: review if any decile with ≥ 100 year-2 defaults is outside 0.8-1.25 in two
    consecutive annual checks.
- **L3: the fade length is not identified on development data** (τ = ∞ at the grid edge;
  rejected by OOT).
  - Trigger: re-estimate τ at each annual recalibration; review if the development estimate
    and the OOT optimum differ by more than one grid step.
- **L4: 2012-16 early prepayment still about 1.8× over-predicted** (carried from v0.2.0;
  understates lifetime PD).
  - Treated as a monitored limitation, pending Yash's confirmation (the answer to this question
    in the review duplicated the splice answer).
  - Trigger: review if vintage prepayment actual / predicted at year 1 is below 0.7 for the
    latest two vintages with ≥ 3 years of data.

### Open decision for Yash
The rule fixed before the run (development argmin) gives τ = ∞, and OOT rejects it. Options:
- (a) Keep τ = ∞ as estimated.
- (b) A parsimony rule on development data alone: the smallest τ within 5% of the development
  minimum, which gives **τ = 3** (OOT 0.039, flags 5 / 5). The rule is set after seeing these
  results.
- (c) τ = 2, the OOT optimum. OOT would then no longer be an independent test.
- (d) Plain splice (τ = 0): accept the residual flags of state decay as limitations.

---

## v0.2.0 — 2026-11-13 — superseded by v0.3.0

Code: commit `f8ae0df` (fitted from a clean tree; `dcdca6e` plus a deterministic row order for
the 40k comparison sample). PIT input `pdpit-0.2.1` (satellite unchanged).
Owner decisions T1-T5 (Yash) after the review of v0.1.0.

### Diagnosis of the 2022-23 year-1 gap (hazard / PIT 0.70 in v0.1.0)
**Hypothesis confirmed.** The incentive bands in the default equation act as a level shift
learned when most loans had an incentive.

| | dev 2000-16 | 2017-19 | 2022-23 |
|---|---|---|---|
| Share of loan-quarters with incentive < −1 pp | 3.8% | 6.3% | **89.4%** |
| Share with incentive ≥ 1 pp | 35% | 20% | 0.3% |
| Mean default-equation contribution of the incentive bands (log-odds) | +0.40 | +0.28 | **−0.03** |

Decomposition of the 2022-23 year-1 default (v0.1.0): hazard 0.31% vs PIT 0.45% (ratio 0.70).
Giving every loan the development-average incentive contribution lifts the ratio to **1.01**.
Other terms differ much less between periods: Z +0.09, the score's rest −0.20 (better borrowers),
LTV and loan-age paths ±0.03.

### Stage A — refinancing incentive in the default equation
| Variant | Year-1 hazard / PIT: 2000-06 · 2012-16 · 2017-19 · 2022-23 · COVID · crisis | Vintage default error | Lifetime PD 2023-12 (40k sample) |
|---|---|---|---|
| A0 bands (v0.1.0) | 0.89 · 1.07 · 0.98 · **0.70** · 1.10 · 0.99 | 0.315 | 4.70% |
| A1 none | 0.93 · 1.07 · 1.09 · 1.14 · 1.07 · 0.98 | **0.364** | **6.78%** |
| **A2 one indicator, incentive ≥ 1 pp (chosen)** | 0.91 · 1.06 · 1.00 · **0.91** · 1.09 · 0.99 | 0.316 | 5.62% |

Rule (stated in the code before the run): every period within 0.8-1.25, then the lowest vintage
default error. Why A2 and not A1:
- **A1 fixes 2022-23 by removing the selection effect altogether.** The intercept then gives every
  loan the average development-era incentive effect for its whole life, which raises the
  2023-12 lifetime PD by 44% (sample: 4.70% → 6.78%) and worsens the vintage fit.
- **A2 keeps the adverse-selection effect only where it is material.** Loans that stay despite
  an incentive of ≥ 1 pp have log-odds +0.45 (z 20). The base is everyone else, so a period
  with no incentive no longer moves the level.

### Stage B — prepayment seasoning (decision T3)
| Variant (on A2) | Extra terms | dev_train log-lik | Vintage prepay error (years 1-3) | 2012-16 year-1 prepay, predicted (actual 6.1%) |
|---|---|---|---|---|
| none | – | −0.19979 | 0.410 | 12.9% |
| B1 quarter-of-age ramp | 4 | −0.19975 | 0.345 | 11.5% |
| B2 young (< 2y) × incentive bands | 5 | −0.19967 | 0.332 | 12.5% |
| **B3 both (chosen)** | 9 | **−0.19964** | **0.282** | **11.2%** |

Rule: log-likelihood not below the stage-A choice, then the lowest vintage prepayment error.

Coefficients (prepayment equation, relative to the age-year baseline):
- **Age ramp** (within the age year): 0-2 months −0.91, 3-5 months −0.31, 6-8 months −0.17,
  12-17 months 0.00. A new loan barely prepays in its first quarter.
- **Young × incentive** (adds to the bands, z 7-27): +0.32 / +0.53 / +0.68 / +0.64 / +0.44.
  Young loans respond *more* to an incentive, not less: borrowers who refinance once tend to
  refinance again.

**The fix is partial.** 2003-07 vintages now fit well; at year 1 the predicted range is 7-11% vs
6.5-9.6% actual. 2012-16 vintages are still over-predicted about 1.8× at year 1 and 1.3-1.6× at
year 3. Candidate explanation for review: many 2012-13 loans were themselves refinances at record
low rates, and the 2013 rate rise left them with little incentive. The model's incentive is based
on the national 30-year rate, while the loan's own refinancing history is not a feature.
Remaining direction: prepayment too high → lifetime PD **understated**, kept as a known
limitation with monitoring.

### Change in the 2023-12 lifetime PD (all 297,213 loans, forward path)
| Segment | v0.1.0 | v0.2.0 | Change |
|---|---|---|---|
| All | 4.65% | **5.50%** | +18% |
| never 30+ dpd | 3.90% | 4.63% | +19% |
| cured 13+ months | 5.94% | 7.29% | +23% |
| cured 4-12 / 1-3 months | 9.89% / 16.45% | 11.84% / 19.04% | +20% / +16% |
| 30-59 / 60-89 dpd | 31.3% / 72.0% | 34.7% / 74.8% | +11% / +4% |
| LTV ≤ 60 / 60-80 / 80-90 / 90-100 | 3.8 / 5.7 / 7.2 / 8.8% | 4.7 / 6.6 / 7.8 / 9.1% | +23 / +15 / +8 / +3% |

On the 40k sample, almost all of the change comes from stage A (4.70% → 5.62%); stage B moves it
5.62% → 5.55%. The 2023-12 loans are mostly seasoned, so the young-loan terms barely apply.
Long-run macro: 4.60% → 5.34%.

### Year-2 / year-1 jump check (decision T2)
The spliced curve takes year 1 from the PIT PD and year 2 from the hazard (conditional on
surviving year 1). Its jump, year-2 conditional PD / year-1 PD, is compared with the empirical
jump (Aalen-Johansen). Development = dev_holdout references; OOT = references 2017-2022 with 8
quarters of outcomes. **Flag: model / empirical outside 0.8-1.25.**

| Segment | Year-2 defaults (dev / OOT) | Model / empirical, dev | Model / empirical, OOT |
|---|---|---|---|
| never 30+ dpd | 1,146 / 1,030 | 1.08 | 1.09 |
| cured 13+ months | 135 / 179 | 0.86 | 1.07 |
| cured 4-12 months | 140 / 126 | **0.65** | **0.77** |
| cured 1-3 months | 125 / 139 | **0.65** | **0.61** |
| 30-59 dpd | 157 / 165 | **0.73** | **0.70** |
| 60-89 dpd | 29 / 38 | 0.95 | 0.94 |
| TTC decile 1-4 | 9-26 / 23-75 | 0.65-1.80 (flagged: 2-4) | **1.46-2.91 (all flagged)** |
| TTC decile 5-9 | 33-294 / 91-277 | 0.84-1.69 (flagged: 5, 7) | 0.91-1.39 (flagged: 6) |
| TTC decile 10 | 1,024 / 661 | 0.81 | **0.75** |

Findings:
1. **Recently delinquent or recently cured loans:** the spliced curve understates year 2 by
   23-39%. The PIT year 1 is steeper than the hazard's year 1 for these states (hazard / PIT
   0.65-0.94), while year 2 comes from the flatter hazard. This matters for Stage 2, where most
   of these loans will sit.
2. **Low-risk deciles (OOT):** the jump is overstated 1.5-2.9×. The PIT year 1 is lower than the
   hazard's, so year 2 jumps up. Year-2 defaults in these cells are few (9-75), so the flags are
   noisy, and the absolute amounts are small.
3. **Candidate remedy for review (not implemented):** a calibrated splice. Carry the year-1
   ratio PIT / hazard into years 2+ with a weight that fades to 1 over 2-3 years, so year 2
   inherits each segment's year-1 calibration. To be decided by the owner.

### Other results (champion v0.2.0)
- Year-1 hazard / PIT by period: 0.91 · 1.06 · 1.00 · **0.92** (2022-23) · 1.09 · 0.99, all
  within tolerance.
- Vintage defaults at 5 years (actual / predicted):
  - crisis vintages: 2005 6.37 / 6.28%, 2006 10.55 / 9.24%, 2007 14.07 / 10.29%;
  - benign vintages over-predicted: 2012-16 at 5 years 1.3 / 1.6-1.9% (×0.7-0.8).
- CO-3: sand-state 5-year vintage ratios 1.19 (2005), 1.35 (2006), 1.69 (2007); year-1 crisis
  1.26. Unchanged; see the Module 4 requirement.
- SICR comparator (long-run both sides), never 30+ dpd 0.71-0.85, 30-59 dpd 3.2-5.0: still
  seasoning-neutral.
- Floors: the annual floor binds for 0.01% of loans; para 96 quoted (names the 12-month PD only).

### CO-3 — requirement carried to Module 4 (decision T4)
No regional factor. The downside scenario must be calibrated so that a 2007-09 replay
reproduces the actual 2006-07 vintage cumulative defaults within tolerance (proposal 0.8-1.25 at
3 and 5 years). If not achievable, CO-3 becomes an applied overlay in the downside scenario
(para 131, Annex 4 Table 6). Current gap to close: sand-state 2007 vintage at 5 years, 28.7%
actual vs 17.0% predicted with realised macro.

---

## v0.1.0 — 2026-11-13 — superseded by v0.2.0

Code: commit `00817e0` (fitted from a clean tree). Inputs: TTC `pd12m-1.2.0`, PIT
`pdpit-0.2.0` (ρ = 0.15). Target B-18; outcomes to 2024-12.

### What was built
- Quarterly multinomial logit, default / prepay / survive, from reference snapshots. Fitted on
  dev_train references 2000-2016: 1.31M references, 684k loans, 1.43M weighted rows
  representing 11.8M loan-quarters. dev_holdout references and 2017-2023 references are never
  used in fitting.
- **Champion H2:**
  - v1.2.0 score components (delinquency-state part, rest of the logit), each × 5 horizon
    buckets;
  - change in the v1.2.0 WoE of current LTV and of loan age along the path, and the change in
    negative equity;
  - Z (the cycle index of pd_pit) in the default equation;
  - refinancing incentive bands in both equations;
  - national HPI growth in the prepayment equation;
  - age baseline (years 0-14, pooled 15+ held flat to maturity).
- **Challenger H1:** borrower effects re-estimated — delinquency-state dummies × horizon and
  the WoE of the eight other features.
- Lifetime PD = cumulative incidence of default to contractual maturity (`remaining_months`)
  with prepayment as a competing risk (paras 46(1), 51). Year 1 is spliced to the 12-month PIT PD
  (design C1). Floors (config):
  - 0.03% on the 12-month PD (`pd.floor_12_month`, para 96);
  - 0.03% on every later year's conditional annual PD (`pd.floor_lifetime_annual`,
    `rbi_specified: false`).

### Defects found and fixed during development (before this version)
| # | Defect | Evidence | Fix |
|---|---|---|---|
| 1 | **Outcome-dependent reference sample**: one random snapshot per loan over-draws short-lived loans | Reference-sample 12-month default 1.41% vs 0.75% population (2000-06); hazard/PIT 1.5-2.7; predicted year-1 prepayment of new vintages 35-46% vs 4-10% | 1-in-16 hash sample of snapshots; errors clustered by loan |
| 2 | **Linear ΔLTV extrapolated without bound** | SICR comparator (origination side) fell 1.2× → 1.6× below the current side as loans aged | Change in the v1.2.0 WoE of current LTV (saturates as in the score) + change in negative equity |
| 3 | **Loan-age WoE frozen at the reference age** | Comparator ~1.4× below the current side for unchanged loans even at ages 0-2; crisis vintages under-predicted from origination by 1.5-1.8× | Change in the v1.2.0 WoE of loan age along the projection |
| 4 | Every covariate in both equations | HPI growth +0.25 in the default equation (collinear with Z and the LTV change) | Equations restricted as designed (HPI growth: prepayment only; Z: default only) |
| 5 | Singular Hessian on an overshooting Newton step (H1) | – | Damped Newton (small ridge, step cap); converges in 6-7 iterations |

### Coefficients (champion H2, cluster-robust z in brackets)
**Para 45 argument:** every element that shapes years 2+ is estimated from multi-year outcomes.
None of it is derived mechanically from the 12-month PD:
- **Horizon decay:** the delinquency-state weight falls 0.91 → 0.57 → 0.45 → 0.39 → 0.29 across
  horizon buckets (z 70 → 17); the weight on the rest of the score falls 0.95 → 0.80.
- **Baseline hazard by age:** estimated, with the pooled 15+ level held flat to maturity.
- **Macro sensitivities:** Z in default −0.72 (z −34; benign years lower default); HPI growth in
  prepayment +0.21 per 10% (z 37); incentive bands in both equations.
- **Prepayment as a competing risk:** an equation of its own, estimated from observed payoffs.

| Term | Default | Prepay |
|---|---|---|
| d WoE(current LTV) | −0.72 (−40) | +0.10 (14) |
| d negative equity per 10pp | +0.22 (13) | 0.00 (0.3) |
| d WoE(loan age) | −0.64 (−28) | +0.11 (13) |
| z | −0.72 (−34) | – |
| incentive 0-0.5 / 0.5-1 / 1-1.5 / 1.5-2 / ≥2 pp | +0.25 / 0.50 / 0.67 / 0.76 / 0.80 | +0.45 / 0.87 / 1.17 / 1.26 / 1.30 |
| HPI growth per 10% | – | +0.21 (37) |

The default incentive terms are a documented addition to the design (adverse selection: loans
that do not refinance despite an incentive are the ones that cannot).

### Fit
| Split | Mean log-lik H2 | H1 | Default A/P year 1 (H2) | Default A/P years 4-5+ (H2) |
|---|---|---|---|---|
| dev_holdout | −0.1991 | −0.1986 | 0.94 | 1.00-1.02 |
| OOT 2017-23 | −0.1654 | −0.1652 | 1.03 | 1.10-1.27 |

### Year-1 splice check: the hazard's own 12-month default vs the 12m PIT PD (tolerance 0.8-1.25)
| Period | Actual | PIT 12m | Hazard H2 | Hazard / PIT |
|---|---|---|---|---|
| 2000-06 | 0.61% | 0.72% | 0.65% | 0.89 |
| Crisis 2007-11 | 2.14% | 2.10% | 2.09% | 0.99 |
| 2012-16 | 0.73% | 0.78% | 0.83% | 1.07 |
| 2017-19 | 0.51% | 0.50% | 0.49% | 0.98 |
| COVID 2020-21 | 0.34% | 0.42% | 0.46% | 1.10 |
| 2022-23 | 0.44% | 0.45% | 0.31% | **0.70** |

**Within tolerance at portfolio level except 2022-23. By segment, 24 of 36 period × delinquency
state cells are within tolerance.** The hazard ranks more flatly than the PIT PD:
- TTC-PD decile 1: hazard/PIT 1.1-2.5;
- decile 10: 0.6-1.0;
- 30-59 dpd: 0.50-0.94.

The quarterly score weight (0.95) is below 1, and the Vasicek conversion stretches the probit
scale (1/√(1−ρ) = 1.085), so the PIT PD is steeper than the hazard. The splice makes year 1 equal
to the PIT PD exactly, so Stage 1 and the start of the Stage 2 curve agree. The diagnostic shows
that the hazard alone would compress year 1.

### Cumulative default and prepayment vs actual by vintage (dev_holdout loans, realised macro)
| Vintage | Default 3y actual / H2 / H1 | Default 5y actual / H2 / H1 | Default 8y actual / H2 |
|---|---|---|---|
| 2003 | 0.72 / 0.84 / 0.90% | 1.22 / 1.56 / 1.70% | 2.53 / 3.55% |
| 2004 | 1.44 / 1.15 / 1.21% | 3.23 / 3.18 / 3.43% | 5.60 / 5.94% |
| 2005 | 2.14 / 1.79 / 1.81% | 6.37 / 5.79 / 6.08% | 9.30 / 8.80% |
| 2006 | 5.40 / 4.69 / 4.71% | 10.55 / 9.05 / 9.33% | 13.07 / 11.28% |
| 2007 | 9.38 / 6.99 / 7.04% | 14.07 / 10.51 / 10.79% | 16.22 / 12.12% |
| 2012 | 0.79 / 0.91 / 0.94% | 1.23 / 1.41 / 1.49% | 1.76 / 1.88% |
| 2014 | 0.78 / 1.22 / 1.26% | 1.29 / 1.75 / 1.83% | – |
| 2016 | 0.76 / 0.98 / 0.99% | 1.38 / 1.72 / 1.79% | – |

- **Crisis vintages are under-predicted, most of all 2007** (5y: 10.5% vs 14.1%, ×1.34; 2006
  ×1.17). The worst vintage-crisis interaction is deeper than the hazard reproduces. This is the
  lifetime counterpart of the PIT crisis-peak finding.
- **Benign vintages are over-predicted early** (2012-16 at 3y: ×0.65-0.87), and converge by 8y.
- H1 and H2 now agree closely (after defect 3); H1 is 0-6% higher.
- **Prepayment is over-predicted in the first years**, most for 2012-16 (year 1: 11-15% vs
  4-9%), and converges by year 5-8. Over-predicted prepayment shortens expected life, so this
  **understates** lifetime PD (non-conservative). It needs monitoring and, if it persists, a
  recalibration of the early-age prepayment baseline.

### Regional re-run (CO-3)
| | Actual / predicted |
|---|---|
| Year 1, crisis 2007-11, CA/FL/NV/AZ (hazard; PIT for comparison) | **1.26** (PIT 1.33) |
| Year 1, crisis 2007-11, other states | 0.94 (PIT 0.92) |
| Vintage 2006, 5y, CA/FL/NV/AZ / other | **1.40** / 1.07 |
| Vintage 2007, 5y, CA/FL/NV/AZ / other | **1.68** / 1.21 |

State HPI through the LTV term narrows the year-1 gap slightly (1.33 → 1.26). **CO-3 persists
and is larger over the lifetime**: the regional downturn is deeper than LTV and a national Z
capture.

### 2023-12 portfolio (297,213 loans): lifetime PD
The forward path is **illustrative**: published macro to the latest quarter, then linear
reversion over 8 quarters to the 2000-2016 means (HPI 3.3%, GDP 2.1%, mortgage rate 5.4%,
long-run Z −0.21). Module 4 will supply base / upside / downside paths.

| Segment | Loans | 12m PIT PD (fwd) | Lifetime PD forward | Lifetime PD long-run | Origination-side comparator (long-run) |
|---|---|---|---|---|---|
| All | 297,213 | 0.50% | 4.65% | 4.60% | 5.10% |
| never 30+ dpd | 262,566 | 0.22% | 3.90% | 3.81% | 4.89% |
| cured 13+ months | 23,474 | 0.34% | 5.94% | 6.07% | 6.36% |
| cured 4-12 months | 5,171 | 1.30% | 9.89% | 10.09% | 6.91% |
| cured 1-3 months | 2,820 | 3.84% | 16.45% | 16.98% | 7.42% |
| 30-59 dpd | 2,669 | 12.99% | 31.31% | 32.58% | 8.29% |
| 60-89 dpd | 513 | 55.39% | 71.98% | 73.71% | 8.96% |
| LTV ≤ 60 / 60-80 / 80-90 / 90-100 | | | 3.8 / 5.7 / 7.2 / 8.8% | | |

Cumulative PD by year (forward), never 30+ dpd: 0.22% (1y), 0.92% (3y), 1.55% (5y), 2.65% (10y),
3.90% (30y). 30-59 dpd: 13.0 / 18.0 / 21.1 / 25.6 / 31.3%.

**Floor:** the annual floor binds in 0.01% of loan-years after year 1 (0.2% of loans) and changes
the mean lifetime PD by < 0.01%. The 12-month floor matters more: in benign quarters it binds for
many loans (pd_pit).

### SICR comparator (input to Module 6; decision B)
Both sides use long-run macro over the same remaining window. Median ratio of current lifetime
PD to the origination-expected remaining PD:

| dlq_state | 0-2y | 2-4y | 4-8y | 8y+ |
|---|---|---|---|---|
| never 30+ dpd | 0.85 | 0.73 | 0.71 | 0.74 |
| cured 13+ months | 1.08 | 0.95 | 0.92 | 0.96 |
| cured 4-12 months | 1.70 | 1.43 | 1.32 | 1.37 |
| cured 1-3 months | 2.77 | 2.22 | 1.99 | 2.05 |
| 30-59 dpd | 4.96 | 3.97 | 3.41 | 3.35 |
| 60-89 dpd | 9.32 | 8.75 | 7.63 | 8.69 |

- **No residual trend with age** (seasoning-neutral after defects 2-3).
- Clean loans sit below 1, because their LTVs fell faster than the long-run path assumed
  (2020-22 house prices).
- Recent delinquency raises the ratio sharply.
- A relative threshold (e.g. 2-3×) would separate the states. The threshold is Module 6's
  decision, and it is not an RBI value.

### Known limitations / open issues
1. Crisis vintages under-predicted (2007: ×1.34 at 5y); sand states worst (CO-3).
2. Early-life prepayment over-predicted for 2012-16 vintages (understates lifetime PD).
3. 2022-23 year 1: the hazard is below the PIT PD and below actual (0.70); the splice uses the
   PIT PD. OOT default A/P at horizons 13+ quarters is 1.2-1.3.
4. The hazard ranks more flatly than the PIT PD in year 1; the splice handles year 1, but the
   compression may continue into year 2.
5. The forward path is illustrative; Module 4 scenarios are needed for ECL.
6. 2017-2023 was used for PIT driver selection; it is not a fully clean test period.
7. Standard errors are clustered by loan; the satellite's estimation error in Z is not
   propagated.

## TTC input relabelled 2026-11-15 (no change to this model)

The TTC input is now `pd12m-1.2.1` (patch: exact decimal `rate_spread` average; inputs
identical within 1e-14; `models/pd_12m/CHANGELOG.md`, finding M-7). Version unchanged.
