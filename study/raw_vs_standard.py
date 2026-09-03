"""Standard account (10pt effective spread) vs Raw Spread account (~5pt
effective: $2/side/lot commission ~= 4pts at any size, + ~1pt residual raw
spread) - all three deployed strategies, full 6yr, same methodology."""
import sys, json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import deque

BRICK, REVERSAL = 50.0, 2
LOTS = 0.05
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

print("prep: signals + 24h range...", flush=True)
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

def stats(trades, label):
    total = sum(t[1] for t in trades)
    losses = sum(1 for t in trades if t[2])
    peak=0.0; cum=0.0; mdd=0.0
    for _,usd,_ in trades:
        cum += usd
        if cum > peak: peak = cum
        if peak-cum > mdd: mdd = peak-cum
    span_days = (tm_f[-1]-tm_f[0])/86400
    print(f"{label:<34} trades={len(trades):>5} losses={losses:>4} net=${total:>9,.2f} "
          f"$/mo=${total/(span_days/30.44):>7,.2f} maxDD=${mdd:>9,.2f}", flush=True)

def run_gated_conc(tp_pct, sl_pct, gate, K, spread):
    open_pos = []; pending=None; trades = []
    for j in range(N):
        if pending is not None:
            L, et = pending; pending = None
            e = o_f[j] + (spread if L else 0.0)
            open_pos.append(dict(L=L, entry=e,
                                 tp=e*(1+tp_pct) if L else e*(1-tp_pct),
                                 sl=e*(1-sl_pct) if L else e*(1+sl_pct)))
        if j in sigs and j+1<N and len(open_pos) < K:
            if not np.isnan(range24[j]) and 100.0*range24[j]/c_f[j] < gate:
                pending = ((sigs[j]==1), int(tm_f[j+1]))
        still = []
        for p in open_pos:
            if p['L']:
                htp = h_f[j] >= p['tp']; hsl = l_f[j] <= p['sl']
            else:
                htp = l_f[j] <= p['tp']; hsl = h_f[j] >= p['sl']
            if htp or hsl:
                usd = (-p['entry']*sl_pct if hsl else p['entry']*tp_pct)*LOTS
                trades.append((int(tm_f[j]), usd, hsl))
            else:
                still.append(p)
        open_pos = still
    return trades

def run_v1(spread):
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    trades = []
    TP_PTS = 100.0; SL_PCT = 0.40
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
            L=(sigs[j]==1); SP=spread if L else 0.0
            pending=(L, o_f[j+1]+SP if L else o_f[j+1])
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h_f[j]>=tpp) if pos_L else (l_f[j]<=tpp)
            hsl = (l_f[j]<=slp) if pos_L else (h_f[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*LOTS
                bal += usd; realized_cum += usd
                trades.append((int(tm_f[j]), usd, hsl))
                in_pos=False
    return trades

for spread, acct in [(10.0, "STANDARD"), (5.0, "RAW")]:
    print(f"\n--- {acct} account (effective spread {spread:g}pts) ---", flush=True)
    stats(run_gated_conc(0.01, 0.005, 2.5, 5, spread), f"TURTLE ({acct})")
    stats(run_gated_conc(0.04, 0.02, 4.0, 10, spread), f"RABBIT ({acct})")
    stats(run_v1(spread), f"V1 ({acct})")
