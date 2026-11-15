# Point-in-time 12-month PD (pdpit-0.2.1)

Converts the through-the-cycle (TTC) 12-month PD into a point-in-time (PIT) PD that moves with the
credit cycle and with each macro scenario. Code: `src/ecl/lifetime/{macro,cells,cycle,satellite}.py`,
`src/ecl/lifetime/fit_pit.py` (`ecl train pd-pit`). Model card: `reports/summary/pd_pit_model_card.md`;
development log: `models/pd_pit/CHANGELOG.md`.

RBI paragraphs: 26-27 (SICR on lifetime risk), 45 (lifetime PD not mechanically derived from the
12-month PD), 47-49 and 124 (multiple probability-weighted scenarios, reversion beyond the forecast),
96 (12-month PD floor of 0.03%). US data (Freddie Mac, FRED); not Indian risk estimates.

## Method

**Vasicek single factor.** For a loan with TTC PD `p` and asset correlation `rho`, the PD given the
systematic factor `Z` (Z > 0 benign, Z < 0 stress) is

```
PD_PIT(Z) = Phi( (Phi^-1(p) - sqrt(rho) * Z) / sqrt(1 - rho) )
```

A borrower defaults when a latent asset value falls below a threshold set by the TTC PD; part of that
value is common to all borrowers, so a bad year moves everyone towards the threshold at once. The
relative shift is larger for low PDs than for high PDs, which matches the data: in benign years
current loans fall to about half their TTC PD while delinquent loans hardly move.

**Measuring Z_t.** For each snapshot quarter 2000Q1-2023Q4, Z_t is the maximum-likelihood value that
makes the loans' PIT PDs fit their realised 12-month B-18 defaults (one-dimensional root find on
cells of TTC-PD bins; `cycle.fit_z`). Loan-level likelihood keeps the spread of PDs, so there is no
averaging bias; overlapping 12-month windows make Z_t autocorrelated, which the regression handles
with HAC errors. The TTC model already contains part of the cycle (indexed current LTV, observed
delinquency), so Z_t measures the cycle net of those channels; the scenario's house-price path also
moves each loan's LTV in the lifetime model.

**Asset correlation rho = 0.15** (Basel residential-mortgage benchmark). The profile likelihood runs to
the edge of the grid (rho-hat 0.01) and unit variance of Z would need rho 0.026, so rho is not
identifiable from one major cycle in this data. The benchmark was chosen by the backtest by
delinquency group (actual / predicted by group inside 0.8-1.25); 0.10 and 0.20 are reported
sensitivities. Consequence: Z_t is not N(0, 1); its long-run value is -0.207.

**One Z for all loans.** Group loadings (a separate weight of Z for never-delinquent, cured and 30-89
dpd loans) were tested against the single Z. The single Z passed the group backtest (all groups
inside 0.8-1.25), so it stands.

**Macro satellite.** Z_t is regressed on macro drivers averaged over the 12-month outcome window
(quarters t+1..t+4), estimated 2000Q1-2016Q4 with Newey-West (HAC) errors:

```
Z_hat = -0.5456 + 0.0438 x hpi_yoy[W] + 0.0946 x gdp_yoy[W]      R2 0.772, residual sd 0.183
```

Driver rule, fixed before the fit: every driver needs the expected sign and |HAC t| >= 2; core
drivers named in advance (house prices, GDP) may not worsen the out-of-time error by more than 5%;
optional additions must improve it by at least 5%. The Fed funds change failed (t = -1.0) and is a
reported sensitivity only; the unemployment specification is a challenger. The window-aligned
specification was preferred to explicit lags because it is directly forward-looking (para 47). Only
growth rates and changes enter (stationarity tests reported). The mortgage rate is not a cycle
driver; it enters the prepayment hazard as the refinancing incentive.

**Projection.** For each scenario and future year, Z comes from that year's four quarters of the
scenario path; the 12-month PIT PD is `Vasicek(p, Z_year1)`. The 12-month PD floor of 0.03% (para 96)
applies per loan and scenario before weighting. Probability weighting happens on ECL, not on PDs or
macro inputs, because ECL is non-linear in the macro path.

## Validation (summary)

| Period | Pre-crisis | Crisis | Recovery | OOT1 2017-19 | COVID 2020-21 | OOT3 2022-23 |
|---|---|---|---|---|---|---|
| Actual / PIT PD | 1.02 | 1.06 | 0.87 | 0.86 | 0.77 | 1.15 |

The crisis peak is predicted at 2.74% in 2008Q4 against 3.33% actual in 2009Q1. Under the B-18 target
there is no COVID default spike, so a GDP-heavy satellite over-predicts 2020-21; house prices lead.
Full tables: `reports/summary/pd_pit_*`.

## Limitations

- The out-of-time period 2017-2023 was used for driver selection, so it is not a fully clean test.
- rho is a benchmark, not an estimate; Z is not standard normal.
- Crisis peak under-predicted and early (covered in the downside by overlay CO-3, see
  [scenarios](scenarios.md)).

Register: [docs/limitations.md](../limitations.md).
