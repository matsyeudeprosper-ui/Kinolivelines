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

def build_trend_events(period_sec):
    idx = (tm_f // period_sec).astype(np.int64)
    uniq, first = np.unique(idx, return_index=True)
    nb = len(uniq)
    bounds = list(first) + [N]
    bh = np.empty(nb); bl = np.empty(nb); bc = np.empty(nb)
    for k in range(nb):
        s,e = bounds[k], bounds[k+1]
        bh[k]=h_f[s:e].max(); bl[k]=l_f[s:e].min(); bc[k]=c_f[e-1]
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
    return tt, tv

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

def run_sizemod(tt, tv, against_lots, use_ratchet):
    """Every signal traded, sequence-preserving size modulation: WITH-trend
    trades at FULL_LOTS, AGAINST-trend (and unknown) at against_lots.
    use_ratchet=False keeps the SL a pure fixed 40%-of-entry for every trade,
    which makes the trade SEQUENCE byte-identical across all against_lots
    values - only the dollars scale. use_ratchet=True layers the live
    ratchet on top (couples sizes into SL widths, sequence may shift)."""
    def trend_before(t_epoch):
        pos = np.searchsorted(tt, t_epoch, side='right') - 1
        if pos < 0: return 0
        return int(tv[pos])
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_lots=None
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry,et,lots = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_et = et; pos_lots = lots
            if not use_ratchet:
                pos_sl = pos_entry*REL_SL_PCT
            else:
                default_sl_usd = pos_entry*REL_SL_PCT*pos_lots
                trig = 0.30*default_sl_usd; cap = 1.00*default_sl_usd
                if realized_cum >= trig:
                    sl_usd = min(max(realized_cum, 0.0), cap)
                else:
                    sl_usd = default_sl_usd
                pos_sl = sl_usd/pos_lots
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1)
            tr = trend_before(tm_f[j+1])
            with_trend = (tr == 1 and L) or (tr == -1 and not L)
            lots = FULL_LOTS if with_trend else against_lots
            SP=SPREAD_PTS if L else 0.0
            entry = o_f[j+1]+SP if L else o_f[j+1]
            pending=(L,entry,int(tm_f[j+1]),lots)
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h_f[j]>=tpp) if pos_L else (l_f[j]<=tpp)
            hsl = (l_f[j]<=slp) if pos_L else (h_f[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*pos_lots
                bal += usd; realized_cum += usd
                trades.append((pos_et, tm_f[j], usd, hsl))
                in_pos=False
    return trades, bal

for tf_label, secs in [("M15", 900), ("M30", 1800)]:
    tt, tv = build_trend_events(secs)
    print(f"\n===== trend source: {tf_label} =====")
    print("--- CLEAN version (no ratchet, sequence identical across rows - pure edge harvest) ---")
    print("against_lots   trades   losses   net$        vs_row1     era breakdown")
    base_n = None
    for lots in [0.05, 0.04, 0.03, 0.02, 0.01, 0.005]:
        t, n = run_sizemod(tt, tv, lots, False)
        l = sum(1 for x in t if x[3])
        if base_n is None: base_n = n
        print(f"{lots:>10.3f}   {len(t):>6}   {l:>6}   ${n:>10,.2f}   ${n-base_n:>+10,.2f}   [{era_line(t)}]")
    print("--- REALISTIC version (live ratchet on top) ---")
    base_n = None
    for lots in [0.05, 0.04, 0.03, 0.02, 0.01, 0.005]:
        t, n = run_sizemod(tt, tv, lots, True)
        l = sum(1 for x in t if x[3])
        if base_n is None: base_n = n
        print(f"{lots:>10.3f}   {len(t):>6}   {l:>6}   ${n:>10,.2f}   ${n-base_n:>+10,.2f}   [{era_line(t)}]")
