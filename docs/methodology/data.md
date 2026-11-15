# Data: loan-month panel and PD modelling dataset

Code: `src/ecl/data/panel.py` (`ecl build-panel`), `src/ecl/data/hpi.py`, `src/ecl/pd/dataset.py`
(`ecl build-pd-dataset`). Layout: `config/freddie_layout.yaml`. QC tables: `reports/summary/qc_by_vintage.csv`,
`first_defaults_by_year.csv`, `pd_dataset_*.csv`.

## Source

Freddie Mac Single-Family Loan-Level Dataset, sample files, Release 47 layout: 56 files
(`sample_orig_YYYY.txt` / `sample_perf_YYYY.txt`, vintages 1999-2026), pipe-delimited without a
header, 31 origination and 35 performance columns. **The data are not in this repository and are not
redistributed;** users download them from Freddie Mac under its terms.

Every line of every file is checked against the configured column count before anything loads; the
build runs one vintage at a time (memory bounded by the largest vintage) into
`data/processed/{loans,panel}/vintage=YYYY/data.parquet`, with DuckDB views `loans_all` and
`panel_all`. Result: 1,375,000 loans and 76.0m loan-months; no orphan loans and no duplicate
loan-months.

## Definitions

- **Default (RBI, paras 6(5), 8(1)):** more than 90 days overdue on a term loan. Monthly data cannot
  separate day 90 from day 91, so delinquency status 03 (90-119 days) or REO (`RA`) is the documented
  proxy. Loss-type terminations (zero balance codes 02, 03, 09, 15) also count. This definition drives
  staging and Stage 3.
- **PD training target B-18 (modelling choice, not the regulatory definition):** a default month is
  relabelled as non-default if the loan was under relief that month (forbearance, deferral, disaster),
  is back to current within 18 months and has no loss-type termination in that window. Relief fields
  exist only from 2014, so before 2014 B-18 equals the RBI definition and crisis-era forbearance
  counts as default (conservative). B-12 and the RBI definition are sensitivities.
- **Relief months** (2020-21 forbearance, deferral, disaster) are flagged, never dropped.

## Current LTV

`current_ltv = 100 x current_upb / (orig_upb / (orig_ltv / 100) x HPI(t) / HPI(origination quarter))`,
with the FHFA All-Transactions state index (quarterly, not seasonally adjusted). One consistent
current LTV feeds the PD, the Stage 2 trigger and the LGD collateral value. The origination quarter is
the quarter of (first payment date - 1 month), which agrees with period - loan age for 99.995% of
loans. Loans in states without an index (PR, GU, VI; 2,332 loans) keep a missing current LTV, flagged
`hpi_fallback`; the WoE missing bin handles them. This is a US index, not an Indian HPI.

## PD modelling dataset

Quarterly snapshots of loans not in default, with targets `target_b18` (primary), `target_b12` and
`target_a` (RBI definition) = default within the next 12 months. The last fully labelled snapshot is
data end minus 30 months (2023-12). Splits by observation date: development 2000-2016 (80/20
loan-level holdout by a seeded hash), out of time OOT1 2017-19, OOT2 2020-21 (COVID), OOT3 2022-23.
20.9m snapshots, 1.24m loans; B-18 12-month default rate: development 1.24%, OOT1 0.49%, OOT2 0.37%,
OOT3 0.45%.

Missing DTI: every HARP loan has a missing DTI, and some non-HARP loans do too; missing DTI is its own
WoE bin, the HARP flag is a separate feature, and DTI is never imputed for HARP loans.
