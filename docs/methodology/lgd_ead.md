# LGD and EAD (lgd-0.2.0)

Loss given default, exposure at default and the secured portion of each exposure. Code:
`src/ecl/lgd/{data,models,apply,run}.py`, `src/ecl/ead/ead.py` (`ecl train lgd`). Parameters:
`config/lgd.yaml`. Development log: `models/lgd/CHANGELOG.md`; model card: `models/lgd/model_card.md`.
US data (Freddie Mac loan-level, FHFA HPI); not Indian risk estimates.

## RBI basis

| Topic | Para | Use |
|---|---|---|
| Own LGD estimate, independently validated | 99 | Cure x severity model below |
| Fallback LGD 65% secured / 70% unsecured | 97 | Sensitivity (values in `config/rbi_2026.yaml`) |
| EAD: credit-risk mitigants not netted | 100 | Collateral enters the LGD and the secured portion, never the EAD |
| Secured portion = realistic realisable value of collateral | 6(24) | Indexed property value x (1 - realisation haircut) |
| Discount at the EIR at initial recognition (contractual rate allowed to 31 March 2030) | 50-51 | Origination note rate as the EIR proxy |
| A late recovery is a credit loss | 44 | Recoveries discounted from default to the zero-balance month |

## Default and resolution

- **Default:** RBI definition (90+ dpd, REO acquired, or loss-type termination); the loan's first
  default.
- **Liquidation:** zero balance code 02 / 03 / 09 / 15 after default. **Cure:** back to current, or
  prepaid / securitised (01 / 16), with no loss termination; economic loss 0. Defect repurchases (96)
  are excluded; defaults still open at data end are censored.

## LGD = P(no cure | default) x severity

- **Cure model** (logistic, standard errors clustered by loan): indexed LTV, credit score and loan
  age (linear splines), a prior 30+ dpd episode, relief at default and **months in default**
  (dummies 0, 3, 6, 12, 18, 24, 36). Each default contributes one row per observation point while
  still in default, so a Stage 3 loan gets an LGD conditional on its time in default.
- **Severity** (fractional logit on [0, 1]): EAD at default = UPB + interest on the three missed
  instalments; net recovery = -(net sale proceeds + mortgage insurance + other recoveries) - expenses
  (Release 47 signs: recoveries negative, losses positive), discounted at the note rate from default
  to the zero-balance month; severity = 1 - PV / EAD. Drivers: indexed LTV at default and loan size
  (linear splines), mortgage-insurance coverage, property type.
- **Recalibration:** the cure-model intercept is shifted so that the level matches fully resolved
  2012-19 defaults (shift -0.469; slopes kept). The development fit (option 1) is kept as a
  sensitivity.

**Scenario dependence.** For each loan and future year, the LTV at default comes from the scenario's
state HPI path and the amortised balance; P(no cure) is taken at months in default 0 with relief set
to 0 (conservative); severity at that LTV. Macro enters only through indexed LTV.

**Downturn overlay CO-5 (para 131).** Rule set by the model owner: no separate downturn overlay unless
the backtest shows a non-conservative crisis gap (2007-11 actual / predicted LGD > 1.10). It fires
(1.51), so the downside scales severity by 1 + (1.507 - 1) x s in stressed years, where s is the CO-3
severity scale.

**Stage 3.** P(no cure) at the months in the current default spell (capped at the last observation
point, 36 months), LTV now; REO-acquired loans cannot cure (P = 1).

## EAD and the secured portion

- EAD at a future default = scheduled balance before the three missed instalments + their interest;
  prepayment acts through survival in the lifetime PD.
- EAD now = UPB + interest on the delinquent months.
- Secured = min(EAD, indexed value x (1 - haircut)), unsecured = remainder; haircut = 1 - median(net
  sale proceeds / indexed value) over REO sales = **47.7%**. The split feeds the Stage 3 floors.

## Results (summary)

- 2026-03-31 weighted lifetime LGD 6.9% (option 1: 8.8%); Stage 3 LGD 10.3%.
- Actual / predicted LGD by default period: development 1.31, 2000-06 0.84, crisis 2007-11 1.51
  (covered by CO-5 in the downside), 2012-16 1.05, 2017-19 0.55, out of time 2017+ 0.29.
- After the floors, the recalibration moves the provision by only +1.2% to +1.8%; the RBI fallback LGD
  would raise the 2026-03 provision by 43.5%. Para 97 expects independent validation before an own
  estimate replaces the fallback (finding H-2).

## Limitations

L-LGD1 to L-LGD8 (post-2017 over-prediction, resolution bias, first default only, relief = 0 in
projection, Stage 3 LGD not scenario-weighted, recovery timing, haircut includes distressed-sale
discounts, development-period calibration). Register: [docs/limitations.md](../limitations.md).
