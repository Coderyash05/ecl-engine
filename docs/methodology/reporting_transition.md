# Annex 4 reporting, old-rules provision and transition (report-0.1.0)

Annex 4 disclosure tables, the old-rules (IRACP 2025) provision and the ECL transition with the CET1
add-back schedule. Code: `src/ecl/reporting/{annex4,iracp}.py` (`ecl report`). Old-rules values:
`config/rbi_iracp_2025.yaml`; transition fractions: `config/rbi_2026.yaml` (`transition`). Outputs:
`reports/summary/annex4/` (one CSV per table with a header, one Markdown file per date). Development
log: `models/reporting/CHANGELOG.md`. US data, US dollars where the Annex 4 formats use Rs crore; not
Indian risk estimates.

## Dates

- **2026-03-31: dry-run first-application date.** ACPIR para 107 uses the balance sheet of
  2027-03-31; the data end in 2026. The previous year, 2025-03-31, is run with the same engine (SPF
  2025Q1, SEP March 2025, macro history cut at 2025Q1).
- 2023-03-31: comparison date (no 2022 run, so no previous-year columns and no Table 3).

## Annex 4 tables

| Table | Content and mapping |
|---|---|
| 1.A | Gross carrying amount (EAD now) by DPD bucket x stage, allowance, net; per product category. Status 00 / not reported -> "Current / 1-30"; 01 -> 31-60; 02 -> 61-90; 03+ / REO -> 90+ (monthly status cannot split day 30 / 60 / 90). Tables 1.B / 1.C (investments, commitments) not applicable |
| 2 | Gross, ECL allowance, net by stage, current and previous year |
| 3.A | Loan-level roll from 2025-03-31 to 2026-03-31: transfers between stages at opening amounts; net remeasurement; new assets; matured or repaid (non-loss zero balance); write-offs (loss-type codes 02, 03, 09, 15); other. The closing line is checked against the closing data |
| 4 | PD-TTC (EAD-weighted) by stage, LGD and approach |
| 5 | Macro assumptions: 1-year forward and 5-year average, three scenarios ([scenarios](scenarios.md)) |
| 6 | Allowance before / after the post-model adjustments CO-3 (PD) and CO-5 (LGD); memo lines with model ECL before floors |
| 7 | Forward-looking PD (Stage 1 12-month, Stage 2 lifetime, Stage 3 100%) and LGD, EAD-weighted |
| 8 | SICR criteria per category (loan level, no segments); supplement: stage rule by region |
| 9 | Transitional adjustment by stage = ECL allowance - IRACP provision on that stage's loans |
| Manual overrides | Approved stage overrides with the system stage next to the overridden one ([governance](governance.md)) |

Loss allowance = final provision after the floors; a Stage 1-2 portfolio floor uplift is allocated to
loans pro rata to exposure (presentation only).

## Old rules (IRACP 2025)

- **NPA population** = ECL Stage 3: default until arrears are cleared (IRACP 69); restructured until
  the RSA monitoring period is met (RSA 52-62); calamity resolutions stay standard (62A / 62B). Age as
  NPA = the unbroken Stage 3 spell (RSA 53-54).
- **Rates:** standard 0.25%; substandard (<= 12 months) 15% (25% if the unsecured exposure has
  realisable value <= 10%); doubtful (after 12 months) unsecured portion 100%, secured portion 25 /
  40 / 100% for < 1 / 1-3 / >= 3 years in doubtful; loss (realisable value < 10%) 100%.
- **Additional provisions:** 5% per Chapter VI-A resolution (84A / 84B), written back after 20%
  repaid without a miss (84C); 15% for accounts blocked under RSA 61 / 62 (RSA 64); ceiling 100%.
- Outstanding = EAD now; realisable value = secured portion. IRACP 68(1) (erosion of more than 50%
  against the last assessed value) is not applied: the data have no last assessed value.

## Transition (ACPIR paras 107-108)

Impact = max(0, ECL allowance - IRACP provision) on the dry-run date; CET1 add-back of at most 4/5,
3/5, 2/5 and 1/5 of the impact in FY 2027-28 to 2030-31. The Directions apply the fractions to the
amount net of applicable taxes; no tax rate is modelled, so the schedule is labelled pre-tax.

**Result (2026-03-31):** ECL allowance 1,229.9m < IRACP provision 1,281.7m, so the impact is 0 and
there is no add-back (2023-03-31: 767.2m < 851.1m).

**Old rules vs ECL by segment** (table `old_vs_ecl`): on base rates alone, ECL is 50.5m above IRACP;
the IRACP additional provisions (RSA 64 15% on accounts blocked under RSA 61 / 62: 58.3m; 84A / 84B
5%: 43.9m) make IRACP 51.8m higher. Both rule sets read the same loan-level flags. Without RSA 64 the
impact would be +6.5m: the sign of the transition depends on the add-ons (limitation R-8, finding
M-2).

## Limitations

R-1 to R-8 (dry-run date, pre-tax add-back, tables not applicable, DPD buckets, IRACP data proxies,
write-off proxy, no 2022 run, transition sign depends on RSA 64 / 84A). Register:
[docs/limitations.md](../limitations.md).
