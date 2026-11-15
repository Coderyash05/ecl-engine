"""Module 12 entry point: SYNTHETIC Indian housing book, end to end (macro inventory and
splices, Indian scenarios and Table 5, synthetic book, ECL with the engine's staging and floors,
sensitivities, Annex 4 tables, old-rules provision and transition, US comparison).

Outputs (aggregates only; the loan-level synthetic book is derived from Freddie Mac loans and
stays in data/processed/india/): reports/summary/india/. Every table is labelled SYNTHETIC.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ecl.india import engine, macro, portfolio, scenarios
from ecl.reporting.annex4 import (
    old_rules_table,
    old_vs_ecl_by_segment,
    table1,
    table2,
    table7,
    transition,
    with_old_rules,
    write_tables,
)

logger = logging.getLogger(__name__)

NOTE = (
    "SYNTHETIC Indian housing book derived from US (Freddie Mac) loans under documented "
    "assumptions (docs/india_adapter.md); real RBI DBIE macro series; NOT Indian risk "
    "estimates; amounts in Rs crore"
)


def base_params(cfg: dict, k: float) -> dict:
    """Base-case parameters of the synthetic measurement (calibration multiplier k, employment PD
    multiplier, payment-shock beta, prepayment, LGD assumptions) from the India config."""
    pc, lg = cfg["portfolio"], cfg["lgd"]
    return {
        "k": k,
        "pd_multiplier_self_employed": pc["employment"]["pd_multiplier_self_employed"],
        "pd_beta": pc["payment_shock"]["pd_beta"],
        "prepayment_cpr": pc["prepayment_cpr"],
        "p_no_cure": lg["p_no_cure"],
        "realisation_haircut": lg["realisation_haircut"],
        "stage3_p_no_cure": lg["stage3_p_no_cure"],
    }


def sensitivity_specs(cfg: dict) -> list[tuple[str, dict, float]]:
    """(name, parameter overrides, Z elasticity)."""
    pc, lg, sc = cfg["portfolio"], cfg["lgd"], cfg["scenarios"]
    out = []
    for v in pc["employment"]["pd_multiplier_sensitivity"]:
        out.append((f"self-employed PD multiplier {v}", {"pd_multiplier_self_employed": v}, 1.0))
    for v in pc["payment_shock"]["pd_beta_sensitivity"]:
        out.append((f"payment-shock beta {v}", {"pd_beta": v}, 1.0))
    out.append(("repo +2 pp in every scenario (payment shock)", {"repo_shift": 2.0}, 1.0))
    for v in pc["prepayment_cpr_sensitivity"]:
        out.append((f"prepayment CPR {v:.0%}", {"prepayment_cpr": v}, 1.0))
    for v in lg["p_no_cure_sensitivity"]:
        out.append((f"P(no cure) {v}", {"p_no_cure": v}, 1.0))
    for v in lg["realisation_haircut_sensitivity"]:
        out.append((f"realisation haircut {v:.0%}", {"realisation_haircut": v}, 1.0))
    for v in sc["z_hpi_elasticity_sensitivity"]:
        out.append((f"Z elasticity to Indian HPI and GDP x{v}", {}, v))
    out.append(("PD level x2 (GNPA stock unchanged)", {"pd_level": 2.0}, 1.0))
    out.append(("RBI fallback LGD 65 / 70% (para 97)", {"fallback_lgd": True}, 1.0))
    return out


def us_inputs(root: Path, us_tag: str) -> pd.DataFrame:
    """US loan-level ECL output of `us_tag` joined with the origination attributes the synthetic
    book is derived from."""
    us = pd.read_parquet(root / f"data/processed/ecl/ecl_{us_tag}.parquet")
    con = duckdb.connect(str(root / "data/processed/ecl.duckdb"), read_only=True)
    ln = con.execute(
        "SELECT loan_id, orig_upb, orig_ltv, orig_dti, orig_loan_term, num_borrowers, "
        "first_payment_date FROM loans_all ORDER BY loan_id"
    ).df()
    con.close()
    return us.merge(ln, on="loan_id", how="left")


def us_z(root: Path, us_tag: str, h: int) -> dict:
    """Mean US satellite Z per scenario over the first 4 forecast quarters (z1) and the first `h`
    quarters (z12), the anchor points of the Indian Z shift."""
    p = pd.read_csv(root / f"reports/summary/scenarios_paths_{us_tag}.csv")
    f = p[p.forecast]
    g = f.groupby("scenario").z_satellite
    return {
        "z1": g.apply(lambda s: s.iloc[:4].mean()).to_dict(),
        "z12": g.apply(lambda s: s.iloc[:h].mean()).to_dict(),
    }


def book_profile(b: pd.DataFrame) -> pd.DataFrame:
    """Synthetic book composition (exposure shares and counts)."""
    rows = []
    e = b.ead_now.sum()

    def add(dim: str, ser: pd.Series) -> None:
        for k, g in b.groupby(ser, observed=True):
            rows.append(
                {
                    "dimension": dim,
                    "value": str(k),
                    "loans": len(g),
                    "exposure_share": g.ead_now.sum() / e,
                }
            )

    add("CIBIL band", pd.cut(b.cibil, [299, 650, 700, 750, 800, 900]))
    add("ticket (Rs lakh)", pd.cut(b.orig_amount_lakh, [0, 30, 75, np.inf]))
    add("LTV cap at origination", b.ltv_cap)
    add("current LTV band", pd.cut(b.current_ltv, [-1, 40, 60, 80, 100, np.inf]))
    add("city tier", b.city_tier)
    add("employment", np.where(b.self_employed, "self-employed", "salaried"))
    add("co-borrower", b.co_borrower)
    add(
        "EMI increase now (central)",
        pd.cut(b.payment_shock_central, [-1, 0, 0.05, 0.10, 0.25, np.inf]),
    )
    add(
        "remaining tenure (years, central)",
        pd.cut(b.remaining_months_central / 12, [0, 5, 10, 15, 20, 30]),
    )
    return pd.DataFrame(rows)


def stage_summary(prov: dict) -> dict:
    """Model ECL, provision, exposure and coverage per stage."""
    return {
        s: {
            k: prov[s][k]
            for k in ["model_ecl", "provision", "exposure", "coverage_model", "coverage_provision"]
            if k in prov[s]
        }
        | ({"loans": prov[s].get("loans", prov[s].get("accounts"))} if s != "total" else {})
        | (
            {"floor_binds": prov[s].get("binds", prov[s].get("binds_accounts"))}
            if s != "total"
            else {}
        )
        for s in ["stage1", "stage2", "stage3", "total"]
    }


def comparison(
    us_rec: dict, us_tr: dict, india: dict, india_tr: dict, us_n: dict, in_n: dict
) -> pd.DataFrame:
    """Synthetic India vs US book by stage: loans, exposure shares, model and provision coverage,
    where the floors bind, and the transition impact (all labelled SYNTHETIC for India)."""
    rows = []
    for s in ["stage1", "stage2", "stage3", "total"]:
        u, i = us_rec["by_stage"][s], india[s]
        rows.append(
            {
                "stage": s,
                "US loans": us_n.get(s),
                "India loans (synthetic)": in_n.get(s),
                "US exposure share": u["exposure"] / us_rec["by_stage"]["total"]["exposure"],
                "India exposure share": i["exposure"] / india["total"]["exposure"],
                "US model coverage": u["coverage_model"],
                "India model coverage": i["coverage_model"],
                "US provision coverage": u["coverage_provision"],
                "India provision coverage": i["coverage_provision"],
                "US floor binds": u.get("binds", u.get("binds_accounts")),
                "India floor binds": i.get("floor_binds"),
            }
        )
    rows.append(
        {
            "stage": "transition (dry run 2026-03-31)",
            "US provision coverage": us_tr["ecl_allowance"]
            / us_rec["by_stage"]["total"]["exposure"],
            "India provision coverage": india_tr["ecl_allowance"] / india["total"]["exposure"],
            "US loans": f"ECL {us_tr['ecl_allowance'] / 1e6:,.1f}m vs IRACP {us_tr['iracp_provision'] / 1e6:,.1f}m; impact {us_tr['impact'] / 1e6:,.1f}m",
            "India loans (synthetic)": f"ECL Rs {india_tr['ecl_allowance']:,.1f} cr vs IRACP Rs {india_tr['iracp_provision']:,.1f} cr; impact Rs {india_tr['impact']:,.1f} cr",
        }
    )
    return pd.DataFrame(rows)


def run_india(
    root: Path,
    cfg: dict,
    ecl_cfg: dict,
    rbi: dict,
    iracp: dict,
    credit_facilities: dict,
    git: dict,
) -> dict:
    """Module 12 end to end on the SYNTHETIC Indian book: load and check the Indian macro data,
    build the scenarios and the book, measure ECL with the engine's staging and floors, the
    old-rules provision, the transition and sensitivities. Writes aggregate tables to the
    configured output folder; not Indian risk estimates."""
    as_of = cfg["as_of"]
    tag = pd.Timestamp(as_of).strftime("%Y-%m")
    out_dir = root / cfg["outputs"]["dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    d, f = root / cfg["macro"]["dir"], cfg["macro"]["files"]
    m = macro.load_all(d, cfg["macro"])
    inv, hpi, checks, repo_q = m["inventory"], m["hpi"], m["hpi_checks"], m["repo_q"]
    for row in inv.itertuples(index=False):
        logger.info(
            f"  {row.series}: base {row.base}, {row.first}-{row.last}, {row.frequency}, {row.rows} rows"
        )
    repo_now = macro.repo_at(d / f["repo"], as_of)
    mf = scenarios.macro_frame(hpi["All India"], m["gdp_yoy"], m["cpi"])
    meta = json.loads((root / "models/pd_pit/metadata.json").read_text())
    sat, zlr = meta["satellite"]["params"], meta["long_run_z"]
    sc = scenarios.build(mf, repo_q, repo_now, as_of, cfg, sat, zlr)
    logger.info(
        f"Scenarios: VAR {sc['var']['window']} ex {sc['var']['excluded']}; repo {sc['repo_shift_pp']}"
    )
    us = us_inputs(root, tag)
    book, stats = portfolio.build_book(
        us, hpi, repo_q, repo_now, as_of, cfg, credit_facilities["ltv_individual_housing"]["bands"]
    )
    logger.info(f"Synthetic book {stats}")
    z_us = us_z(root, tag, cfg["scenarios"]["horizon_quarters"])
    p0 = base_params(cfg, stats["pd_calibration_k"])
    b, prov = engine.measure(book, sc, cfg, ecl_cfg, rbi, z_us, p0)
    base = stage_summary(prov)
    logger.info(
        f"Provision Rs {base['total']['provision']:,.1f} crore ({base['total']['coverage_provision']:.2%})"
    )
    sens = [
        {
            "sensitivity": "base",
            "provision_rs_crore": base["total"]["provision"],
            "model_ecl_rs_crore": base["total"]["model_ecl"],
            "stage2_loans": int((b.stage == 2).sum()),
        }
    ]
    for name, over, el in sensitivity_specs(cfg):
        sc_x = sc if el == 1.0 else scenarios.build(mf, repo_q, repo_now, as_of, cfg, sat, zlr, el)
        bx, px = engine.measure(book, sc_x, cfg, ecl_cfg, rbi, z_us, p0 | over)
        sens.append(
            {
                "sensitivity": name,
                "provision_rs_crore": px["total"]["provision"],
                "model_ecl_rs_crore": px["total"]["model_ecl"],
                "stage2_loans": int((bx.stage == 2).sum()),
            }
        )
    sens = pd.DataFrame(sens)
    sens["change_vs_base"] = sens.provision_rs_crore / base["total"]["provision"] - 1
    # old rules and transition (same IRACP code and config as the US book)
    b["npa"] = b.stage == 3
    b["npa_years"] = b.years_s3.fillna(b.months_in_default / 12)
    for c, v in [
        ("restructured_cal", False),
        ("events_cal", 0),
        ("restr_state_cal", np.nan),
        ("stuck", False),
        ("modification_events", 0),
    ]:
        b[c] = v
    b = with_old_rules(b, iracp)
    sched, t9, tr = transition(b, rbi)
    # Annex 4 tables (synthetic)
    t4 = pd.DataFrame(
        [
            {
                "Financial instrument": "Loans (SYNTHETIC)",
                "Brief of the product": "Synthetic Indian floating-rate (repo-linked) housing loans to individuals, derived from US loans",
                "Category": "Housing loans to individuals (item (xi)(a))",
                "PD-TTC Stage 1": float(
                    np.average(b.pd12_ttc[b.stage == 1], weights=b.ead_now[b.stage == 1])
                ),
                "PD-TTC Stage 2": float(
                    np.average(b.pd12_ttc[b.stage == 2], weights=b.ead_now[b.stage == 2])
                ),
                "PD approach": "US scorecard rank order, US hazard macro sensitivity at Indian Z (HPI only), calibrated to GNPA 0.5%; employment and payment-shock multipliers (assumptions)",
                "LGD (12-month, scenario-weighted, Stages 1-2)": float(
                    np.average(b.lgd12_weighted[b.stage < 3], weights=b.ead_now[b.stage < 3])
                ),
                "LGD approach": "P(no cure) x collateral severity with RBI HPI-indexed values, realisation haircut, recovery time (assumptions)",
            }
        ]
    )
    t6 = pd.DataFrame(
        [
            {
                "row": "Post Model Adjustments / Management Overlays",
                "amount": 0.0,
                "note": "none applied to the synthetic book (US CO-3 / CO-5 are US-calibrated)",
            }
        ]
    )
    t8 = pd.DataFrame(
        [
            {
                "Loan product category": "Housing loans to individuals (item (xi)(a))",
                "Internal loan product": "SYNTHETIC repo-linked floating-rate home loan",
                "SICR criteria": "as the US engine (config/ecl.yaml): 30+ dpd backstop; lifetime PD ratio and absolute thresholds; indexed LTV; RBI default until arrears cleared",
                "Segmentation criteria": "none - loan level (para 68)",
                "Number of segments": 1,
            }
        ]
    )
    stage_rules = (
        b.groupby(["stage", "stage_rule"])
        .agg(loans=("loan_id", "size"), exposure=("ead_now", "sum"))
        .reset_index()
    )
    tables = {
        "t1": ("Table 1.A Credit quality of loan assets (SYNTHETIC)", table1(b, None)),
        "t2": ("Table 2 Summary of loan assets (SYNTHETIC)", table2(b, None)),
        "t4": ("Table 4 Approach for ECL (SYNTHETIC)", t4),
        "t5": ("Table 5 Macroeconomic assumptions - India (RBI DBIE / MoSPI series)", sc["table5"]),
        "t6": ("Table 6 ECL adjustments (SYNTHETIC)", t6),
        "t7": ("Table 7 ECL data (SYNTHETIC)", table7(b)),
        "t8": ("Table 8 SICR criteria (SYNTHETIC)", t8),
        "t8rules": ("Table 8 supplement: stage rule (SYNTHETIC)", stage_rules),
        "t9": ("Table 9 Transitional adjustments (SYNTHETIC)", t9),
        "old_rules": ("Old-rules (IRACP 2025) provision (SYNTHETIC)", old_rules_table(b)),
        "old_vs_ecl": ("Old rules vs ECL by segment (SYNTHETIC)", old_vs_ecl_by_segment(b)),
        "transition": ("Transition: CET1 add-back schedule (pre-tax; SYNTHETIC)", sched),
    }
    mt = {
        "ecl_version": f"{cfg['version']} / {ecl_cfg['version']}",
        "iracp_version": iracp["version"],
        "ltv_caps": f"{credit_facilities['version']} para {credit_facilities['ltv_individual_housing']['para']}",
        "run_git": git["commit"][:7],
        "run_clean": git["clean"],
        "report_git": git["commit"][:7],
        "dry_run": True,
        "data_note": NOTE,
    }
    md = write_tables(out_dir, as_of, {f"india_{k}": v for k, v in tables.items()}, mt)
    # comparison with the US book
    us_rec = json.loads((root / f"models/ecl/ecl_{tag}.json").read_text())
    us_tr = json.loads((root / "reports/summary/annex4/annex4_summary.json").read_text())[as_of]
    us_n = {
        f"stage{s}": int(n)
        for s, n in pd.read_parquet(
            root / f"data/processed/ecl/ecl_{tag}.parquet", columns=["stage"]
        )
        .stage.value_counts()
        .items()
    }
    in_n = {f"stage{s}": int(n) for s, n in b.stage.value_counts().items()}
    comp = comparison(us_rec, us_tr, base, tr, us_n, in_n)
    prof = book_profile(b)
    for name, df in [
        ("india_data_inventory", inv),
        ("india_hpi_splice_checks", checks),
        (
            "india_gdp_overlap",
            pd.DataFrame(
                [
                    {"quarter": q, "yoy_base_2011_12": v[0], "yoy_base_2022_23": v[1]}
                    for q, v in m["gdp_stats"]["by_quarter"].items()
                ]
            ),
        ),
        ("india_macro_history", mf.reset_index(names="quarter").astype({"quarter": str})),
        ("india_scenario_paths", sc["paths"]),
        ("india_sensitivities", sens),
        ("india_vs_us", comp),
        ("india_book_profile", prof),
    ]:
        with (out_dir / f"{name}_{tag}.csv").open("w", encoding="utf-8", newline="") as fh:
            fh.write(f"# {NOTE}\n")
            df.to_csv(fh, index=False)
    gnpa = float(
        b.ead_now[b.stage_rule.isin(["default", "default_arrears"])].sum() / b.ead_now.sum()
    )
    summary = {
        "label": cfg["label"],
        "as_of": as_of,
        "git": git,
        "config_version": cfg["version"],
        "book": stats | {"gnpa_exposure_share": gnpa, "exposure_rs_crore": float(b.ead_now.sum())},
        "scenarios": {k: sc[k] for k in ["var", "repo_shift_pp", "repo_now"]},
        "gdp_chain": {k: v for k, v in m["gdp_stats"].items() if k != "by_quarter"},
        "cpi_link": m["cpi_stats"],
        "provision": base,
        "transition": tr,
        "markdown": str(md.relative_to(root)),
    }
    (out_dir / f"india_summary_{tag}.json").write_text(json.dumps(summary, indent=2, default=float))
    proc = root / "data/processed/india"
    proc.mkdir(parents=True, exist_ok=True)
    b.drop(columns=["rules_fired"]).to_parquet(proc / f"india_book_{tag}.parquet", index=False)
    return summary | {"sensitivities": sens, "comparison": comp}
