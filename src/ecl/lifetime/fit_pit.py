"""Point-in-time PD (Module 3): credit-cycle index Z_t, macro satellite and PIT backtest.

Run: ecl train pd-pit [--rebuild-cells]

1. Quarterly US macro drivers from the FRED files in data/macro/ (macro.py).
2. Every PD snapshot 2000-2023 scored with the TTC model pd12m-1.2.1 and aggregated to cells
   (cells.py; cached in data/processed/pd_cycle_cells/, loan-level derived, not in git).
3. Asset correlation: rho = 0.15, the Basel residential-mortgage benchmark (decided: not
   identifiable from this data, chosen by the backtest by delinquency group); the profile
   likelihood is reported, 0.10 and 0.20 are sensitivities.
4. Z_t per quarter; final satellite: window-aligned (macro averaged over t+1..t+4), house
   prices + GDP. The amended driver rule (sign, |HAC t| >= 2, >= 5% lower OOT error) is
   reported for every candidate driver; the Fed funds specification is a sensitivity.
5. Backtest: by quarter, period, delinquency group, sand states; 90% band; COVID under B-18 and
   target A; with and without the 0.03% 12-month PD floor (para 96).

Outputs: aggregates in reports/summary/pd_pit_* and models/pd_pit/ (tracked). All estimates
are on US data and are not Indian risk estimates.
"""

from __future__ import annotations

import json
import logging
import warnings
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import statsmodels.api as sm
import yaml
from statsmodels.tools.sm_exceptions import InterpolationWarning
from statsmodels.tsa.stattools import adfuller, kpss

from ecl.common import CODE_AND_REGULATORY_CONFIG, git_state, md_table, project_root
from ecl.lifetime.cells import build_cells
from ecl.lifetime.cycle import (
    predicted_by_group,
    profile_rho,
    rho_unit_variance,
    vasicek_pd,
    z_series,
)
from ecl.lifetime.macro import DRIVERS, load_macro
from ecl.lifetime.satellite import SatelliteFit, fit_lagged, fit_terms, fit_window
from ecl.pd.scorecard import WoEScorecard

ROOT = project_root()

VERSION = "pdpit-0.2.1"
PREVIOUS = "pdpit-0.2.0"
TTC_MODEL = "pd12m-1.2.1"
PROCESSED = ROOT / "data" / "processed"
CELLS = PROCESSED / "pd_cycle_cells"
MODEL_DIR = ROOT / "models" / "pd_pit"
REPORTS = ROOT / "reports" / "summary"
YEARS = range(2000, 2024)

# Decided by the model owner (2026-11-13; models/pd_pit/CHANGELOG.md); not RBI values
RHO = 0.15  # Basel residential-mortgage benchmark; not identifiable here
RHO_SENSITIVITIES = [0.10, 0.20]
FINAL_DRIVERS = ["hpi_yoy", "gdp_yoy"]  # window-aligned (W)
# Developer choices (docs/methodology/pd_point_in_time.md)
RHO_GRID = np.round(np.arange(0.01, 0.401, 0.01), 2)
GROUP_TOLERANCE = (0.8, 1.25)  # actual / predicted per delinquency group, OOT1 + OOT3
BAND_Z = 1.645  # 90% band
# Driver rule (model owner, amended 2026-11-13; models/pd_pit/CHANGELOG.md): every driver needs the
# expected sign and |HAC t| >= 2 in sample. Core drivers, named ex ante in the design (HPI, GDP),
# must not worsen the out-of-sample error by more than 5% (error with <= 1.05 x error without);
# optional additions (Fed funds) must improve it by >= 5%.
DRIVER_MIN_T = 2.0
DRIVER_MIN_GAIN = 0.05
CORE_DRIVERS = ["hpi_yoy", "gdp_yoy"]
CANDIDATE_DRIVERS = ["hpi_yoy", "gdp_yoy", "ff_chg4"]
CHALLENGER_DRIVERS = ["hpi_yoy", "unrate_chg4"]

PERIODS = [
    ("pre-crisis", 2000, 2006),
    ("crisis", 2007, 2011),
    ("recovery", 2012, 2016),
    ("benign (OOT1)", 2017, 2019),
    ("COVID (OOT2)", 2020, 2021),
    ("2022-23 (OOT3)", 2022, 2023),
]
logger = logging.getLogger(__name__)


