"""Point-in-time PD (Module 3): Vasicek PIT conversion, cycle index Z_t, macro alignment, satellite.

Hand-built examples: each test states the rule it checks.
"""

import numpy as np
import pandas as pd
import pytest

from ecl.lifetime.cycle import (
    fit_z,
    predicted_by_group,
    profile_rho,
    rho_unit_variance,
    vasicek_pd,
    z_series,
)
from ecl.lifetime.macro import gdp_yoy, read_fred, to_quarterly, window_mean
from ecl.lifetime.satellite import fit_lagged, fit_terms, fit_window

# ---------------------------------------------------------------- Vasicek


def test_pit_pd_averages_to_ttc_pd_over_the_cycle():
    """E_Z[PD_PIT(p, Z)] = p for Z ~ N(0, 1): the TTC PD is the cycle average."""
    x, w = np.polynomial.hermite_e.hermegauss(80)
    w = w / w.sum()
    for p in [0.0005, 0.01, 0.25, 0.69]:
        for rho in [0.05, 0.15, 0.30]:
            assert np.sum(w * vasicek_pd(p, x, rho)) == pytest.approx(p, rel=1e-6)


def test_average_year_pd_is_below_ttc_pd_for_low_pds():
    """Z = 0 is the median year: the PIT PD is below the TTC PD when p < 50%."""
    assert vasicek_pd(0.0124, 0.0, 0.15) == pytest.approx(0.0075, abs=2e-4)
    assert vasicek_pd(0.0124, 0.0, 0.15) < 0.0124


def test_benign_year_lowers_pd_and_stress_raises_it():
    z = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    pd_ = vasicek_pd(0.01, z, 0.15)
    assert np.all(np.diff(pd_) < 0)


def test_relative_shift_is_smaller_for_high_pds():
    """The same benign Z cuts a 0.5% PD proportionally more than a 60% PD (docs/methodology/pd_point_in_time.md)."""
    z = 0.5
    low = vasicek_pd(0.005, z, 0.15) / 0.005
    high = vasicek_pd(0.60, z, 0.15) / 0.60
    assert low < high < 1


# ---------------------------------------------------------------- Z_t estimation


def _cells(
    z_by_q: dict,
    rho: float,
    p=(0.002, 0.01, 0.05, 0.25, 0.6),
    n=(200_000, 50_000, 10_000, 3_000, 1_000),
) -> pd.DataFrame:
    """Expected defaults (no noise) for loans with TTC PD p in quarters with known Z."""
    rows = []
    for q, z in z_by_q.items():
        for pi, ni in zip(p, n, strict=True):
            rows.append(
                {
                    "obs_date": q,
                    "p": pi,
                    "n": ni,
                    "d": ni * float(vasicek_pd(pi, z, rho)),
                    "group": "low" if pi < 0.1 else "high",
                }
            )
    return pd.DataFrame(rows)


def test_fit_z_recovers_the_true_z():
    for z0 in [-1.4, 0.0, 0.6]:
        c = _cells({1: z0}, 0.15)
        z, _ = fit_z(c.p, c.n, c.d, 0.15)
        assert z == pytest.approx(z0, abs=1e-4)


def test_z_series_fits_every_quarter_and_matches_actual_rate():
    c = _cells({1: -1.0, 2: 0.3}, 0.12)
    zs = z_series(c, 0.12)
    assert zs.z.tolist() == pytest.approx([-1.0, 0.3], abs=1e-4)
    assert zs.pit_pd.values == pytest.approx(zs.actual_rate.values, rel=1e-5)


def test_profile_likelihood_recovers_rho_from_the_cross_section():
    """With Z free every quarter, rho is identified by how the shift spreads across PDs."""
    c = _cells({q: z for q, z in enumerate([-1.5, -0.5, 0.0, 0.4, 1.0])}, 0.12)
    prof = profile_rho(c, np.round(np.arange(0.02, 0.31, 0.01), 2))
    assert prof.rho_hat == pytest.approx(0.12)
    assert prof.ci[0] <= 0.12 <= prof.ci[1]


def test_rho_where_z_has_unit_variance():
    t = pd.DataFrame({"rho": [0.01, 0.02, 0.03], "z_var": [2.0, 1.2, 0.8]})
    assert rho_unit_variance(t) == pytest.approx(0.025)
    assert np.isnan(rho_unit_variance(t.assign(z_var=[0.5, 0.4, 0.3])))


def test_predicted_by_group_uses_the_quarter_z():
    c = _cells({1: -1.0}, 0.15)
    g = predicted_by_group(c, pd.Series({1: -1.0}), 0.15, "group")
    assert g.pred_rate.values == pytest.approx(g.actual_rate.values, rel=1e-6)


