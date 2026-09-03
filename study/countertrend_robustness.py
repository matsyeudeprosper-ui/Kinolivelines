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

def build_trend_events(period_sec):
    """Full pipeline for one source timeframe: bars -> breakout chain ->
    swing highs/lows from completed runs -> causal trend flip events."""
    idx = (tm_f // period_sec).astype(np.int64)
    uniq, first = np.unique(idx, return_index=True)
    nb = len(uniq)
    bounds = list(first) + [N]
    bo = np.empty(nb); bh = np.empty(nb); bl = np.empty(nb); bc = np.empty(nb)
    for k in range(nb):
        s,e = bounds[k], bounds[k+1]
        bo[k]=o_f[s]; bh[k]=h_f[s:e].max(); bl[k]=l_f[s:e].min(); bc[k]=c_f[e-1]
    close_time = np.array([int(tm_f[bounds[k+1]-1]) + 60 for k in range(nb)])

    kept_idx = [0]; kept_dir = [0]
    ref_hi, ref_lo = bh[0], bl[0]
    for i in range(1, nb):
        if bc[i] > ref_hi:
            kept_idx.append(i); kept_dir.append(1)
            ref_hi, ref_lo = bh[i], bl[i]
        elif bc[i] < ref_lo:
            kept_idx.append(i); kept_dir.append(-1)
            ref_hi, ref_lo = bh[i], bl[i]

    trend_events = []
    cur_run_dir = kept_dir[0]
    run_hi = bh[kept_idx[0]]; run_lo = bl[kept_idx[0]]
    swing_high = None; swing_low = None
    trend = 0
    for n in range(1, len(kept_idx)):
        i = kept_idx[n]; d = kept_dir[n]
        if d != cur_run_dir:
            if cur_run_dir == 1: swing_high = run_hi
            elif cur_run_dir == -1: swing_low = run_lo
            cur_run_dir = d
            run_hi = bh[i]; run_lo = bl[i]
        else:
            if d == 1: run_hi = bh[i]
            else: run_lo = bl[i]
        close = bc[i]
        changed = False
        if swing_high is not None and close > swing_high and trend != 1:
            trend = 1; changed = True
        if swing_low is not None and close < swing_low and trend != -1:
            trend = -1; changed = True
        if changed:
            trend_events.append((close_time[i], trend))
    tt = np.array([e[0] for e in trend_events])
    tv = np.array([e[1] for e in trend_events])
    return tt, tv, nb, len(kept_idx)

def run_full(o,h,l,c,tm,N,sigs,trig_f,cap_f,tt,tv,allow_unknown):
    def trend_before(t_epoch):
        pos = np.searchsorted(tt, t_epoch, side='right') - 1
        if pos < 0: return 0
        return int(tv[pos])
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_et = et
            if trig_f is None:
                pos_sl = pos_entry*REL_SL_PCT
            else:
                default_sl_usd = pos_entry*REL_SL_PCT*LOTS
                trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
                if realized_cum >= trig:
                    sl_usd = min(max(realized_cum, 0.0), cap)
                else:
                    sl_usd = default_sl_usd
                pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1)
            tr = trend_before(tm[j+1])
            if tr == 0:
                allow = allow_unknown
            else:
                allow = (tr == -1) if L else (tr == 1)
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

eras = [
    ("2020-22", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-24", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-26", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

def era_line(trades):
    parts = []
    for label,d0,d1 in eras:
        grp = [t for t in trades if d0<=t[0]<d1]
        gn = sum(t[2] for t in grp); gl = sum(1 for t in grp if t[3])
        parts.append(f"{label}: {gn:+,.0f}({gl}L)")
    return "  ".join(parts)

print("\n=== robustness: source timeframe for the swing/trend structure ===")
for label, secs in [("M1", 60), ("M5 (original)", 300), ("M15", 900), ("M30", 1800)]:
    tt, tv, nb, nkept = build_trend_events(secs)
    t, n = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00,tt,tv,False)
    l = sum(1 for x in t if x[3])
    print(f"{label:<15} trades={len(t):>5} losses={l:>3} net=${n:>10,.2f}   [{era_line(t)}]")

print("\n=== robustness: allow trades when trend is unknown (vs block, the original) ===")
tt5, tv5, _, _ = build_trend_events(300)
t, n = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00,tt5,tv5,True)
l = sum(1 for x in t if x[3])
print(f"allow-unknown   trades={len(t):>5} losses={l:>3} net=${n:>10,.2f}   [{era_line(t)}]")

print("\n=== robustness: gate WITHOUT the ratchet (does the edge exist on its own?) ===")
t, n = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,None,None,tt5,tv5,False)
l = sum(1 for x in t if x[3])
print(f"no-ratchet      trades={len(t):>5} losses={l:>3} net=${n:>10,.2f}   [{era_line(t)}]")
