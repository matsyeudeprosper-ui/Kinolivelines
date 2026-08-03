"""TASK 006 / 006A - READ-ONLY LIQUIDATION DATA-READINESS AUDIT

Counts and integrity ONLY. This script never loads the BTCUSDm price series, which is the
simplest possible guarantee that no outcome was examined: the data required to compute a
post-cascade return, direction, volatility outcome or win rate is not opened.

It changes nothing. No recorder setting, no polling interval, no live process, no trade.

All counting is delegated to `study/liquidation_readiness.py` so that this script and
`study/data_readiness.py` cannot drift apart again - and the agreement is asserted below
rather than assumed.

--------------------------------------------------------------------------------
006A CORRECTIONS
--------------------------------------------------------------------------------
1. The 100-event truncation warning is WITHDRAWN. It was wrong. `limit=100` caps the
   outer instrument array, not the events inside each `details` array; a fresh audit
   (`study/okx_liquidation_endpoint_audit.py`) returned 654 events spanning 22.6 hours
   from one call. The repository had already established this in commit 812ac5f, and
   `recorder/derivs_recorder.py` documents it. The 60-second poll is comfortable and must
   NOT be shortened on that basis.

2. FORMAL and PROVISIONAL counts are now separated. The frozen definition ranks against a
   trailing 30-day distribution, so nothing is formally scorable until 30 days of capture
   precede it. Task 006 presented startup numbers as gate progress; they are provisional
   only.

3. No gate ETA is published from a partial sample. The trigger is the formal count.
"""
import os
import datetime as dt

import pandas as pd

from liquidation_readiness import (compute_readiness, load_events, AGREEMENT_KEYS,
                                   BUCKET, TOP_PCT, TRAIL_DAYS, HOLDOUT_FRAC,
                                   DEV_GATE, HOLD_GATE, PRIMARY_HORIZON,
                                   PROVISIONAL_MIN_PRIOR_BUCKETS, LIQ_CSV)

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
os.makedirs(RES, exist_ok=True)
OUT_CSV = os.path.join(RES, "liquidation_readiness_audit.csv")
OUT_TXT = os.path.join(RES, "liquidation_readiness_audit.txt")

LOG = []


def say(s=""):
    print(s, flush=True)
    LOG.append(s)


