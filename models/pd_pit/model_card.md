# Model card: PIT conversion of the 12-month PD (pdpit-0.2.1)

**Code version.** git commit `424af508bb1265bfd5c040b5030b7788546640ae` (code and regulatory config committed); fitted 2026-11-15.
TTC input: `pd12m-1.2.0`. Methodology: `docs/methodology/pd_point_in_time.md`. Development log:
`models/pd_pit/CHANGELOG.md`.

**US data.** Freddie Mac loans and US macro series (FRED). Not Indian risk estimates.

**What it does.** A credit-cycle index Z_t (Z > 0 benign) is measured each quarter from the
realised 12-month B-18 defaults given each loan's TTC PD (Vasicek single factor). A satellite
regression links Z_t to macro drivers averaged over the 12-month outcome window, so scenarios
can move the PD (RBI paras 47-49). The same Z drives the default hazard of the lifetime PD.

**Asset correlation rho = 0.15**: Basel residential-mortgage benchmark; not identifiable from this data; chosen by the backtest by delinquency group (Yash, 2026-11-13). The profile likelihood runs to the
edge of the grid (rho_hat 0.01, not an interior estimate); unit variance of
Z would need rho 0.026. 0.10 and 0.20 are reported as sensitivities.
Z_t is therefore not N(0, 1): long-run Z = -0.207 (the satellite at the
2000-2016 driver means).

**Satellite (final, window-aligned)**, estimated 2000Q1-2016Q4:
Z_hat = -0.5456 +0.0438 x hpi_yoy[W] +0.0946 x gdp_yoy[W]; R² 0.772; residual sd 0.183.
Driver rule (expected sign, |HAC t| >= 2; core drivers named ex ante may not worsen the OOT
error by more than 5%, optional additions must improve it by >= 5%): final drivers pass =
**True**. The Fed funds change is reported
as a sensitivity only. **OOT1-OOT3 (2017-2023) have been used for driver selection, so they are
not a fully clean test period.**

**Crisis peak:** predicted 2.74% in 2008Q4 vs actual
3.33% in 2009Q1.

## Driver rule
| specification | driver | role | sign_ok | t_hac | err_with | err_without | error_reduction | out_of_sample_ok | passes |
|---|---|---|---|---|---|---|---|---|---|
| hpi_yoy + gdp_yoy + ff_chg4 | hpi_yoy | core (ex ante) | True | 4.1269 | 0.1663 | 0.2644 | 0.3709 | True | True |
| hpi_yoy + gdp_yoy + ff_chg4 | gdp_yoy | core (ex ante) | True | 3.1159 | 0.1663 | 0.1762 | 0.0559 | True | True |
| hpi_yoy + gdp_yoy + ff_chg4 | ff_chg4 | optional | True | -1.0218 | 0.1663 | 0.1758 | 0.0539 | True | False |
| hpi_yoy + gdp_yoy | hpi_yoy | core (ex ante) | True | 3.9722 | 0.1758 | 0.2390 | 0.2644 | True | True |
| hpi_yoy + gdp_yoy | gdp_yoy | core (ex ante) | True | 3.7123 | 0.1758 | 0.1762 | 0.0022 | True | True |

## Coefficients
| term | coef_2000_2016 | t_hac | coef_2000_2012 | coef_ar_challenger | expected_sign |
|---|---|---|---|---|---|
| const | -0.5456 | -8.1657 | -0.5869 | -0.4305 |  |
| hpi_yoy[W] | 0.0438 | 3.9722 | 0.0399 | 0.0144 | + |
| gdp_yoy[W] | 0.0946 | 3.7123 | 0.0977 | 0.1341 | + |
| z_lag4 (AR challenger) | nan | 3.7254 | nan | 0.4337 |  |

## Reported specifications (rho = 0.15)
| rho | variant | alignment | spec | dropped_wrong_sign | r2 | bic | sigma | nobs | err_dev | err_oot1 | err_oot2 | err_oot3 | err_oot13 | peak_actual | peak_pred | peak_actual_rate | peak_pred_rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.1500 | final: W house prices + GDP | W | +0.044*hpi_yoy[W] + +0.095*gdp_yoy[W] |  | 0.7721 | -28.0460 | 0.1835 | 68 | 0.1257 | 0.2010 | 0.3182 | 0.1380 | 0.1758 | 2009Q1 | 2008Q4 | 0.0333 | 0.0274 |
| 0.1500 | sensitivity: W + Fed funds change | W | +0.044*hpi_yoy[W] + +0.117*gdp_yoy[W] + -0.034*ff_chg4[W] |  | 0.7794 | -26.0527 | 0.1819 | 68 | 0.1234 | 0.2123 | 0.3094 | 0.0974 | 0.1663 | 2009Q1 | 2008Q4 | 0.0333 | 0.0283 |
| 0.1500 | alternative: L (lags t, t-4) | L | +0.044*hpi_yoy[t] + +0.068*gdp_yoy[t] |  | 0.6938 | -7.9586 | 0.2127 | 68 | 0.1421 | 0.1838 | 0.6904 | 0.2760 | 0.2207 | 2009Q1 | 2009Q3 | 0.0333 | 0.0313 |
| 0.1500 | challenger: W house prices + unemployment | W | +0.045*hpi_yoy[W] + -0.161*unrate_chg4[W] |  | 0.8630 | -62.6499 | 0.1423 | 68 | 0.0898 | 0.2569 | 0.4857 | 0.1186 | 0.2016 | 2009Q1 | 2008Q4 | 0.0333 | 0.0300 |

