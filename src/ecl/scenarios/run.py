"""Module 4 entry point: build the macro scenarios for one reporting date and write the outputs.

`build_scenarios(date, cfg, macro, pit, git, root)` (all parameters from config/scenarios.yaml):
1. Data as at the date (no look-ahead): macro history cut at the reporting quarter; the SPF
   survey released by the date; the SEP released by the date, medians confirmed against the PDF
   text; GS10 months to the date.
2. Base: SPF GDP / unemployment / 10-year Treasury (+ spread = mortgage rate) and HPI from the
   VAR conditional on them (base.py).
3. Simulated VAR paths around the base, ranked by severity (satellite Z at mean growth);
   scenarios = region means, weights = region shares (unbiased, para 47).
4. Reversion to the long-run values; state HPI by betas (paras 49, 124).
5. Severity checks (severity.py) and outputs in reports/summary/ (aggregates of public macro
   data): scenarios_table5_{d}.csv/.md (Annex 4 Table 5), scenarios_base_{d}.csv,
   scenarios_paths_{d}.csv, scenarios_state_hpi_{d}.csv, scenarios_severity_{d}.csv,
   scenarios_run_{d}.json.

US data (FRED, FHFA, SPF, SEP): never Indian risk estimates.
"""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from ecl.lifetime.paths import satellite_z
from ecl.scenarios.base import (
    base_forecast,
    ff_spread,
    mortgage_path,
    sep_q4q4,
    spf_paths,
    treasury_spread,
)
from ecl.scenarios.build import extend, one_year_forward, partition, severity, yoy_paths
from ecl.scenarios.severity import (
    distance_check,
    historical_one_year,
    level_reference,
    plausibility,
    spf_gdp_errors,
    var_errors,
    z_index_check,
)
from ecl.scenarios.sources import (
    check_sep_pdf,
    read_gs10,
    read_spf,
    spf_release_bound,
    spf_row,
    spf_survey_as_at,
)
from ecl.scenarios.state_paths import fit_betas, project_states, state_wide
from ecl.scenarios.table5 import table5
from ecl.scenarios.var import ANNUALISE, fit_var, simulate_deviations, var_data

SCEN = ["downside", "central", "upside"]


def _md_table(df: pd.DataFrame, fmt: str = "{:.2f}") -> str:
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    for r in df.itertuples(index=False):
        cells = (fmt.format(v) if isinstance(v, float) else str(v) for v in r)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _sources(date: str, cfg: dict, root: Path) -> dict:
    """SPF rows, SEP medians (checked against the PDF) and GS10, all as at `date`."""
    as_at = pd.Timestamp(date)
    rq = pd.Period(as_at, freq="Q")
    dcfg = cfg["base"]["dates"][date]
    files = {k: root / v for k, v in cfg["base"]["files"].items()}
    drgdp = read_spf(files["spf_growth"], "RGDP")
    levels = {s: read_spf(files["spf_level"], s) for s in ["RGDP", "UNEMP", "TBOND"]}
    survey = spf_survey_as_at(drgdp, as_at)
    if str(survey) != dcfg["spf_survey"]:
        raise ValueError(f"latest SPF as at {date} is {survey}; config: {dcfg['spf_survey']}")
    rows = {"drgdp": spf_row(drgdp, survey, as_at)}
    rows |= {s: spf_row(d, survey, as_at) for s, d in levels.items()}
    sep = dcfg["sep"]
    if pd.Timestamp(sep["release_date"]) > as_at:
        raise ValueError(f"SEP released {sep['release_date']}, after {date}")
    missing = check_sep_pdf(root / sep["file"], {k: sep[k] for k in ["gdp", "unrate", "fedfunds"]})
    if missing:
        raise ValueError(f"SEP medians not found in the PDF: {missing}")
    gs10 = read_gs10(files["gs10"], as_at)
    if gs10.index.max() != rq:
        raise ValueError(f"GS10 last full quarter {gs10.index.max()} != {rq}")
    return {"drgdp": drgdp, "survey": survey, "rows": rows, "sep": sep, "gs10": gs10}


