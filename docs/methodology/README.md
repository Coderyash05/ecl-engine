# Methodology

One document per component, in pipeline order. Each states the method as built, the decisions with
their rationale, the RBI paragraphs it implements and its limitations (register:
[../limitations.md](../limitations.md)). US data (Freddie Mac); not Indian risk estimates.

| Document | Component | Command |
|---|---|---|
| [data.md](data.md) | Loan-month panel, default definitions, current LTV, PD modelling dataset | `ecl build-panel`, `ecl build-pd-dataset` |
| [pd_12m.md](pd_12m.md) | 12-month TTC PD (WoE scorecard) | `ecl train pd-12m` |
| [pd_point_in_time.md](pd_point_in_time.md) | Point-in-time PD (Vasicek cycle index, macro satellite) | `ecl train pd-pit` |
| [pd_lifetime.md](pd_lifetime.md) | Lifetime PD (competing-risk hazard), SICR comparator | `ecl train pd-lifetime` |
| [scenarios.md](scenarios.md) | Macro scenarios, crisis replay and CO-3, scenario PDs | `ecl scenarios`, `ecl crisis-replay`, `ecl scenario-pd` |
| [lgd_ead.md](lgd_ead.md) | LGD (cure x severity), EAD, secured portion, CO-5 | `ecl train lgd` |
| [staging.md](staging.md) | Stage rules, restructured accounts, calamity route | `ecl run` |
| [measurement_floors.md](measurement_floors.md) | ECL measurement and prudential floors | `ecl run` |
| [reporting_transition.md](reporting_transition.md) | Annex 4 tables, old-rules provision, transition | `ecl report` |
| [governance.md](governance.md) | Maker-checker overrides, model inventory, change control | `ecl governance` |

Validation: [../validation_report.md](../validation_report.md). India adapter (SYNTHETIC):
[../india_adapter.md](../india_adapter.md).
