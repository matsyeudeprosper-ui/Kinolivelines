"""V2 step 4: volatility-scaled TP/SL - the regime fix.

The TP/SL-as-%-of-price plateau (TP 3-6% x SL 1.5-3%) is real but earns
mostly in high-volatility eras: in quiet regimes a fixed-% target is too
far to reach. Fix: express TP and SL as MULTIPLES of current volatility -
a causal rolling ATR over the last 24h of M1 bars (1440 bars), computed at
entry. Uniform rule (every trade treated identically) - the surviving
category, no luck-floor exposure.

Args: "ktp,ksl" pairs, TP = ktp x ATR24h, SL = ksl x ATR24h at entry.
"""
import sys, json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

BRICK, REVERSAL = 50.0, 2
SPREAD_PTS = 10.0
LOTS = 0.05
ATR_WIN = 1440   # 24h of M1 bars

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

print("computing causal 24h rolling HIGH-LOW RANGE (sliding-window max/min over 1440 M1 bars)...", flush=True)
# (First version of this script summed per-minute true ranges instead - minute
# noise adds up to ~50-150% of price, making targets absurdly wide and producing
# only 8 trades in 6 years. Corrected 2026-08-19, same day: the natural yardstick
# is the actual high-to-low span of the last 24h, typically 2-5% of price.)
from collections import deque
atr24 = np.full(N, np.nan)
maxq = deque(); minq = deque()   # monotonic deques of indices
for j in range(N):
    while maxq and h_f[maxq[-1]] <= h_f[j]: maxq.pop()
    maxq.append(j)
    while minq and l_f[minq[-1]] >= l_f[j]: minq.pop()
    minq.append(j)
    lo_bound = j - ATR_WIN + 1
    while maxq[0] < lo_bound: maxq.popleft()
    while minq[0] < lo_bound: minq.popleft()
    if j >= ATR_WIN:
        atr24[j] = h_f[maxq[0]] - l_f[minq[0]]

eras = [
    ("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

def run_atr_shape(ktp, ksl):
    bal=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None
    tp_price=None; sl_price=None; pos_sl_d=None; pos_tp_d=None
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry,et,tp_d,sl_d = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_et = et; pos_tp_d = tp_d; pos_sl_d = sl_d
            tp_price = entry+tp_d if L else entry-tp_d
            sl_price = entry-sl_d if L else entry+sl_d
        if j in sigs and j+1<N and not in_pos:
            a = atr24[j]
            if not np.isnan(a) and a > 0:
                L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
                entry = o_f[j+1]+SP if L else o_f[j+1]
                # ktp/ksl are fractions of the 24h total range
                pending=(L,entry,int(tm_f[j+1]), ktp*a, ksl*a)
        if in_pos:
            htp = (h_f[j]>=tp_price) if pos_L else (l_f[j]<=tp_price)
            hsl = (l_f[j]<=sl_price) if pos_L else (h_f[j]>=sl_price)
            if htp or hsl:
                pts = -pos_sl_d if hsl else pos_tp_d
                usd = pts*LOTS
                bal += usd
                trades.append((pos_et, usd, hsl))
                in_pos=False
    return trades, bal

def summarize(trades, bal, ktp, ksl):
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
    print(f"TP {ktp:>4.2f}xR24  SL {ksl:>4.2f}xR24  n={n:>5} W={wins:>5} L={losses:>5} "
          f"win%={100*wins/n if n else 0:>5.1f}  net=${bal:>9,.0f}  $/mo={monthly:>7,.1f}  "
          f"maxDD=${mdd:>7,.0f}  avgW=${avg_win:>7,.2f} avgL=${avg_loss:>8,.2f}  "
          f"eras[{'/'.join(era_parts)}] ({era_ok}/3 pos)", flush=True)

configs = []
for a_ in sys.argv[1:]:
    s = a_.split(",")
    configs.append((float(s[0]), float(s[1])))

for ktp, ksl in configs:
    trades, bal = run_atr_shape(ktp, ksl)
    summarize(trades, bal, ktp, ksl)
