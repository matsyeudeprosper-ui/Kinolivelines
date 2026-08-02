"""Preliminary test of the two recorded datasets, with honest power for each.

WHAT IS AND IS NOT TESTABLE YET

  ORDER-BOOK IMBALANCE - testable. 41,146 paired samples at ~2.3s give roughly 1,500
  independent 60-second windows, enough to resolve a few percentage points. This is the
  classic microstructure signal: when resting size is lopsided, the thin side is easier
  to push through, so price should drift that way over seconds to minutes.

  LIQUIDATIONS - NOT testable, and the preregistration says so. 2,091 events sound like
  plenty but they cluster into 184 distinct minutes, and the frozen gate is 400
  independent cascades in development plus 100 in holdout. A run now could only detect
  an enormous effect, and a null would mean nothing. It is reported here descriptively -
  what the flow looks like - with no outcome test attached, so nothing is spent from the
  preregistered hypothesis.

THE COST BAR, which is what usually decides it: any directional signal at this horizon
must beat a $10 spread. Over 60 seconds BTCUSDm typically travels a fraction of that, so
even a genuine and statistically clean signal is likely unprofitable. Effect sizes are
therefore reported in DOLLARS next to the spread, not only as correlations.
"""
import os, glob, math
import numpy as np, pandas as pd

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "recorder", "data")
SPREAD = 10.0
HORIZONS = [("30s", 30), ("60s", 60), ("120s", 120), ("300s", 300)]

frames = []
for f in sorted(glob.glob(os.path.join(D, "micro_*.csv"))):
    try:
        frames.append(pd.read_csv(f))
    except Exception:
        pass
m = pd.concat(frames, ignore_index=True)
m["t"] = pd.to_datetime(m["t_local"], format="mixed", utc=True)
for c in ("mt5_bid", "mt5_ask", "okx_bid", "okx_ask", "bid_sz5", "ask_sz5", "bid_sz1", "ask_sz1"):
    m[c] = pd.to_numeric(m[c], errors="coerce")
m = m.dropna(subset=["mt5_bid", "mt5_ask", "okx_bid", "okx_ask", "bid_sz5", "ask_sz5"])
m = m.sort_values("t").reset_index(drop=True)

m["ex_mid"] = (m.mt5_bid + m.mt5_ask) / 2
m["ok_mid"] = (m.okx_bid + m.okx_ask) / 2
# order-book imbalance: +1 = all size on the bid, -1 = all on the ask
m["imb5"] = (m.bid_sz5 - m.ask_sz5) / (m.bid_sz5 + m.ask_sz5)
m["imb1"] = (m.bid_sz1 - m.ask_sz1) / (m.bid_sz1 + m.ask_sz1)

secs = (m["t"] - m["t"].iloc[0]).dt.total_seconds().to_numpy()
print("ORDER-BOOK IMBALANCE  (OKX top-5 depth  ->  next move)")
print("%s paired samples, %s to %s, median gap %.1fs"
      % (f"{len(m):,}", m.t.min().strftime("%m-%d %H:%M"), m.t.max().strftime("%m-%d %H:%M"),
         np.median(np.diff(secs))))
print("imbalance: mean %+.3f  sd %.3f\n" % (m.imb5.mean(), m.imb5.std()))

for pxcol, pxname in (("ex_mid", "Exness mid (what we trade)"),
                      ("ok_mid", "OKX mid (same venue as the book)")):
    px = m[pxcol].to_numpy(float)
    print("=" * 88)
    print("target: %s" % pxname)
    print("  %-6s %8s %10s %10s %9s %10s   %s"
          % ("horiz", "n", "top20% up", "bot20% up", "spread", "$ move", "verdict"))
    print("  " + "-" * 80)
    for hname, hsec in HORIZONS:
        # NON-OVERLAPPING: step forward by the horizon each time
        idx, last = [], -1e9
        for i in range(len(secs)):
            if secs[i] - last >= hsec:
                j = np.searchsorted(secs, secs[i] + hsec)
                if j < len(secs):
                    idx.append((i, j)); last = secs[i]
        if len(idx) < 100:
            print("  %-6s %8d   too few" % (hname, len(idx))); continue
        a = np.array([i for i, _ in idx]); b = np.array([j for _, j in idx])
        imb = m["imb5"].to_numpy()[a]
        fwd = px[b] - px[a]
        hi = imb >= np.quantile(imb, 0.8)
        lo = imb <= np.quantile(imb, 0.2)
        p_hi = (fwd[hi] > 0).mean(); p_lo = (fwd[lo] > 0).mean()
        n_hi, n_lo = hi.sum(), lo.sum()
        se2 = 2*math.sqrt(p_hi*(1-p_hi)/n_hi + p_lo*(1-p_lo)/n_lo)
        gap = p_hi - p_lo
        move = fwd[hi].mean() - fwd[lo].mean()
        sig = abs(gap) > se2
        pays = abs(move) > SPREAD
        verdict = ("REAL and beats spread" if sig and pays else
                   "real but under the $%.0f spread" % SPREAD if sig else "no signal")
        print("  %-6s %8d %9.1f%% %9.1f%% %8.1f%% %9.2f   %s"
              % (hname, len(idx), 100*p_hi, 100*p_lo, 100*se2, move, verdict))

print("\n" + "=" * 88)
print("LIQUIDATIONS - DESCRIPTIVE ONLY, no outcome test (frozen gate not reached)")
L = pd.read_csv(os.path.join(D, "liquidations_BTC.csv"))
L["t"] = pd.to_datetime(pd.to_numeric(L["ts_ms"], errors="coerce"), unit="ms", utc=True)
L["sz"] = pd.to_numeric(L["sz"], errors="coerce")
L = L.dropna(subset=["t", "sz"])
per_min = L.set_index("t").resample("1min").agg(n=("sz", "size"), vol=("sz", "sum"))
busy = per_min[per_min.n > 0]
span_h = (L.t.max() - L.t.min()).total_seconds()/3600
print("  %d events over %.1f h (%.1f/h), in %d distinct minutes"
      % (len(L), span_h, len(L)/span_h, len(busy)))
print("  side split: %s" % L["posSide"].value_counts().to_dict())
print("  size: median %.2f  p90 %.2f  p99 %.2f  max %.2f"
      % (L.sz.median(), L.sz.quantile(.9), L.sz.quantile(.99), L.sz.max()))
print("  busiest minute: %d events, %.1f contracts" % (busy.n.max(), busy.vol.max()))
big = busy[busy.vol >= busy.vol.quantile(0.95)]
print("  minutes in the top 5%% by volume: %d  <-- these are the 'cascades'" % len(big))
print("  at this rate the 400-cascade gate arrives in roughly %.0f days"
      % (400 / max(len(big) / (span_h/24), 1e-9)))
print("""
  No outcome test is run on these. The preregistration fixed the gate at 400 independent
  cascades precisely so an underpowered null could not be mistaken for a finding - the
  error already made once with the crowding branch.""")
