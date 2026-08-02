"""Does volatility make a trade unable to resolve - and is avoiding those worth anything?

The question behind this: are there moments when ATR makes it impossible for a trade to
win or lose? The answer is yes, and it is worth separating two things that sound alike.

  THE MIX - how often a trade wins, loses, times out, or hits both barriers in one bar.
  This absolutely moves with volatility, and it moves a lot. Quiet market, neither
  barrier is reachable inside the hold and the trade times out. Wild market, both are
  reached in the same bar and which came first is unknowable.

  THE RATIO - among trades that DID resolve, how many won versus lost. This is the only
  thing that pays. A filter has to move this, and moving the mix is not the same thing.

WHY THE DISTINCTION MATTERS FINANCIALLY. A timeout is not free. The position closes at
whatever price exists at the end, so it settles near zero move but still paid the spread
to get in. Every timeout is roughly a spread donated for nothing. If volatility predicts
timeouts, then avoiding those moments saves real money - not by creating an edge, but by
not paying the toll on trades that were never going to reach a barrier.

That is a genuinely different lever from the geometry invariance, which says expectancy
is minus one spread whatever the arrangement of stop and target. This asks instead
whether some trades can be skipped BEFORE paying that spread.
"""
import os, math, random
import numpy as np, pandas as pd
import MetaTrader5 as mt5

SYM, LOTS = "BTCUSDm", 0.05
TP_PTS, SL_PTS, MAX_BARS = 20.0, 40.0, 24
rng = random.Random(8080)

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select(SYM, True)
tk = mt5.symbol_info_tick(SYM); SPREAD = tk.ask - tk.bid
r5 = None
for w in (200000, 120000, 60000, 30000):
    r5 = mt5.copy_rates_from_pos(SYM, mt5.TIMEFRAME_M5, 0, w)
    if r5 is not None and len(r5): break
mt5.shutdown()
d5 = pd.DataFrame(r5); d5["t"] = pd.to_datetime(d5["time"], unit="s")
T5 = d5["t"].to_numpy(); H5 = d5.high.to_numpy(float)
L5 = d5.low.to_numpy(float); C5 = d5.close.to_numpy(float)
pc = d5.close.shift(1)
atr5 = pd.concat([d5.high-d5.low, (d5.high-pc).abs(),
                  (d5.low-pc).abs()], axis=1).max(axis=1).rolling(14).mean().to_numpy()
FAV, ADV = TP_PTS + SPREAD, SL_PTS - SPREAD

su = pd.read_csv(r"C:\Projects\KinoliveLines\study\setups.csv", parse_dates=["time"])
su = su[su.time >= d5.t.min()].reset_index(drop=True)
idx = np.searchsorted(T5, su["time"].to_numpy(), side="left")

recs, busy = [], -1
for i0 in idx:
    if i0 <= busy or i0 >= len(C5) - MAX_BARS - 1 or i0 < 300:
        continue
    side = 1 if rng.random() < 0.5 else -1
    b0 = C5[i0]; tp, sl = b0 + side*FAV, b0 - side*ADV
    out, pnl = "timeout", None
    for j in range(i0+1, i0+1+MAX_BARS):
        ht = (H5[j] >= tp) if side > 0 else (L5[j] <= tp)
        hs = (L5[j] <= sl) if side > 0 else (H5[j] >= sl)
        if ht and hs: out = "ambig"; break
        if hs: out = "loss"; break
        if ht: out = "win"; break
    if out == "win":     pnl = TP_PTS*LOTS
    elif out == "loss":  pnl = -SL_PTS*LOTS
    elif out == "ambig": pnl = (TP_PTS - SL_PTS)/2*LOTS     # split the ambiguous
    else:
        # timed out: settle at the close, which is where the spread was spent for nothing
        end = C5[min(i0+MAX_BARS, len(C5)-1)]
        pnl = max(min(side*(end-b0)*LOTS, TP_PTS*LOTS), -SL_PTS*LOTS)
    # how big is the barrier compared with what the market actually moves in a bar?
    recs.append({"out": out, "pnl": pnl,
                 "reach": ADV / max(atr5[i0], 1e-9)})       # barriers per M5 ATR
    busy = i0 + MAX_BARS

df = pd.DataFrame(recs)
df["q"] = pd.qcut(df["reach"], 5, labels=False, duplicates="drop")

print("OUTCOME MIX BY VOLATILITY   (barrier %.0f pts, hold %d min, %.2f lots)"
      % (ADV, MAX_BARS*5, LOTS))
print("'reach' = barrier distance / ATR(M5). HIGH reach means a QUIET market where the")
print("barrier is far away in ATR terms; LOW reach means a wild one.\n")
print("%-6s %8s %9s %7s %7s %8s %8s %10s %11s"
      % ("bucket", "reach", "n", "win", "loss", "ambig", "timeout", "net $", "$ / trade"))
print("-" * 84)
for q in sorted(df["q"].dropna().unique()):
    v = df[df["q"] == q]
    n = len(v)
    print("%-6s %8.1f %9d %6.0f%% %6.0f%% %7.0f%% %7.0f%% %10.2f %11.3f"
          % ("Q%d" % (q+1), v["reach"].median(), n,
             100*(v.out=="win").mean(), 100*(v.out=="loss").mean(),
             100*(v.out=="ambig").mean(), 100*(v.out=="timeout").mean(),
             v["pnl"].sum(), v["pnl"].mean()))
print("-" * 84)
print("%-6s %8s %9d %6.0f%% %6.0f%% %7.0f%% %7.0f%% %10.2f %11.3f"
      % ("ALL", "", len(df), 100*(df.out=="win").mean(), 100*(df.out=="loss").mean(),
         100*(df.out=="ambig").mean(), 100*(df.out=="timeout").mean(),
         df["pnl"].sum(), df["pnl"].mean()))

# the ratio that actually pays, among decided trades only
print("\nWIN RATE AMONG DECIDED TRADES ONLY (the number that has to move)")
print("  breakeven needs %.1f%%" % (100*SL_PTS/(SL_PTS+TP_PTS)))
for q in sorted(df["q"].dropna().unique()):
    v = df[(df["q"] == q) & df.out.isin(["win", "loss"])]
    if len(v) < 60: continue
    p = (v.out == "win").mean()
    se2 = 2*math.sqrt(p*(1-p)/len(v))
    print("  Q%d  n=%-5d  %.1f%%  +/-%.1f%%   %s"
          % (q+1, len(v), 100*p, 100*se2,
             "TRADEABLE" if p > SL_PTS/(SL_PTS+TP_PTS) else "not enough"))

best = df.groupby("q")["pnl"].mean().idxmax()
print("\nIF THE WORST BUCKETS WERE SKIPPED")
for keep in range(1, 6):
    order = df.groupby("q")["pnl"].mean().sort_values(ascending=False).index[:keep]
    v = df[df["q"].isin(order)]
    print("  keep best %d of 5 buckets: %d trades (%.0f%% of them), $%+.3f/trade, total $%+.2f"
          % (keep, len(v), 100*len(v)/len(df), v["pnl"].mean(), v["pnl"].sum()))
print("""
Read the decided-trades block first. If every bucket sits near 50%, volatility is
changing WHICH KIND of outcome you get without changing who wins - and skipping the bad
buckets only saves the spread on trades that were going nowhere. That is worth having,
but it is a smaller and different thing from an edge.""")
