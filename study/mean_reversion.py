"""Does price revert after an extreme move?

This is the natural extension of the one genuine finding we have. Breaking an
H1/H4 level and following the break is measurably worse than random, which says
those moves give something back. If that is a real property rather than a quirk
of levels, it should show up for extreme moves generally - defined by size, not
by whether a line happened to be there.

DIRECTIONAL, so it needs the fade control. Every earlier location test entered
long and short to avoid supplying an opinion; here the opinion IS the hypothesis.

  CONTINUE   enter in the direction the move just went
  REVERT     enter against it
  RANDOM     the no-skill baseline

If reversion is real, REVERT beats RANDOM and CONTINUE loses to it, roughly
mirrored. If all three land together, the move size tells us nothing.

EXTREME defined three ways, each strictly backward-looking:
  SIGMA   move over the last 30 minutes exceeds N standard deviations of the
          preceding 12 hours of 30-minute moves
  ATR     move over the last 30 minutes exceeds N x ATR(M15)
  RUN     N consecutive M1 closes in the same direction

Measured on M1 where ties are rare - the M15 grain destroyed the volume test
because bar size drove the result. Real $10 spread, stop 0.4x ATR(M15), target
1.5x the stop, 120-minute cap, timeouts settled at the closing price.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYM, SPREAD, HOLD = "BTCUSDm", 10.0, 120
STOP_ATR, TMULT = 0.40, 1.50

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, want):
    for k in (want, 90000, 45000, 20000, 10000):
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
print("M1 bars %s covering %d days\n" % (f"{n:,}", (d["time"].max() - d["time"].min()).days))

LOOK = 30                                   # the move being judged: last 30 minutes
move = np.full(n, np.nan)
move[LOOK:] = cl[LOOK:] - cl[:-LOOK]
ms = pd.Series(move)
sd12 = ms.rolling(720).std().shift(1).to_numpy()          # 12h of context, no lookahead

sig = {}
for k in (2.0, 2.5, 3.0):
    sig["SIGMA %.1f" % k] = (np.abs(move) >= k * sd12) & np.isfinite(sd12)
for k in (1.0, 1.5, 2.0):
    sig["ATR %.1fx" % k] = np.abs(move) >= k * atr
up = np.r_[False, np.diff(cl) > 0]
for k in (6, 9):
    run = np.ones(n, bool)
    for j in range(k):
        run &= np.r_[[False] * j, up[: n - j]] if j else up
    rund = np.ones(n, bool)
    for j in range(k):
        rund &= np.r_[[False] * j, ~up[: n - j]] if j else ~up
    sig["RUN %d" % k] = run | rund

WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR


def run_sim(entries, dirs):
    w = l = ti = to = 0
    s1 = s2 = 0.0
    for i, dirn in zip(entries, dirs):
        A = atr[i]
        if not np.isfinite(A) or A <= 0 or i + HOLD >= n:
            continue
        sd, td = STOP_ATR * A, STOP_ATR * A * TMULT
        win = slice(i + 1, i + 1 + HOLD)
        rmax = np.maximum.accumulate(hi[win]); rmin = np.minimum.accumulate(lo[win])
        mid, endp = cl[i], cl[i + HOLD]
        for s_ in ((1, -1) if dirn == 0 else (dirn,)):
            e = mid + s_ * SPREAD / 2
            tp, sl = e + s_ * td, e - s_ * sd
            if s_ > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                hs = np.argmax(rmin <= sl) if rmin[-1] <= sl else 10 ** 6
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                hs = np.argmax(rmax >= sl) if rmax[-1] >= sl else 10 ** 6
            if ht == 10 ** 6 and hs == 10 ** 6:
                to += 1; r = s_ * (endp - e) / A
            elif ht == hs:
                ti += 1; r = (WIN_R + LOSS_R) / 2
            elif hs < ht:
                l += 1; r = LOSS_R
            else:
                w += 1; r = WIN_R
            s1 += r; s2 += r * r
    tot = max(w + l + ti + to, 1)
    m = s1 / tot
    return w / tot * 100, m, math.sqrt(max(s2 / tot - m * m, 0) / tot), tot, ti / tot * 100


base = np.arange(800, n - HOLD - 2)
rw, rm, rse, rtot, rtie = run_sim(base, np.zeros(len(base), np.int8))
print("%-12s %-9s %8s %6s %7s %11s %10s  %s"
      % ("condition", "arm", "trades", "tie%", "win%", "expectancy", "vs random", "verdict"))
print("-" * 92)
print("%-12s %-9s %8s %5.1f%% %6.2f%% %+11.4f" % ("RANDOM", "", f"{rtot:,}", rtie, rw, rm))

for name in sorted(sig):
    mask = sig[name]
    e = base[mask[base]]
    if len(e) < 400:
        print("%-12s %-9s only %s - too few" % (name, "", f"{len(e):,}")); continue
    dirn = np.sign(move[e]).astype(np.int8)
    rows = {}
    for arm, dd in (("CONTINUE", dirn), ("REVERT", -dirn)):
        w_, m_, se_, tot_, tie_ = run_sim(e, dd)
        two = 2 * math.sqrt(se_ ** 2 + rse ** 2)
        rows[arm] = (m_, m_ - rm, two)
        print("%-12s %-9s %8s %5.1f%% %6.2f%% %+11.4f %+10.4f  %s"
              % (name if arm == "CONTINUE" else "", arm, f"{tot_:,}", tie_, w_, m_, m_ - rm,
                 "REAL" if abs(m_ - rm) > two else ""))
    gap = rows["REVERT"][0] - rows["CONTINUE"][0]
    gapse = 2 * math.sqrt(rows["REVERT"][2] ** 2 + rows["CONTINUE"][2] ** 2) / 2
    print("%-12s %-9s %8s %5s %6s %11s %+10.4f  %s"
          % ("", "  gap", "", "", "", "", gap, "REVERT>CONTINUE" if gap > gapse else "no gap"))
print("-" * 92)
print("""
The gap line is the real test. A one-sided result can be noise; REVERT beating
CONTINUE by more than the error bar means the direction of the prior move carries
information, whichever side of random the arms happen to sit.""")
