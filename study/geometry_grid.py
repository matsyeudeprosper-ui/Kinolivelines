"""Which stop/target SHAPE actually works? Sweep both, don't assume either.

The user's proposal: keep reward-to-risk at 1.5 but make BOTH distances small,
so the target is easy to reach and each win recovers a lot of ground. The
objection would be "a tight stop gets hit by noise" - but rule 4's 0.5x ATR
minimum was never measured, it was inherited convention, and that is precisely
the kind of assumption that made rule 6 wrong.

So test the whole grid. Stop from 0.25x to 1.5x ATR(M15); target from 0.5x to
2.0x the stop. For each cell, walk forward from every sampled bar and record
which barrier is touched FIRST, long and short, with the real $10 spread.

Efficiency: one forward walk per entry, then every cell resolved from the running
cumulative high/low. Checking the stop on the same bar as the target counts as a
LOSS - the pessimistic assumption, since intrabar order is unknown.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np

SYM, SPREAD, HOLD, STEP = "BTCUSDm", 10.0, 120, 11
STOPS = [0.25, 0.40, 0.50, 0.75, 1.00, 1.50]        # x ATR(M15)
TMULT = [0.50, 0.75, 1.00, 1.50, 2.00]              # target as multiple of stop

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, n):
    for k in (n, 20000, 10000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m1, m15 = bars(mt5.TIMEFRAME_M1, 50000), bars(mt5.TIMEFRAME_M15, 5000)
mt5.shutdown()

pc = m15["close"].shift(1)
m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                        (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
a = m15[["time", "atr"]].dropna().copy()
a["time"] = (a["time"] + pd.Timedelta(minutes=15)).astype("datetime64[ns]")
d = pd.merge_asof(m1, a, on="time", direction="backward").dropna(subset=["atr"]).reset_index(drop=True)

hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                   d["close"].to_numpy(float), d["atr"].to_numpy(float))
n = len(cl)
BIG = HOLD + 5

wins = np.zeros((len(STOPS), len(TMULT)))
loss = np.zeros_like(wins)
tout = np.zeros_like(wins)

entries = range(300, n - HOLD, STEP)
for i in entries:
    A = atr[i]
    if not np.isfinite(A) or A <= 0:
        continue
    w = slice(i + 1, i + 1 + HOLD)
    runmax = np.maximum.accumulate(hi[w])       # highest high so far
    runmin = np.minimum.accumulate(lo[w])       # lowest low so far
    mid = cl[i]
    for si_, s in enumerate(STOPS):
        sd = s * A
        for ti, tm in enumerate(TMULT):
            td = sd * tm
            # LONG: enter at ask, stop below, target above
            e = mid + SPREAD / 2
            hit_t = np.argmax(runmax >= e + td) if (runmax[-1] >= e + td) else BIG
            hit_s = np.argmax(runmin <= e - sd) if (runmin[-1] <= e - sd) else BIG
            if hit_t == BIG and hit_s == BIG:   tout[si_, ti] += 1
            elif hit_s <= hit_t:                loss[si_, ti] += 1   # tie -> loss
            else:                               wins[si_, ti] += 1
            # SHORT: enter at bid, stop above, target below
            es = mid - SPREAD / 2
            hit_t = np.argmax(runmin <= es - td) if (runmin[-1] <= es - td) else BIG
            hit_s = np.argmax(runmax >= es + sd) if (runmax[-1] >= es + sd) else BIG
            if hit_t == BIG and hit_s == BIG:   tout[si_, ti] += 1
            elif hit_s <= hit_t:                loss[si_, ti] += 1
            else:                               wins[si_, ti] += 1

print("BTCUSDm - stop x target grid, random entry, real $10 spread, 120-min cap")
print("%s entries per cell (long+short)\n" % f"{2*len(list(entries)):,}")
print("EXPECTANCY in ATR units per trade. Higher is better; all-negative means")
print("geometry alone does not pay and the entry must supply the difference.\n")

hdr = "stop\\target " + "".join("%10s" % ("x%.2f" % t) for t in TMULT)
print(hdr)
print("-" * len(hdr))
best = (-9, None)
for si_, s in enumerate(STOPS):
    row = "%-12s" % ("%.2fx ATR" % s)
    for ti, tm in enumerate(TMULT):
        tot = wins[si_, ti] + loss[si_, ti] + tout[si_, ti]
        exp = (wins[si_, ti] / tot) * (s * tm) - (loss[si_, ti] / tot) * s
        row += "%10.4f" % exp
        if exp > best[0]:
            best = (exp, (s, tm, wins[si_, ti] / tot * 100, tout[si_, ti] / tot * 100))
    print(row)
print("-" * len(hdr))

s, tm, wr, to = best[1]
print("\nBEST CELL: stop %.2fx ATR, target %.2fx stop (R:R 1:%.2f)" % (s, tm, tm))
print("  win rate %.1f%%   timeout %.1f%%   expectancy %+.4f ATR" % (wr, to, best[0]))
print("\nCURRENT LIVE SHAPE for comparison: stop ~0.6x ATR, target ~0.8x stop")

# the user's specific proposal: small distances, R:R 1.5
print("\nUSER'S PROPOSAL - tight stop with R:R 1.5, at each stop size:")
ti15 = TMULT.index(1.50)
for si_, s in enumerate(STOPS):
    tot = wins[si_, ti15] + loss[si_, ti15] + tout[si_, ti15]
    exp = (wins[si_, ti15] / tot) * (s * 1.5) - (loss[si_, ti15] / tot) * s
    print("  stop %.2fx ATR, target %.2fx ATR -> win %.1f%%  timeout %.1f%%  exp %+.4f"
          % (s, s * 1.5, wins[si_, ti15] / tot * 100, tout[si_, ti15] / tot * 100, exp))
