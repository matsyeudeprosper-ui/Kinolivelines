"""Quick-in-quick-out scalps on a RAW account (effective toll ~5pts:
$2/side/lot commission = 4pts + ~1pt residual spread).
TP 10 and 20 pts, SLs 10/20/0.5%. cap=1, full 6yr."""
import sys, json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

BRICK, REVERSAL = 50.0, 2
SPREAD = 5.0    # RAW effective toll
LOTS = 0.05

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
N = len(times)

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

print("building signals...", flush=True)
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

def run(tp_pts, sl_spec):
    pct_mode = sl_spec.startswith("p")
    sl_pct = float(sl_spec[1:])/100.0 if pct_mode else None
    sl_fixed = None if pct_mode else float(sl_spec)
    bal=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; sl_d=None
    trades=[]
    for j in range(N):
        if pending is not None:
            L,entry = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            sl_d = entry*sl_pct if pct_mode else sl_fixed
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD if L else 0.0
            pending=(L, o_f[j+1]+SP if L else o_f[j+1])
        if in_pos:
            tpp = pos_entry+tp_pts if pos_L else pos_entry-tp_pts
            slp = pos_entry-sl_d if pos_L else pos_entry+sl_d
            htp = (h_f[j]>=tpp) if pos_L else (l_f[j]<=tpp)
            hsl = (l_f[j]<=slp) if pos_L else (h_f[j]>=slp)
            if htp or hsl:
                usd = (-sl_d if hsl else tp_pts)*LOTS
                bal += usd
                trades.append((usd, hsl))
                in_pos=False
    wins = sum(1 for t in trades if not t[1])
    span_days = (tm_f[-1]-tm_f[0])/86400
    lbl = f"SL {sl_spec[1:]}%" if pct_mode else f"SL {sl_spec}pts"
    print(f"RAW: TP{tp_pts:g} / {lbl:<9} trades={len(trades):>6} win%={100*wins/len(trades):>5.1f} "
          f"net=${bal:>10,.2f}  $/mo=${bal/(span_days/30.44):>8,.2f}", flush=True)

for tp in [10.0, 20.0]:
    for sl in ["10", "20", "p0.5"]:
        run(tp, sl)
