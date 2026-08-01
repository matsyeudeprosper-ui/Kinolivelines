"""Does the break-reversal effect extend to M15 levels, or stop at H1?

Rule 9 covers H1 and H4 breaks because those were the ones tested. M15 is the
third level type in the live set and was left out for a good reason: on M15 bars
an M15 level IS the previous bar's extreme, so "breaking" it is just an up or
down candle - that measures momentum, not a level.

Testing it needs a finer grain. M5 gives 173 days, far short of the 520 used for
H1/H4 but ~35x more than the 5 days that made the first D1/W1 attempt worthless.

H1 is included as a CALIBRATION arm. It was already shown significant on M15 bars
over 520 days, so if the M5/173-day setup is sound it should reproduce that. If
H1 fails to reproduce here, the setup is too small or too coarse and the M15
result cannot be trusted either - that check matters more than the M15 number.

Geometry is the live shape: stop 0.4x ATR(M15), target 1.5x stop, 120-minute hold
(24 M5 bars). Real $10 spread. Timeouts settled at the closing price. FADE arm
included as the internal control.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYM, SPREAD, HOLD = "BTCUSDm", 10.0, 24          # 24 x M5 = 120 min
STOP_ATR, TMULT = 0.40, 1.50

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, want):
    for k in (want, 45000, 20000, 10000, 5000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m5 = bars(mt5.TIMEFRAME_M5, 50000)
m15 = bars(mt5.TIMEFRAME_M15, 50000)
h1 = bars(mt5.TIMEFRAME_H1, 45000)
mt5.shutdown()

pc = m15["close"].shift(1)
m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                        (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
a = m15[["time", "atr"]].dropna().copy()
a["time"] = (a["time"] + pd.Timedelta(minutes=15)).astype("datetime64[ns]")
d = pd.merge_asof(m5, a, on="time", direction="backward").dropna(subset=["atr"]).reset_index(drop=True)

hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                   d["close"].to_numpy(float), d["atr"].to_numpy(float))
n = len(cl)
span = (d["time"].max() - d["time"].min()).days
print("M5 bars %s covering %d days (%.2f years)\n" % (f"{n:,}", span, span / 365))

SPEC = {"M15": (m15, 15), "H1": (h1, 60)}
breaks = {}
for name, (src, mins) in SPEC.items():
    j = np.searchsorted((src["time"] + pd.Timedelta(minutes=mins)).values,
                        d["time"].values, side="right") - 1
    H, L = src["high"].to_numpy(), src["low"].to_numpy()
    sig = np.zeros(n, np.int8)
    for i in range(2, n - HOLD - 1):
        k = j[i]
        if k < 0:
            continue
        if cl[i - 1] < H[k] <= cl[i] and cl[i + 1] > H[k]:
            sig[i + 1] = 1
        elif cl[i - 1] > L[k] >= cl[i] and cl[i + 1] < L[k]:
            sig[i + 1] = -1
    breaks[name] = sig
    print("  %-3s confirmed breaks: %s (up %s / down %s)"
          % (name, f"{int((sig!=0).sum()):,}", f"{int((sig>0).sum()):,}", f"{int((sig<0).sum()):,}"))


def run(entries, dirs):
    w = l = to = 0
    s1 = s2 = 0.0
    for i, dirn in zip(entries, dirs):
        A = atr[i]
        if not np.isfinite(A) or A <= 0 or i + HOLD >= n:
            continue
        sd, td = STOP_ATR * A, STOP_ATR * A * TMULT
        win = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[win]); rmin = np.minimum.accumulate(lo[win])
        mid, endp = cl[i], cl[i + HOLD]
        for sign in ((1, -1) if dirn == 0 else (dirn,)):
            e = mid + sign * SPREAD / 2
            tp, sl = e + sign * td, e - sign * sd
            if sign > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 999
                hs = np.argmax(rmin <= sl) if rmin[-1] <= sl else 999
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 999
                hs = np.argmax(rmax >= sl) if rmax[-1] >= sl else 999
            if ht == 999 and hs == 999: to += 1; r = sign * (endp - e) / A
            elif hs <= ht:              l += 1;  r = -STOP_ATR
            else:                       w += 1;  r = STOP_ATR * TMULT
            s1 += r; s2 += r * r
    tot = max(w + l + to, 1)
    m = s1 / tot
    return w / tot * 100, m, math.sqrt(max(s2 / tot - m * m, 0) / tot), tot


valid = np.arange(300, n - HOLD - 2)
rw, rm, rse, rtot = run(valid, np.zeros(len(valid), np.int8))
print("\n%-14s %9s %8s %12s %10s" % ("population", "trades", "win%", "expectancy", "+/- SE"))
print("-" * 60)
print("%-14s %9s %8.2f %+12.4f %10.4f" % ("RANDOM", f"{rtot:,}", rw, rm, rse))

for name in ("H1", "M15"):
    sig = breaks[name]
    e = np.where(sig != 0)[0]
    e = e[(e >= 300) & (e < n - HOLD - 2)]
    if len(e) < 200:
        print("%-14s too few" % name); continue
    for lbl, dd in (("%s FOLLOW" % name, sig[e]), ("%s FADE" % name, -sig[e])):
        w_, m_, se_, tot_ = run(e, dd)
        diff = m_ - rm
        two = 2 * math.sqrt(se_ ** 2 + rse ** 2)
        tag = "  REAL" if abs(diff) > two else ""
        print("%-14s %9s %8.2f %+12.4f %10.4f  vs rand %+.4f (2SE %.4f)%s"
              % (lbl, f"{tot_:,}", w_, m_, se_, diff, two, tag))
print("-" * 60)
print("""
CALIBRATION: H1 FOLLOW was -0.034 below random on 520 days of M15 bars. If it
does not reproduce as clearly negative here, this M5/173-day setup is too small
or too coarse and the M15 row means nothing either way.""")
