"""PENDULUM V2 - the velocity fix: only fade the 24h-range edge if price
got there FAST (the excursion from the mid-zone to the edge took at most
V_BARS minutes). Slow drifts to the edge (breakout preludes) are ignored;
sharp lurches (snap-back candidates, per the Turtle's proven physics) are
faded. Everything else identical to Pendulum v1.
Args: EDGE SLR V_BARS triplets, e.g. 0.8 0.5 30"""
import sys, json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import deque

SPREAD = 10.0
LOTS = 0.05
ATR_WIN = 1440
GATE_PCT = 2.5
MAX_POS = 3

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

print("computing causal 24h rolling high/low...", flush=True)
hi24 = np.full(N, np.nan); lo24 = np.full(N, np.nan)
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
        hi24[j] = h_f[maxq[0]]; lo24[j] = l_f[minq[0]]

eras = [
    ("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

def run(edge, slr, vbars):
    open_pos = []; pending=None; trades = []
    armed_up = True; armed_dn = True
    left_mid_up = None   # bar index when price last left the mid-zone heading up
    left_mid_dn = None
    for j in range(N):
        if pending is not None:
            L, tp_dist = pending; pending = None
            e = o_f[j] + (SPREAD if L else 0.0)
            open_pos.append(dict(L=L, entry=e,
                                 tp=e + tp_dist if L else e - tp_dist,
                                 sl=e - tp_dist*slr if L else e + tp_dist*slr))
        if j >= ATR_WIN and not np.isnan(hi24[j]):
            rng = hi24[j] - lo24[j]
            mid = (hi24[j] + lo24[j]) / 2.0
            half = rng / 2.0
            quiet = 100.0 * rng / c_f[j] < GATE_PCT
            c = c_f[j]
            in_mid = abs(c - mid) < 0.5 * half
            if in_mid:
                armed_up = True; armed_dn = True
                left_mid_up = j; left_mid_dn = j   # clock restarts while in the mid-zone
            if quiet and j+1 < N and len(open_pos) < MAX_POS and pending is None:
                if c >= mid + edge * half and armed_up:
                    fast = left_mid_up is not None and (j - left_mid_up) <= vbars
                    armed_up = False
                    if fast:
                        pending = (False, abs(c - mid))
                elif c <= mid - edge * half and armed_dn:
                    fast = left_mid_dn is not None and (j - left_mid_dn) <= vbars
                    armed_dn = False
                    if fast:
                        pending = (True, abs(c - mid))
        still = []
        for p in open_pos:
            if p['L']:
                htp = h_f[j] >= p['tp']; hsl = l_f[j] <= p['sl']
            else:
                htp = l_f[j] <= p['tp']; hsl = h_f[j] >= p['sl']
            if htp or hsl:
                if hsl:
                    pnl = -(abs(p['entry'] - p['sl']))*LOTS
                else:
                    pnl = abs(p['tp'] - p['entry'])*LOTS
                trades.append((int(tm_f[j]), pnl, bool(hsl)))
            else:
                still.append(p)
        open_pos = still
    total = sum(t[1] for t in trades)
    wins = sum(1 for t in trades if not t[2])
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
    be = 100.0/(1.0+ (1.0/slr))
    print(f"edge {edge:.2f} SLr {slr:.2f} fast<={vbars:>3.0f}min (BE win% {be:.1f}): "
          f"trades={len(trades):>5} win%={100*wins/len(trades) if trades else 0:>5.1f} "
          f"net=${total:>9,.2f} $/mo=${total/(span_days/30.44):>7,.2f} maxDD=${mdd:>8,.2f} "
          f"[{'  '.join(era_parts)}] ({era_pos}/3)", flush=True)

args = sys.argv[1:]
for i in range(0, len(args), 3):
    run(float(args[i]), float(args[i+1]), float(args[i+2]))
