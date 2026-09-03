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
sig_bars = sorted(sigs.keys())
print(f"signals: {len(sig_bars)}")

print("simulating EVERY signal independently (no cap, no interaction - pure per-signal outcome)...")
# For each signal: entry at next bar's open (+spread for BUY), fixed TP 100pts,
# SL = 40% of entry price. Walk forward until one side hits. SL takes precedence
# on a same-bar collision, matching every other sim in this project.
outcomes = {}   # sig_bar -> (is_buy, entry_time, hsl)  ; unresolved signals excluded
CHUNK = 20000
resolved = 0
for j in sig_bars:
    if j+1 >= N: continue
    L = (sigs[j] == 1)
    entry = o_f[j+1] + (SPREAD_PTS if L else 0.0)
    tp = entry + TP_PTS if L else entry - TP_PTS
    slp = entry - entry*REL_SL_PCT if L else entry + entry*REL_SL_PCT
    start = j+1
    hit = None
    pos = start
    while pos < N:
        end = min(N, pos + CHUNK)
        hseg = h_f[pos:end]; lseg = l_f[pos:end]
        if L:
            tp_hit = hseg >= tp
            sl_hit = lseg <= slp
        else:
            tp_hit = lseg <= tp
            sl_hit = hseg >= slp
        any_hit = tp_hit | sl_hit
        if any_hit.any():
            k = int(np.argmax(any_hit))
            hit = bool(sl_hit[k])   # SL precedence on same-bar collision
            break
        pos = end
    if hit is None:
        continue   # ran off the end of history unresolved
    outcomes[j] = (L, int(tm_f[j+1]), hit)
    resolved += 1
print(f"resolved: {resolved}  (unresolved excluded: {len(sig_bars)-resolved})")
all_losses = sum(1 for v in outcomes.values() if v[2])
print(f"independent per-signal loss rate, ALL signals: {all_losses}/{resolved} = {100*all_losses/resolved:.3f}%")

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

print("\n=== per-signal loss rates by trend alignment, per timeframe (NO sequencing effects) ===")
print("A real informational edge must show 'against < with' consistently across timeframes.")
for label, secs in [("M1", 60), ("M5", 300), ("M15", 900), ("M30", 1800)]:
    tt, tv = build_trend_events(secs)
    def trend_before(t_epoch):
        pos = np.searchsorted(tt, t_epoch, side='right') - 1
        if pos < 0: return 0
        return int(tv[pos])
    buckets = {"against": [0,0], "with": [0,0], "unknown": [0,0]}  # [n, losses]
    for j,(L, et, hsl) in outcomes.items():
        tr = trend_before(et)
        if tr == 0: b = "unknown"
        elif (tr == -1 and L) or (tr == 1 and not L): b = "against"
        else: b = "with"
        buckets[b][0] += 1
        buckets[b][1] += 1 if hsl else 0
    line = f"{label:<4} "
    for b in ("against","with","unknown"):
        n_, l_ = buckets[b]
        pct = 100*l_/n_ if n_ else 0
        line += f" {b}: {l_:>3}/{n_:>5} ({pct:.3f}%) "
    print(line)

print("\n=== sequence-chaos measurement: how different are the GATED runs' actual trade lists? ===")
def run_gated(tt, tv):
    def trend_before(t_epoch):
        pos = np.searchsorted(tt, t_epoch, side='right') - 1
        if pos < 0: return 0
        return int(tv[pos])
    realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    entries = []
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            entries.append(et)
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trig = 0.30*default_sl_usd; cap = 1.00*default_sl_usd
            if realized_cum >= trig:
                sl_usd = min(max(realized_cum, 0.0), cap)
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1)
            tr = trend_before(tm_f[j+1])
            allow = False if tr == 0 else ((tr == -1) if L else (tr == 1))
            if allow:
                SP=SPREAD_PTS if L else 0.0
                entry = o_f[j+1]+SP if L else o_f[j+1]
                pending=(L,entry,int(tm_f[j+1]))
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h_f[j]>=tpp) if pos_L else (l_f[j]<=tpp)
            hsl = (l_f[j]<=slp) if pos_L else (h_f[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                realized_cum += usd
                in_pos=False
    return set(entries)

tt5, tv5 = build_trend_events(300)
tt15, tv15 = build_trend_events(900)
e5 = run_gated(tt5, tv5)
e15 = run_gated(tt15, tv15)
inter = len(e5 & e15); union = len(e5 | e15)
print(f"M5-gated entries: {len(e5)}   M15-gated entries: {len(e15)}")
print(f"shared entries: {inter}   overlap (Jaccard): {100*inter/union:.1f}%")
print("(low overlap = the gated P&L difference is mostly sequence reshuffling, not the filter's per-trade wisdom)")
