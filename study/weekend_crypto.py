"""Is the BTC weekend effect real, or 2 lucky hits out of 52 tests?

BTC measured Sat -0.0212 and Sun -0.0074 against its own random control, both
significant, with a sensible mechanism (thin weekend liquidity). But that came
from a 52-test sweep where ~2.6 false positives were expected, and BTC was the
only weekend-trading instrument in that run - so it could not be cross-checked.

Crypto pairs all trade weekends, which makes them the right control group. They
are NOT fully independent (they co-move with BTC), so agreement is weaker evidence
than the count suggests - but DISAGREEMENT would be strong evidence against, since
thin weekend liquidity should affect all of them.

Expected value is modest even if it holds: avoiding the worst days reduces a
negative expectancy, it does not create a positive one. The reason to run it is
the mechanism - if low liquidity reliably hurts, that generalises beyond weekends.

Long AND short from every bar so no direction is supplied. M1 grain, live spread
per symbol, stop 0.4x ATR(M15), target 1.5x stop, 120-min cap, timeouts settled
at close, each symbol against its OWN random control.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np, math

CRYPTOS = ["BTCUSDm", "ETHUSDm", "BCHUSDm", "LTCUSDm", "XRPUSDm", "LINKUSDm", "ADAUSDm", "DOTUSDm"]
HOLD, STOP_ATR, TMULT = 120, 0.40, 1.50
WIN_R, LOSS_R = STOP_ATR * TMULT, -STOP_ATR

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")


def bars(sym, tf, want):
    if not mt5.symbol_select(sym, True):
        return None
    for k in (want, 90000, 45000, 20000, 10000):
        r = mt5.copy_rates_from_pos(sym, tf, 0, k)
        if r is not None and len(r) > 2000:
            d = pd.DataFrame(r)
            d["time"] = pd.to_datetime(d["time"], unit="s").astype("datetime64[ns]")
            return d.sort_values("time").reset_index(drop=True)


def analyse(sym):
    tick = mt5.symbol_info_tick(sym)
    if tick is None or tick.ask <= 0:
        return None
    spread = tick.ask - tick.bid
    m1 = bars(sym, mt5.TIMEFRAME_M1, 99000)
    m15 = bars(sym, mt5.TIMEFRAME_M15, 50000)
    if m1 is None or m15 is None:
        return None
    pc = m15["close"].shift(1)
    m15["atr"] = pd.concat([m15.high - m15.low, (m15.high - pc).abs(),
                            (m15.low - pc).abs()], axis=1).max(axis=1).rolling(14).mean()
    a = m15[["time", "atr"]].dropna().copy()
    a["time"] = (a["time"] + pd.Timedelta(minutes=15)).astype("datetime64[ns]")
    d = pd.merge_asof(m1, a, on="time", direction="backward").dropna(subset=["atr"]).reset_index(drop=True)
    if len(d) < 20000:
        return None

    hi, lo, cl, atr = (d["high"].to_numpy(float), d["low"].to_numpy(float),
                       d["close"].to_numpy(float), d["atr"].to_numpy(float))
    vol = d["tick_volume"].to_numpy(float)
    dow = d["time"].dt.dayofweek.to_numpy()
    n = len(cl)

    def sim(entries):
        w = l = ti = to = 0
        s1 = s2 = 0.0
        for i in entries:
            A = atr[i]
            if not np.isfinite(A) or A <= 0 or i + HOLD >= n:
                continue
            sd, td = STOP_ATR * A, STOP_ATR * A * TMULT
            win = slice(i + 1, i + 1 + HOLD)
            rmax = np.maximum.accumulate(hi[win]); rmin = np.minimum.accumulate(lo[win])
            mid, endp = cl[i], cl[i + HOLD]
            for s_ in (1, -1):
                e = mid + s_ * spread / 2
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
        return m, math.sqrt(max(s2 / tot - m * m, 0) / tot), tot

    base = np.arange(800, n - HOLD - 2)
    rm, rse, _ = sim(base)
    wk = base[dow[base] >= 5]
    wd = base[dow[base] < 5]
    if len(wk) < 2000:
        return None
    wm, wse, wtot = sim(wk)
    dm, dse, _ = sim(wd)
    # is weekend volume actually thinner? the mechanism check
    volratio = np.nanmedian(vol[wk]) / max(np.nanmedian(vol[wd]), 1e-9)
    return dict(sym=sym, rm=rm, wm=wm, dm=dm, wtot=wtot,
                two=2 * math.sqrt(wse ** 2 + rse ** 2), volratio=volratio)


print("%-9s %9s %10s %10s %10s %9s  %s"
      % ("symbol", "wkend n", "random", "weekend", "weekday", "wkend vol", "verdict"))
print("-" * 80)
worse = better = 0
rows = []
for s in CRYPTOS:
    try:
        r = analyse(s)
    except Exception as ex:
        print("%-9s failed: %s" % (s, type(ex).__name__)); continue
    if r is None:
        print("%-9s no usable data / too few weekend bars" % s); continue
    diff = r["wm"] - r["rm"]
    sig = abs(diff) > r["two"]
    v = ("weekend WORSE" if diff < 0 else "weekend BETTER") if sig else "no difference"
    if sig and diff < 0: worse += 1
    if sig and diff > 0: better += 1
    rows.append(r)
    print("%-9s %9s %10.4f %10.4f %10.4f %8.0f%%  %s"
          % (s, f"{r['wtot']:,}", r["rm"], r["wm"], r["dm"], r["volratio"] * 100, v))
mt5.shutdown()
print("-" * 80)
print("\n%d of %d cryptos show weekends significantly WORSE, %d better."
      % (worse, len(rows), better))
if rows:
    print("median weekend volume as %% of weekday: %.0f%%"
          % (100 * float(np.median([r["volratio"] for r in rows]))))
print("""
If most cryptos agree AND weekend volume is genuinely thinner, the thin-liquidity
mechanism is supported and probably generalises beyond weekends. If only BTC shows
it, the original hit was one of the ~2.6 false positives that 52 tests predicted.""")