def split_of(q: pd.Period) -> str:
    """Time split of a quarter: dev (to 2016), oot1 (2017-19), oot2 (2020-21), oot3 (2022 on)."""
    return (
        "dev"
        if q.year <= 2016
        else "oot1"
        if q.year <= 2019
        else "oot2"
        if q.year <= 2021
        else "oot3"
    )


def period_of(q: pd.Period) -> str:
    """Validation period label of a quarter."""
    return next(name for name, a, b in PERIODS if a <= q.year <= b)


def load_cells(rebuild: bool) -> pd.DataFrame:
    """Scored snapshot cells: rebuilt from the PD dataset if asked, if the cache is missing or if
    it was built with another TTC model; else read from the cache."""
    path, meta = CELLS / "cells.parquet", CELLS / "meta.json"
    if rebuild or not path.exists() or json.loads(meta.read_text())["model"] != TTC_MODEL:
        logger.info("Scoring all snapshots with the TTC model (cells)")
        model = WoEScorecard.load(ROOT / "models" / "pd_12m" / "scorecard.pkl")
        cells = build_cells(PROCESSED / "pd_dataset", model, YEARS)
        CELLS.mkdir(parents=True, exist_ok=True)
        cells.to_parquet(path, index=False)
        meta.write_text(json.dumps({"model": TTC_MODEL, "rows": len(cells)}))
    cells = pd.read_parquet(path)
    cells["obs_date"] = pd.PeriodIndex(pd.to_datetime(cells.obs_date), freq="Q")
    return cells


def as_series(zs: pd.DataFrame, col: str = "z") -> pd.Series:
    """Column `col` of the per-quarter Z table, indexed by quarter."""
    return zs.set_index("obs_date")[col]


def portfolio_pred(cells: pd.DataFrame, z: pd.Series, rho: float, floor: float = 0.0) -> pd.Series:
    """Predicted portfolio default rate per quarter for a Z per quarter; `floor` > 0 applies
    the 12-month PD floor to every cell (para 96)."""
    c = cells[cells.n > 0]
    q = np.maximum(vasicek_pd(c.p.values, c.obs_date.map(z).values, rho), floor)
    num = pd.Series(c.n.values * q, index=c.obs_date).groupby(level=0).sum()
    return num / c.groupby("obs_date").n.sum()


def mean_abs_log_error(actual: pd.Series, pred: pd.Series, quarters: list[pd.Period]) -> float:
    """Mean |log(actual / predicted)| default rate over `quarters`."""
    a, p = actual.loc[quarters], pred.loc[quarters]
    return float(np.mean(np.abs(np.log(a / p))))


def evaluate_fit(
    fit: SatelliteFit,
    cells: pd.DataFrame,
    macro: pd.DataFrame,
    zs: pd.DataFrame,
    rho: float,
    quarters_by_split: dict[str, list[pd.Period]],
) -> dict:
    """Fit statistics of a satellite specification and its backtest error per split, plus the
    crisis peak quarter actual vs predicted."""
    zhat = fit.predict(macro)
    actual = as_series(zs, "actual_rate")
    pred = portfolio_pred(cells, zhat, rho)
    out = {
        "alignment": fit.alignment,
        "spec": fit.describe(),
        "dropped_wrong_sign": ", ".join(fit.dropped),
        "r2": fit.r2,
        "bic": fit.bic,
        "sigma": fit.sigma,
        "nobs": fit.nobs,
    }
    for name, qs in quarters_by_split.items():
        out[f"err_{name}"] = mean_abs_log_error(actual, pred, qs)
    out["err_oot13"] = mean_abs_log_error(
        actual, pred, quarters_by_split["oot1"] + quarters_by_split["oot3"]
    )
    crisis = [q for q in actual.index if 2007 <= q.year <= 2011]
    out["peak_actual"] = str(actual.loc[crisis].idxmax())
    out["peak_pred"] = str(pred.loc[crisis].idxmax())
    out["peak_actual_rate"] = float(actual.loc[crisis].max())
    out["peak_pred_rate"] = float(pred.loc[crisis].max())
    return out


