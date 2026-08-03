"""Data-readiness report, and a quality audit of the new liquidation capture.

The milestone is not "thirty days have passed". It is "there are enough independent
observations to detect an economically useful effect". This computes that for every
hypothesis still open, so the decision to test or keep waiting is made on arithmetic
rather than on the calendar.

It also audits the liquidation feed before anything is built on it: duplicates and
timestamp sanity.

TASK 006A: an earlier version of this file tested whether a "100-event cap" was
truncating cascades. There is no such cap on events - `limit=100` bounds the OUTER
instrument array, and one call returns ~650+ events spanning ~22 hours. That test has
been removed rather than softened, because it produced a false alarm twice.

The H4 cascade count is no longer computed here either. It now comes from
`study/liquidation_readiness.py`, the single authoritative implementation, and an
assertion at the end of this file fails loudly if the two ever disagree again.
"""
import os, csv, math
import numpy as np, pandas as pd
from datetime import datetime, timezone

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")


def mde_binomial(n, base=0.5):
    """Smallest difference in a rate detectable at 2SE with n in each arm."""
    return 2 * math.sqrt(2 * base * (1 - base) / max(n, 1)) * 100


print("=" * 92)
print("1. LIQUIDATION FEED AUDIT")
print("=" * 92)
lp = os.path.join(DATA, "liquidations_BTC.csv")
if not os.path.exists(lp):
    print("  not recording yet")
else:
    L = pd.read_csv(lp)
    L["ts_ms"] = pd.to_numeric(L["ts_ms"], errors="coerce")
    L = L.dropna(subset=["ts_ms"])
    L["t"] = pd.to_datetime(L["ts_ms"], unit="ms", utc=True)
    L["sz"] = pd.to_numeric(L["sz"], errors="coerce")
    L["bkPx"] = pd.to_numeric(L["bkPx"], errors="coerce")

    key = L["ts_ms"].astype(str) + "|" + L["side"].astype(str) + "|" + \
          L["sz"].astype(str) + "|" + L["bkPx"].astype(str)
    dupes = len(L) - key.nunique()
    span_h = (L.t.max() - L.t.min()).total_seconds() / 3600
    print("  events stored        %d" % len(L))
    print("  duplicate keys       %d   %s" % (dupes, "CLEAN" if dupes == 0 else "*** DEDUP BROKEN ***"))
    print("  span                 %s -> %s  (%.1f hours)"
          % (L.t.min().strftime("%m-%d %H:%M"), L.t.max().strftime("%m-%d %H:%M"), span_h))
    print("  rate                 %.1f events/hour" % (len(L) / max(span_h, 1e-9)))
    fut = (L.t > pd.Timestamp.now(tz=timezone.utc)).sum()
    print("  timestamps in future %d   %s" % (fut, "ok" if fut == 0 else "*** CLOCK PROBLEM ***"))
    print("  side split           %s" % L["side"].value_counts().to_dict())
    print("  posSide split        %s" % L["posSide"].value_counts().to_dict())
    print("  size    median %.2f  p95 %.2f  max %.2f" % (L.sz.median(), L.sz.quantile(.95), L.sz.max()))

    # --- TASK 006A: the truncation check is REMOVED, not softened, because it tested a
    # false premise. `limit=100` caps the OUTER instrument array, not the events inside
    # each `details` array. Measured 2026-08-03 by okx_liquidation_endpoint_audit.py: ONE
    # call returned 654 events spanning 22.6 hours. Commit 812ac5f established the same on
    # 2026-07-31 and recorder/derivs_recorder.py documents it. A busy minute is therefore
    # NOT evidence of truncation and the 60s poll must not be shortened on that basis.
    L = L.sort_values("t")
    per_min = L.set_index("t").resample("1min").size()
    busy = per_min[per_min > 0]
    print("\n  MINUTE-LEVEL ACTIVITY (descriptive only - NOT a truncation test)")
    print("    minutes with any event   %d" % len(busy))
    print("    busiest minute           %d events" % (busy.max() if len(busy) else 0))
    print("    a busy minute is NOT evidence of truncation: limit=100 caps the outer")
    print("    instrument array, and one call returns ~650+ events spanning ~22 hours")

    # gaps that look like missed polls rather than quiet markets
    gaps = L["t"].diff().dt.total_seconds().dropna()
    print("    largest gap between events %.1f min" % (gaps.max() / 60 if len(gaps) else 0))