## Correlation sensitivity (final satellite refitted for each rho)
| rho | role | worst_group_mean_abs_log | a_to_p_oot13[30-89 dpd] | a_to_p_oot13[cured] | a_to_p_oot13[never 30+ dpd] | groups_within_tolerance | z_mean_dev | z_var_dev | satellite | sat_err_oot13 | mean_pit_2009 | mean_pit_2018 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.1000 | sensitivity | 0.1451 | 1.0397 | 1.2467 | 0.8616 | True | -0.0897 | 0.2276 | +0.056*hpi_yoy[W] + +0.115*gdp_yoy[W] | 0.1738 | 0.0241 | 0.0053 |
| 0.1500 | model | 0.1394 | 0.9870 | 1.2208 | 0.8857 | True | -0.2152 | 0.1433 | +0.044*hpi_yoy[W] + +0.095*gdp_yoy[W] | 0.1758 | 0.0244 | 0.0052 |
| 0.2000 | sensitivity | 0.1477 | 0.9351 | 1.1937 | 0.9134 | True | -0.3118 | 0.1014 | +0.036*hpi_yoy[W] + +0.083*gdp_yoy[W] | 0.1778 | 0.0246 | 0.0052 |

## Backtest by period (satellite Z with realised macro), with and without the 0.03% floor
`pit_pd` is the model; `pit_pd_floored` applies the 12-month PD floor (para 96) per cell;
`floor_effect` = floored / unfloored - 1. `actual_to_pit` measures model error;
`actual_to_pit_floored` adds the effect of the floor.

| period | quarters | actual_rate | ttc_pd | pit_pd | pit_pd_floored | z_measured | z_satellite | share_inside_band | floor_binds_share | actual_rate_target_a | actual_to_ttc | actual_to_pit | actual_to_pit_floored | floor_effect |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pre-crisis | 28 | 0.0075 | 0.0100 | 0.0073 | 0.0073 | -0.0377 | 0.0224 | 0.8929 | 0.0715 | 0.0075 | 0.7478 | 1.0215 | 1.0205 | 0.0010 |
| crisis | 20 | 0.0209 | 0.0161 | 0.0198 | 0.0198 | -0.6968 | -0.6346 | 0.8500 | 0.0065 | 0.0209 | 1.2952 | 1.0553 | 1.0552 | 0.0000 |
| recovery | 20 | 0.0075 | 0.0104 | 0.0086 | 0.0086 | 0.0181 | -0.1284 | 0.9000 | 0.0526 | 0.0076 | 0.7183 | 0.8685 | 0.8680 | 0.0005 |
| benign (OOT1) | 12 | 0.0049 | 0.0072 | 0.0057 | 0.0057 | 0.0034 | -0.1549 | 0.6667 | 0.0477 | 0.0113 | 0.6769 | 0.8583 | 0.8577 | 0.0006 |
| COVID (OOT2) | 8 | 0.0036 | 0.0080 | 0.0047 | 0.0047 | 0.4791 | 0.3959 | 0.6250 | 0.2557 | 0.0130 | 0.4480 | 0.7693 | 0.7635 | 0.0075 |
| 2022-23 (OOT3) | 8 | 0.0045 | 0.0059 | 0.0039 | 0.0039 | -0.1296 | 0.0193 | 1.0000 | 0.1131 | 0.0054 | 0.7546 | 1.1514 | 1.1483 | 0.0027 |

