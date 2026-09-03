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
N_full = len(times)
print(f"loaded {N_full} M1 bars, {times[0]} -> {times[-1]}")

# --- build H1 bars for a cheap rolling volatility regime signal ---
hour_idx = (tm_f // 3600).astype(np.int64)
uniq_hours, first_pos = np.unique(hour_idx, return_index=True)
n_hours = len(uniq_hours)
bounds = list(first_pos) + [N_full]
h1_high = np.empty(n_hours); h1_low = np.empty(n_hours); h1_close = np.empty(n_hours)
for k in range(n_hours):
    s,e = bounds[k], bounds[k+1]
    h1_high[k] = h_f[s:e].max()
    h1_low[k] = l_f[s:e].min()
    h1_close[k] = c_f[e-1]

WIN = 24  # trailing 24h range as %-of-price volatility proxy
roll_range_pct = np.full(n_hours, np.nan)
for k in range(WIN, n_hours):
    hi = h1_high[k-WIN:k].max()
    lo = h1_low[k-WIN:k].min()
    roll_range_pct[k] = (hi-lo)/h1_close[k-1]

valid = roll_range_pct[~np.isnan(roll_range_pct)]
print("vol proxy (24h range as fraction of price) percentiles: p50=%.4f p60=%.4f p75=%.4f p90=%.4f p95=%.4f" % (
    np.percentile(valid,50), np.percentile(valid,60), np.percentile(valid,75),
    np.percentile(valid,90), np.percentile(valid,95)))

# forward-map each M1 bar to its hour's vol value (no lookahead: hour k's value uses the 24h BEFORE hour k)
hour_to_pos = {int(h): i for i, h in enumerate(uniq_hours)}
vol_m1 = np.array([roll_range_pct[hour_to_pos[int(h)]] for h in hour_idx])

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

def run_baseline(o,h,l,c,tm,N,sigs):
    bal=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            pos_sl = pos_entry*REL_SL_PCT
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
                bal += usd
                if hsl: losses+=1
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal)

def run_volregime(o,h,l,c,tm,N,sigs,vol,vol_thresh,trigA,capA,trigB,capB):
    """Regime-switched ratchet: use loose (trigA,capA) settings normally, but
    switch to tight (trigB,capB) settings for any trade ENTERED while the
    market's own 24h volatility (not the account's P&L) is elevated above
    vol_thresh. This is a market signal, not an account-state signal."""
    bal=0.0; wins=losses=0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    for j in range(N):
        if pending is not None:
            L,entry,et,ei = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            v = vol[ei]
            if not np.isnan(v) and v >= vol_thresh:
                trig_f, cap_f = trigB, capB
            else:
                trig_f, cap_f = trigA, capA
            trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
            if realized_cum >= trig:
                sl_usd = min(max(realized_cum,0.0), cap)
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1],j+1)
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd; realized_cum += usd
                if hsl: losses+=1
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal)

segs = [
    ("2020-08-16 -> 2022-08-16", datetime(2020,8,16), datetime(2022,8,16)),
    ("2022-08-16 -> 2024-08-16", datetime(2022,8,16), datetime(2024,8,16)),
    ("2024-08-16 -> 2026-08-18", datetime(2024,8,16), datetime(2026,8,18)),
]
seg_data = []
for label, d0, d1 in segs:
    mask = (tm_f >= d0.timestamp()) & (tm_f < d1.timestamp())
    ot,ht,lt,ct,tmt,volt = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask],vol_m1[mask]
    Nt = len(ct)
    sigt = build_bricks_signals(ot,ht,lt,ct,Nt)
    zb = run_baseline(ot,ht,lt,ct,tmt,Nt,sigt)
    seg_data.append((label,ot,ht,lt,ct,tmt,volt,Nt,sigt,zb))
    print(f"{label}: baseline ${zb['net']:,.2f}  losses={zb['losses']}")

p60,p75,p90 = np.percentile(valid,60), np.percentile(valid,75), np.percentile(valid,90)
print(f"\n=== vol-regime ratchet: loose=trig20%/cap100% normally, tight=trig35%/cap90% when 24h vol >= threshold ===")
print("thresh(pctile)  seg1      seg2      seg3      SUM")
for label_p, thresh in [("p50",np.percentile(valid,50)),("p60",p60),("p70",np.percentile(valid,70)),
                         ("p75",p75),("p80",np.percentile(valid,80)),("p90",p90),("p95",np.percentile(valid,95))]:
    diffs = []
    for label,ot,ht,lt,ct,tmt,volt,Nt,sigt,zb in seg_data:
        z = run_volregime(ot,ht,lt,ct,tmt,Nt,sigt,volt,thresh, 0.20,1.00, 0.35,0.90)
        diffs.append(z['net']-zb['net'])
    print(f"{label_p:>6s} ({thresh:.4f})  {diffs[0]:>+8.0f}  {diffs[1]:>+8.0f}  {diffs[2]:>+8.0f}  {sum(diffs):>+9.0f}")
