"""Honest version: calibrate SL from a RARITY PERCENTILE on the FIRST HALF
only, then test on the untouched SECOND HALF. No whole-dataset lookahead.
TP = $1 flat, single position, no daily limit, same live-bot entry (A0).
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
TP_USD = 1.0
TP_PTS = TP_USD / PT
CALIBRATE_WINDOW = 2000

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
N = len(c)
HALF = N // 2
print(f"total bars {N}   first half [0:{HALF}]   second half [{HALF}:{N}]\n")


def signals_reversal(o, h, l, c, N):
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


def worst_adverse_distribution(o, h, l, c, N, sigs):
    vals = []
    for j, dirn in sigs.items():
        if j + 1 >= N:
            continue
        ent_bar = j + 1
        SP = c[j] * SPCT
        L = (dirn == 1)
        entry = o[ent_bar] + SP if L else o[ent_bar]
        end = min(N, ent_bar + CALIBRATE_WINDOW)
        worst = 0.0
        for k in range(ent_bar, end):
            adv = (entry - l[k]) if L else (h[k] - entry)
            if adv > worst:
                worst = adv
        vals.append(worst)
    return np.array(vals)


def run(o, h, l, c, N, sigs, SL_PTS):
    bal = 1000.0; peak = bal; mdd = 0.0; lo = bal
    wins = losses = 0; pnl_list = []
    pending = None; in_pos = False; pos_L = None; pos_entry = None
    for j in range(N):
        if pending is not None:
            L, entry = pending
            in_pos = True; pos_L = L; pos_entry = entry; pending = None
        if j in sigs and j + 1 < N and not in_pos:
            L = (sigs[j] == 1)
            SP = c[j] * SPCT
            entry = o[j+1] + SP if L else o[j+1]
            pending = (L, entry)
        if in_pos:
            tp_price = pos_entry + TP_PTS if pos_L else pos_entry - TP_PTS
            sl_price = pos_entry - SL_PTS if pos_L else pos_entry + SL_PTS
            hit_tp = (h[j] >= tp_price) if pos_L else (l[j] <= tp_price)
            hit_sl = (l[j] <= sl_price) if pos_L else (h[j] >= sl_price)
            if hit_tp and hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses += 1; in_pos = False
            elif hit_tp:
                bal += TP_PTS*PT; pnl_list.append(TP_PTS*PT); wins += 1; in_pos = False
            elif hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses += 1; in_pos = False
        peak = max(peak, bal); mdd = max(mdd, peak-bal); lo = min(lo, bal)
        if bal <= 0:
            return dict(dead=True)
    pnl = np.array(pnl_list) if pnl_list else np.array([0.0])
    return dict(dead=False, trades=len(pnl), wins=wins, losses=losses, end=bal, lo=lo,
                mdd=mdd, mddp=100*mdd/peak, exp=pnl.mean(), worst=pnl.min(),
                winrate=100*wins/max(1,len(pnl)))


# ---- calibrate on FIRST HALF only ----
o1,h1,l1,c1 = o[:HALF],h[:HALF],l[:HALF],c[:HALF]
sig1 = signals_reversal(o1,h1,l1,c1,HALF)
dist1 = worst_adverse_distribution(o1,h1,l1,c1,HALF,sig1)
print(f"first-half calibration: {len(dist1)} signals measured\n")
print(f"{'rarity':>10} {'SL($)':>8}")
percentiles = {"1 in 20 (95%)":95, "1 in 100 (99%)":99, "1 in 200 (99.5%)":99.5, "1 in 1000 (99.9%)":99.9}
sl_choices = {}
for label, p in percentiles.items():
    sl = np.percentile(dist1, p) * PT
    sl_choices[label] = sl
    print(f"{label:>18} ${sl:>7.2f}")

# ---- test each SL on the SECOND HALF (unseen) ----
o2,h2,l2,c2 = o[HALF:],h[HALF:],l[HALF:],c[HALF:]
N2 = N - HALF
sig2 = signals_reversal(o2,h2,l2,c2,N2)

print(f"\n=== applied to the SECOND HALF (never seen during calibration), TP=$1 flat ===")
print(f"{'rarity':>18} {'SL':>8} {'trades':>7} {'win%':>6} {'ended':>10} {'lowest':>9} {'worstDD':>9} {'exp/trade':>10}")
for label in percentiles:
    SL_USD = sl_choices[label]
    SL_PTS = SL_USD / PT
    z = run(o2,h2,l2,c2,N2,sig2,SL_PTS)
    if z["dead"]:
        print(f"{label:>18} ${SL_USD:>7.2f}  *** DIED ***")
        continue
    print(f"{label:>18} ${SL_USD:>7.2f} {z['trades']:>7} {z['winrate']:>5.1f}% "
          f"${z['end']:>9,.2f} ${z['lo']:>8,.2f} ${z['mdd']:>8,.2f} ${z['exp']:>+9.3f}")

print(f"\n(for reference: same SL choices tested on the FIRST half they were calibrated on - in-sample, optimistic)")
print(f"{'rarity':>18} {'SL':>8} {'trades':>7} {'win%':>6} {'ended':>10} {'lowest':>9} {'worstDD':>9} {'exp/trade':>10}")
for label in percentiles:
    SL_USD = sl_choices[label]
    SL_PTS = SL_USD / PT
    z = run(o1,h1,l1,c1,HALF,sig1,SL_PTS)
    if z["dead"]:
        print(f"{label:>18} ${SL_USD:>7.2f}  *** DIED ***")
        continue
    print(f"{label:>18} ${SL_USD:>7.2f} {z['trades']:>7} {z['winrate']:>5.1f}% "
          f"${z['end']:>9,.2f} ${z['lo']:>8,.2f} ${z['mdd']:>8,.2f} ${z['exp']:>+9.3f}")