print("\n" + "=" * 92)
print("2. DATA READINESS BY HYPOTHESIS")
print("=" * 92)
print("%-26s %10s %11s %11s  %s"
      % ("hypothesis / dataset", "rows|events", "independent", "MDE", "meaningful when"))
print("-" * 92)


def row(name, rows, indep, mde, when):
    print("%-26s %10s %11s %10.1fpp  %s" % (name, f"{rows:,}", f"{indep:,}", mde, when))


# H4 liquidations
# TASK 006A: this no longer computes its own cascade count. It previously ranked
# INDIVIDUAL EVENTS at the 90th percentile against the WHOLE SAMPLE and ignored the
# holdout arm, giving 14 independent cascades and a "+2,129 h" estimate where the frozen
# preregistration gives 0 formal. That looser number propagated into HANDOFF.md as a
# wrong "~85 days". There is now ONE authoritative implementation and both scripts call
# it; the assertion below fails loudly if they ever diverge again.
if os.path.exists(lp):
    from liquidation_readiness import compute_readiness, AGREEMENT_KEYS
    R = compute_readiness()
    row("H4 liquidation cascade (FORMAL)", R["usable_events"], R["formal_cascades"],
        mde_binomial(max(R["formal_cascades"], 1)),
        "gate %d dev + %d holdout; formal scoring starts in ~%.1f days"
        % (R["dev_gate"], R["hold_gate"], R["days_until_formal_scoring_begins"]))
    row("  (provisional startup only)", R["usable_events"],
        R["provisional_independent_4h"],
        mde_binomial(max(R["provisional_independent_4h"], 1)),
        "NOT gate progress - partial trailing window, no ETA derivable")

# H5 open interest
oi = os.path.join(DATA, "derivs_BTC_hourly.csv")
if os.path.exists(oi):
    n = sum(1 for _ in open(oi, encoding="utf-8")) - 1
    row("H5 open-interest change", n, n // 4, mde_binomial(max(n // 4, 1)),
        "OKX caps at 30 days; live recorder must extend it")

# order book / microstructure
import glob
mrows = sum(sum(1 for _ in open(f, encoding="utf-8", errors="replace")) - 1
            for f in glob.glob(os.path.join(DATA, "micro_*.csv")))
row("H4b order-book imbalance", mrows, mrows // 1500, mde_binomial(max(mrows // 1500, 1)),
    "~1500 samples per independent 1h window")

# already-sufficient reference datasets
for nm, fn, per in (("funding (BTC, cached)", "hist_BTC_PERPETUAL.csv", 4),
                    ("funding (ETH, cached)", "hist_ETH_PERPETUAL.csv", 4)):
    p = os.path.join(DATA, fn)
    if os.path.exists(p):
        n = sum(1 for _ in open(p, encoding="utf-8")) - 1
        row(nm, n, n // per, mde_binomial(n // per), "already sufficient")

print("""
MDE is the smallest change in a rate this sample could resolve at two standard errors.
Compare it with the effect actually worth having: for a stop-out or continuation rate
that is roughly 2-3 percentage points. A hypothesis whose MDE is far above that cannot
be tested yet regardless of how many rows it has, and running it early only produces a
null that means nothing - the mistake already made once with the crowding branch.""")

# ---------------------------------------------------------------------------
# TASK 006A - deterministic agreement assertion.
# The repository briefly carried two disagreeing liquidation-readiness numbers and the
# looser one reached HANDOFF.md as a wrong "~85 days". Both scripts now read the same
# implementation, and this fails loudly rather than silently drifting apart again.
if os.path.exists(lp):
    import csv as _csv
    from liquidation_readiness import compute_readiness as _cr, AGREEMENT_KEYS as _AK
    _mine = _cr()
    _audit_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "results", "liquidation_readiness_audit.csv")
    if os.path.exists(_audit_csv):
        with open(_audit_csv, encoding="utf-8") as _f:
            _saved = list(_csv.DictReader(_f))[-1]
        _bad = []
        for _k in _AK:
            _a, _b = str(_mine[_k]), str(_saved.get(_k))
            if _a != _b:
                _bad.append("%s: data_readiness=%s audit=%s" % (_k, _a, _b))
        assert not _bad, ("TASK 006A ASSERTION FAILED - the two readiness "
                          "implementations disagree:\n  " + "\n  ".join(_bad))
        print("\n[OK] readiness agreement assertion: data_readiness.py and "
              "liquidation_readiness_audit.py agree on all %d shared keys" % len(_AK))
    else:
        print("\n[--] readiness agreement assertion skipped: run "
              "study/liquidation_readiness_audit.py first")
