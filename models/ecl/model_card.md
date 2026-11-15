# Model card - staging, ECL measurement, prudential floors (ecl-0.1.0)

**Status:** development, not independently validated. **Owner:** Yash. **Tier:** 1.
**Data:** Freddie Mac Single-Family Loan-Level sample (US), FHFA state HPI, FRED / SPF / SEP.
Not Indian risk estimates.

| Item | Value |
|---|---|
| RBI basis | ACPIR paras 25-27, 33-36, Annex 1 (staging); 6(3), 77-81 (credit-impaired, curing, restructured); 44, 47-51 (measurement); 82(4)-(5), 90 (floors); RSA Directions 2025 paras 6(8), 6(12), 6(14), 6(16), 52-54, 58 (restructured upgrade; quoted) |
| Stage 3 | RBI default (90+ dpd, REO) until arrears are cleared (para 8(10)); general restructuring (modification, non-calamity deferral) until >= 10% repaid and >= 12 months after the first payment, a miss blocking upgrades until a fresh restructuring (RSA 58, 61, 62); duration = unbroken Stage 3 spell |
| Stage 2 | > 30 dpd backstop (no rebuttals); lifetime PD now / origination-expected >= 2.5 and + 0.5 pp; indexed LTV >= 100%; modified loans with 10-20% repaid |
| ECL | Stage 1 12-month, Stage 2 lifetime, Stage 3 LGD in default x EAD; per scenario then 20/60/20 weighted; note-rate discounting; CO-3, CO-5 in the downside |
| Floors | per category: housing (xi)(a) 0.25% / 1.50%, calamity-restructured (xiv) 5% / 10% (portfolio, per stage); Stage 3 per account by duration and secured / unsecured portion, [from, to) |
| Results 2026-03 | model ECL 154.7m -> provision 1,229.9m (0.19% -> 1.49% of 82.3bn EAD); restructuring 65% of the provision |
| Results 2023-03 | 75.8m -> 767.2m (0.13% -> 1.34%); Stage 2 anticipation 33% |
| Restructuring sensitivities | deferrals unmapped 951.7m / 615.6m; all deferrals general 1,590.7m / 1,030.1m; all restructured Stage 3 1,360.5m / 848.8m; at least Stage 2 419.3m / 317.6m |
| Other sensitivities | SICR 2.0 / 3.0 <= 1.1%; LGD option 1 +1.2% / +0.8%; RBI fallback LGD 1,765.0m / 1,042.8m; without CO-3 / CO-5 1,226.7m / 765.4m |
| Limitations | L-ECL1 to L-ECL8 (CHANGELOG) |
| Code / reproduce | `70e66da`; `ecl run [--date YYYY-MM-DD]` (~20 min per date) |
