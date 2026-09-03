"""V2 step 7: concurrency - allow up to K simultaneous positions on the
TP4%/SL2% shape. The per-signal analysis says ~$65k of EV exists across all
signals over 6yr; cap=1 captures ~$3.4k of it. Small per-trade losses
(~2% of price ~= $50 at 0.05 lots) make concurrent exposure survivable in a
way V1's 40%-SL shape never was. Tracks max concurrent positions and worst
aggregate equity drawdown honestly.

Args: "K,thresh" pairs - K = max concurrent positions, thresh = only enter
when 24h range% below this (999 = no gate). e.g. 3,999 10,999 3,4 10,4
"""
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

def run_concurrent(K, thresh_pct):
    bal=0.0
    open_pos = []   # list of dicts: L, entry, tp, sl, et
    pending = None  # (L, entry_bar) -> open at next bar's open
    trades = []
    max_conc = 0
    # realized-equity drawdown (floating not tracked per-bar for speed; losses
    # are small and fast so realized DD is a fair first-pass proxy)
    peak=0.0; cum=0.0; mdd=0.0
    for j in range(N):
        if pending is not None:
            L, et = pending; pending = None
            entry = o_f[j] + (SPREAD_PTS if L else 0.0)
            open_pos.append(dict(L=L, entry=entry,
                                 tp=entry*(1+TP_PCT) if L else entry*(1-TP_PCT),
                                 sl=entry*(1-SL_PCT) if L else entry*(1+SL_PCT),
                                 et=et))
            if len(open_pos) > max_conc: max_conc = len(open_pos)
        if j in sigs and j+1<N and len(open_pos) < K:
            if not np.isnan(range24[j]) and 100.0*range24[j]/c_f[j] < thresh_pct:
                pending = ((sigs[j]==1), int(tm_f[j+1]))
        still = []
        for p in open_pos:
            if p['L']:
                htp = h_f[j] >= p['tp']; hsl = l_f[j] <= p['sl']
            else:
                htp = l_f[j] <= p['tp']; hsl = h_f[j] >= p['sl']
            if htp or hsl:
                usd = (-p['entry']*SL_PCT if hsl else p['entry']*TP_PCT)*LOTS
                bal += usd
                cum += usd
                if cum > peak: peak = cum
                if peak-cum > mdd: mdd = peak-cum
                trades.append((p['et'], usd, hsl))
            else:
                still.append(p)
        open_pos = still
    return trades, bal, max_conc, mdd

for arg in sys.argv[1:]:
    s = arg.split(",")
    K = int(s[0]); thresh = float(s[1])
    trades, bal, max_conc, mdd = run_concurrent(K, thresh)
    n = len(trades)
    losses = sum(1 for t in trades if t[2]); wins = n-losses
    span_days = (tm_f[-1]-tm_f[0])/86400
    monthly = bal/(span_days/30.44)
    era_parts=[]; era_ok=0
    for label,d0,d1 in eras:
        gn = sum(t[1] for t in trades if d0<=t[0]<d1)
        if gn > 0: era_ok += 1
        era_parts.append(f"{gn:+,.0f}")
    gate_lbl = "nogate" if thresh >= 999 else f"<{thresh:g}%"
    print(f"K={K:>3} {gate_lbl:<7} n={n:>6} W={wins:>6} L={losses:>6} "
          f"win%={100*wins/n if n else 0:>5.1f}  net=${bal:>10,.0f}  $/mo={monthly:>8,.1f}  "
          f"maxconc={max_conc:>3}  maxDD=${mdd:>8,.0f}  eras[{'/'.join(era_parts)}] ({era_ok}/3 pos)", flush=True)
