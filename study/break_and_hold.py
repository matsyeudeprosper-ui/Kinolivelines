"""If entering AT a level is worse than random, is entering AFTER a break better?

The 520-day test showed level touches underperform random, significantly so for
H4 and D1. The natural reading is that a level is where price REVERSES, so
stepping in there blind means stepping in front of a turn. That suggests the
opposite condition is worth measuring: wait for the level to be decisively broken
and HELD, then enter in the direction of the break.

This is the first DIRECTIONAL test in the series. Every earlier study entered
long and short from each bar precisely to avoid supplying a directional opinion.
Here the direction is the hypothesis, so it has to be taken - which means it also
needs a stronger control.

THREE POPULATIONS
  RANDOM       both directions from random bars - the no-skill baseline
  BREAK-FOLLOW enter in the direction of the confirmed break
  BREAK-FADE   the same entries with the direction FLIPPED

The fade arm is the sanity check. If break direction carries information then
FOLLOW should beat RANDOM and FADE should lose to it, roughly symmetrically. If
FOLLOW, FADE and RANDOM all land together, the break tells us nothing and any
single-arm result was noise.

BREAK DEFINITION - deliberately strict, since a wick through a level is not a
break: bar closes beyond the level, the previous bar closed on the other side,
and the NEXT bar also closes beyond it. Entry is at that confirmation close, so
nothing is known that would not have been known live.

Geometry is the live shape: stop 0.4x ATR(M15), target 1.5x stop, 120-minute
hold. Real $10 spread. Timeouts settled at the closing price.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYM, SPREAD, HOLD = "BTCUSDm", 10.0, 8          # 8 x M15 = 120 min
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

SPEC = {"H1": (h1, 60), "H4": (h4, 240), "D1": (d1, 1440)}

# breaks[i] = +1 if an upside break confirmed at bar i, -1 downside, 0 none
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
        up, dn = H[k], L[k]
        # upside: prev close below the level, this close above, next close still above
        if cl[i - 1] < up <= cl[i] and cl[i + 1] > up:
            sig[i + 1] = 1                      # entry on the confirmation bar
        elif cl[i - 1] > dn >= cl[i] and cl[i + 1] < dn:
            sig[i + 1] = -1
    breaks[name] = sig
    print("  %-3s confirmed breaks: %s  (up %s / down %s)"
          % (name, f"{int((sig != 0).sum()):,}",
             f"{int((sig > 0).sum()):,}", f"{int((sig < 0).sum()):,}"))


def run(entries, directions):
    """directions: +1 long, -1 short, or 0 meaning 'do both'."""
    w = l = to = 0
    s1 = s2 = 0.0
    for i, dirn in zip(entries, directions):
        A = atr[i]
        if not np.isfinite(A) or A <= 0 or i + HOLD >= n:
            continue
        sd, td = STOP_ATR * A, STOP_ATR * A * TMULT
        win = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[win])
        rmin = np.minimum.accumulate(lo[win])
        mid, endp = cl[i], cl[i + HOLD]
        signs = (1, -1) if dirn == 0 else (dirn,)
        for sign in signs:
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
    tot = max(w + l + to, 1)
    m = s1 / tot
    return w / tot * 100, m, math.sqrt(max(s2 / tot - m * m, 0) / tot), tot


valid = np.arange(300, n - HOLD - 2)
rw, rm, rse, rtot = run(valid, np.zeros(len(valid), np.int8))
print("\n%-16s %9s %8s %12s %10s" % ("population", "trades", "win%", "expectancy", "+/- SE"))
print("-" * 60)
print("%-16s %9s %8.2f %+12.4f %10.4f" % ("RANDOM", f"{rtot:,}", rw, rm, rse))

for name in ("H1", "H4", "D1"):
    sig = breaks[name]
    ents = np.where(sig != 0)[0]
    ents = ents[(ents >= 300) & (ents < n - HOLD)]
    if len(ents) < 200:
        print("%-16s too few breaks" % name)
        continue
    dirs = sig[ents]
    for label, dd in (("%s FOLLOW" % name, dirs), ("%s FADE" % name, -dirs)):
        w_, m_, se_, tot_ = run(ents, dd)
        diff = m_ - rm
        two = 2 * math.sqrt(se_ ** 2 + rse ** 2)
        tag = "  REAL" if abs(diff) > two else ""
        print("%-16s %9s %8.2f %+12.4f %10.4f  vs random %+.4f (2SE %.4f)%s"
              % (label, f"{tot_:,}", w_, m_, se_, diff, two, tag))
print("-" * 60)
print("""
FOLLOW should beat RANDOM and FADE should lose to it if break direction carries
information. If all three sit together, the break says nothing - and a single
arm looking good on its own would have been noise.""")
