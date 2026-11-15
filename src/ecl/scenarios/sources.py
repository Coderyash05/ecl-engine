"""External forecast sources for the base scenario, read "as at" the reporting date.

What (docs/methodology/scenarios.md):
- **SPF** (Philadelphia Fed Survey of Professional Forecasters, median forecasts):
  - `medianGrowth.xlsx`, sheet RGDP: quarterly real GDP growth, SAAR (`drgdp2..6`);
  - `medianLevel.xlsx`, sheets RGDP / UNEMP / TBOND: quarterly levels (suffix 1-6) and annual
    averages (suffix A-D).
  - Suffix convention: 1 = the quarter before the survey, 2 = the survey quarter, 3-6 = 1-4
    quarters ahead; A = the survey year, B-D = 1-3 years ahead (annual averages).
- **FRED GS10**: monthly 10-year Treasury yield (the mortgage-Treasury spread).
- **SEP** (FOMC Summary of Economic Projections): medians are held in `config/scenarios.yaml`
  (typed from Table 1 of the PDF) and checked against the PDF text by `check_sep_pdf`.

No look-ahead (paras 47-49: "information available without undue cost or effort at the reporting
date"):
- an SPF survey is used only if its release falls on or before the "as at" date. The release
  date is not in the file; the bound used is the **last day of the survey quarter's second
  month** (surveys are released in the middle of that month, e.g. 2023Q1 on 10 Feb 2023);
- GS10 and SEP observations after the "as at" date raise an error or are cut.

US sources; the Indian adapter (Module 12) would read the RBI Survey of Professional
Forecasters and the Monetary Policy Report the same way.
"""

from pathlib import Path

import numpy as np
import pandas as pd

SPF_SUFFIX_QUARTER = {"1": -1, "2": 0, "3": 1, "4": 2, "5": 3, "6": 4}
SPF_SUFFIX_YEAR = {"A": 0, "B": 1, "C": 2, "D": 3}


def spf_release_bound(survey: pd.Period) -> pd.Timestamp:
    """Latest plausible release date of an SPF survey: end of the quarter's second month."""
    month2 = survey.asfreq("M", how="start") + 1
    return month2.end_time.normalize()


def read_spf(path: Path, sheet: str) -> pd.DataFrame:
    """One SPF median sheet with a quarterly PeriodIndex (survey quarter)."""
    d = pd.read_excel(path, sheet_name=sheet)
    d.index = pd.PeriodIndex(
        [
            pd.Period(year=int(y), quarter=int(q), freq="Q")
            for y, q in zip(d.YEAR, d.QUARTER, strict=True)
        ]
    )
    return d.drop(columns=["YEAR", "QUARTER"]).apply(pd.to_numeric, errors="coerce")


def spf_survey_as_at(spf: pd.DataFrame, as_at: pd.Timestamp) -> pd.Period:
    """The latest survey released on or before `as_at` (see the module note on release dates)."""
    ok = [q for q in spf.index if spf_release_bound(q) <= as_at]
    if not ok:
        raise ValueError(f"no SPF survey released by {as_at.date()}")
    return max(ok)


def spf_row(spf: pd.DataFrame, survey: pd.Period, as_at: pd.Timestamp) -> pd.Series:
    """The survey's row, refusing a survey released after `as_at` (look-ahead)."""
    if spf_release_bound(survey) > as_at:
        raise ValueError(f"SPF {survey} is released after the as-at date {as_at.date()}")
    return spf.loc[survey]


def spf_points(row: pd.Series, var: str, survey: pd.Period) -> tuple[dict, dict]:
    """Quarterly values {quarter: value} (suffix 1-6) and annual averages {year: value} (A-D)."""
    q = {
        survey + k: row[f"{var}{s}"]
        for s, k in SPF_SUFFIX_QUARTER.items()
        if f"{var}{s}" in row and pd.notna(row[f"{var}{s}"])
    }
    a = {
        survey.year + k: row[f"{var}{s}"]
        for s, k in SPF_SUFFIX_YEAR.items()
        if f"{var}{s}" in row and pd.notna(row[f"{var}{s}"])
    }
    return q, a


def read_gs10(path: Path, as_at: pd.Timestamp) -> pd.Series:
    """Quarterly mean of the monthly 10-year Treasury yield, months up to `as_at` only; a quarter
    is kept only when all 3 months are observed."""
    d = pd.read_csv(path)
    s = pd.Series(
        pd.to_numeric(d.iloc[:, 1], errors="coerce").values,
        index=pd.PeriodIndex(pd.to_datetime(d.iloc[:, 0]), freq="M"),
    ).dropna()
    s = s[s.index.end_time <= as_at + pd.Timedelta(days=1)]
    g = s.groupby(s.index.asfreq("Q"))
    out = g.mean()[g.count() == 3]
    out.index = pd.PeriodIndex(out.index, freq="Q")
    return out


def smooth_quarterly(start: pd.Period, end: pd.Period, fixed: dict, averages: dict) -> pd.Series:
    """Quarterly path start..end that passes through `fixed` {quarter: value}, whose calendar-year
    means equal `averages` {year: value}, and is otherwise as smooth as possible (minimum sum of
    squared second differences; equality-constrained least squares solved by its KKT system).

    Why: the SPF gives 4 quarterly values and then annual averages only. Holding each annual
    average exactly (rather than placing it at mid-year) keeps the path consistent with the
    published forecast; minimum curvature avoids the steps of a piecewise-constant fill."""
    idx = pd.period_range(start, end, freq="Q")
    n = len(idx)
    pos = {q: i for i, q in enumerate(idx)}
    rows, b = [], []
    for q, v in fixed.items():
        if q in pos:
            r = np.zeros(n)
            r[pos[q]] = 1.0
            rows.append(r)
            b.append(v)
    for y, v in averages.items():
        qs = [pos[q] for q in pd.period_range(f"{y}Q1", f"{y}Q4", freq="Q")]
        if all(idx[i] in fixed for i in qs):
            continue  # year fully pinned: the average is implied
        r = np.zeros(n)
        r[qs] = 0.25
        rows.append(r)
        b.append(v)
    a = np.array(rows)
    d2 = np.diff(np.eye(n), n=2, axis=0)
    k = len(b)
    kkt = np.block([[2 * d2.T @ d2, a.T], [a, np.zeros((k, k))]])
    sol = np.linalg.solve(kkt, np.r_[np.zeros(n), np.array(b, dtype=float)])
    return pd.Series(sol[:n], index=idx)


def check_sep_pdf(pdf: Path, medians: dict) -> list[str]:
    """Confirm the SEP medians typed into the config against the PDF's text: the row
    'GDP 2023 2024 2025 LR' etc. must appear as consecutive numbers. Returns the rows not found
    (empty = all confirmed)."""
    from pypdf import PdfReader

    text = " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(pdf).pages)
    missing = []
    for name, vals in medians.items():
        row = " ".join(f"{v:.1f}" for v in vals)
        alt = row.replace("0.", ".")  # accessible-HTML printouts drop the 0
        if row not in text and alt not in text:
            missing.append(f"{name}: {row}")
    return missing