## Backtest by segment and period
| z | segment | period | n | defaults | actual_rate | pred_rate | actual_to_pred |
|---|---|---|---|---|---|---|---|
| measured | 30-89 dpd | pre-crisis | 43838 | 10165 | 0.2319 | 0.2560 | 0.9056 |
| measured | cured | pre-crisis | 197396 | 5446 | 0.0276 | 0.0251 | 1.1013 |
| measured | never 30+ dpd | pre-crisis | 3093358 | 8976 | 0.0029 | 0.0028 | 1.0277 |
| measured | 30-89 dpd | crisis | 84604 | 34943 | 0.4130 | 0.4595 | 0.8989 |
| measured | cured | crisis | 376152 | 18481 | 0.0491 | 0.0543 | 0.9054 |
| measured | never 30+ dpd | crisis | 4213081 | 45513 | 0.0108 | 0.0097 | 1.1114 |
| measured | 30-89 dpd | recovery | 53401 | 14712 | 0.2755 | 0.2917 | 0.9444 |
| measured | cured | recovery | 384578 | 8616 | 0.0224 | 0.0222 | 1.0101 |
| measured | never 30+ dpd | recovery | 4496517 | 12873 | 0.0029 | 0.0030 | 0.9672 |
| measured | 30-89 dpd | benign (OOT1) | 31203 | 6239 | 0.1999 | 0.2081 | 0.9607 |
| measured | cured | benign (OOT1) | 256014 | 4178 | 0.0163 | 0.0132 | 1.2356 |
| measured | never 30+ dpd | benign (OOT1) | 3325334 | 7196 | 0.0022 | 0.0024 | 0.8900 |
| measured | 30-89 dpd | COVID (OOT2) | 25474 | 2991 | 0.1174 | 0.1871 | 0.6275 |
| measured | cured | COVID (OOT2) | 221144 | 2009 | 0.0091 | 0.0081 | 1.1187 |
| measured | never 30+ dpd | COVID (OOT2) | 1921532 | 2985 | 0.0016 | 0.0013 | 1.1686 |
| measured | 30-89 dpd | 2022-23 (OOT3) | 18327 | 3616 | 0.1973 | 0.1904 | 1.0360 |
| measured | cured | 2022-23 (OOT3) | 237266 | 2476 | 0.0104 | 0.0087 | 1.1966 |
| measured | never 30+ dpd | 2022-23 (OOT3) | 1908258 | 3674 | 0.0019 | 0.0022 | 0.8775 |
| measured | other states | pre-crisis | 2668515 | 21182 | 0.0079 | 0.0079 | 1.0094 |
| measured | CA/FL/NV/AZ | pre-crisis | 666077 | 3405 | 0.0051 | 0.0059 | 0.8688 |
| measured | other states | crisis | 3797918 | 67430 | 0.0178 | 0.0200 | 0.8889 |
| measured | CA/FL/NV/AZ | crisis | 875919 | 31507 | 0.0360 | 0.0278 | 1.2924 |
| measured | other states | recovery | 3928193 | 28722 | 0.0073 | 0.0075 | 0.9731 |
| measured | CA/FL/NV/AZ | recovery | 1006303 | 7479 | 0.0074 | 0.0079 | 0.9465 |
| measured | other states | benign (OOT1) | 2828687 | 13771 | 0.0049 | 0.0051 | 0.9596 |
| measured | CA/FL/NV/AZ | benign (OOT1) | 783864 | 3842 | 0.0049 | 0.0046 | 1.0643 |
| measured | other states | COVID (OOT2) | 1705440 | 6393 | 0.0037 | 0.0042 | 0.8907 |
| measured | CA/FL/NV/AZ | COVID (OOT2) | 462710 | 1592 | 0.0034 | 0.0042 | 0.8210 |
| measured | other states | 2022-23 (OOT3) | 1701791 | 7686 | 0.0045 | 0.0046 | 0.9872 |
| measured | CA/FL/NV/AZ | 2022-23 (OOT3) | 462060 | 2080 | 0.0045 | 0.0042 | 1.0609 |
| satellite | 30-89 dpd | pre-crisis | 43838 | 10165 | 0.2319 | 0.2520 | 0.9200 |
| satellite | cured | pre-crisis | 197396 | 5446 | 0.0276 | 0.0242 | 1.1418 |
| satellite | never 30+ dpd | pre-crisis | 3093358 | 8976 | 0.0029 | 0.0027 | 1.0625 |
| satellite | 30-89 dpd | crisis | 84604 | 34943 | 0.4130 | 0.4474 | 0.9232 |
| satellite | cured | crisis | 376152 | 18481 | 0.0491 | 0.0508 | 0.9666 |
| satellite | never 30+ dpd | crisis | 4213081 | 45513 | 0.0108 | 0.0087 | 1.2450 |
| satellite | 30-89 dpd | recovery | 53401 | 14712 | 0.2755 | 0.3074 | 0.8962 |
| satellite | cured | recovery | 384578 | 8616 | 0.0224 | 0.0249 | 0.9003 |
| satellite | never 30+ dpd | recovery | 4496517 | 12873 | 0.0029 | 0.0035 | 0.8170 |
| satellite | 30-89 dpd | benign (OOT1) | 31203 | 6239 | 0.1999 | 0.2245 | 0.8907 |
| satellite | cured | benign (OOT1) | 256014 | 4178 | 0.0163 | 0.0152 | 1.0726 |
| satellite | never 30+ dpd | benign (OOT1) | 3325334 | 7196 | 0.0022 | 0.0029 | 0.7414 |
| satellite | 30-89 dpd | COVID (OOT2) | 25474 | 2991 | 0.1174 | 0.2280 | 0.5150 |
| satellite | cured | COVID (OOT2) | 221144 | 2009 | 0.0091 | 0.0087 | 1.0432 |
| satellite | never 30+ dpd | COVID (OOT2) | 1921532 | 2985 | 0.0016 | 0.0015 | 1.0415 |
| satellite | 30-89 dpd | 2022-23 (OOT3) | 18327 | 3616 | 0.1973 | 0.1771 | 1.1139 |
| satellite | cured | 2022-23 (OOT3) | 237266 | 2476 | 0.0104 | 0.0075 | 1.3974 |
| satellite | never 30+ dpd | 2022-23 (OOT3) | 1908258 | 3674 | 0.0019 | 0.0018 | 1.0648 |
| satellite | other states | pre-crisis | 2668515 | 21182 | 0.0079 | 0.0077 | 1.0359 |
| satellite | CA/FL/NV/AZ | pre-crisis | 666077 | 3405 | 0.0051 | 0.0057 | 0.8916 |
| satellite | other states | crisis | 3797918 | 67430 | 0.0178 | 0.0186 | 0.9533 |
| satellite | CA/FL/NV/AZ | crisis | 875919 | 31507 | 0.0360 | 0.0260 | 1.3822 |
| satellite | other states | recovery | 3928193 | 28722 | 0.0073 | 0.0084 | 0.8716 |
| satellite | CA/FL/NV/AZ | recovery | 1006303 | 7479 | 0.0074 | 0.0087 | 0.8511 |
| satellite | other states | benign (OOT1) | 2828687 | 13771 | 0.0049 | 0.0058 | 0.8370 |
| satellite | CA/FL/NV/AZ | benign (OOT1) | 783864 | 3842 | 0.0049 | 0.0053 | 0.9250 |
| satellite | other states | COVID (OOT2) | 1705440 | 6393 | 0.0037 | 0.0049 | 0.7703 |
| satellite | CA/FL/NV/AZ | COVID (OOT2) | 462710 | 1592 | 0.0034 | 0.0050 | 0.6920 |
| satellite | other states | 2022-23 (OOT3) | 1701791 | 7686 | 0.0045 | 0.0040 | 1.1357 |
| satellite | CA/FL/NV/AZ | 2022-23 (OOT3) | 462060 | 2080 | 0.0045 | 0.0037 | 1.2229 |

