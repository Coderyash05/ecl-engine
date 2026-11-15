# Module 12 - India adapter and SYNTHETIC Indian housing book

> **SYNTHETIC.** The Indian book is built loan by loan from the US (Freddie Mac) book under the
> assumptions below. The macro series are real RBI / MoSPI data. **None of the results are
> Indian risk estimates.** Amounts are in Rs crore.

Code: `src/ecl/india/{macro,scenarios,portfolio,engine,run}.py`, CLI
`ecl india` (about 3 minutes; it needs the US 2026-03-31 ECL run). Config
`config/india.yaml` (india-0.2.1). Outputs are aggregate tables in `reports/summary/india/`; the
loan-level synthetic book stays in `data/processed/india/` (gitignored, derived from Freddie
loans). Reporting date 2026-03-31. Current run: code `229e57d`, clean tree.

## 1. Data sources (`data/macro/india/`, gitignored)

Every file is validated on load (`macro.load_all`) for base year, first and last period, row
count and gaps, and raises `DataCheckError` on any mismatch. The run log prints one line per
series; the same lines are in `india_data_inventory_2026-03.csv`.

| Series | File | Source / table | Base | Coverage | Rows |
|---|---|---|---|---|---|
| Real GDP (Rs crore, constant prices) | `gdp_nas_2011-12.csv` | RBI DBIE table 161, NAS | 2011-12 | 2011-12 Q1 to 2025-26 Q2 (2011Q2-2025Q3) | 58 quarters |
| Real GDP | `gdp_nas_2022-23.csv` | RBI DBIE table 161, NAS | 2022-23 | 2022-23 Q1 to 2026-27 Q1 (2022Q2-2026Q2) | 17 quarters |
| CPI Combined General, All India | `cpi_base2012.csv` | MoSPI | 2012 = 100 | Jan 2013 to Dec 2025 | 156 months |
| CPI (General), All India, Combined | `cpi_base2024.xlsx` | MoSPI (all states / sectors / divisions; filtered) | 2024 = 100 | Jan 2025 to Oct 2026 | 22 months |
| House price index, all-India and cities | `House Price Index Publication.xlsx` | RBI DBIE | 2008-09, 2010-11, 2022-23 | 2009Q1 (cities) / 2010Q2 (all-India) to 2026Q2 | 3 blocks |
| Policy repo rate | `Major Monetary Policy Rates ... CRR & SLR.xlsx` | RBI DBIE | per cent | 2001Q2 to 2026Q4 | 103 quarter ends |

**GDP parsing:**
- Header rows are skipped.
- c1 is the fiscal year, given only on Q1 rows and forward-filled; c2 is the quarter; c11 is
  "Gross Domestic Product".
- Indian comma grouping ("61,62,845.93") and leading-space negatives (" -67,532.54") are
  parsed.
- Fiscal Q1 = April-June, ..., Q4 = January-March, mapped to calendar quarters.

**CPI parsing:**
- The `index` column is used, not `inflation` (blank in 2013); inflation is computed from it.
- April and May 2020 have status F* (imputed during the COVID lockdown). They are kept and
  listed in `india_summary_2026-03.json`.

**No longer used** (superseded 2026-11-15; removed from the config and moved to
`data/macro/india/superseded/`):
- the base 2004-05 GDP workbook (named "Base _ 2022-23");
- the "Base 2010=100" CPI workbook (base 2012, Jan 2011 to May 2013).

The 1999-2000 GDP file and the RBI T_19C summary were not present.

## 2. Splices and links

**GDP: YoY growth chained, levels not spliced** (`gdp_yoy_chained`; `india_gdp_overlap_2026-03.csv`).
- The two NAS bases disagree on growth in their overlap, not just on level:

  | YoY overlap, 2023Q2-2025Q3 (10 quarters) | Base 2011-12 | Base 2022-23 |
  |---|---|---|
  | Mean YoY | 7.88% | 7.31% |
  | Correlation | -0.008 | |
  | Mean absolute difference | 1.32 pp | |
  | Example: 2023-24 Q1 | 9.66% | 6.58% |

- Chained series: base 2011-12 YoY through 2022-23 Q4 (2023Q1), base 2022-23 YoY from 2023-24 Q1
  (2023Q2). Coverage is 2012Q2-2026Q2, 57 quarters, with no gaps.
- Limitation I-1: the growth series has a structural break at 2023Q2.

**CPI: 2024 base linked to the 2012 base** (`cpi_linked`).
- Link factor = mean of (2012-base index / 2024-base index) over January-December 2025 =
  **1.8985** (monthly min 1.8937, max 1.9027, range 0.009; the loader fails if the range exceeds
  0.05).
- The 2012-base index is used through December 2025; from January 2026 the 2024-base index ×
  1.8985 is used.
