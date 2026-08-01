"""Pooling hides subsets. Split the level-touch population three ways.

The pooled test showed level touches beat random by +0.38 points - noise. But it
mixed H4 levels with M15 levels, first touches with tenth touches, and every hour
of the day. Any of those could contain a subset that works while the average does
not.

Three splits, same simulation, same geometry as the live rules after 2026-07-31
(stop 1.0x ATR(M15), target 0.75x stop, 120-min limit, real $10 spread), long AND
short from every entry so no directional opinion is being supplied.

  BY LEVEL TYPE   H4 / H1 / M15 - is a 4-hour level worth more than a 15-min one?
  BY TOUCH COUNT  1st touch of a fresh level vs the 2nd, 3rd, 4th+
  BY HOUR         session structure

BREAKEVEN is 54.2% at this geometry. A subset only matters if it clears that, and
only if it has enough trades to not be noise. Treat anything under ~500 trades or
within ~1 point of random as nothing.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np
from collections import defaultdict

SYM, SPREAD, HOLD = "BTCUSDm", 10.0, 120
STOP_ATR, TARG_MULT = 1.0, 0.75

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, n):
    for k in (n, 20000, 10000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m1 = bars(mt5.TIMEFRAME_M1, 50000)
m15 = bars(mt5.TIMEFRAME_M15, 5000)
h1 = bars(mt5.TIMEFRAME_H1, 5000)
h4 = bars(mt5.TIMEFRAME_H4, 3000)
mt5.shutdown()

pc = m15["close"].shift(1)
m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                        (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
a = m15[["time", "atr"]].dropna().copy()
a["time"] = (a["time"] + pd.Timedelta(minutes=15)).astype("datetime64[ns]")
d = pd.merge_asof(m1, a, on="time", direction="backward").dropna(subset=["atr"]).reset_index(drop=True)

hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                   d["close"].to_numpy(float), d["atr"].to_numpy(float))
hours = d["time"].dt.hour.to_numpy()
n = len(cl)

DUR = {"H4": 240, "H1": 60, "M15": 15}
SRC = {"H4": (h4, 3), "H1": (h1, 2), "M15": (m15, 1)}
idx = {k: np.searchsorted((SRC[k][0]["time"] + pd.Timedelta(minutes=DUR[k])).values,
                          d["time"].values, side="right") - 1 for k in SRC}
arr = {k: (SRC[k][0]["high"].to_numpy(), SRC[k][0]["low"].to_numpy(), SRC[k][1], k) for k in SRC}
pch = h1["close"].shift(1)
h1_atr = pd.concat([h1.high - h1.low, (h1.high - pch).abs(),
                    (h1.low - pch).abs()], axis=1).max(axis=1).rolling(14).mean().to_numpy()

# entry -> (level type, how many times this exact level has been touched before)
meta = {}
seen = defaultdict(int)
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
        H, L, p, nm = arr[k]
        raw += [[H[j], p, nm], [L[j], p, nm]]
    if not raw:
        continue
    tol = max(SPREAD * 3.0, A * 0.12)
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
    lv = [r for x, r in enumerate(raw) if keep[x]][:6]
    for price, prio, nm in lv:
        if lo[i] <= price <= hi[i]:
            key = round(price, 1)
            meta[i] = (nm, min(seen[key] + 1, 4))     # 1,2,3,4+ touches
            seen[key] += 1
            break

print("entries with level context: %s\n" % f"{len(meta):,}")


def simulate(entries):
    w = l = t = 0
    for i in entries:
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        stop_d = STOP_ATR * A
        targ_d = stop_d * TARG_MULT
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


BE_LABEL = "breakeven ~54.2%"


def report(title, groups):
    print("=" * 66)
    print("%s   (%s)" % (title, BE_LABEL))
    print("=" * 66)
    print("%-14s %9s %8s %10s %10s" % ("group", "trades", "win%", "vs 54.2", "expectancy"))
    rows = []
    for name, ents in groups:
        if len(ents) < 120:
            continue
        w, l, t = simulate(ents)
        tot = w + l + t
        if tot < 240:
            continue
        wp = w / tot * 100
        exp = (w / tot) * STOP_ATR * TARG_MULT - (l / tot) * STOP_ATR
        rows.append((name, tot, wp, exp))
    for name, tot, wp, exp in rows:
        flag = "  <== clears it" if wp > 54.2 else ""
        print("%-14s %9s %8.2f %+10.2f %+10.4f%s" % (name, f"{tot:,}", wp, wp - 54.2, exp, flag))
    print()
    return rows


ents = sorted(meta)
report("BY LEVEL TYPE", [(k, [i for i in ents if meta[i][0] == k]) for k in ("H4", "H1", "M15")])
report("BY TOUCH NUMBER", [("touch %d%s" % (c, "+" if c == 4 else ""),
                            [i for i in ents if meta[i][1] == c]) for c in (1, 2, 3, 4)])
report("BY HOUR (server)", [("%02d:00" % h, [i for i in ents if hours[i] == h])
                            for h in range(0, 24, 2)])

print("Anything under ~500 trades, or within ~1 point of the 52.3% pooled figure,")
print("is noise. Only a subset that clears 54.2% with real volume is worth a rule.")
