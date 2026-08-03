"""Canonical liquidation-readiness computation. Import this; do not reimplement it.

TASK 006A. This module exists because the repository briefly carried TWO disagreeing
readiness numbers - `study/data_readiness.py` said 14 independent cascades and ~89 days,
`study/liquidation_readiness_audit.py` said 5 - and the looser one propagated a wrong
figure into `HANDOFF.md`. Both scripts now call this single implementation, and each
asserts its output matches.

Importing this module has NO side effects: no file is written, no network call is made,
no price series is opened. It computes counts only. It cannot compute a post-cascade
return, direction, volatility outcome or win rate, because it never loads price data.

--------------------------------------------------------------------------------
FORMAL vs PROVISIONAL - the distinction that matters
--------------------------------------------------------------------------------
The frozen definition in PREREGISTRATION_liquidations.md ranks each 5-minute bucket
against a TRAILING 30-DAY distribution. A bucket cannot be scored that way until 30 days
of capture precede it.

  FORMAL      a bucket is formally scorable only when >= 30 calendar days of captured
              liquidation history precede it. While the feed is younger than 30 days the
              formal cascade count is 0, the formal gate is closed, and there is no formal
              development or holdout count. This is not pessimism - it is the frozen rule
              applied honestly.

  PROVISIONAL a clearly-labelled startup diagnostic that ranks against whatever history
              exists. It uses an ad-hoc floor of 20 prior non-empty buckets so a 95th
              percentile is not taken from two observations. THAT FLOOR IS NOT IN THE
              PREREGISTRATION and the numbers it produces MUST NOT be presented as gate
              progress, nor used to publish a gate ETA.

Task 006 reported the provisional numbers as though they were gate progress and derived a
"~340 days" estimate from a 3.22-day sample. Both are corrected here.
"""
import os

import numpy as np
import pandas as pd

# frozen parameters - these mirror PREREGISTRATION_liquidations.md and must not drift
BUCKET = "5min"
TOP_PCT = 0.95              # top 5% of non-empty buckets
TRAIL_DAYS = 30             # trailing window the rank is taken against
HOLDOUT_FRAC = 0.25         # untouched final 25%, chronological
DEV_GATE = 400              # independent cascades required in development
HOLD_GATE = 100             # independent cascades required in untouched holdout
HORIZON_H = {"15min": 0.25, "1h": 1.0, "4h": 4.0}
PRIMARY_HORIZON = "4h"      # longest preregistered horizon = strictest independence

# provisional-only, NOT a preregistration rule
PROVISIONAL_MIN_PRIOR_BUCKETS = 20

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIQ_CSV = os.path.join(ROOT, "recorder", "data", "liquidations_BTC.csv")


def load_events(path=LIQ_CSV):
    """Clean event frame. Returns (df, integrity dict)."""
    raw = pd.read_csv(path)
    n_raw = len(raw)
    L = raw.copy()
    L["ts_ms"] = pd.to_numeric(L["ts_ms"], errors="coerce")
    L["sz"] = pd.to_numeric(L["sz"], errors="coerce")
    L["bkPx"] = pd.to_numeric(L["bkPx"], errors="coerce")

    integ = {
        "raw_rows": n_raw,
        "nonfinite_ts": int(L["ts_ms"].isna().sum()),
        "nonfinite_sz": int(L["sz"].isna().sum()),
        "nonfinite_px": int(L["bkPx"].isna().sum()),
        "nonpositive_size": int((L["sz"] <= 0).sum()),
        "malformed_rows": int(L[["ts_ms", "sz", "bkPx"]].isna().any(axis=1).sum()),
        "stored_in_time_order": bool(L["ts_ms"].is_monotonic_increasing),
    }
    L = L.dropna(subset=["ts_ms", "sz"])
    L = L[np.isfinite(L["sz"]) & (L["sz"] > 0)].copy()
    L["t"] = pd.to_datetime(L["ts_ms"], unit="ms", utc=True)

    key = (L["ts_ms"].astype("int64").astype(str) + "|" + L["side"].astype(str) + "|"
           + L["posSide"].astype(str) + "|" + L["sz"].astype(str) + "|"
           + L["bkPx"].astype(str))
    integ["duplicates"] = int(len(L) - key.nunique())
    L = L.loc[~key.duplicated()].sort_values("t").reset_index(drop=True)
    integ["usable_events"] = len(L)
    integ["timestamps_in_future"] = int((L["t"] > pd.Timestamp.now(tz="UTC")).sum())
    return L, integ


def _independent(times, hours):
    """Greedy forward pass: keep an event only if >= `hours` after the last kept one."""
    kept, last = [], None
    for t in times:
        if last is None or (t - last).total_seconds() / 3600.0 >= hours:
            kept.append(t)
            last = t
    return kept


