"""Simple renko-following backtest, per the user's spec (2026-08-19):
classic 50pt renko (the chart's own rule from build_custom_bars.py -
brick completes when close moves 50pts from the anchor), green brick = be
long, red brick = be short.
Variant A: every new brick closes the old trade and opens fresh (literal).
Variant B: hold through same-color bricks, flip only on color change.
Spread modeled as buy-at-ask (+10pts), sell-at-bid - each round trip costs
10pts. LOTS=0.05 for comparability with the other backtests."""
import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import defaultdict

BRICK = 50.0
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

print("building classic 50pt renko bricks (the chart's rule)...", flush=True)
bricks = []   # (bar_index_of_completion, dir)
anchor = c_f[0]
for j in range(N):
    c = c_f[j]
    while c >= anchor + BRICK or c <= anchor - BRICK:
        if c >= anchor + BRICK:
            anchor += BRICK; bricks.append((j, 1))
        else:
            anchor -= BRICK; bricks.append((j, -1))
print(f"bricks: {len(bricks)}", flush=True)

eras = [
    ("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

def report(trades, label):
    total = sum(t[1] for t in trades)
    wins = sum(1 for t in trades if t[1] > 0); losses = len(trades)-wins
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
    print(f"\n=== {label} ===")
    print(f"trades: {len(trades)}  wins: {wins} ({100*wins/len(trades):.1f}%)  net: ${total:,.2f}  "
          f"$/mo: ${total/(span_days/30.44):,.2f}  maxDD: ${mdd:,.2f}")
    print("eras: " + "  ".join(era_parts))

# entry/exit at the NEXT M1 bar's open after the brick completes.
# long: enter at open+SPREAD (ask), exit at open (bid).
# short: enter at open (bid), exit at open+SPREAD (ask).

print("variant A: literal - every brick closes old + opens new...", flush=True)
tradesA = []
pos = None   # (dir, entry_price)
for k,(j, d) in enumerate(bricks):
    if j+1 >= N: break
    op = o_f[j+1]; t = int(tm_f[j+1])
    if pos is not None:
        pd_, pe = pos
        exit_p = op if pd_ == 1 else op + SPREAD
        pnl = (exit_p - pe)*LOTS if pd_ == 1 else (pe - exit_p)*LOTS
        tradesA.append((t, pnl))
    entry = op + SPREAD if d == 1 else op
    pos = (d, entry)
report(tradesA, "A: roll every brick (literal reading)")

print("variant B: flip only on color change...", flush=True)
tradesB = []
pos = None
prev_dir = 0
for k,(j, d) in enumerate(bricks):
    if j+1 >= N: break
    if d == prev_dir:
        continue
    op = o_f[j+1]; t = int(tm_f[j+1])
    if pos is not None:
        pd_, pe = pos
        exit_p = op if pd_ == 1 else op + SPREAD
        pnl = (exit_p - pe)*LOTS if pd_ == 1 else (pe - exit_p)*LOTS
        tradesB.append((t, pnl))
    entry = op + SPREAD if d == 1 else op
    pos = (d, entry)
    prev_dir = d
report(tradesB, "B: stop-and-reverse on color change only")
