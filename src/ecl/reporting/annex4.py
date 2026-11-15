"""Annex 4 disclosure tables 1-9, old-rules (IRACP) provision and the ECL transition (Module 10).

Entry point `build_reports(root, cfg, rbi, iracp, dates, git)`: for each reporting date it
reads the Modules 6-8 outputs (loan level `data/processed/ecl/ecl_{YYYY-MM}.parquet`, run record
`models/ecl/ecl_{YYYY-MM}.json`) and the Module 4 Table 5, and writes
`reports/summary/annex4/annex4_t{n}_{YYYY-MM}.csv` plus one Markdown file per date, and the
transition (ACPIR paras 107-108) for the dry-run first-application date.

Tables follow the ACPIR Annex 4 formats (docs/reference/RBI-Directions.pdf): 1 credit quality by
DPD bucket x stage; 2 summary of loan assets; 3 reconciliation of loss allowance; 4 approach for
ECL; 5 macroeconomic assumptions; 6 ECL adjustments; 7 ECL data (forward-looking PD, LGD);
8 SICR criteria; 9 reconciliation of opening reserves (transitional adjustments). Loss allowance
= final provision after the prudential floors (ACPIR 90); a portfolio floor uplift is allocated
to loans pro rata to exposure (presentation). Gross carrying amount = EAD now (UPB + accrued
interest). POCI: none (the sample has no purchased or originated credit-impaired loans).
US data (Freddie Mac sample) - amounts in US dollars, not Indian risk estimates.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ecl.reporting.iracp import old_rules_provision

logger = logging.getLogger(__name__)

STAGES = [1, 2, 3]
CATEGORY_NAMES = {
    "xi_a": "Housing loans to individuals (item (xi)(a))",
    "xiv": "Advances restructured and classified as standard - calamity (item (xiv))",
}
DPD_ROWS = [
    ("Current / past due 1-30 days (status 00 or not yet reported)", ["current", "unknown"]),
    ("Past due 31-60 days (status 01: 30-59)", ["30-59"]),
    ("Past due 61-90 days (status 02: 60-89)", ["60-89"]),
    ("Past due 90 days + (status 03+ / REO)", ["90+"]),
]
LOSS_ZB = ("02", "03", "09", "15")  # loss-type terminations (third-party sale, short sale /
# charge-off, REO disposition, whole-loan sale of a defaulted loan) -> write-off


def _tag(date: str) -> str:
    return pd.Timestamp(date).strftime("%Y-%m")


def load_run(root: Path, date: str) -> tuple[pd.DataFrame, dict]:
    """Loan-level ECL output and run record of a reporting date."""
    t = _tag(date)
    df = pd.read_parquet(root / f"data/processed/ecl/ecl_{t}.parquet")
    rec = json.loads((root / f"models/ecl/ecl_{t}.json").read_text())
    df["npa"] = df.stage == 3
    df["npa_years"] = df.years_s3.fillna(df.months_in_default / 12)
    return df, rec


def with_old_rules(df: pd.DataFrame, iracp: dict) -> pd.DataFrame:
    """Add the IRACP provision per loan (ecl.reporting.iracp)."""
    x = df.assign(
        calamity_events=np.where(df.restructured_cal, df.events_cal, 0),
        calamity_written_back=df.restr_state_cal.eq(1),
        failed_monitoring=df.stuck,
    )
    return pd.concat([df, old_rules_provision(x, iracp)], axis=1)


def _stage_cols(df: pd.DataFrame, value: str) -> dict:
    out = {f"Stage {s}": float(df.loc[df.stage == s, value].sum()) for s in STAGES}
    out["POCI"] = 0.0
    out["Total"] = float(df[value].sum())
    return out


def table1(cur: pd.DataFrame, prev: pd.DataFrame | None) -> pd.DataFrame:
    """Table 1.A credit quality of loan assets: gross carrying amount by DPD bucket x stage,
    impairment loss allowance, net carrying amount; per loan product category."""
    rows = []
    for cat in sorted(cur.category.unique()):
        for label, frame in [("current year", cur), ("previous year", prev)]:
            if frame is None:
                continue
            f = frame[frame.category == cat]
            for name, buckets in DPD_ROWS:
                rows.append(
                    {"category": CATEGORY_NAMES[cat], "year": label, "row": name}
                    | _stage_cols(f[f.dpd_bucket.isin(buckets)], "ead_now")
                )
            g = _stage_cols(f, "ead_now")
            a = _stage_cols(f, "allowance")
            rows.append(
                {"category": CATEGORY_NAMES[cat], "year": label, "row": "Gross Carrying Amount"} | g
            )
            rows.append(
                {"category": CATEGORY_NAMES[cat], "year": label, "row": "Impairment loss allowance"}
                | a
            )
            rows.append(
                {"category": CATEGORY_NAMES[cat], "year": label, "row": "Net Carrying amount"}
                | {k: g[k] - a[k] for k in g}
            )
    return pd.DataFrame(rows)


def table2(cur: pd.DataFrame, prev: pd.DataFrame | None) -> pd.DataFrame:
    """Table 2 summary of loan assets by stage."""
    rows = []
    for label, frame in [("current year", cur), ("previous year", prev)]:
        if frame is None:
            continue
        g, a = _stage_cols(frame, "ead_now"), _stage_cols(frame, "allowance")
        rows += [
            {"year": label, "row": "Gross carrying amount"} | g,
            {"year": label, "row": "Less: ECL allowance"} | a,
            {"year": label, "row": "Net carrying amount"} | {k: g[k] - a[k] for k in g},
        ]
    return pd.DataFrame(rows)


def exits(processed: Path, ids: pd.Series, open_date: str, close_date: str) -> pd.DataFrame:
    """For opening loans: last zero-balance code in (open, close] and first panel month (to tell
    new originations from loans re-entering the population)."""
    con = duckdb.connect()
    con.register("ids", pd.DataFrame({"loan_id": ids.values}))
    panel = (processed / "panel").as_posix() + "/*/*.parquet"
    out = con.execute(f"""
        SELECT p.loan_id,
               ARG_MAX(p.zb_code, p.period) FILTER (WHERE p.zb_code IS NOT NULL
                   AND p.period > DATE '{open_date}' AND p.period <= DATE '{close_date}') AS zb_code,
               MIN(p.period) AS first_period
        FROM read_parquet('{panel}', hive_partitioning=true) p JOIN ids USING (loan_id)
        GROUP BY 1 ORDER BY 1""").df()
    con.close()
    return out


def reconciliation(
    opening: pd.DataFrame, closing: pd.DataFrame, info: pd.DataFrame, open_date: str
) -> pd.DataFrame:
    """Table 3.A reconciliation of gross loan amount and loss allowance by stage. Transfers
    move the opening amounts of loans that changed stage; net remeasurement = closing - opening
    for continuing loans (in the closing stage); new = loans first observed after the opening
    date; matured / repaid = opening loans derecognised without loss; write-offs = opening
    loans derecognised with a loss-type zero-balance code; other = population changes."""
    o = opening[["loan_id", "stage", "ead_now", "allowance"]]
    c = closing[["loan_id", "stage", "ead_now", "allowance"]]
    m = o.merge(c, on="loan_id", how="outer", suffixes=("_o", "_c"), indicator=True)
    m = m.merge(info, on="loan_id", how="left")
    lines = {
        k: {(s, v): 0.0 for s in STAGES for v in ("gross", "ecl")}
        for k in [
            "Balance at the opening date",
            "Transfer to Stage 1",
            "Transfer to Stage 2",
            "Transfer to Stage 3",
            "Net remeasurement of loss allowance (gross: balance change)",
            "New financial assets originated during the year",
            "Matured or repaid",
            "Write-offs (loss-type terminations)",
            "Other (population changes)",
        ]
    }

    def add(line: str, stage: int, g: float, e: float) -> None:
        lines[line][(int(stage), "gross")] += float(g)
        lines[line][(int(stage), "ecl")] += float(e)

    for r in m[m._merge != "right_only"].itertuples():
        add("Balance at the opening date", r.stage_o, r.ead_now_o, r.allowance_o)
    both = m[m._merge == "both"]
    for r in both.itertuples():
        if r.stage_o != r.stage_c:
            line = f"Transfer to Stage {int(r.stage_c)}"
            add(line, r.stage_o, -r.ead_now_o, -r.allowance_o)
            add(line, r.stage_c, r.ead_now_o, r.allowance_o)
        add(
            "Net remeasurement of loss allowance (gross: balance change)",
            r.stage_c,
            r.ead_now_c - r.ead_now_o,
            r.allowance_c - r.allowance_o,
        )
    new_mask = m._merge == "right_only"
    for r in m[new_mask].itertuples():
        is_new = pd.notna(r.first_period) and r.first_period > pd.Timestamp(open_date)
        line = (
            "New financial assets originated during the year"
            if is_new
            else "Other (population changes)"
        )
        add(line, r.stage_c, r.ead_now_c, r.allowance_c)
    for r in m[m._merge == "left_only"].itertuples():
        zb = None if pd.isna(r.zb_code) else str(r.zb_code)
        if zb in LOSS_ZB:
            line = "Write-offs (loss-type terminations)"
        elif zb is not None:
            line = "Matured or repaid"
        else:
            line = "Other (population changes)"
        add(line, r.stage_o, -r.ead_now_o, -r.allowance_o)
    rows = []
    for k, v in lines.items():
        row = {"row": k}
        for s in STAGES:
            row[f"Stage {s} gross"], row[f"Stage {s} ECL"] = v[(s, "gross")], v[(s, "ecl")]
        row["Total gross"] = sum(v[(s, "gross")] for s in STAGES)
        row["Total ECL"] = sum(v[(s, "ecl")] for s in STAGES)
        rows.append(row)
    t = pd.DataFrame(rows)
    close_row = {"row": "Balance at the closing date"} | t.drop(columns="row").sum().to_dict()
    check = _stage_cols(closing, "allowance")
    close_row["check_closing_ecl_from_data"] = check["Total"]
    return pd.concat([t, pd.DataFrame([close_row])], ignore_index=True)


def _w(df: pd.DataFrame, col: str, w: str = "ead_now") -> float:
    d = df[df[col].notna()]
    return float(np.average(d[col], weights=d[w])) if len(d) and d[w].sum() > 0 else np.nan


def table4(cur: pd.DataFrame) -> pd.DataFrame:
    """Table 4 approach for ECL: PD-TTC (Module 2 scorecard, EAD-weighted) by stage and LGD."""
    rows = []
    for cat in sorted(cur.category.unique()):
        f = cur[cur.category == cat]
        rows.append(
            {
                "Financial instrument": "Loans",
                "Brief of the product": "US conforming 30-year fixed-rate first-lien mortgages "
                "(Freddie Mac sample), owner-occupied and investor",
                "Category": CATEGORY_NAMES[cat],
                "PD-TTC Stage 1": _w(f[f.stage == 1], "pd12_ttc"),
                "PD-TTC Stage 2": _w(f[f.stage == 2], "pd12_ttc"),
                "PD approach": "12-month TTC WoE logistic scorecard v1.2.0 (B-18 target); PIT "
                "via Vasicek Z-shift; lifetime by discrete-time hazard (pdlife-0.4.0); "
                "scenario-weighted (scen-0.2.0)",
                "LGD (12-month, scenario-weighted, Stages 1-2)": _w(
                    f[f.stage < 3], "lgd12_weighted"
                ),
                "LGD approach": "P(no cure | months in default) x discounted severity "
                "(lgd-0.2.0); HPI-indexed collateral; Stage 3 LGD by months in default; EAD from "
                "the amortisation schedule, no netting (para 100)",
            }
        )
    return pd.DataFrame(rows)


def table5(root: Path, date: str) -> pd.DataFrame:
    """Table 5 macroeconomic assumptions (Module 4 output)."""
    p = root / f"reports/summary/scenarios_table5_{_tag(date)}.csv"
    return (
        pd.read_csv(p)
        if p.exists()
        else pd.DataFrame({"note": ["Module 4 Table 5 not run for this date"]})
    )


def table6(cur: pd.DataFrame, prev: pd.DataFrame | None) -> pd.DataFrame:
    """Table 6 ECL adjustments: allowance before / after the post-model adjustments CO-3 (PD,
    downside) and CO-5 (LGD, downside), by product category; model ECL memo lines."""
    rows = []
    for label, frame in [("current year", cur), ("previous year", prev)]:
        if frame is None:
            continue
        for cat in sorted(frame.category.unique()):
            f = frame[frame.category == cat]
            before, after = f.allowance_noov.sum(), f.allowance.sum()
            rows += [
                {"year": label, "portfolio": CATEGORY_NAMES[cat], "row": r, "amount": v}
                for r, v in [
                    ("Loss allowance before judgmental adjustments", before),
                    ("Post Model Adjustment (CO-3 PD, CO-5 LGD; downside)", after - before),
                    ("Management Overlays", 0.0),
                    ("Any other", 0.0),
                    ("Loss allowance after judgmental adjustments", after),
                    (
                        "Memo: model ECL before adjustments (before floors)",
                        f.ecl_stage_model_noov.sum(),
                    ),
                    ("Memo: model ECL after adjustments (before floors)", f.ecl_stage_model.sum()),
                ]
            ]
    return pd.DataFrame(rows)


def table7(cur: pd.DataFrame) -> pd.DataFrame:
    """Table 7 ECL data: forward-looking PD and LGD by stage (EAD-weighted). Stage 1 PD =
    12-month, Stage 2 PD = lifetime (scenario-weighted); Stage 3 PD = 100%. LGD: Stage 1 = year-1
    LGD; Stage 2 = implied lifetime LGD (lifetime ECL / (lifetime PD x EAD)); Stage 3 = LGD in
    default (loans 90+ at the date)."""
    rows = []
    for cat in sorted(cur.category.unique()):
        f = cur[cur.category == cat]
        s2 = f[f.stage == 2]
        denom = (s2.pd_life_now * s2.ead_now).sum()
        d3 = f[(f.stage == 3) & f.in_default]
        rows.append(
            {
                "Loan product category": CATEGORY_NAMES[cat],
                "PD Stage 1 (12-month)": _w(f[f.stage == 1], "pd12_weighted"),
                "PD Stage 2 (lifetime)": _w(s2, "pd_life_now"),
                "PD Stage 3": 1.0,
                "LGD Stage 1": _w(f[f.stage == 1], "lgd12_weighted"),
                "LGD Stage 2 (implied lifetime)": float(s2.ecl_life_weighted.sum() / denom)
                if denom > 0
                else np.nan,
                "LGD Stage 3 (in default)": _w(d3, "lgd3"),
            }
        )
    return pd.DataFrame(rows)


def table8(cur: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Table 8 SICR criteria by product category, and the rules fired by segment."""
    st = cfg["staging"]
    crit = (
        f"Stage 2: > 30 dpd backstop (status 01-02; no rebuttals); lifetime PD now / origination-"
        f"expected lifetime PD >= {st['sicr_pd']['ratio_threshold']} and + "
        f"{st['sicr_pd']['absolute_threshold']:.1%} (para 26); indexed LTV >= "
        f"{st['collateral']['indexed_ltv_threshold']}% (Annex 1); restructured with 10-20% repaid. "
        "Stage 3: RBI default (90+, REO) until arrears cleared (para 8(10)); restructured until "
        "the RSA monitoring period is met (RSA 58, 61)"
    )
    t = pd.DataFrame(
        [
            {
                "Loan product category": CATEGORY_NAMES[c],
                "Internal loan product": "US 30-year fixed-rate conforming mortgage",
                "SICR criteria": crit,
                "Segmentation criteria": "none - loan level, uniform thresholds (para 68)",
                "Number of segments": 1,
            }
            for c in sorted(cur.category.unique())
        ]
    )
    seg = cur.assign(
        region=np.where(cur.property_state.isin(["CA", "FL", "NV", "AZ"]), "CA/FL/NV/AZ", "other")
    )
    seg = (
        seg.assign(rule=seg.stage_rule)
        .groupby(["category", "region", "stage", "rule"])
        .agg(loans=("loan_id", "size"), ead=("ead_now", "sum"))
    )
    return t, seg.reset_index()