- Result: one continuous monthly series, January 2013 to October 2026 (166 months). Quarterly
  CPI = mean of complete quarters; inflation = YoY of the quarterly mean.

**RBI HPI: levels spliced on growth** (`hpi_spliced`; `india_hpi_splice_checks_2026-03.csv`).
- Each quarter takes its level from the newest base that covers it; earlier quarters are
  chained back on the older base's quarter-on-quarter growth.
- Cities that appear only in the 2022-23 base, and Kochi before 2010Q2, are chained back on
  all-India growth (flagged).
- The 2008-09 vs 2010-11 overlap agrees (city YoY correlations 0.83-1.00).
- The **2010-11 vs 2022-23 overlap does not**: all-India YoY correlation **-0.14**, mean absolute
  difference 2.2 pp. Coverage went from 10 to 18 cities and the weights changed (limitation
  I-2).

## 3. Indian scenarios (`india_scenario_paths_2026-03.csv`, Table 5)

**Model**
- VAR(1) on HPI quarter-on-quarter log growth, GDP YoY and CPI YoY, over 2014Q1-2026Q1. The
  COVID quarters 2020Q1-2021Q4 are excluded from estimation and bootstrap (GDP YoY −23% /
  +23%); 39 quarter pairs remain.
- 10,000 block-bootstrapped joint paths of 12 quarters, then linear reversion over 8 quarters
  to the window means: HPI 6.6% a year, GDP 7.1%, CPI 4.7% (paras 49, 124).
- Paths are cut 20 / 60 / 20 on the 12-quarter mean Z (para 47).

**Mapping to Z**
- Z = −0.207 + 0.0438 × (India HPI YoY − 6.63) + 0.0946 × (India GDP YoY − 7.09), using the US
  pdpit-0.2.1 satellite coefficients on Indian deviations from Indian means.
- GDP is now included in Z (it was HPI only in india-0.1.0).
- Sensitivity: both coefficients ×0.5 or ×2.

**Repo path**
- Base: flat at 5.25%, the rate in force on 2026-03-31.
- Downside / upside: +0.75 / −1.00 pp, the 80th / 20th percentiles of 4-quarter repo changes
  since 2001.
- CPI is reported only; it moves no PD.

**Table 5 (India)**

| Scenario | Weight | GDP 1y | GDP 5y avg | HPI 1y | HPI 5y avg | CPI 1y | CPI 5y avg | Repo 1y | Repo 5y avg | Z 12q |
|---|---|---|---|---|---|---|---|---|---|---|
| Downside | 0.2 | 6.3 | 6.6 | 3.1 | 4.4 | 3.2 | 3.8 | 6.00 | 5.78 | −0.42 |
| Central | 0.6 | 7.0 | 7.0 | 5.4 | 5.8 | 3.9 | 4.2 | 5.25 | 5.25 | −0.28 |
| Upside | 0.2 | 7.6 | 7.3 | 7.9 | 7.5 | 4.5 | 4.4 | 4.25 | 4.55 | −0.14 |

## 4. Regulatory and calibration values

**Housing GNPA target: 0.8%, verified.**
- Source: RBI Financial Stability Report June 2026, Chapter II, **Chart 2.3 b** "Personal Loans
  - GNPA Ratio by Category", printed page 65. Housing loans at end-March 2026: PSBs 0.7, PVBs
  0.8, FBs 0.8, **All SCBs 0.8**. File: `docs/reference/RBI-FSR-June-2026-Chapter-II.pdf`.
- How it was checked: no PDF renderer is installed, so the check uses the PDF text layer. The
  panel b title, the bank-group labels and the values "0.7 0.8 0.8 0.8" appear together for the
  Housing Loans group.
- It **replaces 0.5%**, an unverified secondary figure. That figure probably covers all
  lenders including housing finance companies, not scheduled commercial banks, so it does not
  fit a commercial-bank engine.

**LTV caps: verified (2026-11-15).**
- Source: RBI (Commercial Banks - Credit Facilities) Directions, 2025 (RBI/DOR/2025-26/154),
  **updated as on October 1, 2026**, Chapter VIII B.6 "Quantum of Loan", **para 111**, page 55.
  File: `docs/reference/RBI-Credit-Facilities-Directions-2025.pdf`.
- Individual housing loans: up to Rs 30 lakh ≤ 90% (≤ 80% at risk weight 35; > 80-90% at risk
  weight 50); above Rs 30 lakh and up to Rs 75 lakh ≤ 80% (risk weight 35); above Rs 75 lakh
  ≤ 75% (risk weight 50). These match the values the owner stated and the earlier config.
- How it was checked: PDF text layer (pypdf), the table under para 111. The proviso on page 56
  (loans sanctioned up to June 06, 2017) changes only risk weights; the maximum LTV per band is
  the same, so one set of caps applies to every origination date. Para 113 (stamp duty and
  registration charges excluded from the property value) does not arise in the synthetic book.
