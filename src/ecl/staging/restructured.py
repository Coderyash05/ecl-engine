"""Stage 3 history per loan: NPA status, restructuring state and duration in Stage 3 (Module 6).

RBI basis (texts quoted in docs/methodology/staging.md):
- ACPIR para 8(10): an NPA "may be upgraded as 'standard' asset only if the entire arrears of
  interest and principal are repaid" -> a loan that reached 90+ dpd (status 03+, REO) stays in
  default and Stage 3 (paras 6(3)(i), 6(5)) until it is back to current (status 00).
- RSA 6(12): restructuring = concessions granted for reasons relating to the borrower's financial
  difficulty, incl. "alteration of payment period / payable amount". RSA 52-54: a standard
  account restructured becomes NPA (ACPIR 6(3)(iii): credit-impaired -> Stage 3); an NPA keeps
  its classification and ageing. ACPIR 78 + RSA 58: Stage 3 -> 2 after satisfactory performance
  (RSA 6(14): no default at any time) during the monitoring period (RSA 6(8): 10% of principal
  incl. interest capitalisation repaid), not before one year from the first payment; Stage 2 -> 1
  after the specified period (RSA 6(16): 20% repaid) and no SICR. RSA 61 / 62: a miss during the
  monitoring period (or a default after upgrade, before the specified period ends) -> no upgrade
  without a fresh restructuring. Paras 59 (MSME) and 60 (>= Rs 100 crore) do not apply.
- RSA Chapter VI-A / IRACP 62A, 62B: a calamity resolution (borrower standard and not > 30 days
  in default when the calamity occurred, RSA 124J) keeps the account standard; ACPIR 82(4)(xiv)
  floors apply (category advances_restructured_standard).
- ACPIR 82(5) "Duration in Stage 3" = the unbroken run of Stage 3 months ending at the date (NPA
  months and restructured Stage 3 months together; RSA 53-54: NPA ageing continues through a
  restructuring).

Data mapping (Freddie Mac; US data):
- restructuring events: modification month (flag Y; later Y months = fresh restructurings) and,
  by mapping, the first month of a payment-deferral run (status C);
- calamity-linked deferral: in the COVID window derived from the data, or the disaster flag in
  the lookback; eligible if current (or not reported) and not NPA in the month before the
  hardship episode (contiguous relief months) began;
- base = Current Actual UPB in the event month (= interest-bearing + non-interest-bearing UPB);
- miss = any month at status 01+ or RBI default after the implementation month (1-29 days late
  is status 00 and not observable: slightly lenient vs "any default"); status XX = no evidence.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike

TOL = 1e-9  # floating-point tolerance on the repaid-share thresholds (not a parameter)
MODES = ("text", "stage3", "stage2")  # restructuring mapping: RSA rule / always 3 / at most 2
MISS_RULES = ("no_upgrade", "restart")


def _month(x: ArrayLike) -> np.ndarray:
    t = pd.to_datetime(pd.Series(x))
    return (t.dt.year * 12 + t.dt.month).to_numpy()


def covid_window(monthly: pd.Series, baseline_years: list, multiplier: float) -> tuple:
    """COVID deferral window from panel-wide deferral counts by month (index: month start dates):
    the contiguous run of months around the peak whose count exceeds multiplier x the median
    month of the baseline years. Returns (first, last) month as Timestamps."""
    m = monthly.sort_index()
    yrs = m.index.year
    base = m[(yrs >= baseline_years[0]) & (yrs <= baseline_years[1])].median()
    above = (m > multiplier * base).to_numpy()
    peak = int(np.argmax(m.to_numpy()))
    if not above[peak]:
        raise ValueError("no deferral peak above the baseline threshold")
    lo = hi = peak
    while lo > 0 and above[lo - 1]:
        lo -= 1
    while hi < len(m) - 1 and above[hi + 1]:
        hi += 1
    return m.index[lo], m.index[hi]


def restructuring_events(hist: pd.DataFrame, window: tuple, lookback: int) -> pd.DataFrame:
    """Per loan-month event flags. hist: loan_id, period, dpd_bucket, default_event, modified,
    payment_deferral, relief_flag, disaster_dlq. Adds mod_event (flag Y month), deferral_event
    (first month of a deferral run), calamity_link, calamity_eligible, calamity_event (eligible
    calamity-linked deferral), general_event (modification, or a deferral that is not an
    eligible calamity deferral)."""
    h = hist.sort_values(["loan_id", "period"], ignore_index=True)
    flag = lambda c: h[c].fillna(False).astype(bool)
    defer, relief, dis = flag("payment_deferral"), flag("relief_flag"), flag("disaster_dlq")
    h["mod_event"] = flag("modified")
    h["deferral_event"] = defer & ~defer.groupby(h.loan_id).shift(fill_value=False).astype(bool)
    in_window = (h.period >= window[0]) & (h.period <= window[1])
    dis_recent = (
        dis.astype(float)
        .groupby(h.loan_id)
        .rolling(lookback + 1, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
        .sort_index()
        .astype(bool)
    )
    h["calamity_link"] = h.deferral_event & (in_window | dis_recent)
    # NPA status (para 8(10)) and the start of the hardship episode (run of relief months)
    dflt = flag("default_event")
    cur = h.dpd_bucket.isin(["current", "unknown"])
    npa = pd.Series(np.where(dflt, 1.0, np.where(h.dpd_bucket.eq("current"), 0.0, np.nan)))
    npa = npa.groupby(h.loan_id).ffill().fillna(0.0).astype(bool)
    # key = loan x (number of non-relief months so far): a relief run shares its key with the
    # non-relief month just before it; that month's status is the status before the episode
    run = (~relief).astype(int).groupby(h.loan_id).cumsum()
    first_row = h.groupby([h.loan_id, run]).cumcount() == 0
    ok = (cur & ~npa & ~relief).where(first_row)
    episode_ok = ok.groupby([h.loan_id, run]).transform("first")
    h["calamity_eligible"] = h.calamity_link & episode_ok.fillna(False).astype(bool)
    h["calamity_event"] = h.calamity_eligible
    h["general_event"] = h.mod_event | (h.deferral_event & ~h.calamity_eligible)
    return h


def stage3_history(
    hist: pd.DataFrame,
    tm: dict,
    mode: str = "text",
    npa_persists: bool = True,
    event_col: str = "restr_event",
    miss_rule: str = "no_upgrade",
    fresh: bool = True,
) -> pd.DataFrame:
    """Walk each loan's months (loan_id, period, current_upb, dpd_bucket, default_event and the
    restructuring-event column) up to the reporting date. tm = config
    `staging.restructured.text_mapping`.

    mode: restructured loans follow the RSA rule ('text'), are always Stage 3 ('stage3') or never
    Stage 3 ('stage2'). npa_persists: para 8(10) (False = in default only in a 90+ month).
    miss_rule 'no_upgrade' (RSA 61 / 62): a miss after the implementation month blocks upgrades
    until a fresh restructuring; 'restart': a miss restarts the clock the month after (earlier
    rule; misses in the implementation month count). fresh: later events start a new monitoring
    period (False: only the first event counts).

    Per loan at the last month: npa, npa_arrears (npa, not 90+ now), restructured (an event
    happened), restr_state (3 / 2 / 1 = graduated; NaN if never), stuck (blocked by RSA 61 / 62),
    events (number of restructuring events), stage3, years_s3 (current Stage 3 spell; NaN if not
    Stage 3), years_restr_s3 (restructured Stage 3 months only), months_after_first_payment,
    repaid_on_clock, restarts (misses that reset or blocked the clock)."""
    if mode not in MODES or miss_rule not in MISS_RULES:
        raise ValueError(f"unknown mode {mode} or miss rule {miss_rule}")
    r2, mo, r1 = tm["stage2_repaid"], tm["stage2_months_after_first_payment"], tm["stage1_repaid"]
    h = hist.sort_values(["loan_id", "period"], ignore_index=True)
    ids = h.loan_id.to_numpy()
    mon = _month(h.period)
    upb = h.current_upb.to_numpy(float)
    dpd = h.dpd_bucket.to_numpy(object)
    dflt = h.default_event.fillna(False).to_numpy(bool)
    event = h[event_col].fillna(False).to_numpy(bool)
    starts = np.flatnonzero(np.r_[True, ids[1:] != ids[:-1]])
    ends = np.r_[starts[1:], len(h)]
    rows = []
    for a, b in zip(starts, ends, strict=True):
        npa = started = stuck = False
        state, clock, base, restarts, repaid, n_events = 3, 0, np.nan, 0, 0.0, 0
        s3_start = r3_start = None
        prev3 = prev_r3 = False
        for i in range(a, b):
            cur, unk = dpd[i] == "current", dpd[i] == "unknown"
            miss = dflt[i] or not (cur or unk)
            npa = True if dflt[i] else (False if cur or not npa_persists else npa)
            if event[i] and (not started or fresh):
                started, stuck, state, clock, base, repaid = True, False, 3, mon[i], np.nan, 0.0
                n_events += 1
            if started and mode == "text" and state > 1:
                if miss and (miss_rule == "restart" or mon[i] > clock):
                    restarts += 1
                    state, base, repaid = 3, np.nan, 0.0
                    if miss_rule == "restart":
                        clock = mon[i] + 1
                    else:
                        stuck = True
                elif not stuck and mon[i] >= clock and not miss:
                    if np.isnan(base) and upb[i] > 0:
                        base = upb[i]
                    if not np.isnan(base):
                        repaid = max(0.0, 1 - upb[i] / base) if upb[i] > 0 else repaid
                        if state == 3 and mon[i] - (clock + 1) >= mo and repaid >= r2 - TOL:
                            state = 2
                        if state == 2 and repaid >= r1 - TOL:
                            state = 1
            r3 = started and (mode == "stage3" or (mode == "text" and state == 3))
            s3 = npa or r3
            if s3 and not prev3:
                s3_start = mon[i]
            if r3 and not prev_r3:
                r3_start = mon[i]
            prev3, prev_r3 = s3, r3
        last = mon[b - 1]
        rows.append(
            (
                ids[a],
                npa,
                npa and not dflt[b - 1],
                started,
                (state if mode == "text" else {"stage3": 3, "stage2": 2}[mode])
                if started
                else np.nan,
                stuck,
                n_events,
                prev3,
                (last - s3_start) / 12 if prev3 else np.nan,
                (last - r3_start) / 12 if prev_r3 else np.nan,
                last - (clock + 1) if started else np.nan,
                repaid if started else np.nan,
                restarts,
            )
        )
    return pd.DataFrame(
        rows,
        columns=[
            "loan_id",
            "npa",
            "npa_arrears",
            "restructured",
            "restr_state",
            "stuck",
            "events",
            "stage3",
            "years_s3",
            "years_restr_s3",
            "months_after_first_payment",
            "repaid_on_clock",
            "restarts",
        ],
    )


def performance_summary(hist: pd.DataFrame, as_at: str, event_col: str) -> pd.DataFrame:
    """Per restructured loan (from its first event month): months since restructuring, any
    missed payment since, share of the UPB at restructuring repaid by the date (descriptive)."""
    h = hist.sort_values(["loan_id", "period"])
    h = h[h.groupby("loan_id")[event_col].cummax().astype(bool)]
    h = h.assign(miss=h.default_event | ~h.dpd_bucket.isin(["current", "unknown"]))
    g = h.groupby("loan_id", sort=False)
    first = g.period.first()
    upb_pos = h[h.current_upb > 0].groupby("loan_id").current_upb
    at = pd.Timestamp(as_at)
    return pd.DataFrame(
        {
            "months_since_modification": (at.year - first.dt.year) * 12 + at.month - first.dt.month,
            "dlq30_since_modification": g.miss.any(),
            "repaid_since_modification": 1 - upb_pos.last() / upb_pos.first(),
        }
    ).reset_index()
