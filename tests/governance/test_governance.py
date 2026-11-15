"""Module 9 rules: maker-checker overrides, append-only tamper-evident log (ACPIR Annex 3 1(5),
3(2)-(4)), application in the next run, model inventory (paras 120-121)."""

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from ecl.governance.inventory import check_inventory
from ecl.governance.overrides import (
    OverrideError,
    OverrideLog,
    TamperError,
    apply_overrides,
)

ALLOWED = {"stage": [1, 2, 3]}


@pytest.fixture
def log(tmp_path):
    return OverrideLog(tmp_path / "log.jsonl", ALLOWED)


def _propose(log, **kw):
    args = {
        "account": "L1",
        "field": "stage",
        "new_value": 2,
        "reason": "borrower job loss reported; SICR not yet in the data",
        "maker": "analyst_a",
        "designation": "credit analyst",
        "effective_from": "2026-03-31",
    } | kw
    return log.propose(**args)


def _approve(log, oid, checker="manager_b"):
    log.approve(oid, checker, "credit risk manager", "evidence reviewed")


def test_missing_reason_is_rejected(log):
    for reason in ["", "   ", None]:
        with pytest.raises(OverrideError, match="reason"):
            _propose(log, reason=reason)
    assert log.entries() == []  # nothing written


def test_missing_account_or_maker_is_rejected(log):
    with pytest.raises(OverrideError, match="account"):
        _propose(log, account="")
    with pytest.raises(OverrideError, match="maker"):
        _propose(log, maker=" ")


def test_same_maker_and_checker_is_rejected_annex3_3_3(log):
    oid = _propose(log)
    with pytest.raises(OverrideError, match="different user"):
        log.approve(oid, "Analyst_A", "credit analyst", "self approval")  # case-insensitive
    assert log.state().status.iloc[0] == "proposed"


def test_field_and_value_must_be_permitted(log):
    with pytest.raises(OverrideError, match="cannot be overridden"):
        _propose(log, field="lgd")
    with pytest.raises(OverrideError, match="not permitted"):
        _propose(log, new_value=4)


def test_log_entry_has_annex3_3_4_fields(log):
    _approve(log, _propose(log, old_value=1))
    e = log.entries()
    assert [x["event"] for x in e] == ["propose", "approve"]
    for k in ["timestamp_utc", "user", "designation", "reason", "account", "system_user"]:
        assert e[0][k]
    assert e[0]["old_value"] == 1 and e[0]["new_value"] == 2


def test_log_cannot_be_edited_any_change_breaks_the_chain(log):
    _approve(log, _propose(log))
    _propose(log, account="L2")
    lines = log.path.read_text(encoding="utf-8").splitlines()
    head = log.verify()
    # edit a field
    e = json.loads(lines[0])
    e["reason"] = "changed afterwards"
    log.path.write_text("\n".join([json.dumps(e, sort_keys=True), *lines[1:]]) + "\n")
    with pytest.raises(TamperError):
        log.verify()
    # delete a middle line
    log.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    with pytest.raises(TamperError):
        log.entries()
    # reorder
    log.path.write_text("\n".join([lines[1], lines[0], lines[2]]) + "\n")
    with pytest.raises(TamperError):
        log.state()
    # restored file verifies to the same head; writes refuse a broken chain
    log.path.write_text("\n".join(lines) + "\n")
    assert log.verify() == head
    log.path.write_text("\n".join(lines[:1]) + "\nnot json\n")
    with pytest.raises(TamperError):
        _propose(log, account="L3")


def test_no_edit_or_delete_api():
    for name in ["edit", "update", "delete", "remove", "purge", "truncate"]:
        assert not hasattr(OverrideLog, name)


