"""Does volatility change WHICH barrier is hit first - or only how fast?

The claim being tested: a stop placed close to entry is more likely to be taken out when
volatility is high, and that is information we could lean on.

The first half is obviously true - a close stop is hit more often than a far one. The
real question is whether VOLATILITY moves that, because if the odds of hitting the stop
first change with volatility, that IS an exploitable imbalance.

Textbook answer is no. For a driftless random walk the chance of touching +A before -B
is B/(A+B) - distances only. Volatility changes how QUICKLY a barrier is reached, not
which one. Doubling volatility halves the time and leaves the odds untouched.

But real prices are not a driftless random walk. Volatility clusters, moves trend and
mean-revert, and tails are fat. Any of those could bend the relationship, and that would
show up as the win rate drifting across volatility buckets. So it is measured rather
than assumed.

ALL COSTS ARE OFF for this test - no spread, no fees. The user asked to set them aside,
and it also isolates the question: with costs included every arrangement loses exactly
one spread, which would drown the effect being looked for.
"""
import os, math, random
import numpy as np, pandas as pd
import MetaTrader5 as mt5

SYM = "BTCUSDm"
MAX_BARS = 24                       # 2 hours of M5
rng = random.Random(4242)

# (stop, target) in points. No spread applied anywhere.
SHAPES = [("stop CLOSE, target FAR", 20.0, 60.0),
          ("stop close, target far", 30.0, 60.0),
          ("symmetric",              40.0, 40.0),
          ("stop far, target close", 60.0, 30.0),
          ("stop FAR, target CLOSE", 60.0, 20.0)]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select(SYM, True)
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

su = pd.read_csv(r"C:\Projects\KinoliveLines\study\setups.csv", parse_dates=["time"])
su = su[su.time >= d5.t.min()].reset_index(drop=True)
base_idx = np.searchsorted(T5, su["time"].to_numpy(), side="left")
base_idx = [i for i in base_idx if 300 <= i < len(C5) - MAX_BARS - 1]

print("WHICH BARRIER IS HIT FIRST - by volatility.  NO COSTS APPLIED.")
print("%d entry points, %s to %s\n" % (len(base_idx), d5.t.min().date(), d5.t.max().date()))

for name, sl_pts, tp_pts in SHAPES:
    theo = sl_pts / (sl_pts + tp_pts)          # random-walk chance of the TARGET first
    rows = []
    busy = -1
    for i0 in base_idx:
        if i0 <= busy:
            continue
        side = 1 if rng.random() < 0.5 else -1
        b0 = C5[i0]
        tp = b0 + side*tp_pts
        sl = b0 - side*sl_pts
        out = None
        for j in range(i0+1, i0+1+MAX_BARS):
            ht = (H5[j] >= tp) if side > 0 else (L5[j] <= tp)
            hs = (L5[j] <= sl) if side > 0 else (H5[j] >= sl)
            if ht and hs: out = "ambig"; break
            if hs: out = "loss"; break
            if ht: out = "win"; break
        busy = i0 + MAX_BARS
        if out in ("win", "loss"):
            rows.append({"win": 1 if out == "win" else 0, "atr": atr5[i0]})
    df = pd.DataFrame(rows)
    if len(df) < 300:
        print("%-24s too few" % name); continue
    df["q"] = pd.qcut(df["atr"], 5, labels=False, duplicates="drop")
    print("%s   stop %.0f / target %.0f   theory says %.0f%% wins"
          % (name, sl_pts, tp_pts, 100*theo))
    line = "   by volatility: "
    rates = []
    for q in sorted(df["q"].dropna().unique()):
        v = df[df["q"] == q]
        p = v["win"].mean(); rates.append(p)
        line += "Q%d %.0f%% (n=%d)  " % (q+1, 100*p, len(v))
    print(line)
    spread_pp = (max(rates) - min(rates)) * 100
    overall = df["win"].mean()
    se2 = 2*math.sqrt(overall*(1-overall)/len(df))
    print("   overall %.1f%%  (theory %.0f%%, 2SE %.1f%%)   quiet-to-wild swing %.0f pp   %s\n"
          % (100*overall, 100*theo, 100*se2, spread_pp,
             "VOLATILITY MATTERS" if spread_pp > 15 else "flat across volatility"))

print("""If the win rate stays roughly flat across Q1..Q5 in every shape, volatility is
only changing how fast a barrier is reached, not which one - and there is no imbalance
to lean on. If it slopes consistently, that is a real effect and worth pursuing.""")
