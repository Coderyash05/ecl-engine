"""Scenario paths: forecast + reversion, severity regions and the MacroPath.

What (docs/methodology/scenarios.md):
1. A scenario's 12-quarter forecast is a (12, 4) array of the VAR variables (var.py).
   `extend` appends it to history (cut at the reporting quarter), then each driver moves linearly
   over 8 quarters to its long-run value and stays there to the end of the path (para 124:
   mean reversion beyond the forecast horizon).
2. Upside / central / downside are **conditional means of regions** of the simulated
   distribution:
   - simulated paths = base + VAR deviations;
   - ranked by a severity index, Zbar = the satellite Z at the 12-quarter mean HPI and GDP
     growth;
   - split by rank into the worst 20% / middle 60% / best 20%.
   The weights are the region shares, so the weighted mean of the scenarios equals the
   simulation mean, which is the base. This is unbiased by construction (para 47).
3. Severity checks against history are in severity.py.
4. `to_macro_path`: the hazard's MacroPath (Module 3):
   - Z from the satellite, with measured Z only for windows complete at the reporting date;
   - state HPI by betas (state_paths.py).

US data; Indian roles plug in through the same frame (Module 12).
"""

import numpy as np
import pandas as pd

from ecl.lifetime.macro import gdp_yoy
from ecl.lifetime.paths import Q0, Q_END, MacroPath, satellite_z, z_for_quarters
from ecl.scenarios.state_paths import project_states
from ecl.scenarios.var import ANNUALISE


def lr_growth_targets(lr: dict) -> dict:
    """Long-run values in the frame's units: hpi_g (annualised log %), gdp_g (SAAR %), levels."""
    return {
        "hpi_g": 100 * np.log1p(lr["hpi_yoy"] / 100),
        "gdp_g": lr["gdp_yoy"],
        "mortgage30": lr["mortgage30"],
        "unrate": lr["unrate"],
    }


