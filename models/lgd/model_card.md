# Model card - LGD and EAD (lgd-0.2.0)

**Status:** development, not independently validated. **Owner:** Yash. **Tier:** 1.
**Data:** Freddie Mac Single-Family Loan-Level sample (US), FHFA state HPI. Not Indian risk
estimates.

| Item | Value |
|---|---|
| RBI basis | paras 97, 99 (own LGD, fallback 65/70%), 100 (no netting), 6(24) (secured portion), 44, 50-51 (discounting) |
| Default | RBI target A, first default per loan |
| Form | LGD = P(no cure, logistic incl. months in default) x severity (fractional logit) |
| Drivers | indexed LTV, credit score, loan age, prior 30+, relief; MI, property type, loan size |
| Discounting | origination note rate (EIR proxy), default -> zero-balance month |
| Development / OOT | defaults to 2016 / from 2017; cure intercept recalibrated on resolved 2012-19 defaults (shift -0.469) |
| Performance | 2012-16 LGD ratio 1.05; crisis 1.51 (CO-5); 2017-19 0.55, OOT 0.29 (conservative, L-LGD1); cure Gini 0.38 / 0.58 |
| Scenario use | per-year LGD from scenario state HPI paths; CO-5 in downside stressed years |
| EAD | scheduled balance + 3 months accrued interest at default; secured = min(EAD, value x 0.523) |
| Results 2026-03 | weighted lifetime LGD 6.9% (PD x EAD-weighted 7.7%; option 1: 8.8%); Stage 3 10.3%; 0.12 x RBI fallback |
| Overlays | CO-5 (applied) |
| Limitations | L-LGD1 to L-LGD7 (CHANGELOG) |
| Code / reproduce | `fd27c5e`; `ecl train lgd` (~10 min) |
