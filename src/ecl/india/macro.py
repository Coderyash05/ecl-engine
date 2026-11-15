"""Indian macro inputs from the RBI DBIE files (Module 12, SYNTHETIC book; data are real RBI
series but they drive a synthetic portfolio, so outputs are not Indian risk estimates).

- House Price Index (RBI, quarterly, all-India and cities) in three bases: 2008-09 = 100 (9
  cities; all-India from Q3 2011-12), 2010-11 = 100 (10 cities, Q1 2010-11 to Q4 2024-25) and
  2022-23 = 100 (18 cities, Q1 2022-23 on). Spliced on growth rates: each quarter's level comes
  from the newest base covering it; earlier quarters are chained back with the QoQ growth of the
  older base. Overlap checks compare YoY growth of the bases in the common quarters.
- Policy repo rate (LAF repo; effective dates) -> rate in force at each quarter end.
- Real GDP (DBIE table 161, NAS bases 2011-12 and 2022-23, CSV exports): YoY growth chained
  across the bases (no level splice); CPI (MoSPI, Combined General, All India) base 2012 linked
  to base 2024 by the mean 2025 ratio. Every file is checked for base, coverage, row count and
  gaps (DataCheckError).
RBI fiscal quarters: Q1 = April-June ... Q4 = January-March of the following calendar year.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd


def fiscal_to_period(label: str) -> pd.Period:
    """'Q1.2022-23' -> 2022Q2 (April-June 2022); Q4.2022-23 -> 2023Q1."""
    m = re.match(r"\s*Q([1-4])\.(\d{4})-\d{2}", str(label))
    if not m:
        raise ValueError(f"not a fiscal quarter label: {label!r}")
    q, y = int(m.group(1)), int(m.group(2))
    return pd.Period(year=y + (q == 4), quarter={1: 2, 2: 3, 3: 4, 4: 1}[q], freq="Q")


def _read(path: Path) -> pd.DataFrame:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_excel(path, header=None)


def read_hpi(path: Path) -> dict[str, pd.DataFrame]:
    """{base label: DataFrame (quarter index x city columns incl. 'All India')}."""
    raw = _read(path)
    first = raw.iloc[:, 1].fillna("").astype(str)
    starts = [i for i, v in first.items() if v.startswith("Base Year")]
    out = {}
    for k, s in enumerate(starts):
        base = re.search(r"(\d{4}-\d{2})", first[s]).group(1)
        end = starts[k + 1] if k + 1 < len(starts) else len(raw)
        hdr = s + 2
        cols = [c for c in raw.columns[2:] if pd.notna(raw.at[hdr, c])]
        names = [str(raw.at[hdr, c]).strip() for c in cols]
        rows = []
        for i in range(hdr + 1, end):
            lab = raw.at[i, 1]
            if pd.isna(lab) or not str(lab).strip().startswith("Q"):
                continue
            rows.append(
                [
                    fiscal_to_period(lab),
                    *[pd.to_numeric(raw.at[i, c], errors="coerce") for c in cols],
                ]
            )
        df = pd.DataFrame(rows, columns=["quarter", *names]).set_index("quarter")
        out[base] = df
    return out


def splice(series: list[pd.Series]) -> tuple[pd.Series, list[dict]]:
    """Splice index series (oldest first) on growth rates: the newest series sets the level in
    its quarters; earlier quarters are chained back with QoQ growth of the newest older series
    covering them. Returns the spliced index (rebased to the newest base) and overlap checks
    (YoY growth of adjacent bases in their common quarters)."""
    series = [s.dropna() for s in series if s.dropna().size]
    out = series[-1].copy()
    checks = []
    for older in reversed(series[:-1]):
        common = out.index.intersection(older.index)
        if len(common):
            a, b = out.loc[common], older.loc[common]
            ya, yb = a.pct_change(4).dropna(), b.pct_change(4).dropna()
            both = ya.index.intersection(yb.index)
            checks.append(
                {
                    "overlap_from": str(common.min()),
                    "overlap_to": str(common.max()),
                    "quarters": len(common),
                    "yoy_quarters": len(both),
                    "mean_abs_diff_yoy_pp": float((ya[both] - yb[both]).abs().mean() * 100)
                    if len(both)
                    else None,
                    "corr_yoy": float(np.corrcoef(ya[both], yb[both])[0, 1])
                    if len(both) > 2
                    else None,
                }
            )
        first = out.index.min()
        back = older[older.index < first]
        if back.empty:
            continue
        if first not in older.index:  # gap: cannot chain
            continue
        ratio = older / older.loc[first]
        out = pd.concat([ratio[ratio.index < first] * out.loc[first], out]).sort_index()
    return out, checks


def hpi_spliced(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Spliced quarterly HPI for all-India and every city (rebased to the 2022-23 base); a city
    missing from the older bases is chained back with the all-India growth (flagged)."""
    bases = read_hpi(path)
    order = sorted(bases)  # '2008-09' < '2010-11' < '2022-23'
    cities = sorted(set().union(*[set(b.columns) for b in bases.values()]))
    out, checks = {}, []
    for c in cities:
        s, ch = splice([bases[b][c] for b in order if c in bases[b]])
        out[c] = s
        checks += [{"series": c, **x} for x in ch]
    df = pd.DataFrame(out).sort_index()
    ai = df["All India"]
    for c in cities:
        if c == "All India":
            continue
        first = df[c].first_valid_index()
        early = ai.index < first
        if early.any() and first in ai.index:
            df.loc[early, c] = ai[early] / ai.loc[first] * df.at[first, c]
            checks.append({"series": c, "chained_with_all_india_before": str(first)})
    return df, pd.DataFrame(checks)


