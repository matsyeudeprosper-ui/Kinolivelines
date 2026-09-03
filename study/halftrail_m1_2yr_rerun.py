import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

BRICK, REVERSAL = 50.0, 2
PT = 0.01
TP_PTS = 100.0
SL_PTS_DEFAULT = 44439.0
SPREAD_PTS = 10.0
LOTS = 0.05; SCALE = LOTS/0.01
HT_FLOOR = 400.0

# --- load cached coinbase M1 history, dedup overlaps, sort ---
files = ['coinbase_m1_2yr_part0.json','coinbase_m1_2yr_part1.json','coinbase_m1_2yr_part2.json','coinbase_m1_extra_year.json','coinbase_m1_pilot.json']
rows = {}
for f in files:
    for t, lo, hi, op, cl, vol in json.load(open(f)):
        rows[int(t)] = (op, hi, lo, cl)

# --- fresh broker M1 data to cover the gap up to now ---
ok = mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
if not ok:
    raise SystemExit(f"initialize failed: {mt5.last_error()}")
mt5.symbol_select("BTCUSDm", True)
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 99000)
mt5.shutdown()
if r is None:
    raise SystemExit(f"copy_rates_from_pos failed: {mt5.last_error()}")
for i in range(len(r)):
    t = int(r["time"][i])
    rows[t] = (float(r["open"][i]), float(r["high"][i]), float(r["low"][i]), float(r["close"][i]))

times = sorted(rows.keys())
N = len(times)
o = np.array([rows[t][0] for t in times])
h = np.array([rows[t][1] for t in times])
l = np.array([rows[t][2] for t in times])
c = np.array([rows[t][3] for t in times])
tm = np.array(times)
span_days = (tm[-1]-tm[0])/86400
print(f"M1 bars combined: {N}  {datetime.utcfromtimestamp(tm[0])} -> {datetime.utcfromtimestamp(tm[-1])}  ({span_days:.1f} days)")

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
print(f"total signals: {len(sigs)}\n")

def run(o,h,l,c,tm,N,sigs,default_sl_pts,use_halftrail):
    default_sl_usd = default_sl_pts*PT*SCALE
    activation_usd = 2*HT_FLOOR
    realized_peak = 0.0
    bal_usd=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_entry_t=None; pos_sl_pts=None
    loss_events=[]
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_entry_t=et; pending=None
            if use_halftrail and realized_peak >= activation_usd:
                sl_usd = max(realized_peak/2.0, HT_FLOOR)
            else:
                sl_usd = default_sl_usd
            pos_sl_pts = sl_usd/(PT*SCALE)
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
                bal_usd += usd
                if hit_sl:
                    losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_entry_t), round(usd,2)))
                else: wins+=1
                realized_peak = max(realized_peak, bal_usd)
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal_usd, loss_events=loss_events)

base = run(o,h,l,c,tm,N,sigs,SL_PTS_DEFAULT,False)
ht_ = run(o,h,l,c,tm,N,sigs,SL_PTS_DEFAULT,True)

print(f"window: {span_days:.1f} days\n")
print("=== BASELINE (no trailing) ===")
print(f"  trades: {base['trades']}  win%: {100*base['wins']/base['trades']:.2f}  losses: {base['losses']}  net: ${base['net']:.2f}   ${base['net']/(span_days/30.44):.2f}/mo")
for L,t,usd in base['loss_events']:
    print(f"    LOSS: {'BUY' if L else 'SELL'} {t}  cost ${usd}")

print("\n=== HALF TRAIL (floor=$400) ===")
print(f"  trades: {ht_['trades']}  win%: {100*ht_['wins']/ht_['trades']:.2f}  losses: {ht_['losses']}  net: ${ht_['net']:.2f}   ${ht_['net']/(span_days/30.44):.2f}/mo")
for L,t,usd in ht_['loss_events']:
    print(f"    LOSS: {'BUY' if L else 'SELL'} {t}  cost ${usd}")
