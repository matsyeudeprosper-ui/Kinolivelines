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

print("building M1 signals (once, continuous)...")
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

print("building H1 bars for previous-candle-color lookup...")
hour_idx = (tm_f // 3600).astype(np.int64)
uniq_hours, first_pos = np.unique(hour_idx, return_index=True)
n_hours = len(uniq_hours)
bounds = list(first_pos) + [N]
h1_open = np.empty(n_hours); h1_close = np.empty(n_hours)
for k in range(n_hours):
    s,e = bounds[k], bounds[k+1]
    h1_open[k] = o_f[s]
    h1_close[k] = c_f[e-1]
h1_color = np.where(h1_close > h1_open, 1, np.where(h1_close < h1_open, -1, 0))  # 1=green -1=red 0=flat
hour_to_pos = {int(h): i for i, h in enumerate(uniq_hours)}

def run_ratchet(o,h,l,c,tm,N,sigs,trig_f,cap_f):
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    pos_sig_bar=None
    trades = []  # (side, m1_prev_color, h1_prev_color, hsl)
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
            pending=(L,entry,j)  # j = the reversal bar itself = "previous M1 candle" at entry
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd; realized_cum += usd
                m1c = 1 if c[pos_sig_bar] > o[pos_sig_bar] else (-1 if c[pos_sig_bar] < o[pos_sig_bar] else 0)
                entry_hour = int(tm[pos_sig_bar+1] // 3600)
                prev_hour = entry_hour - 1
                h1c = h1_color[hour_to_pos[prev_hour]] if prev_hour in hour_to_pos else 0
                trades.append(("BUY" if pos_L else "SELL", m1c, h1c, hsl))
                in_pos=False
    return trades, bal

print("running the deployed rule (ratchet trigger=30%, cap=100%)...")
trades, net = run_ratchet(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00)
print(f"total trades: {len(trades)}, net ${net:,.2f}")

def colname(c):
    return "Green" if c==1 else ("Red" if c==-1 else "Flat")

print("\n=== breakdown: side x M1-prev-color x H1-prev-color x win/loss ===")
counts = defaultdict(lambda: [0,0])  # key -> [wins, losses]
for side, m1c, h1c, hsl in trades:
    key = (side, colname(m1c), colname(h1c))
    counts[key][1 if hsl else 0] += 1

print(f"{'Side':<5} {'M1 prev':<7} {'H1 prev':<7} {'Wins':>7} {'Losses':>7} {'Loss %':>8}")
for key in sorted(counts.keys()):
    wins, losses = counts[key]
    total = wins+losses
    pct = 100*losses/total if total else 0
    print(f"{key[0]:<5} {key[1]:<7} {key[2]:<7} {wins:>7} {losses:>7} {pct:>7.2f}%")

print("\n=== simpler breakdown: just M1-prev-color, all sides combined ===")
m1_counts = defaultdict(lambda: [0,0])
for side, m1c, h1c, hsl in trades:
    m1_counts[colname(m1c)][1 if hsl else 0] += 1
for k,v in m1_counts.items():
    w,l = v; tot=w+l
    print(f"M1 prev {k:<6}: wins={w} losses={l} loss%={100*l/tot:.2f}%")

print("\n=== simpler breakdown: just H1-prev-color, all sides combined ===")
h1_counts = defaultdict(lambda: [0,0])
for side, m1c, h1c, hsl in trades:
    h1_counts[colname(h1c)][1 if hsl else 0] += 1
for k,v in h1_counts.items():
    w,l = v; tot=w+l
    print(f"H1 prev {k:<6}: wins={w} losses={l} loss%={100*l/tot:.2f}%")

print("\n=== overall totals ===")
tot_w = sum(1 for t in trades if not t[3])
tot_l = sum(1 for t in trades if t[3])
print(f"total wins={tot_w} losses={tot_l} loss%={100*tot_l/len(trades):.2f}%")
