"""Does market calmness at entry predict per-signal outcomes for V1's shape
(TP 100pts fixed, SL 40% of entry)? Every signal simulated independently
(the clean method - no cap=1 lottery), bucketed by 24h-range regime."""
import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import deque

BRICK, REVERSAL = 50.0, 2
SPREAD = 10.0
LOTS = 0.05
ATR_WIN = 1440
TP_PTS = 100.0
SL_PCT = 0.40

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

print("building signals + 24h range...", flush=True)
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)
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

print("simulating every signal independently at V1's shape (TP 100pts / SL 40%)...", flush=True)
CHUNK = 50000
results = []
for j in sorted(sigs.keys()):
    if j+1 >= N or np.isnan(range24[j]): continue
    L = (sigs[j] == 1)
    entry = o_f[j+1] + (SPREAD if L else 0.0)
    tp = entry + TP_PTS if L else entry - TP_PTS
    slp = entry*(1-SL_PCT) if L else entry*(1+SL_PCT)
    pos = j+1
    hit = None
    while pos < N:
        end = min(N, pos + CHUNK)
        hseg = h_f[pos:end]; lseg = l_f[pos:end]
        if L:
            tp_hit = hseg >= tp; sl_hit = lseg <= slp
        else:
            tp_hit = lseg <= tp; sl_hit = hseg >= slp
        any_hit = tp_hit | sl_hit
        if any_hit.any():
            k = int(np.argmax(any_hit))
            hit = bool(sl_hit[k])
            break
        pos = end
    if hit is None: continue
    usd = (-entry*SL_PCT if hit else TP_PTS)*LOTS
    results.append((int(tm_f[j+1]), 100.0*range24[j]/c_f[j], usd, hit))

print(f"resolved: {len(results)}", flush=True)
BUCKETS = [(0,1.5),(1.5,2.5),(2.5,4),(4,6),(6,100)]
print(f"\n{'regime':<10} {'n':>6} {'losses':>7} {'loss%':>8} {'avg$/sig':>9} {'total$':>10}")
for lo, hi in BUCKETS:
    grp = [x for x in results if lo <= x[1] < hi]
    n = len(grp)
    if n == 0: continue
    losses = sum(1 for x in grp if x[3])
    tot = sum(x[2] for x in grp)
    print(f"{f'{lo}-{hi}%':<10} {n:>6} {losses:>7} {100*losses/n:>7.3f}% {tot/n:>9.3f} {tot:>10,.0f}")
