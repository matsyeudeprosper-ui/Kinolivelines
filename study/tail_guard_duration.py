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
o2,h2,l2,c2,tm2 = o[HALF:],h[HALF:],l[HALF:],c[HALF:],tm[HALF:]
N2 = N - HALF

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

sig2 = signals_reversal(o2,h2,l2,c2,N2)
trades = []
pending = None; in_pos = False; pos_L=None; pos_entry=None; pos_entry_t=None
for j in range(N2):
    if pending is not None:
        L, entry, et = pending
        in_pos = True; pos_L=L; pos_entry=entry; pos_entry_t=et; pending=None
    if j in sig2 and j+1 < N2 and not in_pos:
        L = (sig2[j]==1); SP = c2[j]*SPCT
        entry = o2[j+1]+SP if L else o2[j+1]
        pending = (L, entry, tm2[j+1])
    if in_pos:
        tp_price = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
        sl_price = pos_entry-SL_PTS if pos_L else pos_entry+SL_PTS
        hit_tp = (h2[j]>=tp_price) if pos_L else (l2[j]<=tp_price)
        hit_sl = (l2[j]<=sl_price) if pos_L else (h2[j]>=sl_price)
        if hit_tp or hit_sl:
            pnl = -SL_PTS*PT if (hit_sl and not (hit_tp and not hit_sl)) else TP_PTS*PT
            if hit_tp and hit_sl: pnl = -SL_PTS*PT
            elif hit_tp: pnl = TP_PTS*PT
            else: pnl = -SL_PTS*PT
            trades.append((pos_entry_t, tm2[j], pnl)); in_pos = False

dur_h = np.array([(x[1]-x[0])/3600 for x in trades])
pnl = np.array([x[2] for x in trades])
wins_d = dur_h[pnl>0]; loss_d = dur_h[pnl<0]

print(f"total trades: {len(trades)}\n")
print("ALL TRADES")
print(f"  average: {dur_h.mean():.1f}h ({dur_h.mean()/24:.2f} days)   median: {np.median(dur_h):.1f}h ({np.median(dur_h)/24:.2f} days)")
print(f"  min: {dur_h.min():.1f}h   max: {dur_h.max():.1f}h ({dur_h.max()/24:.1f} days)")
print("\nWINS only")
print(f"  average: {wins_d.mean():.1f}h ({wins_d.mean()/24:.2f} days)   median: {np.median(wins_d):.1f}h")
print(f"  min: {wins_d.min():.1f}h   max: {wins_d.max():.1f}h ({wins_d.max()/24:.1f} days)")
print("\nLOSSES only")
print(f"  average: {loss_d.mean():.1f}h ({loss_d.mean()/24:.1f} days)   values: {sorted(loss_d/24)} days each")

pct = np.percentile(dur_h, [25,50,75,90,95])
print(f"\nspread (all trades): p25 {pct[0]:.1f}h  p50 {pct[1]:.1f}h  p75 {pct[2]:.1f}h  p90 {pct[3]:.1f}h  p95 {pct[4]:.1f}h")
