import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

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

print("building M1 signals once (continuous)...")
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

print("building M5 bars (source for the breakout chain -> swing points)...")
m5_idx = (tm_f // 300).astype(np.int64)
m5_uniq, m5_first = np.unique(m5_idx, return_index=True)
n5 = len(m5_uniq)
m5_bounds = list(m5_first) + [N]
m5_o = np.empty(n5); m5_h = np.empty(n5); m5_l = np.empty(n5); m5_c = np.empty(n5)
for k in range(n5):
    s,e = m5_bounds[k], m5_bounds[k+1]
    m5_o[k]=o_f[s]; m5_h[k]=h_f[s:e].max(); m5_l[k]=l_f[s:e].min(); m5_c[k]=c_f[e-1]
m5_close_time = np.array([int(tm_f[m5_bounds[k+1]-1]) + 60 for k in range(n5)])

print("building the breakout chain (kept bars)...")
kept_idx = [0]; kept_dir = [0]
ref_hi, ref_lo = m5_h[0], m5_l[0]
for i in range(1, n5):
    if m5_c[i] > ref_hi:
        kept_idx.append(i); kept_dir.append(1)
        ref_hi, ref_lo = m5_h[i], m5_l[i]
    elif m5_c[i] < ref_lo:
        kept_idx.append(i); kept_dir.append(-1)
        ref_hi, ref_lo = m5_h[i], m5_l[i]
print(f"M5 bars: {n5}, kept: {len(kept_idx)} ({100*len(kept_idx)/n5:.1f}%)")

print("deriving genuine swing highs/lows from the kept-bar runs, and a causal trend state...")
# swing points = the LAST bar of each same-direction run in the kept-bar sequence
# (each new same-direction kept bar extends the run's extreme further, so the
# last bar in a run holds the run's true high/low). trend flips to UP the
# moment a bar's CLOSE breaks above the last COMPLETED run's high (a genuine
# prior swing high, not just the immediately-preceding kept bar's own level).
# Mirror for DOWN via swing lows. This directly matches: "when a previous high
# is broken by a candle that closes completely above/below it, that confirms
# the start or continuation of a trend."
trend_events = []  # (m5_close_time, trend) - trend: 1=up, -1=down, 0=unknown
cur_run_dir = kept_dir[0]
cur_run_extreme_hi = m5_h[kept_idx[0]]
cur_run_extreme_lo = m5_l[kept_idx[0]]
last_swing_high = None
last_swing_low = None
trend = 0
for n in range(1, len(kept_idx)):
    i = kept_idx[n]; d = kept_dir[n]
    if d != cur_run_dir:
        # the previous run just ended - finalize its extreme as a confirmed swing
        if cur_run_dir == 1:
            last_swing_high = cur_run_extreme_hi
        elif cur_run_dir == -1:
            last_swing_low = cur_run_extreme_lo
        cur_run_dir = d
        cur_run_extreme_hi = m5_h[i]
        cur_run_extreme_lo = m5_l[i]
    else:
        if d == 1: cur_run_extreme_hi = m5_h[i]
        else: cur_run_extreme_lo = m5_l[i]

    close = m5_c[i]
    changed = False
    if last_swing_high is not None and close > last_swing_high and trend != 1:
        trend = 1; changed = True
    if last_swing_low is not None and close < last_swing_low and trend != -1:
        trend = -1; changed = True
    if changed:
        trend_events.append((m5_close_time[i], trend))

trend_times = np.array([e[0] for e in trend_events])
trend_vals = np.array([e[1] for e in trend_events])
print(f"trend flips recorded: {len(trend_events)}")

def trend_before(t_epoch):
    pos = np.searchsorted(trend_times, t_epoch, side='right') - 1
    if pos < 0:
        return 0
    return int(trend_vals[pos])

def run_full(o,h,l,c,tm,N,sigs,trig_f,cap_f,use_trend_gate):
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_et = et
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
            if realized_cum >= trig:
                sl_usd = min(max(realized_cum, 0.0), cap)
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1)
            allow = True
            if use_trend_gate:
                tr = trend_before(tm[j+1])
                allow = (tr == 1) if L else (tr == -1)
            if allow:
                SP=SPREAD_PTS if L else 0.0
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
                trades.append((pos_et, tm[j], usd, hsl))
                in_pos=False
    return trades, bal

def calendar_stats(trades, label):
    total = sum(t[2] for t in trades)
    wins = sum(1 for t in trades if not t[3]); losses = sum(1 for t in trades if t[3])
    peak = 0.0; cum = 0.0; max_eq_dd = 0.0
    for et,xt,pnl,hsl in trades:
        cum += pnl
        if cum > peak: peak = cum
        draw = peak - cum
        if draw > max_eq_dd: max_eq_dd = draw
    print(f"\n=== {label} ===")
    print(f"trades: {len(trades)}  wins: {wins}  losses: {losses}  win rate: {100*wins/len(trades) if trades else 0:.2f}%")
    print(f"net: ${total:,.2f}   max account drawdown: ${max_eq_dd:,.2f}")
    return trades

print("\nrunning RATCHET ONLY (no gate - current live baseline)...")
t0, n0 = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00,False)
calendar_stats(t0, "RATCHET ONLY, no swing-trend gate (current live)")

print("running RATCHET + SWING TREND GATE (real gating)...")
t1, n1 = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00,True)
gated = calendar_stats(t1, "RATCHET + SWING TREND GATE (REAL GATE)")

eras = [
    ("2020-08-16 -> 2022-08-16", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-08-16 -> 2024-08-16", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-08-16 -> 2026-08-18", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]
print("\n=== gated version, era by era ===")
tot=0.0
for label,d0,d1 in eras:
    grp = [t for t in gated if d0<=t[0]<d1]
    gn = sum(t[2] for t in grp); gl = sum(1 for t in grp if t[3])
    tot += gn
    print(f"{label}: n={len(grp)} losses={gl} net=${gn:+,.2f}")
print(f"TOTAL: ${tot:+,.2f}")
