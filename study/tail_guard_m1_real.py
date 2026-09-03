"""Real M1 version of Tail Guard - SL calibrated from M1 data itself this
time (not reused from H1). Only ~55 days of M1 broker history exists, split
first-half calibrates / second-half tests (single split, NOT multi-anchor -
not enough data for that). Same TP=$1, cap=1, 1-in-100 percentile SL.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import Counter

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
TP_USD = 1.0; TP_PTS = TP_USD / PT
CALIBRATE_WINDOW = 4000  # minutes forward, generous for M1 (~2.8 days)

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
mt5.shutdown()
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c)
HALF = N // 2
print(f"M1 bars {N}   {datetime.utcfromtimestamp(tm[0])} -> {datetime.utcfromtimestamp(tm[-1])}   "
      f"({(tm[-1]-tm[0])/86400:.1f} days)\n")


def signals_reversal(o,h,l,c,N):
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
            else: break
            if pd_ and d != pd_: revs.setdefault(i, d)
            pd_ = d
    return revs


def worst_adverse_distribution(o,h,l,c,N,sigs):
    vals = []
    for j, dirn in sigs.items():
        if j+1 >= N: continue
        ent_bar = j+1; SP = c[j]*SPCT; L = (dirn==1)
        entry = o[ent_bar]+SP if L else o[ent_bar]
        end = min(N, ent_bar+CALIBRATE_WINDOW)
        worst = 0.0
        for k in range(ent_bar, end):
            adv = (entry-l[k]) if L else (h[k]-entry)
            if adv > worst: worst = adv
        vals.append(worst)
    return np.array(vals)


def run(o,h,l,c,tm,N,sigs,SL_PTS):
    bal = 1000.0; peak = bal; mdd = 0.0; lo = bal
    wins = losses = 0; pnl_list = []; durs = []
    pending = None; in_pos = False; pos_L=None; pos_entry=None; pos_entry_t=None
    entry_days = []
    for j in range(N):
        if pending is not None:
            L, entry, et = pending
            in_pos = True; pos_L=L; pos_entry=entry; pos_entry_t=et; pending=None
        if j in sigs and j+1 < N and not in_pos:
            L = (sigs[j]==1); SP = c[j]*SPCT
            entry = o[j+1]+SP if L else o[j+1]
            pending = (L, entry, tm[j+1])
            entry_days.append(datetime.utcfromtimestamp(tm[j+1]).date())
        if in_pos:
            tp_price = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            sl_price = pos_entry-SL_PTS if pos_L else pos_entry+SL_PTS
            hit_tp = (h[j]>=tp_price) if pos_L else (l[j]<=tp_price)
            hit_sl = (l[j]<=sl_price) if pos_L else (h[j]>=sl_price)
            if hit_tp or hit_sl:
                durs.append((tm[j]-pos_entry_t)/60)  # minutes
            if hit_tp and hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses+=1; in_pos=False
            elif hit_tp:
                bal += TP_PTS*PT; pnl_list.append(TP_PTS*PT); wins+=1; in_pos=False
            elif hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses+=1; in_pos=False
        peak = max(peak, bal); mdd = max(mdd, peak-bal); lo = min(lo, bal)
        if bal <= 0:
            return dict(dead=True, entry_days=entry_days)
    pnl = np.array(pnl_list) if pnl_list else np.array([0.0])
    durs = np.array(durs) if durs else np.array([0.0])
    return dict(dead=False, trades=len(pnl), wins=wins, losses=losses, end=bal, lo=lo, mdd=mdd,
                winrate=100*wins/max(1,len(pnl)), entry_days=entry_days,
                mean_dur_min=durs.mean(), median_dur_min=np.median(durs), max_dur_min=durs.max())


o1,h1,l1,c1 = o[:HALF],h[:HALF],l[:HALF],c[:HALF]
sig1 = signals_reversal(o1,h1,l1,c1,HALF)
dist1 = worst_adverse_distribution(o1,h1,l1,c1,HALF,sig1)
SL_USD = np.percentile(dist1, 99) * PT
SL_PTS = SL_USD / PT
print(f"first-half calibration: {len(sig1)} signals, SL (1-in-100) = ${SL_USD:.2f}\n")

o2,h2,l2,c2,tm2 = o[HALF:],h[HALF:],l[HALF:],c[HALF:],tm[HALF:]
N2 = N - HALF
sig2 = signals_reversal(o2,h2,l2,c2,N2)
z = run(o2,h2,l2,c2,tm2,N2,sig2,SL_PTS)

span_days = (tm2[-1]-tm2[0])/86400
day_counter = Counter(z["entry_days"])
total_days = len(set(datetime.utcfromtimestamp(t).date() for t in tm2))

print(f"=== SECOND HALF test ({span_days:.1f} days) ===")
if z["dead"]:
    print("*** DIED ***")
else:
    print(f"trades: {z['trades']}   win%: {z['winrate']:.1f}%   losses: {z['losses']}")
    print(f"ended: ${z['end']:,.2f}   lowest: ${z['lo']:,.2f}   worst dd: ${z['mdd']:,.2f}")
    print(f"duration: mean {z['mean_dur_min']:.1f}min   median {z['median_dur_min']:.1f}min   max {z['max_dur_min']:.0f}min ({z['max_dur_min']/1440:.1f} days)")
    print(f"days with >=1 trade: {len(day_counter)}/{total_days} ({100*len(day_counter)/total_days:.1f}%)")
    print(f"avg trades/day: {z['trades']/span_days:.2f}")
