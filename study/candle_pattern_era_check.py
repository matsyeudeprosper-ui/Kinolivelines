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

print("building signals ONCE (continuous, correct method)...")
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

def m1_color_at(idx):
    return 1 if c_f[idx] > o_f[idx] else (-1 if c_f[idx] < o_f[idx] else 0)

def run_ratchet(o,h,l,c,tm,N,sigs,trig_f,cap_f):
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    pos_sig_bar=None
    trades = []  # (entry_time, m1_fresh_bool, usd, hsl)
    for j in range(N):
        if pending is not None:
            L,entry,sig_bar,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_sig_bar = sig_bar; pos_et = et
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
            if realized_cum >= trig:
                sl_usd = min(max(realized_cum, 0.0), cap)
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,j,tm[j+1])
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd; realized_cum += usd
                m1c1 = m1_color_at(pos_sig_bar)
                m1c2 = m1_color_at(pos_sig_bar-1) if pos_sig_bar-1 >= 0 else 0
                fresh = not (m1c1 != 0 and m1c1 == m1c2)  # "fresh/mixed" = NOT a 2-bar same-direction run
                trades.append((pos_et, fresh, usd, hsl))
                in_pos=False
    return trades, bal

print("running deployed rule (ratchet trigger=30%, cap=100%)...")
trades, net = run_ratchet(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00)
print(f"total trades: {len(trades)}, net ${net:,.2f}")

eras = [
    ("2020-08-16 -> 2022-08-16", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-08-16 -> 2024-08-16", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-08-16 -> 2026-08-18", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

print("\n=== M1 fresh-vs-continuing pattern, sliced by era (from the ONE continuous run above - no signal resets) ===")
print(f"{'Era':<28} {'Fresh: n/loss/net':<28} {'Continuing: n/loss/net':<28}")
tot_fresh_net = 0.0; tot_cont_net = 0.0
for label, d0, d1 in eras:
    fresh = [t for t in trades if d0 <= t[0] < d1 and t[1]]
    cont = [t for t in trades if d0 <= t[0] < d1 and not t[1]]
    fn = sum(t[2] for t in fresh); fl = sum(1 for t in fresh if t[3])
    cn = sum(t[2] for t in cont); cl = sum(1 for t in cont if t[3])
    tot_fresh_net += fn; tot_cont_net += cn
    print(f"{label:<28} n={len(fresh):>4} loss={fl:>2} net=${fn:>+9,.2f}      n={len(cont):>4} loss={cl:>2} net=${cn:>+9,.2f}")
print(f"\nTOTAL fresh net: ${tot_fresh_net:+,.2f}   TOTAL continuing net: ${tot_cont_net:+,.2f}")
