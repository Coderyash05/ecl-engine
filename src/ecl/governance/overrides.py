"""Manual overrides with maker-checker control and an append-only, tamper-evident audit log
(Module 9; ACPIR Annex 3 paras 1(5), 3(1)-(4); SICR rebuttals paras 33-36).

What the Directions ask (Annex 3):
- 1(5): staging, SICR and impairment processes automated "with clearly documented business
  rules, maker-checker controls, audit trails and exception logs. Any manual intervention shall
  be duly documented and subject to appropriate oversight."
- 3(2)-(3): no manual override of the system NPA classification, except in exceptional
  circumstances with "at least two level authorisation" and audit trails.
- 3(4): logs of all manual interventions with "the date and time stamp; purpose / reason;
  user-IDs, name and designation ... and necessary account details", stored for at least three
  years, "not be tampered with", "system generated".

Design:
- An override is proposed by a maker (account, field, new value, reason, effective date) and is
  active only after a different user (checker) approves it; a revocation is proposed and
  approved the same way. Every step is one appended JSON line.
- Each line carries the SHA-256 of the previous line and of itself (hash chain): editing,
  deleting or reordering any line breaks the chain, and `verify` raises. The module has no
  edit or delete function; lines are only appended. The head hash is written into each ECL run
  record, so a later truncation of the log is visible against the run that used it.
- The next ECL run applies the approved, unrevoked overrides whose effective date is on or
  before the reporting date; outputs keep the system stage and show the override id and reason.
  Moving a system NPA (Stage 3) account out of Stage 3 additionally needs `npa_exception`
  (Annex 3 3(2)-(3)); otherwise the override is not applied and is reported as rejected.
"""

from __future__ import annotations

import getpass
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

GENESIS = "0" * 64


class OverrideError(ValueError):
    """Invalid override request (missing reason, same maker and checker, unknown id, ...)."""


class TamperError(RuntimeError):
    """The audit log hash chain does not verify: a line was edited, deleted or reordered."""


