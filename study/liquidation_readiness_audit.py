"""TASK 006 - READ-ONLY LIQUIDATION DATA-READINESS AUDIT

Counts and integrity ONLY. This script deliberately never touches a price outcome.

It does NOT compute post-cascade returns, direction, volatility outcomes, profitability,
win rates, or any other quantity that could answer H4a/H4b/H4c/H4d. It never opens the
BTCUSDm price series at all, which is the simplest possible guarantee that no outcome was
examined: the data needed to compute one is not loaded.

It changes nothing. No file is written except this audit's own CSV/report, no recorder
setting is touched, no process is started or stopped, and the live bot is not contacted.

--------------------------------------------------------------------------------
THE FROZEN DEFINITION, APPLIED AS WRITTEN
--------------------------------------------------------------------------------
From PREREGISTRATION_liquidations.md, unchanged:

  event      one row of liquidations_BTC.csv (OKX BTC-USDT swap)
  cascade    a 5-minute bucket whose TOTAL liquidated size sits in the top 5% of all
             non-empty 5-minute buckets, ranked against a TRAILING 30-DAY distribution
  gate       >= 400 independent cascades in development AND >= 100 in untouched holdout
  holdout    the final 25% of the data, chronologically
  independence  cascades separated by at least one horizon length

Two implementation notes, both conservative and both recorded rather than chosen quietly:

1. The longest preregistered horizon is 4 hours, so independence is enforced at 4h. That
   is the strictest reading - a set independent at 4h is independent at 15m and 1h too.
   The 1h and 15m counts are reported alongside for reference only.

2. The feed is younger than 30 days, so no bucket yet has a full trailing-30-day window.
   The trailing rank is therefore computed against whatever history precedes each bucket,
   which is the same rule with a shorter effective window. Every count below is flagged
   PROVISIONAL until the feed exceeds 30 days, because the 5% threshold is being set by a
   partial distribution.
"""
import os
import json
import datetime as dt

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "recorder", "data")
RES = os.path.join(HERE, "results")
os.makedirs(RES, exist_ok=True)

LIQ = os.path.join(DATA, "liquidations_BTC.csv")
OUT_CSV = os.path.join(RES, "liquidation_readiness_audit.csv")
OUT_TXT = os.path.join(RES, "liquidation_readiness_audit.txt")

BUCKET = "5min"
TOP_PCT = 0.95            # top 5%
TRAIL_DAYS = 30
HOLDOUT_FRAC = 0.25
DEV_GATE, HOLD_GATE = 400, 100
HORIZON_H = {"15min": 0.25, "1h": 1.0, "4h": 4.0}
PRIMARY_HORIZON = "4h"

LOG = []


def say(s=""):
    print(s, flush=True)
    LOG.append(s)


