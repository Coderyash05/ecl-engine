"""Command-line interface: `ecl <command>` (installed by `pip install -e .`; also
`python -m ecl <command>`).

Pipeline order (each step reads what the previous ones wrote):

    ecl build-panel                 Module 1   loan-month panel from the Freddie Mac files
    ecl build-pd-dataset            Module 2a  12-month PD modelling dataset
    ecl train pd-12m                Module 2b  TTC scorecard and challenger
    ecl train pd-pit                Module 3   credit-cycle index and macro satellite
    ecl train pd-lifetime           Module 3   competing-risk lifetime hazard
    ecl scenarios                   Module 4   macro scenarios and Annex 4 Table 5
    ecl crisis-replay               Module 4   crisis replay and CO-3 calibration
    ecl scenario-pd                 Module 4   scenario-weighted PDs, early-performance check
    ecl train lgd                   Module 5   LGD models, then LGD / EAD per reporting date
    ecl run [--date YYYY-MM-DD]     Modules 6-8 staging, ECL, prudential floors
    ecl report                      Module 10  Annex 4 tables, old-rules provision, transition
    ecl backtest --date 2023-03-31  Module 11  ECL backtest of a reporting date
    ecl validate --date 2023-03-31  Module 11  backtest plus the relief-cure check (M-1)
    ecl india                       Module 12  SYNTHETIC Indian book end to end
    ecl governance <subcommand>     Module 9   overrides (maker-checker), audit log, inventory

US data (Freddie Mac); results are not Indian risk estimates. The India run is SYNTHETIC.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml

from ecl.common import configure_logging, git_state, project_root

logger = logging.getLogger(__name__)


def _config(root: Path, name: str) -> dict:
    return yaml.safe_load((root / "config" / name).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------- data and models


def cmd_build_panel(args: argparse.Namespace, root: Path) -> None:
    """Module 1: loan-month panel, default flags and QC tables."""
    from ecl.data.panel import build_panel

    build_panel(args.raw_dir, args.out, args.reports, args.vintages, args.cure_months)


def cmd_build_pd_dataset(args: argparse.Namespace, root: Path) -> None:
    """Module 2a: 12-month PD modelling dataset."""
    from ecl.pd.dataset import build_pd_dataset

    build_pd_dataset(
        args.processed,
        args.out or args.processed / "pd_dataset",
        args.reports,
        args.hpi,
        args.hpi_national,
        args.seed,
    )


def cmd_train(args: argparse.Namespace, root: Path) -> None:
    """Modules 2b, 3 and 5: fit a model (and, for the LGD, apply it to the reporting dates)."""
    if args.model == "pd-12m":
        from ecl.pd.fit import fit_pd_model

        fit_pd_model()
    elif args.model == "pd-pit":
        from ecl.lifetime.fit_pit import fit_pit_pd

        fit_pit_pd(args.rebuild_cells)
    elif args.model == "pd-lifetime":
        from ecl.lifetime.fit_lifetime import fit_lifetime_pd

        fit_lifetime_pd()
    elif args.model == "lgd":
        _train_lgd(args, root)


def _train_lgd(args: argparse.Namespace, root: Path) -> None:
    from ecl.lgd.run import apply_lgd, fit_lgd
    from ecl.scenarios.run_pd import load_inputs

    cfg = _config(root, "lgd.yaml")
    scen = _config(root, "scenarios.yaml")
    ov = _config(root, "overlays.yaml")
    inp = load_inputs(scen, root)
    git = git_state(root)
    logger.info("Fit and validate LGD")
    fitted = fit_lgd(cfg, root, inp.log_state)
    fitted["summary"]["git"] = git
    logger.info(json.dumps(fitted["summary"], indent=1, default=float))
    if args.fit_only:
        return
    for date in args.date or list(scen["base"]["dates"]):
        logger.info(f"LGD / EAD as on {date}")
        res = apply_lgd(
            date,
            cfg,
            scen,
            ov["overlays"]["CO-3"],
            ov["overlays"]["CO-5"],
            inp,
            fitted,
            root,
            git,
        )
        logger.info(json.dumps(res, indent=1, default=float))


# ----------------------------------------------------------------------------- scenarios


def cmd_scenarios(args: argparse.Namespace, root: Path) -> None:
    """Module 4: macro scenarios and Annex 4 Table 5 per reporting date."""
    from ecl.lifetime.macro import load_macro
    from ecl.scenarios.run import build_scenarios

    cfg = _config(root, "scenarios.yaml")
    pit = json.loads((root / "models/pd_pit/metadata.json").read_text(encoding="utf-8"))
    macro, _ = load_macro(root / "data/macro")
    git = git_state(root)
    for date in args.date or list(cfg["base"]["dates"]):
        run, _ = build_scenarios(date, cfg, macro, pit, git, root)
        logger.info(json.dumps({k: run[k] for k in ["as_at", "sources", "scenarios"]}, default=str))


def cmd_crisis_replay(args: argparse.Namespace, root: Path) -> None:
    """Module 4: crisis replay R1-R3 and the CO-3 calibration."""
    from ecl.scenarios.run_pd import crisis_replay, load_inputs

    cfg = _config(root, "scenarios.yaml")
    res = crisis_replay(cfg, load_inputs(cfg, root), root)
    logger.info(res["table"].round(4).to_string(index=False))
    logger.info(json.dumps({k: v for k, v in res.items() if k != "table"}, indent=1, default=float))


def cmd_scenario_pd(args: argparse.Namespace, root: Path) -> None:
    """Module 4: scenario-weighted PDs per reporting date and the early-performance check."""
    from ecl.scenarios.run_pd import early_performance_check, load_inputs, scenario_pd_for_date

    cfg = _config(root, "scenarios.yaml")
    ov = _config(root, "overlays.yaml")
    inp = load_inputs(cfg, root)
    git = git_state(root)
    for date in args.date or list(cfg["base"]["dates"]):
        logger.info(f"Scenario PDs as on {date}")
        res = scenario_pd_for_date(date, cfg, ov["overlays"]["CO-3"], inp, root, git)
        logger.info(json.dumps(res, indent=1, default=float))
    if not args.skip_early_performance:
        logger.info("Early-performance check, vintages 2024-26")
        logger.info(json.dumps(early_performance_check(cfg, inp, root), indent=1, default=float))


# ----------------------------------------------------------------------------- ECL and reporting


def cmd_run(args: argparse.Namespace, root: Path) -> None:
    """Modules 6-8: staging, ECL measurement and prudential floors per reporting date."""
    from ecl.provisioning.run import run_ecl
    from ecl.scenarios.run_pd import load_inputs

    cfg, scen, lgd = (_config(root, f) for f in ("ecl.yaml", "scenarios.yaml", "lgd.yaml"))
    ov = _config(root, "overlays.yaml")["overlays"]
    if args.date:
        scen["base"]["dates"] = {args.date: scen["base"]["dates"][args.date]}
    res = run_ecl(cfg, scen, lgd, ov, load_inputs(scen, root), root, git_state(root))
    for date, r in res.items():
        logger.info(f"{date} {json.dumps(r['by_stage']['total'], default=float)}")


def cmd_report(args: argparse.Namespace, root: Path) -> None:
    """Module 10: Annex 4 tables, old-rules (IRACP) provision and transition."""
    from ecl.reporting.annex4 import build_reports

    cfg = _config(root, "ecl.yaml")
    rep = cfg["reporting"]
    build_reports(
        root,
        cfg,
        _config(root, "rbi_2026.yaml"),
        yaml.safe_load((root / rep["old_rules_config"]).read_text(encoding="utf-8")),
        rep["annex4_dates"],
        git_state(root),
    )


def cmd_backtest(args: argparse.Namespace, root: Path) -> None:
    """Module 11: ECL backtest of a reporting date; `validate` adds the M-1 check first."""
    from ecl.validation.run import ecl_backtest_report, m1_check

    lgd = _config(root, "lgd.yaml")
    if args.command == "validate":
        logger.info(json.dumps(m1_check(root, lgd), indent=2))
    logger.info(ecl_backtest_report(root, args.date, lgd).T.to_string())


def cmd_india(args: argparse.Namespace, root: Path) -> None:
    """Module 12: SYNTHETIC Indian book end to end (not Indian risk estimates)."""
    from ecl.india.run import run_india

    res = run_india(
        root,
        _config(root, "india.yaml"),
        _config(root, "ecl.yaml"),
        _config(root, "rbi_2026.yaml"),
        _config(root, "rbi_iracp_2025.yaml"),
        _config(root, "rbi_credit_facilities.yaml"),
        git_state(root),
    )
    logger.info(res["sensitivities"].to_string(index=False))
    logger.info(res["comparison"].T.to_string())


# ----------------------------------------------------------------------------- governance


def _current_stage(root: Path, account: str) -> int | None:
    """System stage of the account in the latest ECL run output (the override's old value)."""
    runs = sorted((root / "data/processed/ecl").glob("ecl_*.parquet"))
    if not runs:
        return None
    df = pd.read_parquet(runs[-1], columns=["loan_id", "stage"])
    hit = df[df.loan_id.astype(str) == account]
    return None if hit.empty else int(hit.stage.iloc[0])


def cmd_governance(args: argparse.Namespace, root: Path) -> None:
    """Module 9: manual overrides with maker-checker and an append-only audit log (ACPIR Annex
    3), and the model inventory check (paras 120-121). Prints the result of each command."""
    from ecl.governance.inventory import check_inventory
    from ecl.governance.overrides import OverrideError, OverrideLog, TamperError

    gov = _config(root, "governance.yaml")
    log = OverrideLog(root / gov["overrides"]["log_path"], gov["overrides"]["allowed"])
    a = args
    try:
        if a.action == "propose":
            oid = log.propose(
                a.account, "stage", a.stage, a.reason, a.maker, a.designation,
                a.effective_from, old_value=_current_stage(root, a.account),
                npa_exception=a.npa_exception,
            )  # fmt: skip
            print(f"{oid} proposed; needs approval by a different user")
        elif a.action == "approve":
            log.approve(a.id, a.checker, a.designation, a.reason)
            print(f"{a.id} approved; applies from the next ECL run")
        elif a.action == "revoke":
            log.revoke(a.id, a.maker, a.designation, a.reason)
            print(f"{a.id} revocation proposed")
        elif a.action == "approve-revoke":
            log.approve_revoke(a.id, a.checker, a.designation, a.reason)
            print(f"{a.id} revoked")
        elif a.action == "list":
            print(log.state().to_string(index=False) or "no overrides")
        elif a.action == "verify":
            print(f"log verified; head hash {log.verify()}")
        elif a.action == "inventory":

            def exists(c: str) -> bool:
                return (
                    subprocess.run(
                        ["git", "cat-file", "-e", f"{c}^{{commit}}"],
                        cwd=root,
                        capture_output=True,
                        check=False,
                    ).returncode
                    == 0
                )

            found = check_inventory(
                _config(root, "models.yaml")["models"],
                gov["inventory"]["required_fields"],
                _config(root, "overlays.yaml")["overlays"],
                root,
                exists if gov["inventory"].get("resolve_commits", True) else None,
            )
            print("\n".join(found) if found else "inventory complete: no findings")
            sys.exit(1 if found else 0)
    except (OverrideError, TamperError) as err:
        sys.exit(f"rejected: {err}")


# ----------------------------------------------------------------------------- parser


def build_parser(root: Path) -> argparse.ArgumentParser:
    """Argument parser with one subcommand per pipeline step."""
    from ecl.data.hpi import DEFAULT_HPI_PATH, DEFAULT_NATIONAL_HPI_PATH
    from ecl.pd.dataset import SEED

    ap = argparse.ArgumentParser(prog="ecl", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build-panel", help="Module 1: loan-month panel")
    p.add_argument("--raw-dir", default=root / "data" / "raw", type=Path)
    p.add_argument("--out", default=root / "data" / "processed", type=Path)
    p.add_argument("--reports", default=root / "reports" / "summary", type=Path)
    p.add_argument("--vintages", help="subset to rebuild, e.g. 2005-2007 or 2005,2017")
    p.add_argument(
        "--cure-months",
        default=[12, 18],
        type=int,
        nargs="+",
        help="cure windows for the Option B PD training targets",
    )
    p.set_defaults(func=cmd_build_panel)

    p = sub.add_parser("build-pd-dataset", help="Module 2a: PD modelling dataset")
    p.add_argument("--processed", default=root / "data" / "processed", type=Path)
    p.add_argument("--out", type=Path, help="default: <processed>/pd_dataset")
    p.add_argument("--reports", default=root / "reports" / "summary", type=Path)
    p.add_argument("--hpi", default=DEFAULT_HPI_PATH, type=Path)
    p.add_argument("--hpi-national", default=DEFAULT_NATIONAL_HPI_PATH, type=Path)
    p.add_argument("--seed", default=SEED, type=int)
    p.set_defaults(func=cmd_build_pd_dataset)

    p = sub.add_parser("train", help="fit a model: pd-12m, pd-pit, pd-lifetime or lgd")
    p.add_argument("model", choices=["pd-12m", "pd-pit", "pd-lifetime", "lgd"])
    p.add_argument("--rebuild-cells", action="store_true", help="pd-pit: rescan all snapshots")
    p.add_argument("--fit-only", action="store_true", help="lgd: skip the reporting dates")
    p.add_argument("--date", action="append", help="lgd: reporting date (repeatable)")
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("scenarios", help="Module 4: macro scenarios and Table 5")
    p.add_argument("--date", action="append", help="reporting date YYYY-MM-DD (repeatable)")
    p.set_defaults(func=cmd_scenarios)

    p = sub.add_parser("crisis-replay", help="Module 4: crisis replay and CO-3 calibration")
    p.set_defaults(func=cmd_crisis_replay)

    p = sub.add_parser("scenario-pd", help="Module 4: scenario-weighted PDs")
    p.add_argument("--date", action="append", help="reporting date YYYY-MM-DD (repeatable)")
    p.add_argument("--skip-early-performance", action="store_true")
    p.set_defaults(func=cmd_scenario_pd)

    p = sub.add_parser("run", help="Modules 6-8: staging, ECL and floors")
    p.add_argument("--date", help="one reporting date from config/scenarios.yaml")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("report", help="Module 10: Annex 4 tables and transition")
    p.set_defaults(func=cmd_report)

    for name, text in [
        ("backtest", "Module 11: ECL backtest of a reporting date"),
        ("validate", "Module 11: backtest plus the relief-cure double-count check (M-1)"),
    ]:
        p = sub.add_parser(name, help=text)
        p.add_argument("--date", default="2023-03-31")
        p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("india", help="Module 12: SYNTHETIC Indian book")
    p.set_defaults(func=cmd_india)

    p = sub.add_parser("governance", help="Module 9: overrides, audit log, inventory")
    gsub = p.add_subparsers(dest="action", required=True)
    q = gsub.add_parser("propose")
    q.add_argument("--account", required=True)
    q.add_argument("--stage", type=int, required=True)
    q.add_argument("--reason", required=True)
    q.add_argument("--maker", required=True)
    q.add_argument("--designation", required=True)
    q.add_argument("--effective-from", required=True)
    q.add_argument("--npa-exception", action="store_true")
    for name, who in [("approve", "checker"), ("revoke", "maker"), ("approve-revoke", "checker")]:
        q = gsub.add_parser(name)
        q.add_argument("--id", required=True)
        q.add_argument(f"--{who}", required=True)
        q.add_argument("--designation", required=True)
        q.add_argument("--reason", required=True)
    for name in ["list", "verify", "inventory"]:
        gsub.add_parser(name)
    p.set_defaults(func=cmd_governance)
    return ap


def main(argv: list[str] | None = None) -> None:
    """Entry point of the `ecl` command."""
    root = project_root()
    args = build_parser(root).parse_args(argv)
    if args.command != "governance":
        configure_logging()
    args.func(args, root)


if __name__ == "__main__":
    main()