def test_only_approved_unrevoked_effective_overrides_are_active(log):
    a = _propose(log, account="A")
    _approve(log, a)
    _propose(log, account="B")  # pending
    c = _propose(log, account="C", effective_from="2026-06-30")
    _approve(log, c)  # future
    d = _propose(log, account="D")
    _approve(log, d)
    log.revoke(d, "analyst_a", "credit analyst", "SICR now in the data")
    assert set(log.active("2026-03-31").account) == {"A", "D"}  # revocation not yet approved
    with pytest.raises(OverrideError, match="different user"):
        log.approve_revoke(d, "analyst_a", "credit analyst", "x")
    log.approve_revoke(d, "manager_b", "credit risk manager", "agreed")
    assert set(log.active("2026-03-31").account) == {"A"}
    assert set(log.active("2026-06-30").account) == {"A", "C"}


def _portfolio():
    return pd.DataFrame(
        {
            "loan_id": ["A", "B", "N"],
            "stage": [1, 2, 3],
            "stage_rule": ["none", "sicr_pd", "default"],
        }
    )


def test_overrides_applied_on_the_next_run_and_shown_in_outputs(log):
    a = _propose(log, account="A", new_value=2)
    _approve(log, a)
    n = _propose(log, account="N", new_value=2, reason="cleared arrears, system lag")
    _approve(log, n)
    x = _propose(log, account="ZZ", new_value=3)
    _approve(log, x)
    out, info = apply_overrides(_portfolio(), log.active("2026-03-31"))
    r = out.set_index("loan_id")
    assert r.loc["A", "stage"] == 2 and r.loc["A", "stage_rule"] == "override"
    assert r.loc["A", "stage_system"] == 1 and r.loc["A", "override_id"] == a
    assert r.loc["B", "stage"] == 2 and pd.isna(r.loc["B", "override_id"])
    # Annex 3 3(2): a system NPA leaves Stage 3 only with npa_exception
    assert r.loc["N", "stage"] == 3 and info["rejected"][0]["override_id"] == n
    assert info["unmatched"] == [x]
    assert [i["override_id"] for i in info["applied"]] == [a]


def test_npa_exception_allows_moving_out_of_stage_3(log):
    n = _propose(log, account="N", new_value=2, npa_exception=True)
    _approve(log, n)
    out, info = apply_overrides(_portfolio(), log.active("2026-03-31"))
    assert out.set_index("loan_id").loc["N", "stage"] == 2 and len(info["applied"]) == 1


def test_inventory_has_para_120_fields_and_no_cycles():
    root = Path(".")
    gov = yaml.safe_load(Path("config/governance.yaml").read_text(encoding="utf-8"))
    models = yaml.safe_load(Path("config/models.yaml").read_text(encoding="utf-8"))["models"]
    ov = yaml.safe_load(Path("config/overlays.yaml").read_text(encoding="utf-8"))["overlays"]
    assert check_inventory(models, gov["inventory"]["required_fields"], ov, root) == []
    for k in ["pd_12m", "pd_pit", "pd_lifetime", "macro_scenarios", "lgd", "staging"]:
        assert k in models


def test_inventory_check_reports_gaps():
    models = {
        "a": {"tier": 4, "dependencies": ["b"], "overlays": ["CO-9"], "validation": {}},
        "b": {"tier": 1, "dependencies": ["a"], "validation": {"status": "validated"}},
    }
    f = check_inventory(models, ["owner"], {"CO-3": {}}, Path("."))
    text = "\n".join(f)
    for s in ["a: missing ['owner']", "tier must be", "CO-9", "validation status missing",
              "validated without a date", "dependency cycle"]:  # fmt: skip
        assert s in text


def test_inventory_checks_data_inputs_only_when_a_data_folder_exists(tmp_path):
    models = {
        "m": {
            "tier": 1,
            "dependencies": ["data/macro/hpi.csv"],
            "validation": {"status": "not independently validated"},
        }
    }
    assert check_inventory(models, [], {}, tmp_path) == []  # fresh clone: no data/ folder
    (tmp_path / "data").mkdir()
    f = check_inventory(models, [], {}, tmp_path)
    assert any("data/macro/hpi.csv" in x for x in f)  # local setup: a missing input is a finding
    (tmp_path / "data" / "macro").mkdir()
    (tmp_path / "data" / "macro" / "hpi.csv").write_text("x")
    assert check_inventory(models, [], {}, tmp_path) == []