def driver_rule(
    z: pd.Series,
    cells: pd.DataFrame,
    macro: pd.DataFrame,
    zs: pd.DataFrame,
    rho: float,
    dev_q: list[pd.Period],
    oot13: list[pd.Period],
    drivers: list[str],
) -> pd.DataFrame:
    """Driver rule for each driver of a window-aligned specification: expected sign and |HAC t|
    >= 2 in sample; on OOT1+OOT3 a core driver may not worsen the error by more than 5%, an
    optional driver must improve it by at least 5% (compared with the same specification
    without it)."""
    actual = as_series(zs, "actual_rate")
    full = fit_window(z, macro, drivers, dev_q)
    e_full = mean_abs_log_error(actual, portfolio_pred(cells, full.predict(macro), rho), oot13)
    rows = []
    for d in drivers:
        rest = [x for x in drivers if x != d]
        red = fit_window(z, macro, rest, dev_q)
        e_red = mean_abs_log_error(actual, portfolio_pred(cells, red.predict(macro), rho), oot13)
        term = f"{d}[W]"
        in_fit = term in full.params.index
        t = float(full.tvalues[term]) if in_fit else float("nan")
        gain = 1 - e_full / e_red
        core = d in CORE_DRIVERS
        oos_ok = e_full <= (1 + DRIVER_MIN_GAIN) * e_red if core else gain >= DRIVER_MIN_GAIN
        rows.append(
            {
                "specification": " + ".join(drivers),
                "driver": d,
                "role": "core (ex ante)" if core else "optional",
                "sign_ok": in_fit,
                "t_hac": t,
                "err_with": e_full,
                "err_without": e_red,
                "error_reduction": gain,
                "out_of_sample_ok": bool(oos_ok),
                "passes": bool(in_fit and abs(t) >= DRIVER_MIN_T and oos_ok),
            }
        )
    return pd.DataFrame(rows)


def satellite_specs(
    zs: pd.DataFrame,
    cells: pd.DataFrame,
    macro: pd.DataFrame,
    rho: float,
    dev_q: list[pd.Period],
    qsplit: dict[str, list[pd.Period]],
) -> pd.DataFrame:
    """The final specification and the reported alternatives (sensitivities / challengers)."""
    z = as_series(zs)
    specs = [
        ("final: W house prices + GDP", fit_window, FINAL_DRIVERS),
        ("sensitivity: W + Fed funds change", fit_window, CANDIDATE_DRIVERS),
        ("alternative: L (lags t, t-4)", fit_lagged, FINAL_DRIVERS),
        ("challenger: W house prices + unemployment", fit_window, CHALLENGER_DRIVERS),
    ]
    rows = []
    for label, fitter, drivers in specs:
        f = fitter(z, macro, drivers, dev_q)
        rows.append(
            {"rho": rho, "variant": label, **evaluate_fit(f, cells, macro, zs, rho, qsplit)}
        )
    return pd.DataFrame(rows)


def group_fit(
    cells: pd.DataFrame, z: pd.Series, rho: float, oot13: list[pd.Period]
) -> pd.DataFrame:
    """Measured-Z backtest by delinquency group: the test of the cross-sectional shape."""
    g = predicted_by_group(cells, z, rho, "group")
    g["abs_log"] = np.abs(np.log(g.actual_rate / g.pred_rate))
    allq = g.groupby("group").abs_log.mean().rename("mean_abs_log_all")
    o = g[g.obs_date.isin(oot13)].assign(pred_d=lambda d: d.pred_rate * d.n)
    ratio = (o.groupby("group").defaults.sum() / o.groupby("group").pred_d.sum()).rename(
        "actual_to_pred_oot13"
    )
    return pd.concat([allq, ratio], axis=1).reset_index().assign(rho=rho)


def stationarity(series: dict[str, pd.Series]) -> pd.DataFrame:
    """ADF (H0 unit root) and KPSS (H0 stationary); KPSS p-values are capped at 0.10 by its
    look-up table. Low power with ~68 overlapping quarters: read with the economic signs."""
    warnings.filterwarnings("ignore", category=InterpolationWarning)
    rows = []
    for name, s in series.items():
        s = s.dropna()
        adf_p = adfuller(s, autolag="AIC")[1]
        kpss_p = kpss(s, regression="c", nlags="auto")[1]
        rows.append(
            {
                "series": name,
                "n": len(s),
                "adf_p": adf_p,
                "kpss_p": kpss_p,
                "reading": "stationary"
                if adf_p < 0.05 and kpss_p > 0.05
                else "non-stationary"
                if adf_p >= 0.05 and kpss_p <= 0.05
                else "inconclusive",
            }
        )
    return pd.DataFrame(rows)