def _repo_changes(path: Path) -> pd.DataFrame:
    """Effective date and LAF repo rate of each change (column 'Repo' under 'Fix Range LAF')."""
    raw = _read(path)
    hdr = raw.index[raw.apply(lambda r: r.astype(str).str.strip().eq("Repo").any(), axis=1)][0]
    col = raw.columns[raw.loc[hdr].astype(str).str.strip().eq("Repo")][0]
    datecol = raw.columns[raw.loc[hdr - 1].astype(str).str.startswith("Effective")][0]
    d = raw.loc[hdr + 2 :, [datecol, col]].copy()
    d.columns = ["date", "repo"]
    d["date"] = pd.to_datetime(d.date, errors="coerce")
    d["repo"] = pd.to_numeric(d.repo, errors="coerce")
    return d.dropna().sort_values("date").reset_index(drop=True)


def repo_quarterly(path: Path) -> pd.Series:
    """LAF policy repo rate in force at each quarter end (per cent): step function of the last
    change on or before the quarter end."""
    d = _repo_changes(path)
    q = pd.period_range(d.date.min().to_period("Q"), d.date.max().to_period("Q"), freq="Q")
    ends = q.to_timestamp(how="end")
    idx = np.searchsorted(d.date.values, ends.values, side="right") - 1
    vals = np.where(idx >= 0, d.repo.values[np.clip(idx, 0, None)], np.nan)
    return pd.Series(vals, index=q, name="repo").dropna()


def repo_at(path: Path, date: str) -> float:
    """Repo rate in force on a date."""
    d = _repo_changes(path)
    return float(d[d.date <= pd.Timestamp(date)].repo.iloc[-1])


class DataCheckError(ValueError):
    """An Indian macro file does not have the expected base, coverage or continuity."""


