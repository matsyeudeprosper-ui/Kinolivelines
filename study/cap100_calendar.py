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

sigs = build_bricks_signals(o_f,h_f,l_f,c_f,N)

def run_full(o,h,l,c,tm,N,sigs,trig_f,cap_f):
    bal=0.0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    trade_dd = 0.0
    trades = []
    for j in range(N):
        if pending is not None:
            L,entry = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            trade_dd = 0.0
            if trig_f is None:
                pos_sl = pos_entry*REL_SL_PCT
            else:
                default_sl_usd = pos_entry*REL_SL_PCT*LOTS
                trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
                if realized_cum >= trig:
                    sl_usd = min(max(realized_cum,0.0), cap)
                else:
                    sl_usd = default_sl_usd
                pos_sl = sl_usd/LOTS
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry)
        if in_pos:
            dd_now = (pos_entry - l[j])*LOTS if pos_L else (h[j] - pos_entry)*LOTS
            if dd_now > trade_dd: trade_dd = dd_now
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd
                if trig_f is not None: realized_cum += usd
                trades.append((tm[j], usd, trade_dd))
                in_pos=False
    return trades, bal

def calendar_stats(trades, label):
    daily = defaultdict(float); weekly = defaultdict(float); monthly = defaultdict(float)
    max_trade_dd = 0.0
    for epoch, pnl, dd in trades:
        dt = datetime.utcfromtimestamp(epoch)
        daily[dt.date()] += pnl
        wk = dt.date() - timedelta(days=dt.weekday())
        weekly[wk] += pnl
        monthly[(dt.year, dt.month)] += pnl
        if dd > max_trade_dd: max_trade_dd = dd
    peak = 0.0; cum = 0.0; max_eq_dd = 0.0
    for epoch, pnl, dd in trades:
        cum += pnl
        if cum > peak: peak = cum
        draw = peak - cum
        if draw > max_eq_dd: max_eq_dd = draw
    dvals = list(daily.values()); wvals = list(weekly.values()); mvals = list(monthly.values())
    n_days = (max(daily.keys()) - min(daily.keys())).days + 1 if daily else 1
    total = sum(pnl for _,pnl,_ in trades)
    print(f"\n=== {label} ===")
    print(f"total net: ${total:,.2f}  trades: {len(trades)}")
    print(f"avg profit/day: ${total/n_days:,.4f}   avg/week: ${total/(n_days/7):,.2f}   avg/month: ${total/(n_days/30.44):,.2f}")
    print(f"best day: ${max(dvals):,.2f}   worst day: ${min(dvals):,.2f}")
    print(f"best week: ${max(wvals):,.2f}   worst week: ${min(wvals):,.2f}")
    print(f"best month: ${max(mvals):,.2f}   worst month: ${min(mvals):,.2f}")
    print(f"max single-trade intra-trade drawdown: ${max_trade_dd:,.2f}")
    print(f"max account equity drawdown (peak-to-trough): ${max_eq_dd:,.2f}")

trades_base, net_base = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,None,None)
calendar_stats(trades_base, "CURRENT LIVE BOT (relative 40% SL, no ratchet) - continuous, correct")

trades_rat, net_rat = run_full(o_f,h_f,l_f,c_f,tm_f,N,sigs,0.30,1.00)
calendar_stats(trades_rat, "SINGLE-CAP RATCHET trigger=30%, cap=100% - continuous, correct, on the confirmed 26-38% plateau")