def _digest(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()


def _required(**fields) -> None:
    for name, value in fields.items():
        if value is None or not str(value).strip():
            raise OverrideError(f"{name} is required")


class OverrideLog:
    """Append-only override log (JSON lines, hash-chained). No edit or delete operations."""

    def __init__(self, path: Path, allowed: dict):
        """allowed: {field: [permitted new values]} from config/governance.yaml."""
        self.path = Path(path)
        self.allowed = allowed

    # reading -----------------------------------------------------------------------------
    def entries(self) -> list[dict]:
        """All log lines, after verifying the hash chain."""
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        out, prev = [], GENESIS
        for i, line in enumerate(lines, start=1):
            try:
                e = json.loads(line)
            except json.JSONDecodeError as err:
                raise TamperError(f"line {i} is not valid JSON") from err
            if e.get("seq") != i or e.get("prev_hash") != prev or e.get("hash") != _digest(e):
                raise TamperError(f"hash chain broken at line {i}")
            out.append(e)
            prev = e["hash"]
        return out

    def verify(self) -> str:
        """Verify the chain; return the head hash (GENESIS for an empty log)."""
        e = self.entries()
        return e[-1]["hash"] if e else GENESIS

    def state(self) -> pd.DataFrame:
        """One row per override id with its current status (proposed / approved / revoked)."""
        rows: dict[str, dict] = {}
        for e in self.entries():
            oid = e["override_id"]
            if e["event"] == "propose":
                rows[oid] = {
                    k: e.get(k)
                    for k in [
                        "override_id",
                        "account",
                        "field",
                        "old_value",
                        "new_value",
                        "reason",
                        "effective_from",
                        "npa_exception",
                    ]
                } | {"maker": e["user"], "status": "proposed", "checker": None}
            elif e["event"] == "approve":
                rows[oid] |= {"status": "approved", "checker": e["user"]}
            elif e["event"] == "revoke_propose":
                rows[oid] |= {"revoke_maker": e["user"], "revoke_reason": e["reason"]}
            elif e["event"] == "revoke_approve":
                rows[oid] |= {"status": "revoked", "revoke_checker": e["user"]}
        return pd.DataFrame(rows.values())

    # writing -----------------------------------------------------------------------------
    def _append(self, entry: dict) -> dict:
        prior = self.entries()  # verifies the chain before writing
        entry = {
            "seq": len(prior) + 1,
            "timestamp_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "system_user": getpass.getuser(),
            **entry,
            "prev_hash": prior[-1]["hash"] if prior else GENESIS,
        }
        entry["hash"] = _digest(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:  # append only
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
        return entry

    def _get(self, override_id: str) -> dict:
        s = self.state()
        if s.empty or override_id not in set(s.override_id):
            raise OverrideError(f"unknown override id {override_id}")
        return s.set_index("override_id").loc[override_id].to_dict()

    def propose(
        self,
        account: str,
        field: str,
        new_value: object,
        reason: str,
        maker: str,
        designation: str,
        effective_from: str,
        old_value: object = None,
        npa_exception: bool = False,
    ) -> str:
        """Maker step. Returns the override id."""
        _required(account=account, field=field, reason=reason, maker=maker, designation=designation)
        _required(new_value=new_value, effective_from=effective_from)
        if field not in self.allowed:
            raise OverrideError(
                f"field {field!r} cannot be overridden (allowed: {list(self.allowed)})"
            )
        if new_value not in self.allowed[field]:
            raise OverrideError(f"{field} = {new_value!r} not permitted ({self.allowed[field]})")
        pd.Timestamp(effective_from)  # raises on a bad date
        oid = f"OV-{len(self.entries()) + 1:05d}"
        self._append(
            {
                "event": "propose",
                "override_id": oid,
                "account": str(account),
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "reason": reason.strip(),
                "effective_from": str(pd.Timestamp(effective_from).date()),
                "npa_exception": bool(npa_exception),
                "user": maker,
                "designation": designation,
            }
        )
        return oid

    def approve(self, override_id: str, checker: str, designation: str, reason: str) -> None:
        """Checker step: a different user from the maker (two-level authorisation)."""
        _required(checker=checker, designation=designation, reason=reason)
        o = self._get(override_id)
        if o["status"] != "proposed":
            raise OverrideError(f"{override_id} is {o['status']}, not awaiting approval")
        if checker.strip().lower() == str(o["maker"]).strip().lower():
            raise OverrideError("checker must be a different user from the maker")
        self._append(
            {
                "event": "approve",
                "override_id": override_id,
                "account": o["account"],
                "reason": reason.strip(),
                "user": checker,
                "designation": designation,
            }
        )

    def revoke(self, override_id: str, maker: str, designation: str, reason: str) -> None:
        """Maker step of a revocation (approved by a different user with `approve_revoke`)."""
        _required(maker=maker, designation=designation, reason=reason)
        o = self._get(override_id)
        if o["status"] != "approved":
            raise OverrideError(
                f"{override_id} is {o['status']}; only approved overrides are revoked"
            )
        self._append(
            {
                "event": "revoke_propose",
                "override_id": override_id,
                "account": o["account"],
                "reason": reason.strip(),
                "user": maker,
                "designation": designation,
            }
        )

    def approve_revoke(self, override_id: str, checker: str, designation: str, reason: str) -> None:
        """Checker step for a revocation: a different user approves it and the override stops
        applying from the next run (Annex 3 3(3), two-level authorisation)."""
        _required(checker=checker, designation=designation, reason=reason)
        o = self._get(override_id)
        if o["status"] != "approved" or not o.get("revoke_maker"):
            raise OverrideError(f"{override_id} has no pending revocation")
        if checker.strip().lower() == str(o["revoke_maker"]).strip().lower():
            raise OverrideError("checker must be a different user from the maker")
        self._append(
            {
                "event": "revoke_approve",
                "override_id": override_id,
                "account": o["account"],
                "reason": reason.strip(),
                "user": checker,
                "designation": designation,
            }
        )

    def active(self, as_of: str) -> pd.DataFrame:
        """Approved, unrevoked overrides effective on or before `as_of`."""
        s = self.state()
        if s.empty:
            return s
        s = s[(s.status == "approved") & (pd.to_datetime(s.effective_from) <= pd.Timestamp(as_of))]
        return s.reset_index(drop=True)


def apply_overrides(res: pd.DataFrame, active: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Apply active stage overrides to a staged portfolio (loan_id, stage, stage_rule).

    Keeps the system result in `stage_system` / `stage_rule_system`; overridden loans get
    stage_rule 'override' and the override id and reason. One override per account (the latest
    approved id wins). Annex 3 3(2): a system Stage 3 (NPA) account is moved out of Stage 3 only
    with npa_exception; otherwise the override is rejected and reported."""
    res = res.copy()
    res["stage_system"] = res.stage
    res["stage_rule_system"] = res.stage_rule
    res["override_id"] = pd.Series(pd.NA, index=res.index, dtype="string")
    res["override_reason"] = pd.Series(pd.NA, index=res.index, dtype="string")
    info = {"applied": [], "rejected": [], "unmatched": []}
    if active is None or active.empty:
        return res, info
    a = (
        active[active.field == "stage"]
        .sort_values("override_id")
        .drop_duplicates("account", keep="last")
    )
    pos = pd.Series(res.index, index=res.loan_id.astype(str))
    for o in a.itertuples(index=False):
        if o.account not in pos.index:
            info["unmatched"].append(o.override_id)
            continue
        i = pos[o.account]
        old, new = int(res.at[i, "stage"]), int(o.new_value)
        if old == 3 and new < 3 and not bool(o.npa_exception):
            info["rejected"].append(
                {"override_id": o.override_id, "account": o.account, "why": "NPA, no exception"}
            )
            continue
        res.loc[i, ["stage", "stage_rule"]] = [new, "override"]
        res.loc[i, ["override_id", "override_reason"]] = [o.override_id, o.reason]
        info["applied"].append(
            {"override_id": o.override_id, "account": o.account, "old": old, "new": new}
        )
    return res, info