def parse_inr(x: object) -> float:
    """Indian-format number: '61,62,845.93' (lakh / crore comma grouping), ' -67,532.54'."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = str(x).strip().replace(",", "")
    return float(s) if s not in ("", "-") else np.nan


def read_gdp_csv(path: Path, expected: dict) -> pd.Series:
    """DBIE table 161 CSV export (one NAS base): c1 = fiscal year on Q1 rows (forward-filled),
    c2 = quarter, c11 = GDP (Rs crore, constant prices). Checks the base in the title, the first
    and last quarter, the row count and continuity; raises DataCheckError otherwise."""
    raw = pd.read_csv(path, dtype=str)
    title = " ".join(raw.c1.dropna().astype(str))
    base = re.search(r"Base\s*:\s*(\d{4}-\d{2})", title)
    if not base or base.group(1) != expected["base"]:
        raise DataCheckError(f"{path.name}: base {base and base.group(1)} != {expected['base']}")
    rows = raw[raw.c2.fillna("").str.strip().str.fullmatch(r"Q[1-4]")].copy()
    fy = rows.c1.where(rows.c1.fillna("").str.strip().str.fullmatch(r"\d{4}-\d{2}")).ffill()
    if fy.isna().any():
        raise DataCheckError(f"{path.name}: quarter rows before the first fiscal year label")
    idx = [fiscal_to_period(f"{q.strip()}.{y.strip()}") for y, q in zip(fy, rows.c2, strict=True)]
    gdp = pd.Series([parse_inr(v) for v in rows.c11], index=pd.PeriodIndex(idx, freq="Q"))
    gdp = gdp.sort_index()
    _check_periods(gdp, path.name, expected, "Q")
    return gdp


def _check_periods(s: pd.Series, name: str, expected: dict, freq: str) -> None:
    if freq == "Q":
        first, last = fiscal_to_period(expected["first"]), fiscal_to_period(expected["last"])
    else:
        first, last = pd.Period(expected["first"], freq="M"), pd.Period(expected["last"], freq="M")
    full = pd.period_range(s.index.min(), s.index.max(), freq=freq)
    problems = []
    if s.index.min() != first or s.index.max() != last:
        problems.append(f"covers {s.index.min()}-{s.index.max()}, expected {first}-{last}")
    if len(s) != expected["rows"]:
        problems.append(f"{len(s)} rows, expected {expected['rows']}")
    if len(full) != len(s) or s.index.duplicated().any():
        problems.append("gaps or duplicate periods")
    if s.isna().any():
        problems.append(f"{int(s.isna().sum())} missing values")
    if problems:
        raise DataCheckError(f"{name}: " + "; ".join(problems))


def gdp_yoy_chained(old: pd.Series, new: pd.Series, last_old: pd.Period) -> tuple[pd.Series, dict]:
    """Real GDP YoY growth (per cent) chained across NAS bases WITHOUT splicing levels: the old
    base's YoY up to `last_old`, the new base's YoY afterwards. Overlap statistics compare the
    two bases' YoY in their common quarters (re-basing changes growth, not just the level)."""
    yo, yn = old.pct_change(4).dropna() * 100, new.pct_change(4).dropna() * 100
    both = yo.index.intersection(yn.index)
    stats = {
        "overlap_from": str(both.min()) if len(both) else None,
        "overlap_to": str(both.max()) if len(both) else None,
        "overlap_quarters": len(both),
        "mean_yoy_old_base": float(yo[both].mean()) if len(both) else None,
        "mean_yoy_new_base": float(yn[both].mean()) if len(both) else None,
        "corr_yoy": float(np.corrcoef(yo[both], yn[both])[0, 1]) if len(both) > 2 else None,
        "mean_abs_diff_pp": float((yo[both] - yn[both]).abs().mean()) if len(both) else None,
        "by_quarter": {str(q): [round(float(yo[q]), 2), round(float(yn[q]), 2)] for q in both},
    }
    out = pd.concat([yo[yo.index <= last_old], yn[yn.index > last_old]]).sort_index()
    if len(pd.period_range(out.index.min(), out.index.max(), freq="Q")) != len(out):
        raise DataCheckError("chained GDP YoY has gaps")
    stats["chained_from"], stats["chained_to"] = str(out.index.min()), str(out.index.max())
    stats["switch_after"] = str(last_old)
    return out, stats


def _months(year: pd.Series, month: pd.Series) -> pd.PeriodIndex:
    dt = pd.to_datetime(year.astype(str) + "-" + month.astype(str), format="%Y-%B")
    return pd.PeriodIndex(dt, freq="M")


def read_cpi2012(path: Path, expected: dict) -> pd.Series:
    """MoSPI CPI, base 2012 = 100, All India Combined General: monthly `index` column (the
    `inflation` column is blank in 2013, so inflation is computed). Status F* (Apr-May 2020,
    imputed during the COVID lockdown) is kept and reported."""
    d = pd.read_csv(path)
    if set(d.baseyear.astype(str)) != {expected["base"]}:
        raise DataCheckError(f"{path.name}: base {set(d.baseyear)} != {expected['base']}")
    d = d[(d.state == "All India") & (d.sector == "Combined") & (d.subgroup == "General-Overall")]
    s = pd.Series(d["index"].astype(float).values, index=_months(d.year, d.month)).sort_index()
    _check_periods(s, path.name, expected, "M")
    return s


