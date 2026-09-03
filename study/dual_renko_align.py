"""User spec 2026-08-19: dual-renko alignment. The 100pt classic renko
chart's latest brick color gates direction; entries fire on each new
50pt brick that MATCHES that color (BUY on green/green, SELL on red/red).
cap=1, entry at next M1 open (+spread on buys). Three exits:
  A: bracket TP 1% / SL 0.5% of entry (turtle-style)
  B: bracket TP 400pts / SL 200pts (8/4 bricks of the 50 chart)
  C: hold until the 100pt chart's brick color flips against the position"""
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
o_f = np.array([rows[t][0] for t in times]); h_f = np.array([rows[t][1] for t in times])
l_f = np.array([rows[t][2] for t in times]); c_f = np.array([rows[t][3] for t in times])
tm_f = np.array(times)
N = len(times)

def classic_bricks(brick):
    out = []
    anchor = c_f[0]
    for j in range(N):
        c = c_f[j]
        while c >= anchor + brick or c <= anchor - brick:
            if c >= anchor + brick:
                anchor += brick; out.append((j, 1))
            else:
                anchor -= brick; out.append((j, -1))
    return out

print("building 50pt and 100pt classic renko streams...", flush=True)
b50 = classic_bricks(50.0)
b100 = classic_bricks(100.0)
print(f"50pt bricks: {len(b50)}   100pt bricks: {len(b100)}", flush=True)

# per-bar last-brick-dir maps (as of END of bar j)
dir100 = np.zeros(N, dtype=np.int8)
d = 0; k = 0
for j in range(N):
    while k < len(b100) and b100[k][0] <= j:
        d = b100[k][1]; k += 1
    dir100[j] = d
sig50 = {}
for j, d in b50:
    sig50[j] = d   # last 50-brick of the bar wins

eras = [
    ("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

def report(trades, label):
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
    print(f"{label:<28} trades={len(trades):>6} win%={100*wins/len(trades) if trades else 0:>5.1f} "
          f"net=${total:>10,.2f} $/mo=${total/(span_days/30.44):>7,.2f} maxDD=${mdd:>9,.2f} [{'  '.join(era_parts)}]", flush=True)

def run_bracket(tp_mode, tp_val, sl_val):
    """tp_mode 'pct': tp/sl as fraction of entry; 'pts': fixed points."""
    trades=[]; pending=None; in_pos=False; pos_L=None; e=None; tpp=None; slp=None
    for j in range(N):
        if pending is not None:
            L = pending; pending=None
            e_ = o_f[j] + (SPREAD if L else 0.0)
            if tp_mode == 'pct':
                tp_d = e_*tp_val; sl_d = e_*sl_val
            else:
                tp_d = tp_val; sl_d = sl_val
            in_pos=True; pos_L=L; e=e_
            tpp = e_+tp_d if L else e_-tp_d
            slp = e_-sl_d if L else e_+sl_d
        if j in sig50 and j+1 < N and not in_pos:
            d50 = sig50[j]
            if d50 == dir100[j] and d50 != 0:
                pending = (d50 == 1)
        if in_pos:
            if pos_L:
                htp = h_f[j] >= tpp; hsl = l_f[j] <= slp
            else:
                htp = l_f[j] <= tpp; hsl = h_f[j] >= slp
            if htp or hsl:
                pnl = (-(abs(e-slp)) if hsl else abs(tpp-e))*LOTS
                trades.append((int(tm_f[j]), pnl))
                in_pos=False
    return trades

def run_flip_exit():
    trades=[]; pending=None; in_pos=False; pos_L=None; e=None
    for j in range(N):
        if pending is not None:
            L = pending; pending=None
            e = o_f[j] + (SPREAD if L else 0.0)
            in_pos=True; pos_L=L
        if in_pos:
            d100 = dir100[j]
            if (pos_L and d100 == -1) or ((not pos_L) and d100 == 1):
                if j+1 < N:
                    op = o_f[j+1]
                    exit_p = op if pos_L else op + SPREAD
                    pnl = (exit_p-e)*LOTS if pos_L else (e-exit_p)*LOTS
                    trades.append((int(tm_f[j+1]), pnl))
                    in_pos=False
        if j in sig50 and j+1 < N and not in_pos and pending is None:
            d50 = sig50[j]
            if d50 == dir100[j] and d50 != 0:
                pending = (d50 == 1)
    return trades

print("running exit A: TP1%/SL0.5% bracket...", flush=True)
report(run_bracket('pct', 0.01, 0.005), "A: aligned + TP1%/SL0.5%")
print("running exit B: TP400/SL200 pts bracket...", flush=True)
report(run_bracket('pts', 400.0, 200.0), "B: aligned + TP400/SL200")
print("running exit C: hold until 100-chart flips...", flush=True)
report(run_flip_exit(), "C: aligned + exit on 100-flip")
