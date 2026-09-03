"""V2 zoom: fine grid around the TP5%/SL2% 'flipped shape' corner.
Args: "tp,sl" pairs in percent, e.g. 4,2 5,2.5
Same methodology as v2_shape_sweep.py (continuous 6yr, signals built once,
spread included, per-era breakdown)."""
import sys, json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

BRICK, REVERSAL = 50.0, 2
SPREAD_PTS = 10.0
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

print("building signals once (continuous)...", flush=True)
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

eras = [
    ("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

def run_shape(tp_pct, sl_pct):
    bal=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None
    tp_price=None; sl_price=None
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_et = et
            tp_d = entry*tp_pct; sl_d = entry*sl_pct
            tp_price = entry+tp_d if L else entry-tp_d
            sl_price = entry-sl_d if L else entry+sl_d
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o_f[j+1]+SP if L else o_f[j+1]
            pending=(L,entry,int(tm_f[j+1]))
        if in_pos:
            htp = (h_f[j]>=tp_price) if pos_L else (l_f[j]<=tp_price)
            hsl = (l_f[j]<=sl_price) if pos_L else (h_f[j]>=sl_price)
            if htp or hsl:
                pts = -(pos_entry*sl_pct) if hsl else (pos_entry*tp_pct)
                usd = pts*LOTS
                bal += usd
                trades.append((pos_et, usd, hsl))
                in_pos=False
    return trades, bal

def summarize(trades, bal, tp_pct, sl_pct):
    n = len(trades)
    losses = sum(1 for t in trades if t[2]); wins = n-losses
    peak=0.0; cum=0.0; mdd=0.0
    for _,usd,_ in trades:
        cum += usd
        if cum > peak: peak = cum
        if peak-cum > mdd: mdd = peak-cum
    span_days = (tm_f[-1]-tm_f[0])/86400
    monthly = bal/(span_days/30.44)
    era_parts = []; era_ok=0
    for label,d0,d1 in eras:
        gn = sum(t[1] for t in trades if d0<=t[0]<d1)
        if gn > 0: era_ok += 1
        era_parts.append(f"{gn:+,.0f}")
    avg_win = np.mean([t[1] for t in trades if not t[2]]) if wins else 0
    avg_loss = np.mean([t[1] for t in trades if t[2]]) if losses else 0
    print(f"TP {100*tp_pct:>5.2f}%  SL {100*sl_pct:>5.2f}%  n={n:>5} W={wins:>5} L={losses:>5} "
          f"win%={100*wins/n if n else 0:>5.1f}  net=${bal:>9,.0f}  $/mo={monthly:>7,.1f}  "
          f"maxDD=${mdd:>7,.0f}  avgW=${avg_win:>7,.2f} avgL=${avg_loss:>8,.2f}  "
          f"eras[{'/'.join(era_parts)}] ({era_ok}/3 pos)", flush=True)

configs = []
for a in sys.argv[1:]:
    s = a.split(",")
    configs.append((float(s[0])/100.0, float(s[1])/100.0))

for tp, sl in configs:
    trades, bal = run_shape(tp, sl)
    summarize(trades, bal, tp, sl)
