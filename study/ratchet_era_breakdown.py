import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import defaultdict

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

print("building signals ONCE over the full continuous history (correct method)...")
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)
print(f"signals: {len(sigs)}")

def run_full(o,h,l,c,tm,N,sigs,trig_f,cap_f):
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            if trig_f is None:
                pos_sl = pos_entry*REL_SL_PCT
            else:
                default_sl_usd = pos_entry*REL_SL_PCT*LOTS
                trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
                if realized_cum >= trig:
                    sl_usd = min(max(realized_cum,0.0), cap)
                else:
                    sl_usd = default_sl_usd
                pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry)
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd
                if trig_f is not None: realized_cum += usd
                trades.append((tm[j], usd, hsl))
                in_pos=False
    return trades, bal

print("running baseline continuously (one pass, whole 6 years)...")
trades_base, net_base = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,None,None)
print(f"baseline: {len(trades_base)} trades, net ${net_base:,.2f}")

print("running ratchet continuously (trigger=30%, cap=100%, realized_cum never reset)...")
trades_rat, net_rat = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00)
print(f"ratchet: {len(trades_rat)} trades, net ${net_rat:,.2f}")

eras = [
    ("2020-08-16 -> 2022-08-16", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-08-16 -> 2024-08-16", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-08-16 -> 2026-08-18", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

print("\n=== era-by-era breakdown, SLICING THE ALREADY-COMPUTED CONTINUOUS TRADE LISTS BY DATE (correct method - no signal or state resets) ===")
print(f"{'Era':<28} {'Baseline net':>14} {'Base losses':>12} {'Ratchet net':>14} {'Ratch losses':>13} {'Diff':>10}")
tot_base = 0.0; tot_rat = 0.0
for label, d0, d1 in eras:
    b_net = sum(pnl for et,pnl,isl in trades_base if d0 <= et < d1)
    b_loss = sum(1 for et,pnl,isl in trades_base if d0 <= et < d1 and isl)
    r_net = sum(pnl for et,pnl,isl in trades_rat if d0 <= et < d1)
    r_loss = sum(1 for et,pnl,isl in trades_rat if d0 <= et < d1 and isl)
    tot_base += b_net; tot_rat += r_net
    print(f"{label:<28} {b_net:>+14,.2f} {b_loss:>12d} {r_net:>+14,.2f} {r_loss:>13d} {r_net-b_net:>+10,.2f}")
print(f"{'TOTAL':<28} {tot_base:>+14,.2f} {'':>12} {tot_rat:>+14,.2f} {'':>13} {tot_rat-tot_base:>+10,.2f}")
