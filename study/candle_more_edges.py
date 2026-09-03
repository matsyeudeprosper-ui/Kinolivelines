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

print("building M1 signals once (continuous)...")
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

print("building M15 and H1 bars...")
m15_o,m15_h,m15_l,m15_c,m15_units,m15_pos = build_bars(900)
h1_o,h1_h,h1_l,h1_c,h1_units,h1_pos = build_bars(3600)

def atr14(o,h,l,c):
    n = len(c)
    atr = np.full(n, np.nan)
    tr = np.empty(n)
    tr[0] = h[0]-l[0]
    for i in range(1,n):
        tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
    for i in range(14,n):
        atr[i] = tr[i-13:i+1].mean()
    return atr

def ema(c, period):
    n=len(c)
    e = np.full(n, np.nan)
    if n < period: return e
    e[period-1] = c[:period].mean()
    k = 2.0/(period+1)
    for i in range(period, n):
        e[i] = c[i]*k + e[i-1]*(1-k)
    return e

print("computing ATR14 and EMA21 for M15 and H1 (causal, no lookahead)...")
m15_atr = atr14(m15_o,m15_h,m15_l,m15_c)
h1_atr = atr14(h1_o,h1_h,h1_l,h1_c)
m15_ema = ema(m15_c, 21)
h1_ema = ema(h1_c, 21)

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
                p2 = bar_lookup(m15_pos, 900, pos_et, 2)
                m15c1 = (1 if m15_c[p1]>m15_o[p1] else (-1 if m15_c[p1]<m15_o[p1] else 0)) if p1 is not None else 0
                m15c2 = (1 if m15_c[p2]>m15_o[p2] else (-1 if m15_c[p2]<m15_o[p2] else 0)) if p2 is not None else 0
                m15_fresh = not (m15c1 != 0 and m15c1 == m15c2)

                m15_atr_trend = None
                if p1 is not None and p2 is not None and not np.isnan(m15_atr[p1]) and not np.isnan(m15_atr[p2]):
                    m15_atr_trend = "rising" if m15_atr[p1] > m15_atr[p2] else "falling"
                ph1 = bar_lookup(h1_pos, 3600, pos_et, 1)
                ph2 = bar_lookup(h1_pos, 3600, pos_et, 2)
                h1_atr_trend = None
                if ph1 is not None and ph2 is not None and not np.isnan(h1_atr[ph1]) and not np.isnan(h1_atr[ph2]):
                    h1_atr_trend = "rising" if h1_atr[ph1] > h1_atr[ph2] else "falling"

                m15_above_ema = None
                if p1 is not None and not np.isnan(m15_ema[p1]):
                    m15_above_ema = m15_c[p1] > m15_ema[p1]
                h1_above_ema = None
                if ph1 is not None and not np.isnan(h1_ema[ph1]):
                    h1_above_ema = h1_c[ph1] > h1_ema[ph1]

                trades.append(dict(side="BUY" if pos_L else "SELL", m1_fresh=m1_fresh, m15_fresh=m15_fresh,
                                    m15_atr_trend=m15_atr_trend, h1_atr_trend=h1_atr_trend,
                                    m15_above_ema=m15_above_ema, h1_above_ema=h1_above_ema,
                                    usd=usd, hsl=hsl))
                in_pos=False
    return trades, bal

print("running deployed rule...")
trades, net = run_ratchet(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00)
print(f"total trades: {len(trades)}, net ${net:,.2f}")

def report(feature_name, key_fn):
    print(f"\n=== {feature_name} ===")
    buckets = defaultdict(lambda: [0,0,0.0])
    for t in trades:
        k = key_fn(t)
        if k is None: continue
        buckets[k][1 if t['hsl'] else 0] += 1
        buckets[k][2] += t['usd']
    for k in sorted(buckets.keys(), key=str):
        w,l,usd = buckets[k]
        tot=w+l
        print(f"  {str(k):<12} n={tot:>5}  losses={l:>3}  loss%={100*l/tot if tot else 0:>6.2f}%  net=${usd:>+10,.2f}  avg/trade=${usd/tot if tot else 0:>+6.2f}")

report("M15 fresh vs continuing", lambda t: t['m15_fresh'])
report("M15 ATR trend (rising/falling)", lambda t: t['m15_atr_trend'])
report("H1 ATR trend (rising/falling)", lambda t: t['h1_atr_trend'])
report("M15 price above/below its own EMA21", lambda t: t['m15_above_ema'])
report("H1 price above/below its own EMA21", lambda t: t['h1_above_ema'])

print("\n=== M1-fresh AND M15-fresh together (double confirmation) ===")
both = [t for t in trades if t['m1_fresh'] and t['m15_fresh']]
neither = [t for t in trades if not t['m1_fresh'] and not t['m15_fresh']]
for label, grp in [("both fresh", both), ("neither fresh", neither)]:
    w = sum(1 for t in grp if not t['hsl']); l = sum(1 for t in grp if t['hsl'])
    usd = sum(t['usd'] for t in grp)
    tot = w+l
    print(f"  {label}: n={tot} losses={l} loss%={100*l/tot if tot else 0:.2f}% net=${usd:+,.2f}")
