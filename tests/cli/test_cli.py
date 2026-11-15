"""The `ecl` command: every pipeline step parses, and a governance command runs end to end."""

import shutil
from pathlib import Path

import pytest

from ecl import cli

ROOT = Path(__file__).resolve().parents[2]

PIPELINE = [
    ["build-panel"],
    ["build-pd-dataset"],
    ["train", "pd-12m"],
    ["train", "pd-pit", "--rebuild-cells"],
    ["train", "pd-lifetime"],
    ["scenarios", "--date", "2026-03-31"],
    ["crisis-replay"],
    ["scenario-pd", "--skip-early-performance"],
    ["train", "lgd", "--fit-only"],
    ["run", "--date", "2026-03-31"],
    ["report"],
    ["backtest", "--date", "2023-03-31"],
    ["validate", "--date", "2023-03-31"],
    ["india"],
    ["governance", "inventory"],
]


@pytest.mark.parametrize("argv", PIPELINE, ids=lambda a: " ".join(a))
def test_every_pipeline_command_parses_to_a_handler(argv):
    args = cli.build_parser(ROOT).parse_args(argv)
    assert callable(args.func)


def test_unknown_model_is_rejected():
    with pytest.raises(SystemExit):
        cli.build_parser(ROOT).parse_args(["train", "pd-unknown"])


def test_governance_verify_on_an_empty_log(tmp_path, monkeypatch, capsys):
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "governance.yaml", tmp_path / "config" / "governance.yaml")
    monkeypatch.setenv("ECL_ROOT", str(tmp_path))
    cli.main(["governance", "verify"])
    assert capsys.readouterr().out.strip() == "log verified; head hash " + "0" * 64
