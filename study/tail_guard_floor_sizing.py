"""Find a safety-floor size that catches genuinely rare cases without
interfering with normal trade patience. For every A0 signal (same entry as
live), simulate the FULL trade life (entry to TP or the real wide SL,
44,439 pts / $444.39 at 0.01 lots), and record the worst adverse excursion
reached along the way - win or lose. Report the percentile distribution so
a floor can be picked to match a chosen rarity, converted to $ at 0.05 lots.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
TP_PTS = 100.0
SL_PTS = 44439.0  # the actual live SL, in points
FROM = datetime(2022, 1, 1)
LOTS_LIVE = 0.05


def signals_reversal(o, h, l, c, N):
    revs = {}
    ao = ac = float(o[0])
    d = 0
    pd_ = 0
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                base = ao if d == -1 else ac
                ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                base = ao if d == 1 else ac
                ao, ac, d = base, base - B, -1
            else:
                break
            if pd_ and d != pd_:
                revs.setdefault(i, d)
            pd_ = d
    return revs


mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
N = len(c)

sigs = signals_reversal(o, h, l, c, N)

worst_each = []
for j, dirn in sigs.items():
    if j + 1 >= N:
        continue
    ent_bar = j + 1
    SP = c[j] * SPCT
    L = (dirn == 1)
    entry = o[ent_bar] + SP if L else o[ent_bar]
    worst = 0.0
    for k in range(ent_bar, N):
        tp_price = entry + TP_PTS if L else entry - TP_PTS
        sl_price = entry - SL_PTS if L else entry + SL_PTS
        hit_tp = (h[k] >= tp_price) if L else (l[k] <= tp_price)
        hit_sl = (l[k] <= sl_price) if L else (h[k] >= sl_price)
        adv = (entry - l[k]) if L else (h[k] - entry)
        if adv > worst:
            worst = adv
        if hit_tp or hit_sl:
            break
    worst_each.append(worst)

worst_each = np.array(worst_each)
print(f"total trades simulated (full life, entry to real exit): {len(worst_each)}\n")
print("worst-adverse-excursion-during-the-trade, percentile table:")
print(f"{'pctile':>8} {'points':>10} {'$ at 0.01L':>12} {'$ at 0.05L (live)':>18}")
for p in (50, 60, 70, 75, 80, 85, 90, 95, 97, 98, 99, 99.5, 99.9, 100):
    val = np.percentile(worst_each, p)
    print(f"{p:>7.1f}% {val:>10.1f} ${val*PT:>10.2f}   ${val*PT*LOTS_LIVE/0.01:>16.2f}")

print(f"\nhow many trades would trip various flat-dollar floors (at 0.05 lots):")
for floor_usd in (50, 100, 150, 200, 300, 400, 500, 750, 1000):
    floor_pts = floor_usd / (PT * LOTS_LIVE / 0.01)
    trip_rate = 100 * np.mean(worst_each >= floor_pts)
    print(f"  floor ${floor_usd:>5.0f}  ->  {trip_rate:5.2f}% of ALL trades would exceed this "
          f"(1 in {1/max(trip_rate/100,1e-9):.0f})")
