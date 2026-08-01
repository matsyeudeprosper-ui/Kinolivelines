"""How long should a trade be allowed to live?

The 120-minute cap is the biggest untested assumption in the system. It was
inherited from the OLD grid strategy's 101 trades - a different system - and has
never been checked for this one.

It matters because the spread is a FIXED $10. Over two hours the typical move is
around one ATR(M15), so ten points is a large slice of it. Over a day the move is
far bigger and the same ten points barely register. Holding longer does not find
an edge; it shrinks the handicap.

Against that: a longer hold ties up the single position slot, so fewer trades get
taken, and the max-hold rule exists partly to stop losers from lingering.

Method matches the corrected studies. Random entry, long AND short from each bar
so no direction is supplied, real $10 spread, stop 0.4x ATR(M15) and target 1.5x
the stop. Ambiguous bars - where one bar spans both barriers - are resolved
NEUTRALLY (half win, half loss), the convention that survived the tie-sensitivity
check; tie->loss is also reported so the difference stays visible. Trades still
open at the cap settle at the closing price.

Reported per hold length: expectancy per trade, and expectancy per DAY of capital
tied up, because a slightly better trade that occupies the slot ten times longer
is not actually better.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

SYM, SPREAD = "BTCUSDm", 10.0
STOP_ATR, TMULT = 0.40, 1.50
HOLDS_MIN = [30, 60, 120, 240, 480, 1440, 2880]      # 0.5h to 48h

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, want):
    for k in (want, 45000, 20000, 10000, 5000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


m15 = bars(mt5.TIMEFRAME_M15, 50000)
mt5.shutdown()

pc = m15["close"].shift(1)
m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                        (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
d = m15.dropna(subset=["atr"]).reset_index(drop=True)
hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                   d["close"].to_numpy(float), d["atr"].to_numpy(float))
n = len(cl)
print("M15 bars %s covering %d days\n" % (f"{n:,}", (d["time"].max() - d["time"].min()).days))

WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR
STEP = 3

print("%-9s %9s %7s %8s %9s %12s %12s %13s" % (
    "hold", "trades", "tie%", "win%", "timeout%", "TIE->SPLIT", "TIE->LOSS", "per day held"))
print("-" * 88)

for hm in HOLDS_MIN:
    H = hm // 15                                  # M15 bars
    w = l = ti = to = 0
    s1 = s2 = 0.0
    for i in range(300, n - H, STEP):
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        sd, td = STOP_ATR * A, STOP_ATR * A * TMULT
        win = slice(i + 1, i + 1 + H)
        rmax = np.maximum.accumulate(hi[win]); rmin = np.minimum.accumulate(lo[win])
        mid, endp = cl[i], cl[i + H]
        for sign in (1, -1):
            e = mid + sign * SPREAD / 2
            tp, sl = e + sign * td, e - sign * sd
            if sign > 0:
                ht = np.argmax(rmax >= tp) if rmax[-1] >= tp else 10 ** 6
                hs = np.argmax(rmin <= sl) if rmin[-1] <= sl else 10 ** 6
            else:
                ht = np.argmax(rmin <= tp) if rmin[-1] <= tp else 10 ** 6
                hs = np.argmax(rmax >= sl) if rmax[-1] >= sl else 10 ** 6
            if ht == 10 ** 6 and hs == 10 ** 6:
                to += 1; r = sign * (endp - e) / A
            elif ht == hs:
                ti += 1; r = (WIN_R + LOSS_R) / 2          # neutral on ambiguity
            elif hs < ht:
                l += 1; r = LOSS_R
            else:
                w += 1; r = WIN_R
            s1 += r; s2 += r * r
    tot = w + l + ti + to
    m = s1 / tot
    se = math.sqrt(max(s2 / tot - m * m, 0) / tot)
    # tie->loss variant, for comparison with the older studies
    m_loss = (s1 + ti * (LOSS_R - (WIN_R + LOSS_R) / 2)) / tot
    per_day = m / (hm / 1440.0)
    print("%-9s %9s %6.1f%% %7.1f%% %8.1f%% %+9.4f+-%.4f %+12.4f %+13.4f" % (
        ("%dh" % (hm // 60)) if hm >= 60 else ("%dm" % hm),
        f"{tot:,}", ti / tot * 100, w / tot * 100, to / tot * 100, m, se, m_loss, per_day))

print("-" * 88)
print("""
TIE->SPLIT is the column to read; TIE->LOSS is shown only to stay comparable with
the earlier studies, which used it and were biased by it.

'per day held' divides expectancy by the days of capital tied up. A longer hold
that earns slightly more per trade but occupies the only position slot for a day
can still be the worse choice. Judge on that column, not on expectancy alone.

If expectancy climbs steadily toward zero as the hold lengthens, the fixed spread
is being diluted exactly as expected - and the 120-minute cap is costing money.""")
