import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import defaultdict

BRICK, REVERSAL = 50.0, 2
PT = 0.01
TP_PTS = 100.0
SPREAD_PTS = 10.0
LOTS = 0.05; SCALE = LOTS/0.01
REL_SL_PCT = 0.40

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

sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

def run_ratchet_tracked(o,h,l,c,tm,N,sigs,trig_f,cap_f):
    """Same as the deployed ratchet, but also records whether the mechanism
    was ACTIVE at each trade's entry (realized_cum >= trigger), and for
    losses while active, what the loss WOULD have cost at the normal
    default SL (to quantify money actually saved)."""
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_active=None; pos_default_sl_usd=None
    trades = []  # (entry_time, active, usd, would_be_default_usd_if_loss, hsl)
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            pos_default_sl_usd = default_sl_usd
            trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
            if realized_cum >= trig:
                sl_usd = min(max(realized_cum, 0.0), cap)
                pos_active = True
            else:
                sl_usd = default_sl_usd
                pos_active = False
            pos_sl = sl_usd/LOTS
            pos_et = et
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1])
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd; realized_cum += usd
                would_be_default_loss = -pos_default_sl_usd if hsl else None
                trades.append((pos_et, pos_active, usd, would_be_default_loss, hsl))
                in_pos=False
    return trades, bal

print("running the deployed ratchet (trigger=30%, cap=100%), tracking active/inactive per trade...")
trades, net = run_ratchet_tracked(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00)
print(f"total trades: {len(trades)}, net ${net:,.2f}")

active_trades = [t for t in trades if t[1]]
print(f"\ntrades where the guard was ACTIVE at entry: {len(active_trades)} out of {len(trades)}")
if active_trades:
    first_active = datetime.utcfromtimestamp(active_trades[0][0])
    last_active = datetime.utcfromtimestamp(active_trades[-1][0])
    print(f"first active trade: {first_active}   last active trade: {last_active}")

active_losses = [t for t in active_trades if t[4]]
print(f"\nof those, LOSSES while active: {len(active_losses)}")
total_saved = 0.0
for et, active, usd, would_be, hsl in active_losses:
    dt = datetime.utcfromtimestamp(et)
    saved = would_be - usd  # would_be is negative (bigger loss), usd is the actual (smaller) loss
    total_saved += saved
    print(f"  {dt.strftime('%Y-%m-%d %H:%M')}  actual loss ${usd:>+9,.2f}   would've been ${would_be:>+9,.2f} at normal SL   SAVED ${saved:>8,.2f}")
print(f"\nTOTAL directly saved by the guard being active during a loss: ${total_saved:,.2f}")

active_wins = [t for t in active_trades if not t[4]]
print(f"\nwins while active (guard doesn't change these - TP is fixed): {len(active_wins)}, total ${sum(t[2] for t in active_wins):,.2f}")

# how many separate "active stretches" (consecutive active trades) were there
stretches = 0
prev_active = False
for t in trades:
    if t[1] and not prev_active:
        stretches += 1
    prev_active = t[1]
print(f"\nnumber of separate times the guard turned ON (armed) over the 6 years: {stretches}")
