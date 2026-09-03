"""Tail Guard with a MAX HOLD TIME added - force-close any trade still
open past the cutoff, at market (whatever P&L it has then), instead of
letting it run for weeks/months. Cutoff calibrated on FIRST HALF duration
distribution (95th percentile), tested honestly on SECOND HALF.
Same TP=$1 / SL=$311.48 (1-in-100) otherwise.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
TP_USD = 1.0; TP_PTS = TP_USD / PT
SL_USD = 311.48; SL_PTS = SL_USD / PT

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c); HALF = N // 2

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


def run(o,h,l,c,tm,N,sigs,max_hold_h=None):
    bal = 1000.0; peak = bal; mdd = 0.0; lo = bal
    wins = losses = timeouts = 0; pnl_list = []
    durs = []
    pending = None; in_pos = False; pos_L=None; pos_entry=None; pos_entry_t=None
    for j in range(N):
        if pending is not None:
            L, entry, et = pending
            in_pos = True; pos_L=L; pos_entry=entry; pos_entry_t=et; pending=None
        if j in sigs and j+1 < N and not in_pos:
            L = (sigs[j]==1); SP = c[j]*SPCT
            entry = o[j+1]+SP if L else o[j+1]
            pending = (L, entry, tm[j+1])
        if in_pos:
            tp_price = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            sl_price = pos_entry-SL_PTS if pos_L else pos_entry+SL_PTS
            hit_tp = (h[j]>=tp_price) if pos_L else (l[j]<=tp_price)
            hit_sl = (l[j]<=sl_price) if pos_L else (h[j]>=sl_price)
            hours_open = (tm[j]-pos_entry_t)/3600
            timed_out = (max_hold_h is not None) and (hours_open >= max_hold_h) and not (hit_tp or hit_sl)
            if hit_tp and hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses+=1; in_pos=False; durs.append(hours_open)
            elif hit_tp:
                bal += TP_PTS*PT; pnl_list.append(TP_PTS*PT); wins+=1; in_pos=False; durs.append(hours_open)
            elif hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses+=1; in_pos=False; durs.append(hours_open)
            elif timed_out:
                mtm = (c[j]-pos_entry) if pos_L else (pos_entry-c[j])
                bal += mtm*PT; pnl_list.append(mtm*PT); timeouts+=1; in_pos=False; durs.append(hours_open)
                if mtm > 0: wins += 1
                else: losses += 1
        peak = max(peak, bal); mdd = max(mdd, peak-bal); lo = min(lo, bal)
        if bal <= 0:
            return dict(dead=True)
    pnl = np.array(pnl_list) if pnl_list else np.array([0.0])
    return dict(dead=False, trades=len(pnl), wins=wins, losses=losses, timeouts=timeouts,
                end=bal, lo=lo, mdd=mdd, mddp=100*mdd/peak if peak else 0,
                winrate=100*wins/max(1,len(pnl)), exp=pnl.mean(), worst=pnl.min(),
                durs=np.array(durs))


o1,h1,l1,c1,tm1 = o[:HALF],h[:HALF],l[:HALF],c[:HALF],tm[:HALF]
sig1 = signals_reversal(o1,h1,l1,c1,HALF)
z1_uncapped = run(o1,h1,l1,c1,tm1,HALF,sig1,max_hold_h=None)
MAX_HOLD = np.percentile(z1_uncapped["durs"], 95)
print(f"first-half calibration: 95th percentile duration = {MAX_HOLD:.1f}h ({MAX_HOLD/24:.1f} days) -> cutoff\n")

o2,h2,l2,c2,tm2 = o[HALF:],h[HALF:],l[HALF:],c[HALF:],tm[HALF:]
N2 = N - HALF
sig2 = signals_reversal(o2,h2,l2,c2,N2)

print("=== SECOND HALF (out-of-sample) ===")
zU = run(o2,h2,l2,c2,tm2,N2,sig2,max_hold_h=None)
print(f"UNCAPPED  trades {zU['trades']}  wins {zU['wins']}  losses {zU['losses']}  "
      f"ended ${zU['end']:,.2f}  lowest ${zU['lo']:,.2f}  dd ${zU['mdd']:,.2f}  worst ${zU['worst']:+.2f}  exp ${zU['exp']:+.3f}")

zC = run(o2,h2,l2,c2,tm2,N2,sig2,max_hold_h=MAX_HOLD)
print(f"CAPPED@{MAX_HOLD:.0f}h trades {zC['trades']}  wins {zC['wins']}  losses {zC['losses']}  timeouts {zC['timeouts']}  "
      f"ended ${zC['end']:,.2f}  lowest ${zC['lo']:,.2f}  dd ${zC['mdd']:,.2f}  worst ${zC['worst']:+.2f}  exp ${zC['exp']:+.3f}")

print(f"\nTHE 2 REAL LOSSES - what the time cap does to them (uncapped they cost $311.47 each, took 63 & 83.5 days):")
print(f"  (any trade force-closed at {MAX_HOLD:.1f}h is exited at THAT MOMENT'S floating P&L, win or lose)")