def segment_backtest(cells: pd.DataFrame, z_meas: pd.Series, z_hat: pd.Series) -> pd.DataFrame:
    """Actual vs predicted by delinquency group and by sand states, per period."""
    by_group = []
    for zname, zz in [("measured", z_meas), ("satellite", z_hat)]:
        for col in ["group", "sand"]:
            g = predicted_by_group(cells, zz, RHO, col).rename(columns={col: "segment"})
            g["segment"] = (
                g.segment.astype(str)
                if col == "group"
                else g.segment.map({True: "CA/FL/NV/AZ", False: "other states"})
            )
            g["z"] = zname
            g["period"] = [period_of(q) for q in g.obs_date]
            by_group.append(g)
    by_group = pd.concat(by_group)
    seg = (
        by_group.assign(pred_d=by_group.pred_rate * by_group.n)
        .groupby(["z", "segment", "period"], sort=False)
        .agg(n=("n", "sum"), defaults=("defaults", "sum"), pred=("pred_d", "sum"))
        .reset_index()
    )
    seg["actual_rate"] = seg.defaults / seg.n
    seg["pred_rate"] = seg.pred / seg.n
    seg["actual_to_pred"] = seg.defaults / seg.pred
    # CO-3 monitoring view: sand-state actual / predicted by quarter (satellite Z)
    sand = by_group[(by_group.z == "satellite") & (by_group.segment == "CA/FL/NV/AZ")].copy()
    sand["actual_to_pred"] = sand.actual_rate / sand.pred_rate
    sand = sand[
        ["obs_date", "period", "n", "defaults", "actual_rate", "pred_rate", "actual_to_pred"]
    ].rename(columns={"obs_date": "quarter"})
    sand["quarter"] = sand.quarter.astype(str)
    return seg.drop(columns="pred"), sand


