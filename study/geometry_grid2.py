"""Geometry grid, done properly: full available history and honest error bars.

Supersedes geometry_grid.py, which had two problems:
  * it used 50,000 M1 bars when the terminal will serve 99,000
  * it scored timed-out trades as ZERO, which made wide stops look profitable
    because with a distant stop almost nothing resolves and every unresolved
    loss was silently dropped

Both fixed here. A timed-out trade is settled at the price when the 120-minute
cap force-closes it, which is what actually happens to the account.

The error-bar table is the point of this version. Earlier runs reported cells
differing by 0.007 ATR as if that meant something; without knowing the standard
error there was no way to say which differences were real. Any two cells closer
together than roughly two standard errors are the same result.

Random entry, long AND short from every sampled bar, real $10 spread, stop
checked before target on a tied bar (pessimistic).
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYM, SPREAD, HOLD, STEP = "BTCUSDm", 10.0, 120, 7
STOPS = [0.25, 0.40, 0.50, 0.75, 1.00, 1.50]
TMULT = [0.50, 0.75, 1.00, 1.50, 2.00]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, want):
    for k in (want, 90000, 70000, 50000, 20000, 5000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m1 = bars(mt5.TIMEFRAME_M1, 99000)
m15 = bars(mt5.TIMEFRAME_M15, 50000)
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
days = (d["time"].max() - d["time"].min()).days
print("M1 bars %s covering %d days\n" % (f"{n:,}", days))

R, C = len(STOPS), len(TMULT)
W = np.zeros((R, C)); L = np.zeros((R, C)); T = np.zeros((R, C))
S1 = np.zeros((R, C)); S2 = np.zeros((R, C))          # running sum and sum of squares

ents = list(range(300, n - HOLD, STEP))
for i in ents:
    A = atr[i]
    if not np.isfinite(A) or A <= 0:
        continue
    w = slice(i + 1, i + 1 + HOLD)
    runmax = np.maximum.accumulate(hi[w])
    runmin = np.minimum.accumulate(lo[w])
    mid, endp = cl[i], cl[i + HOLD]
    for si_, s in enumerate(STOPS):
        sd = s * A
        for ti, tm in enumerate(TMULT):
            td = sd * tm
            for sign in (1, -1):
                e = mid + sign * SPREAD / 2
                tp, sl = e + sign * td, e - sign * sd
                if sign > 0:
                    ht = np.argmax(runmax >= tp) if runmax[-1] >= tp else BIG
                    hs = np.argmax(runmin <= sl) if runmin[-1] <= sl else BIG
                else:
                    ht = np.argmax(runmin <= tp) if runmin[-1] <= tp else BIG
                    hs = np.argmax(runmax >= sl) if runmax[-1] >= sl else BIG
                if ht == BIG and hs == BIG:
                    T[si_, ti] += 1
                    r = sign * (endp - e) / A            # settled at the cap
                elif hs <= ht:
                    L[si_, ti] += 1
                    r = -s
                else:
                    W[si_, ti] += 1
                    r = s * tm
                S1[si_, ti] += r
                S2[si_, ti] += r * r

TOT = W + L + T
MEAN = S1 / TOT
SE = np.sqrt(np.maximum(S2 / TOT - MEAN ** 2, 0) / TOT)

print("EXPECTANCY (ATR per trade), %s trades per cell" % f"{int(TOT[0,0]):,}")
hdr = "stop\\target " + "".join("%11s" % ("x%.2f" % t) for t in TMULT)
print(hdr); print("-" * len(hdr))
for si_, s in enumerate(STOPS):
    print("%-12s" % ("%.2fx ATR" % s) + "".join("%11.4f" % MEAN[si_, ti] for ti in range(C)))
print("-" * len(hdr))

print("\nSTANDARD ERROR of each cell (differences smaller than ~2x this are noise)")
print(hdr); print("-" * len(hdr))
for si_, s in enumerate(STOPS):
    print("%-12s" % ("%.2fx ATR" % s) + "".join("%11.4f" % SE[si_, ti] for ti in range(C)))
print("-" * len(hdr))

flat = [(MEAN[r_, c_], SE[r_, c_], STOPS[r_], TMULT[c_]) for r_ in range(R) for c_ in range(C)]
flat.sort(key=lambda x: -x[0])
bm, bse, bs, bt = flat[0]
print("\nBEST CELL: stop %.2fx ATR, target %.2fx stop -> %+.4f +/- %.4f" % (bs, bt, bm, bse))
print("\nCELLS STATISTICALLY TIED WITH THE BEST (within 2 SE of it):")
for m, se, s, t in flat:
    if m >= bm - 2 * math.sqrt(bse ** 2 + se ** 2):
        print("   stop %.2fx  target %.2fx stop (R:R 1:%.2f)   %+.4f +/- %.4f" % (s, t, t, m, se))

live = MEAN[STOPS.index(0.40), TMULT.index(1.50)]
live_se = SE[STOPS.index(0.40), TMULT.index(1.50)]
print("\nWHAT IS LIVE NOW (stop 0.40x, R:R 1.50): %+.4f +/- %.4f" % (live, live_se))
print("difference from best cell: %+.4f  (2 SE of that difference = %.4f)"
      % (bm - live, 2 * math.sqrt(bse ** 2 + live_se ** 2)))
print("\nIf that difference is smaller than its own error bar, the live shape is")
print("as good as anything on this grid and the exact numbers do not matter.")
