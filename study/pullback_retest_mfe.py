"""Average peak-possible-profit (MFE) for the pullback-retest entry signal
(user asked, 2026-08-13). Same brick/signal definition as pullback_retest.py.
For every F signal, entry = next bar's open (same alignment as the main
backtest), then scan forward up to WINDOW bars tracking the best price seen
in the trade's favor (intrabar high/low). This measures the entry's raw
potential, independent of the harvest bot's TP/recovery/cap money management.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
WINDOW = 500  # bars (hours) forward cap

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
N = len(c)


def signals_pullback_retest():
    sigs = {}; ao = ac = float(o[0]); d = 0
    last_high = None; last_low = None
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                if d == -1:
                    last_low = ac
                base = ao if d == -1 else ac; ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                if d == 1:
                    last_high = ac
                base = ao if d == 1 else ac; ao, ac, d = base, base - B, -1
            else:
                break
        if last_high is not None and h[i] >= last_high:
            sigs.setdefault(i, 1); last_high = None
        if last_low is not None and l[i] <= last_low:
            sigs.setdefault(i, -1); last_low = None
    return sigs


sigs = signals_pullback_retest()
mfe_pts = []
mfe_usd = []
censored = 0
brick_at_entry_pts = []

for j, dirn in sigs.items():
    if j + 1 >= N:
        continue
    ent_bar = j + 1
    SP = c[j] * SPCT
    L = (dirn == 1)
    entry = o[ent_bar] + SP if L else o[ent_bar]
    best = 0.0
    end = min(N, ent_bar + WINDOW)
    for k in range(ent_bar, end):
        if L:
            best = max(best, h[k] - entry)
        else:
            best = max(best, entry - l[k])
    if end < N and end == ent_bar + WINDOW:
        censored += 1
    mfe_pts.append(best)
    mfe_usd.append(best * PT)
    brick_at_entry_pts.append(c[j] * PCT)

mfe_pts = np.array(mfe_pts); mfe_usd = np.array(mfe_usd); brick_at_entry_pts = np.array(brick_at_entry_pts)
tp_target_pts = 5 * brick_at_entry_pts  # the live bot's 5-brick TP, in points, per-signal brick size

print(f"signals with a forward window: {len(mfe_pts)}  (censored at {WINDOW}h cap: {censored})")
print(f"\nMFE in points (price units):")
print(f"  mean   {mfe_pts.mean():8.1f}")
print(f"  median {np.median(mfe_pts):8.1f}")
print(f"  p25    {np.percentile(mfe_pts,25):8.1f}   p75 {np.percentile(mfe_pts,75):8.1f}")
print(f"\nMFE in $ at 0.01 lots:")
print(f"  mean   ${mfe_usd.mean():8.2f}")
print(f"  median ${np.median(mfe_usd):8.2f}")
print(f"\ncompare to the live bot's 5-brick TP target (varies with price, ~$250 pts today):")
print(f"  mean TP target today-equivalent: {tp_target_pts.mean():8.1f} pts")
print(f"  share of signals whose MFE reached/exceeded their own 5-brick TP: {100*np.mean(mfe_pts >= tp_target_pts):5.1f}%")
print(f"  share of signals whose MFE reached at least 1 brick ({brick_at_entry_pts.mean():.0f}pt avg): {100*np.mean(mfe_pts >= brick_at_entry_pts):5.1f}%")
print(f"  share of signals whose MFE reached at least 10 bricks: {100*np.mean(mfe_pts >= 10*brick_at_entry_pts):5.1f}%")