def transition(cur: pd.DataFrame, rbi: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """ACPIR 107-108: impact = max(0, ECL - IRACP provisions); CET1 add-back schedule (pre-tax:
    the Directions apply the fractions net of applicable taxes; no tax rate is modelled). Table 9
    transitional adjustments by stage = ECL allowance - IRACP provision on the stage's loans."""
    ecl, old = float(cur.allowance.sum()), float(cur.iracp_provision.sum())
    impact = max(0.0, ecl - old)
    tr = rbi["transition"]
    sched = pd.DataFrame(
        [
            {
                "financial_year": fy,
                "max_fraction": f,
                "max_addback_to_cet1_pre_tax": f * impact,
            }
            for fy, f in tr["cet1_addback_max_share"].items()
        ]
    )
    t9 = pd.DataFrame(
        [
            {
                "row": f"Stage {s} adjustment",
                "ecl_allowance": float(cur.loc[cur.stage == s, "allowance"].sum()),
                "iracp_provision": float(cur.loc[cur.stage == s, "iracp_provision"].sum()),
            }
            for s in STAGES
        ]
    )
    t9["adjustment"] = t9.ecl_allowance - t9.iracp_provision
    t9 = pd.concat(
        [
            pd.DataFrame(
                [
                    {"row": "Opening retained earnings under extant norms", "adjustment": np.nan},
                    {
                        "row": "Add: Effect of transitional adjustments",
                        "adjustment": -t9.adjustment.sum(),
                    },
                ]
            ),
            t9,
        ],
        ignore_index=True,
    )
    summary = {
        "ecl_allowance": ecl,
        "iracp_provision": old,
        "impact": impact,
        "formula": tr["impact"],
        "paras": tr["para"],
    }
    return sched, t9, summary


def old_rules_table(cur: pd.DataFrame) -> pd.DataFrame:
    """IRACP provision by asset class and by ECL stage."""
    g = cur.groupby(["asset_class", "stage"]).agg(
        loans=("loan_id", "size"),
        outstanding=("ead_now", "sum"),
        iracp_base=("iracp_base", "sum"),
        iracp_additional=("iracp_additional", "sum"),
        iracp_provision=("iracp_provision", "sum"),
        ecl_allowance=("allowance", "sum"),
    )
    return g.reset_index()


SEGMENTS = [
    "Stage 1",
    "Stage 2",
    "Stage 3 non-restructured (default / arrears not cleared)",
    "Stage 3 restructured - modification",
    "Stage 3 restructured - general deferral",
    "Calamity route (xiv), all stages",
]
NPA_BANDS = [0, 1, 2, 3, 4, np.inf]  # years in Stage 3 = years as NPA, [from, to)


def segment_of(df: pd.DataFrame) -> pd.Series:
    """Segment for the old-rules vs ECL comparison: calamity-route loans (category (xiv)) first,
    then by stage; Stage 3 split by the rule that fired (default / arrears vs restructured) and,
    for restructured accounts, by whether the restructuring includes a modification."""
    mod = df.modification_events.fillna(0) > 0
    s3 = df.stage.eq(3)
    restr = df.stage_rule.eq("restructured")
    cal = df.category.eq("xiv")
    return pd.Series(
        np.select(
            [  # same order as SEGMENTS; calamity-route loans only in the last row
                ~cal & df.stage.eq(1),
                ~cal & df.stage.eq(2),
                ~cal & s3 & ~restr,
                ~cal & s3 & restr & mod,
                ~cal & s3 & restr & ~mod,
                cal,
            ],
            SEGMENTS,
            "other",
        ),
        index=df.index,
    )


def old_vs_ecl_by_segment(cur: pd.DataFrame) -> pd.DataFrame:
    """ECL allowance vs IRACP provision by segment and, for Stage 3, by years as NPA. The IRACP
    provision is split into the base rate (IRACP 80(1), 85, 86, 90, 91, 95) and the additional
    specific provisions (84A / 84B calamity 5%, RSA 64 15%), so each difference can be traced
    to the rule on each side (ACPIR 82(4)-(5), 90 vs IRACP)."""
    d = cur.assign(
        segment=segment_of(cur),
        npa_band=pd.cut(
            cur.npa_years.fillna(0),
            NPA_BANDS,
            right=False,
            labels=["0-1", "1-2", "2-3", "3-4", "4+"],
        )
        .astype(str)
        .where(cur.stage.eq(3), "performing"),
        secured_c=np.minimum(cur.secured, cur.ead_now),
    )
    g = (
        d.groupby(["segment", "npa_band"], sort=False)
        .agg(
            loans=("loan_id", "size"),
            outstanding=("ead_now", "sum"),
            secured_portion=("secured_c", "sum"),
            model_ecl=("ecl_stage_model", "sum"),
            ecl_allowance=("allowance", "sum"),
            iracp_base=("iracp_base", "sum"),
            iracp_additional=("iracp_additional", "sum"),
            iracp_provision=("iracp_provision", "sum"),
            blocked_rsa61=("stuck", "sum"),
        )
        .reset_index()
    )
    order = {s: i for i, s in enumerate(SEGMENTS)}
    g = g.sort_values(
        ["segment", "npa_band"], key=lambda s: s.map(order) if s.name == "segment" else s
    )
    tot = g.drop(columns=["segment", "npa_band"]).sum()
    g = pd.concat(
        [g, pd.DataFrame([{"segment": "Total", "npa_band": ""} | tot.to_dict()])],
        ignore_index=True,
    )
    g["ecl_minus_iracp"] = g.ecl_allowance - g.iracp_provision
    g["ecl_minus_iracp_base"] = g.ecl_allowance - g.iracp_base
    g["ecl_coverage"] = g.ecl_allowance / g.outstanding
    g["iracp_coverage"] = g.iracp_provision / g.outstanding
    return g


def overrides_table(cur: pd.DataFrame, rec: dict) -> pd.DataFrame:
    """Manual overrides applied in the run (Module 9 log; ACPIR Annex 3 3(3)-(4)): account,
    system stage, final stage, override id and reason; rejected ones listed too. 'none' if the
    run had none (runs before Module 9 have no override record)."""
    info = rec.get("overrides") or {}
    cols = ["override_id", "account", "stage_system", "stage", "status", "reason"]
    rows = []
    if "override_id" in cur:
        o = cur[cur.override_id.notna()]
        rows += [
            {
                "override_id": r.override_id,
                "account": r.loan_id,
                "stage_system": r.stage_system,
                "stage": r.stage,
                "status": "applied",
                "reason": r.override_reason,
            }
            for r in o.itertuples(index=False)
        ]
    rows += [
        {
            "override_id": r["override_id"],
            "account": r["account"],
            "status": f"rejected: {r['why']}",
        }
        for r in info.get("rejected", [])
    ]
    if not rows:
        head = info.get("log_head_hash", "no override record (run before Module 9)")
        rows = [{"override_id": "none", "status": f"log head {head}"}]
    return pd.DataFrame(rows).reindex(columns=cols)


def _header(date: str, meta: dict) -> list[str]:
    dry = " - DRY RUN first-application date" if meta.get("dry_run") else ""
    data = meta.get(
        "data_note",
        "Data: US (Freddie Mac Single-Family sample, FHFA, FRED, SPF, SEP) - NOT Indian risk "
        "estimates; amounts in US dollars (the Annex 4 formats use Rs crore)",
    )
    config = (
        f"Config: {meta['ecl_version']} (config/ecl.yaml), rbi_2026.yaml, "
        f"{meta['iracp_version']}; ECL run git {meta['run_git']} (clean {meta['run_clean']}); "
        f"report git {meta['report_git']}"
    )
    return [f"Reporting date: {date}{dry}", data, config]


def write_tables(out_dir: Path, date: str, tables: dict, meta: dict) -> Path:
    """One CSV per table (header lines as '#' comments) and one Markdown file per date."""
    out_dir.mkdir(parents=True, exist_ok=True)
    t = _tag(date)
    head = _header(date, meta)
    md = [f"# Annex 4 tables - {date}", "", *[f"- {h}" for h in head], ""]
    for name, (title, df) in tables.items():
        p = out_dir / f"annex4_{name}_{t}.csv"
        with p.open("w", encoding="utf-8", newline="") as fh:
            fh.write("".join(f"# {h}\n" for h in [title, *head]))
            df.to_csv(fh, index=False)
        md += [f"## {title}", "", _md(df), ""]
    p = out_dir / f"annex4_{t}.md"
    p.write_text("\n".join(md), encoding="utf-8")
    return p


def _md(df: pd.DataFrame) -> str:
    def fmt(v: object) -> str:
        if isinstance(v, float | np.floating):
            if np.isnan(v):
                return ""
            if v == 0:
                return "0"
            return f"{v:,.4f}" if abs(v) < 1 else f"{v:,.0f}"
        return str(v)

    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def build_reports(
    root: Path,
    cfg: dict,
    rbi: dict,
    iracp: dict,
    dates: dict,
    git: dict,
) -> dict:
    """dates: {reporting date: {"previous": date or None, "dry_run": bool}}."""
    out_dir = root / "reports/summary/annex4"
    processed = root / "data/processed"
    results = {}
    for date, spec in dates.items():
        cur, rec = load_run(root, date)
        cur = with_old_rules(cur, iracp)
        prev = None
        if spec.get("previous"):
            prev, _ = load_run(root, spec["previous"])
        meta = {
            "ecl_version": rec["version"],
            "iracp_version": iracp["version"],
            "run_git": rec["git"]["commit"][:7],
            "run_clean": rec["git"]["clean"],
            "report_git": git["commit"][:7],
            "dry_run": spec.get("dry_run", False),
        }
        t8, t8seg = table8(cur, cfg)
        sched, t9, summ = transition(cur, rbi)
        tables = {
            "t1": ("Table 1.A Credit quality of loan assets", table1(cur, prev)),
            "t2": ("Table 2 Summary of loan assets", table2(cur, prev)),
        }
        if prev is not None:
            info = exits(
                processed, prev.loan_id, f"{_tag(spec['previous'])}-01", f"{_tag(date)}-01"
            )
            info2 = exits(
                processed, cur.loan_id, f"{_tag(spec['previous'])}-01", f"{_tag(date)}-01"
            )
            info = pd.concat([info, info2]).drop_duplicates("loan_id")
            tables["t3"] = (
                f"Table 3.A Reconciliation of loss allowance ({spec['previous']} to {date})",
                reconciliation(prev, cur, info, f"{_tag(spec['previous'])}-01"),
            )
        tables |= {
            "t4": ("Table 4 Approach for ECL", table4(cur)),
            "t5": ("Table 5 Macroeconomic assumptions (Module 4)", table5(root, date)),
            "t6": ("Table 6 ECL adjustments", table6(cur, prev)),
            "t7": ("Table 7 ECL data (forward-looking PD and LGD)", table7(cur)),
            "t8": ("Table 8 SICR criteria", t8),
            "t8seg": ("Table 8 supplement: stage rule by segment", t8seg),
            "t9": ("Table 9 Reconciliation of opening reserves (transitional adjustments)", t9),
            "old_rules": (
                "Old-rules (IRACP 2025) provision by asset class and ECL stage",
                old_rules_table(cur),
            ),
            "overrides": (
                "Manual overrides (maker-checker log, Annex 3)",
                overrides_table(cur, rec),
            ),
            "old_vs_ecl": (
                "Old-rules provision vs ECL allowance by segment and years as NPA",
                old_vs_ecl_by_segment(cur),
            ),
            "transition": ("Transition: CET1 add-back schedule (ACPIR 108; pre-tax)", sched),
        }
        p = write_tables(out_dir, date, tables, meta)
        results[date] = {
            **summ,
            "markdown": str(p.relative_to(root)),
            "reconciliation_check": None
            if "t3" not in tables
            else float(
                tables["t3"][1].iloc[-1]["Total ECL"]
                - tables["t3"][1].iloc[-1]["check_closing_ecl_from_data"]
            ),
        }
        logger.info(
            f"{date}: ECL {summ['ecl_allowance'] / 1e6:,.1f}m, IRACP {summ['iracp_provision'] / 1e6:,.1f}m"
        )
    (out_dir / "annex4_summary.json").write_text(json.dumps(results, indent=2, default=float))
    return results
