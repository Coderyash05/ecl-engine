# Housing-loan ECL engine under the RBI ECL Directions 2026 - summary for reviewers

**What this is.** A Python engine that computes expected credit loss (ECL) for a housing-loan
portfolio under the Reserve Bank of India (Commercial Banks - Asset Classification, Provisioning
and Income Recognition) Directions, 2026. It covers staging, measurement, prudential floors,
the Annex 4 disclosures and the transition from the old IRACP provisioning. It is a portfolio
project built by one developer. It is **run on US data** (the Freddie Mac Single-Family
Loan-Level sample, 1.375m loans, 1999-2026, with FHFA / FRED / SPF / SEP macro data). Its results
are therefore **not Indian risk estimates**: they show how the Directions' rules behave on a
real mortgage book with a full credit cycle. Validation so far is **developer self-validation,
not independent validation**.

## What the engine does

| Step | Method | Directions |
|---|---|---|
| Data | 56 raw files to a loan-month panel (DuckDB / Parquet), every line checked; current LTV from state HPI | - |
| 12-month PD | WoE logistic scorecard (9 features; Gini 0.80 holdout, 0.69-0.75 out of time); PD at origination stored per loan | 26, 45, 96 |
| Point in time and lifetime PD | Vasicek cycle index driven by house prices and GDP; competing-risk hazard (default / prepay) by quarter | 45-49, 51 |
| Scenarios | SPF / SEP-anchored base, VAR Monte Carlo, downside / central / upside 20/60/20, mean reversion after 12 quarters | 47-49, 124, Annex 4 T5 |
| LGD and EAD | P(no cure) x discounted severity on indexed LTV; amortising EAD with prepayment; secured portion after a 47.7% realisation haircut | 97, 99, 100, 6(24) |
| Staging | 30+ dpd backstop; lifetime-PD SICR test against origination (2.5x and +0.5 pp); indexed LTV; NPA until arrears cleared; restructured accounts per the Stressed Assets Directions (RSA 52-62); calamity relief per RSA Chapter VI-A. Every loan records the rule that fired | 25-36, 77-81, 8(10) |
| Measurement and floors | 12-month / lifetime ECL per scenario, probability-weighted; floors per product category - housing (xi)(a) 0.25% / 1.50%, calamity-restructured (xiv) 5% / 10%, Stage 3 by years in Stage 3 and secured / unsecured portion | 44, 47-51, 82, 90-92 |
| Reporting and transition | Annex 4 Tables 1-9 (CSV + Markdown); old-rules IRACP provision; impact = max(0, ECL - IRACP); CET1 add-back 4/5 ... 1/5 | 107-108, Annex 4 |
| Governance | Maker-checker overrides with a hash-chained append-only log, applied in the next run; model inventory with tiering, checked automatically | 120-121, Annex 3 |
| Validation | Report under para 130's eight headings; backtests, sensitivities, findings | 130-131 |
| India adapter | Synthetic Indian book from the US loans (CIBIL, FOIR, LTV caps, repo-linked rates, tenure extension, RBI HPI); same staging, floors, Annex 4 and transition code | 82, 90, 107-108 |

Every RBI value sits in one config file with its paragraph reference. Developer choices are
marked as such. 259 unit tests check each rule with a hand-built example.

## Headline results (US data, US dollars)

| | 2026-03-31 | 2023-03-31 |
|---|---|---|
| Loans (Stage 1 / 2 / 3) | 333,110 / 8,138 / 7,693 | 269,381 / 4,798 / 6,128 |
| Exposure | 82.3bn | 57.3bn |
| Model ECL before floors | 154.7m (0.19%) | 75.8m (0.13%) |
| **Provision after floors** | **1,229.9m (1.49%)** | **767.2m (1.34%)** |
| Old-rules (IRACP) provision | 1,281.7m | 851.1m |
| Transition impact (dry run, 2026-03-31 used as first-application date) | 0 (ECL below IRACP; no CET1 add-back) | 0 |

- **The floors set the provision.** Model ECL is 13% of it. The Stage 1 floor binds, and the
  Stage 3 floors bind on 94-97% of accounts. Only Stage 2 passes model ECL through.
- **Restructuring is 65% of the provision** (804m on 2.6% of exposure). Restructured accounts
  stay in Stage 3 until the RSA monitoring period is met (10% repaid, 12 months after the first
  payment, no missed payment). A miss blocks the upgrade until a fresh restructuring. Stage 3
  floors rise with years in Stage 3.
- **Transition.** On base rates alone the ECL is 50.5m above the old rules. The old rules' 15%
  add-on for failed restructurings (RSA 64) and the 5% calamity add-on (IRACP 84A) reverse the
  sign.
- **Backtest (2023-03-31, next 12 months).** RBI defaults came in at 1.11x the predicted count
  (Stage 1 1.00, Stage 2 1.30). Realised losses were 0.09x the predicted 12-month ECL: most
  defaults cured, and the LGD is conservative after 2017.

## Key decisions (owner, recorded with the regulatory text)

1. **PD target B-18.** A COVID-relief default that cures within 18 months is not counted as a
   default for PD training. Staging and Stage 3 always use the RBI 90+ definition.
