"""V1 shape traded ONLY in HOT markets (24h range >= threshold) - the
inverse of the animals' calm gate, motivated by the per-signal finding
that V1's tiny TP resolves near-instantly in storms (+$1.66/sig, lowest
loss rate after the calm buckets). Real gating, V1's full live config
(relative 40% SL + Breakeven Ratchet trigger 30%/cap 100%), cap=1.
Args: thresholds in %, 0 = no gate (baseline). CAVEAT: V1's rare losses
mean gated results carry the dozen-loss luck floor - read with the
per-signal table, not alone."""
import sys, json
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

eras = [
    ("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

def run(thresh):
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            default_sl_usd = pos_entry*SL_PCT*LOTS
            trig = 0.30*default_sl_usd; cap = 1.00*default_sl_usd
            if realized_cum >= trig:
                sl_usd = min(max(realized_cum, 0.0), cap)
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            hot = True
            if thresh > 0:
                hot = (not np.isnan(range24[j])) and 100.0*range24[j]/c_f[j] >= thresh
            if hot:
                L=(sigs[j]==1); SP=SPREAD if L else 0.0
                pending=(L, o_f[j+1]+SP if L else o_f[j+1])
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h_f[j]>=tpp) if pos_L else (l_f[j]<=tpp)
            hsl = (l_f[j]<=slp) if pos_L else (h_f[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl*0.01*(LOTS/0.01) if hsl else TP_PTS*LOTS) if False else ((-pos_sl if hsl else TP_PTS)*0.01*(LOTS/0.01))
                usd = (-pos_sl if hsl else TP_PTS)*LOTS
                bal += usd; realized_cum += usd
                trades.append((int(tm_f[j]), usd, hsl))
                in_pos=False
    total = sum(t[1] for t in trades)
    wins = sum(1 for t in trades if not t[2]); losses = len(trades)-wins
    peak=0.0; cum=0.0; mdd=0.0
    for _,usd,_ in trades:
        cum += usd
        if cum > peak: peak = cum
        if peak-cum > mdd: mdd = peak-cum
    span_days = (tm_f[-1]-tm_f[0])/86400
    era_parts=[]; era_pos=0
    for lbl,d0,d1 in eras:
        gn = sum(t[1] for t in trades if d0<=t[0]<d1)
        if gn > 0: era_pos += 1
        era_parts.append(f"{lbl}:{gn:+,.0f}")
    lbl = "no gate" if thresh == 0 else f">={thresh:g}%"
    print(f"{lbl:<8} trades={len(trades):>5} W={wins:>5} L={losses:>3} net=${total:>9,.2f} "
          f"$/mo=${total/(span_days/30.44):>7,.2f} maxDD=${mdd:>9,.2f} [{'  '.join(era_parts)}] ({era_pos}/3)", flush=True)

for a in sys.argv[1:]:
    run(float(a))