- Config: `config/rbi_credit_facilities.yaml` (`rbi_specified: true`, para, page, quote and
  "updated as on" date). `config/india.yaml` no longer holds the values; `rbi_2026.yaml` is
  unchanged.
- The generator enforces them by ticket size: `apply_ltv_caps`, plus a hard check that raises
  if any synthetic loan is above its cap. Tests read the caps from the RBI config.

## 5. Synthetic book construction

Source: the US 2026-03-31 loan-level output. 11,150 US loans with a modification, deferral or
calamity route are excluded, because no restructuring history is synthesised. Another 7,807
are dropped because they would have matured under the Indian tenure.

**GNPA calibration** (`stock_multiplier`):
- The eligible US NPA share of INR exposure is s = 0.489%. Multiplier k = t(1 − s) / (s(1 − t))
  = **1.640** for the target t = 0.8%.
- The delinquent stock (NPA and 30-89 dpd) is replicated by k: 2,848 copies, with ids suffixed
  `-cN`.
- The PD level is scaled by the same k (in steady state the NPA stock is proportional to the
  default intensity).
- Simulated GNPA is **0.793%**. **The synthetic book is 332,832 loans and Rs 101,296 crore.**

| Feature | Construction | Assumption / sensitivity |
|---|---|---|
| CIBIL score | US score percentile → piecewise-linear through assumed CIBIL quantiles (1% 600, 10% 690, 50% 760, 90% 820, 99% 860) | Descriptive only (PD keeps the US rank) |
| FOIR | = US DTI | Same definition |
| Employment | 30% self-employed, random | PD multiplier 1.5 vs salaried, normalised to a book average of 1; sensitivity 1.2 / 2.0 |
| Co-borrower | US `num_borrowers` >= 2 | - |
| City | One of the 18 RBI HPI cities, equal weights; tier 1 = HRA class X cities | The file does not publish its population weights |
| Ticket size | US amount percentile → lognormal, median Rs 30 lakh, US log dispersion | - |
| LTV caps | min(US LTV, cap of the ticket band); hard check | Section 4 (para 111, verified) |
| Collateral | Value = amount / LTV, indexed with the city RBI HPI | - |
| Rate | Repo-linked (EBLR) = repo + 2.5 pp | - |
| Tenure | Original = min(20 years, retirement age − age at origination); retirement 60 (salaried) / 65 (self-employed); maximum 30 years | Bank-practice assumption |
| Rate rise | EMI fixed, tenure extends up to the cap; then the EMI rises (payment shock) | - |
| Payment shock → PD | PD × (1 + 2.0 × EMI increase), on current PD only | Sensitivity beta 0 / 4; repo +2 pp |
| Prepayment | 8% a year | Sensitivity 4% / 15% |
| LGD | P(no cure) 0.5 × collateral severity (40% haircut, 3 years to recovery, at least 5%); Stage 3 P(no cure) 0.6 | Sensitivities P(no cure) 0.3 / 0.7; haircut 30% / 50%; RBI fallback 65 / 70% |

PD mechanics, staging, floors and the old-rules provision are unchanged from india-0.1.0. The
US PD rank order and the US hazard's response to Z are evaluated at the Indian scenario Z, so
the lifetime PD is not derived from the 12-month PD (para 45). The same engine code is used for
staging, floors and the old rules.

## 6. Results (2026-03-31, SYNTHETIC) and change from india-0.1.0

| | Stage 1 | Stage 2 | Stage 3 | Total |
|---|---|---|---|---|
| Loans | 318,908 | 11,361 | 2,563 | 332,832 |
| Exposure (Rs crore) | 96,734 | 3,760 | 803 | 101,296 |
| Model ECL (Rs crore) | 77.8 | 112.0 | 47.5 | 237.4 |
| **Provision (Rs crore)** | 241.8 | 112.0 | 114.9 | **468.8 (0.46%)** |
| Floor binds | yes (0.25%) | no (2.98% > 1.50%) | 2,349 of 2,563 accounts | |

- **Stage 2 rules:** 30+ dpd backstop 4,799; sicr_pd 4,691; indexed LTV 1,871.
- **Table 7:** Stage 1 PD 0.73%, Stage 2 lifetime PD 42.4%; LGD Stage 1 9.0%, Stage 2 7.0%,
  Stage 3 5.8%.

**Transition (dry run):**
- ECL Rs 468.8 crore vs old rules (IRACP) Rs 395.4 crore, so the **impact is Rs 73.4 crore**.
- CET1 add-back (pre-tax): Rs 58.7 / 44.0 / 29.3 / 14.7 crore in FY 2027-28 to 2030-31.
- Table 9: Stage 2 +102.6 (lifetime ECL vs 0.25% standard rate); Stage 3 −29.3 (housing Stage 3
  floors vs the old NPA rates in years 0-3).

