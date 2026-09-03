"""User idea 2026-08-22: 'runner' trade — at each confirmed H4 flip, open one
0.02-lot trade WITH the new regime; once it is ARM_PTS in profit, SL moves to
breakeven+5pts (risk-free); exit at BE-stop or when the regime flips back.
Before arming there is no SL (user style) — exposed until BE or flip-back.
Sweep ARM_PTS. Regime = confirmed-flip state machine (red H4 closing below
last green H4's open, mirror). Spread 10pts on buys.
"""
import sys, json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = 10.0
LOTS = 0.02
BE_BUF = 5.0

files = ['coinbase_m1_2yr_partneg1.json','coinbase_m1_2yr_part0.json','coinbase_m1_2yr_part1.json',
         'coinbase_m1_2yr_part2.json','coinbase_m1_extra_year.json','coinbase_m1_pilot.json']
rows = {}
for f in files:
    for t, lo, hi, op, cl, vol in json.load(open(f)):
        rows[int(t)] = (op, hi, lo, cl)
mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select("BTCUSDm", True)
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 99000)
mt5.shutdown()
for i in range(len(r)):
    rows[int(r["time"][i])] = (float(r["open"][i]), float(r["high"][i]), float(r["low"][i]), float(r["close"][i]))
times = sorted(rows.keys())
o = np.array([rows[t][0] for t in times]); h = np.array([rows[t][1] for t in times])
l = np.array([rows[t][2] for t in times]); c = np.array([rows[t][3] for t in times])
tm = np.array(times); N = len(times)
print(f"{N} M1 bars", flush=True)

eras = [("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
        ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
        ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,23).timestamp())]

def run(ARM_PTS):
    mode = 0
    lg = lr = None
    cur = None      # forming H4 [wid, o,h,l,c]
    pos = None      # dict: dir, entry, armed, sl
    trades = []
    flips = 0
    pending_dir = 0
    for i in range(N):
        wid = tm[i] // 14400
        closed = None
        if cur is None or cur[0] != wid:
            if cur is not None:
                closed = (cur[1], cur[2], cur[3], cur[4])
            cur = [wid, o[i], h[i], l[i], c[i]]
        else:
            if h[i] > cur[2]: cur[2] = h[i]
            if l[i] < cur[3]: cur[3] = l[i]
            cur[4] = c[i]
        flipped = 0
        if closed is not None:
            op4, _, _, cl4 = closed
            if cl4 > op4:
                lg = op4
                if mode == 0: mode = 1
                elif mode == -1 and lr is not None and cl4 > lr:
                    mode = 1; flipped = 1
            elif cl4 < op4:
                lr = op4
                if mode == 0: mode = -1
                elif mode == 1 and lg is not None and cl4 < lg:
                    mode = -1; flipped = -1
        # manage open runner
        if pos is not None:
            d = pos['dir']
            # arm BE
            if not pos['armed']:
                fav = (h[i] - pos['entry']) if d == 1 else (pos['entry'] - l[i])
                if fav >= ARM_PTS:
                    pos['armed'] = True
                    pos['sl'] = pos['entry'] + d * BE_BUF
            # BE stop hit?
            if pos['armed']:
                hit = (l[i] <= pos['sl']) if d == 1 else (h[i] >= pos['sl'])
                if hit:
                    pnl = (pos['sl'] - pos['entry']) * LOTS * d
                    trades.append((tm[i], pnl, 'be_stop'))
                    pos = None
            # regime flip-back -> close at market
            if pos is not None and flipped and flipped != pos['dir']:
                pnl = (c[i] - pos['entry']) * LOTS * pos['dir']
                trades.append((tm[i], pnl, 'flip_exit'))
                pos = None
        # open new runner on flip (next bar open)
        if flipped and pos is None:
            pending_dir = flipped
        elif pending_dir and pos is None and i + 1 < N:
            d = pending_dir
            ep = o[i] + (SPREAD if d == 1 else 0.0)
            pos = {'dir': d, 'entry': ep, 'armed': False, 'sl': None}
            pending_dir = 0
            flips += 1
    if pos is not None:
        trades.append((tm[-1], (c[-1] - pos['entry']) * LOTS * pos['dir'], 'open_end'))
    total = sum(t[1] for t in trades)
    wins = [t for t in trades if t[1] > 1.0]
    bes = [t for t in trades if -1.0 <= t[1] <= 1.0]
    losses = [t for t in trades if t[1] < -1.0]
    peak = cum = mdd = 0.0
    for _, pnl, _ in trades:
        cum += pnl
        if cum > peak: peak = cum
        if peak - cum > mdd: mdd = peak - cum
    # worst single open drawdown estimate: track per trade? quick: worst loss
    span_mo = (tm[-1] - tm[0]) / 86400 / 30.44
    print(f"\nARM {ARM_PTS:>5.0f}pts: runners={len(trades)} | big-wins {len(wins)} "
          f"(avg ${np.mean([t[1] for t in wins]):,.2f}, best ${max(t[1] for t in wins):,.2f}) | "
          f"BE-outs {len(bes)} | losses {len(losses)} "
          f"(avg ${np.mean([t[1] for t in losses]) if losses else 0:,.2f}, worst ${min((t[1] for t in losses), default=0):,.2f})")
    print(f"          NET ${total:,.2f} (${total/span_mo:,.2f}/mo)  seq maxDD ${mdd:,.2f}")
    for lbl, d0, d1 in eras:
        g = sum(t[1] for t in trades if d0 <= t[0] < d1)
        n = sum(1 for t in trades if d0 <= t[0] < d1)
        print(f"          {lbl}: n={n} net=${g:,.2f}")

for arm in [200.0, 500.0, 1000.0]:
    run(arm)
