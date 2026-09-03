"""User idea 2026-08-22 #3: ALIGNED PARTIAL RUNNER.
Only when H4 regime == D1 regime (both confirmed-flip state machines agree):
the first trade after alignment begins (0.02, with the trend) runs the
normal scalp path. If it reaches +150pts: bank half (+$1.50), keep 0.01 as
runner with BE+5 stop; the runner rides the DAILY clock (exits at BE stop or
at the next D1 flip). If alignment breaks (either clock flips) before +150:
full position exits at market (managed-out approximation).
Baseline for comparison = taking the full $3 at +150.
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

def regime_array(tfsec):
    mode = 0; lg = lr = None; cur = None
    out = np.zeros(N, dtype=np.int8)
    for i in range(N):
        wid = tm[i] // tfsec
        closed = None
        if cur is None or cur[0] != wid:
            if cur is not None:
                closed = (cur[1], cur[4])
            cur = [wid, o[i], h[i], l[i], c[i]]
        else:
            cur[4] = c[i]
        if closed is not None:
            op_, cl_ = closed
            if cl_ > op_:
                lg = op_
                if mode == 0: mode = 1
                elif mode == -1 and lr is not None and cl_ > lr: mode = 1
            elif cl_ < op_:
                lr = op_
                if mode == 0: mode = -1
                elif mode == 1 and lg is not None and cl_ < lg: mode = -1
        out[i] = mode
    return out

print("building regimes...", flush=True)
h4 = regime_array(14400)
d1 = regime_array(86400)
aligned = (h4 == d1) & (h4 != 0)
print(f"aligned {100*aligned.mean():.1f}% of the time", flush=True)

trades = []          # (t, partial_version_pnl, baseline_pnl, kind)
i = 1
while i < N - 1:
    if aligned[i] and not aligned[i - 1]:
        d = int(h4[i])
        ep = o[i + 1] + (SPREAD if d == 1 else 0.0)
        tp = ep + d * TP_PTS
        sl = ep + d * BE_BUF
        stage = 0
        j = i + 1
        done = False
        while j < N and not done:
            if stage == 0:
                if not aligned[j]:            # alignment broke pre-TP: both versions exit
                    pnl = (c[j] - ep) * 0.02 * d
                    trades.append((tm[j], pnl, pnl, 'broke_pre_tp'))
                    done = True
                elif (h[j] >= tp) if d == 1 else (l[j] <= tp):
                    stage = 1                 # banked $1.50, runner armed at BE
            else:
                if (l[j] <= sl) if d == 1 else (h[j] >= sl):
                    trades.append((tm[j], 1.50 + BE_BUF * 0.01, 3.00, 'runner_be'))
                    done = True
                elif d1[j] != d:              # daily flip: runner harvest
                    pnl_run = (c[j] - ep) * 0.01 * d
                    trades.append((tm[j], 1.50 + pnl_run, 3.00, 'runner_ride'))
                    done = True
            j += 1
        if not done and j >= N:
            if stage == 1:
                trades.append((tm[-1], 1.50 + (c[-1] - ep) * 0.01 * d, 3.00, 'open_end'))
            else:
                pnl = (c[-1] - ep) * 0.02 * d
                trades.append((tm[-1], pnl, pnl, 'open_end'))
        i = j
    else:
        i += 1

part = sum(t[1] for t in trades)
# drawdown + monthly stats of the partial+runner equity curve
cum = peak = mdd = 0.0
worst_streak = streak = 0.0
for t in sorted(trades):
    cum += t[1]
    if cum > peak: peak = cum
    if peak - cum > mdd: mdd = peak - cum
    if t[1] < 0:
        streak += t[1]
        if streak < worst_streak: worst_streak = streak
    else:
        streak = 0.0
import collections
months = collections.defaultdict(float)
from datetime import datetime as _dt
for t in trades:
    months[_dt.utcfromtimestamp(int(t[0])).strftime('%Y-%m')] += t[1]
mv = sorted(months.values())
pos_months = sum(1 for v in mv if v > 0)
print(f"DD/RISK: sequence maxDD ${mdd:,.2f} | worst losing streak ${worst_streak:,.2f}")
print(f"months: {len(mv)} | positive: {pos_months} ({100*pos_months/len(mv):.0f}%) | best +${mv[-1]:,.2f} | worst ${mv[0]:,.2f} | median ${mv[len(mv)//2]:,.2f}")
base = sum(t[2] for t in trades)
rides = [t for t in trades if t[3] == 'runner_ride']
bes = [t for t in trades if t[3] == 'runner_be']
broke = [t for t in trades if t[3] == 'broke_pre_tp']
span_mo = (tm[-1] - tm[0]) / 86400 / 30.44
print(f"\nalignment-start trades: {len(trades)}")
print(f"  broke before +150 (same both versions): {len(broke)} (sum ${sum(t[1] for t in broke):,.2f})")
print(f"  runner BE-stopped: {len(bes)}")
print(f"  runner rode to D1 flip: {len(rides)}")
if rides:
    rv = np.array([t[1] - 1.50 for t in rides])
    print(f"    rides: avg ${rv.mean():,.2f}  median ${np.median(rv):,.2f}  best ${rv.max():,.2f}")
print(f"\nPARTIAL+RUNNER total: ${part:,.2f} (${part/span_mo:,.2f}/mo)")
print(f"BASELINE (full $3)  : ${base:,.2f} (${base/span_mo:,.2f}/mo)")
print(f"EXTRA from the runner design: ${part-base:,.2f} over 6yr (${(part-base)/span_mo:,.2f}/mo)")
eras = [("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
        ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
        ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,23).timestamp())]
for lbl, d0, d1e in eras:
    e = sum(t[1] - t[2] for t in trades if d0 <= t[0] < d1e)
    print(f"  {lbl}: runner extra ${e:,.2f}")
