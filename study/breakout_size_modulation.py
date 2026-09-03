import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

BRICK, REVERSAL = 50.0, 2
PT = 0.01
TP_PTS = 100.0
SPREAD_PTS = 10.0
FULL_LOTS = 0.05
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

print("building M1 signals once (continuous)...")
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

print("building M5 bars (for the Breakout chart, chain mode)...")
m5_idx = (tm_f // 300).astype(np.int64)
m5_uniq, m5_first = np.unique(m5_idx, return_index=True)
n5 = len(m5_uniq)
m5_bounds = list(m5_first) + [N]
m5_o = np.empty(n5); m5_h = np.empty(n5); m5_l = np.empty(n5); m5_c = np.empty(n5)
for k in range(n5):
    s,e = m5_bounds[k], m5_bounds[k+1]
    m5_o[k]=o_f[s]; m5_h[k]=h_f[s:e].max(); m5_l[k]=l_f[s:e].min(); m5_c[k]=c_f[e-1]
m5_close_time = np.array([int(tm_f[m5_bounds[k+1]-1]) + 60 for k in range(n5)])

print("applying the CHAIN breakout filter...")
kept_idx = [0]; kept_dir = [0]
ref_hi, ref_lo = m5_h[0], m5_l[0]
for i in range(1, n5):
    if m5_c[i] > ref_hi:
        kept_idx.append(i); kept_dir.append(1)
        ref_hi, ref_lo = m5_h[i], m5_l[i]
    elif m5_c[i] < ref_lo:
        kept_idx.append(i); kept_dir.append(-1)
        ref_hi, ref_lo = m5_h[i], m5_l[i]
kept_close_time = np.array([m5_close_time[i] for i in kept_idx])
kept_dir_arr = np.array(kept_dir)
print(f"M5 bars: {n5}, kept: {len(kept_idx)} ({100*len(kept_idx)/n5:.1f}%)")

def latest_kept_dir_before(t_epoch):
    pos = np.searchsorted(kept_close_time, t_epoch, side='right') - 1
    if pos < 0:
        return 0
    return int(kept_dir_arr[pos])

def run_full(o,h,l,c,tm,N,sigs,trig_f,cap_f,unconfirmed_lots):
    """Every signal still gets traded (no skipping, no SL change). 'Confirmed'
    trades (breakout chart agrees with direction) use FULL_LOTS. 'Unconfirmed'
    trades use a SMALLER fixed lot size - scales both win and loss dollars
    down for those trades without touching timing or SL width at all."""
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_lots=None
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry,et,lots = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_et = et; pos_lots = lots
            default_sl_usd = pos_entry*REL_SL_PCT*pos_lots
            trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
            if realized_cum >= trig:
                sl_usd = min(max(realized_cum, 0.0), cap)
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/pos_lots
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1)
            bdir = latest_kept_dir_before(tm[j+1])
            confirmed = (bdir == 1) if L else (bdir == -1)
            lots = FULL_LOTS if confirmed else unconfirmed_lots
            SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1],lots)
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*pos_lots
                bal += usd; realized_cum += usd
                trades.append((pos_et, tm[j], usd, hsl))
                in_pos=False
    return trades, bal

print("\nrunning baseline (Ratchet only, all trades at full 0.05 lots)...")
t0, n0 = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00,FULL_LOTS)
l0 = sum(1 for t in t0 if t[3])
print(f"baseline: {len(t0)} trades, {l0} losses, net ${n0:,.2f}")

print("\n=== sweep: reduce lot size for 'unconfirmed' trades only, all trades still taken ===")
print("unconf_lots   trades   losses   net$        vs_baseline")
for lots in [0.05, 0.04, 0.035, 0.03, 0.025, 0.02, 0.015, 0.01, 0.005]:
    t, n = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00,lots)
    l = sum(1 for t_ in t if t_[3])
    print(f"{lots:>10.3f}   {len(t):>6}   {l:>6}   ${n:>10,.2f}   ${n-n0:>+10,.2f}")
