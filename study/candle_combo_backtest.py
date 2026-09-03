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

print("building signals...")
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

print("building H1 bars...")
hour_idx = (tm_f // 3600).astype(np.int64)
uniq_hours, first_pos = np.unique(hour_idx, return_index=True)
n_hours = len(uniq_hours)
bounds = list(first_pos) + [N]
h1_open = np.empty(n_hours); h1_close = np.empty(n_hours)
for k in range(n_hours):
    s,e = bounds[k], bounds[k+1]
    h1_open[k] = o_f[s]
    h1_close[k] = c_f[e-1]
h1_color = np.where(h1_close > h1_open, 1, np.where(h1_close < h1_open, -1, 0))
hour_to_pos = {int(h): i for i, h in enumerate(uniq_hours)}

def m1_color_at(idx):
    return 1 if c_f[idx] > o_f[idx] else (-1 if c_f[idx] < o_f[idx] else 0)

def h1_color_before(entry_hour, back):
    hr = entry_hour - back
    return h1_color[hour_to_pos[hr]] if hr in hour_to_pos else 0

def run_ratchet(o,h,l,c,tm,N,sigs,trig_f,cap_f):
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    pos_sig_bar=None
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry,sig_bar = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_sig_bar = sig_bar
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
            if realized_cum >= trig:
                sl_usd = min(max(realized_cum, 0.0), cap)
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,j)
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd; realized_cum += usd
                m1c_1 = m1_color_at(pos_sig_bar)
                m1c_2 = m1_color_at(pos_sig_bar-1) if pos_sig_bar-1 >= 0 else 0
                entry_hour = int(tm[pos_sig_bar+1] // 3600)
                h1c_1 = h1_color_before(entry_hour, 1)
                h1c_2 = h1_color_before(entry_hour, 2)
                trades.append(("BUY" if pos_L else "SELL", m1c_1, m1c_2, h1c_1, h1c_2, usd, hsl))
                in_pos=False
    return trades, bal

print("running deployed rule...")
trades, net = run_ratchet(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00)
print(f"total trades: {len(trades)}, net ${net:,.2f}")

def h1_streak(c1,c2):
    if c1==1 and c2==1: return "H1:2xGreen"
    if c1==-1 and c2==-1: return "H1:2xRed"
    return "H1:Mixed"

def m1_streak(c1,c2):
    if c1==1 and c2==1: return "M1:2xGreen"
    if c1==-1 and c2==-1: return "M1:2xRed"
    return "M1:Mixed"

print("\n=== FULL combo: side x H1-streak x M1-streak ===")
combo = defaultdict(lambda: [0,0,0.0])  # wins, losses, sum_usd
for side, m1c1, m1c2, h1c1, h1c2, usd, hsl in trades:
    key = (side, h1_streak(h1c1,h1c2), m1_streak(m1c1,m1c2))
    combo[key][1 if hsl else 0] += 1
    combo[key][2] += usd

print(f"{'Side':<5} {'H1':<11} {'M1':<11} {'Wins':>6} {'Losses':>7} {'Total':>6} {'Loss%':>7} {'NetUSD':>10}")
for key in sorted(combo.keys()):
    w,l,usd = combo[key]
    tot = w+l
    print(f"{key[0]:<5} {key[1]:<11} {key[2]:<11} {w:>6} {l:>7} {tot:>6} {100*l/tot if tot else 0:>6.2f}% {usd:>10,.2f}")

print("\n=== SPECIFIC CHECK: SELL + H1 2xGreen + M1 Mixed (the overlap of both found patterns) ===")
target = [t for t in trades if t[0]=="SELL" and h1_streak(t[3],t[4])=="H1:2xGreen" and m1_streak(t[1],t[2])=="M1:Mixed"]
w = sum(1 for t in target if not t[6]); l = sum(1 for t in target if t[6])
print(f"trades: {len(target)}  wins: {w}  losses: {l}  loss%={100*l/len(target) if target else 0:.2f}%")

print("\n=== SPECIFIC CHECK: just SELL + H1 2xGreen (regardless of M1) - the strongest single pattern found so far ===")
target2 = [t for t in trades if t[0]=="SELL" and h1_streak(t[3],t[4])=="H1:2xGreen"]
w2 = sum(1 for t in target2 if not t[6]); l2 = sum(1 for t in target2 if t[6])
print(f"trades: {len(target2)}  wins: {w2}  losses: {l2}  loss%={100*l2/len(target2) if target2 else 0:.2f}%")
