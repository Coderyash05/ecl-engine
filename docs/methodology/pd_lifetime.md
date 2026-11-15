# Lifetime PD (pdlife-0.4.0)

Lifetime default probability per loan and scenario, used for Stage 2 ECL and the SICR test.
Code: `src/ecl/lifetime/{hazard_data,hazard,paths,portfolio}.py`, `src/ecl/lifetime/fit_lifetime.py`
(`ecl train pd-lifetime`). Model card: `reports/summary/pd_lifetime_model_card.md`; development log:
`models/pd_lifetime/CHANGELOG.md`.

RBI paragraphs: 45 (lifetime PD not mechanically derived from the 12-month PD), 46(1) (maximum
contractual period), 51 (expected cash flows including prepayment), 26 (SICR against initial
recognition), 49 and 124 (reversion beyond the forecast horizon), 96 (PD floor). US data; not Indian
risk estimates.

## Method

**Competing-risk discrete-time hazard.** One row per loan per quarter after a reference date, with
three outcomes: default (first B-18 default), prepayment (zero balance code 01 before maturity) and
survival. A weighted multinomial logit with survival as the base (own Newton-Raphson code: weights,
per-equation restrictions, standard errors clustered by loan):

```
log(h_outcome / h_survive) = age baseline + score components x horizon + delinquency state x horizon
                             + change in LTV and loan-age WoE + change in negative equity
                             + outcome-specific terms
default:   + Z (credit-cycle index) + one refinancing-incentive indicator (>= 1 pp)
prepay:    + HPI growth + incentive bands + seasoning (age ramp, young x incentive)
```

Both equations share the borrower and collateral terms with their own coefficients; Z is kept out
of the prepayment equation and HPI growth out of the default equation (its default effect runs
through Z and the LTV change).

- **Score components** of the 12-month scorecard (pd12m-1.2.1) at the reference date, each with its
  own coefficient per horizon bucket (quarters 1-4, 5-8, 9-12, 13-20, 21+). The data decides how fast
  delinquency and credit-score information fade; the delinquency decay is state-specific.
- **LTV and loan age** enter as the change in their scorecard WoE along the projection. The WoE
  saturates as the score does, so long projections do not extrapolate without bound.
- **Macro:** the credit-cycle index Z (the same satellite as the [PIT PD](pd_point_in_time.md))
  enters the default equation only; HPI growth and the refinancing incentive (note rate minus the
  30-year mortgage rate) drive prepayment. The default equation keeps one incentive indicator
  (>= 1 pp): loans that stay despite an incentive are those that cannot refinance.
- **Age baseline** by loan-age year 0-14, pooled and held flat from 15 (763 defaults at ages 15+);
  the flat tail errs on the conservative side.
- **Sample:** a 1-in-16 hash sample of PD snapshots as reference dates (independent of outcomes;
  one snapshot per loan would over-draw short-lived loans), every default row, prepayment rows at
  50% and survival rows at 10% with inverse weights. Fitted on dev_train 2000-2016 references;
  holdout and out-of-time references are never used in fitting.

**Para 45.** Nothing about years 2+ is fixed by the 12-month PD: horizon decay, the age baseline and
the macro sensitivities are estimated from multi-year outcomes, and prepayment is a competing risk
with its own equation. The 12-month model contributes only ranking information at the reference
date. A challenger (H1) that re-estimates every borrower feature inside the hazard is reported.

**Lifetime PD** = cumulative incidence of default to contractual maturity (para 46(1)),
`sum_k S(k-1) h_default(k)` with `S(k) = prod_{j<=k} (1 - h_default(j) - h_prepay(j))`; prepayment
removes loans before they can default (para 51). The same survival curve feeds the EAD.

**Splice with the 12-month PD.** Year 1 of the curve is the 12-month PIT PD, so a loan's year-1 PD
does not jump when it moves from Stage 1 to Stage 2. Years 2+ come from the hazard, conditional on
surviving year 1. The year-1 ratio PIT / hazard is carried into later years with weight
`exp(-(y - 1) / tau)`, **tau = 3 years** (model-owner decision, 2026-11-13): it equals the 12-quarter
explicit macro forecast, so the carried cycle mismatch fades on the forecast's time scale (paras 49,
124). The development-optimal tau (infinite) failed out of time; the grid is reported as a
sensitivity.

**Floor.** 0.03% applies to the 12-month PD (para 96) and, as an interpretation marked
`rbi_specified: false`, to each later year's conditional annual PD (quarterly hazards are scaled up
when a year falls below it).

**Paths.** Each scenario's macro path: explicit forecast for 12 quarters, linear reversion to the
long-run means over the next 8, then flat to maturity (para 124). Long-run means are the 2000-2016
averages (the satellite window).

**SICR comparator (para 26).** Twelve-month PD rises with seasoning, and a remaining lifetime PD falls
as less time is left, so neither compares like with like. The comparator is the lifetime PD expected
at origination over the same remaining window (score components at origination, origination LTV,
scheduled amortisation, long-run macro); today's scenario-weighted remaining lifetime PD is compared
with it, so seasoning cancels. Historical forecasts at each origination are not available; long-run
macro stands in for them (documented approximation).

## Validation (summary)

- Year-1 hazard / 12-month PIT PD: 0.92-1.09 in every period.
- Year-2 over year-1 jump check (model / empirical by delinquency state and TTC decile): 5 flags in
  development, 5 out of time; recently delinquent and cured states inside 0.8-1.25 except 60-89 dpd.
- 2023-12 portfolio lifetime PD 5.34%.
- Crisis vintages under-predicted: the 2007 vintage reaches a 5-year cumulative default of 10.2%
  predicted vs 14.1% actual (covered in the downside by overlay CO-3).

## Limitations

L1 (60-89 dpd year-2 understated), L2 (TTC decile mis-fit), L3 (tau set by decision), L4 (2012-16
vintages over-predicted), L5 (carried ratio not split into segment and cycle parts). Register:
[docs/limitations.md](../limitations.md).