def build_scenarios(
    date: str,
    cfg: dict,
    macro: pd.DataFrame,
    pit: dict,
    git: dict,
    root: Path,
    write: bool = True,
) -> dict:
    """Build and write the scenarios for reporting date `date` (YYYY-MM-DD); returns the run
    record (also written as scenarios_run_{YYYY-MM}.json) and the scenario frames (base,
    downside, central, upside: build.extend output plus z_satellite). With write=False the
    files go to a temporary directory (later modules regenerate the frames without touching
    the Module 4 outputs; the build is deterministic)."""
    rq = pd.Period(pd.Timestamp(date), freq="Q")
    tag = pd.Timestamp(date).strftime("%Y-%m")
    out = root / cfg["outputs"]["dir"] if write else Path(tempfile.mkdtemp())
    h, rv = cfg["horizon_quarters"], cfg["reversion_quarters"]
    m = macro.loc[:rq]  # no history after the reporting quarter
    src = _sources(date, cfg, root)
    sep, gs10 = src["sep"], src["gs10"]

    # --- base -------------------------------------------------------------------------------
    d = var_data(m)
    vc = cfg["var"]
    var = fit_var(d, vc["window"][0], vc["window"][1], p=vc["lags"])
    actual = {
        "unrate": float(m.unrate[rq]),
        "gs10": float(gs10[rq]),
        "mortgage30": float(m.mortgage30[rq]),
    }
    spf = spf_paths(src["rows"], src["survey"], rq, actual, h)
    spread0 = actual["mortgage30"] - actual["gs10"]
    spread_t = treasury_spread(m, gs10, *cfg["base"]["treasury_spread_window"])
    spf["mortgage30"] = mortgage_path(spf.tbond, spread0, spread_t)
    hist = d.loc[:rq, var.names].values[-var.p :]
    fc_base = base_forecast(var, hist, spf, spf.mortgage30, actual["unrate"], actual["mortgage30"])
    spf["hpi_g_var_conditional"] = fc_base[:, 0]

    lrc = cfg["long_run"]
    ffs = ff_spread(m, *lrc["ff_spread_window"], zlb_below=lrc["ff_spread_exclude_zlb_below"])
    ffs_all = ff_spread(m, *lrc["ff_spread_window"], zlb_below=None)
    lrm = pit["long_run_driver_means_2000_2016"]
    lr = {
        "hpi_yoy": lrm["hpi_yoy"],
        "gdp_yoy": lrm["gdp_yoy"],
        "mortgage30": sep["fedfunds"][-1] + ffs["spread"],
        "unrate": sep["unrate"][-1],
    }

    # --- simulation and partition ------------------------------------------------------------
    sim = vc["simulation"]
    rng = np.random.default_rng(sim["seed"])
    dev = simulate_deviations(var, h, sim["n_sims"], rng, block=sim["block_quarters"])
    sims = fc_base[None] + dev
    params = pit["satellite"]["params"]
    last3_h, last3_g = d.hpi_g.loc[:rq].values[-3:], d.gdp_g.loc[:rq].values[-3:]

    def sev_of(paths: np.ndarray) -> np.ndarray:
        return severity(
            params,
            yoy_paths(last3_h, paths[:, :, 0], "hpi"),
            yoy_paths(last3_g, paths[:, :, 1], "gdp"),
        )

    sev = sev_of(sims)
    shares = tuple(cfg["partition"]["shares"][k] for k in SCEN)
    reg = partition(sims, sev, shares)
    frames = {"base": extend(m, fc_base, lr, rq, rv)}
    frames |= {k: extend(m, reg[k]["path"], lr, rq, rv) for k in SCEN}
    for f in frames.values():
        f["z_satellite"] = satellite_z(params, f.hpi_yoy, f.gdp_yoy)
    weights = {k: reg[k]["weight"] for k in SCEN}

    # --- Table 5, base, paths ---------------------------------------------------------------
    t5 = table5(frames, weights, rq)
    t5.to_csv(out / f"scenarios_table5_{tag}.csv", index=False)
    stamp = (
        f"Run {datetime.now(UTC).isoformat(timespec='seconds')}; git {git['commit'][:7]}"
        f"{'' if git['clean'] else ' (dirty)'}; config {cfg['version']}; SPF {src['survey']}; "
        f"SEP {sep['release_date']}; macro history to {rq}."
    )
    (out / f"scenarios_table5_{tag}.md").write_text(
        f"# Annex 4 Table 5: macroeconomic assumptions, as on {date}\n\n"
        "US data (FRED, FHFA, SPF, SEP); a parallel-run illustration, **not Indian risk "
        "estimates**.\n\n" + _md_table(t5) + f"\n\n{stamp}\n",
        encoding="utf-8",
    )
    spf.index = spf.index.astype(str)
    spf.to_csv(out / f"scenarios_base_{tag}.csv", index_label="quarter")

    w0, w1 = cfg["outputs"]["paths_window_quarters"]
    lo, hi = rq + w0, rq + w1
    cols = ["hpi_g", "hpi_yoy", "gdp_g", "gdp_yoy", "mortgage30", "unrate", "z_satellite"]
    pth = []
    for k, f in frames.items():
        x = f.loc[lo:hi, cols].copy()
        x["hpi_index"] = np.exp(f.log_hpi.loc[lo:hi])
        x.insert(0, "scenario", k)
        x.insert(1, "forecast", x.index > rq)
        pth.append(x)
    paths = pd.concat(pth)
    paths.index = paths.index.astype(str)
    paths.to_csv(out / f"scenarios_paths_{tag}.csv", index_label="quarter")

    hs = pd.read_csv(
        root / cfg["state_paths"]["file"], header=None, names=["state", "yr", "qtr", "hpi"]
    )
    ls = state_wide(hs)
    betas = fit_betas(ls, np.log(macro.hpi), *cfg["state_paths"]["beta_window"])
    st = []
    for k, f in frames.items():
        p = project_states(ls, f.log_hpi.loc[:hi], betas.beta, rq).loc[rq:hi]
        p = (100 * np.exp(p - p.loc[rq])).stack().reset_index()
        p.columns = ["quarter", "state", "index_rq100"]
        p.insert(0, "scenario", k)
        st.append(p)
    st = pd.concat(st)
    st["quarter"] = st.quarter.astype(str)
    st.to_csv(out / f"scenarios_state_hpi_{tag}.csv", index=False, float_format="%.3f")

    # --- severity checks -----------------------------------------------------------------------
    sc = cfg["severity_check"]
    bands = {"downside": sc["band_downside"], "upside": sc["band_upside"]}
    excl = pd.period_range(*sc["exclude_windows_touching"], freq="Q")
    fwd = {k: one_year_forward(frames[k], rq) for k in SCEN}
    base1 = one_year_forward(frames["base"], rq)
    ve = var_errors(var, d, sc["reference_start_primary"], rq, excl)
    refs = {
        "gdp:spf": spf_gdp_errors(src["drgdp"], m, sc["reference_start_primary"], rq, excl),
        "hpi:var": ve.hpi,
        "gdp:var": ve.gdp,
    }
    dist = pd.concat(
        [distance_check(fwd, base1, refs, bands), z_index_check(fwd, base1, ve, params, bands)],
        ignore_index=True,
    )
    dist.insert(0, "check", "primary: distance from base")
    lvl_ref = level_reference(m, sc["reference_start_secondary"], rq, excl)
    lvl = plausibility(fwd, lvl_ref, bands)
    lvl.insert(0, "check", "secondary: level vs history")
    lvl["reference"] = f"history {sc['reference_start_secondary']}-{rq - 4}"
    sev_tab = pd.concat([dist, lvl], ignore_index=True)
    sev_tab.to_csv(out / f"scenarios_severity_{tag}.csv", index=False)

    # --- cross-checks and run record -------------------------------------------------------------
    xs = sep_q4q4(frames["base"], [int(y) for y in sep["years"][:-1]])
    xs["sep_gdp"] = sep["gdp"][:-1]
    xs["sep_unrate"] = sep["unrate"][:-1]
    fq = slice(rq + 1, rq + h)

    def summary(k: str) -> dict:
        f = frames[k]
        s = {
            "one_year_forward": one_year_forward(f, rq),
            "hpi_cum_forecast": float(100 * (np.exp(f.log_hpi[rq + h] - f.log_hpi[rq]) - 1)),
            "z_min_forecast": float(f.z_satellite.loc[fq].min()),
        }
        if k in reg:
            s |= {
                "weight": reg[k]["weight"],
                "n": reg[k]["n"],
                "severity_zbar": reg[k]["severity"],
                "severity_percentile_in_sims": float(100 * (sev <= reg[k]["severity"]).mean()),
            }
        else:
            s["severity_zbar"] = float(sev_of(fc_base[None])[0])
        return s

    run = {
        "version": cfg["version"],
        "as_at": date,
        "reporting_quarter": str(rq),
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git,
        "sources": {
            "spf_survey": str(src["survey"]),
            "spf_release_bound": str(spf_release_bound(src["survey"]).date()),
            "sep_release": str(sep["release_date"]),
            "sep_pdf_confirmed": True,
            "gs10_last_quarter": str(gs10.index.max()),
            "macro_history_to": str(rq),
        },
        "var": {"obs": len(var.index), "max_abs_eigenvalue": var.max_abs_eigenvalue()},
        "actual_at_reporting_quarter": actual,
        "spreads": {
            "mortgage_treasury_at_rq": spread0,
            "mortgage_treasury_window_mean": spread_t,
            "mortgage_fedfunds_ex_zlb": ffs,
            "mortgage_fedfunds_all": ffs_all,
        },
        "long_run": lr,
        "long_run_z": pit["long_run_z"],
        "scenarios": {k: summary(k) for k in ["base", *SCEN]},
        "sep_crosscheck": xs.to_dict(orient="records"),
        "reference_sizes": {k: len(v) for k, v in refs.items()} | {"levels": len(lvl_ref)},
    }
    if rq + h <= macro.index.max():  # backtest evaluation only: uses data after the date
        full = var_data(macro).loc[rq + 1 : rq + h, ["hpi_g", "gdp_g"]].values
        z_real = float(sev_of(np.dstack([full[None, :, 0], full[None, :, 1]]))[0])
        run["evaluation_only_realised_after_as_at"] = {
            "one_year_forward": historical_one_year(macro, str(rq), str(rq)).iloc[0].to_dict(),
            "hpi_cum_forecast_window": float(100 * (np.exp(full[:, 0].sum() / ANNUALISE) - 1)),
            "severity_zbar": z_real,
            "severity_percentile_in_sims": float(100 * (sev <= z_real).mean()),
        }
    (out / f"scenarios_run_{tag}.json").write_text(
        json.dumps(run, indent=2, default=str), encoding="utf-8"
    )
    return run, frames
