"""V2 step 6: TP4%/SL2% shape, entries allowed only when the 24h range is
BELOW a threshold (per-signal analysis showed quiet regimes have the edge).
Gating is legitimately testable here: hundreds of loss events, fast trade
resolution. Args: thresholds in percent, e.g. 2.5 4 6 (999 = no gate)."""
import sys, json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import deque

BRICK, REVERSAL = 50.0, 2
SPREAD_PTS = 10.0
LOTS = 0.05
TP_PCT = 0.04
SL_PCT = 0.02
ATR_WIN = 1440

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

print("computing causal 24h high-low range...", flush=True)
range24 = np.full(N, np.nan)
maxq = deque(); minq = deque()
for j in range(N):
    while maxq and h_f[maxq[-1]] <= h_f[j]: maxq.pop()
    maxq.append(j)
    while minq and l_f[minq[-1]] >= l_f[j]: minq.pop()
    minq.append(j)
    lo_bound = j - ATR_WIN + 1
    while maxq[0] < lo_bound: maxq.popleft()
    while minq[0] < lo_bound: minq.popleft()
    if j >= ATR_WIN:
        range24[j] = h_f[maxq[0]] - l_f[minq[0]]

eras = [
    ("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

def run_gated(thresh_pct):
    bal=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None
    tp_price=None; sl_price=None
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_et = et
            tp_price = entry*(1+TP_PCT) if L else entry*(1-TP_PCT)
            sl_price = entry*(1-SL_PCT) if L else entry*(1+SL_PCT)
        if j in sigs and j+1<N and not in_pos:
            if not np.isnan(range24[j]) and 100.0*range24[j]/c_f[j] < thresh_pct:
                L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
                entry = o_f[j+1]+SP if L else o_f[j+1]
                pending=(L,entry,int(tm_f[j+1]))
        if in_pos:
            htp = (h_f[j]>=tp_price) if pos_L else (l_f[j]<=tp_price)
            hsl = (l_f[j]<=sl_price) if pos_L else (h_f[j]>=sl_price)
            if htp or hsl:
                usd = (-pos_entry*SL_PCT if hsl else pos_entry*TP_PCT)*LOTS
                bal += usd
                trades.append((pos_et, usd, hsl))
                in_pos=False
    return trades, bal

for arg in sys.argv[1:]:
    thresh = float(arg)
    trades, bal = run_gated(thresh)
    n = len(trades)
    losses = sum(1 for t in trades if t[2]); wins = n-losses
    peak=0.0; cum=0.0; mdd=0.0
    for _,usd,_ in trades:
        cum += usd
        if cum > peak: peak = cum
        if peak-cum > mdd: mdd = peak-cum
    span_days = (tm_f[-1]-tm_f[0])/86400
    monthly = bal/(span_days/30.44)
    era_parts=[]; era_ok=0
    for label,d0,d1 in eras:
        gn = sum(t[1] for t in trades if d0<=t[0]<d1)
        if gn > 0: era_ok += 1
        era_parts.append(f"{gn:+,.0f}")
    print(f"range<{thresh:>5.1f}%  n={n:>5} W={wins:>5} L={losses:>5} "
          f"win%={100*wins/n if n else 0:>5.1f}  net=${bal:>9,.0f}  $/mo={monthly:>7,.1f}  "
          f"maxDD=${mdd:>7,.0f}  eras[{'/'.join(era_parts)}] ({era_ok}/3 pos)", flush=True)
