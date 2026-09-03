"""Variant of h1_sweep_test: after the M1 sweep, require a CONFIRMATION candle
before entering. soft = next bar closes beyond sweep bar close (green for buy),
strong = next bar closes beyond sweep bar high/low. Entry on the bar after
confirmation. Same H1 bias, 1 trade/hour, TP $3 / SL $3 @ 0.02 lots.
Run: python h1_sweep_confirm_test.py [spread] [soft|strong]
"""
import sys, json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
MODE = sys.argv[2] if len(sys.argv) > 2 else "strong"
LOTS = 0.02
TP_PTS = 3.0 / LOTS
SL_PTS = 3.0 / LOTS

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
print(f"{N} M1 bars loaded  mode={MODE} spread={SPREAD}", flush=True)

hour_id = tm_f // 3600
h1 = {}
for i in range(N):
    hid = hour_id[i]
    e = h1.get(hid)
    if e is None:
        h1[hid] = [h_f[i], l_f[i]]
    else:
        if h_f[i] > e[0]: e[0] = h_f[i]
        if l_f[i] < e[1]: e[1] = l_f[i]

def bias_for(hid):
    a = h1.get(hid-1); b = h1.get(hid-2)
    if a is None or b is None:
        return False, False
    return a[0] > b[0], a[1] < b[1]

eras = [
    ("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,20).timestamp()),
]

in_pos=False; pos_L=None; pos_entry=None
pending=None
sweep=None   # (is_long, sweep_bar_index)
last_trade_hour=-1
trades=[]
cur_hid=-1; buy_ok=sell_ok=False
for j in range(1, N):
    hid = hour_id[j]
    if hid != cur_hid:
        cur_hid = hid
        buy_ok, sell_ok = bias_for(hid)
        sweep = None   # sweep does not carry across the hour boundary
    if pending is not None:
        L, entry = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
    if in_pos:
        tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
        slp = pos_entry-SL_PTS if pos_L else pos_entry+SL_PTS
        htp = (h_f[j]>=tpp) if pos_L else (l_f[j]<=tpp)
        hsl = (l_f[j]<=slp) if pos_L else (h_f[j]>=slp)
        if htp or hsl:
            usd = (-SL_PTS if hsl else TP_PTS)*LOTS
            trades.append((int(tm_f[j]), usd, hsl, pos_L))
            in_pos=False
    if in_pos or pending is not None or hid == last_trade_hour or j+1 >= N:
        continue
    if tm_f[j] - tm_f[j-1] != 60:
        sweep = None
        continue
    # confirmation check first (sweep set on an earlier bar)
    if sweep is not None:
        L, s = sweep
        if L:
            ref = c_f[s] if MODE == "soft" else h_f[s]
            if c_f[j] > ref:
                pending=(True, o_f[j+1]+SPREAD); last_trade_hour=hid; sweep=None
                continue
        else:
            ref = c_f[s] if MODE == "soft" else l_f[s]
            if c_f[j] < ref:
                pending=(False, o_f[j+1]); last_trade_hour=hid; sweep=None
                continue
        sweep = None   # confirmation failed -> discard, allow a new sweep
    # sweep detection
    if buy_ok and l_f[j] <= l_f[j-1] and c_f[j] >= l_f[j-1]:
        sweep=(True, j)
    elif sell_ok and h_f[j] >= h_f[j-1] and c_f[j] <= h_f[j-1]:
        sweep=(False, j)

total = sum(t[1] for t in trades)
wins = sum(1 for t in trades if not t[2])
buys = sum(1 for t in trades if t[3]); sells=len(trades)-buys
peak=cum=mdd=0.0
for _,usd,_,_ in trades:
    cum+=usd
    if cum>peak: peak=cum
    if peak-cum>mdd: mdd=peak-cum
span_days=(tm_f[-1]-tm_f[0])/86400
print(f"CONFIRM-{MODE} TP$3/SL$3 @0.02 sp{SPREAD:.0f}: trades={len(trades)} (buy {buys}/sell {sells}) "
      f"win%={100*wins/max(1,len(trades)):.1f} net=${total:,.2f} $/mo=${total/(span_days/30.44):,.2f} maxDD=${mdd:,.2f}", flush=True)
for lbl,d0,d1 in eras:
    tr=[t for t in trades if d0<=t[0]<d1]
    gn=sum(t[1] for t in tr)
    w=sum(1 for t in tr if not t[2])
    print(f"  {lbl}: trades={len(tr)} win%={100*w/max(1,len(tr)):.1f} net=${gn:,.2f}", flush=True)
