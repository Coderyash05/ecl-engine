"""Scenario entry points (Module 4): crisis replay + CO-3, scenario PDs, early performance.

- `crisis_replay(cfg, inp, root)`: R1-R3 on the 2005-07 holdout vintages, CO-3 calibration
  (replay.py, overlay.py). Writes reports/summary/crisis_replay.csv and
  models/scenarios/co3_calibration.json. The approved values go to config/overlays.yaml.
- `scenario_pd_for_date(date, ...)`: scenario-weighted 12-month and lifetime PD for a reporting
  date (scenario_pd.py); the 2023-03 backtest when outcomes exist.
- `early_performance_check(cfg, inp, root)`: the 2024-26 vintages vs history (candidate overlay CO-4).

US data; not Indian risk estimates.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

from ecl.lifetime.cells import SAND_STATES
from ecl.lifetime.cycle import vasicek_pd
from ecl.lifetime.hazard import HazardModel
from ecl.lifetime.hazard_data import create_life_table, create_origination_table
from ecl.lifetime.macro import load_macro
from ecl.lifetime.paths import Q0, MacroPath, realised_path
from ecl.lifetime.portfolio import components, origination_loans, read_state_hpi
from ecl.pd.dataset import build_scoring_snapshot, holdout_flags
from ecl.pd.origination import origination_frame
from ecl.pd.scorecard import WoEScorecard
from ecl.scenarios import early_performance as ep
from ecl.scenarios.build import to_macro_path
from ecl.scenarios.replay import (
    beta_state_path,
    calibrate,
    replay_table,
    run_path,
    satellite_path,
)
from ecl.scenarios.run import build_scenarios
from ecl.scenarios.scenario_pd import SCEN, backtest_table, scenario_pds, segment_table, segments
from ecl.scenarios.state_paths import fit_betas, state_wide

logger = logging.getLogger(__name__)


@dataclass
class Inputs:
    """Inputs shared by the scenario-PD, LGD and ECL runs: macro history, the point-in-time model
    metadata, measured Z, state HPI and betas, the realised macro path, the lifetime hazard
    model, the TTC scorecard and the RBI and lifetime-model configs."""

    macro: pd.DataFrame
    pit: dict
    z_meas: pd.Series
    hpi_state: pd.DataFrame
    log_state: pd.DataFrame
    betas: pd.Series
    realised: MacroPath
    model: HazardModel
    sc: WoEScorecard
    rbi: dict
    life_meta: dict


def load_inputs(cfg: dict, root: Path) -> Inputs:
    """Macro data, Module 2-3 models and the realised path (as Module 3 builds it)."""
    macro, _ = load_macro(root / "data/macro")
    pit = json.loads((root / "models/pd_pit/metadata.json").read_text(encoding="utf-8"))
    zq = pd.read_csv(root / cfg["scenario_pd"]["z_measured"])
    z_meas = pd.Series(zq.z_measured.values, index=pd.PeriodIndex(zq.quarter, freq="Q"))
    hpi_state = read_state_hpi(root / cfg["state_paths"]["file"])
    ls = state_wide(hpi_state)
    betas = fit_betas(ls, np.log(macro.hpi), *cfg["state_paths"]["beta_window"]).beta
    realised = realised_path(macro, z_meas, hpi_state)
    for a in ["z_q", "hpi_yoy", "mortgage30"]:
        setattr(realised, a, pd.Series(getattr(realised, a)).ffill().bfill().values)
    sp = cfg["scenario_pd"]
    return Inputs(
        macro,
        pit,
        z_meas,
        hpi_state,
        ls,
        betas,
        realised,
        HazardModel.load(root / sp["lifetime_model"]),
        WoEScorecard.load(root / sp["scorecard"]),
        yaml.safe_load((root / "config/rbi_2026.yaml").read_text(encoding="utf-8")),
        json.loads((root / "models/pd_lifetime/metadata.json").read_text(encoding="utf-8")),
    )


# ------------------------------------------------------------------ crisis replay and CO-3


def crisis_replay(cfg: dict, inp: Inputs, root: Path) -> dict:
    """Crisis replay of the 2005-07 holdout vintages through 2007-09 (R1 realised macro, R2
    satellite Z, R3 state paths from national growth) and the calibration of the downside
    default multiplier CO-3 (config/overlays.yaml). Writes the replay table; returns the
    results."""
    rc = cfg["replay"]
    processed = root / "data/processed"
    con = duckdb.connect()
    create_life_table(con, processed)
    create_origination_table(con, processed)
    orig, loans = origination_loans(con, origination_frame(processed), inp.sc, inp.realised)
    con.close()
    hold = np.array(holdout_flags(orig.loan_id.tolist()))
    vint = [rc["vintage_holdout"], *rc["vintages_calibration"]]
    ii = np.where(hold & orig.vintage.isin(vint).values)[0]
    orig, loans = orig.iloc[ii].reset_index(drop=True), loans.take(ii)
    logger.info(f"Replay loans (holdout, vintages {vint}): {len(orig):,}")

    z_lr = inp.pit["long_run_z"]
    params = inp.pit["satellite"]["params"]
    r2 = satellite_path(inp.realised, inp.macro, params)
    r3 = beta_state_path(r2, inp.log_state, inp.macro, inp.betas, rc["state_cut"])
    k = 4 * max(rc["years"])
    fq = orig.first_q.values
    runs = {
        name: run_path(inp.model, loans, fq, p, k, z_lr)
        for name, p in [("R1", inp.realised), ("R2", r2), ("R3", r3)]
    }
    sand = orig.property_state.isin(SAND_STATES).values
    v = orig.vintage.values
    cal = np.isin(v, rc["vintages_calibration"])
    groups = {}
    for name, m in [("all", np.ones(len(v), bool)), ("CA/FL/NV/AZ", sand), ("other", ~sand)]:
        for vv in vint:
            groups[f"{vv} {name}"] = np.where(m & (v == vv))[0]
        groups[f"2006-07 {name}"] = np.where(m & cal)[0]

    g = rc["m_grid"]
    grid = np.exp(np.linspace(np.log(g[0]), np.log(g[1]), int(g[2])))
    b = rc["bootstrap"]
    kc = 4 * rc["calibration_years"]
    cal_all = calibrate(runs["R3"], orig, np.where(cal)[0], kc, grid, b["n"], b["seed"], b["level"])
    cal_sand = calibrate(
        runs["R3"], orig, np.where(cal & sand)[0], kc, grid, b["n"], b["seed"], b["level"]
    )
    cal_other = calibrate(
        runs["R3"], orig, np.where(cal & ~sand)[0], kc, grid, b["n"], b["seed"], b["level"]
    )
    pooled = replay_table(runs, orig, groups, rc["years"], cal_all["m"])
    lo, hi = rc["tolerance_before"]
    reg5 = pooled[
        (pooled.group.isin(["2006-07 CA/FL/NV/AZ", "2006-07 other"]))
        & (pooled.years == rc["calibration_years"])
    ]
    outside = bool((~reg5.actual_to_R3_CO3.between(lo, hi)).any())
    disjoint = cal_sand["lo"] > cal_other["hi"] or cal_other["lo"] > cal_sand["hi"]
    split = outside or disjoint
    m_loan = np.where(sand, cal_sand["m"], cal_other["m"]) if split else cal_all["m"]
    table = replay_table(runs, orig, groups, rc["years"], m_loan) if split else pooled

    def check(row: pd.Series) -> bool | None:
        """Acceptance of the replay: 2006 and 2007 at 5 years within the calibrated tolerance; 2005 (held
        out) at 3 and 5 years within the holdout tolerance; regions only if split."""
        first, region = row.group.split(" ", 1)
        if not first.isdigit() or (region != "all" and not split):
            return None
        tol = (
            rc["tolerance_holdout"]
            if int(first) == rc["vintage_holdout"]
            else rc["tolerance_calibrated"]
            if row.years == rc["calibration_years"]
            else None
        )
        return None if tol is None else bool(tol[0] <= row.actual_to_R3_CO3 <= tol[1])

    table["acceptance"] = [check(r) for r in table.itertuples()]
    # sensitivity: calibration on all three vintages (2005 no longer held out)
    allv = np.isin(v, vint)
    alt = {
        reg: calibrate(
            runs["R3"], orig, np.where(allv & msk)[0], kc, grid, b["n"], b["seed"], b["level"]
        )
        for reg, msk in [("sand", sand), ("other", ~sand)]
    }
    alt_t = replay_table(
        {"R3": runs["R3"]},
        orig,
        groups,
        rc["years"],
        np.where(sand, alt["sand"]["m"], alt["other"]["m"]),
    )
    table["actual_to_R3_CO3_cal2005_07"] = alt_t.actual_to_R3_CO3.values
    table.to_csv(root / cfg["outputs"]["dir"] / "crisis_replay.csv", index=False)

    w0, w1 = (pd.Period(x, freq="Q") for x in rc["z_trough_window"])
    qs = np.arange(w0.year * 4 + w0.quarter - 1, w1.year * 4 + w1.quarter)
    z_min_replay = float(r3.at(r3.z_q, qs).min())
    z_min_measured = float(inp.realised.at(inp.realised.z_q, qs).min())
    res = {
        "loans": len(orig),
        "by_vintage": orig.vintage.value_counts().sort_index().to_dict(),
        "z_long_run": z_lr,
        "z_min_replay_R3": z_min_replay,
        "z_min_replay_measured_R1": z_min_measured,
        "stressed_quarters_rule": "z_q < long-run Z",
        "calibration": {"pooled": cal_all, "sand": cal_sand, "other": cal_other},
        "split_sand_other": split,
        "split_reason": {
            "pooled_m_region_outside_tolerance": outside,
            "intervals_disjoint": bool(disjoint),
        },
        "sensitivity_calibration_2005_07": alt,
        "m_applied": {"CA/FL/NV/AZ": cal_sand["m"], "other": cal_other["m"]}
        if split
        else {"all": cal_all["m"]},
        "acceptance_all_pass": bool(table.acceptance.dropna().all()),
        "holdout_2005_pass": bool(
            table[table.group.str.startswith(str(rc["vintage_holdout"]))].acceptance.dropna().all()
        ),
    }
    (root / "models/scenarios/co3_calibration.json").write_text(
        json.dumps(res, indent=2, default=float), encoding="utf-8"
    )
    return {"table": table, **res}


# ------------------------------------------------------------------ scenario PDs


def scenario_pd_for_date(
    date: str, cfg: dict, co3_cfg: dict, inp: Inputs, root: Path, git: dict
) -> dict:
    """Scenario paths, per-loan 12-month and lifetime PDs per scenario and probability-weighted
    (paras 45-49), segment tables and, for a past date, the backtest against realised
    defaults. Returns the run summary."""
    rq = pd.Period(pd.Timestamp(date), freq="Q")
    tag = pd.Timestamp(date).strftime("%Y-%m")
    run, frames = build_scenarios(date, cfg, inp.macro, inp.pit, git, root)
    weights = {k: run["scenarios"][k]["weight"] for k in SCEN}
    params = inp.pit["satellite"]["params"]
    paths = {
        name: to_macro_path(name, frames[name], params, inp.z_meas, rq, inp.log_state, inp.betas)
        for name in ["base", *SCEN]
    }
    snap_month = f"{rq.year}-{rq.end_time.month:02d}-01"
    pf = build_scoring_snapshot(
        root / "data/processed", snap_month, root / cfg["state_paths"]["file"]
    )
    pcomp = components(inp.sc, pf)
    sand = pf.property_state.isin(SAND_STATES).values
    m = co3_cfg["calibration"]["m"]
    m_loan = np.where(sand, m["CA/FL/NV/AZ"], m["other"]) if "other" in m else m["all"]
    pdcfg = {
        "rho": inp.pit["rho"],
        "floor12": float(inp.rbi["pd"]["floor_12_month"]["value"]),
        "floor_annual": float(inp.rbi["pd"]["floor_lifetime_annual"]["value"]),
        "tau": float(inp.life_meta["carry_tau"]),
        "z_lr": float(inp.pit["long_run_z"]),
        "horizon": cfg["horizon_quarters"],
    }
    co3 = {"m": m_loan, "z_min_replay": co3_cfg["calibration"]["z_min_replay"]}
    df, info = scenario_pds(inp.model, pf, pcomp, paths, weights, rq, pdcfg, co3)
    sp = cfg["scenario_pd"]
    seg = segments(pf, pcomp, sp["ltv_bands"], sp["ltv_labels"])
    out_dir = root / sp["per_loan_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.concat([df, seg, pf[["vintage", "property_state"]]], axis=1).to_parquet(
        out_dir / f"report_date={tag}.parquet", index=False
    )
    cols = [c for c in df.columns if c != "loan_id"]
    st = segment_table(df, seg, cols)
    st.insert(0, "as_on", date)
    st.to_csv(root / cfg["outputs"]["dir"] / f"scenario_pd_{tag}.csv", index=False)
    result = {
        "date": date,
        "loans": len(pf),
        "weights": weights,
        "co3": info,
        "all": st[st.segment == "all"].iloc[0].to_dict(),
    }
    if (inp.z_meas.index == rq).any():  # outcomes observed: backtest (evaluation only)
        lab = (
            duckdb.connect()
            .execute(f"""
            SELECT loan_id, target_b18::INT AS target_b18, target_a::INT AS target_a
            FROM read_parquet('{(root / "data/processed/pd_dataset").as_posix()}/*/*.parquet',
                              hive_partitioning = true)
            WHERE obs_date = DATE '{snap_month}' ORDER BY loan_id""")
            .df()
        )
        ttc = 1 / (1 + np.exp(-pcomp["logit"]))
        df["pd12_realised_z"] = np.maximum(
            vasicek_pd(ttc, float(inp.z_meas[rq]), pdcfg["rho"]), pdcfg["floor12"]
        )
        df["pd12_ttc"] = ttc
        pcols = [
            "pd12_ttc",
            "pd12_base",
            "pd12_downside_co3",
            "pd12_central",
            "pd12_upside",
            "pd12_weighted",
            "pd12_realised_z",
        ]
        bt = backtest_table(df, seg, lab, pcols)
        bt.to_csv(root / cfg["outputs"]["dir"] / f"scenarios_backtest_{tag}.csv", index=False)
        result["backtest_all"] = bt[bt.segment == "all"].iloc[0].to_dict()
        result["realised_macro"] = run.get("evaluation_only_realised_after_as_at")
        result["z_measured_rq"] = float(inp.z_meas[rq])
    (root / "models/scenarios" / f"scenario_pd_{tag}.json").write_text(
        json.dumps(result, indent=2, default=float), encoding="utf-8"
    )
    return result


# ------------------------------------------------------------------ early performance


def early_performance_check(cfg: dict, inp: Inputs, root: Path) -> dict:
    """Early performance of the 2024-26 vintages against the age profile of benchmark vintages,
    PIT-adjusted; flags the CO-4 monitoring trigger (config/overlays.yaml)."""
    e = cfg["early_performance"]
    con = duckdb.connect()
    for kind in ["loans", "panel"]:
        glob = (root / "data/processed" / kind).as_posix() + "/*/*.parquet"
        con.execute(
            f"CREATE VIEW {kind}_all AS SELECT * FROM read_parquet('{glob}', "
            "hive_partitioning=true)"
        )
    as_at = str(e["as_at"])
    target = ep.cell_counts(con, tuple(e["vintages"]), as_at, e["max_age_months"])
    r2 = satellite_path(inp.realised, inp.macro, inp.pit["satellite"]["params"])
    z_q = pd.Series(r2.z_q, index=Q0 + np.arange(len(r2.z_q)))
    out, summary = {}, {}
    for name, bv in [
        ("primary", e["benchmark_vintages"]),
        ("sensitivity", e["benchmark_sensitivity"]),
    ]:
        bench = ep.cell_counts(con, tuple(bv), as_at, e["max_age_months"])
        cells = ep.expected_counts(bench, target, z_q, inp.pit["rho"])
        detail, bands = ep.summarise(
            cells, e["age_band_months"], e["trigger_ratio"], e["min_events"]
        )
        detail.insert(0, "benchmark", f"{name} {bv[0]}-{bv[1]}")
        bands.insert(0, "benchmark", f"{name} {bv[0]}-{bv[1]}")
        out[name] = (detail, bands)
        by_v = bands.groupby(["vintage", "rate"])[["n", "actual", "expected"]].sum()
        by_v["actual_to_expected"] = by_v.actual / by_v.expected
        summary[name] = {
            "triggers": int(bands.trigger.sum()),
            "by_vintage": {
                f"{a} {b}": float(r.actual_to_expected) for (a, b), r in by_v.iterrows()
            },
        }
    mix = ep.mix(
        con,
        {
            "2024-26": tuple(e["vintages"]),
            "benchmark 2000-16": tuple(e["benchmark_vintages"]),
            "benchmark 2012-16": tuple(e["benchmark_sensitivity"]),
        },
    )
    con.close()
    rep = root / cfg["outputs"]["dir"]
    pd.concat([o[1] for o in out.values()]).to_csv(
        rep / "early_performance_2024_26.csv", index=False
    )
    pd.concat([o[0] for o in out.values()]).to_csv(
        rep / "early_performance_2024_26_by_age.csv", index=False
    )
    mix.to_csv(rep / "early_performance_2024_26_mix.csv", index=False)
    res = {
        "as_at": as_at,
        "summary": summary,
        "co4_triggered": summary["primary"]["triggers"] > 0,
        "mix": mix.to_dict(orient="records"),
    }
    (root / "models/scenarios/early_performance.json").write_text(
        json.dumps(res, indent=2, default=float), encoding="utf-8"
    )
    return res
