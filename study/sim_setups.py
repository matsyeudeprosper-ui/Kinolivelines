"""Rebuild the setups KinoliveLines would genuinely have been woken for.

This is NOT "a trade every hour". The daemon only asks for a decision under a specific
mechanical condition, and that condition is reproducible from OHLC alone:

  LEVEL SET (briefing.py, identical to the EA)
    previous completed bar high and low of H4, H1 and M15
    merged when within max(3 x spread, 0.12 x ATR_H1), higher timeframe wins
    de-duplicated, first six kept

  TRIGGER (daemon.py)
    flat, no resting orders
    price within setup_proximity_atr (0.06) x ATR_H1 of a level
    the level is "armed" - it re-arms only after price moves 2.5x that distance away
    a per-level cooldown of 1800s after it has been assessed
    M15 levels equal to the last two M15 bar extremes are skipped as self-referential

What is NOT reproducible is the DIRECTION. That call was made by a language model
reading the briefing, and no rule recovers it. So every setup is simulated twice - once
fading the level (long at support, short at resistance, the natural reading of "levels
as decision points") and once following it. Absolute P&L from either convention is
close to meaningless, because fifteen tests showed level touches do not beat a random
entry. That is fine: the question here is not whether the strategy makes money, it is
whether CROWDED FUNDING CHANGES WHAT HAPPENS to these particular setups, and that
comparison is unaffected by which direction convention is used.

This file only counts and characterises the setups. The variant simulation is separate.
"""
import MetaTrader5 as mt5
import pandas as pd, numpy as np
from datetime import datetime

SYM = "BTCUSDm"
PROX_ATR, COOLDOWN_S, REARM_MULT = 0.06, 1800, 2.5

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select(SYM, True)
tick = mt5.symbol_info_tick(SYM)
SPREAD = tick.ask - tick.bid


def bars(tf, n):
    r = mt5.copy_rates_from_pos(SYM, tf, 0, n)
    d = pd.DataFrame(r)
    d["time"] = pd.to_datetime(d["time"], unit="s")
    return d


m15 = bars(mt5.TIMEFRAME_M15, 50000)
h1 = bars(mt5.TIMEFRAME_H1, 45000)
h4 = bars(mt5.TIMEFRAME_H4, 12000)
mt5.shutdown()


def atr_of(d, n=14):
    pc = d["close"].shift(1)
    return pd.concat([d.high - d.low, (d.high - pc).abs(),
                      (d.low - pc).abs()], axis=1).max(axis=1).rolling(n).mean()


for d in (m15, h1, h4):
    d["atr"] = atr_of(d)

# index of the last CLOSED higher-timeframe bar as of each M15 bar's open
m15["h1i"] = np.searchsorted(h1["time"].values, m15["time"].values, side="right") - 1
m15["h4i"] = np.searchsorted(h4["time"].values, m15["time"].values, side="right") - 1

h1H, h1L = h1.high.to_numpy(), h1.low.to_numpy()
h4H, h4L = h4.high.to_numpy(), h4.low.to_numpy()
mH, mL = m15.high.to_numpy(), m15.low.to_numpy()
mC, mO = m15.close.to_numpy(), m15.open.to_numpy()
a15, a1 = m15.atr.to_numpy(), h1.atr.to_numpy()
times = m15["time"].to_numpy()


def level_set(i):
    """The six levels briefing.py would print, using only bars closed before bar i."""
    h1i, h4i = m15["h1i"].iloc[i], m15["h4i"].iloc[i]
    if h1i < 1 or h4i < 1 or i < 1:
        return []
    A1 = a1[h1i]
    if not np.isfinite(A1) or A1 <= 0:
        return []
    raw = [[h4H[h4i - 1], True, 3, "H4"], [h4L[h4i - 1], False, 3, "H4"],
           [h1H[h1i - 1], True, 2, "H1"], [h1L[h1i - 1], False, 2, "H1"],
           [mH[i - 1], True, 1, "M15"], [mL[i - 1], False, 1, "M15"]]
    tol = max(SPREAD * 3.0, A1 * 0.12)
    raw.sort(key=lambda r: r[0])
    keep = [True] * len(raw)
    for x in range(len(raw)):
        if not keep[x]:
            continue
        for y in range(x + 1, len(raw)):
            if keep[y] and abs(raw[x][0] - raw[y][0]) <= tol:
                if raw[y][2] > raw[x][2]:
                    raw[x] = raw[y]
                keep[y] = False
    merged = [r for k, r in zip(keep, raw) if k]
    if not merged:
        return []
    md = merged[0][0] * 0.001
    out = []
    for r in merged:
        if not out or r[1] != out[-1][1] or abs(r[0] - out[-1][0]) >= md:
            out.append(r)
        if len(out) >= 6:
            break
    return out


armed, declined, setups = {}, {}, []
start = max(60, int(np.argmax(np.isfinite(a15))) + 1)
for i in range(start, len(m15) - 1):
    A1 = a1[m15["h1i"].iloc[i]]
    A15 = a15[i]
    if not (np.isfinite(A1) and A1 > 0 and np.isfinite(A15) and A15 > 0):
        continue
    now = times[i].astype("datetime64[s]").astype(int)
    mid = mC[i]
    near = PROX_ATR * A1
    fresh = {round(mH[i - 1], 2), round(mL[i - 1], 2),
             round(mH[i - 2], 2), round(mL[i - 2], 2)} if i >= 2 else set()

    for lp, isHigh, prio, nm in level_set(i):
        k = round(lp, 2)
        if nm == "M15" and k in fresh:
            continue
        dist = abs(mid - lp)
        if dist <= near:
            if now - declined.get(k, -10 ** 9) < COOLDOWN_S:
                continue
            if armed.get(k, True):
                armed[k] = False
                declined[k] = now
                setups.append({"i": i, "time": m15["time"].iloc[i], "level": lp,
                               "isHigh": isHigh, "tf": nm, "mid": mid,
                               "atr15": A15, "atr1": A1})
        elif dist > near * REARM_MULT:
            armed[k] = True

s = pd.DataFrame(setups)
print("SETUP RECONSTRUCTION - what the daemon would have woken for")
print("M15 history: %s bars, %s to %s"
      % (f"{len(m15):,}", m15.time.min().date(), m15.time.max().date()))
print("live spread used for the merge tolerance: $%.2f\n" % SPREAD)
print("total setups: %s   (%.1f per day)"
      % (f"{len(s):,}", len(s) / max((m15.time.max() - m15.time.min()).days, 1)))
print("\nby level timeframe:")
print(s["tf"].value_counts().to_string())
print("\nresistance vs support:")
print(s["isHigh"].map({True: "resistance", False: "support"}).value_counts().to_string())
print("\nper calendar month:")
print(s.groupby(s["time"].dt.to_period("M")).size().to_string())
s.to_csv(r"C:\Projects\KinoliveLines\study\setups.csv", index=False)
print("\n-> study/setups.csv")
