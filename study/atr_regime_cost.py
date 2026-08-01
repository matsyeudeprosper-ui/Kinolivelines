"""Is it worth refusing to trade when the market is quiet?

The spread on BTCUSDm is a FIXED $10, so a quiet market pays a bigger share of
every trade. But cost is only half the question - the other half is whether the
target is actually reachable in that regime.

FIRST-TOUCH IS THE WHOLE POINT. An earlier version of this script asked only
"did price reach +1.5x ATR within 120 minutes" and counted that as a win. That
is wrong: a trade that first dips to the stop at -1.0x ATR is a LOSS even if
price later runs to the target. This version walks forward bar by bar and
records WHICH BARRIER IS TOUCHED FIRST - target, stop, or neither by the time
the 120-minute hold expires.

Direction is not being predicted here. Both a long and a short are simulated
from every bar, so the result is what a coin-flip entry earns in each volatility
regime after the real spread. That isolates the geometry and the cost from any
claim about reading the market.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np

SYM, SPREAD, HOLD = "BTCUSDm", 10.0, 120
STOP_ATR, TARG_ATR = 1.0, 1.5

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(tf, n):
    for k in (n, 20000, 10000, 5000):
        r = mt5.copy_rates_from_pos(SYM, tf, 0, k)
        if r is not None and len(r):
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d
    return None


m1 = bars(mt5.TIMEFRAME_M1, 50000)
m15 = bars(mt5.TIMEFRAME_M15, 5000)
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
n = len(cl)

STEP = 3          # sample every 3rd bar: 16k trades is plenty and keeps this quick
idx, res_l, res_s = [], [], []

for i in range(0, n - HOLD, STEP):
    A = atr[i]
    if not np.isfinite(A) or A <= 0:
        continue
    mid = cl[i]
    # LONG: pay half the spread on entry, barriers measured from the fill
    e = mid + SPREAD / 2
    tp_l, sl_l = e + TARG_ATR * A, e - STOP_ATR * A
    # SHORT: mirror image
    es = mid - SPREAD / 2
    tp_s, sl_s = es - TARG_ATR * A, es + STOP_ATR * A
    ol = os_ = 0                      # 0 = timed out, +1 = target first, -1 = stop first
    for j in range(i + 1, i + 1 + HOLD):
        if ol == 0:
            if lo[j] <= sl_l:   ol = -1          # stop checked first: pessimistic
            elif hi[j] >= tp_l: ol = 1
        if os_ == 0:
            if hi[j] >= sl_s:   os_ = -1
            elif lo[j] <= tp_s: os_ = 1
        if ol and os_:
            break
    idx.append(A); res_l.append(ol); res_s.append(os_)

A = np.array(idx); L = np.array(res_l); S = np.array(res_s)
print("BTCUSDm - coin-flip entry, 1.0x ATR stop / 1.5x ATR target, $10 spread")
print("FIRST-TOUCH simulation, %s entries per side (%s total)\n" % (f"{len(A):,}", f"{2*len(A):,}"))

qs = np.quantile(A, [0, .2, .4, .6, .8, 1.0])
print("%-15s %8s %8s %8s %8s %9s %10s" % (
    "ATR(M15)", "n", "cost%", "win%", "loss%", "timeout%", "expectancy"))
print("-" * 74)
out = []
for i in range(5):
    b0, b1 = qs[i], qs[i + 1]
    sel = (A >= b0) & (A < b1) if i < 4 else (A >= b0)
    if sel.sum() < 200:
        continue
    r = np.concatenate([L[sel], S[sel]])
    med = np.median(A[sel])
    win = (r == 1).mean() * 100
    loss = (r == -1).mean() * 100
    to = (r == 0).mean() * 100
    # expectancy in ATR units: wins pay 1.5, losses cost 1.0, timeouts ~0
    exp_atr = (r == 1).mean() * TARG_ATR - (r == -1).mean() * STOP_ATR
    out.append((b0, b1, exp_atr))
    print("%-15s %8s %8.1f %8.1f %8.1f %9.1f %+10.3f" % (
        "%.0f - %.0f" % (b0, b1), f"{sel.sum():,}", SPREAD / med * 100, win, loss, to, exp_atr))
print("-" * 74)
print("""
expectancy is in ATR units per trade, after the real spread, entering at random.
POSITIVE would mean the geometry alone pays without predicting direction.
NEGATIVE means direction has to make up the difference.""")
best = max(out, key=lambda x: x[2])
worst = min(out, key=lambda x: x[2])
print("\nbest regime  ATR %.0f-%.0f  expectancy %+.3f ATR" % best)
print("worst regime ATR %.0f-%.0f  expectancy %+.3f ATR" % worst)
print("spread between them: %.3f ATR per trade" % (best[2] - worst[2]))
