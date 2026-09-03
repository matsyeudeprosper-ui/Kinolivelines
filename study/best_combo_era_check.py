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

print("building signals once (continuous)...")
sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

def build_bars(period_sec):
    idx = (tm_f // period_sec).astype(np.int64)
    uniq, first_pos = np.unique(idx, return_index=True)
    n = len(uniq)
    bounds = list(first_pos) + [N]
    bo=np.empty(n); bh=np.empty(n); bl=np.empty(n); bc=np.empty(n)
    for k in range(n):
        s,e = bounds[k], bounds[k+1]
        bo[k]=o_f[s]; bh[k]=h_f[s:e].max(); bl[k]=l_f[s:e].min(); bc[k]=c_f[e-1]
    pos = {int(u): i for i,u in enumerate(uniq)}
    return bo,bh,bl,bc,uniq,pos

print("building M15 bars and EMA21 (Trend Lane)...")
m15_o,m15_h,m15_l,m15_c,m15_units,m15_pos = build_bars(900)

def ema(c, period):
    n=len(c)
    e = np.full(n, np.nan)
    if n < period: return e
    e[period-1] = c[:period].mean()
    k = 2.0/(period+1)
    for i in range(period, n):
        e[i] = c[i]*k + e[i-1]*(1-k)
    return e

m15_ema = ema(m15_c, 21)

def m1_color_at(idx):
    return 1 if c_f[idx] > o_f[idx] else (-1 if c_f[idx] < o_f[idx] else 0)

def bar_lookup(units_pos, period_sec, entry_epoch, back):
    cur_unit = int(entry_epoch // period_sec)
    want = cur_unit - back
    return units_pos.get(want, None)

def run_ratchet(o,h,l,c,tm,N,sigs,trig_f,cap_f):
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    pos_sig_bar=None
    trades = []
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
                m1_fresh = not (m1c1 != 0 and m1c1 == m1c2)
                p1 = bar_lookup(m15_pos, 900, pos_et, 1)
                trend_lane = None
                if p1 is not None and not np.isnan(m15_ema[p1]):
                    trend_lane = bool(m15_c[p1] <= m15_ema[p1])
                best_combo = (trend_lane is True) and m1_fresh
                trades.append((pos_et, best_combo, usd, hsl))
                in_pos=False
    return trades, bal

print("running deployed rule...")
trades, net = run_ratchet(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00)
print(f"total trades: {len(trades)}, net ${net:,.2f}")

eras = [
    ("2020-08-16 -> 2022-08-16", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-08-16 -> 2024-08-16", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-08-16 -> 2026-08-18", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]

print("\n=== 'TrendLane + M1-fresh' best combo, sliced by era (one continuous run, sliced post-hoc) ===")
tot_best = 0.0; tot_rest = 0.0
for label, d0, d1 in eras:
    best = [t for t in trades if d0<=t[0]<d1 and t[1]]
    rest = [t for t in trades if d0<=t[0]<d1 and not t[1]]
    bn = sum(t[2] for t in best); bl = sum(1 for t in best if t[3])
    rn = sum(t[2] for t in rest); rl = sum(1 for t in rest if t[3])
    tot_best += bn; tot_rest += rn
    print(f"{label}: BEST n={len(best):>4} loss={bl:>2} net=${bn:>+9,.2f}   REST n={len(rest):>4} loss={rl:>2} net=${rn:>+9,.2f}")
print(f"\nTOTAL best combo: ${tot_best:+,.2f}   TOTAL rest: ${tot_rest:+,.2f}")
