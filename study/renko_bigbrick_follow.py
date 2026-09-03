"""Renko-following with BIGGER bricks (spread tax shrinks as bricks grow).
Brick size expressed BOTH ways: fixed points, and % of price (scale-safe,
the lesson from the relative-SL fix). Variant B logic only (flip on color
change) - variant A's roll-every-brick is strictly tax-bleed, not retested.
Args: list of brick specs, e.g. 500 1000 2000 p0.5 p1 p2  (p = % of price)"""
import sys, json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = 10.0
LOTS = 0.05

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
o_f = np.array([rows[t][0] for t in times]); c_f = np.array([rows[t][3] for t in times])
tm_f = np.array(times)
N = len(times)

eras = [
    ("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

def run(brick_spec):
    pct_mode = brick_spec.startswith("p")
    if pct_mode:
        pct = float(brick_spec[1:]) / 100.0
    else:
        fixed = float(brick_spec)
    # build classic renko; % mode: brick size recomputed from the anchor each step
    bricks = []
    anchor = c_f[0]
    for j in range(N):
        c = c_f[j]
        while True:
            b = anchor * pct if pct_mode else fixed
            if c >= anchor + b:
                anchor += b; bricks.append((j, 1))
            elif c <= anchor - b:
                anchor -= b; bricks.append((j, -1))
            else:
                break
    # variant B: flip on color change
    trades = []
    pos = None; prev_dir = 0
    for (j, d) in bricks:
        if j+1 >= N: break
        if d == prev_dir: continue
        op = o_f[j+1]; t = int(tm_f[j+1])
        if pos is not None:
            pd_, pe = pos
            exit_p = op if pd_ == 1 else op + SPREAD
            pnl = (exit_p - pe)*LOTS if pd_ == 1 else (pe - exit_p)*LOTS
            trades.append((t, pnl))
        pos = (d, op + SPREAD if d == 1 else op)
        prev_dir = d
    total = sum(t[1] for t in trades)
    wins = sum(1 for t in trades if t[1] > 0)
    peak=0.0; cum=0.0; mdd=0.0
    for _,usd in trades:
        cum += usd
        if cum > peak: peak = cum
        if peak-cum > mdd: mdd = peak-cum
    span_days = (tm_f[-1]-tm_f[0])/86400
    era_parts=[]
    for lbl,d0,d1 in eras:
        gn = sum(t[1] for t in trades if d0<=t[0]<d1)
        era_parts.append(f"{lbl}:{gn:+,.0f}")
    label = f"{brick_spec[1:]}% of price" if pct_mode else f"{brick_spec}pts"
    print(f"brick {label:<14} bricks={len(bricks):>7} flips={len(trades):>6} "
          f"win%={100*wins/len(trades) if trades else 0:>5.1f} net=${total:>11,.2f} "
          f"$/mo=${total/(span_days/30.44):>8,.2f} maxDD=${mdd:>10,.2f}  [{'  '.join(era_parts)}]", flush=True)

for spec in sys.argv[1:]:
    run(spec)
