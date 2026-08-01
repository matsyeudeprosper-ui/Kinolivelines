"""Does the wide-stop corner keep improving, or was 1.5x ATR the edge of a cliff?

The first grid stopped at a 1.5x ATR stop and that cell came out barely positive
(+0.0048) sitting on top of a clean gradient. Two possibilities: the trend keeps
going and wide stops genuinely suit this market, or 1.5x is a peak and it falls
away after. Extending the grid settles it.

Also reports the practical constraint, because a wide stop costs real money: at
0.01 lots the dollar risk is stop_ATR x ATR x 0.01, and rule 2 caps risk at 0.5%
of equity. A shape that only works at 3x ATR may be untradeable on this account.

Same method throughout: random entry, long and short, real $10 spread, 120-minute
cap, stop checked before target on a tied bar (pessimistic).
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np

SYM, SPREAD, HOLD, STEP = "BTCUSDm", 10.0, 120, 11
STOPS = [1.00, 1.50, 2.00, 2.50, 3.00, 4.00]
TMULT = [0.30, 0.50, 0.75, 1.00]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, n):
    for k in (n, 20000, 10000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m1, m15 = bars(mt5.TIMEFRAME_M1, 50000), bars(mt5.TIMEFRAME_M15, 5000)
eq = 984.0
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
med_atr = float(np.nanmedian(atr))

W = np.zeros((len(STOPS), len(TMULT)))
L = np.zeros_like(W)
T = np.zeros_like(W)
PNL = np.zeros_like(W)   # true P&L in ATR units, timeouts settled at the cap

ents = list(range(300, n - HOLD, STEP))
for i in ents:
    A = atr[i]
    if not np.isfinite(A) or A <= 0:
        continue
    w = slice(i + 1, i + 1 + HOLD)
    runmax = np.maximum.accumulate(hi[w])
    runmin = np.minimum.accumulate(lo[w])
    mid = cl[i]
    for si_, s in enumerate(STOPS):
        sd = s * A
        for ti, tm in enumerate(TMULT):
            td = sd * tm
            # A TIMED-OUT trade is not free. The 120-minute cap force-closes it at
            # whatever the market is at that moment, so it must be scored at its
            # actual mark-to-market, not at zero. Scoring timeouts as zero is what
            # made a 4x ATR stop look like +0.32 ATR/trade: with a stop that far
            # away almost nothing resolves, and every unresolved loss was being
            # dropped. That is the wide-stop illusion in one line of code.
            e = mid + SPREAD / 2
            ht = np.argmax(runmax >= e + td) if runmax[-1] >= e + td else BIG
            hs = np.argmax(runmin <= e - sd) if runmin[-1] <= e - sd else BIG
            if ht == BIG and hs == BIG:
                T[si_, ti] += 1
                PNL[si_, ti] += (cl[i + HOLD] - e) / A          # settled at the cap
            elif hs <= ht:
                L[si_, ti] += 1; PNL[si_, ti] -= s
            else:
                W[si_, ti] += 1; PNL[si_, ti] += s * tm
            es = mid - SPREAD / 2
            ht = np.argmax(runmin <= es - td) if runmin[-1] <= es - td else BIG
            hs = np.argmax(runmax >= es + sd) if runmax[-1] >= es + sd else BIG
            if ht == BIG and hs == BIG:
                T[si_, ti] += 1
                PNL[si_, ti] += (es - cl[i + HOLD]) / A
            elif hs <= ht:
                L[si_, ti] += 1; PNL[si_, ti] -= s
            else:
                W[si_, ti] += 1; PNL[si_, ti] += s * tm

tot_per_cell = 2 * len(ents)
print("BTCUSDm - EXTENDED grid, wide stops. %s trades per cell." % f"{tot_per_cell:,}")
print("median ATR(M15) = %.0f pts. At 0.01 lots, 1 ATR of stop = $%.2f risk.\n"
      % (med_atr, med_atr * 0.01))

hdr = "stop\\target " + "".join("%10s" % ("x%.2f" % t) for t in TMULT) + "    $risk  %eq"
print(hdr)
print("-" * len(hdr))
best = (-9, None)
for si_, s in enumerate(STOPS):
    row = "%-12s" % ("%.2fx ATR" % s)
    for ti, tm in enumerate(TMULT):
        tot = W[si_, ti] + L[si_, ti] + T[si_, ti]
        exp = PNL[si_, ti] / tot
        row += "%10.4f" % exp
        if exp > best[0]:
            best = (exp, (s, tm, W[si_, ti] / tot * 100, T[si_, ti] / tot * 100))
    dollar = s * med_atr * 0.01
    row += "  %7.2f %5.2f%%" % (dollar, dollar / eq * 100)
    print(row)
print("-" * len(hdr))

s, tm, wr, to = best[1]
print("\nBEST: stop %.2fx ATR, target %.2fx stop -> win %.1f%%, timeout %.1f%%, exp %+.4f"
      % (s, tm, wr, to, best[0]))
print("      dollar risk at 0.01 lots: $%.2f = %.2f%% of equity (rule 2 caps at 0.50%%)"
      % (s * med_atr * 0.01, s * med_atr * 0.01 / eq * 100))

# Is the positive corner real, or one lucky cell? Check the whole gradient.
print("\nGRADIENT CHECK - reading each target column down the stop sizes:")
for ti, tm in enumerate(TMULT):
    col = []
    for si_ in range(len(STOPS)):
        tot = W[si_, ti] + L[si_, ti] + T[si_, ti]
        col.append(PNL[si_, ti] / tot)
    trend = "rising" if col[-1] > col[0] else "falling"
    print("  target x%.2f: %s  -> %s" % (tm, "  ".join("%+.4f" % c for c in col), trend))
print("""
A single positive cell is noise. A whole column that rises and STAYS positive is
a pattern. If the columns turn over past some stop size, that peak is the real
answer and anything wider is worse.""")
