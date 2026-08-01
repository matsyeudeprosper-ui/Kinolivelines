"""Level tests on 520 days instead of 35, using M15 bars as the grain.

The D1/W1 result was untrustworthy because 50,000 M1 bars is only ~35 days, which
contains about five weekly candles - the "1,186 trades" were really a handful of
distinct levels seen many times, so the error bar was far wider than the naive
calculation suggested.

M15 goes back 520 days on this terminal, roughly 74 weekly candles and 520 daily
ones. Trading off M15 bars costs intrabar precision, which matters little when the
barriers sit tens of ATR-fractions apart, and buys a 15x longer sample.

M15 levels themselves are excluded: at M15 grain they would be self-referential
(the level IS the previous bar's extreme), which the live daemon also suppresses.

Geometry is the live shape: stop 0.4x ATR(M15), target 1.5x the stop, 120-minute
hold (8 M15 bars). Long AND short from every entry so no direction is supplied.
Timeouts settle at the closing price - scoring them zero is what faked two earlier
results. RANDOM is the control; without it a level type matching chance looks
like a finding.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYM, SPREAD = "BTCUSDm", 10.0
HOLD = 8                      # 8 x M15 = 120 minutes, same as live
STOP_ATR, TMULT = 0.40, 1.50

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, want):
    for k in (want, 45000, 20000, 10000, 5000, 2000, 500):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m15 = bars(mt5.TIMEFRAME_M15, 50000)
h1 = bars(mt5.TIMEFRAME_H1, 45000)
h4 = bars(mt5.TIMEFRAME_H4, 20000)
d1 = bars(mt5.TIMEFRAME_D1, 5000)
w1 = bars(mt5.TIMEFRAME_W1, 2000)
mt5.shutdown()

pc = m15["close"].shift(1)
m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                        (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
d = m15.dropna(subset=["atr"]).reset_index(drop=True)
hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                   d["close"].to_numpy(float), d["atr"].to_numpy(float))
n = len(cl)
span = (d["time"].max() - d["time"].min()).days
print("M15 bars %s covering %d days (%.1f years)\n" % (f"{n:,}", span, span / 365))

SPEC = {"H1": (h1, 60), "H4": (h4, 240), "D1": (d1, 1440), "W1": (w1, 10080)}
touch = {}
for name, (src, mins) in SPEC.items():
    if src is None or len(src) < 5:
        continue
    j = np.searchsorted((src["time"] + pd.Timedelta(minutes=mins)).values,
                        d["time"].values, side="right") - 1
    H, L = src["high"].to_numpy(), src["low"].to_numpy()
    t = np.zeros(n, bool)
    ok = np.where(j >= 0)[0]
    jj = j[ok]
    t[ok] = ((lo[ok] <= H[jj]) & (hi[ok] >= H[jj])) | ((lo[ok] <= L[jj]) & (hi[ok] >= L[jj]))
    touch[name] = t
    print("  %-3s levels touched on %s bars (%.1f%%)  from %s distinct candles"
          % (name, f"{t.sum():,}", t.sum() / n * 100, f"{len(src):,}"))


def simulate(entries):
    w = l = to = 0
    s1 = s2 = 0.0
    for i in entries:
        A = atr[i]
        if not np.isfinite(A) or A <= 0 or i + HOLD >= n:
            continue
        sd, td = STOP_ATR * A, STOP_ATR * A * TMULT
        win = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[win])
        rmin = np.minimum.accumulate(lo[win])
        mid, endp = cl[i], cl[i + HOLD]
        for sign in (1, -1):
            e = mid + sign * SPREAD / 2
            tp, sl = e + sign * td, e - sign * sd
            if sign > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 99
                hs = np.argmax(rmin <= sl) if rmin[-1] <= sl else 99
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 99
                hs = np.argmax(rmax >= sl) if rmax[-1] >= sl else 99
            if ht == 99 and hs == 99:
                to += 1; r = sign * (endp - e) / A
            elif hs <= ht:
                l += 1; r = -STOP_ATR
            else:
                w += 1; r = STOP_ATR * TMULT
            s1 += r; s2 += r * r
    tot = w + l + to
    m = s1 / tot
    se = math.sqrt(max(s2 / tot - m * m, 0) / tot)
    return w, l, to, m, se


valid = np.arange(300, n - HOLD)
print("\n%-8s %9s %8s %9s %12s %10s" % ("levels", "trades", "win%", "timeout%", "expectancy", "+/- SE"))
print("-" * 62)
res = {}
for name in ["RANDOM", "H1", "H4", "D1", "W1"]:
    ents = valid if name == "RANDOM" else valid[touch[name][valid]]
    if len(ents) < 300:
        print("%-8s too few" % name); continue
    w, l, to, m, se = simulate(ents)
    tot = w + l + to
    res[name] = (w / tot * 100, m, se, tot)
    print("%-8s %9s %8.2f %9.2f %+12.4f %10.4f"
          % (name, f"{tot:,}", w / tot * 100, to / tot * 100, m, se))
print("-" * 62)

if "RANDOM" in res:
    rw, rm, rse, _ = res["RANDOM"]
    print("\nversus RANDOM control:")
    for name in ["H1", "H4", "D1", "W1"]:
        if name in res:
            w, m, se, tot = res[name]
            diff = m - rm
            two = 2 * math.sqrt(se ** 2 + rse ** 2)
            verdict = "REAL" if abs(diff) > two else "noise"
            print("  %-3s  win %+.2f pts | expectancy %+.4f | 2SE %.4f -> %s"
                  % (name, w - rw, diff, two, verdict))