**Change from the previous run** (attribution run with the new data at the old 0.5% target):

| Step | Provision | Coverage | Transition | GNPA | Driver |
|---|---|---|---|---|---|
| india-0.1.0 | 361.0 | 0.36% | 22.7 | 0.49% | - |
| + GDP / CPI data, VAR scenarios with the GDP channel (0.5% target) | 366.0 | 0.36% | 25.4 | 0.50% | Central Z −0.28 (was −0.25): HPI growth below its mean. Stage 2 model ECL +3.7; replication now lifts GNPA to exactly 0.50% (k 1.02) |
| + GNPA target 0.8% (k 1.64) | **468.8** | **0.46%** | **73.4** | **0.79%** | Stage 2 +60.1 (more 30+ dpd loans, PD ×1.6; the Stage 2 floor does not bind, so model ECL passes through); Stage 3 +42.6 (more NPAs); Stage 1 unchanged (0.25% floor still binds: model 0.08%) |
| LTV caps | 0 | - | - | - | Same values; verified against para 111 on 2026-11-15 (section 4) |

The transition impact grows with Stage 2: lifetime ECL rises with PD, while the old rules keep
standard assets at 0.25%.

**Sensitivities (provision; base Rs 468.8 crore):**

| Sensitivity | Provision | Change |
|---|---|---|
| Self-employed PD multiplier 1.2 / 2.0 | 468.9 / 467.4 | 0.0% / −0.3% |
| Payment-shock beta 0 / 4 | 468.1 / 469.3 | −0.2% / +0.1% |
| Repo +2 pp in every scenario | 504.7 | **+7.7%** (Stage 2 loans 11,361 → 14,354) |
| Prepayment 4% / 15% | 463.8 / 476.7 | −1.1% / +1.7% |
| P(no cure) 0.3 / 0.7 | 423.5 / 514.7 | −9.7% / +9.8% |
| Realisation haircut 30% / 50% | 418.2 / 552.1 | −10.8% / **+17.8%** |
| Z elasticity (HPI and GDP) ×0.5 / ×2 | 464.2 / 479.6 | −1.0% / +2.3% |
| PD level ×2 (GNPA stock unchanged) | 529.6 | +13.0% |
| RBI fallback LGD 65 / 70% | 1,757.0 | **+275%** |

With more of the provision now in Stage 2, where model ECL is not floored, LGD and rate
assumptions matter more than in india-0.1.0.

## 7. Synthetic India vs US book (`india_vs_us_2026-03.csv`)

| | US (Freddie Mac) | India (SYNTHETIC) |
|---|---|---|
| Stage mix by exposure, S1 / S2 / S3 | 95.4 / 2.4 / 2.2% | 95.5 / 3.7 / 0.8% |
| Model coverage | 0.19% | 0.23% |
| Provision coverage | 1.49% | 0.46% |
| Stage 3 provision coverage | 52.0% | 14.3% |
| Floors binding | Stage 1, 7,395 Stage 3 accounts | Stage 1, 2,349 of 2,563 Stage 3 accounts |
| Transition impact (dry run) | 0 (old rules higher: restructuring add-ons) | **Rs 73.4 crore** (ECL higher) |

## 8. Limitations (monitoring triggers)

- **I-1 GDP base change.** The 2011-12 and 2022-23 NAS bases disagree on YoY growth in the
  overlap (correlation −0.008; means 7.9% vs 7.3%). Growth is chained (2011-12 base to 2023Q1,
  2022-23 base after), so the GDP growth series has a break at 2023Q2. Trigger: re-check when
  MoSPI publishes a back series on the 2022-23 base.
- **I-2 HPI 2022-23 re-basing:** YoY growth is inconsistent in the 2022-25 overlap (all-India
  correlation −0.14). Trigger: re-check when DBIE publishes a linked series.
- **I-3 US borrower behaviour:** PD rank order, macro sensitivity and delinquency states are US.
  Employment, payment-shock and LGD parameters are assumptions.
- **I-4 US lifetime PD over the US remaining life** is spread over the Indian tenure (constant
  hazard).
- **I-5 No restructuring or calamity history** in the synthetic book.
- **I-6 Path-independent rate mechanics** (the rate change is measured from origination to the
  date).
- **I-7 Equal city weights.** Each loan gets a random RBI HPI city with equal weights, not the
  lending mix. (The LTV caps and the GNPA target are now verified: para 111 and FSR Chart 2.3 b.)
- **I-8 Replicated delinquent loans** (k = 1.64; 2,848 copies) share every attribute with their
  originals.
- **I-9 CPI April-May 2020** are MoSPI imputations (status F*); they fall in the excluded COVID
  window.
