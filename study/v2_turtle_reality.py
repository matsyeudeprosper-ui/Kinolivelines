"""Turtle reality checks: (1) spread stress - does the thin edge survive
worse spreads? (2) $100-lifecycle sim at 0.01 lots with the trailing floor
(arm at $200 peak, giveback $100), started from every possible month in
history to get outcome statistics.
Args: mode (spread|lifecycle)"""
import sys, json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import deque

BRICK, REVERSAL = 50.0, 2
ATR_WIN = 1440
TP_PCT = 0.01; SL_PCT = 0.005; GATE_PCT = 2.5; MAX_POS = 5

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

def run_turtle(lots, spread_pts):
    """Full-history turtle at given lot size & spread; returns trade list."""
    open_pos = []; pending=None; trades = []
    for j in range(N):
        if pending is not None:
            L, et = pending; pending = None
            entry = o_f[j] + (spread_pts if L else 0.0)
            open_pos.append(dict(L=L, entry=entry,
                                 tp=entry*(1+TP_PCT) if L else entry*(1-TP_PCT),
                                 sl=entry*(1-SL_PCT) if L else entry*(1+SL_PCT), et=et))
        if j in sigs and j+1<N and len(open_pos) < MAX_POS:
            if not np.isnan(range24[j]) and 100.0*range24[j]/c_f[j] < GATE_PCT:
                pending = ((sigs[j]==1), int(tm_f[j+1]))
        still = []
        for p in open_pos:
            if p['L']:
                htp = h_f[j] >= p['tp']; hsl = l_f[j] <= p['sl']
            else:
                htp = l_f[j] <= p['tp']; hsl = h_f[j] >= p['sl']
            if htp or hsl:
                usd = (-p['entry']*SL_PCT if hsl else p['entry']*TP_PCT)*lots
                trades.append((int(tm_f[j]), usd, hsl))
            else:
                still.append(p)
        open_pos = still
    return trades

mode = sys.argv[1]
if mode == "spread":
    print("\n=== spread stress at 0.05 lots (numbers scale linearly to any size) ===")
    for sp in [10.0, 15.0, 20.0, 30.0, 40.0]:
        t = run_turtle(0.05, sp)
        net = sum(x[1] for x in t)
        losses = sum(1 for x in t if x[2])
        print(f"spread {sp:>4.0f}pts: trades={len(t)} losses={losses} net=${net:,.2f}  ($/mo={net/72:,.2f})", flush=True)
elif mode == "lifecycle":
    print("\n=== $100 lifecycle at 0.01 lots, floor arm $200 / giveback $100, from every start month ===")
    trades = run_turtle(0.01, 10.0)
    # walk the account from each possible start month
    starts = []
    t0 = datetime(2020,9,1)
    while True:
        ts = t0.timestamp()
        if ts > tm_f[-1] - 90*86400: break   # need at least ~3 months of runway
        starts.append(ts)
        m = t0.month + 1; y = t0.year + (1 if m > 12 else 0)
        t0 = datetime(y, 1 if m > 12 else m, 1)
    outcomes = {"wiped": 0, "doubled_then_floor": 0, "still_running": 0}
    finals = []
    for s in starts:
        eq = 100.0; peak = eq; armed=False; tripped=False
        for xt, usd, hsl in trades:
            if xt < s: continue
            eq += usd
            peak = max(peak, eq)
            if peak >= 200: armed = True
            if eq <= 2.0:      # effectively wiped (can't margin a position)
                outcomes["wiped"] += 1; finals.append(eq); tripped=True; break
            if armed and eq <= peak - 100:
                outcomes["doubled_then_floor"] += 1; finals.append(eq); tripped=True; break
        if not tripped:
            outcomes["still_running"] += 1; finals.append(eq)
    n = len(starts)
    print(f"start months tested: {n}")
    print(f"  wiped out (to ~$0):            {outcomes['wiped']:>3}  ({100*outcomes['wiped']/n:.0f}%)")
    print(f"  doubled, floor later tripped:  {outcomes['doubled_then_floor']:>3}  ({100*outcomes['doubled_then_floor']/n:.0f}%)  <- locked-in exit, profit kept")
    print(f"  still alive at end of data:    {outcomes['still_running']:>3}  ({100*outcomes['still_running']/n:.0f}%)")
    fa = np.array(finals)
    print(f"  final equity: median ${np.median(fa):,.0f}   mean ${fa.mean():,.0f}   min ${fa.min():,.0f}   max ${fa.max():,.0f}")
