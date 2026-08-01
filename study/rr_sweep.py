"""Does a bigger reward-to-risk ratio pay for the spread?

The intuition is: "if I win 1.5 for every 1 I risk, I only need to be right some
of the time, so the spread is covered." This tests it directly.

Same stop (1.0x ATR) every time. Only the target changes. For each shape, walk
forward bar by bar and record WHICH BARRIER IS TOUCHED FIRST, entering long and
short from every sampled bar so no direction is being predicted.

What to look for: as the target moves further away the win RATE must fall,
because a distant barrier is harder to reach than a near one. The question is
whether the bigger payout more than compensates. If expectancy stays flat across
every shape, then reward-to-risk on its own creates nothing - it only trades win
rate against win size.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np

SYM, SPREAD, HOLD, STOP_ATR = "BTCUSDm", 10.0, 120, 1.0
TARGETS = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, n):
    for k in (n, 20000, 10000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d


m1, m15 = bars(mt5.TIMEFRAME_M1, 50000), bars(mt5.TIMEFRAME_M15, 5000)
mt5.shutdown()

pc = m15["close"].shift(1)
m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                        (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
a = m15[["time", "atr"]].dropna().copy()
a["time"] = (a["time"] + pd.Timedelta(minutes=15)).astype("datetime64[ns]")
d = pd.merge_asof(m1.sort_values("time"), a.sort_values("time"),
                  on="time", direction="backward").dropna(subset=["atr"]).reset_index(drop=True)

hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                   d["close"].to_numpy(float), d["atr"].to_numpy(float))
n, STEP = len(cl), 5

print("BTCUSDm - does a bigger reward-to-risk ratio pay for the spread?")
print("stop fixed at 1.0x ATR(M15), entry at random, real $10 spread, 120-min limit\n")
print("%-9s %-8s %8s %8s %9s %10s %12s" % (
    "target", "R:R", "win%", "loss%", "timeout%", "expectancy", "per trade $"))
print("-" * 72)

for T in TARGETS:
    wins = losses = touts = 0
    for i in range(0, n - HOLD, STEP):
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        mid = cl[i]
        for sign in (1, -1):                       # long and short from the same bar
            e = mid + sign * SPREAD / 2            # pay half the spread entering
            tp = e + sign * T * A
            sl = e - sign * STOP_ATR * A
            r = 0
            for j in range(i + 1, i + 1 + HOLD):
                if sign > 0:
                    if lo[j] <= sl: r = -1; break   # stop checked first = pessimistic
                    if hi[j] >= tp: r = 1;  break
                else:
                    if hi[j] >= sl: r = -1; break
                    if lo[j] <= tp: r = 1;  break
            if r == 1:    wins += 1
            elif r == -1: losses += 1
            else:         touts += 1
    tot = wins + losses + touts
    w, l, t = wins / tot, losses / tot, touts / tot
    exp_atr = w * T - l * STOP_ATR
    # dollars at 0.01 lot: 1 ATR of ~120 points = $1.20
    per_trade = exp_atr * 120 * 0.01
    print("%-9s %-8s %8.1f %8.1f %9.1f %+10.3f %+11.3f" % (
        "%.2fx ATR" % T, "1:%.2f" % T, w * 100, l * 100, t * 100, exp_atr, per_trade))

print("-" * 72)
print("""
READ THE 'expectancy' COLUMN DOWNWARDS.

If bigger reward-to-risk genuinely paid, expectancy would climb as the target
grows. If it stays roughly flat, then reward-to-risk is only swapping win rate
for win size and creates nothing on its own - the whole result comes from the
spread and from whether entries are better than random.""")
