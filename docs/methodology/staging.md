# Staging (ecl-0.1.0)

Stage 1 / 2 / 3 for every loan at a reporting date, with the rule that fired. Code:
`src/ecl/staging/{rules,restructured,comparator}.py`, called by `src/ecl/provisioning/run.py`
(`ecl run`). Parameters: `config/ecl.yaml` (`staging`); RBI values: `config/rbi_2026.yaml`.
Development log: `models/ecl/CHANGELOG.md`. US data; not Indian risk estimates.

## RBI text used (ACPIR Directions, `docs/reference/RBI-Directions.pdf`)

- **Para 25:** Stage 1 = no SICR since initial recognition (12-month ECL); Stage 2 = SICR, not
  credit-impaired (lifetime ECL); Stage 3 = credit-impaired at the reporting date (lifetime ECL).
- **Para 26:** compare "the risk of default occurring on the financial instrument over its expected
  life as at the reporting date, with the risk of a default occurring on the financial instrument
  over its expected life as at the date of initial recognition".
- **Para 6(3):** a credit-impaired asset shows objective evidence of impairment, including "(iii)
  Lender Concessions: The lender grants concessions - such as reduction in interest rates,
  rescheduling of repayment, or other reliefs, due to the borrower's financial difficulty, which
  would not have been offered under normal circumstances."
- **Para 5:** "A bank shall also follow the prudential guidelines for restructured accounts as
  prescribed in the Reserve Bank of India (Commercial Banks - Resolution of Stressed Assets)
  Directions, 2025, in addition to these Directions, as amended from time to time."
- **Para 8(10):** "The financial assets classified as NPA may be upgraded as 'standard' asset only if
  the entire arrears of interest and principal are repaid by the borrower."
- **Paras 33-36:** rebuttable presumption of SICR at more than 30 days past due.
- **Para 76:** Stage 3 at borrower level, Stage 2 at facility level.
- **Para 77:** "A financial instrument, other than a restructured financial instrument, classified as
  Stage 3, may be straightaway upgraded to Stage 1, after all the irregularities which lead to
  Stage 3 classification cease to exist, including absence of any evidence indicating SICR. If there
  is evidence of SICR, the financial instrument may be moved to Stage 2."
- **Para 78:** a restructured instrument classified as Stage 3 "shall be classified as Stage 2 only
  upon fulfilling the conditions prescribed at paragraph 58 and 60 of the aforesaid Directions.
  Thereafter, such financial instrument shall be classified as Stage 1, upon achievement of
  satisfactory performance during the specified period, provided there is no SICR."
- **Paras 80-81:** satisfactory performance, the specified period and upgrades follow the
  Resolution of Stressed Assets (RSA) Directions, 2025.
- **Annex 1:** SICR indicators include collateral value falling with house prices.

## Staging rules

| Rule (recorded per loan) | Stage | Basis |
|---|---|---|
| `default`: RBI default at the date (90+ dpd, REO acquired) | 3 | paras 6(3)(i), 6(5), 8(1) |
| `default_arrears`: reached 90+ and arrears not cleared (not back to current) | 3 | para 8(10) |
| `restructured`: general restructuring (modification, general deferral); stage from share repaid, time and misses | 3, then 2 | ACPIR 6(3)(iii), 78, 80; RSA 6(12), 52-62 |
| calamity route (calamity-linked deferral, RSA Chapter VI-A): stays standard, ordinary staging | 1 or 2, category (xiv) floors | ACPIR 82(4)(xiv), 82(5); IRACP 62A |
| `backstop_30dpd`: 30-89 dpd; no rebuttals (none evidenced) | 2 | paras 33-36 |
| `sicr_pd`: lifetime PD now / origination-expected lifetime PD over the same remaining window >= 2.5 **and** +0.5 pp | 2 | paras 26-27 (thresholds are developer choices; sensitivities 2.0 and 3.0) |
| `collateral_ltv`: indexed LTV >= 100% | 2 | Annex 1 |
| `override`: approved manual override (maker-checker) | as approved | Annex 3; see [governance](governance.md) |

Every loan records all rules that fired and the highest-priority one. The SICR test compares the
scenario-weighted remaining lifetime PD (with CO-3 in the downside) with the comparator described in
[lifetime PD](pd_lifetime.md): the PD expected at origination over the same remaining window under
long-run macro, so seasoning cancels. **Curing (para 77):** a non-restructured loan back to current is
restaged by the Stage 1-2 rules. Loan level is taken as borrower level (one loan per borrower in the
data; para 76 approximation).

## Restructured accounts (RSA Directions 2025)

Source: `docs/reference/RBI-Stressed-Assets-Directions-2025.pdf` (RBI/DOR/2025-26/165, 28 November
2025, updated as on 1 October 2026).

