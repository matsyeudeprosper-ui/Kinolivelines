"""User idea 2026-08-22 #2: PARTIAL runner. First trade after each confirmed
H4 flip (0.02 lots, with the regime). When it reaches +150pts (the $3 TP
level): bank HALF (0.01 = $1.50), keep 0.01 as runner with SL at
entry+5pts (breakeven, risk-free). Runner exits at BE-stop (+$0.05) or at
regime flip-back (market). If the regime flips back BEFORE +150 is reached,
the full 0.02 closes at flip price (same in both versions - excluded from
the comparison, counted for context).
Baseline = closing the full 0.02 at +150 for $3.00.
Question: does the runner's average payoff beat the $1.50 given up?
"""
import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = 10.0
TP_PTS = 150.0
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

# regime + flip indices
mode = 0; lg = lr = None; cur = None
flip_at = []          # (bar_index, dir)
regime_arr = np.zeros(N, dtype=np.int8)
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
    if closed is not None:
        op4, _, _, cl4 = closed
        if cl4 > op4:
            lg = op4
            if mode == 0: mode = 1
            elif mode == -1 and lr is not None and cl4 > lr:
                mode = 1; flip_at.append((i, 1))
        elif cl4 < op4:
            lr = op4
            if mode == 0: mode = -1
            elif mode == 1 and lg is not None and cl4 < lg:
                mode = -1; flip_at.append((i, -1))
    regime_arr[i] = mode

print(f"{len(flip_at)} flips", flush=True)

reached_tp = 0
died_before_tp = 0
runner_be = 0
runner_flip_wins = []
extra_total = 0.0     # (partial version) - (baseline) on trades that reached TP
for k, (fi, d) in enumerate(flip_at):
    if fi + 1 >= N: break
    ep = o[fi + 1] + (SPREAD if d == 1 else 0.0)
    tp = ep + d * TP_PTS
    sl = ep + d * BE_BUF
    stage = 0   # 0=full position waiting for TP, 1=runner
    end = flip_at[k + 1][0] if k + 1 < len(flip_at) else N - 1
    outcome = None
    for i in range(fi + 1, end + 1):
        if stage == 0:
            hit_tp = (h[i] >= tp) if d == 1 else (l[i] <= tp)
            if hit_tp:
                stage = 1
                reached_tp += 1
                continue
            if i == end:                     # flip-back before TP: same in both versions
                died_before_tp += 1
                outcome = 'died'
        else:
            hit_sl = (l[i] <= sl) if d == 1 else (h[i] >= sl)
            if hit_sl:
                runner_pnl = BE_BUF * 0.01
                extra_total += runner_pnl - 1.50
                runner_be += 1
                outcome = 'be'
                break
            if i == end:                     # regime flip-back: runner exits at market
                runner_pnl = (c[i] - ep) * 0.01 * d
                extra_total += runner_pnl - 1.50
                runner_flip_wins.append(runner_pnl)
                outcome = 'ride'
if runner_flip_wins:
    rw = np.array(runner_flip_wins)
span_mo = (tm[-1] - tm[0]) / 86400 / 30.44
print(f"\nfirst-trades that reached the +150 TP stage: {reached_tp}")
print(f"flipped back before TP (same in both versions): {died_before_tp}")
print(f"runner outcomes: BE-stopped {runner_be} (+$0.05 each) | rode to flip-back {len(runner_flip_wins)}")
if runner_flip_wins:
    print(f"riders: avg ${rw.mean():,.2f}  median ${np.median(rw):,.2f}  best ${rw.max():,.2f}  worst ${rw.min():,.2f}")
print(f"\nEXTRA vs baseline (runner payoff minus the $1.50 given up, summed):")
print(f"  ${extra_total:,.2f} over 6yr  (${extra_total/span_mo:,.2f}/mo)")
print(f"  per TP-stage trade: ${extra_total/max(1,reached_tp):,.3f}")