2. **The SICR test compares lifetime PD now with the lifetime PD expected at origination,
   adjusted for seasoning** (para 26), because the 12-month PD of a mortgage rises with age.
3. **The LGD is an own estimate, recalibrated on 2012-19 workouts.** It is kept against the
   65 / 70% fallback, which would raise the provision by 43.5%. Para 97 requires validation
   before such use.
4. **Downside overlays CO-3 (crisis default multiplier) and CO-5 (downturn LGD)** are applied
   and calibrated on a 2005-07 crisis replay. They move model ECL by 6%, but the provision by
   only 0.3%.
5. **Restructuring per the Stressed Assets Directions text.** The monitoring and specified
   periods both start at implementation. Each Freddie modification month is a fresh
   restructuring.
6. **Payment deferrals are split by cause.** COVID-window or disaster-linked deferrals that meet
   the calamity eligibility test follow the calamity route: they stay standard with the (xiv)
   floors. Other deferrals are general restructuring and go to Stage 3.
7. **Dry-run transition** at 2026-03-31, because the data end before the 2027 first-application
   date.

## Main limitations and open findings

- **No independent validation** (High). The developer, owner and validator are one person.
- **Regulatory readings drive the result** (High). The deferral mapping moves the provision
  between -23% and +29%; the restructuring mapping between -66% and +11%. These readings need
  compliance review.
- **PD target vs the default definition** (Medium). Stage 2 defaults on the RBI definition were
  under-predicted at 1.30x in the backtest. The cure credit counted twice (in the PD target and
  in the LGD) is worth +1.7% of Stage 1-2 model ECL, below the 5% retrain threshold, so it is
  monitored.
- **Floors mask model weaknesses** (Medium). Crisis vintages are under-predicted by the lifetime
  PD (2007: 10.2% vs 14.1%) and post-2017 LGD is over-predicted; neither shows in the provision
  while the floors bind.
- **Stage 2 anticipation is 33%** (Medium). Most defaults roll quickly from Stage 1.
- **Transition sign depends on the old-rules add-ons** (Medium).
- **Stale outputs, now regenerated** (Medium). Some 2026-03 scenario-PD and LGD summaries
  predated a scoring fix; a full deterministic rerun regenerated every output (headlines
  unchanged). A full-rerun regression check now precedes every results commit.
- **Data proxies.** Monthly status hides 1-29 day misses. A loan is treated as the borrower. The
  realisable value of collateral is the HPI-indexed value after a haircut.
- **US data.** The synthetic Indian book below tests the rules on Indian product features; it
  is not an Indian estimate either.

## Synthetic Indian book (Module 12; SYNTHETIC, not Indian risk estimates)

The 2026-03-31 US loans were re-expressed as an Indian book, with every assumption documented
with sensitivities in `docs/india_adapter.md`:
- CIBIL-style scores and FOIR, employment type, city (RBI HPI cities), ticket sizes in rupees;
- RBI LTV caps by ticket band (Credit Facilities Directions, para 111), enforced in the generator;
- repo-linked floating rates whose tenure extends on rate rises up to retirement age, after
  which the EMI rises;
- PD and the NPA stock calibrated to a housing GNPA of **0.8%** (RBI FSR June 2026, Chart 2.3 b,
  all scheduled commercial banks, end-March 2026);
- an Indian LGD assumption.

Scenarios come from a VAR on the real RBI house price index (three bases spliced), real GDP
(NAS 2011-12 and 2022-23 bases, chained on growth because the bases disagree) and CPI (2012 base
linked to 2024), with the repo rate driving the floating-rate mechanics.

| | US book | Synthetic India |
|---|---|---|
| Exposure; GNPA | 82.3bn USD; 2.2% Stage 3 (65% of the provision restructured) | Rs 101,296 crore; 0.79% |
| Provision (coverage) | 1,229.9m (1.49%) | Rs 468.8 crore (0.46%) |
| Floors | Stage 1; 7,395 Stage 3 accounts | Stage 1; 2,349 of 2,563 Stage 3 accounts |
| Transition (dry run) | 0: old rules higher (restructuring add-ons) | **Rs 73.4 crore**: ECL above the old rules |

Without restructuring, ECL exceeds the old rules: lifetime Stage 2 ECL is above the 0.25%
standard-asset rate. That confirms the US base-rate finding.

The largest sensitivities:
- RBI fallback LGD: +275%.
- Realisation haircut of 50%: +18%.
- PD level ×2: +13%.
- P(no cure) of 0.7: +10%.
- Repo +2 pp: +7.7%.

The LTV caps are verified against the Credit Facilities Directions 2025 (updated as on
October 1, 2026), para 111.

**Where to look.**
- Method: `docs/methodology/`. Rules to code to tests: `docs/regulatory_mapping.md`.
- Validation: `docs/validation_report.md`; register of limitations, overlays and findings:
  `docs/limitations.md`.
- Development logs: `models/*/CHANGELOG.md`. Inventory: `config/models.yaml`.
- India adapter: `docs/india_adapter.md`; outputs `reports/summary/india/` (SYNTHETIC).
- Annex 4 outputs: `reports/summary/annex4/`.
- Rules and parameters: `config/rbi_2026.yaml`, `config/ecl.yaml`.