def read_cpi2024(path: Path, expected: dict) -> pd.Series:
    """MoSPI CPI, base 2024 = 100: state All India, sector Combined, division CPI (General)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d = pd.read_excel(path)
    if set(d.base_year.astype(str)) != {expected["base"]}:
        raise DataCheckError(f"{path.name}: base {set(d.base_year)} != {expected['base']}")
    keep = (d.state == "All India") & (d.sector == "Combined") & (d.division == "CPI (General)")
    d = d[keep & d.group.isna()]
    s = pd.Series(d["index"].astype(float).values, index=_months(d.year, d.month)).sort_index()
    _check_periods(s, path.name, expected, "M")
    return s


def cpi_linked(
    c12: pd.Series, c24: pd.Series, link_year: int, max_ratio_range: float
) -> tuple[pd.Series, dict]:
    """One monthly CPI series on the 2012 base: the 2012-base index to its last month, then the
    2024-base index x link factor = mean of (2012 base / 2024 base) over the link year's months.
    Raises if the monthly ratios vary by more than `max_ratio_range` (unstable link)."""
    common = c12.index.intersection(c24.index)
    common = common[common.year == link_year]
    if len(common) != 12:
        raise DataCheckError(f"CPI link year {link_year}: {len(common)} common months, need 12")
    ratio = c12[common] / c24[common]
    stats = {
        "link_year": link_year,
        "ratio_mean": float(ratio.mean()),
        "ratio_min": float(ratio.min()),
        "ratio_max": float(ratio.max()),
        "ratio_range": float(ratio.max() - ratio.min()),
    }
    if stats["ratio_range"] > max_ratio_range:
        raise DataCheckError(f"CPI link ratio unstable: {stats}")
    tail = c24[c24.index > c12.index.max()] * stats["ratio_mean"]
    out = pd.concat([c12, tail]).sort_index()
    if len(pd.period_range(out.index.min(), out.index.max(), freq="M")) != len(out):
        raise DataCheckError("linked CPI has gaps")
    stats["linked_from"], stats["linked_to"] = str(out.index.min()), str(out.index.max())
    return out, stats


def describe(name: str, s: pd.Series, base: str) -> dict:
    """One inventory row: base, first / last period, frequency, rows."""
    return {
        "series": name,
        "base": base,
        "first": str(s.index.min()),
        "last": str(s.index.max()),
        "frequency": s.index.freqstr,
        "rows": len(s),
    }


def load_all(dir_: Path, cfg: dict) -> dict:
    """Load and validate every Indian macro input (raises DataCheckError on a wrong base, gaps
    or truncation). Returns the series, the inventory and the splice / link statistics."""
    f, ex = cfg["files"], cfg["expected"]
    hpi, hpi_checks = hpi_spliced(dir_ / f["hpi"])
    repo_q = repo_quarterly(dir_ / f["repo"])
    g11 = read_gdp_csv(dir_ / f["gdp_2011_12"], ex["gdp_2011_12"])
    g22 = read_gdp_csv(dir_ / f["gdp_2022_23"], ex["gdp_2022_23"])
    last_old = fiscal_to_period(cfg["gdp_last_quarter_old_base"])
    gdp_yoy, gdp_stats = gdp_yoy_chained(g11, g22, last_old)
    c12 = read_cpi2012(dir_ / f["cpi_2012"], ex["cpi_2012"])
    c24 = read_cpi2024(dir_ / f["cpi_2024"], ex["cpi_2024"])
    cpi, cpi_stats = cpi_linked(c12, c24, cfg["cpi_link_year"], cfg["cpi_link_max_ratio_range"])
    imputed = pd.read_csv(dir_ / f["cpi_2012"]).query("status != 'F'")
    cpi_stats["imputed_months"] = [f"{r.year}-{r.month} ({r.status})" for r in imputed.itertuples()]
    hb = read_hpi(dir_ / f["hpi"])
    inv = [describe(f"HPI all-India, base {b}", d["All India"].dropna(), b) for b, d in hb.items()]
    inv += [
        describe("HPI all-India spliced", hpi["All India"].dropna(), "2022-23 (spliced on growth)"),
        describe("Repo rate (quarter end)", repo_q, "per cent"),
        describe("GDP NAS (Rs crore, constant prices)", g11, ex["gdp_2011_12"]["base"]),
        describe("GDP NAS (Rs crore, constant prices)", g22, ex["gdp_2022_23"]["base"]),
        describe("GDP YoY growth, chained", gdp_yoy, "growth only (no level splice)"),
        describe("CPI Combined General, All India", c12, ex["cpi_2012"]["base"]),
        describe("CPI Combined General, All India", c24, ex["cpi_2024"]["base"]),
        describe("CPI linked", cpi, "2012 = 100 (2024 base linked)"),
    ]
    return {
        "hpi": hpi,
        "hpi_checks": hpi_checks,
        "repo_q": repo_q,
        "gdp_yoy": gdp_yoy,
        "gdp_stats": gdp_stats,
        "cpi": cpi,
        "cpi_stats": cpi_stats,
        "inventory": pd.DataFrame(inv),
    }
