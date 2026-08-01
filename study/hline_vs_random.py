"""Do KinoliveLines level touches beat a random entry?

This is the question that actually decides trades, and it has never been asked.

Earlier research asked "after price touches a level, does it go UP or DOWN over
the next N minutes" and found nothing. That is a DIFFERENT question. Real trades
are decided by which barrier is touched FIRST - the stop or the target. A level
could have zero directional bias and still change barrier order, for instance if
price stalls or bounces around levels rather than travelling cleanly through.

METHOD
  Levels are rebuilt per-bar exactly as the EA builds them: previous CLOSED
  H4/H1/M15 high and low, merged by ATR tolerance, spaced, capped at 6. No
  lookahead - a level only exists once the candle that made it has closed.

  Two populations, same simulation, same geometry, same real spread:
     RANDOM   every Nth bar
     HLINE    only bars where price is touching a level

  Both trade long AND short from each entry, so neither population is being
  given a directional opinion. The only difference is WHERE the entry happens.

  Geometry matches the live rules after the 2026-07-31 change: stop 1.0x
  ATR(M15), target 0.75x the stop, 120-minute limit, $10 spread.

READING IT
  If HLINE win% is meaningfully above RANDOM win%, the levels carry information
  about barrier order and the entry signal is worth keeping. If it matches, the
  levels are decoration and the entry needs replacing, not tuning.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np

SYM, SPREAD, HOLD = "BTCUSDm", 10.0, 120
STOP_ATR, TARG_MULT = 1.0, 0.75          # target = 0.75 x stop, the new live shape

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, n):
    for k in (n, 20000, 10000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m1 = bars(mt5.TIMEFRAME_M1, 50000)
m5 = bars(mt5.TIMEFRAME_M5, 20000)
m15 = bars(mt5.TIMEFRAME_M15, 5000)
h1 = bars(mt5.TIMEFRAME_H1, 5000)
h4 = bars(mt5.TIMEFRAME_H4, 3000)
si = mt5.symbol_info(SYM)
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

# ---- rebuild the EA's level set per bar, no lookahead ----
DUR = {"H4": 240, "H1": 60, "M15": 15}
SRC = {"H4": (h4, 3), "H1": (h1, 2), "M15": (m15, 1)}
idx = {k: np.searchsorted((SRC[k][0]["time"] + pd.Timedelta(minutes=DUR[k])).values,
                          d["time"].values, side="right") - 1 for k in SRC}
arr = {k: (SRC[k][0]["high"].to_numpy(), SRC[k][0]["low"].to_numpy(), SRC[k][1]) for k in SRC}
pch = h1["close"].shift(1)
h1_atr = pd.concat([h1.high - h1.low, (h1.high - pch).abs(),
                    (h1.low - pch).abs()], axis=1).max(axis=1).rolling(14).mean().to_numpy()
spread_px = SPREAD

touch = np.zeros(n, bool)
for i in range(300, n - HOLD):
    j1 = idx["H1"][i]
    A = h1_atr[j1] if j1 >= 0 else np.nan
    if not np.isfinite(A) or A <= 0:
        continue
    raw = []
    for k in ("H4", "H1", "M15"):
        j = idx[k][i]
        if j < 0:
            continue
        H, L, p = arr[k]
        raw += [[H[j], p], [L[j], p]]
    if not raw:
        continue
    tol = max(spread_px * 3.0, A * 0.12)
    raw.sort(key=lambda x: x[0])
    keep = [True] * len(raw)
    for x in range(len(raw)):
        if not keep[x]:
            continue
        for y in range(x + 1, len(raw)):
            if keep[y] and abs(raw[x][0] - raw[y][0]) <= tol:
                if raw[y][1] > raw[x][1]:
                    raw[x] = raw[y]
                keep[y] = False
    lv = [r[0] for x, r in enumerate(raw) if keep[x]][:6]
    if any(lo[i] <= p <= hi[i] for p in lv):
        touch[i] = True

print("level touches: %s of %s bars (%.1f%%)\n" % (
    f"{touch.sum():,}", f"{n:,}", touch.sum() / n * 100))


def simulate(entries):
    w = l = t = 0
    for i in entries:
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        stop_d, targ_d = STOP_ATR * A, STOP_ATR * A * TARG_MULT
        mid = cl[i]
        for sign in (1, -1):
            e = mid + sign * SPREAD / 2
            tp, sl = e + sign * targ_d, e - sign * stop_d
            r = 0
            for j in range(i + 1, i + 1 + HOLD):
                if sign > 0:
                    if lo[j] <= sl: r = -1; break
                    if hi[j] >= tp: r = 1;  break
                else:
                    if hi[j] >= sl: r = -1; break
                    if lo[j] <= tp: r = 1;  break
            if r == 1: w += 1
            elif r == -1: l += 1
            else: t += 1
    return w, l, t


valid = np.arange(300, n - HOLD)
rand_e = valid[::7]                                   # comparable count, spread out
hline_e = valid[touch[valid]]
hline_e = hline_e[::max(1, len(hline_e) // len(rand_e))]   # match sample sizes

print("%-10s %8s %8s %8s %9s %11s %11s" % (
    "entry", "trades", "win%", "loss%", "timeout%", "expectancy", "breakeven%"))
print("-" * 72)
out = {}
for name, e in (("RANDOM", rand_e), ("HLINE", hline_e)):
    w, l, t = simulate(e)
    tot = w + l + t
    if not tot:
        continue
    wp, lp, tp_ = w / tot, l / tot, t / tot
    exp = wp * (STOP_ATR * TARG_MULT) - lp * STOP_ATR
    be = (1 - tp_) / (1 + TARG_MULT) * 100          # win% needed to break even
    out[name] = (wp * 100, exp, be)
    print("%-10s %8s %8.2f %8.2f %9.2f %+11.4f %10.2f%%" % (
        name, f"{tot:,}", wp * 100, lp * 100, tp_ * 100, exp, be))
print("-" * 72)

if "RANDOM" in out and "HLINE" in out:
    dw = out["HLINE"][0] - out["RANDOM"][0]
    de = out["HLINE"][1] - out["RANDOM"][1]
    print("\nHLINE minus RANDOM:  win rate %+.2f points | expectancy %+.4f ATR" % (dw, de))
    print("gap HLINE still needs to close: %+.2f points" % (out["HLINE"][2] - out["HLINE"][0]))
    print("""
A win-rate difference under about 1 point is noise at this sample size.
Above ~2 points and consistently positive, the levels are doing something.""")
