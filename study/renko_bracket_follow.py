"""Renko-follow with a BRACKET (user spec 2026-08-19): TP = 8 bricks,
SL = 4 bricks. Enter in the brick's direction, one position at a time.
Variant 'flip': enter only when brick color CHANGES (fresh direction).
Variant 'any':  enter on any new brick when flat (follow prevailing color).
Args: brick_pts variant   e.g. 50 flip"""
import sys, json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = 10.0
LOTS = 0.05
TP_BRICKS = 8
SL_BRICKS = 4

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

eras = [
    ("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

def run(brick, variant):
    # classic renko signal stream: (bar_index, dir, is_flip)
    sigs = []
    anchor = c_f[0]; prev_dir = 0
    for j in range(N):
        c = c_f[j]
        while True:
            if c >= anchor + brick:
                anchor += brick; d = 1
            elif c <= anchor - brick:
                anchor -= brick; d = -1
            else:
                break
            sigs.append((j, d, d != prev_dir))
            prev_dir = d
    # sequenced sim, one bracket position at a time
    tp_d = TP_BRICKS * brick; sl_d = SL_BRICKS * brick
    trades = []
    in_pos = False; pos_L=None; entry=None; tpp=None; slp=None
    pending = None
    si = 0
    sig_by_bar = {}
    for (j, d, flip) in sigs:
        if variant == "flip" and not flip:
            continue
        sig_by_bar.setdefault(j, d)   # last signal per bar is fine at this granularity
    for j in range(N):
        if pending is not None:
            L = pending; pending = None
            e = o_f[j] + (SPREAD if L else 0.0)
            in_pos=True; pos_L=L; entry=e
            tpp = e + tp_d if L else e - tp_d
            slp = e - sl_d if L else e + sl_d
        if j in sig_by_bar and j+1 < N and not in_pos:
            pending = (sig_by_bar[j] == 1)
        if in_pos:
            if pos_L:
                htp = h_f[j] >= tpp; hsl = l_f[j] <= slp
            else:
                htp = l_f[j] <= tpp; hsl = h_f[j] >= slp
            if htp or hsl:
                pnl = (-sl_d if hsl else tp_d) * LOTS
                trades.append((int(tm_f[j]), pnl, bool(hsl)))
                in_pos=False
    total = sum(t[1] for t in trades)
    wins = sum(1 for t in trades if not t[2])
    peak=0.0; cum=0.0; mdd=0.0
    for _,usd,_ in trades:
        cum += usd
        if cum > peak: peak = cum
        if peak-cum > mdd: mdd = peak-cum
    span_days = (tm_f[-1]-tm_f[0])/86400
    era_parts=[]
    for lbl,d0,d1 in eras:
        gn = sum(t[1] for t in trades if d0<=t[0]<d1)
        era_parts.append(f"{lbl}:{gn:+,.0f}")
    print(f"brick {brick:>5g}pts {variant:<5} TP8/SL4: trades={len(trades):>6} win%={100*wins/len(trades) if trades else 0:>5.1f} "
          f"net=${total:>10,.2f} $/mo=${total/(span_days/30.44):>7,.2f} maxDD=${mdd:>9,.2f}  [{'  '.join(era_parts)}]", flush=True)

for i in range(1, len(sys.argv), 2):
    run(float(sys.argv[i]), sys.argv[i+1])
