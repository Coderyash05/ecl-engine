# Glossary

| Term | Meaning in this project |
|---|---|
| **ACPIR Directions** | Reserve Bank of India (Commercial Banks - Asset Classification, Provisioning and Income Recognition) Directions, 2026: the ECL rules the engine implements (issued 27 April 2026, effective 1 April 2027) |
| **Aalen-Johansen estimator** | Non-parametric cumulative incidence of one outcome (default) when another (prepayment) competes and loans are censored; the "actual" curve in vintage backtests |
| **Asset correlation (rho)** | Share of a borrower's latent asset value driven by the common factor in the Vasicek model; 0.15 here (Basel residential-mortgage benchmark) |
| **B-18 / B-12 target** | PD training target: an RBI default that occurred under relief and cured within 18 (12) months, with no loss, is not counted as a default. Not the regulatory default definition |
| **Backstop (30 dpd)** | Rebuttable presumption that a loan more than 30 days past due has a significant increase in credit risk (paras 33-36) |
| **Calamity route** | Resolution of an account hit by a notified natural calamity (RSA Directions Chapter VI-A): the account stays standard, with the item (xiv) floors |
| **CET1 add-back** | Transitional relief: part of the ECL transition impact may be added back to Common Equity Tier 1 capital, at most 4/5, 3/5, 2/5, 1/5 over four years (paras 107-108) |
| **CO-1 ... CO-5** | Candidate or applied post-model adjustments (overlays), defined in `config/overlays.yaml` and the [register](limitations.md) |
| **Cure** | A defaulted loan that returns to current (arrears cleared) or is repaid without loss; for LGD, a default with no economic loss |
| **Current LTV / indexed LTV** | Outstanding balance over the property value indexed with the state house-price index since origination |
| **DPD (days past due)** | Days a payment is overdue; Freddie Mac reports months delinquent (00 current, 01 30-59, 02 60-89, 03 90-119, ...) |
| **EAD (exposure at default)** | Amount owed when default occurs: balance plus accrued interest; collateral is never netted (para 100) |
| **ECL (expected credit loss)** | Probability-weighted present value of cash shortfalls: PD x LGD x EAD x discount factor, over 12 months (Stage 1) or lifetime (Stages 2-3) |
| **EIR (effective interest rate)** | Rate that discounts expected cash flows to the carrying amount at initial recognition; the origination note rate is used as the proxy (allowed until 31 March 2030) |
| **Floor (prudential)** | Minimum provision rate per product category and stage (para 82): the provision is the larger of model ECL and the floor |
| **GNPA ratio** | Gross non-performing assets / gross advances; housing GNPA 0.8% at end-March 2026 for scheduled commercial banks (RBI Financial Stability Report, June 2026) |
| **Hazard (competing risk)** | Probability that a loan defaults, prepays or survives in a quarter, given it was alive at its start |
| **IRACP** | The old (pre-ECL) Income Recognition, Asset Classification and Provisioning rules, used for the transition comparison |
| **LGD (loss given default)** | Share of EAD lost after default, here P(no cure) x severity |
| **Lifetime PD** | Probability of default over the remaining contractual life, net of prepayment |
| **Monitoring period / specified period** | RSA Directions: from implementation of a resolution plan until 10% / 20% of the restructured debt is repaid |
| **NPA (non-performing asset)** | A loan more than 90 days overdue (para 6(5)); upgraded only when all arrears are repaid (para 8(10)) |
| **OOT (out of time)** | Validation sample from a later period than development: OOT1 2017-19, OOT2 2020-21, OOT3 2022-23 |
| **PD (probability of default)** | Probability of an RBI default within a horizon |
| **PIT / TTC** | Point-in-time PD reflects current and forecast economic conditions; through-the-cycle PD is the long-run average |
| **PSI (population stability index)** | Measure of distribution shift between development and a later sample (< 0.10 stable, 0.10-0.25 watch, > 0.25 review) |
| **RSA Directions** | Reserve Bank of India (Commercial Banks - Resolution of Stressed Assets) Directions, 2025: rules for restructured accounts |
| **Satellite model** | Regression linking the credit-cycle index Z to macro variables, so scenarios move the PD |
| **Secured portion** | Part of the exposure covered by the realisable value of the collateral (para 6(24)); the rest is unsecured |
| **SICR** | Significant increase in credit risk since initial recognition: the trigger for Stage 2 (para 26) |
| **Stage 1 / 2 / 3** | No SICR (12-month ECL) / SICR, not credit-impaired (lifetime ECL) / credit-impaired (lifetime ECL) (para 25) |
| **Synthetic (India)** | The India adapter's book is derived from US loans with Indian product features: labelled synthetic, not Indian risk estimates |
| **Vasicek model** | One-factor model: default when a latent asset value, partly common to all borrowers, falls below a threshold; gives the PD conditional on the cycle factor Z |
| **WoE (weight of evidence)** | ln(share of non-defaults / share of defaults) in a bin; the scorecard's transformation of each feature |
| **Z (credit-cycle index)** | Systematic factor of the Vasicek model (Z > 0 benign, Z < 0 stress), measured each quarter from realised defaults |