# ---------------------------------------------------------------- macro alignment


def test_read_fred_handles_old_header_and_missing_values(tmp_path):
    f = tmp_path / "X.csv"
    f.write_text("DATE,X\n2020-01-01,1.5\n2020-02-01,.\n2020-03-01,\n")
    s = read_fred(f)
    assert s.name == "X" and s.iloc[0] == 1.5 and s.isna().sum() == 2


def test_monthly_to_quarterly_mean_needs_two_months():
    idx = pd.to_datetime(["2025-10-01", "2025-11-01", "2025-12-01", "2026-01-01"])
    s = pd.Series([np.nan, 4.0, 5.0, 3.0], index=idx)  # Oct missing; Q1 2026 has one month
    q, short = to_quarterly(s, min_obs=2)
    assert q.to_dict() == {pd.Period("2025Q4"): 4.5}
    assert set(short.quarter) == {"2025Q4", "2026Q1"}


def test_weekly_to_quarterly_mean_needs_ten_weeks():
    weeks = pd.date_range("2020-01-02", "2020-06-30", freq="W-THU")
    s = pd.Series(np.arange(len(weeks), dtype=float), index=weeks)
    q, _ = to_quarterly(s.iloc[:20], min_obs=10)  # Q1 complete, Q2 has 7 weeks
    assert list(q.index) == [pd.Period("2020Q1")]
    assert q.iloc[0] == pytest.approx(s.iloc[:13].mean())


def test_gdp_yoy_compounds_quarterly_annualised_rates():
    g = pd.Series([4.0] * 4 + [0.0, 0.0, 0.0, -8.0])
    yoy = gdp_yoy(g)
    assert yoy.iloc[3] == pytest.approx(4.0)
    assert yoy.iloc[7] == pytest.approx(100 * (0.92**0.25) - 100)


def test_window_mean_covers_the_four_quarters_after_t():
    """Snapshot in quarter t, outcomes in t+1..t+4 (alignment W)."""
    x = pd.Series(np.arange(10, dtype=float))
    w = window_mean(x)
    assert w.iloc[0] == pytest.approx(np.mean([1, 2, 3, 4]))
    assert np.isnan(w.iloc[6])


# ---------------------------------------------------------------- satellite


def _macro(n=80, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.period_range("2000Q1", periods=n, freq="Q")
    return pd.DataFrame(
        {
            "hpi_yoy": rng.normal(4, 5, n),
            "gdp_yoy": rng.normal(2, 2, n),
            "ff_chg4": rng.normal(0, 1.5, n),
            "unrate_chg4": rng.normal(0, 1, n),
        },
        index=idx,
    )


def test_window_satellite_recovers_coefficients():
    m = _macro()
    z = -0.5 + 0.05 * window_mean(m.hpi_yoy) + 0.10 * window_mean(m.gdp_yoy)
    q = list(m.index[:70])
    fit = fit_window(z, m, ["hpi_yoy", "gdp_yoy"], q)
    assert fit.params["hpi_yoy[W]"] == pytest.approx(0.05, abs=1e-8)
    assert fit.params["gdp_yoy[W]"] == pytest.approx(0.10, abs=1e-8)
    assert fit.predict(m).loc[q].values == pytest.approx(z.loc[q].values)


def test_wrong_sign_driver_is_dropped_not_forced():
    """A rate rise must lower Z (benign = positive). A driver with the wrong sign is removed."""
    m = _macro()
    rng = np.random.default_rng(2)
    z = 0.05 * window_mean(m.hpi_yoy) + 0.2 * window_mean(m.ff_chg4) + rng.normal(0, 0.01, 80)
    fit = fit_window(z, m, ["hpi_yoy", "ff_chg4"], list(m.index[:70]))
    assert [d for d, _ in fit.terms] == ["hpi_yoy"]
    assert fit.dropped == ["ff_chg4[W]"]


def test_lagged_satellite_picks_the_true_lag():
    m = _macro()
    z = 0.05 * m.hpi_yoy.shift(4) + 0.1 * m.gdp_yoy
    fit = fit_lagged(z, m, ["hpi_yoy", "gdp_yoy"], list(m.index[8:70]))
    assert sorted(fit.terms) == [("gdp_yoy", 0), ("hpi_yoy", 4)]


def test_fit_terms_uses_only_the_given_quarters():
    m = _macro()
    z = 0.05 * window_mean(m.hpi_yoy)
    z.iloc[60:] += 5  # out-of-time quarters must not affect the fit
    fit = fit_terms(z, m, [("hpi_yoy", "W")], "W", list(m.index[:60]))
    assert fit.params["hpi_yoy[W]"] == pytest.approx(0.05, abs=1e-8)
