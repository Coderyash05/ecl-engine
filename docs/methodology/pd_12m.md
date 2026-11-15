# 12-month TTC PD (pd12m-1.2.1)

Probability of an RBI-relevant default within 12 months for a performing loan, through the cycle
(no macro variables). Code: `src/ecl/pd/{features,sampling,scorecard,challenger,metrics,origination}.py`,
`src/ecl/pd/fit.py` (`ecl train pd-12m`). Model card: `reports/summary/pd_12m_model_card.md`;
development log: `models/pd_12m/CHANGELOG.md`.

RBI paragraphs: 26 (credit risk at initial recognition: PD at origination stored per loan), 45 (the
lifetime PD is not derived mechanically from this model), 96 (12-month PD floor). US data; not Indian
risk estimates.

## Method

- **Target:** B-18 default within 12 months (see [data](data.md)); RBI 90+ and B-12 are
  sensitivities.
- **Sample:** all development defaults and 15% of non-defaults (seeded), non-defaults weighted 6.667;
  the weighted default rate matches the population (1.2361% vs 1.2356%).
- **Scorecard:** logistic regression on weight-of-evidence (WoE) bins (optbinning). The delinquency
  state (never 30+ dpd / cured 13+, 4-12, 1-3 months ago / 30-59 / 60-89 dpd) enters as dummy
  variables with "never 30+ dpd" as base; the other features enter as WoE.
- **Final features (9):** delinquency state, credit score, current LTV, rate spread (note rate minus
  the same-month market rate), DTI, number of borrowers (1 vs 2+), loan age, loan purpose, channel
  (retail vs third party).
- **Binning policy (documented choices, not RBI values):** continuous features minimum bin 5%;
  states, flags and categoricals keep natural categories, merged only if a bin has under 0.5% of
  weighted snapshots and fewer than 500 defaults. The original interest rate is excluded (it measures
  the rate era, not borrower risk).
- **Selection:** drop IV < 0.02, flag IV > 0.5, drop the weaker of any pair with |corr(WoE)| > 0.7,
  then drop the highest VIF above 5. All WoE coefficients are negative (as expected); the delinquency
  coefficients rise monotonically (0.55 / 1.35 / 2.20 / 3.31 / 5.32; checked, not forced); max VIF 1.18.
- **Challenger:** LightGBM on the same features with monotone constraints; it gains only about 0.02
  Gini, so the interpretable scorecard is the champion.
- **PD at origination:** every loan is scored at its origination state (no delinquency history,
  current LTV = original LTV) and stored per loan for the SICR test.

## Results

| Split | Default rate | Mean PD | Gini (champion) | Gini (challenger) | Score PSI |
|---|---|---|---|---|---|
| Development holdout | 1.23% | 1.23% | 0.803 | 0.821 | - |
| OOT 2017-19 | 0.49% | 0.72% | 0.709 | 0.736 | 0.06 |
| OOT 2020-21 (COVID) | 0.37% | 0.81% | 0.694 | 0.716 | 0.09 |
| OOT 2022-23 | 0.45% | 0.59% | 0.750 | 0.770 | 0.15 |

On the development holdout, predicted and actual default rates agree within 5% in every delinquency
state (60-89 dpd: 69.2% vs 69.3%). The out-of-time over-prediction of the level is by design: the
model is TTC and the [point-in-time conversion](pd_point_in_time.md) sets the level.

## Candidate overlays (not applied)

CO-1 (COVID mass forbearance: 60-89 dpd PD too high in OOT2) and CO-2 (ever-deferred loans: PD too
low in OOT1), with monitoring triggers in `config/overlays.yaml`. Register:
[docs/limitations.md](../limitations.md).
