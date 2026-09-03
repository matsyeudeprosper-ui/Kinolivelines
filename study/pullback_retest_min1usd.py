"""Does every Swing Reclaim entry reach at least $1 (100 points at 0.01 lots)
of favorable move at some point? Check across windows, and find the true
worst case (minimum peak ever seen, unbounded up to 500h)."""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
TARGET_USD = 1.0
TARGET_PTS = TARGET_USD / PT  # 100 points

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

WINDOW = 500  # generous, for "does it EVER reach $1"
worst_peak_pts = None; worst_j = None
hours_to_1usd = []  # None if never within WINDOW
never = 0
peaks_all = []

for j, dirn in sigs.items():
    if j + 1 >= N:
        continue
    ent_bar = j + 1
    SP = c[j] * SPCT
    L = (dirn == 1)
    entry = o[ent_bar] + SP if L else o[ent_bar]
    end = min(N, ent_bar + WINDOW)
    best = 0.0
    reached_at = None
    for k in range(ent_bar, end):
        fav = (h[k] - entry) if L else (entry - l[k])
        if fav > best:
            best = fav
        if reached_at is None and best >= TARGET_PTS:
            reached_at = k - ent_bar
    peaks_all.append(best)
    if worst_peak_pts is None or best < worst_peak_pts:
        worst_peak_pts = best; worst_j = j
    if reached_at is not None:
        hours_to_1usd.append(reached_at)
    else:
        never += 1

peaks_all = np.array(peaks_all)
hours_to_1usd = np.array(hours_to_1usd)

print(f"n = {len(peaks_all)} entries checked (up to {WINDOW}h forward each)\n")
print(f"reached at least $1 ({TARGET_PTS:.0f} pts) AT SOME POINT: {100*(1-never/len(peaks_all)):.1f}%   ({never} never did, out of {len(peaks_all)})")
if len(hours_to_1usd):
    print(f"time to reach $1: mean {hours_to_1usd.mean():.1f}h   median {np.median(hours_to_1usd):.0f}h   p90 {np.percentile(hours_to_1usd,90):.0f}h")
print(f"\nworst case ever seen: peak only {worst_peak_pts:.1f} pts (${worst_peak_pts*PT:.2f}) at signal index {worst_j}")

print()
for tgt_usd in (0.5, 1.0, 2.0, 2.5, 5.0):
    tgt_pts = tgt_usd / PT
    print(f"share reaching >= ${tgt_usd:.2f}: {100*np.mean(peaks_all >= tgt_pts):5.1f}%")
