"""Before hitting $1 profit, how far against you did price move
(max adverse excursion)? Same Swing Reclaim entries, same 500h window."""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
TARGET_USD = 1.0
TARGET_PTS = TARGET_USD / PT
WINDOW = 500

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
mae_pts_reached = []   # MAE before hitting $1, for trades that DID reach $1
mae_pts_never = []     # worst MAE over the whole window, for trades that never reached $1
reached_flag = []

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
        adv = (entry - l[k]) if L else (h[k] - entry)   # adverse = negative of fav's mirror
        worst_adverse = max(worst_adverse, adv)
        if fav > best:
            best = fav
        if not reached and best >= TARGET_PTS:
            reached = True
            mae_pts_reached.append(worst_adverse)
            break
    if not reached:
        mae_pts_never.append(worst_adverse)
    reached_flag.append(reached)

mae_r = np.array(mae_pts_reached)
mae_n = np.array(mae_pts_never)

print(f"trades that DID reach $1 (n={len(mae_r)}):")
print(f"  max adverse move seen BEFORE hitting $1 - mean {mae_r.mean():6.1f}pts (${mae_r.mean()*PT:5.2f})   "
      f"median {np.median(mae_r):6.1f}pts (${np.median(mae_r)*PT:5.2f})")
print(f"  p90 {np.percentile(mae_r,90):6.1f}pts (${np.percentile(mae_r,90)*PT:5.2f})   "
      f"worst ever {mae_r.max():6.1f}pts (${mae_r.max()*PT:5.2f})")
print(f"  share that went straight to $1 with ZERO adverse move first: {100*np.mean(mae_r==0):.1f}%")
print()
for lvl in (0.20, 0.50, 1.0, 2.0):
    print(f"  share whose adverse move before $1 stayed under ${lvl:.2f}: {100*np.mean(mae_r <= lvl/PT):5.1f}%")

print(f"\ntrades that NEVER reached $1 within {WINDOW}h (n={len(mae_n)}):")
if len(mae_n):
    print(f"  worst adverse move over the whole window - mean {mae_n.mean():6.1f}pts (${mae_n.mean()*PT:5.2f})   "
          f"median {np.median(mae_n):6.1f}pts (${np.median(mae_n)*PT:5.2f})")
