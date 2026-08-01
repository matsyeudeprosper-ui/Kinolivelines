"""Is the break-reversal finding real, or an artifact of how ties are scored?

Rule 9 rests on a 520-day M15-bar test where following a confirmed H1/H4 break
lost significantly more than random, split-half validated. But split-half only
tests whether a result holds across TIME. It cannot catch a bias built into the
measurement, because that bias sits in both halves equally.

The suspected bias: with a 0.4x ATR stop on M15 bars, one bar often spans BOTH
barriers. The original test resolved those ties in favour of the stop. Break bars
are by definition unusually large, so FOLLOW entries land on wide bars, hit more
ties, and collect more of those stop-wins - which would manufacture "following
breaks loses" out of nothing. A finer-grained M5 re-test failed to reproduce the
effect, which is what a tie artifact would look like.

So run the SAME 520-day test three ways and compare:
  TIE->LOSS   the original, pessimistic
  TIE->WIN    optimistic
  TIE->SPLIT  half a win and half a loss, the neutral assumption

A real market effect survives all three. An artifact flips or collapses. Also
reported: what fraction of each population's trades are actually ties, since if
FOLLOW ties far more often than RANDOM that alone shows the bias exists.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYM, SPREAD, HOLD = "BTCUSDm", 10.0, 8
STOP_ATR, TMULT = 0.40, 1.50

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, want):
    for k in (want, 45000, 20000, 10000, 5000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m15 = bars(mt5.TIMEFRAME_M15, 50000)
h1 = bars(mt5.TIMEFRAME_H1, 45000)
h4 = bars(mt5.TIMEFRAME_H4, 20000)
mt5.shutdown()

pc = m15["close"].shift(1)
m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                        (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
d = m15.dropna(subset=["atr"]).reset_index(drop=True)
hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                   d["close"].to_numpy(float), d["atr"].to_numpy(float))
n = len(cl)
print("M15 bars %s covering %d days\n" % (f"{n:,}", (d["time"].max() - d["time"].min()).days))

SPEC = {"H1": (h1, 60), "H4": (h4, 240)}
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


def run(entries, dirs):
    """Returns expectancy under three tie conventions, plus the tie rate."""
    acc = {"LOSS": [0.0, 0.0], "WIN": [0.0, 0.0], "SPLIT": [0.0, 0.0]}
    ties = tot = 0
    WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR
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
            tot += 1
            if ht == 999 and hs == 999:
                r = sign * (endp - e) / A
                for k in acc: acc[k][0] += r; acc[k][1] += r * r
            elif ht == hs:                       # SAME BAR - this is the tie
                ties += 1
                for k, r in (("LOSS", LOSS_R), ("WIN", WIN_R),
                             ("SPLIT", (WIN_R + LOSS_R) / 2)):
                    acc[k][0] += r; acc[k][1] += r * r
            elif hs < ht:
                for k in acc: acc[k][0] += LOSS_R; acc[k][1] += LOSS_R ** 2
            else:
                for k in acc: acc[k][0] += WIN_R; acc[k][1] += WIN_R ** 2
    out = {}
    for k, (s1, s2) in acc.items():
        m = s1 / tot
        out[k] = (m, math.sqrt(max(s2 / tot - m * m, 0) / tot))
    return out, ties / tot * 100, tot


valid = np.arange(300, n - HOLD - 2)
rand, rand_tie, rtot = run(valid, np.zeros(len(valid), np.int8))
print("%-14s %8s %7s %s" % ("population", "trades", "tie%", "expectancy under each tie rule"))
print("%-14s %8s %7s %11s %11s %11s" % ("", "", "", "TIE->LOSS", "TIE->WIN", "TIE->SPLIT"))
print("-" * 68)
print("%-14s %8s %6.1f%% %11.4f %11.4f %11.4f"
      % ("RANDOM", f"{rtot:,}", rand_tie, rand["LOSS"][0], rand["WIN"][0], rand["SPLIT"][0]))

for name in ("H1", "H4"):
    sig = breaks[name]
    e = np.where(sig != 0)[0]
    e = e[(e >= 300) & (e < n - HOLD - 2)]
    res, tie, tot_ = run(e, sig[e])
    print("%-14s %8s %6.1f%% %11.4f %11.4f %11.4f"
          % ("%s FOLLOW" % name, f"{tot_:,}", tie, res["LOSS"][0], res["WIN"][0], res["SPLIT"][0]))
    print("%-14s %8s %6s %11.4f %11.4f %11.4f"
          % ("  vs random", "", "",
             res["LOSS"][0] - rand["LOSS"][0],
             res["WIN"][0] - rand["WIN"][0],
             res["SPLIT"][0] - rand["SPLIT"][0]))
    two = {k: 2 * math.sqrt(res[k][1] ** 2 + rand[k][1] ** 2) for k in res}
    print("%-14s %8s %6s %11s %11s %11s"
          % ("  significant?", "", "",
             "YES" if abs(res["LOSS"][0] - rand["LOSS"][0]) > two["LOSS"] else "no",
             "YES" if abs(res["WIN"][0] - rand["WIN"][0]) > two["WIN"] else "no",
             "YES" if abs(res["SPLIT"][0] - rand["SPLIT"][0]) > two["SPLIT"] else "no"))
print("-" * 68)
print("""
VERDICT RULE: the finding is real only if FOLLOW stays significantly below RANDOM
under ALL THREE conventions. If it is significant only under TIE->LOSS, then it
was the scoring, not the market, and rule 9 must come out.
Also check the tie% column: if FOLLOW ties far more often than RANDOM, the bias
is demonstrated directly.""")