- **6(8)** "'monitoring period' shall mean the period from the date of implementation of resolution
  plan up to the date by which at least 10 per cent of the sum of outstanding principal debt as per
  the resolution plan and interest capitalisation sanctioned as part of the restructuring, if any,
  is repaid;"
- **6(12)** "'restructuring' shall mean an act in which a bank, for economic or legal reasons relating
  to the borrower's financial difficulty, grants concessions to the borrower. Explanation:
  Restructuring would normally involve modification of terms of the advances / securities, which
  would generally include, among others, alteration of payment period / payable amount / the amount
  of instalments / rate of interest; ..."
- **6(14)** "'satisfactory performance' shall mean that the borrower entity is not in default with any
  specified lender at any point of time during the period concerned;"
- **6(16)** "'specified period' shall mean the period from the date of implementation of resolution
  plan up to the date by which at least 20 per cent of the sum of outstanding principal debt as per
  the resolution plan and interest capitalisation sanctioned as part of the restructuring, if any,
  is repaid."
- **52** "An account classified as 'standard' shall be immediately downgraded as non-performing
  assets, i.e., sub-standard' to begin with, following a restructuring by a bank."
- **53-54** an NPA restructured keeps its classification, and ageing continues.
- **58** upgrade only when the account shows satisfactory performance during the monitoring period,
  and not "before one year from the commencement of the first payment of interest or principal".
- **61** a borrower that fails during the monitoring period can be upgraded only after "a fresh
  restructuring / change in ownership".
- **62** "Any default ... subsequent to upgrade in asset classification before the end of the
  specified period, will require a fresh resolution plan".
- Paras 59 (MSME) and 60 (aggregate exposure of Rs 100 crore and above, rating requirement) do not
  apply to individual housing loans.

**Reading applied (model-owner decisions, 2026-11-14; compliance review pending, finding H-1):**
1. Each Freddie modification month (flag Y) and the first month of a general deferral run is a
   restructuring; a later one is a fresh restructuring and starts a new monitoring period.
2. One clock from implementation: Stage 3 until at least 10% of the post-modification balance
   (including capitalised interest and the non-interest-bearing part) is repaid, at least 12 months
   have passed since the first post-modification payment, and no payment was missed (6(14): any
   default). Then Stage 2 until 20% is repaid with no miss; then Stage 1 if there is no SICR (para 78).
3. A miss blocks upgrades until a fresh restructuring (61 / 62); the clock does not restart.
4. An NPA restructured keeps its NPA ageing (53, 54): time in Stage 3 runs from the original default.

**Deferrals, split by cause.** A Freddie payment deferral (missed instalments moved to a
non-interest-bearing balance due at payoff) alters the payment period for financial difficulty, so it
is a restructuring under 6(12). Two routes:
- **Calamity route:** the deferral falls in the COVID window derived from the data (months with
  panel-wide deferrals above 2x the 2023-25 monthly median: 2020-07 to 2022-04) or follows a Freddie
  disaster flag within 12 months, and the loan was eligible under RSA 124J ("classified as 'Standard',
  but ... not in default for more than 30 days ... as on the date of occurrence of the calamity").
  The account stays standard (IRACP 62A, 62B) in category (xiv), with the ACPIR 82(4)(xiv) floors of
  5% (Stage 1) and 10% (Stage 2) and the 82(5) Stage 3 schedule for that category. RSA 124B keeps
  relief given before Chapter VI-A's effective date under the 2018 Master Direction that 82(4)(xiv)
  names, so the floors apply to the 2020-21 cases.
- **General restructuring:** other deferrals and ineligible calamity-linked ones (RSA 124K) follow
  RSA 52 -> Stage 3 and the upgrade rules above.

Sensitivities: every restructured account in Stage 3 (upper bound), every one at least Stage 2
(lower bound), deferrals unmapped, all deferrals general restructuring.

**Data mapping.** Base = current actual UPB in the event month (interest-bearing plus
non-interest-bearing UPB). The first payment after implementation is the next month; misses = status
01+ or an RBI default afterwards. Category (xiv) is kept while the loan is live (the text has no exit
rule). Calamity eligibility: status current (or not reported) and not NPA in the month before the
contiguous run of relief months ending at the deferral began.

## Limitations

L-ECL1 (RSA 124M timing not applied; calamity date proxied by the start of the relief run; (xiv) kept
for life; 1-29 day misses invisible in monthly data), L-ECL2 (loan = borrower), L-ECL3 (Stage 2
anticipates 33% of next-year defaults), L-ECL8 (arrears cleared proxied by status 00). Register:
[docs/limitations.md](../limitations.md).
