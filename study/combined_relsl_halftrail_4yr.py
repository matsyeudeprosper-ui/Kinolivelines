import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

BRICK, REVERSAL = 50.0, 2
PT = 0.01
TP_PTS = 100.0
SPREAD_PTS = 10.0
LOTS = 0.05; SCALE = LOTS/0.01
REL_SL_PCT = 0.40
HT_FLOOR = 400.0
HT_ACTIVATION = 2*HT_FLOOR

files = ['coinbase_m1_2yr_part0.json','coinbase_m1_2yr_part1.json','coinbase_m1_2yr_part2.json','coinbase_m1_extra_year.json','coinbase_m1_pilot.json']
rows = {}
for f in files:
    for t, lo, hi, op, cl, vol in json.load(open(f)):
        rows[int(t)] = (op, hi, lo, cl)
ok = mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select("BTCUSDm", True)
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 99000)
mt5.shutdown()
for i in range(len(r)):
    t = int(r["time"][i])
    rows[t] = (float(r["open"][i]), float(r["high"][i]), float(r["low"][i]), float(r["close"][i]))
times = sorted(rows.keys())
N = len(times)
o = np.array([rows[t][0] for t in times]); h = np.array([rows[t][1] for t in times])
l = np.array([rows[t][2] for t in times]); c = np.array([rows[t][3] for t in times])
tm = np.array(times)
span_days = (tm[-1]-tm[0])/86400
print(f"M1 bars: {N}  {datetime.utcfromtimestamp(tm[0])} -> {datetime.utcfromtimestamp(tm[-1])}  ({span_days:.1f} days)\n")

def build_bricks_signals(o,h,l,c,N):
    revs = {}
    ao = ac = float(o[0]); d = 0; pd_ = 0
    for i in range(N):
        while True:
            up = (ao if d==-1 else ac) + BRICK*(REVERSAL if d==-1 else 1)
            dn = (ao if d==1 else ac) - BRICK*(REVERSAL if d==1 else 1)
            if c[i] >= up:
                base = ao if d==-1 else ac; ao,ac,d = base, base+BRICK, 1
            elif c[i] <= dn:
                base = ao if d==1 else ac; ao,ac,d = base, base-BRICK, -1
            else: break
            if pd_ and d != pd_: revs.setdefault(i,d)
            pd_ = d
    return revs

sigs = build_bricks_signals(o,h,l,c,N)

def effective_sl_pts(realized_peak, price):
    """EXACT same logic as the live bot's effective_sl_pts()."""
    if realized_peak >= HT_ACTIVATION:
        sl_usd = max(realized_peak/2.0, HT_FLOOR)
        return sl_usd / LOTS
    return price * REL_SL_PCT

def run(o,h,l,c,tm,N,sigs,use_halftrail):
    realized_cum = 0.0; realized_peak = 0.0
    bal_usd=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl_pts=None; pos_entry_t=None
    loss_events=[]
    max_peak_ever = 0.0
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_entry_t=et; pending=None
            rp = realized_peak if use_halftrail else 0.0
            pos_sl_pts = effective_sl_pts(rp, entry)
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1])
        if in_pos:
            tp_price = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            sl_price = pos_entry-pos_sl_pts if pos_L else pos_entry+pos_sl_pts
            hit_tp = (h[j]>=tp_price) if pos_L else (l[j]<=tp_price)
            hit_sl = (l[j]<=sl_price) if pos_L else (h[j]>=sl_price)
            if hit_tp or hit_sl:
                usd = (-pos_sl_pts if hit_sl else TP_PTS)*PT*SCALE
                bal_usd += usd; realized_cum = bal_usd
                if realized_cum > realized_peak:
                    realized_peak = realized_cum
                    max_peak_ever = max(max_peak_ever, realized_peak)
                if hit_sl:
                    losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_entry_t), round(usd,2)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal_usd, loss_events=loss_events, max_peak_ever=max_peak_ever)

print("=== Relative SL ALONE (Half Trail disabled) ===")
z1 = run(o,h,l,c,tm,N,sigs,use_halftrail=False)
print(f"  trades {z1['trades']}  win% {100*z1['wins']/z1['trades']:.2f}  losses {z1['losses']}  net ${z1['net']:.2f}   ${z1['net']/(span_days/30.44):.2f}/mo")
for L,t,usd in z1['loss_events']:
    print(f"    LOSS: {'BUY' if L else 'SELL'} {t}  ${usd}")

print("\n=== COMBINED: Relative SL (default) + Half Trail (active branch) - EXACTLY what's live now ===")
z2 = run(o,h,l,c,tm,N,sigs,use_halftrail=True)
print(f"  trades {z2['trades']}  win% {100*z2['wins']/z2['trades']:.2f}  losses {z2['losses']}  net ${z2['net']:.2f}   ${z2['net']/(span_days/30.44):.2f}/mo")
print(f"  highest realized_profit_peak ever reached: ${z2['max_peak_ever']:.2f}  (activation threshold: ${HT_ACTIVATION:.2f})")
for L,t,usd in z2['loss_events']:
    print(f"    LOSS: {'BUY' if L else 'SELL'} {t}  ${usd}")

print(f"\nDIFFERENCE (combined - relative-SL-alone): ${z2['net']-z1['net']:.2f}")
