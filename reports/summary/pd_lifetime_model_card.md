# Model card: lifetime PD, competing-risk hazard (pdlife-0.4.0) — for review

**Code version.** git commit `424af508bb1265bfd5c040b5030b7788546640ae` (code and regulatory config committed); fitted 2026-11-15.
Inputs: TTC `pd12m-1.2.0`, PIT `pdpit-0.2.1` (rho 0.15).
Methodology: `docs/methodology/pd_lifetime.md`. Development log: `models/pd_lifetime/CHANGELOG.md`.
**US data — not Indian risk estimates.**

Quarterly multinomial logit (default / prepay / survive) from a 1-in-16 hash sample of PD
snapshots as reference dates, fitted on dev_train references 2000-2016; outcomes to
2024-12. Lifetime PD = cumulative incidence of default to contractual maturity
with prepayment as a competing risk (paras 46(1), 51). Year 1 is spliced to the 12-month PIT PD.
Every later year's conditional annual PD is floored at 0.03%
(config `pd.floor_lifetime_annual`, `rbi_specified: false`: para 96 sets the floor on "the
12-month PD"; extending it to later years is an interpretation).

**Specification chosen:** {'default_incentive': 'ge1', 'prepay_ramp': 'both', 'dlq_decay': 'state'} — stage A: all periods' year-1 hazard/PIT within tolerance, then the lowest vintage default error; stage B:
dev_train log-likelihood not below the stage-A choice, then the lowest vintage prepayment error (years 1-3); stage C: state-specific delinquency decay in the default equation (owner decision 2026-11-13); shared fade reported; stage D:
D2 (incentive x age 2-5y) adopted only if it moves the 2012-16 vintage lifetime PD at origination or the 2023-12 lifetime PD by > 5% vs D1 and does not lower the dev_train log-likelihood (D2 material: False, adopted:
False).

The forward-looking path is **illustrative** (published macro, then linear reversion over
8 quarters to the 2000-2016 means); Module 4 supplies the scenarios.

## Specification comparison
| stage | variant | default_incentive | prepay_ramp | dlq_decay | terms | loglik_dev_train | loglik_dev_holdout | loglik_oot | y1_hazard_to_pit[2000-06] | y1_hazard_to_pit[2012-16] | y1_hazard_to_pit[2017-19] | y1_hazard_to_pit[2022-23] | y1_hazard_to_pit[COVID 2020-21] | y1_hazard_to_pit[crisis 2007-11] | y1_all_within_tolerance | y1_max_abs_log | vintage_default_error | vintage_prepay_error_y1_3 | prepay_y1_2012_16_actual | prepay_y1_2012_16_pred | lifetime_pd_2023_12_sample | jump_flags_dlq_state | jump_flags_ttc_decile | jump_max_abs_log | loans_2012_16 | lifetime_pd_2012_16_at_orig | prepay_y1_2012_16_actual_to_pred | default_y1_2012_16_actual_to_pred | prepay_y3_2012_16_actual_to_pred | default_y3_2012_16_actual_to_pred | prepay_y5_2012_16_actual_to_pred | default_y5_2012_16_actual_to_pred | change_lifetime_pd_2012_16_at_orig_vs_D1 | change_lifetime_pd_2023_12_sample_vs_D1 | chosen |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A: default incentive | A0 incentive bands in default | bands | none | shared | 72 | -0.1998 | -0.1991 | -0.1654 | 0.8944 | 1.0661 | 0.9759 | 0.6973 | 1.0967 | 0.9944 | False | 0.3606 | 0.3145 | 0.4102 | 0.0605 | 0.1292 | 0.0470 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | False |
| A: default incentive | A1 no incentive in default | none | none | shared | 66 | -0.1998 | -0.1992 | -0.1654 | 0.9277 | 1.0655 | 1.0889 | 1.1366 | 1.0663 | 0.9835 | True | 0.1280 | 0.3639 | 0.4100 | 0.0605 | 0.1292 | 0.0678 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | False |
| A: default incentive | A2 incentive >= 1pp indicator in default | ge1 | none | shared | 67 | -0.1998 | -0.1991 | -0.1654 | 0.9090 | 1.0571 | 0.9984 | 0.9135 | 1.0906 | 0.9934 | True | 0.0954 | 0.3156 | 0.4102 | 0.0605 | 0.1292 | 0.0562 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | False |
| B: prepayment seasoning | A2 incentive >= 1pp indicator in default | ge1 | none | shared | 67 | -0.1998 | -0.1991 | -0.1654 | 0.9090 | 1.0571 | 0.9984 | 0.9135 | 1.0906 | 0.9934 | True | 0.0954 | 0.3156 | 0.4102 | 0.0605 | 0.1292 | 0.0562 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | False |
| B: prepayment seasoning | B1 + age ramp (prepay) | ge1 | age | shared | 71 | -0.1998 | -0.1991 | -0.1654 | 0.9093 | 1.0573 | 0.9987 | 0.9139 | 1.0908 | 0.9935 | True | 0.0951 | 0.3211 | 0.3448 | 0.0605 | 0.1151 | 0.0562 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | False |
| B: prepayment seasoning | B2 + young x incentive (prepay) | ge1 | young | shared | 72 | -0.1997 | -0.1990 | -0.1651 | 0.9077 | 1.0568 | 0.9967 | 0.9182 | 1.0889 | 0.9923 | True | 0.0968 | 0.3172 | 0.3319 | 0.0605 | 0.1247 | 0.0554 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | False |
| B: prepayment seasoning | B3 + both (prepay) | ge1 | both | shared | 76 | -0.1996 | -0.1990 | -0.1651 | 0.9080 | 1.0570 | 0.9970 | 0.9185 | 1.0891 | 0.9924 | True | 0.0965 | 0.3232 | 0.2824 | 0.0605 | 0.1117 | 0.0555 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | False |
| C: delinquency decay | C0 shared fade (B3 + both (prepay)) | ge1 | both | shared | 76 | -0.1996 | -0.1990 | -0.1651 | 0.9080 | 1.0570 | 0.9970 | 0.9185 | 1.0891 | 0.9924 | True | 0.0965 | 0.3232 | 0.2824 | 0.0605 | 0.1117 | 0.0555 | 6.0000 | 10.0000 | 1.1743 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | False |
| C: delinquency decay | C1 state-specific delinquency decay (default) | ge1 | both | state | 96 | -0.1996 | -0.1990 | -0.1650 | 0.9155 | 1.0517 | 0.9984 | 0.9225 | 1.0919 | 0.9902 | True | 0.0883 | 0.3233 | 0.2825 | 0.0605 | 0.1117 | 0.0554 | 7.0000 | 8.0000 | 1.1245 | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | False |
| D: prepayment refinement | D0 no prepayment seasoning | ge1 | none | state | 87 | -0.1998 | -0.1991 | -0.1654 | nan | nan | nan | nan | nan | nan | nan | nan | 0.3162 | 0.4102 | 0.0605 | 0.1292 | 0.0546 | nan | nan | nan | 49948.0000 | 0.0627 | 0.4681 | 0.5445 | 0.6638 | 0.7186 | 0.8302 | 0.8071 | -0.0370 | 0.0131 | False |
| D: prepayment refinement | D1 age ramp + young x incentive (B3) | ge1 | both | state | 96 | -0.1996 | -0.1990 | -0.1650 | nan | nan | nan | nan | nan | nan | nan | nan | 0.3233 | 0.2825 | 0.0605 | 0.1117 | 0.0539 | nan | nan | nan | 49948.0000 | 0.0651 | 0.5415 | 0.5329 | 0.7110 | 0.7031 | 0.8566 | 0.7892 | 0.0000 | 0.0000 | True |
| D: prepayment refinement | D2 D1 + incentive x age 2-5y | ge1 | both5 | state | 101 | -0.1994 | -0.1987 | -0.1646 | nan | nan | nan | nan | nan | nan | nan | nan | 0.3270 | 0.2805 | 0.0605 | 0.1117 | 0.0520 | nan | nan | nan | 49948.0000 | 0.0647 | 0.5414 | 0.5330 | 0.7297 | 0.7014 | 0.8891 | 0.7812 | -0.0062 | -0.0351 | False |

## Fit
| split | model | rows | weighted_rows | mean_loglik |
|---|---|---|---|---|
| dev_train | H2 | 1427730 | 11789409.0000 | -0.1996 |
| dev_train | H1 | 1427730 | 11789409.0000 | -0.1992 |
| dev_holdout | H2 | 355349 | 2936404.0000 | -0.1990 |
| dev_holdout | H1 | 355349 | 2936404.0000 | -0.1985 |
| oot | H2 | 664166 | 5696837.0000 | -0.1650 |
| oot | H1 | 664166 | 5696837.0000 | -0.1649 |

## Coefficients, champion H2 (loan-clustered sandwich SE)
| outcome | term | coef | se | z |
|---|---|---|---|---|
| default | const | -2.1616 | 0.0771 | -28.0279 |
| default | age_1 | 0.1367 | 0.0597 | 2.2884 |
| default | age_2 | 0.1211 | 0.0590 | 2.0535 |
| default | age_3 | 0.1653 | 0.0590 | 2.8018 |
| default | age_4 | 0.1256 | 0.0601 | 2.0918 |
| default | age_5 | 0.0870 | 0.0616 | 1.4122 |
| default | age_6 | 0.1789 | 0.0638 | 2.8044 |
| default | age_7 | 0.2604 | 0.0662 | 3.9304 |
| default | age_8 | 0.4145 | 0.0695 | 5.9658 |
| default | age_9 | 0.4709 | 0.0745 | 6.3211 |
| default | age_10 | 0.5536 | 0.0788 | 7.0262 |
| default | age_11 | 0.6792 | 0.0836 | 8.1216 |
| default | age_12 | 0.6844 | 0.0896 | 7.6386 |
| default | age_13 | 0.4224 | 0.1064 | 3.9691 |
| default | age_14 | 0.7941 | 0.1068 | 7.4346 |
| default | age_15+ | 0.7751 | 0.0885 | 8.7587 |
| default | rest x q1-4 | 0.9565 | 0.0110 | 86.8415 |
| default | rest x q5-8 | 0.8697 | 0.0104 | 83.5019 |
| default | rest x q9-12 | 0.8497 | 0.0104 | 81.7449 |
| default | rest x q13-20 | 0.8368 | 0.0103 | 80.9469 |
| default | rest x q21+ | 0.8176 | 0.0108 | 75.7695 |
| default | dlq_state=1 x q1-4 [default] | 0.4571 | 0.0574 | 7.9577 |
| default | dlq_state=1 x q5-8 [default] | 0.4705 | 0.0559 | 8.4183 |
| default | dlq_state=1 x q9-12 [default] | 0.4601 | 0.0616 | 7.4655 |
| default | dlq_state=1 x q13-20 [default] | 0.3628 | 0.0569 | 6.3760 |
| default | dlq_state=1 x q21+ [default] | 0.3839 | 0.0611 | 6.2883 |
| default | dlq_state=2 x q1-4 [default] | 1.2129 | 0.0554 | 21.9017 |
| default | dlq_state=2 x q5-8 [default] | 1.1834 | 0.0550 | 21.5164 |
| default | dlq_state=2 x q9-12 [default] | 0.9818 | 0.0626 | 15.6881 |
| default | dlq_state=2 x q13-20 [default] | 0.8694 | 0.0579 | 15.0276 |
| default | dlq_state=2 x q21+ [default] | 0.6532 | 0.0572 | 11.4189 |
| default | dlq_state=3 x q1-4 [default] | 1.9864 | 0.0524 | 37.9380 |
| default | dlq_state=3 x q5-8 [default] | 1.5222 | 0.0583 | 26.1079 |
| default | dlq_state=3 x q9-12 [default] | 1.3065 | 0.0715 | 18.2807 |
| default | dlq_state=3 x q13-20 [default] | 1.1027 | 0.0640 | 17.2402 |
| default | dlq_state=3 x q21+ [default] | 0.7825 | 0.0682 | 11.4768 |
| default | dlq_state=4 x q1-4 [default] | 3.0224 | 0.0440 | 68.6445 |
| default | dlq_state=4 x q5-8 [default] | 1.9502 | 0.0571 | 34.1567 |
| default | dlq_state=4 x q9-12 [default] | 1.5355 | 0.0712 | 21.5516 |
| default | dlq_state=4 x q13-20 [default] | 1.1555 | 0.0686 | 16.8530 |
| default | dlq_state=4 x q21+ [default] | 0.8910 | 0.0736 | 12.0997 |
| default | dlq_state=5 x q1-4 [default] | 4.8283 | 0.1079 | 44.7281 |
| default | dlq_state=5 x q5-8 [default] | 2.3432 | 0.1579 | 14.8380 |
| default | dlq_state=5 x q9-12 [default] | 1.6094 | 0.1883 | 8.5490 |
| default | dlq_state=5 x q13-20 [default] | 1.5290 | 0.2095 | 7.2999 |
| default | dlq_state=5 x q21+ [default] | 1.1267 | 0.2118 | 5.3185 |
| default | d WoE(current LTV) | -0.7522 | 0.0175 | -43.0759 |
| default | d negative equity (per 10pp) | 0.2155 | 0.0164 | 13.1156 |
| default | d WoE(loan age) | -0.6705 | 0.0233 | -28.7471 |
| default | z | -0.7370 | 0.0208 | -35.4776 |
| default | incentive >=1 [default] | 0.4459 | 0.0219 | 20.3693 |
| prepay | const | -4.9533 | 0.0328 | -150.8450 |
| prepay | age_1 | 0.0876 | 0.0244 | 3.5936 |
| prepay | age_2 | 0.4594 | 0.0278 | 16.5306 |
| prepay | age_3 | 0.3893 | 0.0281 | 13.8701 |
| prepay | age_4 | 0.3290 | 0.0285 | 11.5603 |
| prepay | age_5 | 0.2638 | 0.0288 | 9.1451 |
| prepay | age_6 | 0.2485 | 0.0292 | 8.4979 |
| prepay | age_7 | 0.1912 | 0.0298 | 6.4222 |
| prepay | age_8 | 0.0635 | 0.0305 | 2.0799 |
| prepay | age_9 | -0.0653 | 0.0316 | -2.0665 |
| prepay | age_10 | -0.2025 | 0.0326 | -6.2089 |
| prepay | age_11 | -0.2346 | 0.0335 | -7.0067 |
| prepay | age_12 | -0.1624 | 0.0345 | -4.7035 |
| prepay | age_13 | -0.0493 | 0.0359 | -1.3722 |
| prepay | age_14 | -0.0226 | 0.0384 | -0.5894 |
| prepay | age_15+ | -0.4769 | 0.0363 | -13.1415 |
| prepay | dlq x q1-4 | -0.1813 | 0.0119 | -15.1931 |
| prepay | dlq x q5-8 | -0.1508 | 0.0133 | -11.3591 |
| prepay | dlq x q9-12 | -0.1423 | 0.0151 | -9.4272 |
| prepay | dlq x q13-20 | -0.1346 | 0.0130 | -10.3221 |
| prepay | dlq x q21+ | -0.1164 | 0.0114 | -10.2122 |
| prepay | rest x q1-4 | -0.1606 | 0.0033 | -49.3458 |
| prepay | rest x q5-8 | -0.1586 | 0.0033 | -48.6420 |
| prepay | rest x q9-12 | -0.1541 | 0.0033 | -46.6198 |
| prepay | rest x q13-20 | -0.1561 | 0.0033 | -47.7123 |
| prepay | rest x q21+ | -0.1660 | 0.0034 | -49.1686 |
| prepay | d WoE(current LTV) | 0.0894 | 0.0074 | 12.1376 |
| prepay | d negative equity (per 10pp) | 0.0027 | 0.0076 | 0.3550 |
| prepay | d WoE(loan age) | 0.1119 | 0.0083 | 13.4061 |
| prepay | incentive <-1 | 0.0049 | 0.0150 | 0.3241 |
| prepay | incentive 0..0.5 | 0.3864 | 0.0124 | 31.2079 |
| prepay | incentive 0.5..1 | 0.7667 | 0.0115 | 66.9499 |
| prepay | incentive 1..1.5 | 1.0538 | 0.0116 | 91.0549 |
| prepay | incentive 1.5..2 | 1.1587 | 0.0125 | 92.5567 |
| prepay | incentive >=2 | 1.2160 | 0.0130 | 93.7822 |
| prepay | age 0-2m [prepay] | -0.9125 | 0.0624 | -14.6222 |
| prepay | age 3-5m [prepay] | -0.3133 | 0.0387 | -8.0991 |
| prepay | age 6-8m [prepay] | -0.1671 | 0.0329 | -5.0777 |
| prepay | age 12-17m [prepay] | -0.0004 | 0.0173 | -0.0231 |
| prepay | young x incentive 0..0.5 [prepay] | 0.3157 | 0.0256 | 12.3154 |
| prepay | young x incentive 0.5..1 [prepay] | 0.5261 | 0.0236 | 22.2622 |
| prepay | young x incentive 1..1.5 [prepay] | 0.6799 | 0.0248 | 27.3799 |
| prepay | young x incentive 1.5..2 [prepay] | 0.6390 | 0.0328 | 19.4674 |
| prepay | young x incentive >=2 [prepay] | 0.4350 | 0.0578 | 7.5277 |
| prepay | hpi_yoy (per 10%) | 0.2212 | 0.0058 | 38.2383 |

## Calibration by horizon (actual / predicted events)
| split | model | horizon | outcome | exposure_quarters | actual | predicted | actual_to_predicted |
|---|---|---|---|---|---|---|---|
| dev_train | H2 | q1-4 | default | 2411942.0000 | 7862.0000 | 8047.9162 | 0.9769 |
| dev_train | H2 | q1-4 | prepay | 2411942.0000 | 111680.0000 | 111477.9034 | 1.0018 |
| dev_train | H2 | q5-8 | default | 1953860.0000 | 7024.0000 | 6960.0227 | 1.0092 |
| dev_train | H2 | q5-8 | prepay | 1953860.0000 | 91966.0000 | 91777.7289 | 1.0021 |
| dev_train | H2 | q9-12 | default | 1587405.0000 | 5671.0000 | 5619.6406 | 1.0091 |
| dev_train | H2 | q9-12 | prepay | 1587405.0000 | 70924.0000 | 70471.2774 | 1.0064 |
| dev_train | H2 | q13-20 | default | 2367898.0000 | 7618.0000 | 7591.8160 | 1.0034 |
| dev_train | H2 | q13-20 | prepay | 2367898.0000 | 108760.0000 | 108470.5251 | 1.0027 |
| dev_train | H2 | q21+ | default | 3468304.0000 | 8876.0000 | 8831.6082 | 1.0050 |
| dev_train | H2 | q21+ | prepay | 3468304.0000 | 155278.0000 | 156410.5651 | 0.9928 |
| dev_train | H1 | q1-4 | default | 2411942.0000 | 7862.0000 | 9185.8552 | 0.8559 |
| dev_train | H1 | q1-4 | prepay | 2411942.0000 | 111680.0000 | 110793.6840 | 1.0080 |
| dev_train | H1 | q5-8 | default | 1953860.0000 | 7024.0000 | 6818.3370 | 1.0302 |
| dev_train | H1 | q5-8 | prepay | 1953860.0000 | 91966.0000 | 91815.2789 | 1.0016 |
| dev_train | H1 | q9-12 | default | 1587405.0000 | 5671.0000 | 5398.9150 | 1.0504 |
| dev_train | H1 | q9-12 | prepay | 1587405.0000 | 70924.0000 | 72130.2205 | 0.9833 |
| dev_train | H1 | q13-20 | default | 2367898.0000 | 7618.0000 | 7295.1227 | 1.0443 |
| dev_train | H1 | q13-20 | prepay | 2367898.0000 | 108760.0000 | 110090.7862 | 0.9879 |
| dev_train | H1 | q21+ | default | 3468304.0000 | 8876.0000 | 8352.7748 | 1.0626 |
| dev_train | H1 | q21+ | prepay | 3468304.0000 | 155278.0000 | 153778.0303 | 1.0098 |
| dev_holdout | H2 | q1-4 | default | 595776.0000 | 1946.0000 | 2070.5045 | 0.9399 |
| dev_holdout | H2 | q1-4 | prepay | 595776.0000 | 27910.0000 | 27584.9781 | 1.0118 |
| dev_holdout | H2 | q5-8 | default | 485254.0000 | 1732.0000 | 1733.5673 | 0.9991 |
| dev_holdout | H2 | q5-8 | prepay | 485254.0000 | 22662.0000 | 22725.9763 | 0.9972 |
| dev_holdout | H2 | q9-12 | default | 394191.0000 | 1369.0000 | 1376.3295 | 0.9947 |
| dev_holdout | H2 | q9-12 | prepay | 394191.0000 | 17542.0000 | 17540.4898 | 1.0001 |
| dev_holdout | H2 | q13-20 | default | 590030.0000 | 1938.0000 | 1910.9263 | 1.0142 |
| dev_holdout | H2 | q13-20 | prepay | 590030.0000 | 26922.0000 | 27028.4201 | 0.9961 |
| dev_holdout | H2 | q21+ | default | 871153.0000 | 2237.0000 | 2219.7986 | 1.0077 |
| dev_holdout | H2 | q21+ | prepay | 871153.0000 | 38486.0000 | 39274.9220 | 0.9799 |
| dev_holdout | H1 | q1-4 | default | 595776.0000 | 1946.0000 | 2357.9636 | 0.8253 |
| dev_holdout | H1 | q1-4 | prepay | 595776.0000 | 27910.0000 | 27422.2654 | 1.0178 |
| dev_holdout | H1 | q5-8 | default | 485254.0000 | 1732.0000 | 1697.8531 | 1.0201 |
| dev_holdout | H1 | q5-8 | prepay | 485254.0000 | 22662.0000 | 22735.5571 | 0.9968 |
| dev_holdout | H1 | q9-12 | default | 394191.0000 | 1369.0000 | 1323.4284 | 1.0344 |
| dev_holdout | H1 | q9-12 | prepay | 394191.0000 | 17542.0000 | 17948.2085 | 0.9774 |
| dev_holdout | H1 | q13-20 | default | 590030.0000 | 1938.0000 | 1840.6474 | 1.0529 |
| dev_holdout | H1 | q13-20 | prepay | 590030.0000 | 26922.0000 | 27438.9718 | 0.9812 |
| dev_holdout | H1 | q21+ | default | 871153.0000 | 2237.0000 | 2106.5142 | 1.0619 |
| dev_holdout | H1 | q21+ | prepay | 871153.0000 | 38486.0000 | 38568.5664 | 0.9979 |
| oot | H2 | q1-4 | default | 1867764.0000 | 2182.0000 | 2276.1797 | 0.9586 |
| oot | H2 | q1-4 | prepay | 1867764.0000 | 73232.0000 | 77214.9855 | 0.9484 |
| oot | H2 | q5-8 | default | 1419330.0000 | 1848.0000 | 1905.7690 | 0.9697 |
| oot | H2 | q5-8 | prepay | 1419330.0000 | 57392.0000 | 58925.7873 | 0.9740 |
| oot | H2 | q9-12 | default | 973270.0000 | 1312.0000 | 1304.8409 | 1.0055 |
| oot | H2 | q9-12 | prepay | 973270.0000 | 42048.0000 | 39927.5343 | 1.0531 |
| oot | H2 | q13-20 | default | 1030760.0000 | 1278.0000 | 1206.9745 | 1.0588 |
| oot | H2 | q13-20 | prepay | 1030760.0000 | 38612.0000 | 36345.2539 | 1.0624 |
| oot | H2 | q21+ | default | 405713.0000 | 459.0000 | 515.2882 | 0.8908 |
| oot | H2 | q21+ | prepay | 405713.0000 | 8994.0000 | 9051.9395 | 0.9936 |
| oot | H1 | q1-4 | default | 1867764.0000 | 2182.0000 | 2936.3205 | 0.7431 |
| oot | H1 | q1-4 | prepay | 1867764.0000 | 73232.0000 | 75151.9018 | 0.9745 |
| oot | H1 | q5-8 | default | 1419330.0000 | 1848.0000 | 1947.8805 | 0.9487 |
| oot | H1 | q5-8 | prepay | 1419330.0000 | 57392.0000 | 57685.1262 | 0.9949 |
| oot | H1 | q9-12 | default | 973270.0000 | 1312.0000 | 1281.7866 | 1.0236 |
| oot | H1 | q9-12 | prepay | 973270.0000 | 42048.0000 | 40171.6204 | 1.0467 |
| oot | H1 | q13-20 | default | 1030760.0000 | 1278.0000 | 1153.5337 | 1.1079 |
| oot | H1 | q13-20 | prepay | 1030760.0000 | 38612.0000 | 36119.9640 | 1.0690 |
| oot | H1 | q21+ | default | 405713.0000 | 459.0000 | 458.9639 | 1.0001 |
| oot | H1 | q21+ | prepay | 405713.0000 | 8994.0000 | 8183.1071 | 1.0991 |

## Year-1 splice check
| breakdown | period | segment | n | actual | pit12 | hazard_h2 | hazard_h1 | hazard_to_pit | actual_to_hazard | actual_to_pit | within_tolerance |
|---|---|---|---|---|---|---|---|---|---|---|---|
| period x dlq_state | 2000-06 | 30-59 dpd | 444 | 0.1667 | 0.1926 | 0.1398 | 0.1396 | 0.7261 | 1.1919 | 0.8654 | False |
| period x dlq_state | 2000-06 | 60-89 dpd | 73 | 0.4658 | 0.6221 | 0.5235 | 0.5428 | 0.8414 | 0.8898 | 0.7487 | True |
| period x dlq_state | 2000-06 | cured 1-3 months | 576 | 0.0417 | 0.0606 | 0.0447 | 0.0450 | 0.7375 | 0.9318 | 0.6872 | False |
| period x dlq_state | 2000-06 | cured 13+ months | 1013 | 0.0089 | 0.0069 | 0.0070 | 0.0069 | 1.0137 | 1.2697 | 1.2871 | True |
| period x dlq_state | 2000-06 | cured 4-12 months | 893 | 0.0202 | 0.0206 | 0.0179 | 0.0177 | 0.8679 | 1.1271 | 0.9782 | True |
| period x dlq_state | 2000-06 | never 30+ dpd | 38513 | 0.0025 | 0.0028 | 0.0033 | 0.0043 | 1.1539 | 0.7558 | 0.8721 | True |
| period x dlq_state | 2012-16 | 30-59 dpd | 555 | 0.1910 | 0.2121 | 0.1835 | 0.1996 | 0.8653 | 1.0406 | 0.9005 | True |
| period x dlq_state | 2012-16 | 60-89 dpd | 140 | 0.5857 | 0.6465 | 0.6108 | 0.6569 | 0.9447 | 0.9590 | 0.9060 | True |
| period x dlq_state | 2012-16 | cured 1-3 months | 558 | 0.0789 | 0.0751 | 0.0672 | 0.0745 | 0.8942 | 1.1741 | 1.0499 | True |
| period x dlq_state | 2012-16 | cured 13+ months | 3152 | 0.0121 | 0.0103 | 0.0126 | 0.0133 | 1.2248 | 0.9537 | 1.1681 | True |
| period x dlq_state | 2012-16 | cured 4-12 months | 971 | 0.0340 | 0.0307 | 0.0304 | 0.0330 | 0.9926 | 1.1168 | 1.1085 | True |
| period x dlq_state | 2012-16 | never 30+ dpd | 56058 | 0.0026 | 0.0030 | 0.0037 | 0.0053 | 1.2589 | 0.7097 | 0.8934 | False |
| period x dlq_state | 2017-19 | 30-59 dpd | 1629 | 0.1713 | 0.1489 | 0.1127 | 0.1273 | 0.7568 | 1.5201 | 1.1504 | False |
| period x dlq_state | 2017-19 | 60-89 dpd | 286 | 0.5594 | 0.5624 | 0.4783 | 0.5206 | 0.8505 | 1.1696 | 0.9947 | True |
| period x dlq_state | 2017-19 | cured 1-3 months | 1923 | 0.0541 | 0.0461 | 0.0372 | 0.0425 | 0.8066 | 1.4538 | 1.1727 | True |
| period x dlq_state | 2017-19 | cured 13+ months | 10226 | 0.0085 | 0.0057 | 0.0077 | 0.0090 | 1.3399 | 1.1116 | 1.4893 | False |
| period x dlq_state | 2017-19 | cured 4-12 months | 3405 | 0.0188 | 0.0179 | 0.0166 | 0.0189 | 0.9274 | 1.1330 | 1.0508 | True |
| period x dlq_state | 2017-19 | never 30+ dpd | 206809 | 0.0021 | 0.0024 | 0.0028 | 0.0041 | 1.1638 | 0.7449 | 0.8669 | True |
| period x dlq_state | 2022-23 | 30-59 dpd | 936 | 0.1357 | 0.1249 | 0.0829 | 0.0921 | 0.6640 | 1.6363 | 1.0866 | False |
| period x dlq_state | 2022-23 | 60-89 dpd | 194 | 0.5155 | 0.5149 | 0.3775 | 0.4050 | 0.7331 | 1.3655 | 1.0010 | False |
| period x dlq_state | 2022-23 | cured 1-3 months | 1280 | 0.0469 | 0.0377 | 0.0268 | 0.0301 | 0.7118 | 1.7476 | 1.2438 | False |
| period x dlq_state | 2022-23 | cured 13+ months | 10675 | 0.0040 | 0.0040 | 0.0046 | 0.0055 | 1.1531 | 0.8739 | 1.0077 | True |
| period x dlq_state | 2022-23 | cured 4-12 months | 2726 | 0.0187 | 0.0135 | 0.0114 | 0.0128 | 0.8470 | 1.6397 | 1.3888 | True |
| period x dlq_state | 2022-23 | never 30+ dpd | 119281 | 0.0017 | 0.0022 | 0.0025 | 0.0036 | 1.1210 | 0.7055 | 0.7909 | True |
| period x dlq_state | COVID 2020-21 | 30-59 dpd | 1036 | 0.0869 | 0.0885 | 0.0737 | 0.0837 | 0.8327 | 1.1783 | 0.9811 | True |
| period x dlq_state | COVID 2020-21 | 60-89 dpd | 535 | 0.1869 | 0.3769 | 0.3456 | 0.3722 | 0.9171 | 0.5408 | 0.4960 | True |
| period x dlq_state | COVID 2020-21 | cured 1-3 months | 1977 | 0.0243 | 0.0270 | 0.0246 | 0.0279 | 0.9142 | 0.9852 | 0.9007 | True |
| period x dlq_state | COVID 2020-21 | cured 13+ months | 7837 | 0.0032 | 0.0029 | 0.0046 | 0.0056 | 1.5783 | 0.6885 | 1.0867 | False |
| period x dlq_state | COVID 2020-21 | cured 4-12 months | 3927 | 0.0089 | 0.0091 | 0.0099 | 0.0113 | 1.0931 | 0.9003 | 0.9841 | True |
| period x dlq_state | COVID 2020-21 | never 30+ dpd | 120151 | 0.0013 | 0.0013 | 0.0019 | 0.0029 | 1.4477 | 0.6955 | 1.0069 | False |
| period x dlq_state | crisis 2007-11 | 30-59 dpd | 808 | 0.3144 | 0.3580 | 0.3395 | 0.3365 | 0.9483 | 0.9261 | 0.8782 | True |
| period x dlq_state | crisis 2007-11 | 60-89 dpd | 229 | 0.7598 | 0.7961 | 0.7947 | 0.8107 | 0.9983 | 0.9561 | 0.9545 | True |
| period x dlq_state | crisis 2007-11 | cured 1-3 months | 733 | 0.1351 | 0.1444 | 0.1322 | 0.1292 | 0.9154 | 1.0215 | 0.9351 | True |
| period x dlq_state | crisis 2007-11 | cured 13+ months | 2533 | 0.0253 | 0.0229 | 0.0224 | 0.0213 | 0.9790 | 1.1285 | 1.1048 | True |
| period x dlq_state | crisis 2007-11 | cured 4-12 months | 1203 | 0.0640 | 0.0626 | 0.0587 | 0.0565 | 0.9371 | 1.0902 | 1.0217 | True |
| period x dlq_state | crisis 2007-11 | never 30+ dpd | 52585 | 0.0109 | 0.0097 | 0.0100 | 0.0129 | 1.0359 | 1.0888 | 1.1279 | True |
| period x ttc_decile | 2000-06 | 1 | 3067 | 0.0000 | 0.0002 | 0.0004 | 0.0007 | 1.7911 | 0.0000 | 0.0000 | False |
| period x ttc_decile | 2000-06 | 2 | 3584 | 0.0000 | 0.0005 | 0.0008 | 0.0012 | 1.6084 | 0.0000 | 0.0000 | False |
| period x ttc_decile | 2000-06 | 3 | 3774 | 0.0000 | 0.0007 | 0.0011 | 0.0016 | 1.5035 | 0.0000 | 0.0000 | False |
| period x ttc_decile | 2000-06 | 4 | 3857 | 0.0010 | 0.0010 | 0.0014 | 0.0021 | 1.4162 | 0.7204 | 1.0202 | False |
| period x ttc_decile | 2000-06 | 5 | 4141 | 0.0010 | 0.0014 | 0.0019 | 0.0026 | 1.3539 | 0.5120 | 0.6932 | False |
| period x ttc_decile | 2000-06 | 6 | 4230 | 0.0005 | 0.0019 | 0.0024 | 0.0033 | 1.2973 | 0.1942 | 0.2519 | False |
| period x ttc_decile | 2000-06 | 7 | 4477 | 0.0018 | 0.0026 | 0.0032 | 0.0043 | 1.2427 | 0.5595 | 0.6953 | True |
| period x ttc_decile | 2000-06 | 8 | 4711 | 0.0036 | 0.0036 | 0.0043 | 0.0057 | 1.1808 | 0.8407 | 0.9928 | True |
| period x ttc_decile | 2000-06 | 9 | 4782 | 0.0056 | 0.0057 | 0.0063 | 0.0081 | 1.1072 | 0.8997 | 0.9962 | True |
| period x ttc_decile | 2000-06 | 10 | 4889 | 0.0393 | 0.0453 | 0.0365 | 0.0381 | 0.8053 | 1.0755 | 0.8661 | True |
| period x ttc_decile | 2012-16 | 1 | 5507 | 0.0005 | 0.0002 | 0.0005 | 0.0009 | 2.2489 | 1.0760 | 2.4197 | False |
| period x ttc_decile | 2012-16 | 2 | 5550 | 0.0002 | 0.0004 | 0.0008 | 0.0015 | 1.9592 | 0.2129 | 0.4171 | False |
| period x ttc_decile | 2012-16 | 3 | 5701 | 0.0011 | 0.0007 | 0.0012 | 0.0019 | 1.7807 | 0.9030 | 1.6079 | False |
| period x ttc_decile | 2012-16 | 4 | 5864 | 0.0012 | 0.0009 | 0.0015 | 0.0024 | 1.6696 | 0.7705 | 1.2864 | False |
| period x ttc_decile | 2012-16 | 5 | 5751 | 0.0019 | 0.0013 | 0.0020 | 0.0031 | 1.5762 | 0.9566 | 1.5078 | False |
| period x ttc_decile | 2012-16 | 6 | 5728 | 0.0010 | 0.0017 | 0.0026 | 0.0039 | 1.5007 | 0.4058 | 0.6089 | False |
| period x ttc_decile | 2012-16 | 7 | 5999 | 0.0025 | 0.0024 | 0.0034 | 0.0049 | 1.4305 | 0.7408 | 1.0598 | False |
| period x ttc_decile | 2012-16 | 8 | 6128 | 0.0034 | 0.0034 | 0.0046 | 0.0066 | 1.3707 | 0.7429 | 1.0183 | False |
| period x ttc_decile | 2012-16 | 9 | 6751 | 0.0043 | 0.0053 | 0.0069 | 0.0094 | 1.2848 | 0.6265 | 0.8049 | False |
| period x ttc_decile | 2012-16 | 10 | 8455 | 0.0416 | 0.0446 | 0.0424 | 0.0477 | 0.9501 | 0.9819 | 0.9329 | True |
| period x ttc_decile | 2017-19 | 1 | 19801 | 0.0004 | 0.0003 | 0.0005 | 0.0009 | 1.8940 | 0.7422 | 1.4056 | False |
| period x ttc_decile | 2017-19 | 2 | 20658 | 0.0005 | 0.0005 | 0.0008 | 0.0014 | 1.7061 | 0.6678 | 1.1394 | False |
| period x ttc_decile | 2017-19 | 3 | 21983 | 0.0010 | 0.0007 | 0.0011 | 0.0019 | 1.5818 | 0.8480 | 1.3414 | False |
| period x ttc_decile | 2017-19 | 4 | 22739 | 0.0011 | 0.0010 | 0.0015 | 0.0024 | 1.4827 | 0.7646 | 1.1337 | False |
| period x ttc_decile | 2017-19 | 5 | 23527 | 0.0009 | 0.0014 | 0.0019 | 0.0030 | 1.4029 | 0.4850 | 0.6804 | False |
| period x ttc_decile | 2017-19 | 6 | 23930 | 0.0017 | 0.0018 | 0.0025 | 0.0038 | 1.3411 | 0.6745 | 0.9046 | False |
| period x ttc_decile | 2017-19 | 7 | 24003 | 0.0029 | 0.0025 | 0.0032 | 0.0047 | 1.2625 | 0.9122 | 1.1517 | False |
| period x ttc_decile | 2017-19 | 8 | 23932 | 0.0037 | 0.0036 | 0.0043 | 0.0061 | 1.2027 | 0.8526 | 1.0255 | True |
| period x ttc_decile | 2017-19 | 9 | 23707 | 0.0047 | 0.0056 | 0.0063 | 0.0084 | 1.1233 | 0.7479 | 0.8401 | True |
| period x ttc_decile | 2017-19 | 10 | 19998 | 0.0369 | 0.0355 | 0.0299 | 0.0343 | 0.8435 | 1.2319 | 1.0391 | True |
| period x ttc_decile | 2022-23 | 1 | 17030 | 0.0004 | 0.0003 | 0.0006 | 0.0012 | 2.0617 | 0.5965 | 1.2298 | False |
| period x ttc_decile | 2022-23 | 2 | 16107 | 0.0001 | 0.0005 | 0.0009 | 0.0017 | 1.7393 | 0.1317 | 0.2291 | False |
| period x ttc_decile | 2022-23 | 3 | 15254 | 0.0003 | 0.0008 | 0.0013 | 0.0022 | 1.5639 | 0.2539 | 0.3971 | False |
| period x ttc_decile | 2022-23 | 4 | 14588 | 0.0014 | 0.0012 | 0.0017 | 0.0027 | 1.4352 | 0.8624 | 1.2377 | False |
| period x ttc_decile | 2022-23 | 5 | 13901 | 0.0011 | 0.0016 | 0.0021 | 0.0033 | 1.3303 | 0.5109 | 0.6796 | False |
| period x ttc_decile | 2022-23 | 6 | 13254 | 0.0019 | 0.0021 | 0.0027 | 0.0039 | 1.2432 | 0.7096 | 0.8822 | True |
| period x ttc_decile | 2022-23 | 7 | 12881 | 0.0023 | 0.0029 | 0.0034 | 0.0048 | 1.1650 | 0.6624 | 0.7717 | True |
| period x ttc_decile | 2022-23 | 8 | 12260 | 0.0038 | 0.0041 | 0.0045 | 0.0060 | 1.0881 | 0.8576 | 0.9332 | True |
| period x ttc_decile | 2022-23 | 9 | 11149 | 0.0060 | 0.0064 | 0.0063 | 0.0078 | 0.9837 | 0.9562 | 0.9406 | True |
| period x ttc_decile | 2022-23 | 10 | 8668 | 0.0429 | 0.0409 | 0.0297 | 0.0325 | 0.7269 | 1.4430 | 1.0489 | False |
| period x ttc_decile | COVID 2020-21 | 1 | 15661 | 0.0004 | 0.0001 | 0.0004 | 0.0008 | 2.7179 | 0.9710 | 2.6390 | False |
| period x ttc_decile | COVID 2020-21 | 2 | 15177 | 0.0007 | 0.0003 | 0.0007 | 0.0012 | 2.2895 | 1.0096 | 2.3116 | False |
| period x ttc_decile | COVID 2020-21 | 3 | 14485 | 0.0006 | 0.0004 | 0.0009 | 0.0016 | 2.0425 | 0.6871 | 1.4033 | False |
| period x ttc_decile | COVID 2020-21 | 4 | 13994 | 0.0007 | 0.0006 | 0.0012 | 0.0020 | 1.9107 | 0.5932 | 1.1334 | False |
| period x ttc_decile | COVID 2020-21 | 5 | 13662 | 0.0015 | 0.0009 | 0.0015 | 0.0025 | 1.7658 | 0.9977 | 1.7617 | False |
| period x ttc_decile | COVID 2020-21 | 6 | 13429 | 0.0016 | 0.0012 | 0.0020 | 0.0030 | 1.6438 | 0.7977 | 1.3112 | False |
| period x ttc_decile | COVID 2020-21 | 7 | 12936 | 0.0008 | 0.0017 | 0.0025 | 0.0038 | 1.5222 | 0.3054 | 0.4648 | False |
| period x ttc_decile | COVID 2020-21 | 8 | 12574 | 0.0025 | 0.0023 | 0.0034 | 0.0048 | 1.4410 | 0.7558 | 1.0891 | False |
| period x ttc_decile | COVID 2020-21 | 9 | 11955 | 0.0037 | 0.0037 | 0.0049 | 0.0066 | 1.3267 | 0.7534 | 0.9995 | False |
| period x ttc_decile | COVID 2020-21 | 10 | 11590 | 0.0256 | 0.0364 | 0.0338 | 0.0377 | 0.9283 | 0.7592 | 0.7048 | True |
| period x ttc_decile | crisis 2007-11 | 1 | 4259 | 0.0002 | 0.0007 | 0.0008 | 0.0015 | 1.1317 | 0.2824 | 0.3196 | True |
| period x ttc_decile | crisis 2007-11 | 2 | 4414 | 0.0005 | 0.0014 | 0.0015 | 0.0024 | 1.0663 | 0.3095 | 0.3300 | True |
| period x ttc_decile | crisis 2007-11 | 3 | 4359 | 0.0016 | 0.0020 | 0.0021 | 0.0034 | 1.0486 | 0.7709 | 0.8084 | True |
| period x ttc_decile | crisis 2007-11 | 4 | 4550 | 0.0009 | 0.0027 | 0.0028 | 0.0043 | 1.0354 | 0.3099 | 0.3209 | True |
| period x ttc_decile | crisis 2007-11 | 5 | 4652 | 0.0026 | 0.0036 | 0.0037 | 0.0055 | 1.0248 | 0.6970 | 0.7143 | True |
| period x ttc_decile | crisis 2007-11 | 6 | 5087 | 0.0035 | 0.0048 | 0.0049 | 0.0070 | 1.0197 | 0.7202 | 0.7344 | True |
| period x ttc_decile | crisis 2007-11 | 7 | 5366 | 0.0076 | 0.0064 | 0.0065 | 0.0090 | 1.0126 | 1.1719 | 1.1866 | True |
| period x ttc_decile | crisis 2007-11 | 8 | 6055 | 0.0086 | 0.0089 | 0.0089 | 0.0121 | 1.0056 | 0.9621 | 0.9675 | True |
| period x ttc_decile | crisis 2007-11 | 9 | 7321 | 0.0164 | 0.0133 | 0.0134 | 0.0176 | 1.0113 | 1.2187 | 1.2325 | True |
| period x ttc_decile | crisis 2007-11 | 10 | 12028 | 0.0818 | 0.0799 | 0.0786 | 0.0823 | 0.9830 | 1.0412 | 1.0235 | True |
| period | 2000-06 | all | 41512 | 0.0061 | 0.0072 | 0.0066 | 0.0076 | 0.9155 | 0.9243 | 0.8462 | True |
| period | 2012-16 | all | 61434 | 0.0073 | 0.0078 | 0.0082 | 0.0100 | 1.0517 | 0.8970 | 0.9433 | True |
| period | 2017-19 | all | 224278 | 0.0051 | 0.0050 | 0.0050 | 0.0065 | 0.9984 | 1.0152 | 1.0136 | True |
| period | 2022-23 | all | 135092 | 0.0044 | 0.0045 | 0.0041 | 0.0054 | 0.9225 | 1.0512 | 0.9697 | True |
| period | COVID 2020-21 | all | 135463 | 0.0034 | 0.0042 | 0.0046 | 0.0058 | 1.0919 | 0.7442 | 0.8126 | True |
| period | crisis 2007-11 | all | 58091 | 0.0214 | 0.0210 | 0.0208 | 0.0233 | 0.9902 | 1.0283 | 1.0183 | True |

## Year-2 / year-1 jump check (flag: model / actual outside (0.8, 1.25))
Calibrated splice: tau = 3.0 (owner decision 2026-11-13: tau = 3 years, the 12-quarter explicit macro forecast (open question #5), so the carried cycle mismatch fades on the forecast's time scale (paras 49, 124); applied only if the jump check flags a segment after the state-specific decay. Secondary: smallest tau within 5% of the best development error (rule set after seeing the results) = 3; development argmin = inf (failed OOT)).

| tau | sample | cells_y2 | cells_y3 | mse_log | jump_flags | segments |
|---|---|---|---|---|---|---|
| 0.0000 | OOT 2017-21 | 14 | 14 | 0.0552 | 8 | 16 |
| 0.0000 | development holdout 2000-16 | 11 | 13 | 0.0451 | 7 | 16 |
| 0.2500 | OOT 2017-21 | 14 | 14 | 0.0543 | 8 | 16 |
| 0.2500 | development holdout 2000-16 | 11 | 13 | 0.0448 | 7 | 16 |
| 0.5000 | OOT 2017-21 | 14 | 14 | 0.0488 | 6 | 16 |
| 0.5000 | development holdout 2000-16 | 11 | 13 | 0.0427 | 6 | 16 |
| 0.7500 | OOT 2017-21 | 14 | 14 | 0.0432 | 5 | 16 |
| 0.7500 | development holdout 2000-16 | 11 | 13 | 0.0400 | 6 | 16 |
| 1.0000 | OOT 2017-21 | 14 | 14 | 0.0395 | 4 | 16 |
| 1.0000 | development holdout 2000-16 | 11 | 13 | 0.0376 | 6 | 16 |
| 1.5000 | OOT 2017-21 | 14 | 14 | 0.0363 | 5 | 16 |
| 1.5000 | development holdout 2000-16 | 11 | 13 | 0.0344 | 5 | 16 |
| 2.0000 | OOT 2017-21 | 14 | 14 | 0.0363 | 6 | 16 |
| 2.0000 | development holdout 2000-16 | 11 | 13 | 0.0325 | 5 | 16 |
| 3.0000 | OOT 2017-21 | 14 | 14 | 0.0389 | 5 | 16 |
| 3.0000 | development holdout 2000-16 | 11 | 13 | 0.0307 | 5 | 16 |
| 5.0000 | OOT 2017-21 | 14 | 14 | 0.0443 | 5 | 16 |
| 5.0000 | development holdout 2000-16 | 11 | 13 | 0.0296 | 5 | 16 |
| inf | OOT 2017-21 | 14 | 14 | 0.0623 | 5 | 16 |
| inf | development holdout 2000-16 | 11 | 13 | 0.0294 | 6 | 16 |

| tau | sample | breakdown | segment | references | year2_defaults | year3_defaults | y1_actual | y2_cond_actual | y3_cond_actual | y1_model_pit | y1_hazard | y2_cond_model | y3_cond_model | jump_actual | jump_model | model_to_actual | y3_model_to_actual | flag | model |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.0000 | OOT 2017-21 | dlq_state | 30-59 dpd | 2673 | 132 | 81 | 0.1383 | 0.0664 | 0.0508 | 0.1252 | 0.0959 | 0.0450 | 0.0312 | 0.4806 | 0.3597 | 0.7485 | 0.6144 | True | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | dlq_state | 60-89 dpd | 826 | 30 | 8 | 0.3152 | 0.0677 | 0.0239 | 0.4422 | 0.3920 | 0.1000 | 0.0614 | 0.2149 | 0.2261 | 1.0518 | 2.5644 | False | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | dlq_state | cured 1-3 months | 3914 | 112 | 77 | 0.0389 | 0.0366 | 0.0309 | 0.0364 | 0.0312 | 0.0215 | 0.0176 | 0.9401 | 0.5897 | 0.6272 | 0.5716 | True | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | dlq_state | cured 13+ months | 18221 | 140 | 113 | 0.0062 | 0.0094 | 0.0091 | 0.0045 | 0.0067 | 0.0082 | 0.0080 | 1.5244 | 1.8167 | 1.1918 | 0.8774 | False | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | dlq_state | cured 4-12 months | 7359 | 104 | 105 | 0.0135 | 0.0177 | 0.0214 | 0.0131 | 0.0131 | 0.0125 | 0.0113 | 1.3115 | 0.9523 | 0.7262 | 0.5307 | True | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | dlq_state | never 30+ dpd | 327737 | 865 | 817 | 0.0018 | 0.0032 | 0.0038 | 0.0020 | 0.0025 | 0.0039 | 0.0041 | 1.7655 | 1.9277 | 1.0918 | 1.0952 | False | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | ttc_decile | 1 | 38313 | 16 | 25 | 0.0004 | 0.0005 | 0.0010 | 0.0002 | 0.0004 | 0.0009 | 0.0012 | 1.3817 | 4.4711 | 3.2360 | 1.2311 | True | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | ttc_decile | 2 | 37920 | 28 | 36 | 0.0006 | 0.0009 | 0.0014 | 0.0004 | 0.0007 | 0.0015 | 0.0017 | 1.4581 | 3.5926 | 2.4639 | 1.2892 | True | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | ttc_decile | 3 | 37882 | 43 | 34 | 0.0009 | 0.0014 | 0.0013 | 0.0006 | 0.0011 | 0.0020 | 0.0023 | 1.5752 | 3.1048 | 1.9710 | 1.7410 | True | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | ttc_decile | 4 | 37527 | 66 | 65 | 0.0010 | 0.0021 | 0.0026 | 0.0009 | 0.0014 | 0.0025 | 0.0028 | 2.1686 | 2.7928 | 1.2878 | 1.1089 | True | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | ttc_decile | 5 | 37569 | 75 | 64 | 0.0013 | 0.0025 | 0.0026 | 0.0013 | 0.0018 | 0.0032 | 0.0035 | 1.8771 | 2.5234 | 1.3443 | 1.3650 | True | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | ttc_decile | 6 | 37053 | 98 | 86 | 0.0015 | 0.0033 | 0.0035 | 0.0017 | 0.0024 | 0.0039 | 0.0042 | 2.2337 | 2.3042 | 1.0315 | 1.2021 | False | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | ttc_decile | 7 | 36467 | 123 | 124 | 0.0024 | 0.0042 | 0.0053 | 0.0024 | 0.0031 | 0.0049 | 0.0052 | 1.7763 | 2.0849 | 1.1737 | 0.9854 | False | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | ttc_decile | 8 | 35470 | 165 | 157 | 0.0035 | 0.0058 | 0.0070 | 0.0033 | 0.0042 | 0.0063 | 0.0065 | 1.6841 | 1.8892 | 1.1218 | 0.9319 | False | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | ttc_decile | 9 | 33899 | 230 | 189 | 0.0046 | 0.0085 | 0.0089 | 0.0052 | 0.0061 | 0.0087 | 0.0087 | 1.8547 | 1.6526 | 0.8910 | 0.9763 | False | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | ttc_decile | 10 | 28630 | 539 | 421 | 0.0356 | 0.0238 | 0.0233 | 0.0389 | 0.0339 | 0.0201 | 0.0169 | 0.6697 | 0.5175 | 0.7728 | 0.7239 | True | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | dlq_state | 30-59 dpd | 1810 | 157 | 76 | 0.2402 | 0.1296 | 0.0809 | 0.2723 | 0.2399 | 0.1076 | 0.0735 | 0.5395 | 0.3953 | 0.7328 | 0.9078 | True | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | dlq_state | 60-89 dpd | 444 | 29 | 17 | 0.6541 | 0.2067 | 0.1700 | 0.7194 | 0.6902 | 0.2153 | 0.1212 | 0.3161 | 0.2993 | 0.9469 | 0.7127 | False | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | dlq_state | cured 1-3 months | 1868 | 125 | 68 | 0.0894 | 0.0845 | 0.0590 | 0.0978 | 0.0871 | 0.0598 | 0.0475 | 0.9445 | 0.6115 | 0.6474 | 0.8054 | True | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | dlq_state | cured 13+ months | 6717 | 135 | 101 | 0.0166 | 0.0252 | 0.0233 | 0.0145 | 0.0163 | 0.0190 | 0.0176 | 1.5231 | 1.3078 | 0.8586 | 0.7537 | False | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | dlq_state | cured 4-12 months | 3074 | 140 | 91 | 0.0417 | 0.0573 | 0.0467 | 0.0402 | 0.0384 | 0.0357 | 0.0311 | 1.3752 | 0.8873 | 0.6452 | 0.6669 | True | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | dlq_state | never 30+ dpd | 147256 | 1146 | 1016 | 0.0055 | 0.0095 | 0.0104 | 0.0053 | 0.0058 | 0.0099 | 0.0108 | 1.7181 | 1.8623 | 1.0840 | 1.0352 | False | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | ttc_decile | 1 | 13877 | 9 | 6 | 0.0003 | 0.0008 | 0.0006 | 0.0004 | 0.0006 | 0.0014 | 0.0016 | 2.6951 | 3.2686 | 1.2128 | 2.5561 | False | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | ttc_decile | 2 | 14270 | 11 | 11 | 0.0002 | 0.0009 | 0.0011 | 0.0008 | 0.0010 | 0.0022 | 0.0026 | 4.4165 | 2.8467 | 0.6446 | 2.3384 | True | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | ttc_decile | 3 | 14308 | 19 | 33 | 0.0010 | 0.0016 | 0.0034 | 0.0012 | 0.0015 | 0.0031 | 0.0036 | 1.5332 | 2.6661 | 1.7389 | 1.0644 | True | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | ttc_decile | 4 | 14663 | 26 | 30 | 0.0012 | 0.0022 | 0.0031 | 0.0016 | 0.0020 | 0.0041 | 0.0048 | 1.8606 | 2.5314 | 1.3605 | 1.5627 | True | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | ttc_decile | 5 | 14621 | 34 | 36 | 0.0018 | 0.0028 | 0.0037 | 0.0022 | 0.0026 | 0.0053 | 0.0062 | 1.5389 | 2.4226 | 1.5742 | 1.6892 | True | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | ttc_decile | 6 | 15136 | 66 | 71 | 0.0020 | 0.0053 | 0.0071 | 0.0030 | 0.0034 | 0.0068 | 0.0080 | 2.6939 | 2.2916 | 0.8506 | 1.1279 | False | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | ttc_decile | 7 | 15723 | 98 | 103 | 0.0043 | 0.0077 | 0.0100 | 0.0040 | 0.0046 | 0.0089 | 0.0105 | 1.8003 | 2.2146 | 1.2302 | 1.0528 | False | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | ttc_decile | 8 | 16720 | 166 | 150 | 0.0057 | 0.0123 | 0.0138 | 0.0057 | 0.0063 | 0.0117 | 0.0135 | 2.1437 | 2.0462 | 0.9545 | 0.9799 | False | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | ttc_decile | 9 | 18291 | 305 | 257 | 0.0098 | 0.0207 | 0.0217 | 0.0091 | 0.0099 | 0.0172 | 0.0192 | 2.1140 | 1.8904 | 0.8942 | 0.8849 | False | pdlife-0.2.0 shared fade |
| 0.0000 | development holdout 2000-16 | ttc_decile | 10 | 23560 | 998 | 672 | 0.0640 | 0.0544 | 0.0466 | 0.0654 | 0.0623 | 0.0451 | 0.0397 | 0.8491 | 0.6900 | 0.8126 | 0.8538 | False | pdlife-0.2.0 shared fade |
| 0.0000 | OOT 2017-21 | dlq_state | 30-59 dpd | 2673 | 132 | 81 | 0.1383 | 0.0664 | 0.0508 | 0.1252 | 0.0974 | 0.0456 | 0.0306 | 0.4806 | 0.3645 | 0.7585 | 0.6010 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | dlq_state | 60-89 dpd | 826 | 30 | 8 | 0.3152 | 0.0677 | 0.0239 | 0.4422 | 0.3929 | 0.0506 | 0.0274 | 0.2149 | 0.1145 | 0.5327 | 1.1434 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | dlq_state | cured 1-3 months | 3914 | 112 | 77 | 0.0389 | 0.0366 | 0.0309 | 0.0364 | 0.0308 | 0.0265 | 0.0226 | 0.9401 | 0.7284 | 0.7748 | 0.7313 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | dlq_state | cured 13+ months | 18221 | 140 | 113 | 0.0062 | 0.0094 | 0.0091 | 0.0045 | 0.0063 | 0.0089 | 0.0092 | 1.5244 | 1.9848 | 1.3020 | 1.0117 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | dlq_state | cured 4-12 months | 7359 | 104 | 105 | 0.0135 | 0.0177 | 0.0214 | 0.0131 | 0.0130 | 0.0179 | 0.0155 | 1.3115 | 1.3596 | 1.0367 | 0.7228 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | dlq_state | never 30+ dpd | 327737 | 865 | 817 | 0.0018 | 0.0032 | 0.0038 | 0.0020 | 0.0025 | 0.0038 | 0.0040 | 1.7655 | 1.8442 | 1.0446 | 1.0524 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | ttc_decile | 1 | 38313 | 16 | 25 | 0.0004 | 0.0005 | 0.0010 | 0.0002 | 0.0005 | 0.0009 | 0.0011 | 1.3817 | 4.2540 | 3.0788 | 1.1780 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | ttc_decile | 2 | 37920 | 28 | 36 | 0.0006 | 0.0009 | 0.0014 | 0.0004 | 0.0008 | 0.0014 | 0.0017 | 1.4581 | 3.4275 | 2.3507 | 1.2375 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | ttc_decile | 3 | 37882 | 43 | 34 | 0.0009 | 0.0014 | 0.0013 | 0.0006 | 0.0011 | 0.0019 | 0.0022 | 1.5752 | 2.9703 | 1.8856 | 1.6763 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | ttc_decile | 4 | 37527 | 66 | 65 | 0.0010 | 0.0021 | 0.0026 | 0.0009 | 0.0014 | 0.0024 | 0.0028 | 2.1686 | 2.6801 | 1.2359 | 1.0717 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | ttc_decile | 5 | 37569 | 75 | 64 | 0.0013 | 0.0025 | 0.0026 | 0.0013 | 0.0019 | 0.0031 | 0.0034 | 1.8771 | 2.4291 | 1.2941 | 1.3238 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | ttc_decile | 6 | 37053 | 98 | 86 | 0.0015 | 0.0033 | 0.0035 | 0.0017 | 0.0024 | 0.0038 | 0.0041 | 2.2337 | 2.2242 | 0.9957 | 1.1693 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | ttc_decile | 7 | 36467 | 123 | 124 | 0.0024 | 0.0042 | 0.0053 | 0.0024 | 0.0031 | 0.0048 | 0.0051 | 1.7763 | 2.0233 | 1.1391 | 0.9644 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | ttc_decile | 8 | 35470 | 165 | 157 | 0.0035 | 0.0058 | 0.0070 | 0.0033 | 0.0042 | 0.0062 | 0.0064 | 1.6841 | 1.8454 | 1.0958 | 0.9188 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | ttc_decile | 9 | 33899 | 230 | 189 | 0.0046 | 0.0085 | 0.0089 | 0.0052 | 0.0061 | 0.0086 | 0.0087 | 1.8547 | 1.6401 | 0.8843 | 0.9791 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | OOT 2017-21 | ttc_decile | 10 | 28630 | 539 | 421 | 0.0356 | 0.0238 | 0.0233 | 0.0389 | 0.0339 | 0.0211 | 0.0179 | 0.6697 | 0.5414 | 0.8084 | 0.7670 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | dlq_state | 30-59 dpd | 1810 | 157 | 76 | 0.2402 | 0.1296 | 0.0809 | 0.2723 | 0.2423 | 0.1092 | 0.0720 | 0.5395 | 0.4010 | 0.7433 | 0.8894 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | dlq_state | 60-89 dpd | 444 | 29 | 17 | 0.6541 | 0.2067 | 0.1700 | 0.7194 | 0.6906 | 0.1169 | 0.0586 | 0.3161 | 0.1625 | 0.5141 | 0.3448 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | dlq_state | cured 1-3 months | 1868 | 125 | 68 | 0.0894 | 0.0845 | 0.0590 | 0.0978 | 0.0857 | 0.0732 | 0.0595 | 0.9445 | 0.7479 | 0.7919 | 1.0092 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | dlq_state | cured 13+ months | 6717 | 135 | 101 | 0.0166 | 0.0252 | 0.0233 | 0.0145 | 0.0154 | 0.0209 | 0.0204 | 1.5231 | 1.4402 | 0.9456 | 0.8729 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | dlq_state | cured 4-12 months | 3074 | 140 | 91 | 0.0417 | 0.0573 | 0.0467 | 0.0402 | 0.0378 | 0.0503 | 0.0414 | 1.3752 | 1.2508 | 0.9095 | 0.8878 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | dlq_state | never 30+ dpd | 147256 | 1146 | 1016 | 0.0055 | 0.0095 | 0.0104 | 0.0053 | 0.0058 | 0.0095 | 0.0104 | 1.7181 | 1.7861 | 1.0396 | 0.9990 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | ttc_decile | 1 | 13877 | 9 | 6 | 0.0003 | 0.0008 | 0.0006 | 0.0004 | 0.0006 | 0.0013 | 0.0016 | 2.6951 | 3.1460 | 1.1673 | 2.4799 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | ttc_decile | 2 | 14270 | 11 | 11 | 0.0002 | 0.0009 | 0.0011 | 0.0008 | 0.0011 | 0.0021 | 0.0025 | 4.4165 | 2.7420 | 0.6209 | 2.2699 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | ttc_decile | 3 | 14308 | 19 | 33 | 0.0010 | 0.0016 | 0.0034 | 0.0012 | 0.0015 | 0.0030 | 0.0035 | 1.5332 | 2.5709 | 1.6768 | 1.0340 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | ttc_decile | 4 | 14663 | 26 | 30 | 0.0012 | 0.0022 | 0.0031 | 0.0016 | 0.0020 | 0.0039 | 0.0046 | 1.8606 | 2.4412 | 1.3121 | 1.5177 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | ttc_decile | 5 | 14621 | 34 | 36 | 0.0018 | 0.0028 | 0.0037 | 0.0022 | 0.0026 | 0.0051 | 0.0061 | 1.5389 | 2.3386 | 1.5196 | 1.6423 | True | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | ttc_decile | 6 | 15136 | 66 | 71 | 0.0020 | 0.0053 | 0.0071 | 0.0030 | 0.0035 | 0.0066 | 0.0078 | 2.6939 | 2.2135 | 0.8217 | 1.0972 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | ttc_decile | 7 | 15723 | 98 | 103 | 0.0043 | 0.0077 | 0.0100 | 0.0040 | 0.0046 | 0.0086 | 0.0102 | 1.8003 | 2.1414 | 1.1895 | 1.0248 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | ttc_decile | 8 | 16720 | 166 | 150 | 0.0057 | 0.0123 | 0.0138 | 0.0057 | 0.0064 | 0.0113 | 0.0132 | 2.1437 | 1.9821 | 0.9246 | 0.9556 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | ttc_decile | 9 | 18291 | 305 | 257 | 0.0098 | 0.0207 | 0.0217 | 0.0091 | 0.0099 | 0.0167 | 0.0188 | 2.1140 | 1.8395 | 0.8701 | 0.8661 | False | pdlife-0.4.0 state decay, plain splice |
| 0.0000 | development holdout 2000-16 | ttc_decile | 10 | 23560 | 998 | 672 | 0.0640 | 0.0544 | 0.0466 | 0.0654 | 0.0620 | 0.0469 | 0.0413 | 0.8491 | 0.7174 | 0.8449 | 0.8867 | False | pdlife-0.4.0 state decay, plain splice |
| inf | OOT 2017-21 | dlq_state | 30-59 dpd | 2673 | 132 | 81 | 0.1383 | 0.0664 | 0.0508 | 0.1252 | 0.0974 | 0.0589 | 0.0393 | 0.4806 | 0.4704 | 0.9789 | 0.7737 | False | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | dlq_state | 60-89 dpd | 826 | 30 | 8 | 0.3152 | 0.0677 | 0.0239 | 0.4422 | 0.3929 | 0.0598 | 0.0325 | 0.2149 | 0.1352 | 0.6289 | 1.3569 | True | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | dlq_state | cured 1-3 months | 3914 | 112 | 77 | 0.0389 | 0.0366 | 0.0309 | 0.0364 | 0.0308 | 0.0309 | 0.0261 | 0.9401 | 0.8503 | 0.9045 | 0.8448 | False | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | dlq_state | cured 13+ months | 18221 | 140 | 113 | 0.0062 | 0.0094 | 0.0091 | 0.0045 | 0.0063 | 0.0061 | 0.0064 | 1.5244 | 1.3663 | 0.8963 | 0.7023 | False | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | dlq_state | cured 4-12 months | 7359 | 104 | 105 | 0.0135 | 0.0177 | 0.0214 | 0.0131 | 0.0130 | 0.0177 | 0.0152 | 1.3115 | 1.3475 | 1.0275 | 0.7100 | False | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | dlq_state | never 30+ dpd | 327737 | 865 | 817 | 0.0018 | 0.0032 | 0.0038 | 0.0020 | 0.0025 | 0.0029 | 0.0031 | 1.7655 | 1.4271 | 0.8083 | 0.8104 | False | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | ttc_decile | 1 | 38313 | 16 | 25 | 0.0004 | 0.0005 | 0.0010 | 0.0002 | 0.0005 | 0.0004 | 0.0005 | 1.3817 | 1.9124 | 1.3841 | 0.5360 | True | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | ttc_decile | 2 | 37920 | 28 | 36 | 0.0006 | 0.0009 | 0.0014 | 0.0004 | 0.0008 | 0.0007 | 0.0009 | 1.4581 | 1.7651 | 1.2105 | 0.6436 | False | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | ttc_decile | 3 | 37882 | 43 | 34 | 0.0009 | 0.0014 | 0.0013 | 0.0006 | 0.0011 | 0.0011 | 0.0012 | 1.5752 | 1.6782 | 1.0653 | 0.9546 | False | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | ttc_decile | 4 | 37527 | 66 | 65 | 0.0010 | 0.0021 | 0.0026 | 0.0009 | 0.0014 | 0.0015 | 0.0017 | 2.1686 | 1.6274 | 0.7504 | 0.6553 | True | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | ttc_decile | 5 | 37569 | 75 | 64 | 0.0013 | 0.0025 | 0.0026 | 0.0013 | 0.0019 | 0.0020 | 0.0022 | 1.8771 | 1.5762 | 0.8397 | 0.8663 | False | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | ttc_decile | 6 | 37053 | 98 | 86 | 0.0015 | 0.0033 | 0.0035 | 0.0017 | 0.0024 | 0.0026 | 0.0029 | 2.2337 | 1.5324 | 0.6860 | 0.8121 | True | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | ttc_decile | 7 | 36467 | 123 | 124 | 0.0024 | 0.0042 | 0.0053 | 0.0024 | 0.0031 | 0.0035 | 0.0038 | 1.7763 | 1.4870 | 0.8371 | 0.7145 | False | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | ttc_decile | 8 | 35470 | 165 | 157 | 0.0035 | 0.0058 | 0.0070 | 0.0033 | 0.0042 | 0.0048 | 0.0051 | 1.6841 | 1.4430 | 0.8568 | 0.7245 | False | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | ttc_decile | 9 | 33899 | 230 | 189 | 0.0046 | 0.0085 | 0.0089 | 0.0052 | 0.0061 | 0.0073 | 0.0074 | 1.8547 | 1.3826 | 0.7454 | 0.8347 | True | pdlife-0.3.0 carry tau=inf |
| inf | OOT 2017-21 | ttc_decile | 10 | 28630 | 539 | 421 | 0.0356 | 0.0238 | 0.0233 | 0.0389 | 0.0339 | 0.0233 | 0.0196 | 0.6697 | 0.5978 | 0.8927 | 0.8387 | False | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | dlq_state | 30-59 dpd | 1810 | 157 | 76 | 0.2402 | 0.1296 | 0.0809 | 0.2723 | 0.2423 | 0.1288 | 0.0866 | 0.5395 | 0.4728 | 0.8765 | 1.0705 | False | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | dlq_state | 60-89 dpd | 444 | 29 | 17 | 0.6541 | 0.2067 | 0.1700 | 0.7194 | 0.6906 | 0.1296 | 0.0665 | 0.3161 | 0.1801 | 0.5699 | 0.3915 | True | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | dlq_state | cured 1-3 months | 1868 | 125 | 68 | 0.0894 | 0.0845 | 0.0590 | 0.0978 | 0.0857 | 0.0853 | 0.0706 | 0.9445 | 0.8719 | 0.9232 | 1.1968 | False | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | dlq_state | cured 13+ months | 6717 | 135 | 101 | 0.0166 | 0.0252 | 0.0233 | 0.0145 | 0.0154 | 0.0197 | 0.0191 | 1.5231 | 1.3554 | 0.8899 | 0.8204 | False | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | dlq_state | cured 4-12 months | 3074 | 140 | 91 | 0.0417 | 0.0573 | 0.0467 | 0.0402 | 0.0378 | 0.0541 | 0.0448 | 1.3752 | 1.3453 | 0.9783 | 0.9599 | False | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | dlq_state | never 30+ dpd | 147256 | 1146 | 1016 | 0.0055 | 0.0095 | 0.0104 | 0.0053 | 0.0058 | 0.0087 | 0.0094 | 1.7181 | 1.6295 | 0.9485 | 0.9057 | False | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | ttc_decile | 1 | 13877 | 9 | 6 | 0.0003 | 0.0008 | 0.0006 | 0.0004 | 0.0006 | 0.0009 | 0.0010 | 2.6951 | 2.1274 | 0.7893 | 1.6393 | True | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | ttc_decile | 2 | 14270 | 11 | 11 | 0.0002 | 0.0009 | 0.0011 | 0.0008 | 0.0011 | 0.0016 | 0.0018 | 4.4165 | 2.0274 | 0.4590 | 1.6452 | True | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | ttc_decile | 3 | 14308 | 19 | 33 | 0.0010 | 0.0016 | 0.0034 | 0.0012 | 0.0015 | 0.0023 | 0.0027 | 1.5332 | 1.9937 | 1.3004 | 0.7871 | True | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | ttc_decile | 4 | 14663 | 26 | 30 | 0.0012 | 0.0022 | 0.0031 | 0.0016 | 0.0020 | 0.0031 | 0.0037 | 1.8606 | 1.9580 | 1.0523 | 1.1992 | False | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | ttc_decile | 5 | 14621 | 34 | 36 | 0.0018 | 0.0028 | 0.0037 | 0.0022 | 0.0026 | 0.0042 | 0.0049 | 1.5389 | 1.9365 | 1.2583 | 1.3397 | True | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | ttc_decile | 6 | 15136 | 66 | 71 | 0.0020 | 0.0053 | 0.0071 | 0.0030 | 0.0035 | 0.0056 | 0.0066 | 2.6939 | 1.8962 | 0.7039 | 0.9275 | True | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | ttc_decile | 7 | 15723 | 98 | 103 | 0.0043 | 0.0077 | 0.0100 | 0.0040 | 0.0046 | 0.0076 | 0.0089 | 1.8003 | 1.8826 | 1.0457 | 0.8913 | False | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | ttc_decile | 8 | 16720 | 166 | 150 | 0.0057 | 0.0123 | 0.0138 | 0.0057 | 0.0064 | 0.0103 | 0.0119 | 2.1437 | 1.7992 | 0.8393 | 0.8624 | False | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | ttc_decile | 9 | 18291 | 305 | 257 | 0.0098 | 0.0207 | 0.0217 | 0.0091 | 0.0099 | 0.0156 | 0.0176 | 2.1140 | 1.7206 | 0.8139 | 0.8100 | False | pdlife-0.3.0 carry tau=inf |
| inf | development holdout 2000-16 | ttc_decile | 10 | 23560 | 998 | 672 | 0.0640 | 0.0544 | 0.0466 | 0.0654 | 0.0620 | 0.0491 | 0.0432 | 0.8491 | 0.7508 | 0.8842 | 0.9276 | False | pdlife-0.3.0 carry tau=inf |
| 3.0000 | OOT 2017-21 | dlq_state | 30-59 dpd | 2673 | 132 | 81 | 0.1383 | 0.0664 | 0.0508 | 0.1252 | 0.0974 | 0.0541 | 0.0342 | 0.4806 | 0.4322 | 0.8994 | 0.6734 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | dlq_state | 60-89 dpd | 826 | 30 | 8 | 0.3152 | 0.0677 | 0.0239 | 0.4422 | 0.3929 | 0.0566 | 0.0296 | 0.2149 | 0.1281 | 0.5957 | 1.2369 | True | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | dlq_state | cured 1-3 months | 3914 | 112 | 77 | 0.0389 | 0.0366 | 0.0309 | 0.0364 | 0.0308 | 0.0291 | 0.0238 | 0.9401 | 0.7999 | 0.8508 | 0.7704 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | dlq_state | cured 13+ months | 18221 | 140 | 113 | 0.0062 | 0.0094 | 0.0091 | 0.0045 | 0.0063 | 0.0067 | 0.0074 | 1.5244 | 1.4790 | 0.9702 | 0.8119 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | dlq_state | cured 4-12 months | 7359 | 104 | 105 | 0.0135 | 0.0177 | 0.0214 | 0.0131 | 0.0130 | 0.0174 | 0.0150 | 1.3115 | 1.3258 | 1.0109 | 0.6993 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | dlq_state | never 30+ dpd | 327737 | 865 | 817 | 0.0018 | 0.0032 | 0.0038 | 0.0020 | 0.0025 | 0.0031 | 0.0034 | 1.7655 | 1.5074 | 0.8538 | 0.8983 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | ttc_decile | 1 | 38313 | 16 | 25 | 0.0004 | 0.0005 | 0.0010 | 0.0002 | 0.0005 | 0.0005 | 0.0007 | 1.3817 | 2.3570 | 1.7059 | 0.7674 | True | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | ttc_decile | 2 | 37920 | 28 | 36 | 0.0006 | 0.0009 | 0.0014 | 0.0004 | 0.0008 | 0.0009 | 0.0012 | 1.4581 | 2.0930 | 1.4354 | 0.8635 | True | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | ttc_decile | 3 | 37882 | 43 | 34 | 0.0009 | 0.0014 | 0.0013 | 0.0006 | 0.0011 | 0.0012 | 0.0016 | 1.5752 | 1.9395 | 1.2313 | 1.2267 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | ttc_decile | 4 | 37527 | 66 | 65 | 0.0010 | 0.0021 | 0.0026 | 0.0009 | 0.0014 | 0.0017 | 0.0021 | 2.1686 | 1.8439 | 0.8503 | 0.8142 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | ttc_decile | 5 | 37569 | 75 | 64 | 0.0013 | 0.0025 | 0.0026 | 0.0013 | 0.0019 | 0.0022 | 0.0027 | 1.8771 | 1.7533 | 0.9341 | 1.0421 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | ttc_decile | 6 | 37053 | 98 | 86 | 0.0015 | 0.0033 | 0.0035 | 0.0017 | 0.0024 | 0.0029 | 0.0034 | 2.2337 | 1.6769 | 0.7507 | 0.9499 | True | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | ttc_decile | 7 | 36467 | 123 | 124 | 0.0024 | 0.0042 | 0.0053 | 0.0024 | 0.0031 | 0.0038 | 0.0043 | 1.7763 | 1.5983 | 0.8998 | 0.8104 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | ttc_decile | 8 | 35470 | 165 | 157 | 0.0035 | 0.0058 | 0.0070 | 0.0033 | 0.0042 | 0.0051 | 0.0056 | 1.6841 | 1.5247 | 0.9054 | 0.7977 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | ttc_decile | 9 | 33899 | 230 | 189 | 0.0046 | 0.0085 | 0.0089 | 0.0052 | 0.0061 | 0.0075 | 0.0079 | 1.8547 | 1.4292 | 0.7706 | 0.8843 | True | pdlife-0.4.0 carry tau=3 |
| 3.0000 | OOT 2017-21 | ttc_decile | 10 | 28630 | 539 | 421 | 0.0356 | 0.0238 | 0.0233 | 0.0389 | 0.0339 | 0.0223 | 0.0184 | 0.6697 | 0.5721 | 0.8543 | 0.7868 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | dlq_state | 30-59 dpd | 1810 | 157 | 76 | 0.2402 | 0.1296 | 0.0809 | 0.2723 | 0.2423 | 0.1224 | 0.0787 | 0.5395 | 0.4494 | 0.8330 | 0.9725 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | dlq_state | 60-89 dpd | 444 | 29 | 17 | 0.6541 | 0.2067 | 0.1700 | 0.7194 | 0.6906 | 0.1255 | 0.0624 | 0.3161 | 0.1745 | 0.5521 | 0.3668 | True | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | dlq_state | cured 1-3 months | 1868 | 125 | 68 | 0.0894 | 0.0845 | 0.0590 | 0.0978 | 0.0857 | 0.0812 | 0.0646 | 0.9445 | 0.8306 | 0.8795 | 1.0946 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | dlq_state | cured 13+ months | 6717 | 135 | 101 | 0.0166 | 0.0252 | 0.0233 | 0.0145 | 0.0154 | 0.0198 | 0.0194 | 1.5231 | 1.3633 | 0.8951 | 0.8335 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | dlq_state | cured 4-12 months | 3074 | 140 | 91 | 0.0417 | 0.0573 | 0.0467 | 0.0402 | 0.0378 | 0.0527 | 0.0428 | 1.3752 | 1.3100 | 0.9526 | 0.9176 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | dlq_state | never 30+ dpd | 147256 | 1146 | 1016 | 0.0055 | 0.0095 | 0.0104 | 0.0053 | 0.0058 | 0.0088 | 0.0098 | 1.7181 | 1.6597 | 0.9660 | 0.9418 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | ttc_decile | 1 | 13877 | 9 | 6 | 0.0003 | 0.0008 | 0.0006 | 0.0004 | 0.0006 | 0.0010 | 0.0012 | 2.6951 | 2.3329 | 0.8656 | 1.9636 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | ttc_decile | 2 | 14270 | 11 | 11 | 0.0002 | 0.0009 | 0.0011 | 0.0008 | 0.0011 | 0.0017 | 0.0021 | 4.4165 | 2.1742 | 0.4923 | 1.8907 | True | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | ttc_decile | 3 | 14308 | 19 | 33 | 0.0010 | 0.0016 | 0.0034 | 0.0012 | 0.0015 | 0.0024 | 0.0030 | 1.5332 | 2.1147 | 1.3792 | 0.8857 | True | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | ttc_decile | 4 | 14663 | 26 | 30 | 0.0012 | 0.0022 | 0.0031 | 0.0016 | 0.0020 | 0.0033 | 0.0041 | 1.8606 | 2.0601 | 1.1072 | 1.3274 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | ttc_decile | 5 | 14621 | 34 | 36 | 0.0018 | 0.0028 | 0.0037 | 0.0022 | 0.0026 | 0.0044 | 0.0054 | 1.5389 | 2.0218 | 1.3138 | 1.4627 | True | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | ttc_decile | 6 | 15136 | 66 | 71 | 0.0020 | 0.0053 | 0.0071 | 0.0030 | 0.0035 | 0.0058 | 0.0071 | 2.6939 | 1.9631 | 0.7287 | 0.9965 | True | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | ttc_decile | 7 | 15723 | 98 | 103 | 0.0043 | 0.0077 | 0.0100 | 0.0040 | 0.0046 | 0.0078 | 0.0094 | 1.8003 | 1.9354 | 1.0751 | 0.9450 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | ttc_decile | 8 | 16720 | 166 | 150 | 0.0057 | 0.0123 | 0.0138 | 0.0057 | 0.0064 | 0.0105 | 0.0124 | 2.1437 | 1.8346 | 0.8558 | 0.8988 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | ttc_decile | 9 | 18291 | 305 | 257 | 0.0098 | 0.0207 | 0.0217 | 0.0091 | 0.0099 | 0.0158 | 0.0180 | 2.1140 | 1.7406 | 0.8234 | 0.8304 | False | pdlife-0.4.0 carry tau=3 |
| 3.0000 | development holdout 2000-16 | ttc_decile | 10 | 23560 | 998 | 672 | 0.0640 | 0.0544 | 0.0466 | 0.0654 | 0.0620 | 0.0482 | 0.0420 | 0.8491 | 0.7369 | 0.8679 | 0.9014 | False | pdlife-0.4.0 carry tau=3 |

## Regional year-1 (CO-3)
| breakdown | period | segment | n | actual | pit12 | hazard_h2 | hazard_h1 | hazard_to_pit | actual_to_hazard | actual_to_pit | within_tolerance |
|---|---|---|---|---|---|---|---|---|---|---|---|
| period x region | 2000-06 | CA/FL/NV/AZ | 8266 | 0.0042 | 0.0057 | 0.0052 | 0.0061 | 0.9194 | 0.8104 | 0.7450 | True |
| period x region | 2000-06 | other states | 33246 | 0.0066 | 0.0076 | 0.0070 | 0.0080 | 0.9148 | 0.9455 | 0.8649 | True |
| period x region | 2012-16 | CA/FL/NV/AZ | 12252 | 0.0074 | 0.0076 | 0.0077 | 0.0091 | 1.0018 | 0.9698 | 0.9715 | True |
| period x region | 2012-16 | other states | 49182 | 0.0073 | 0.0078 | 0.0083 | 0.0103 | 1.0638 | 0.8803 | 0.9365 | True |
| period x region | 2017-19 | CA/FL/NV/AZ | 48733 | 0.0051 | 0.0046 | 0.0045 | 0.0058 | 0.9845 | 1.1237 | 1.1063 | True |
| period x region | 2017-19 | other states | 175545 | 0.0050 | 0.0051 | 0.0051 | 0.0066 | 1.0019 | 0.9885 | 0.9903 | True |
| period x region | 2022-23 | CA/FL/NV/AZ | 28806 | 0.0043 | 0.0042 | 0.0039 | 0.0050 | 0.9335 | 1.0870 | 1.0147 | True |
| period x region | 2022-23 | other states | 106286 | 0.0044 | 0.0046 | 0.0042 | 0.0054 | 0.9197 | 1.0421 | 0.9585 | True |
| period x region | COVID 2020-21 | CA/FL/NV/AZ | 28876 | 0.0030 | 0.0040 | 0.0043 | 0.0053 | 1.0753 | 0.7102 | 0.7637 | True |
| period x region | COVID 2020-21 | other states | 106587 | 0.0035 | 0.0042 | 0.0046 | 0.0059 | 1.0961 | 0.7527 | 0.8250 | True |
| period x region | crisis 2007-11 | CA/FL/NV/AZ | 10701 | 0.0375 | 0.0281 | 0.0296 | 0.0316 | 1.0533 | 1.2652 | 1.3327 | True |
| period x region | crisis 2007-11 | other states | 47390 | 0.0177 | 0.0194 | 0.0188 | 0.0214 | 0.9695 | 0.9440 | 0.9152 | True |

## Vintage curves (dev_holdout loans, realised macro)
| vintage | region | years | at_risk | actual_default | actual_prepay | pred_default_H2 | pred_prepay_H2 | pred_default_H1 | pred_prepay_H1 | loans | actual_to_pred_default_H2 | actual_to_pred_prepay_H2 | actual_to_pred_default_H1 | actual_to_pred_prepay_H1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2003 | all | 1 | 9174.0000 | 0.0019 | 0.0959 | 0.0021 | 0.0856 | 0.0026 | 0.0828 | 9872.0000 | 0.9293 | 1.1195 | 0.7428 | 1.1579 |
| 2003 | all | 2 | 8043.0000 | 0.0045 | 0.2062 | 0.0060 | 0.1951 | 0.0066 | 0.1892 | 9872.0000 | 0.7386 | 1.0568 | 0.6773 | 1.0896 |
| 2003 | all | 3 | 7108.0000 | 0.0072 | 0.2904 | 0.0099 | 0.2960 | 0.0107 | 0.2913 | 9872.0000 | 0.7256 | 0.9810 | 0.6762 | 0.9969 |
| 2003 | all | 5 | 5892.0000 | 0.0122 | 0.4024 | 0.0191 | 0.4246 | 0.0207 | 0.4157 | 9872.0000 | 0.6392 | 0.9478 | 0.5889 | 0.9681 |
| 2003 | all | 8 | 3611.0000 | 0.0253 | 0.6266 | 0.0396 | 0.6261 | 0.0433 | 0.6097 | 9872.0000 | 0.6391 | 1.0007 | 0.5839 | 1.0277 |
| 2004 | all | 1 | 9397.0000 | 0.0028 | 0.0944 | 0.0027 | 0.0970 | 0.0033 | 0.0970 | 10052.0000 | 1.0266 | 0.9730 | 0.8435 | 0.9728 |
| 2004 | all | 2 | 8240.0000 | 0.0083 | 0.1926 | 0.0080 | 0.1827 | 0.0086 | 0.1805 | 10052.0000 | 1.0280 | 1.0545 | 0.9630 | 1.0669 |
| 2004 | all | 3 | 7411.0000 | 0.0144 | 0.2655 | 0.0139 | 0.2684 | 0.0147 | 0.2668 | 10052.0000 | 1.0366 | 0.9893 | 0.9855 | 0.9954 |
| 2004 | all | 5 | 5868.0000 | 0.0323 | 0.4112 | 0.0363 | 0.4136 | 0.0388 | 0.4098 | 10052.0000 | 0.8901 | 0.9943 | 0.8314 | 1.0034 |
| 2004 | all | 8 | 3064.0000 | 0.0560 | 0.6630 | 0.0651 | 0.6505 | 0.0698 | 0.6448 | 10052.0000 | 0.8609 | 1.0193 | 0.8019 | 1.0283 |
| 2005 | all | 1 | 9509.0000 | 0.0042 | 0.0651 | 0.0029 | 0.0707 | 0.0035 | 0.0693 | 10007.0000 | 1.4479 | 0.9219 | 1.2030 | 0.9396 |
| 2005 | all | 2 | 8641.0000 | 0.0111 | 0.1458 | 0.0097 | 0.1474 | 0.0101 | 0.1429 | 10007.0000 | 1.1488 | 0.9889 | 1.1003 | 1.0200 |
| 2005 | all | 3 | 7793.0000 | 0.0214 | 0.2188 | 0.0215 | 0.2321 | 0.0220 | 0.2275 | 10007.0000 | 0.9980 | 0.9425 | 0.9740 | 0.9615 |
| 2005 | all | 5 | 5561.0000 | 0.0637 | 0.4100 | 0.0627 | 0.4277 | 0.0655 | 0.4257 | 10007.0000 | 1.0157 | 0.9586 | 0.9724 | 0.9630 |
| 2005 | all | 8 | 2170.0000 | 0.0930 | 0.7071 | 0.0949 | 0.6758 | 0.0990 | 0.6756 | 10007.0000 | 0.9799 | 1.0464 | 0.9397 | 1.0466 |
| 2005 | CA/FL/NV/AZ | 1 | 1983.0000 | 0.0014 | 0.0955 | 0.0025 | 0.0725 | 0.0031 | 0.0705 | 2138.0000 | 0.5584 | 1.3180 | 0.4569 | 1.3544 |
| 2005 | CA/FL/NV/AZ | 2 | 1755.0000 | 0.0070 | 0.1916 | 0.0089 | 0.1501 | 0.0093 | 0.1444 | 2138.0000 | 0.7910 | 1.2765 | 0.7566 | 1.3269 |
| 2005 | CA/FL/NV/AZ | 3 | 1604.0000 | 0.0244 | 0.2455 | 0.0236 | 0.2337 | 0.0240 | 0.2277 | 2138.0000 | 1.0308 | 1.0503 | 1.0140 | 1.0782 |
| 2005 | CA/FL/NV/AZ | 5 | 1189.0000 | 0.1059 | 0.3570 | 0.0891 | 0.4178 | 0.0924 | 0.4139 | 2138.0000 | 1.1885 | 0.8547 | 1.1461 | 0.8625 |
| 2005 | CA/FL/NV/AZ | 8 | 432.0000 | 0.1607 | 0.6565 | 0.1421 | 0.6447 | 0.1467 | 0.6424 | 2138.0000 | 1.1313 | 1.0182 | 1.0956 | 1.0219 |
| 2005 | other states | 1 | 7526.0000 | 0.0050 | 0.0569 | 0.0030 | 0.0702 | 0.0036 | 0.0690 | 7869.0000 | 1.6501 | 0.8108 | 1.3759 | 0.8244 |
| 2005 | other states | 2 | 6886.0000 | 0.0122 | 0.1334 | 0.0099 | 0.1467 | 0.0103 | 0.1426 | 7869.0000 | 1.2362 | 0.9090 | 1.1845 | 0.9356 |
| 2005 | other states | 3 | 6189.0000 | 0.0206 | 0.2115 | 0.0209 | 0.2317 | 0.0214 | 0.2275 | 7869.0000 | 0.9879 | 0.9130 | 0.9619 | 0.9298 |
| 2005 | other states | 5 | 4372.0000 | 0.0522 | 0.4243 | 0.0555 | 0.4304 | 0.0581 | 0.4289 | 7869.0000 | 0.9404 | 0.9859 | 0.8975 | 0.9894 |
| 2005 | other states | 8 | 1738.0000 | 0.0746 | 0.7208 | 0.0821 | 0.6842 | 0.0860 | 0.6846 | 7869.0000 | 0.9088 | 1.0535 | 0.8675 | 1.0529 |
| 2006 | all | 1 | 9240.0000 | 0.0052 | 0.0781 | 0.0038 | 0.0965 | 0.0044 | 0.0961 | 9806.0000 | 1.3817 | 0.8094 | 1.1767 | 0.8131 |
| 2006 | all | 2 | 7964.0000 | 0.0225 | 0.1973 | 0.0172 | 0.2237 | 0.0173 | 0.2227 | 9806.0000 | 1.3100 | 0.8817 | 1.3019 | 0.8858 |
| 2006 | all | 3 | 6389.0000 | 0.0540 | 0.3455 | 0.0467 | 0.3577 | 0.0470 | 0.3624 | 9806.0000 | 1.1568 | 0.9660 | 1.1500 | 0.9533 |
| 2006 | all | 5 | 3594.0000 | 0.1055 | 0.5511 | 0.0920 | 0.5664 | 0.0938 | 0.5785 | 9806.0000 | 1.1463 | 0.9731 | 1.1238 | 0.9527 |
| 2006 | all | 8 | 1235.0000 | 0.1307 | 0.7499 | 0.1146 | 0.7464 | 0.1161 | 0.7560 | 9806.0000 | 1.1403 | 1.0046 | 1.1262 | 0.9919 |
| 2006 | CA/FL/NV/AZ | 1 | 1611.0000 | 0.0064 | 0.0947 | 0.0036 | 0.0973 | 0.0042 | 0.0957 | 1734.0000 | 1.7858 | 0.9735 | 1.4981 | 0.9895 |
| 2006 | CA/FL/NV/AZ | 2 | 1409.0000 | 0.0375 | 0.1762 | 0.0217 | 0.2217 | 0.0216 | 0.2186 | 1734.0000 | 1.7276 | 0.7947 | 1.7377 | 0.8059 |
| 2006 | CA/FL/NV/AZ | 3 | 1205.0000 | 0.1028 | 0.2432 | 0.0725 | 0.3470 | 0.0729 | 0.3483 | 1734.0000 | 1.4184 | 0.7008 | 1.4114 | 0.6982 |
| 2006 | CA/FL/NV/AZ | 5 | 760.0000 | 0.2105 | 0.3751 | 0.1552 | 0.5348 | 0.1594 | 0.5404 | 1734.0000 | 1.3564 | 0.7014 | 1.3206 | 0.6942 |
| 2006 | CA/FL/NV/AZ | 8 | 223.0000 | 0.2545 | 0.6269 | 0.1918 | 0.6887 | 0.1954 | 0.6921 | 1734.0000 | 1.3264 | 0.9102 | 1.3025 | 0.9057 |
| 2006 | other states | 1 | 7629.0000 | 0.0050 | 0.0746 | 0.0038 | 0.0964 | 0.0045 | 0.0962 | 8072.0000 | 1.3007 | 0.7738 | 1.1111 | 0.7754 |
| 2006 | other states | 2 | 6555.0000 | 0.0192 | 0.2018 | 0.0162 | 0.2241 | 0.0163 | 0.2236 | 8072.0000 | 1.1894 | 0.9002 | 1.1781 | 0.9026 |
| 2006 | other states | 3 | 5184.0000 | 0.0436 | 0.3675 | 0.0412 | 0.3600 | 0.0414 | 0.3655 | 8072.0000 | 1.0579 | 1.0209 | 1.0512 | 1.0056 |
| 2006 | other states | 5 | 2834.0000 | 0.0829 | 0.5889 | 0.0784 | 0.5732 | 0.0798 | 0.5867 | 8072.0000 | 1.0572 | 1.0275 | 1.0395 | 1.0038 |
| 2006 | other states | 8 | 1012.0000 | 0.1041 | 0.7763 | 0.0980 | 0.7588 | 0.0990 | 0.7697 | 8072.0000 | 1.0623 | 1.0230 | 1.0518 | 1.0085 |
| 2007 | all | 1 | 9173.0000 | 0.0138 | 0.0885 | 0.0070 | 0.1066 | 0.0080 | 0.1057 | 9930.0000 | 1.9678 | 0.8306 | 1.7170 | 0.8374 |
| 2007 | all | 2 | 7529.0000 | 0.0529 | 0.2410 | 0.0372 | 0.2955 | 0.0371 | 0.3021 | 9930.0000 | 1.4229 | 0.8156 | 1.4266 | 0.7977 |
| 2007 | all | 3 | 5743.0000 | 0.0938 | 0.3665 | 0.0675 | 0.4303 | 0.0676 | 0.4429 | 9930.0000 | 1.3889 | 0.8517 | 1.3877 | 0.8275 |
| 2007 | all | 5 | 3299.0000 | 0.1407 | 0.5554 | 0.1022 | 0.6176 | 0.1031 | 0.6352 | 9930.0000 | 1.3774 | 0.8994 | 1.3646 | 0.8744 |
| 2007 | all | 8 | 1193.0000 | 0.1622 | 0.7245 | 0.1180 | 0.7702 | 0.1184 | 0.7816 | 9930.0000 | 1.3749 | 0.9407 | 1.3698 | 0.9269 |
| 2007 | CA/FL/NV/AZ | 1 | 1519.0000 | 0.0248 | 0.0787 | 0.0093 | 0.1067 | 0.0107 | 0.1051 | 1656.0000 | 2.6721 | 0.7375 | 2.3280 | 0.7487 |
| 2007 | CA/FL/NV/AZ | 2 | 1279.0000 | 0.1096 | 0.1616 | 0.0588 | 0.2877 | 0.0588 | 0.2920 | 1656.0000 | 1.8631 | 0.5617 | 1.8641 | 0.5534 |
| 2007 | CA/FL/NV/AZ | 3 | 1000.0000 | 0.2010 | 0.2397 | 0.1097 | 0.4130 | 0.1108 | 0.4217 | 1656.0000 | 1.8316 | 0.5804 | 1.8132 | 0.5685 |
| 2007 | CA/FL/NV/AZ | 5 | 602.0000 | 0.2869 | 0.3832 | 0.1686 | 0.5805 | 0.1724 | 0.5918 | 1656.0000 | 1.7016 | 0.6600 | 1.6639 | 0.6475 |
| 2007 | CA/FL/NV/AZ | 8 | 201.0000 | 0.3148 | 0.5732 | 0.1891 | 0.7137 | 0.1919 | 0.7201 | 1656.0000 | 1.6647 | 0.8032 | 1.6402 | 0.7960 |
| 2007 | other states | 1 | 7654.0000 | 0.0116 | 0.0905 | 0.0066 | 0.1065 | 0.0075 | 0.1058 | 8274.0000 | 1.7689 | 0.8492 | 1.5441 | 0.8551 |
| 2007 | other states | 2 | 6250.0000 | 0.0416 | 0.2569 | 0.0329 | 0.2971 | 0.0328 | 0.3042 | 8274.0000 | 1.2657 | 0.8647 | 1.2699 | 0.8445 |
| 2007 | other states | 3 | 4743.0000 | 0.0724 | 0.3919 | 0.0591 | 0.4338 | 0.0589 | 0.4472 | 8274.0000 | 1.2248 | 0.9034 | 1.2279 | 0.8763 |
| 2007 | other states | 5 | 2697.0000 | 0.1115 | 0.5899 | 0.0889 | 0.6250 | 0.0893 | 0.6439 | 8274.0000 | 1.2546 | 0.9439 | 1.2491 | 0.9161 |
| 2007 | other states | 8 | 992.0000 | 0.1317 | 0.7547 | 0.1038 | 0.7815 | 0.1037 | 0.7939 | 8274.0000 | 1.2695 | 0.9658 | 1.2699 | 0.9507 |
| 2012 | all | 1 | 9574.0000 | 0.0016 | 0.0561 | 0.0024 | 0.1067 | 0.0028 | 0.1035 | 9991.0000 | 0.6818 | 0.5256 | 0.5642 | 0.5418 |
| 2012 | all | 2 | 8927.0000 | 0.0044 | 0.1160 | 0.0064 | 0.1926 | 0.0068 | 0.1858 | 9991.0000 | 0.6898 | 0.6021 | 0.6530 | 0.6241 |
| 2012 | all | 3 | 8232.0000 | 0.0079 | 0.1883 | 0.0101 | 0.3001 | 0.0105 | 0.2955 | 9991.0000 | 0.7855 | 0.6275 | 0.7561 | 0.6374 |
| 2012 | all | 5 | 6498.0000 | 0.0123 | 0.3555 | 0.0157 | 0.4673 | 0.0164 | 0.4637 | 9991.0000 | 0.7882 | 0.7608 | 0.7537 | 0.7667 |
| 2012 | all | 8 | 4563.0000 | 0.0176 | 0.5512 | 0.0211 | 0.6376 | 0.0221 | 0.6282 | 9991.0000 | 0.8336 | 0.8644 | 0.7937 | 0.8774 |
| 2013 | all | 1 | 9727.0000 | 0.0011 | 0.0390 | 0.0023 | 0.0925 | 0.0028 | 0.0894 | 9993.0000 | 0.4722 | 0.4216 | 0.3908 | 0.4358 |
| 2013 | all | 2 | 8919.0000 | 0.0036 | 0.1225 | 0.0067 | 0.2245 | 0.0071 | 0.2188 | 9993.0000 | 0.5353 | 0.5455 | 0.5047 | 0.5599 |
| 2013 | all | 3 | 8031.0000 | 0.0068 | 0.2144 | 0.0107 | 0.3448 | 0.0113 | 0.3421 | 9993.0000 | 0.6356 | 0.6218 | 0.6056 | 0.6268 |
| 2013 | all | 5 | 6357.0000 | 0.0140 | 0.3666 | 0.0166 | 0.4927 | 0.0176 | 0.4898 | 9993.0000 | 0.8441 | 0.7441 | 0.7980 | 0.7484 |
| 2013 | all | 8 | 3810.0000 | 0.0198 | 0.6217 | 0.0222 | 0.6959 | 0.0237 | 0.6900 | 9993.0000 | 0.8907 | 0.8935 | 0.8352 | 0.9010 |
| 2014 | all | 1 | 9378.0000 | 0.0014 | 0.0914 | 0.0025 | 0.1461 | 0.0030 | 0.1461 | 10043.0000 | 0.5566 | 0.6259 | 0.4711 | 0.6259 |
| 2014 | all | 2 | 8232.0000 | 0.0040 | 0.2159 | 0.0071 | 0.3296 | 0.0074 | 0.3313 | 10043.0000 | 0.5641 | 0.6551 | 0.5403 | 0.6518 |
| 2014 | all | 3 | 6802.0000 | 0.0078 | 0.3389 | 0.0110 | 0.4418 | 0.0113 | 0.4467 | 10043.0000 | 0.7078 | 0.7672 | 0.6870 | 0.7587 |
| 2014 | all | 5 | 5290.0000 | 0.0129 | 0.4774 | 0.0165 | 0.5756 | 0.0171 | 0.5806 | 10043.0000 | 0.7802 | 0.8294 | 0.7529 | 0.8223 |
| 2015 | all | 1 | 9621.0000 | 0.0011 | 0.0629 | 0.0022 | 0.1274 | 0.0027 | 0.1261 | 10008.0000 | 0.4894 | 0.4937 | 0.4145 | 0.4990 |
| 2015 | all | 2 | 8506.0000 | 0.0044 | 0.1701 | 0.0066 | 0.2475 | 0.0068 | 0.2439 | 10008.0000 | 0.6668 | 0.6873 | 0.6467 | 0.6975 |
| 2015 | all | 3 | 7573.0000 | 0.0078 | 0.2548 | 0.0106 | 0.3388 | 0.0108 | 0.3366 | 10008.0000 | 0.7365 | 0.7521 | 0.7234 | 0.7570 |
| 2015 | all | 5 | 5711.0000 | 0.0140 | 0.4556 | 0.0174 | 0.5162 | 0.0180 | 0.5160 | 10008.0000 | 0.8029 | 0.8826 | 0.7760 | 0.8830 |
| 2016 | all | 1 | 9534.0000 | 0.0011 | 0.0530 | 0.0024 | 0.0858 | 0.0028 | 0.0835 | 9913.0000 | 0.4622 | 0.6180 | 0.3958 | 0.6347 |
| 2016 | all | 2 | 8783.0000 | 0.0049 | 0.1280 | 0.0072 | 0.1729 | 0.0074 | 0.1673 | 9913.0000 | 0.6861 | 0.7405 | 0.6697 | 0.7649 |
| 2016 | all | 3 | 8016.0000 | 0.0076 | 0.2093 | 0.0115 | 0.2704 | 0.0117 | 0.2661 | 9913.0000 | 0.6586 | 0.7741 | 0.6483 | 0.7866 |
| 2016 | all | 5 | 4749.0000 | 0.0138 | 0.5458 | 0.0188 | 0.5175 | 0.0194 | 0.5211 | 9913.0000 | 0.7365 | 1.0546 | 0.7131 | 1.0473 |

## Lifetime PD of the 2023-12 portfolio
| segment | value | loans | ttc_pd_12m | pd12_forward | hazard_y1_forward | lifetime_forward | floor_effect_forward | floor_bound_share_loan_years_forward | floor_bound_share_loans_forward | pd12_long-run | hazard_y1_long-run | lifetime_long-run | floor_effect_long-run | floor_bound_share_loan_years_long-run | floor_bound_share_loans_long-run | orig_expected_remaining_lr | current_to_orig_ratio_median |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | all | 297213 | 0.0070 | 0.0050 | 0.0045 | 0.0534 | 0.0000 | 0.0000 | 0.0007 | 0.0058 | 0.0055 | 0.0519 | 0.0000 | 0.0000 | 0.0008 | 0.0598 | 0.6959 |
| dlq_state | 30-59 dpd | 2669 | 0.1439 | 0.1299 | 0.0844 | 0.3487 | 0.0000 | 0.0000 | 0.0000 | 0.1449 | 0.1034 | 0.3537 | 0.0000 | 0.0000 | 0.0000 | 0.0961 | 3.4440 |
| dlq_state | 60-89 dpd | 513 | 0.5464 | 0.5539 | 0.4126 | 0.6935 | 0.0000 | 0.0000 | 0.0000 | 0.5800 | 0.4655 | 0.7064 | 0.0000 | 0.0000 | 0.0000 | 0.1033 | 6.7459 |
| dlq_state | cured 1-3 months | 2820 | 0.0487 | 0.0384 | 0.0275 | 0.2196 | 0.0000 | 0.0000 | 0.0000 | 0.0447 | 0.0337 | 0.2199 | 0.0000 | 0.0000 | 0.0000 | 0.0871 | 2.3325 |
| dlq_state | cured 13+ months | 23474 | 0.0059 | 0.0034 | 0.0043 | 0.0794 | 0.0000 | 0.0000 | 0.0003 | 0.0043 | 0.0050 | 0.0806 | 0.0000 | 0.0000 | 0.0001 | 0.0761 | 1.0183 |
| dlq_state | cured 4-12 months | 5171 | 0.0188 | 0.0130 | 0.0113 | 0.1463 | 0.0000 | 0.0000 | 0.0000 | 0.0156 | 0.0136 | 0.1463 | 0.0000 | 0.0000 | 0.0000 | 0.0823 | 1.6714 |
| dlq_state | never 30+ dpd | 262566 | 0.0040 | 0.0022 | 0.0026 | 0.0432 | 0.0000 | 0.0000 | 0.0008 | 0.0028 | 0.0032 | 0.0414 | 0.0000 | 0.0000 | 0.0009 | 0.0572 | 0.6772 |
| ltv_band | 60-80 | 57505 | 0.0097 | 0.0070 | 0.0061 | 0.0649 | 0.0000 | 0.0000 | 0.0000 | 0.0081 | 0.0074 | 0.0616 | 0.0000 | 0.0000 | 0.0000 | 0.0680 | 0.8203 |
| ltv_band | 80-90 | 18001 | 0.0145 | 0.0106 | 0.0086 | 0.0780 | 0.0000 | 0.0000 | 0.0000 | 0.0123 | 0.0113 | 0.0691 | 0.0000 | 0.0000 | 0.0000 | 0.0735 | 0.9567 |
| ltv_band | 90-100 | 13540 | 0.0185 | 0.0137 | 0.0104 | 0.0939 | 0.0000 | 0.0000 | 0.0000 | 0.0159 | 0.0145 | 0.0786 | 0.0000 | 0.0000 | 0.0000 | 0.0752 | 1.1392 |
| ltv_band | <=60 | 207750 | 0.0049 | 0.0033 | 0.0033 | 0.0452 | 0.0000 | 0.0001 | 0.0010 | 0.0039 | 0.0039 | 0.0458 | 0.0000 | 0.0001 | 0.0012 | 0.0552 | 0.6576 |
| ltv_band | >100 | 26 | 0.0654 | 0.0576 | 0.0499 | 0.1889 | 0.0000 | 0.0019 | 0.0385 | 0.0631 | 0.0585 | 0.2041 | 0.0000 | 0.0019 | 0.0385 | 0.0429 | 6.3158 |

### Change from pdlife-0.2.0
| segment | value | loans | lifetime_forward_pdlife-0.2.0 | lifetime_forward_pdlife-0.4.0 | lifetime_forward_pdlife-0.3.0 | change_forward | lifetime_long_run_pdlife-0.2.0 | lifetime_long_run_pdlife-0.4.0 |
|---|---|---|---|---|---|---|---|---|
| all | all | 297213 | 0.0550 | 0.0534 | 0.0484 | -0.0284 | 0.0534 | 0.0519 |
| dlq_state | 30-59 dpd | 2669 | 0.3472 | 0.3487 | 0.3970 | 0.0043 | 0.3544 | 0.3537 |
| dlq_state | 60-89 dpd | 513 | 0.7480 | 0.6935 | 0.7185 | -0.0728 | 0.7585 | 0.7064 |
| dlq_state | cured 1-3 months | 2820 | 0.1904 | 0.2196 | 0.2505 | 0.1533 | 0.1923 | 0.2199 |
| dlq_state | cured 13+ months | 23474 | 0.0729 | 0.0794 | 0.0684 | 0.0891 | 0.0735 | 0.0806 |
| dlq_state | cured 4-12 months | 5171 | 0.1184 | 0.1463 | 0.1541 | 0.2361 | 0.1184 | 0.1463 |
| dlq_state | never 30+ dpd | 262566 | 0.0463 | 0.0432 | 0.0375 | -0.0674 | 0.0444 | 0.0414 |
| ltv_band | 60-80 | 57505 | 0.0662 | 0.0649 | 0.0624 | -0.0204 | 0.0627 | 0.0616 |
| ltv_band | 80-90 | 18001 | 0.0776 | 0.0780 | 0.0820 | 0.0056 | 0.0699 | 0.0691 |
| ltv_band | 90-100 | 13540 | 0.0905 | 0.0939 | 0.1036 | 0.0378 | 0.0787 | 0.0786 |
| ltv_band | <=60 | 207750 | 0.0473 | 0.0452 | 0.0378 | -0.0444 | 0.0474 | 0.0458 |
| ltv_band | >100 | 26 | 0.1824 | 0.1889 | 0.1942 | 0.0354 | 0.1993 | 0.2041 |

| segment | value | macro | loans | cum_pd_y1 | cum_pd_y2 | cum_pd_y3 | cum_pd_y5 | cum_pd_y10 | cum_pd_y15 | cum_pd_y20 | cum_pd_y25 | cum_pd_y30 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dlq_state | 30-59 dpd | forward | 2669 | 0.1299 | 0.1809 | 0.2112 | 0.2456 | 0.2928 | 0.3200 | 0.3366 | 0.3459 | 0.3486 |
| dlq_state | 30-59 dpd | long-run | 2669 | 0.1449 | 0.1973 | 0.2265 | 0.2581 | 0.3012 | 0.3266 | 0.3424 | 0.3511 | 0.3536 |
| dlq_state | 60-89 dpd | forward | 513 | 0.5535 | 0.5876 | 0.6028 | 0.6269 | 0.6573 | 0.6750 | 0.6857 | 0.6918 | 0.6934 |
| dlq_state | 60-89 dpd | long-run | 513 | 0.5796 | 0.6126 | 0.6265 | 0.6477 | 0.6741 | 0.6898 | 0.6995 | 0.7049 | 0.7063 |
| dlq_state | cured 1-3 months | forward | 2820 | 0.0384 | 0.0701 | 0.0938 | 0.1265 | 0.1691 | 0.1935 | 0.2085 | 0.2169 | 0.2194 |
| dlq_state | cured 1-3 months | long-run | 2820 | 0.0447 | 0.0781 | 0.1017 | 0.1323 | 0.1719 | 0.1950 | 0.2093 | 0.2174 | 0.2198 |
| dlq_state | cured 13+ months | forward | 23474 | 0.0034 | 0.0091 | 0.0152 | 0.0265 | 0.0510 | 0.0659 | 0.0749 | 0.0788 | 0.0793 |
| dlq_state | cured 13+ months | long-run | 23474 | 0.0043 | 0.0106 | 0.0172 | 0.0286 | 0.0526 | 0.0672 | 0.0761 | 0.0800 | 0.0806 |
| dlq_state | cured 4-12 months | forward | 5171 | 0.0130 | 0.0309 | 0.0453 | 0.0680 | 0.1031 | 0.1239 | 0.1369 | 0.1441 | 0.1462 |
| dlq_state | cured 4-12 months | long-run | 5171 | 0.0156 | 0.0350 | 0.0495 | 0.0713 | 0.1045 | 0.1245 | 0.1371 | 0.1441 | 0.1461 |
| dlq_state | never 30+ dpd | forward | 262566 | 0.0022 | 0.0059 | 0.0096 | 0.0164 | 0.0289 | 0.0359 | 0.0402 | 0.0425 | 0.0432 |
| dlq_state | never 30+ dpd | long-run | 262566 | 0.0028 | 0.0067 | 0.0105 | 0.0166 | 0.0279 | 0.0344 | 0.0385 | 0.0407 | 0.0414 |
| ltv_band | 60-80 | forward | 57505 | 0.0070 | 0.0135 | 0.0196 | 0.0298 | 0.0462 | 0.0547 | 0.0598 | 0.0633 | 0.0649 |
| ltv_band | 60-80 | long-run | 57505 | 0.0081 | 0.0151 | 0.0210 | 0.0300 | 0.0444 | 0.0521 | 0.0568 | 0.0601 | 0.0616 |
| ltv_band | 80-90 | forward | 18001 | 0.0106 | 0.0200 | 0.0284 | 0.0417 | 0.0615 | 0.0700 | 0.0742 | 0.0767 | 0.0780 |
| ltv_band | 80-90 | long-run | 18001 | 0.0123 | 0.0224 | 0.0299 | 0.0404 | 0.0555 | 0.0623 | 0.0658 | 0.0679 | 0.0691 |
| ltv_band | 90-100 | forward | 13540 | 0.0137 | 0.0287 | 0.0414 | 0.0591 | 0.0808 | 0.0886 | 0.0917 | 0.0931 | 0.0939 |
| ltv_band | 90-100 | long-run | 13540 | 0.0159 | 0.0309 | 0.0426 | 0.0554 | 0.0695 | 0.0748 | 0.0769 | 0.0780 | 0.0786 |
| ltv_band | <=60 | forward | 207750 | 0.0033 | 0.0066 | 0.0098 | 0.0160 | 0.0289 | 0.0371 | 0.0422 | 0.0447 | 0.0452 |
| ltv_band | <=60 | long-run | 207750 | 0.0039 | 0.0075 | 0.0109 | 0.0171 | 0.0297 | 0.0377 | 0.0428 | 0.0453 | 0.0458 |
| ltv_band | >100 | forward | 26 | 0.0576 | 0.0847 | 0.1049 | 0.1309 | 0.1657 | 0.1795 | 0.1868 | 0.1884 | 0.1889 |
| ltv_band | >100 | long-run | 26 | 0.0631 | 0.0945 | 0.1166 | 0.1453 | 0.1814 | 0.1951 | 0.2020 | 0.2036 | 0.2041 |

## SICR comparator (long-run macro both sides)
| dlq_state | age_band | loans | median_ratio_long_run | median_ratio_forward | p90_ratio_long_run |
|---|---|---|---|---|---|
| 30-59 dpd | 0-2y | 904 | 5.0935 | 5.1561 | 6.9534 |
| 30-59 dpd | 2-4y | 531 | 3.5936 | 3.4124 | 4.3341 |
| 30-59 dpd | 4-8y | 634 | 3.1919 | 3.0473 | 4.1455 |
| 30-59 dpd | 8y+ | 600 | 3.0336 | 2.9517 | 4.2989 |
| 60-89 dpd | 0-2y | 199 | 8.7328 | 8.7882 | 14.9193 |
| 60-89 dpd | 2-4y | 81 | 6.6035 | 6.4609 | 9.8028 |
| 60-89 dpd | 4-8y | 131 | 5.9834 | 5.8870 | 9.5288 |
| 60-89 dpd | 8y+ | 102 | 6.8211 | 6.5439 | 13.6991 |
| cured 1-3 months | 0-2y | 895 | 3.2430 | 3.3472 | 4.3132 |
| cured 1-3 months | 2-4y | 588 | 2.4409 | 2.3398 | 2.7353 |
| cured 1-3 months | 4-8y | 683 | 2.2244 | 2.1461 | 2.6091 |
| cured 1-3 months | 8y+ | 654 | 2.1626 | 2.1036 | 2.5273 |
| cured 13+ months | 0-2y | 843 | 1.2440 | 1.2005 | 1.3799 |
| cured 13+ months | 2-4y | 3393 | 1.0892 | 1.0424 | 1.2008 |
| cured 13+ months | 4-8y | 7790 | 1.0479 | 1.0089 | 1.1591 |
| cured 13+ months | 8y+ | 11448 | 1.0130 | 1.0106 | 1.1346 |
| cured 4-12 months | 0-2y | 1475 | 2.1361 | 2.1448 | 2.5256 |
| cured 4-12 months | 2-4y | 1186 | 1.7590 | 1.6812 | 1.9358 |
| cured 4-12 months | 4-8y | 1224 | 1.6318 | 1.5700 | 1.8106 |
| cured 4-12 months | 8y+ | 1286 | 1.5815 | 1.5400 | 1.7222 |
| never 30+ dpd | 0-2y | 94961 | 0.7945 | 0.9556 | 0.9206 |
| never 30+ dpd | 2-4y | 68434 | 0.6782 | 0.6478 | 0.7558 |
| never 30+ dpd | 4-8y | 45518 | 0.6456 | 0.6209 | 0.7243 |
| never 30+ dpd | 8y+ | 53653 | 0.6341 | 0.6248 | 0.7176 |
