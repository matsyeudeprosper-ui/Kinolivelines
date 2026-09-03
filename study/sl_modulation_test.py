import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timedelta
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

print("building signals once (continuous)...")
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

def m1_color_at(idx):
    return 1 if c_f[idx] > o_f[idx] else (-1 if c_f[idx] < o_f[idx] else 0)

def run_full(o,h,l,c,tm,N,sigs,trig_f,cap_f,risky_sl_pct):
    """EVERY signal still gets traded (no skipping - avoids the substitution
    effect that sank every entry-filter idea). Instead, the DEFAULT SL width
    (before the ratchet even applies) is tightened for 'risky' trades
    (M1-continuing: signal candle same direction as the one before it) to
    risky_sl_pct instead of the normal REL_SL_PCT=0.40. 'Fresh' trades keep
    the normal 0.40 width. The ratchet (trigger/cap) still applies on top,
    exactly as deployed live, using each trade's own (possibly tightened)
    default width."""
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry,et,base_pct = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_et = et
            default_sl_usd = pos_entry*base_pct*LOTS
            trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
            if realized_cum >= trig:
                sl_usd = min(max(realized_cum, 0.0), cap)
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1)
            m1c1 = m1_color_at(j)
            m1c2 = m1_color_at(j-1) if j-1 >= 0 else 0
            fresh = not (m1c1 != 0 and m1c1 == m1c2)
            base_pct = REL_SL_PCT if fresh else risky_sl_pct
            SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1],base_pct)
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd; realized_cum += usd
                trades.append((pos_et, tm[j], usd, hsl))
                in_pos=False
    return trades, bal

print("running baseline (Ratchet only, all trades at normal 40% SL - current live)...")
t0, n0 = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00,REL_SL_PCT)
l0 = sum(1 for t in t0 if t[3])
print(f"baseline: {len(t0)} trades, {l0} losses, net ${n0:,.2f}")

print("\n=== sweep: tighten SL for 'continuing' (risky) trades only, all trades still taken ===")
print("risky_sl%   trades   losses   net$        vs_baseline")
for risky_pct in [0.40, 0.35, 0.30, 0.25, 0.20, 0.15, 0.10, 0.05]:
    t, n = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00,risky_pct)
    l = sum(1 for t_ in t if t_[3])
    print(f"{100*risky_pct:>7.0f}%   {len(t):>6}   {l:>6}   ${n:>10,.2f}   ${n-n0:>+10,.2f}")
