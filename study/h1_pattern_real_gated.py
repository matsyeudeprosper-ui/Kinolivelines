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

print("building H1 bars...")
h1_o,h1_h,h1_l,h1_c,h1_units,h1_pos = build_bars(3600)
h1_color = np.where(h1_c > h1_o, 1, np.where(h1_c < h1_o, -1, 0))

def bar_lookup(units_pos, period_sec, entry_epoch, back):
    cur_unit = int(entry_epoch // period_sec)
    want = cur_unit - back
    return units_pos.get(want, None)

def run_full(o,h,l,c,tm,N,sigs,trig_f,cap_f,use_h1_gate):
    """use_h1_gate=True: SELL signals only open if the last 2 CLOSED H1
    candles were both green (bullish) - the pattern found: 0 losses in 428
    post-hoc-bucketed trades. BUY signals are never gated (no comparable
    H1 pattern was found for BUY). REAL gating - a blocked SELL is truly
    skipped, the bot stays free for the next signal."""
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    trade_dd = 0.0
    trades = []  # (entry_time, exit_time, pnl, hsl, dd)
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_et = et
            trade_dd = 0.0
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
            allow = True
            if use_h1_gate and not L:  # SELL signal - check the H1 gate
                p1 = bar_lookup(h1_pos, 3600, tm[j+1], 1)
                p2 = bar_lookup(h1_pos, 3600, tm[j+1], 2)
                c1 = h1_color[p1] if p1 is not None else 0
                c2 = h1_color[p2] if p2 is not None else 0
                allow = (c1 == 1 and c2 == 1)
            if allow:
                SP=SPREAD_PTS if L else 0.0
                entry = o[j+1]+SP if L else o[j+1]
                pending=(L,entry,tm[j+1])
        if in_pos:
            dd_now = (pos_entry - l[j])*LOTS if pos_L else (h[j] - pos_entry)*LOTS
            if dd_now > trade_dd: trade_dd = dd_now
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd; realized_cum += usd
                trades.append((pos_et, tm[j], usd, hsl, trade_dd))
                in_pos=False
    return trades, bal

def calendar_stats(trades, label):
    daily = defaultdict(float); weekly = defaultdict(float); monthly = defaultdict(float)
    max_trade_dd = 0.0
    for et, xt, pnl, hsl, dd in trades:
        dt = datetime.utcfromtimestamp(xt)
        daily[dt.date()] += pnl
        wk = dt.date() - timedelta(days=dt.weekday())
        weekly[wk] += pnl
        monthly[(dt.year, dt.month)] += pnl
        if dd > max_trade_dd: max_trade_dd = dd
    peak = 0.0; cum = 0.0; max_eq_dd = 0.0
    for et, xt, pnl, hsl, dd in trades:
        cum += pnl
        if cum > peak: peak = cum
        draw = peak - cum
        if draw > max_eq_dd: max_eq_dd = draw
    dvals = list(daily.values()); wvals = list(weekly.values()); mvals = list(monthly.values())
    n_days = (max(daily.keys()) - min(daily.keys())).days + 1 if daily else 1
    total = sum(pnl for _,_,pnl,_,_ in trades)
    wins = sum(1 for t in trades if not t[3]); losses = sum(1 for t in trades if t[3])
    print(f"\n=== {label} ===")
    print(f"total net: ${total:,.2f}  trades: {len(trades)}  wins: {wins}  losses: {losses}  win rate: {100*wins/len(trades):.2f}%")
    print(f"avg profit/day: ${total/n_days:,.4f}   avg/week: ${total/(n_days/7):,.2f}   avg/month: ${total/(n_days/30.44):,.2f}   avg/year: ${total/(n_days/365.25):,.2f}")
    print(f"best day: ${max(dvals):,.2f}   worst day: ${min(dvals):,.2f}")
    print(f"best week: ${max(wvals):,.2f}   worst week: ${min(wvals):,.2f}")
    print(f"best month: ${max(mvals):,.2f}   worst month: ${min(mvals):,.2f}")
    print(f"max single-trade intra-trade drawdown: ${max_trade_dd:,.2f}")
    print(f"max account equity drawdown (peak-to-trough): ${max_eq_dd:,.2f}")
    return trades

print("running RATCHET ONLY (no gate - current live baseline)...")
t1, n1 = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00,False)
calendar_stats(t1, "RATCHET ONLY, no H1 gate (current live)")

print("running RATCHET + H1 GATE on SELL only (real gating this time)...")
t2, n2 = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00,True)
gated_trades = calendar_stats(t2, "RATCHET + H1-2-green-gate on SELL (REAL GATE)")

eras = [
    ("2020-08-16 -> 2022-08-16", datetime(2020,8,16).timestamp(), datetime(2022,8,16).timestamp()),
    ("2022-08-16 -> 2024-08-16", datetime(2022,8,16).timestamp(), datetime(2024,8,16).timestamp()),
    ("2024-08-16 -> 2026-08-18", datetime(2024,8,16).timestamp(), datetime(2026,8,18).timestamp()),
]
print("\n=== H1-gated version, era by era ===")
tot=0.0
for label,d0,d1 in eras:
    grp = [t for t in gated_trades if d0<=t[0]<d1]
    gn = sum(t[2] for t in grp); gl = sum(1 for t in grp if t[3])
    tot += gn
    print(f"{label}: n={len(grp)} losses={gl} net=${gn:+,.2f}")
print(f"TOTAL: ${tot:+,.2f}")
