"""Does the Exness quote LAG the real exchange, and by how long?

Exness quote BTCUSDm themselves - the price is derived from real markets rather
than being one. If their feed trails, that is exploitable without predicting
anything: you would already know where price is going because it has already
happened somewhere else.

METHOD - cross-correlation of RETURNS at a range of lags.
Never compare levels. The raw gap between the two feeds averages about -62 points
and that is almost entirely the USDT basis (BTC-USDT vs BTC-USD), not a lag. It
would produce an enormous fake signal. Only changes carry the timing information.

  corr( okx_return[t-k] , mt5_return[t] )  for k = -5 .. +5 polls

  peak at POSITIVE k  -> OKX moves first, MT5 follows: a real lag, exploitable
  peak at k = 0       -> both move together, nothing to trade
  peak at NEGATIVE k  -> MT5 leads, which would mean the broker front-runs the
                         exchange; implausible, and would point at a bug here

A CAUTION THIS SCRIPT ENFORCES: the two feeds are sampled by one loop about 350ms
apart, so sub-second timing is not resolvable. Only lags of a poll or more mean
anything, and the poll is 2 seconds.

Also reported: whether MT5's extra movement is real. On the first 29 minutes MT5
moved on 99% of polls against OKX's 17%, which may simply be broker quote jitter
around a true value. Jitter is noise, not information, and inflates correlation
denominators - so the size of each feed's typical move is printed too.
"""
import glob
import os
import sys

import numpy as np
import pandas as pd

DATA = r"C:\Projects\KinoliveLines\recorder\data"
files = sorted(glob.glob(os.path.join(DATA, "micro_BTCUSDm_*.csv")))
if not files:
    sys.exit("no microstructure files yet")

d = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
d = d.dropna(subset=["okx_bid", "okx_ask", "mt5_bid", "mt5_ask"]).reset_index(drop=True)
d["t"] = pd.to_datetime(d["t_local"])
d = d.sort_values("t").reset_index(drop=True)

d["mt5_mid"] = (d.mt5_bid + d.mt5_ask) / 2
d["okx_mid"] = (d.okx_bid + d.okx_ask) / 2
span_min = (d.t.max() - d.t.min()).total_seconds() / 60

print("BROKER LAG - Exness BTCUSDm vs OKX BTC-USDT")
print("%s rows over %.0f minutes (%.1f hours)\n" % (f"{len(d):,}", span_min, span_min / 60))

# --- how much of each feed's movement is real? -----------------------------
for name, col in (("MT5 ", "mt5_mid"), ("OKX ", "okx_mid")):
    diff = d[col].diff().dropna()
    moved = (diff != 0).mean() * 100
    typical = diff[diff != 0].abs().median() if (diff != 0).any() else 0
    print("%s moved on %5.1f%% of polls, typical move %.2f pts" % (name, moved, typical))

# returns in basis points so the two price scales are comparable
d["r_mt5"] = d.mt5_mid.pct_change() * 1e4
d["r_okx"] = d.okx_mid.pct_change() * 1e4
r = d[["r_mt5", "r_okx"]].dropna()
print("\nreturn sd: MT5 %.3f bp, OKX %.3f bp" % (r.r_mt5.std(), r.r_okx.std()))

# --- lagged cross-correlation ----------------------------------------------
print("\n%-6s %-9s %11s  %s" % ("lag k", "seconds", "corr", "meaning"))
print("-" * 62)
best = (0, 0)
for k in range(-5, 6):
    if k >= 0:
        c = r.r_okx.shift(k).corr(r.r_mt5)          # OKX earlier -> MT5 now
    else:
        c = r.r_okx.shift(k).corr(r.r_mt5)          # pandas handles negative shift
    if not np.isfinite(c):
        continue
    if abs(c) > abs(best[1]):
        best = (k, c)
    tag = ""
    if k == 0:
        tag = "simultaneous"
    elif k > 0:
        tag = "OKX leads by %ds" % (k * 2)
    else:
        tag = "MT5 leads by %ds" % (-k * 2)
    print("%-6d %-9s %11.4f  %s" % (k, "%+ds" % (k * 2), c, tag))
print("-" * 62)

k, c = best
print("\nstrongest correlation at lag %+d (%+ds), r = %.4f" % (k, k * 2, c))
if span_min < 240:
    print("\n*** %.0f minutes is a PIPELINE TEST, not a result. ***" % span_min)
    print("At this sample the correlation estimate is unstable and one volatile")
    print("minute can dominate it. Re-run after a full day; the code is what is")
    print("being validated here, not the number.")
elif k > 0 and c > 0.15:
    print("\n-> OKX appears to lead. Next step is to check whether the lag survives")
    print("   when the market is FAST, since that is when it would be worth money.")
elif abs(k) <= 0:
    print("\n-> moves are simultaneous at 2-second resolution. Any lag is shorter")
    print("   than this recorder can see; a faster poll would be needed to find it.")
else:
    print("\n-> no clean lead-lag structure at this resolution.")

# --- does the gap mean-revert? the other way a lag shows up ----------------
d["gap"] = d.mt5_mid - d.okx_mid
g = d.gap.dropna()
print("\ngap (mostly USDT basis, NOT a lag): mean %.2f sd %.2f" % (g.mean(), g.std()))
dev = g - g.rolling(60, min_periods=20).mean()
fwd = d.mt5_mid.shift(-30) - d.mt5_mid              # next 60 seconds of MT5
ok = dev.notna() & fwd.notna()
if ok.sum() > 100:
    cc = np.corrcoef(dev[ok], fwd[ok])[0, 1]
    print("corr(gap deviation from its own mean, MT5 move over next 60s) = %.4f" % cc)
    print("  NEGATIVE would mean an unusually wide gap closes - i.e. MT5 catches up.")
    print("  That is the same lag seen from a different angle, and is the version")
    print("  that would actually be tradeable.")