def compute_readiness(path=LIQ_CSV):
    """The single authoritative readiness computation. No outcomes are touched."""
    L, integ = load_events(path)
    if not len(L):
        return {"usable_events": 0, "formal_cascades": 0, "formal_dev": 0,
                "formal_holdout": 0, "formal_gate_open": False,
                "formal_scoring_possible": False}

    t0, t1 = L["t"].min(), L["t"].max()
    span_days = (t1 - t0).total_seconds() / 86400.0

    L["bucket"] = L["t"].dt.floor(BUCKET)
    b = L.groupby("bucket").agg(total_size=("sz", "sum"),
                                n_events=("sz", "size")).sort_index().reset_index()

    # ---------------------------------------------------------------- FORMAL
    # A bucket is scorable only when a COMPLETE 30-day capture window precedes it.
    formal_ok = b["bucket"] >= (t0 + pd.Timedelta(days=TRAIL_DAYS))
    n_formal_scorable = int(formal_ok.sum())
    formal_cascades = []
    for i in b.index[formal_ok]:
        t_i = b.loc[i, "bucket"]
        prior = b[(b["bucket"] < t_i)
                  & (b["bucket"] >= t_i - pd.Timedelta(days=TRAIL_DAYS))]
        if not len(prior):
            continue
        if b.loc[i, "total_size"] > float(np.quantile(prior["total_size"], TOP_PCT)):
            formal_cascades.append(t_i)
    formal_indep = _independent(formal_cascades, HORIZON_H[PRIMARY_HORIZON])
    n_formal = len(formal_indep)
    f_hold = int(round(n_formal * HOLDOUT_FRAC))
    f_dev = n_formal - f_hold

    # ------------------------------------------------------------ PROVISIONAL
    # Startup diagnostic only. The 20-bucket floor is ad hoc and NOT preregistered.
    prov_cascades = []
    n_prov_scorable = 0
    for i in range(len(b)):
        t_i = b.loc[i, "bucket"]
        prior = b[(b["bucket"] < t_i)
                  & (b["bucket"] >= t_i - pd.Timedelta(days=TRAIL_DAYS))]
        if len(prior) < PROVISIONAL_MIN_PRIOR_BUCKETS:
            continue
        n_prov_scorable += 1
        if b.loc[i, "total_size"] > float(np.quantile(prior["total_size"], TOP_PCT)):
            prov_cascades.append(t_i)
    prov_indep = {k: len(_independent(prov_cascades, h)) for k, h in HORIZON_H.items()}
    n_prov = prov_indep[PRIMARY_HORIZON]
    p_hold = int(round(n_prov * HOLDOUT_FRAC))
    p_dev = n_prov - p_hold

    out = {
        **integ,
        "first_ts_utc": t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_ts_utc": t1.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "span_days": round(span_days, 3),
        "span_hours": round(span_days * 24, 2),
        "events_per_hour": round(len(L) / max(span_days * 24, 1e-9), 2),
        "nonempty_5min_buckets": len(b),

        # FORMAL - the only numbers that count toward the gate
        "formal_scoring_possible": bool(span_days >= TRAIL_DAYS),
        "days_until_formal_scoring_begins": max(round(TRAIL_DAYS - span_days, 2), 0.0),
        "formal_scorable_buckets": n_formal_scorable,
        "formal_raw_cascades": len(formal_cascades),
        "formal_cascades": n_formal,
        "formal_dev": f_dev,
        "formal_holdout": f_hold,
        "formal_dev_remaining": max(DEV_GATE - f_dev, 0),
        "formal_holdout_remaining": max(HOLD_GATE - f_hold, 0),
        "formal_gate_open": bool(f_dev >= DEV_GATE and f_hold >= HOLD_GATE),

        # PROVISIONAL - diagnostic only, never gate progress
        "provisional_scorable_buckets": n_prov_scorable,
        "provisional_raw_cascades": len(prov_cascades),
        "provisional_independent_15min": prov_indep["15min"],
        "provisional_independent_1h": prov_indep["1h"],
        "provisional_independent_4h": n_prov,
        "provisional_dev": p_dev,
        "provisional_holdout": p_hold,
        "provisional_min_prior_buckets_rule": PROVISIONAL_MIN_PRIOR_BUCKETS,

        "dev_gate": DEV_GATE, "hold_gate": HOLD_GATE,
        "outcomes_examined": False,
    }
    return out


# keys both scripts must agree on exactly
AGREEMENT_KEYS = [
    "formal_cascades", "formal_dev", "formal_holdout", "formal_gate_open",
    "formal_scoring_possible", "provisional_independent_4h",
    "provisional_dev", "provisional_holdout", "dev_gate", "hold_gate",
]
