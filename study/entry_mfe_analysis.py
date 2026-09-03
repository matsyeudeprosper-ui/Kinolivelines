"""For every brick-reversal signal: how far does price travel IN FAVOR
(max favorable excursion, points) before first moving 0.5% ADVERSE
(the turtle's stop)? Distribution answers 'how much room does each
entry give'."""
import json
import numpy as np
import MetaTrader5 as mt5

BRICK, REVERSAL = 50.0, 2
SPREAD = 10.0
ADV_PCT = 0.005

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

print("building signals...", flush=True)
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

print("measuring max favorable move before a 0.5% adverse move, per signal...", flush=True)
CHUNK = 5000
mfes = []
for j in sorted(sigs.keys()):
    if j+1 >= N: continue
    L = (sigs[j] == 1)
    entry = o_f[j+1] + (SPREAD if L else 0.0)
    adv = entry * ADV_PCT
    stop = entry - adv if L else entry + adv
    best = 0.0
    pos = j+1
    done = False
    while pos < N and not done:
        end = min(N, pos + CHUNK)
        for k in range(pos, end):
            if L:
                fav = h_f[k] - entry
                hit = l_f[k] <= stop
            else:
                fav = entry - l_f[k]
                hit = h_f[k] >= stop
            if fav > best: best = fav
            if hit:
                done = True; break
        pos = end
    mfes.append(best)

a = np.array(mfes)
print(f"\nsignals measured: {len(a)}")
print(f"favorable travel (points) before a 0.5% adverse move:")
for p in [5, 10, 25, 50, 75, 90]:
    print(f"  {p}th percentile: {np.percentile(a, p):8.1f} pts")
print(f"  mean:            {a.mean():8.1f} pts")
print(f"\nshare of entries reaching at least X points in favor first:")
for x in [10, 20, 30, 50, 100, 200, 340, 680]:
    print(f"  >= {x:>4} pts: {100*np.mean(a >= x):5.1f}%")
print("\n(reference: 100pts = V1's $5 TP; ~680pts = turtle's 1% TP at $68k)")
