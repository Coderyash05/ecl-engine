# CHANGELOG - Module 10: Annex 4 reports, old-rules provision, ECL transition

US data (Freddie Mac sample, FHFA, FRED, SPF, SEP). **Not Indian risk estimates**; amounts in US
dollars (the Annex 4 formats use Rs crore). Methodology `docs/methodology/reporting_transition.md`; code
`src/ecl/reporting/{annex4,iracp}.py`; command `ecl report` (~10 s after the ECL run);
old-rules values `config/rbi_iracp_2025.yaml` (quoted from the IRACP 2025 and RSA 2025 PDFs).

## report-0.1.0 (report code `679b83a`; ECL run `70e66da`, clean tree, 2026-11-14)

Outputs `reports/summary/annex4/`: `annex4_t{1..9}_{date}.csv` (header lines: reporting date,
US-data note, config versions, ECL-run and report git hashes), `annex4_old_rules_*`,
`annex4_transition_*`, one Markdown file per date, `annex4_summary.json`.

### Opening balance 2025-03-31 (new run for Table 3)
SPF 2025Q1 and the SEP of 19 March 2025 (Table 1 medians GDP 1.7 / 1.8 / 1.8, LR 1.8;
unemployment 4.4 / 4.3 / 4.3, LR 4.2; fed funds 3.9 / 3.4 / 3.1, LR 3.0; PDF fetched from
federalreserve.gov to `data/macro/SEP March 2025.pdf`, values read from the PDF and checked by
the pipeline). Model ECL 136.4m, provision **1,125.9m** (1.46% of 77.0bn).

### Table 3.A loss-allowance reconciliation 2025-03-31 -> 2026-03-31 (ECL, m)
| | Stage 1 | Stage 2 | Stage 3 | Total |
|---|---|---|---|---|
| Opening | 223.4 | 45.2 | 857.3 | 1,125.9 |
| Transfer to Stage 1 | +22.4 | -17.2 | -5.2 | 0 |
| Transfer to Stage 2 | -4.2 | +38.4 | -34.2 | 0 |
| Transfer to Stage 3 | -1.7 | -9.8 | +11.4 | 0 |
| Net remeasurement | -27.3 | -15.9 | +213.7 | +170.4 |
| New loans | +41.7 | +6.0 | +2.1 | +49.8 |
| Matured or repaid | -21.9 | -4.3 | -68.0 | -94.2 |
| Write-offs (loss-type terminations) | 0.0 | -0.1 | -21.8 | -21.9 |
| **Closing** | **232.4** | **42.3** | **955.3** | **1,229.9** |

The closing line matches the closing data (difference < $0.01); no unexplained population
changes. Stage 3 remeasurement +214m: loans ageing into higher floor bands (duration in Stage 3).

### Old rules and transition (dry-run first-application date 2026-03-31)
| (m) | 2026-03 ECL | 2026-03 IRACP | 2023-03 ECL | 2023-03 IRACP |
|---|---|---|---|---|
| Stage 1 (standard) | 232.4 | 232.4 | 184.7 | 189.1 |
| Stage 2 (standard) | 42.3 | 7.4 | 25.1 | 6.6 |
| Stage 3 (NPA) | 955.3 | 1,041.9 | 557.3 | 655.4 |
| **Total** | **1,229.9** | **1,281.7** | **767.2** | **851.1** |

- IRACP Stage 3 by class (2026): substandard 2,299 loans 104.7m; doubtful D1 1,297 / 171.1m,
  D2 1,151 / 167.0m, D3 2,877 / 592.1m; loss 69 / 7.0m. Additional: 84A / 84B calamity 5% and
  RSA 64 15% (blocked restructured loans) 102.2m in all.
- **Transition impact = max(0, 1,229.9 - 1,281.7) = 0**: the ECL is 51.8m (2023: 84.0m) below
  the old-rules provision, so no CET1 add-back (schedule 4/5, 3/5, 2/5, 1/5 of 0); under para
  110 the release could go directly to retained earnings. Table 9: Stage 1 +0.0m, Stage 2
  +34.9m, Stage 3 -86.7m.
- Why ECL < IRACP here: the housing Stage 3 floors (10/25, 20/100, ...) are below the IRACP NPA
  rates in years 0-2 (substandard 15%; doubtful unsecured 100% + 25% secured), and RSA 64 adds
  15% on 2,885 blocked restructured loans; the low US model ECL is floored in Stages 1 and 3, so
  only Stage 2 (lifetime ECL vs 0.25%) is higher under ECL. With the RBI fallback LGD the ECL
  (1,765.0m) would exceed IRACP by 483m.

### Sanity check: old rules vs ECL by segment (2026-03-31; `annex4_old_vs_ecl_{date}.csv`)
Report code adds `old_vs_ecl_by_segment` (IRACP split into base rate and additional provisions).

