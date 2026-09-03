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
N = len(times)
o = np.array([rows[t][0] for t in times]); h = np.array([rows[t][1] for t in times])
l = np.array([rows[t][2] for t in times]); c = np.array([rows[t][3] for t in times])
tm = np.array(times)
span_days = (tm[-1]-tm[0])/86400

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

def run(o,h,l,c,tm,N,sigs,decay_day):
    """decay_day: at this many days held, halve remaining exposure (realize
    half the position at current price, let the other half ride to the
    ORIGINAL tp/sl). decay_day=None = baseline, no deleverage."""
    bal=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    half_closed=False; remaining_frac=1.0
    loss_events=[]
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            pos_sl = pos_entry*REL_SL_PCT
            half_closed=False; remaining_frac=1.0
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1])
        if in_pos:
            if decay_day is not None and not half_closed:
                days_in = (tm[j]-pos_et)/86400
                if days_in >= decay_day:
                    cur_px = c[j]
                    partial_pts = (cur_px-pos_entry) if pos_L else (pos_entry-cur_px)
                    bal += partial_pts*PT*SCALE*0.5
                    remaining_frac = 0.5
                    half_closed = True
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE*remaining_frac
                bal += usd
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(usd/remaining_frac,2) if remaining_frac else 0))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events)

zb = run(o,h,l,c,tm,N,sigs,None)
print(f"BASELINE (no deleverage, current live config): trades {zb['trades']}  losses {zb['losses']}  net ${zb['net']:,.2f}")
print()
for dday in [5, 7, 10, 14, 20, 30]:
    z = run(o,h,l,c,tm,N,sigs,dday)
    print(f"halve exposure at day {dday:>2}: trades {z['trades']}  losses {z['losses']}  net ${z['net']:>10,.2f}  (diff vs baseline: ${z['net']-zb['net']:+,.2f})")

print("\n=== fine sweep around day 14 ===")
for dday in [11,12,13,14,15,16,17,18,19]:
    z = run(o,h,l,c,tm,N,sigs,dday)
    print(f"halve exposure at day {dday:>2}: net ${z['net']:>10,.2f}  (diff vs baseline: ${z['net']-zb['net']:+,.2f})")