say("=" * 96)
say("TASK 006 - LIQUIDATION DATA-READINESS AUDIT (READ-ONLY, NO OUTCOMES)")
say("=" * 96)
say(f"generated : {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
say("")

if not os.path.isfile(LIQ):
    say("liquidations_BTC.csv not present - nothing to audit")
    raise SystemExit(0)

raw = pd.read_csv(LIQ)
n_raw = len(raw)

# ---------------------------------------------------------------- integrity
L = raw.copy()
L["ts_ms"] = pd.to_numeric(L["ts_ms"], errors="coerce")
L["sz"] = pd.to_numeric(L["sz"], errors="coerce")
L["bkPx"] = pd.to_numeric(L["bkPx"], errors="coerce")

bad_ts = int(L["ts_ms"].isna().sum())
bad_sz = int((~np.isfinite(L["sz"].fillna(np.nan))).sum())
bad_px = int((~np.isfinite(L["bkPx"].fillna(np.nan))).sum())
nonpos_sz = int((L["sz"] <= 0).sum())
malformed = int(L[["ts_ms", "sz", "bkPx"]].isna().any(axis=1).sum())

L = L.dropna(subset=["ts_ms", "sz"])
L = L[np.isfinite(L["sz"]) & (L["sz"] > 0)]
L["t"] = pd.to_datetime(L["ts_ms"], unit="ms", utc=True)

key = (L["ts_ms"].astype("int64").astype(str) + "|" + L["side"].astype(str) + "|"
       + L["posSide"].astype(str) + "|" + L["sz"].astype(str) + "|"
       + L["bkPx"].astype(str))
n_dupe = int(len(L) - key.nunique())
L = L.loc[~key.duplicated()].copy()

ordered_as_stored = bool(L["ts_ms"].is_monotonic_increasing)
L = L.sort_values("t").reset_index(drop=True)

now = pd.Timestamp.now(tz="UTC")
t0, t1 = L["t"].min(), L["t"].max()
span_h = (t1 - t0).total_seconds() / 3600.0
future = int((L["t"] > now).sum())

say("1. RAW FEED")
say(f"  file                    : recorder/data/liquidations_BTC.csv")
say(f"  raw rows (incl. header) : {n_raw:,} data rows")
say(f"  first timestamp (UTC)   : {t0:%Y-%m-%d %H:%M:%S}")
say(f"  latest timestamp (UTC)  : {t1:%Y-%m-%d %H:%M:%S}")
say(f"  span                    : {span_h:,.1f} hours ({span_h/24:.2f} days)")
say(f"  audit run at (UTC)      : {now:%Y-%m-%d %H:%M:%S}")
say(f"  observed rate           : {len(L)/max(span_h,1e-9):,.1f} events/hour")
say("")

say("2. INTEGRITY")
say(f"  duplicate rows removed  : {n_dupe}   {'CLEAN' if n_dupe == 0 else 'DEDUP ISSUE'}")
say(f"  malformed rows          : {malformed}  (unparseable ts_ms / sz / bkPx)")
say(f"    non-finite / missing ts_ms : {bad_ts}")
say(f"    non-finite / missing sz    : {bad_sz}")
say(f"    non-finite / missing bkPx  : {bad_px}")
say(f"    non-positive size          : {nonpos_sz}")
say(f"  timestamps in the future: {future}   {'ok' if future == 0 else 'CLOCK PROBLEM'}")
say(f"  stored in time order    : {ordered_as_stored}"
    + ("" if ordered_as_stored else "   (newest-first writer; sorted for this audit)"))
say(f"  usable events after clean: {len(L):,}")
say("")

say("3. GROWTH")
for label, hours in (("last 24 hours", 24), ("last 7 days", 24 * 7), ("last 30 days", 24 * 30)):
    cut = now - pd.Timedelta(hours=hours)
    n = int((L["t"] >= cut).sum())
    covered = min(span_h, hours)
    say(f"  {label:14s}: {n:6,d} events   (feed covers {covered:,.1f}h of that window)")
say("")

# ---------------------------------------------------------------- gaps
L["bucket"] = L["t"].dt.floor(BUCKET)
buckets = L.groupby("bucket").agg(
    total_size=("sz", "sum"), n_events=("sz", "size")).sort_index()
n_buckets_nonempty = len(buckets)

full_idx = pd.date_range(buckets.index.min(), buckets.index.max(), freq=BUCKET)
empty_buckets = int(len(full_idx) - n_buckets_nonempty)

gaps = L["t"].diff().dt.total_seconds().dropna()
big_gaps = gaps[gaps > 3600]
say("4. COVERAGE AND GAPS")
say(f"  non-empty 5-minute buckets : {n_buckets_nonempty:,}")
say(f"  5-minute slots in span     : {len(full_idx):,}")
say(f"  empty 5-minute slots       : {empty_buckets:,} "
    f"({empty_buckets/max(len(full_idx),1)*100:.1f}% - quiet market, not necessarily loss)")
say(f"  inter-event gaps > 1 hour  : {len(big_gaps)}")
if len(big_gaps):
    say(f"    longest gap              : {big_gaps.max()/3600:.2f} hours")
    for i in big_gaps.nlargest(3).index:
        say(f"      {L['t'].iloc[i-1]:%Y-%m-%d %H:%M} -> {L['t'].iloc[i]:%Y-%m-%d %H:%M}"
            f"  ({gaps[i]/3600:.2f} h)")
say("")

# ---------------------------------------------------------------- cascades
# Frozen rule: top 5% of NON-EMPTY buckets by total size, ranked against a trailing
# 30-day distribution of non-empty buckets only. No outcome is consulted.
b = buckets.reset_index()
is_cascade = np.zeros(len(b), dtype=bool)
thresh_used = np.full(len(b), np.nan)
for i in range(len(b)):
    t_i = b.loc[i, "bucket"]
    prior = b[(b["bucket"] < t_i) & (b["bucket"] >= t_i - pd.Timedelta(days=TRAIL_DAYS))]
    if len(prior) < 20:                 # too few to define a 95th percentile
        continue
    thr = float(np.quantile(prior["total_size"], TOP_PCT))
    thresh_used[i] = thr
    is_cascade[i] = b.loc[i, "total_size"] > thr
b["is_cascade"] = is_cascade
b["threshold_used"] = thresh_used
cand = b[b["is_cascade"]].copy()

say("5. CASCADE CANDIDATES (frozen trailing-30-day definition, no outcomes examined)")
say(f"  definition        : 5-min bucket total size > 95th percentile of the trailing")
say(f"                      {TRAIL_DAYS}-day distribution of NON-EMPTY buckets")
say(f"  buckets scorable  : {int(np.isfinite(thresh_used).sum()):,} "
    f"(the rest lack enough trailing history to rank)")
say(f"  RAW cascade buckets: {len(cand):,}")
if len(cand):
    say(f"  first / latest    : {cand['bucket'].min():%Y-%m-%d %H:%M} -> "
        f"{cand['bucket'].max():%Y-%m-%d %H:%M}")
say("")


def independent(times, hours):
    """Greedy forward pass: keep an event only if >= `hours` after the last kept one."""
    kept, last = [], None
    for t in times:
        if last is None or (t - last).total_seconds() / 3600.0 >= hours:
            kept.append(t)
            last = t
    return kept


say("6. INDEPENDENCE AND THE GATE")
indep = {}
for name, h in HORIZON_H.items():
    indep[name] = independent(list(cand["bucket"]), h)
    tag = "  <- PRIMARY (longest horizon, strictest)" if name == PRIMARY_HORIZON else ""
    say(f"  independent at {name:6s} ({h:>4.2f}h separation): {len(indep[name]):5,d}{tag}")
say("")

prim = indep[PRIMARY_HORIZON]
n_prim = len(prim)
n_hold = int(round(n_prim * HOLDOUT_FRAC))
n_dev = n_prim - n_hold
say(f"  chronological split, final {HOLDOUT_FRAC:.0%} reserved and untouched:")
say(f"    development candidates : {n_dev:,}")
say(f"    holdout  (reserved)    : {n_hold:,}")
say("")
say(f"  GATE: >= {DEV_GATE} development AND >= {HOLD_GATE} holdout")
say(f"    development  {n_dev:,} / {DEV_GATE}   remaining {max(DEV_GATE - n_dev, 0):,}")
say(f"    holdout      {n_hold:,} / {HOLD_GATE}   remaining {max(HOLD_GATE - n_hold, 0):,}")
gate_open = (n_dev >= DEV_GATE) and (n_hold >= HOLD_GATE)
say(f"    GATE OPEN    : {gate_open}")
say("")

# rough pace, explicitly not a promise
rate_per_day = n_prim / max(span_h / 24.0, 1e-9)
need_total = max(DEV_GATE / (1 - HOLDOUT_FRAC), HOLD_GATE / HOLDOUT_FRAC)
remaining = max(need_total - n_prim, 0)
say("  ROUGH pace estimate - NOT a deadline. The trigger is the COUNT, never a date.")
say(f"    independent cascades so far : {n_prim:,} over {span_h/24:.2f} days")
say(f"    recent pace                 : {rate_per_day:.2f} independent cascades/day")
if rate_per_day > 0:
    say(f"    total needed to satisfy both arms: ~{need_total:,.0f}")
    say(f"    at the CURRENT pace that is roughly {remaining/rate_per_day:,.0f} more days")
say("    Pace is not stable - liquidation activity is regime-dependent and the trailing")
say("    threshold moves with it, so this figure will change. Do not convert it to a date.")
say("")

if span_h / 24.0 < TRAIL_DAYS:
    say(f"  !! PROVISIONAL: the feed is {span_h/24:.2f} days old, shorter than the "
        f"{TRAIL_DAYS}-day trailing window.")
    say("     No bucket yet has a full trailing distribution, so the 5% threshold is being")
    say("     set by partial history. Every cascade count above is provisional and will be")
    say("     recomputed once the feed exceeds 30 days. This does not affect the gate rule.")
    say("")

# ---------------------------------------------------------------- outputs
rows = [{
    "audit_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "raw_rows": n_raw, "usable_events": len(L),
    "first_ts_utc": t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "latest_ts_utc": t1.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "span_hours": round(span_h, 2), "span_days": round(span_h / 24, 3),
    "events_per_hour": round(len(L) / max(span_h, 1e-9), 2),
    "duplicates_removed": n_dupe, "malformed_rows": malformed,
    "nonfinite_ts": bad_ts, "nonfinite_sz": bad_sz, "nonfinite_px": bad_px,
    "nonpositive_size": nonpos_sz, "timestamps_in_future": future,
    "stored_in_time_order": ordered_as_stored,
    "nonempty_5min_buckets": n_buckets_nonempty,
    "empty_5min_slots": empty_buckets,
    "gaps_over_1h": len(big_gaps),
    "longest_gap_hours": round(float(big_gaps.max()) / 3600, 2) if len(big_gaps) else 0.0,
    "raw_cascade_buckets": len(cand),
    "independent_15min": len(indep["15min"]), "independent_1h": len(indep["1h"]),
    "independent_4h_primary": n_prim,
    "development_candidates": n_dev, "holdout_reserved": n_hold,
    "dev_gate": DEV_GATE, "hold_gate": HOLD_GATE,
    "dev_remaining": max(DEV_GATE - n_dev, 0),
    "hold_remaining": max(HOLD_GATE - n_hold, 0),
    "gate_open": gate_open,
    "provisional_short_trailing_window": bool(span_h / 24.0 < TRAIL_DAYS),
    "outcomes_examined": False,
}]
pd.DataFrame(rows).to_csv(OUT_CSV, index=False)
say(f"audit table -> {OUT_CSV}")
with open(OUT_TXT, "w", encoding="utf-8") as f:
    f.write("\n".join(LOG) + "\n")
print(f"report      -> {OUT_TXT}")
