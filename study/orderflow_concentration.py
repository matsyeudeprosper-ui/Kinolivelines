"""Does taking only the MOST EXTREME imbalance readings make the edge big enough to pay?

The preliminary scan took the top and bottom 20% of order-book imbalance and found a real
but small effect: on the Exness feed the top-vs-bottom move at 30 seconds is $2.04, and
the round-trip cost is $10. Cost cannot be cut - checked across Exness Zero, Pepperstone,
FP Markets and the OKX perp, and $10 is already at the cheap end for BTC.

So the only remaining lever is a BIGGER edge per trade. The top 20% is a wide net that
includes plenty of mildly-tilted books. If the effect is driven by genuinely lopsided
moments, then concentrating on the top 1-2% should raise the move per trade - fewer
trades, each worth more.

THE BAR IS ABSOLUTE. The move must exceed the $10 cost. Not be statistically significant -
significant and unprofitable is exactly where this signal already sits. It has to pay.

Two traps this guards against:

  * NON-OVERLAPPING WINDOWS. Stepping forward by the horizon each time, as the
    preliminary scan did. Overlapping windows shrank standard errors 5.3x elsewhere in
    this project.
  * SHRINKING SAMPLES. The top 1% of 4,369 windows is 44 trades. An edge measured on 44
    trades has an error bar of several dollars, so the move is printed WITH its error bar
    and a cell is only interesting if the LOWER bound clears the cost.
"""
import os, glob, math
import numpy as np, pandas as pd

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "recorder", "data")
COST = 10.0
HORIZONS = [("30s", 30), ("60s", 60), ("120s", 120)]
CUTS = [0.20, 0.10, 0.05, 0.02, 0.01]

frames = []
for f in sorted(glob.glob(os.path.join(D, "micro_*.csv"))):
    try:
        frames.append(pd.read_csv(f))
    except Exception:
        pass
m = pd.concat(frames, ignore_index=True)
m["t"] = pd.to_datetime(m["t_local"], format="mixed", utc=True)
for c in ("mt5_bid", "mt5_ask", "okx_bid", "okx_ask", "bid_sz5", "ask_sz5"):
    m[c] = pd.to_numeric(m[c], errors="coerce")
m = m.dropna(subset=["mt5_bid", "mt5_ask", "okx_bid", "okx_ask", "bid_sz5", "ask_sz5"])
m = m.sort_values("t").reset_index(drop=True)
m["ex_mid"] = (m.mt5_bid + m.mt5_ask) / 2
m["imb5"] = (m.bid_sz5 - m.ask_sz5) / (m.bid_sz5 + m.ask_sz5)
secs = (m["t"] - m["t"].iloc[0]).dt.total_seconds().to_numpy()
px = m["ex_mid"].to_numpy(float)
imb_all = m["imb5"].to_numpy(float)

print("DOES CONCENTRATING THE SIGNAL MAKE IT PAY?")
print("%s samples, %s to %s.  Target = Exness mid, the price we actually fill at."
      % (f"{len(m):,}", m.t.min().strftime("%m-%d %H:%M"), m.t.max().strftime("%m-%d %H:%M")))
print("Round-trip cost to beat: $%.2f per BTC.\n" % COST)

for hname, hsec in HORIZONS:
    idx, last = [], -1e9
    for i in range(len(secs)):                      # non-overlapping
        if secs[i] - last >= hsec:
            j = np.searchsorted(secs, secs[i] + hsec)
            if j < len(secs):
                idx.append((i, j)); last = secs[i]
    if len(idx) < 200:
        print("%s: too few windows\n" % hname); continue
    a = np.array([i for i, _ in idx]); b = np.array([j for _, j in idx])
    imb = imb_all[a]
    fwd = px[b] - px[a]

    print("horizon %s   %d non-overlapping windows" % (hname, len(idx)))
    print("  %-9s %7s %9s %11s %13s   %s"
          % ("cut", "n each", "up-rate", "$ move", "2SE", "pays $%.0f?" % COST))
    print("  " + "-" * 68)
    for q in CUTS:
        hi_c, lo_c = np.quantile(imb, 1-q), np.quantile(imb, q)
        hi, lo = imb >= hi_c, imb <= lo_c
        n = min(hi.sum(), lo.sum())
        if n < 20:
            print("  top/bot %-4.0f%% %7d   too few to measure" % (100*q, n)); continue
        # A long on the tilted-up side and a short on the tilted-down side. The tradeable
        # quantity is the DIFFERENCE in mean forward move between the two arms.
        move = fwd[hi].mean() - fwd[lo].mean()
        se2 = 2*math.sqrt(fwd[hi].var(ddof=1)/hi.sum() + fwd[lo].var(ddof=1)/lo.sum())
        up = (fwd[hi] > 0).mean()
        lower = move - se2
        verdict = ("YES - even the low end clears it" if lower > COST else
                   "maybe - point estimate only" if move > COST else "no")
        print("  top/bot %-4.0f%% %7d %8.1f%% %+10.2f %13.2f   %s"
              % (100*q, n, 100*up, move, se2, verdict))
    print()

print("""HOW TO READ THIS
The $ move must beat $10, and it must do so by more than its own error bar - otherwise a
tiny sample of extreme readings has simply produced a big number by chance. That is the
same mistake that made the crowding branch look real on 307 trades.

If the move does NOT grow as the cut tightens, the effect is spread evenly across the
distribution rather than concentrated in extreme books, and there is no version of this
signal that pays $10.""")
