# Governance: manual overrides and model inventory (gov-0.1.0)

Code: `src/ecl/governance/{overrides,inventory}.py` (`ecl governance <command>`). Config:
`config/governance.yaml`, inventory `config/models.yaml`, overlays `config/overlays.yaml`. Development
log: `models/governance/CHANGELOG.md`.

RBI basis (ACPIR Directions): Annex 3 paras 1(5) and 3(1)-(4) (manual overrides, two-level
authorisation, logs kept at least three years and not tampered with), paras 33-36 (SICR rebuttals),
120-121 (model inventory and tiering), 130 (validation), 131 (post-model adjustments).

## Manual overrides (maker-checker)

```
ecl governance propose --account ID --stage 2 --reason "..." --maker U1 --designation "..." \
                       --effective-from 2026-03-31 [--npa-exception]
ecl governance approve --id OV-00001 --checker U2 --designation "..." --reason "..."
ecl governance revoke --id OV-00001 --maker U1 ...      ecl governance approve-revoke --id ... --checker U2 ...
ecl governance list | verify
```

- A maker proposes an override (account, new stage, reason, designation, effective date); a
  **different** checker approves it (case-insensitive user-id check, Annex 3 3(3)). Revocations take
  the same two steps. A missing reason, account, maker or designation is rejected; only `stage` in
  {1, 2, 3} can be overridden.
- **Append-only, hash-chained log** (`data/governance/override_log.jsonl`, gitignored because entries
  carry loan ids): one JSON line per step with UTC timestamp, user, designation, reason, account,
  old and new value, `prev_hash` and `hash` (SHA-256). Any edit, deletion or reordering breaks the
  chain; `verify` raises and no further write is accepted. No edit or delete function exists
  (Annex 3 3(4)).
- **Applied on the next run:** `ecl run` verifies the log, applies approved, unrevoked overrides
  effective on or before the reporting date, keeps the system stage and rule next to the overridden
  stage (rule `override`, with id and reason), and records the log head hash and the applied /
  rejected lists in `models/ecl/ecl_{date}.json`. Annex 4 has a "Manual overrides" table.
- **NPA protection (Annex 3 3(2)):** a system Stage 3 (NPA) account leaves Stage 3 only with an
  explicit `npa_exception`; otherwise the override is rejected at run time and reported.

## Model inventory (paras 120-121)

`config/models.yaml` holds one entry per model (12-month PD, PIT PD, lifetime PD, scenarios, LGD and
EAD, staging, ECL measurement, reporting, synthetic India) with the para-120 fields: owner,
developers, users, intended use, tier and rationale, dependencies, version and code commit,
validation status, limitations, overlays and monitoring triggers. `ecl governance inventory` checks
that every required field is present, dependencies resolve to models or existing files without
cycles, overlays exist in `config/overlays.yaml`, and each code commit exists in git.

**Tiering** (developer criteria in `config/governance.yaml`): tier 1 drives the provision directly and
a reasonable alternative moves it by 5% or more, or sets the stage of 1% or more of exposure; tier 2
feeds a tier-1 model and moves the provision by 1-5%; tier 3 otherwise. The floors mute PD and
scenario effects on the provision, so the PIT PD and the scenarios are tier 2 for now.

## Change control

Every regulatory value lives in a versioned config file with its paragraph reference
(`config/rbi_2026.yaml`, `rbi_iracp_2025.yaml`, `rbi_credit_facilities.yaml`); developer choices are
marked `rbi_specified: false`. Each model fit and run records its git commit and a clean-tree flag;
the rule is commit the code, run from a clean tree, then commit the results. Overlay changes are
controlled the same way (finding L-4 / G-2: maker-checker for overlays is a future enhancement).

## Limitations

G-1 (user ids are free text; log retention depends on backups; a deleted tail is visible only
against a run record's head hash), G-2 (overlay approvals not enforced by the log), G-3 (tiering not
independently reviewed). Register: [docs/limitations.md](../limitations.md).