def extend(
    hist: pd.DataFrame,
    fc: np.ndarray,
    lr: dict,
    report_q: pd.Period,
    revert: int,
    end: pd.Period | None = None,
) -> pd.DataFrame:
    """Quarterly frame: history to report_q, then the forecast `fc` (h, 4: hpi_g, gdp_g,
    d_mort, d_unrate), then linear reversion over `revert` quarters to the long-run values
    `lr` (hpi_yoy, gdp_yoy, mortgage30, unrate), flat afterwards.

    Columns: hpi_g, gdp_g, mortgage30, unrate, log_hpi (national), hpi_yoy, gdp_yoy.
    `hist` needs hpi (index level), gdp_qoq_saar, mortgage30, unrate."""
    end = end or pd.Period(year=Q_END // 4 - 1, quarter=4, freq="Q")
    h = hist.loc[:report_q]
    for c in ["hpi", "gdp_qoq_saar", "mortgage30", "unrate"]:
        if pd.isna(h[c].iloc[-1]):
            raise ValueError(f"{c} missing at the reporting quarter {report_q}")
    past = pd.DataFrame(
        {
            "hpi_g": ANNUALISE * np.log(h.hpi).diff(),
            "gdp_g": h.gdp_qoq_saar,
            "mortgage30": h.mortgage30,
            "unrate": h.unrate,
        }
    )
    n_fc = len(fc)
    fut_idx = pd.period_range(report_q + 1, end, freq="Q")
    fut = pd.DataFrame(index=fut_idx, columns=past.columns, dtype=float)
    fut.iloc[:n_fc, 0] = fc[:, 0]
    fut.iloc[:n_fc, 1] = fc[:, 1]
    fut.iloc[:n_fc, 2] = h.mortgage30.iloc[-1] + np.cumsum(fc[:, 2])
    fut.iloc[:n_fc, 3] = h.unrate.iloc[-1] + np.cumsum(fc[:, 3])
    tgt = lr_growth_targets(lr)
    k = np.arange(1, len(fut_idx) - n_fc + 1)
    for j, c in enumerate(past.columns):
        x0 = fut.iloc[n_fc - 1, j] if n_fc else past[c].iloc[-1]
        fut.iloc[n_fc:, j] = x0 + (tgt[c] - x0) * np.minimum(k / revert, 1.0)
    out = pd.concat([past, fut])
    out["log_hpi"] = pd.concat(
        [np.log(h.hpi), np.log(h.hpi.iloc[-1]) + (fut.hpi_g / ANNUALISE).cumsum()]
    )
    out["hpi_yoy"] = 100 * (np.exp(out.log_hpi - out.log_hpi.shift(4)) - 1)
    out["gdp_yoy"] = gdp_yoy(out.gdp_g)
    return out


def yoy_paths(last3: np.ndarray, sims: np.ndarray, kind: str) -> np.ndarray:
    """YoY growth (%) for each simulated quarter from quarterly rates: `last3` = the 3 quarters
    before the forecast (hpi_g or gdp_g), `sims` (n, h). kind: 'hpi' (annualised log %) or
    'gdp' (SAAR %)."""
    n, h = sims.shape
    full = np.hstack([np.tile(last3, (n, 1)), sims])
    if kind == "hpi":
        s = np.stack([full[:, t : t + 4].sum(axis=1) for t in range(h)], axis=1)
        return 100 * (np.exp(s / ANNUALISE) - 1)
    f = (1 + full / 100) ** 0.25
    return 100 * (np.stack([f[:, t : t + 4].prod(axis=1) for t in range(h)], axis=1) - 1)


def severity(params: dict, hpi_yoy: np.ndarray, gdp_yoy_: np.ndarray) -> np.ndarray:
    """Zbar: the satellite Z at the mean YoY growth over the forecast quarters (n,)."""
    return (
        params["const"]
        + params["hpi_yoy[W]"] * hpi_yoy.mean(axis=1)
        + params["gdp_yoy[W]"] * gdp_yoy_.mean(axis=1)
    )


def partition(paths: np.ndarray, sev: np.ndarray, shares: tuple[float, float, float]) -> dict:
    """Region means of simulated paths (n, h, k), split by rank of severity (low = adverse);
    `shares` = (downside, central, upside) region shares = the scenario weights (config).
    Returns {'downside', 'central', 'upside'} -> {'path', 'weight', 'severity', 'n'}."""
    n = len(sev)
    order = np.argsort(sev, kind="stable")
    cut1 = round(shares[0] * n)
    cut2 = round((shares[0] + shares[1]) * n)
    out = {}
    for name, sel in [
        ("downside", order[:cut1]),
        ("central", order[cut1:cut2]),
        ("upside", order[cut2:]),
    ]:
        out[name] = {
            "path": paths[sel].mean(axis=0),
            "weight": len(sel) / n,
            "severity": float(sev[sel].mean()),
            "n": len(sel),
        }
    return out


def one_year_forward(frame: pd.DataFrame, report_q: pd.Period) -> dict:
    """Table 5 '1 year forward' growth of HPI and GDP over the 4 quarters after report_q."""
    q4 = report_q + 4
    return {
        "hpi": 100 * (np.exp(frame.log_hpi[q4] - frame.log_hpi[report_q]) - 1),
        "gdp": frame.gdp_yoy[q4],
    }


def to_macro_path(
    name: str,
    frame: pd.DataFrame,
    params: dict,
    z_measured: pd.Series,
    report_q: pd.Period,
    log_state: pd.DataFrame,
    betas: pd.Series,
) -> MacroPath:
    """MacroPath for the hazard: satellite Z, with measured Z only for snapshots whose 12-month
    window is complete at the reporting date (s <= report_q - 4: no look-ahead) and for which a
    measured value exists (the satellite fills the rest); state indices observed to report_q and
    projected with betas afterwards."""
    grid = pd.period_range(
        pd.Period(year=Q0 // 4, quarter=1, freq="Q"),
        pd.Period(year=Q_END // 4 - 1, quarter=4, freq="Q"),
        freq="Q",
    )
    hpi_yoy = frame.hpi_yoy.reindex(grid)
    gdp = frame.gdp_yoy.reindex(grid)
    z_sat = satellite_z(params, hpi_yoy, gdp)
    z_m = z_measured.reindex(grid)
    z_s = z_m.where((grid <= report_q - 4) & z_m.notna(), z_sat).ffill()
    nat = frame.log_hpi.reindex(grid).ffill().bfill()
    st = project_states(log_state, nat, betas, report_q)
    states = list(st.columns)
    return MacroPath(
        name,
        z_for_quarters(z_s).values,
        hpi_yoy.ffill().bfill().values,
        frame.mortgage30.reindex(grid).ffill().bfill().values,
        st.T.values,
        states,
        z_s=z_s.values,
    )