| Segment (m) | Loans | Outstanding | ECL | IRACP base | IRACP additional | ECL - IRACP |
|---|---|---|---|---|---|---|
| Stage 1 | 329,153 | 77,757.5 | 194.4 | 194.4 | 0.1 | -0.1 |
| Stage 2 | 7,900 | 1,904.7 | 37.6 | 4.8 | 0.1 | **+32.8** |
| Stage 3 non-restructured (default / arrears) | 2,355 | 604.8 | 193.8 | 200.3 | 20.4 | -26.8 |
| Stage 3 restructured - modification | 3,390 | 781.1 | 549.5 | 561.3 | 20.9 | -32.8 |
| Stage 3 restructured - general deferral | 1,853 | 432.9 | 204.7 | 212.1 | 21.2 | -28.7 |
| Calamity route (xiv), all stages | 4,290 | 826.0 | 49.9 | 6.7 | 39.4 | +3.9 |
| **Total** | 348,941 | 82,306.9 | **1,229.9** | **1,179.5** | **102.2** | **-51.8** |

Stage 3 by years as NPA (all non-calamity Stage 3; ECL - IRACP, m): 0-1 -15.9, 1-2 -30.7,
2-3 -33.5, 3-4 -8.2, 4+ 0.0.

Rules behind each difference:
- **Stage 2 (+32.8m):** ECL = lifetime ECL, at least the 1.50% housing floor at portfolio level
  (ACPIR 25(2), 82(4)(xi)(a), 90; 2.0% after floors) vs a standard asset at 0.25% (IRACP 80(1)).
- **Stage 3 base rates (-25.6m in all):** ACPIR 82(5) housing table vs IRACP 85 / 90 / 91. In
  year 0-1 a 10% secured / 25% unsecured floor (12.4% on this mix, 16% unsecured) vs a flat 15%
  substandard rate; in years 1-2 20% secured vs 25% (D1); in years 2-3 30% vs 40% (D2); in years
  3-4 both 40% / 100%; after 4 years both 100% (D3 after 3 years as doubtful = 4 years as NPA).
  The model ECL is above the floor for only a few loans.
- **Stage 3 additional (-62.5m):** RSA 64, 15% on accounts that failed the monitoring period
  (RSA 61 / 62), 3,520 accounts, 58.3m, plus 84A / 84B 5% on NPA accounts with a calamity
  resolution. The ECL Directions have no add-on: the same accounts carry the 82(5) floor only.
- **Calamity route (+3.9m):** ACPIR 82(4)(xiv) 5% / 10% floors (Stage 3: 25/40 ...) vs 0.25%
  standard plus 84A / 84B 5% per resolution (written back after 20% repaid, 84C). Both rule sets
  give about 5% here.

**Mapping check - no inconsistency found.** Both sides use the same loan-level flags: NPA =
ECL Stage 3 (IRACP 69 / RSA 52-62 vs ACPIR 8(10), 78, 80); age as NPA = unbroken Stage 3 spell
(RSA 53-54 vs ACPIR 82(5)); calamity resolutions standard on both sides (IRACP 62A / 62B vs
ACPIR 82(4)(xiv)); RSA 64 on the accounts blocked under RSA 61 / 62 on the ECL side. RSA 64
checked against the text: it is in Chapter V, which applies to all restructurings (RSA 51); the
"Review Period" is 30 days from default (RSA 6(13)); the add-on is reversed per RSA 50 (66), i.e.
on implementation of a fresh restructuring (50(2)), which matches the blocked flag. Applied
15% from the miss, not 30 days later (immaterial). No re-run needed.

**Finding (recorded, R-8): the sign of the transition depends on the additional provisions.**
On base rates alone the ECL is 50.5m **above** IRACP (Stage 2 +32.9m, calamity route +43.3m,
Stage 3 -25.6m); the 102.2m of IRACP additional provisions (RSA 64 58.3m, 84A / 84B 43.9m) turn it
into -51.8m. Without RSA 64 the dry-run impact would be +6.5m (2023: still 0, IRACP 812.5m vs
767.2m). 2,067 of the 3,520 blocked accounts are currently paying (status 00): a reading of
RSA 50(1) (reversal six months after clearing overdues) would remove part of the 58.3m. The
primary keeps the text reading (blocked until a fresh restructuring). Monitoring trigger: for
the real first application, recompute the impact with the bank's actual RSA 64 / 84A balances;
if |ECL - IRACP| < 10% of the IRACP additional provisions, report both readings.

### Limitations
- R-1 Dry run: the Directions use the balance sheet of 2027-03-31; 2026-03-31 is a dry run.
- R-2 Add-back fractions are applied pre-tax ("net of applicable taxes": no tax rate modelled).
- R-3 Retained earnings (Table 9) and investments / commitments (Tables 1.B, 1.C, 3.B) n/a.
- R-4 DPD buckets from monthly status (00 = current and 1-29 days; 01 = 30-59 for "31-60").
- R-5 Old rules: outstanding = EAD now; realisable value = secured portion; IRACP 68(1) erosion
  test not applied; 84C write-back requires no 30+ miss (stricter than "not slipping into NPA").
- R-6 Table 3 "write-offs" = derecognition at loss-type zero-balance codes (02, 03, 09, 15);
  partial write-offs are not observable.
- R-7 2023-03-31: no 2022 run, so no previous-year columns or Table 3.
- R-8 The transition sign depends on the IRACP additional provisions (RSA 64, 84A / 84B):
  base rates alone give ECL > IRACP by 50.5m (2026); see the segment check above.
