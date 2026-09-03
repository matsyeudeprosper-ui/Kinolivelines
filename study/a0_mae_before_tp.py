"""Same MAE-before-target analysis, but for A0 - the ACTUAL live bot's
entry (every reversal brick), not the Swing Reclaim idea. This is what
harvest_live_bot.py actually trades, so this is the relevant one for
explaining real live losses."""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
TARGET_USD = 2.50
TARGET_PTS = TARGET_USD / PT
WINDOW = 500

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
N = len(c)


def signals_reversal():
    revs = {}; ao = ac = float(o[0]); d = 0; pd_ = 0
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                base = ao if d == -1 else ac; ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                base = ao if d == 1 else ac; ao, ac, d = base, base - B, -1
            else:
                break
            if pd_ and d != pd_:
                revs.setdefault(i, d)
            pd_ = d
    return revs


sigs = signals_reversal()
mae_reached = []; mae_never = []
peak_reached = []

for j, dirn in sigs.items():
    if j + 1 >= N:
        continue
    ent_bar = j + 1
    SP = c[j] * SPCT
    L = (dirn == 1)
    entry = o[ent_bar] + SP if L else o[ent_bar]
    end = min(N, ent_bar + WINDOW)
    best = 0.0; worst_adverse = 0.0; reached = False
    for k in range(ent_bar, end):
        fav = (h[k] - entry) if L else (entry - l[k])
        adv = (entry - l[k]) if L else (h[k] - entry)
        worst_adverse = max(worst_adverse, adv)
        if fav > best:
            best = fav
        if not reached and best >= TARGET_PTS:
            reached = True
            mae_reached.append(worst_adverse)
            break
    if not reached:
        mae_never.append(worst_adverse)

mae_r = np.array(mae_reached); mae_n = np.array(mae_never)
print(f"A0 (actual live bot entry) - target ${TARGET_USD:.2f}")
print(f"n signals: {len(sigs)}   reach target: {len(mae_r)} ({100*len(mae_r)/len(sigs):.1f}%)   never: {len(mae_n)}")
print()
print("MAE (drawdown) endured BEFORE hitting target, among trades that DID hit it:")
print(f"  mean ${mae_r.mean()*PT:5.2f}   median ${np.median(mae_r)*PT:5.2f}")
for p in (50,75,90,95,99):
    print(f"  p{p:<3} ${np.percentile(mae_r,p)*PT:6.2f}  ({np.percentile(mae_r,p):.0f} pts)")
print(f"  max  ${mae_r.max()*PT:6.2f}")
print()
print("If a stop loss were set at various sizes, share of EVENTUAL WINNERS it would have cut short:")
for sl_usd in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.5, 10.0):
    sl_pts = sl_usd / PT
    cut = 100*np.mean(mae_r > sl_pts)
    print(f"  SL ${sl_usd:5.2f} ({sl_pts:5.0f}pts): would have stopped out {cut:5.1f}% of trades that eventually reached the ${TARGET_USD:.2f} target")