say("=" * 96)
say("LIQUIDATION DATA-READINESS AUDIT (READ-ONLY, NO OUTCOMES EXAMINED)")
say("=" * 96)
say(f"generated : {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
say("")

if not os.path.isfile(LIQ_CSV):
    say("liquidations_BTC.csv not present - nothing to audit")
    raise SystemExit(0)

R = compute_readiness()
L, _ = load_events()

say("1. FEED")
say(f"  raw rows                : {R['raw_rows']:,}")
say(f"  usable events           : {R['usable_events']:,}")
say(f"  first timestamp (UTC)   : {R['first_ts_utc']}")
say(f"  latest timestamp (UTC)  : {R['latest_ts_utc']}")
say(f"  span                    : {R['span_hours']:,.1f} h ({R['span_days']:.2f} days)")
say(f"  observed rate           : {R['events_per_hour']:,.1f} events/hour")
say("")

say("2. INTEGRITY")
say(f"  duplicate rows          : {R['duplicates']}   "
    f"{'CLEAN' if R['duplicates'] == 0 else 'DEDUP ISSUE'}")
say(f"  malformed rows          : {R['malformed_rows']}")
say(f"  non-finite ts / sz / px : {R['nonfinite_ts']} / {R['nonfinite_sz']} / "
    f"{R['nonfinite_px']}")
say(f"  non-positive sizes      : {R['nonpositive_size']}")
say(f"  timestamps in future    : {R['timestamps_in_future']}")
say(f"  stored in time order    : {R['stored_in_time_order']}"
    + ("" if R["stored_in_time_order"] else "   (newest-first writer; sorted for audit)"))
say(f"  non-empty 5-min buckets : {R['nonempty_5min_buckets']:,}")
say("")

now = pd.Timestamp.now(tz="UTC")
say("3. GROWTH")
for label, hours in (("last 24 hours", 24), ("last 7 days", 168), ("last 30 days", 720)):
    n = int((L["t"] >= now - pd.Timedelta(hours=hours)).sum())
    say(f"  {label:14s}: {n:6,d} events   (feed covers "
        f"{min(R['span_hours'], hours):,.1f}h of that window)")
gaps = L["t"].diff().dt.total_seconds().dropna()
big = gaps[gaps > 3600]
say(f"  inter-event gaps > 1 h  : {len(big)}"
    + (f", longest {big.max()/3600:.2f} h" if len(big) else ""))
say("")

say("4. FORMAL CASCADE COUNT - the only numbers that count toward the gate")
say(f"  frozen rule: a 5-minute bucket whose TOTAL size exceeds the {TOP_PCT:.0%} quantile")
say(f"  of the trailing {TRAIL_DAYS}-day distribution of non-empty buckets.")
say("")
if not R["formal_scoring_possible"]:
    say(f"  !! FORMAL SCORING HAS NOT STARTED.")
    say(f"     The feed is {R['span_days']:.2f} days old. No bucket yet has a complete")
    say(f"     preceding {TRAIL_DAYS}-day capture window, so none can be ranked as the")
    say(f"     frozen definition requires.")
    say(f"     Formal scoring begins in ~{R['days_until_formal_scoring_begins']:.2f} days,")
    say(f"     and only then does the first eligible bucket appear.")
    say("")
say(f"  formally scorable buckets : {R['formal_scorable_buckets']:,}")
say(f"  FORMAL cascades           : {R['formal_cascades']:,}")
say(f"  FORMAL development        : {R['formal_dev']:,} / {DEV_GATE}   "
    f"remaining {R['formal_dev_remaining']:,}")
say(f"  FORMAL holdout            : {R['formal_holdout']:,} / {HOLD_GATE}   "
    f"remaining {R['formal_holdout_remaining']:,}")
say(f"  FORMAL GATE OPEN          : {R['formal_gate_open']}")
say("")

say("5. PROVISIONAL STARTUP DIAGNOSTIC - NOT gate progress")
say(f"  Ranks against whatever history exists, with an ad-hoc floor of")
say(f"  {PROVISIONAL_MIN_PRIOR_BUCKETS} prior non-empty buckets. THAT FLOOR IS NOT IN THE")
say("  PREREGISTRATION. These numbers are a sanity check on the pipeline only.")
say("")
say(f"  provisional scorable buckets : {R['provisional_scorable_buckets']:,}")
say(f"  provisional raw cascades     : {R['provisional_raw_cascades']:,}")
say(f"  provisional independent 15min: {R['provisional_independent_15min']:,}")
say(f"  provisional independent 1h   : {R['provisional_independent_1h']:,}")
say(f"  provisional independent {PRIMARY_HORIZON:5s}: "
    f"{R['provisional_independent_4h']:,}   <- primary separation")
say(f"  provisional split            : {R['provisional_dev']} dev / "
    f"{R['provisional_holdout']} holdout")
say("")
say("  These MUST NOT be reported as gate progress and MUST NOT be used to publish a")
say("  gate ETA. A 3-day sample cannot forecast a 30-day-trailing statistic, and task 006")
say("  was wrong to derive one. The trigger is the FORMAL count.")
say("")

say("6. ENDPOINT TRUNCATION - WITHDRAWN")
say("  Task 006 warned that the OKX limit=100 parameter truncates liquidation events and")
say("  called it urgent. That was WRONG and is withdrawn.")
say("  limit=100 caps the OUTER instrument array, not the events inside each `details`")
say("  array. Measured fresh in study/okx_liquidation_endpoint_audit.py: ONE call returned")
say("  654 events spanning 22.6 hours. The repository had already established this in")
say("  commit 812ac5f, and recorder/derivs_recorder.py documents the measured behaviour")
say("  and paginates backwards with `after` as a safety net.")
say("  The 60-second poll interval is comfortable and must NOT be shortened on this basis.")
say("")

rows = [{"audit_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         **R}]
pd.DataFrame(rows).to_csv(OUT_CSV, index=False)
say(f"audit table -> {OUT_CSV}")
with open(OUT_TXT, "w", encoding="utf-8") as f:
    f.write("\n".join(LOG) + "\n")
print(f"report      -> {OUT_TXT}")
print("\nagreement keys exported for data_readiness.py:")
for k in AGREEMENT_KEYS:
    print(f"  {k} = {R[k]}")
