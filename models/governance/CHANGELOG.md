# CHANGELOG - Module 9 governance and Module 11 validation

US data (Freddie Mac sample); not Indian risk estimates. Config `config/governance.yaml`;
code `src/ecl/governance/{overrides,inventory}.py`, `src/ecl/validation/backtest.py`; commands
`ecl governance`, `ecl validate`. Validation report `docs/validation_report.md`
(developer self-validation, NOT independent); reviewer summary `docs/summary.md`.

## gov-0.1.0 (code `1881a92`, 2026-11-14)

### Overrides (ACPIR Annex 3 1(5), 3(2)-(4))
- Maker proposes (account, field `stage`, new value, reason, designation, effective date); a
  different checker approves (case-insensitive user-id check). Revocations use the same two
  steps. Missing reason, account, maker or designation is rejected; only `stage` in {1, 2, 3}.
- Log `data/governance/override_log.jsonl` (gitignored: it holds Freddie loan ids). One JSON
  line per step with UTC timestamp, user, designation, system user, reason, account, old / new
  value, `prev_hash` and `hash` (SHA-256). Any edit, deletion or reordering breaks the chain;
  `verify` raises and no further write is accepted. No edit or delete function exists.
- The ECL run (`run_ecl`) verifies the log, applies approved, unrevoked overrides effective on
  or before the reporting date, keeps `stage_system` / `stage_rule_system`, sets stage_rule
  `override` with the id and reason, and writes the log head hash plus the applied / rejected /
  unmatched lists into `models/ecl/ecl_{date}.json`. Annex 4 has a "Manual overrides" table.
- A system Stage 3 (NPA) account leaves Stage 3 only with `npa_exception` (Annex 3 3(2)-(3));
  otherwise the override is rejected at run time and reported.
- Sensitivity grids re-stage without overrides (they show the rules' effect).

### Inventory (paras 120-121)
- `config/models.yaml` now has 8 entries: `ecl` split into `staging` and `ecl_measurement`;
  `reporting` added. Each entry has developers, users, intended use, tier with a rationale,
  dependencies (upstream; `macro_scenarios` no longer lists its downstream models), limitation
  ids, overlay ids and monitoring triggers.
- Tiers by output materiality (`config/governance.yaml`): `pd_pit` and `macro_scenarios` move to
  tier 2 because the floors mute their effect on the provision; re-tier if the floors stop
  binding. `reporting` tier 3.
- `ecl governance inventory` checks four things: required fields, dependencies
  (models or existing files, no cycles), overlays present in `config/overlays.yaml`, and each
  code commit in git. Result: no findings.

### Validation (para 130) and ECL backtest (para 131)
- `ecl validate --date 2023-03-31` -> `reports/summary/validation_ecl_backtest_2023-03.csv`:
  RBI 90+ defaults actual / predicted 1.11 (Stage 1 1.00, Stage 2 1.30); B-18 0.88; realised
  loss to 2026-06 / predicted 12m ECL 0.09 (118 liquidated, 1,555 cured or prepaid, 43
  unresolved). New finding M-1 (PD target B-18 vs RBI default).
- Findings H-1, H-2, M-1 to M-6, L-1 to L-5 in `docs/validation_report.md` section 13.

### Re-run check
2026-03-31 re-run on code `1881a92` with an empty log: provision unchanged at 1,229.9m; the run
record now carries the override head hash (empty log = 64 zeros).

### M-1 check (2026-11-14, `ecl validate`)
Relief cures removed by B-18 and credited again by the cure recalibration: 869 of 15,054
2012-19 window defaults (no-cure 2.0% vs 36.5% overall). Recalibrating without them: intercept
shift -0.439 (vs -0.469); projected no-cure +1.7% -> Stage 1-2 model ECL about +1.7% (< 5%
threshold of the owner's decision) -> no retrain; monitored (Stage 2 RBI backtest ratio > 1.25).
`reports/summary/validation_m1_relief_cures.json`.

### Limitations
- G-1 (owner decision 2026-11-14: limitation of a local tool) User ids are free text (no
  authentication); log retention (Annex 3 3(4): three years) depends on backups of `data/`; a
  deleted tail is visible only against a run record's head hash. A bank deployment would bind
  ids to authenticated identities and write-once storage.
- G-2 (owner decision 2026-11-14) Overlay changes (`config/overlays.yaml`) are controlled by
  clean-tree git versioning: every run records the config commit and the clean flag, so an
  overlay change is traceable to a commit. Full maker-checker for overlays is a future
  enhancement.
- G-3 Tiering not independently reviewed (para 121).
