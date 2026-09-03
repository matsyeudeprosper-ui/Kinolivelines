"""Full calendar stats for V2's leading config: TP4%/SL2%, entries only when
24h range < 4% of price, up to K=10 concurrent 0.05-lot positions."""
import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timedelta
from collections import deque, defaultdict

BRICK, REVERSAL = 50.0, 2
SPREAD_PTS = 10.0
LOTS = 0.05
TP_PCT = 0.04
SL_PCT = 0.02
ATR_WIN = 1440
K = 10
THRESH = 4.0

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

print("computing 24h range...", flush=True)
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

print("running V2 config (K=10, gate<4%)...", flush=True)
bal=0.0
open_pos = []; pending=None
trades = []
for j in range(N):
    if pending is not None:
        L, et = pending; pending = None
        entry = o_f[j] + (SPREAD_PTS if L else 0.0)
        open_pos.append(dict(L=L, entry=entry,
                             tp=entry*(1+TP_PCT) if L else entry*(1-TP_PCT),
                             sl=entry*(1-SL_PCT) if L else entry*(1+SL_PCT),
                             et=et))
    if j in sigs and j+1<N and len(open_pos) < K:
        if not np.isnan(range24[j]) and 100.0*range24[j]/c_f[j] < THRESH:
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
            trades.append((int(tm_f[j]), usd, hsl))
        else:
            still.append(p)
    open_pos = still

def report(trades, label):
    if not trades:
        print(f"{label}: no trades"); return
    daily = defaultdict(float); weekly = defaultdict(float); monthly = defaultdict(float)
    for xt, usd, hsl in trades:
        dt = datetime.utcfromtimestamp(xt)
        daily[dt.date()] += usd
        weekly[dt.date() - timedelta(days=dt.weekday())] += usd
        monthly[(dt.year, dt.month)] += usd
    peak=0.0; cum=0.0; mdd=0.0
    for xt, usd, hsl in trades:
        cum += usd
        if cum > peak: peak = cum
        if peak-cum > mdd: mdd = peak-cum
    total = sum(t[1] for t in trades)
    losses = sum(1 for t in trades if t[2]); wins = len(trades)-losses
    d0 = min(daily.keys()); d1 = max(daily.keys())
    n_days = (d1-d0).days + 1
    dv = list(daily.values()); wv = list(weekly.values()); mv = list(monthly.values())
    print(f"\n=== {label} ===")
    print(f"trades: {len(trades)}  wins: {wins}  losses: {losses}  win rate: {100*wins/len(trades):.1f}%")
    print(f"total net: ${total:,.2f} over {n_days} days")
    print(f"avg profit/day:   ${total/n_days:,.2f}")
    print(f"avg profit/week:  ${total/(n_days/7):,.2f}")
    print(f"avg profit/month: ${total/(n_days/30.44):,.2f}")
    print(f"best day: ${max(dv):,.2f}   worst day: ${min(dv):,.2f}")
    print(f"best week: ${max(wv):,.2f}   worst week: ${min(wv):,.2f}")
    print(f"best month: ${max(mv):,.2f}   worst month: ${min(mv):,.2f}")
    print(f"max drawdown (realized peak-to-trough): ${mdd:,.2f}")
    print(f"months positive: {sum(1 for v in mv if v>0)}/{len(mv)}")

report(trades, "V2 (TP4%/SL2%, quiet<4%, K=10) - FULL 6 YEARS")
cut = datetime(2024,8,16).timestamp()
report([t for t in trades if t[0] >= cut], "V2 - RECENT ERA ONLY (2024-08-16 onward, the regime where it works)")
cut2 = datetime(2022,8,16).timestamp()
report([t for t in trades if cut2 <= t[0] < cut], "V2 - MIDDLE ERA (2022-24, for honesty)")

print("\n=== MONTH-BY-MONTH record (the honest consistency picture) ===")
monthly = defaultdict(float)
for xt, usd, hsl in trades:
    dt = datetime.utcfromtimestamp(xt)
    monthly[(dt.year, dt.month)] += usd
years = defaultdict(float)
for (y,m), v in sorted(monthly.items()):
    years[y] += v
cur_year = None
line = ""
for (y,m), v in sorted(monthly.items()):
    if y != cur_year:
        if line: print(line)
        cur_year = y
        line = f"{y}:  "
    line += f"{m:02d}:{v:+,.0f}  "
print(line)
print("\nYearly totals:")
for y, v in sorted(years.items()):
    print(f"  {y}: ${v:+,.0f}")

# longest losing-month streak
vals = [v for k,v in sorted(monthly.items())]
worst_streak = 0; cur = 0; worst_streak_dd = 0.0; cur_dd = 0.0
for v in vals:
    if v < 0:
        cur += 1; cur_dd += v
        if cur > worst_streak: worst_streak = cur
        if cur_dd < worst_streak_dd: worst_streak_dd = cur_dd
    else:
        cur = 0; cur_dd = 0.0
print(f"\nlongest run of losing months: {worst_streak}   deepest losing-streak total: ${worst_streak_dd:,.0f}")
