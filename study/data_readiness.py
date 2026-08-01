"""Data-readiness report, and a quality audit of the new liquidation capture.

The milestone is not "thirty days have passed". It is "there are enough independent
observations to detect an economically useful effect". This computes that for every
hypothesis still open, so the decision to test or keep waiting is made on arithmetic
rather than on the calendar.

It also audits the liquidation feed before anything is built on it: duplicates,
timestamp sanity, and - the one that actually matters - whether the 100-event cap is
truncating cascades. Liquidations are only interesting during cascades, so a feed that
silently drops the biggest ones would be worse than no feed at all.
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

    # --- the cap question: does any 60s window hold ~100 events? ---
    L = L.sort_values("t")
    per_min = L.set_index("t").resample("1min").size()
    busy = per_min[per_min > 0]
    print("\n  CASCADE TRUNCATION CHECK (endpoint returns at most 100 events per poll)")
    print("    minutes with any event   %d" % len(busy))
    print("    busiest minute           %d events" % (busy.max() if len(busy) else 0))
    print("    minutes at/over 90       %d" % int((per_min >= 90).sum()))
    if len(busy) and busy.max() >= 90:
        print("    *** AT RISK - a poll may be truncating; consider 30s polling ***")
    else:
        print("    headroom is fine at the current 60s poll")

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
if os.path.exists(lp):
    L2 = pd.read_csv(lp)
    n_ev = len(L2)
    # independent = distinct 4h windows containing at least one sizeable event
    L2["t"] = pd.to_datetime(pd.to_numeric(L2["ts_ms"], errors="coerce"), unit="ms", utc=True)
    L2["sz"] = pd.to_numeric(L2["sz"], errors="coerce")
    big = L2[L2.sz >= L2.sz.quantile(0.90)]
    indep = big.set_index("t").resample("4h").size().gt(0).sum() if len(big) else 0
    hrs = (L2.t.max() - L2.t.min()).total_seconds() / 3600 if len(L2) else 0
    rate = indep / max(hrs, 1e-9)
    need = 400
    eta = (need - indep) / max(rate, 1e-9)
    row("H4 liquidation cascade", n_ev, indep, mde_binomial(max(indep, 1)),
        "need ~%d windows; +%.0f h at current rate" % (need, max(eta, 0)))

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
