"""Follow the one gradient the splits found: slower levels looked better.

The split by level type gave H4 53.23% > H1 52.89% > M15 51.66% - a clean
monotonic ordering, about 1.9 standard errors, suggestive but not proof. The
obvious question it raises is what happens BEYOND H4, since nothing slower was
ever tested. If significance really scales with timeframe then D1 and W1 levels
should be better still, and those are exactly the levels most traders watch.

Method matches the other studies so results are comparable: levels rebuilt from
the previous CLOSED candle of each timeframe (no lookahead), entry when price
touches one, long AND short from every entry so no direction is supplied, real
$10 spread, 120-minute cap, stop checked before target on a tied bar.

Geometry is the shape now live: stop 0.4x ATR(M15), target 1.5x the stop.
Timeouts are settled at the closing price, not scored as zero - scoring them as
zero is what produced a fake +0.32 ATR result on an earlier test.

RANDOM is included as the control. Without it a level type that merely matches
chance can look like a finding.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np

SYM, SPREAD, HOLD = "BTCUSDm", 10.0, 120
STOP_ATR, TMULT = 0.40, 1.50

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, n):
    for k in (n, 20000, 10000, 5000, 2000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m1 = bars(mt5.TIMEFRAME_M1, 50000)
m15 = bars(mt5.TIMEFRAME_M15, 5000)
h1 = bars(mt5.TIMEFRAME_H1, 5000)
h4 = bars(mt5.TIMEFRAME_H4, 3000)
d1 = bars(mt5.TIMEFRAME_D1, 1000)
w1 = bars(mt5.TIMEFRAME_W1, 300)
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

# minutes each timeframe spans, used to know when its candle has CLOSED
SPEC = {"M15": (m15, 15), "H1": (h1, 60), "H4": (h4, 240),
        "D1": (d1, 1440), "W1": (w1, 10080)}
print("bars available: " + ", ".join("%s %s" % (k, f"{len(v[0]):,}") for k, v in SPEC.items()))

# for each timeframe, which bars touch that timeframe's previous closed extremes
touch = {}
for name, (src, mins) in SPEC.items():
    if src is None or len(src) < 3:
        continue
    j = np.searchsorted((src["time"] + pd.Timedelta(minutes=mins)).values,
                        d["time"].values, side="right") - 1
    H, L = src["high"].to_numpy(), src["low"].to_numpy()
    ok = j >= 0
    t = np.zeros(n, bool)
    idx = np.where(ok)[0]
    jj = j[idx]
    t[idx] = ((lo[idx] <= H[jj]) & (hi[idx] >= H[jj])) | ((lo[idx] <= L[jj]) & (hi[idx] >= L[jj]))
    touch[name] = t
    print("  %-4s touches: %s bars (%.1f%%)" % (name, f"{t.sum():,}", t.sum() / n * 100))


def simulate(entries):
    w = l = to = 0
    pnl = 0.0
    for i in entries:
        A = atr[i]
        if not np.isfinite(A) or A <= 0 or i + HOLD >= n:
            continue
        sd = STOP_ATR * A
        td = sd * TMULT
        win = slice(i + 1, i + 1 + HOLD)
        runmax = np.maximum.accumulate(hi[win])
        runmin = np.minimum.accumulate(lo[win])
        mid, endp = cl[i], cl[i + HOLD]
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
                to += 1; pnl += sign * (endp - e) / A
            elif hs <= ht:
                l += 1; pnl -= STOP_ATR
            else:
                w += 1; pnl += STOP_ATR * TMULT
    return w, l, to, pnl


valid = np.arange(300, n - HOLD)
CAP = 2600                                   # keep every population comparable


def take(mask=None):
    e = valid[mask[valid]] if mask is not None else valid
    return e[:: max(1, len(e) // CAP)]


print("\n%-8s %9s %8s %8s %9s %11s" % ("levels", "trades", "win%", "loss%", "timeout%", "expectancy"))
print("-" * 60)
rows = {}
for name in ["RANDOM", "M15", "H1", "H4", "D1", "W1"]:
    if name != "RANDOM" and name not in touch:
        continue
    ents = take(None if name == "RANDOM" else touch[name])
    if len(ents) < 200:
        print("%-8s  too few touches to test" % name)
        continue
    w, l, to, pnl = simulate(ents)
    tot = w + l + to
    if tot < 400:
        print("%-8s  too few trades (%d)" % (name, tot))
        continue
    rows[name] = (w / tot * 100, pnl / tot, tot)
    print("%-8s %9s %8.2f %8.2f %9.2f %+11.4f" % (
        name, f"{tot:,}", w / tot * 100, l / tot * 100, to / tot * 100, pnl / tot))
print("-" * 60)

if "RANDOM" in rows:
    rw, re_, _ = rows["RANDOM"]
    print("\nversus the RANDOM control:")
    for name in ["M15", "H1", "H4", "D1", "W1"]:
        if name in rows:
            w, e, tot = rows[name]
            se = (0.25 / tot) ** 0.5 * 100          # rough SE on a win rate, points
            sig = "" if abs(w - rw) < 2 * se else "  <== beyond 2 SE"
            print("  %-4s  win %+.2f pts   expectancy %+.4f   (2 SE = %.2f pts)%s"
                  % (name, w - rw, e - re_, 2 * se, sig))
    print("""
A slower timeframe should beat a faster one if the gradient from the earlier
split was real. Anything inside 2 standard errors is noise no matter how the
ordering looks.""")