## Stationarity (ADF p < 0.05 and KPSS p > 0.05 = stationary)
| series | n | adf_p | kpss_p | reading |
|---|---|---|---|---|
| z_measured (dev) | 68 | 0.2237 | 0.1000 | inconclusive |
| satellite residual (dev) | 68 | 0.0203 | 0.0732 | stationary |
| hpi_yoy[W] (dev) | 68 | 0.2651 | 0.1000 | inconclusive |
| gdp_yoy[W] (dev) | 68 | 0.1698 | 0.1000 | inconclusive |
| hpi_yoy, 1990-2026 | 146 | 0.0957 | 0.1000 | inconclusive |
| gdp_yoy, 1990-2026 | 146 | 0.0452 | 0.1000 | stationary |
| ff_chg4, 1990-2026 | 146 | 0.0000 | 0.1000 | stationary |
| unrate_chg4, 1990-2026 | 146 | 0.0032 | 0.1000 | stationary |

## Macro data QC
| series | column | frequency | first | last | quarters | short_or_gappy_quarters | missing_values |
|---|---|---|---|---|---|---|---|
| USSTHPI | hpi | Q | 1975Q1 | 2026Q2 | 206 |  | 0 |
| A191RL1Q225SBEA | gdp_qoq_saar | Q | 1947Q2 | 2026Q3 | 318 |  | 0 |
| MORTGAGE30US | mortgage30 | W | 1971Q2 | 2026Q3 | 222 | 2026Q4 (7/7) | 0 |
| UNRATE | unrate | M | 1948Q1 | 2026Q3 | 315 | 2025Q4 (2/3); 2026Q4 (1/1) | 1 |
| FEDFUNDS | fedfunds | M | 1954Q3 | 2026Q3 | 289 | 2026Q4 (1/1) | 0 |