def fit_pit_pd(rebuild_cells: bool = False) -> None:
    """Credit-cycle index Z_t, asset correlation, macro satellite, backtests and model card;
    `rebuild_cells` rescans every PD snapshot instead of using the cached cells."""
    git = git_state(ROOT, CODE_AND_REGULATORY_CONFIG)
    cfg = yaml.safe_load((ROOT / "config" / "rbi_2026.yaml").read_text(encoding="utf-8"))
    floor = float(cfg["pd"]["floor_12_month"]["value"])
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Macro drivers (FRED, quarterly)")
    macro, macro_qc = load_macro(ROOT / "data" / "macro")
    cells = load_cells(rebuild_cells)
    quarters = sorted(cells.obs_date.unique())
    qsplit = {s: [q for q in quarters if split_of(q) == s] for s in ["dev", "oot1", "oot2", "oot3"]}
    dev_q, oot13 = qsplit["dev"], qsplit["oot1"] + qsplit["oot3"]
    logger.info(f"  {len(cells):,} cells, {cells.n.sum():,} snapshots, {len(quarters)} quarters")

    logger.info("Asset correlation: profile likelihood (reported; rho is a decided benchmark)")
    prof = profile_rho(cells, RHO_GRID, var_quarters=dev_q)
    rho_info = {
        "rho": RHO,
        "basis": "Basel residential-mortgage benchmark; not identifiable from this "
        "data; chosen by the backtest by delinquency group (Yash, 2026-11-13)",
        "profile_rho_hat": prof.rho_hat,
        "profile_at_grid_boundary": bool(prof.rho_hat in (RHO_GRID.min(), RHO_GRID.max())),
        "rho_unit_variance_route2": rho_unit_variance(prof.table),
    }

    logger.info("Z_t, group backtest and final satellite for rho = 0.15 and the sensitivities")
    sens_rows, group_tables, per_rho = [], [], {}
    for rho in sorted([RHO, *RHO_SENSITIVITIES]):
        zs = z_series(cells, rho)
        gf = group_fit(cells, as_series(zs), rho, oot13)
        fit = fit_window(as_series(zs), macro, FINAL_DRIVERS, dev_q)
        pred = portfolio_pred(cells, fit.predict(macro), rho)
        sens_rows.append(
            {
                "rho": rho,
                "role": "model" if rho == RHO else "sensitivity",
                "worst_group_mean_abs_log": gf.mean_abs_log_all.max(),
                **{f"a_to_p_oot13[{r.group}]": r.actual_to_pred_oot13 for r in gf.itertuples()},
                "groups_within_tolerance": bool(
                    gf.actual_to_pred_oot13.between(*GROUP_TOLERANCE).all()
                ),
                "z_mean_dev": zs[zs.obs_date.isin(dev_q)].z.mean(),
                "z_var_dev": zs[zs.obs_date.isin(dev_q)].z.var(),
                "satellite": fit.describe(),
                "sat_err_oot13": mean_abs_log_error(as_series(zs, "actual_rate"), pred, oot13),
                "mean_pit_2009": pred.loc[[q for q in quarters if q.year == 2009]].mean(),
                "mean_pit_2018": pred.loc[[q for q in quarters if q.year == 2018]].mean(),
            }
        )
        group_tables.append(gf)
        per_rho[rho] = (zs, fit)
    sensitivity = pd.DataFrame(sens_rows)
    zs, fit = per_rho[RHO]
    z_meas = as_series(zs)
    logger.info(f"  final: {fit.describe()}")

    logger.info("Driver rule and reported specifications")
    rule = pd.concat(
        [
            driver_rule(z_meas, cells, macro, zs, RHO, dev_q, oot13, d)
            for d in [CANDIDATE_DRIVERS, FINAL_DRIVERS]
        ],
        ignore_index=True,
    )
    specs = satellite_specs(zs, cells, macro, RHO, dev_q, qsplit)

    logger.info("Backtest of the final setup (with and without the 12m PD floor)")
    z_hat = fit.predict(macro)
    zq = pd.DataFrame(
        {
            "z_measured": z_meas,
            "z_satellite": z_hat.reindex(quarters),
            "actual_rate": as_series(zs, "actual_rate"),
            "ttc_pd": as_series(zs, "ttc_pd"),
            "pit_pd_measured_z": as_series(zs, "pit_pd"),
        }
    )
    zq["pit_pd"] = portfolio_pred(cells, z_hat, RHO)
    zq["pit_pd_floored"] = portfolio_pred(cells, z_hat, RHO, floor)
    zq["band_low"] = portfolio_pred(cells, z_hat + BAND_Z * fit.sigma, RHO)
    zq["band_high"] = portfolio_pred(cells, z_hat - BAND_Z * fit.sigma, RHO)
    zq["inside_band"] = zq.actual_rate.between(zq.band_low, zq.band_high)
    za = z_series(cells, RHO, n_col="n_a", d_col="d_a", p_col="p_a")
    zq["actual_rate_target_a"] = as_series(za, "actual_rate")
    zq["z_measured_target_a"] = as_series(za)
    c = cells[cells.n > 0]
    q = vasicek_pd(c.p.values, c.obs_date.map(z_hat).values, RHO)
    zq["floor_binds_share"] = (
        pd.Series(c.n.values * (q < floor), index=c.obs_date).groupby(level=0).sum()
        / c.groupby("obs_date").n.sum()
    )
    zq.index.name = "quarter"
    zq = zq.reset_index()
    zq.insert(1, "split", [split_of(q) for q in zq.quarter])
    zq.insert(2, "period", [period_of(q) for q in zq.quarter])
    crisis = zq[zq.period == "crisis"]
    peak = {
        "actual": [
            str(crisis.loc[crisis.actual_rate.idxmax(), "quarter"]),
            float(crisis.actual_rate.max()),
        ],
        "predicted": [
            str(crisis.loc[crisis.pit_pd.idxmax(), "quarter"]),
            float(crisis.pit_pd.max()),
        ],
    }

    periods = (
        zq.groupby("period", sort=False)
        .agg(
            quarters=("quarter", "size"),
            actual_rate=("actual_rate", "mean"),
            ttc_pd=("ttc_pd", "mean"),
            pit_pd=("pit_pd", "mean"),
            pit_pd_floored=("pit_pd_floored", "mean"),
            z_measured=("z_measured", "mean"),
            z_satellite=("z_satellite", "mean"),
            share_inside_band=("inside_band", "mean"),
            floor_binds_share=("floor_binds_share", "mean"),
            actual_rate_target_a=("actual_rate_target_a", "mean"),
        )
        .reset_index()
    )
    periods["actual_to_ttc"] = periods.actual_rate / periods.ttc_pd
    periods["actual_to_pit"] = periods.actual_rate / periods.pit_pd
    periods["actual_to_pit_floored"] = periods.actual_rate / periods.pit_pd_floored
    periods["floor_effect"] = periods.pit_pd_floored / periods.pit_pd - 1
    seg, sand_q = segment_backtest(cells, z_meas, z_hat)

    logger.info("Stationarity, AR challenger, coefficient stability")
    design = fit.design(macro)
    st_series = {
        "z_measured (dev)": z_meas.loc[dev_q],
        "satellite residual (dev)": (z_meas - z_hat).loc[dev_q],
    }
    for col in design.columns:
        st_series[f"{col} (dev)"] = design[col].loc[dev_q]
    for d in DRIVERS:
        st_series[f"{d}, 1990-2026"] = macro[d].loc["1990Q1":"2026Q2"]
    st = stationarity(st_series)
    zdf = (
        pd.concat([z_meas.rename("z"), z_meas.shift(4).rename("z_lag4"), design], axis=1)
        .loc[dev_q]
        .dropna()
    )
    ar = sm.OLS(zdf.z, sm.add_constant(zdf.drop(columns="z"))).fit(
        cov_type="HAC", cov_kwds={"maxlags": 4}
    )
    fit_early = fit_terms(
        z_meas, macro, fit.terms, fit.alignment, [q for q in dev_q if q.year <= 2012]
    )
    coef = pd.DataFrame(
        {
            "term": fit.params.index,
            "coef_2000_2016": fit.params.values,
            "t_hac": fit.tvalues.values,
            "coef_2000_2012": fit_early.params.reindex(fit.params.index).values,
            "coef_ar_challenger": ar.params.reindex(fit.params.index).values,
        }
    )
    coef = pd.concat(
        [
            coef,
            pd.DataFrame(
                [
                    {
                        "term": "z_lag4 (AR challenger)",
                        "coef_ar_challenger": ar.params["z_lag4"],
                        "t_hac": ar.tvalues["z_lag4"],
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    coef["expected_sign"] = [
        ("+" if DRIVERS[t.split("[")[0]] > 0 else "-") if t.split("[")[0] in DRIVERS else ""
        for t in coef.term
    ]

    lr_means = macro.loc[dev_q[0] : dev_q[-1], FINAL_DRIVERS].mean()
    final_rule = rule[rule.specification == " + ".join(FINAL_DRIVERS)]
    meta = {
        "version": VERSION,
        "previous_version": PREVIOUS,
        "ttc_model": TTC_MODEL,
        "trained_at": datetime.now(UTC).isoformat(),
        "git": git,
        "target": "target_b18",
        "rho": RHO,
        "rho_info": rho_info,
        "rho_sensitivities": RHO_SENSITIVITIES,
        "alignment": "W",
        "satellite": {
            "terms": [[d, lag] for d, lag in fit.terms],
            "params": fit.params.to_dict(),
            "sigma": fit.sigma,
            "r2": fit.r2,
            "nobs": fit.nobs,
        },
        "long_run_driver_means_2000_2016": lr_means.to_dict(),
        "long_run_z": float(
            fit.params["const"] + sum(fit.params[f"{d}[W]"] * lr_means[d] for d in FINAL_DRIVERS)
        ),
        "driver_rule": {
            "min_abs_t": DRIVER_MIN_T,
            "core_drivers": CORE_DRIVERS,
            "core_max_error_increase": DRIVER_MIN_GAIN,
            "optional_min_error_reduction": DRIVER_MIN_GAIN,
        },
        "final_drivers_pass_rule": bool(final_rule.passes.all()),
        "estimation_quarters": [str(dev_q[0]), str(dev_q[-1])],
        "pd_floor_12m": floor,
        "crisis_peak": peak,
        "group_tolerance": GROUP_TOLERANCE,
        "data_note": "US Freddie Mac data and US macro (FRED); not Indian risk estimates",
    }

    tables = {
        "macro_quarterly": macro.loc["1998Q1":]
        .reset_index()
        .rename(columns={"observation_date": "quarter"})
        .assign(quarter=lambda d: d.quarter.astype(str)),
        "macro_qc": macro_qc,
        "rho_profile": prof.table,
        "rho_sensitivity": sensitivity,
        "group_fit": pd.concat(group_tables),
        "satellite_specs": specs,
        "driver_rule": rule,
        "z_by_quarter": zq.assign(quarter=zq.quarter.astype(str)),
        "backtest_periods": periods,
        "backtest_by_segment": seg,
        "sand_states_by_quarter": sand_q,
        "coefficients": coef,
        "stationarity": st,
    }
    for name, t in tables.items():
        t.to_csv(REPORTS / f"pd_pit_{name}.csv", index=False)
        t.to_csv(MODEL_DIR / f"{name}.csv", index=False)
    (MODEL_DIR / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    card = model_card(meta, tables)
    (MODEL_DIR / "model_card.md").write_text(card, encoding="utf-8")
    (REPORTS / "pd_pit_model_card.md").write_text(card, encoding="utf-8")
    logger.info("Done")


def model_card(meta: dict, t: dict[str, pd.DataFrame]) -> str:
    """Markdown model card of the point-in-time PD model."""
    sat = meta["satellite"]
    commit = meta["git"]["commit"]
    state = (
        "code and regulatory config committed"
        if meta["git"]["clean"]
        else "WITH UNCOMMITTED CHANGES - not reproducible from this commit"
    )
    ri = meta["rho_info"]
    pk = meta["crisis_peak"]
    terms = " ".join(f"{v:+.4f} x {k}" for k, v in sat["params"].items() if k != "const")
    return f"""# Model card: PIT conversion of the 12-month PD ({meta["version"]})

**Code version.** git commit `{commit}` ({state}); fitted {meta["trained_at"][:10]}.
TTC input: `{meta["ttc_model"]}`. Methodology: `docs/methodology/pd_point_in_time.md`. Development log:
`models/pd_pit/CHANGELOG.md`.

**US data.** Freddie Mac loans and US macro series (FRED). Not Indian risk estimates.

**What it does.** A credit-cycle index Z_t (Z > 0 benign) is measured each quarter from the
realised 12-month B-18 defaults given each loan's TTC PD (Vasicek single factor). A satellite
regression links Z_t to macro drivers averaged over the 12-month outcome window, so scenarios
can move the PD (RBI paras 47-49). The same Z drives the default hazard of the lifetime PD.

**Asset correlation rho = {meta["rho"]:.2f}**: {ri["basis"]}. The profile likelihood runs to the
edge of the grid (rho_hat {ri["profile_rho_hat"]:.2f}, not an interior estimate); unit variance of
Z would need rho {ri["rho_unit_variance_route2"]:.3f}. 0.10 and 0.20 are reported as sensitivities.
Z_t is therefore not N(0, 1): long-run Z = {meta["long_run_z"]:+.3f} (the satellite at the
2000-2016 driver means).

**Satellite (final, window-aligned)**, estimated {meta["estimation_quarters"][0]}-{meta["estimation_quarters"][1]}:
Z_hat = {sat["params"]["const"]:+.4f} {terms}; R² {sat["r2"]:.3f}; residual sd {sat["sigma"]:.3f}.
Driver rule (expected sign, |HAC t| >= 2; core drivers named ex ante may not worsen the OOT
error by more than 5%, optional additions must improve it by >= 5%): final drivers pass =
**{meta["final_drivers_pass_rule"]}**. The Fed funds change is reported
as a sensitivity only. **OOT1-OOT3 (2017-2023) have been used for driver selection, so they are
not a fully clean test period.**

**Crisis peak:** predicted {pk["predicted"][1]:.2%} in {pk["predicted"][0]} vs actual
{pk["actual"][1]:.2%} in {pk["actual"][0]}.

## Driver rule
{md_table(t["driver_rule"])}

## Coefficients
{md_table(t["coefficients"])}

## Reported specifications (rho = 0.15)
{md_table(t["satellite_specs"])}

## Correlation sensitivity (final satellite refitted for each rho)
{md_table(t["rho_sensitivity"])}

## Backtest by period (satellite Z with realised macro), with and without the 0.03% floor
`pit_pd` is the model; `pit_pd_floored` applies the 12-month PD floor (para 96) per cell;
`floor_effect` = floored / unfloored - 1. `actual_to_pit` measures model error;
`actual_to_pit_floored` adds the effect of the floor.

{md_table(t["backtest_periods"])}

## Backtest by segment and period
{md_table(t["backtest_by_segment"])}

## Stationarity (ADF p < 0.05 and KPSS p > 0.05 = stationary)
{md_table(t["stationarity"])}

## Macro data QC
{md_table(t["macro_qc"])}
"""
