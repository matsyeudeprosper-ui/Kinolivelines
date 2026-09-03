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

files = ['coinbase_m1_2yr_partneg1.json','coinbase_m1_2yr_part0.json','coinbase_m1_2yr_part1.json',
         'coinbase_m1_2yr_part2.json','coinbase_m1_extra_year.json','coinbase_m1_pilot.json']
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
o_f = np.array([rows[t][0] for t in times]); h_f = np.array([rows[t][1] for t in times])
l_f = np.array([rows[t][2] for t in times]); c_f = np.array([rows[t][3] for t in times])
tm_f = np.array(times)

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

def run_baseline(o,h,l,c,tm,N,sigs):
    bal=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            pos_sl = pos_entry*REL_SL_PCT
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1])
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd
                if hsl: losses+=1
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal)

def run_debounce(o,h,l,c,tm,N,sigs,trig_f,cap_f,grace_trades):
    """Once armed (realized_cum>=trig), stay armed through a dip below trig for
    up to grace_trades subsequent trades before actually disarming - a single bad
    trade right after arming shouldn't instantly hand control back to the wide
    default SL. Cap is always relative to CURRENT trade's default (price grows),
    same as other dual-cap variants."""
    bal=0.0; wins=losses=0; realized_cum=0.0; armed=False; grace=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trig = trig_f*default_sl_usd
            cap = cap_f*default_sl_usd
            if realized_cum >= trig:
                armed = True; grace = grace_trades
            elif armed:
                grace -= 1
                if grace < 0: armed = False
            if armed:
                sl_usd = min(max(realized_cum,0.0), cap)
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1])
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd; realized_cum += usd
                if hsl: losses+=1
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal)

segs = [
    ("2020-08-16 -> 2022-08-16", datetime(2020,8,16), datetime(2022,8,16)),
    ("2022-08-16 -> 2024-08-16", datetime(2022,8,16), datetime(2024,8,16)),
    ("2024-08-16 -> 2026-08-18", datetime(2024,8,16), datetime(2026,8,18)),
]
seg_data = []
for label, d0, d1 in segs:
    mask = (tm_f >= d0.timestamp()) & (tm_f < d1.timestamp())
    ot,ht,lt,ct,tmt = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask]
    Nt = len(ct)
    sigt = build_bricks_signals(ot,ht,lt,ct,Nt)
    zb = run_baseline(ot,ht,lt,ct,tmt,Nt,sigt)
    seg_data.append((label,ot,ht,lt,ct,tmt,Nt,sigt,zb))

print("=== debounce sweep: trig=20%, cap=90%, grace_trades 0-8 (trade-count based sticky) ===")
print("grace   seg1      seg2      seg3      SUM")
for grace in [0,1,2,3,4,5,6,8]:
    diffs = []
    for label,ot,ht,lt,ct,tmt,Nt,sigt,zb in seg_data:
        z = run_debounce(ot,ht,lt,ct,tmt,Nt,sigt, 0.20, 0.90, grace)
        diffs.append(z['net']-zb['net'])
    print(f"{grace:>5d}  {diffs[0]:>+8.0f}  {diffs[1]:>+8.0f}  {diffs[2]:>+8.0f}  {sum(diffs):>+9.0f}")

print("\n=== debounce sweep: trig=15%, cap=90%, grace_trades 0-8 ===")
print("grace   seg1      seg2      seg3      SUM")
for grace in [0,1,2,3,4,5,6,8]:
    diffs = []
    for label,ot,ht,lt,ct,tmt,Nt,sigt,zb in seg_data:
        z = run_debounce(ot,ht,lt,ct,tmt,Nt,sigt, 0.15, 0.90, grace)
        diffs.append(z['net']-zb['net'])
    print(f"{grace:>5d}  {diffs[0]:>+8.0f}  {diffs[1]:>+8.0f}  {diffs[2]:>+8.0f}  {sum(diffs):>+9.0f}")
