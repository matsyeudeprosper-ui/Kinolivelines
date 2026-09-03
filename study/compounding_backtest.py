import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import defaultdict

BRICK, REVERSAL = 50.0, 2
PT = 0.01
TP_PTS = 100.0
SPREAD_PTS = 10.0
REL_SL_PCT = 0.40
LOT_STEP = 0.01
LOT_MIN = 0.01
LOT_MAX = 200.0

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

def round_lots(x):
    steps = int(x / LOT_STEP)  # round DOWN (conservative)
    lots = steps * LOT_STEP
    return max(LOT_MIN, min(LOT_MAX, round(lots, 2)))

def run_compounding(o,h,l,c,tm,N,sigs,start_balance,risk_frac,trig_f,cap_f,use_compounding):
    """Combines the deployed ratchet (trig_f/cap_f, trigger=30%/cap=100% live)
    with a position size that's either FIXED (use_compounding=False, LOTS=0.05
    always, matching today's live bot) or COMPOUNDING (recalculated fresh at
    each new trade from current balance: lots = risk_frac*balance/(price*REL_SL_PCT),
    rounded down to the broker's 0.01 step, floored at the 0.01 minimum)."""
    balance = start_balance
    realized_cum = 0.0
    min_balance = start_balance
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_lots=None
    trades = []  # (exit_time, usd, hsl, lots_used, balance_after)
    for j in range(N):
        if pending is not None:
            L,entry = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            if use_compounding:
                lots = round_lots(risk_frac * balance / (pos_entry * REL_SL_PCT))
            else:
                lots = 0.05
            pos_lots = lots
            default_sl_usd = pos_entry*REL_SL_PCT*lots
            trig = trig_f*default_sl_usd; cap = cap_f*default_sl_usd
            if realized_cum >= trig:
                sl_usd = min(max(realized_cum, 0.0), cap)
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/lots
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry)
        if in_pos:
            tpp = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            slp = pos_entry-pos_sl if pos_L else pos_entry+pos_sl
            htp = (h[j]>=tpp) if pos_L else (l[j]<=tpp)
            hsl = (l[j]<=slp) if pos_L else (h[j]>=slp)
            if htp or hsl:
                usd = (-pos_sl if hsl else TP_PTS)*pos_lots
                balance += usd
                realized_cum += usd
                if balance < min_balance: min_balance = balance
                trades.append((tm[j], usd, hsl, pos_lots, balance))
                in_pos=False
    return trades, balance, min_balance

def summarize(trades, start_balance, final_balance, min_balance, label):
    total = final_balance - start_balance
    losses = sum(1 for t in trades if t[2])
    span_days = (datetime.utcfromtimestamp(times[-1]) - datetime.utcfromtimestamp(times[0])).days
    print(f"\n=== {label} ===")
    print(f"  start ${start_balance:,.2f} -> end ${final_balance:,.2f}  (net ${total:+,.2f})")
    print(f"  trades: {len(trades)}  losses: {losses}")
    print(f"  lowest balance ever reached: ${min_balance:,.2f}  ({'BLOWN UP / went very low' if min_balance < start_balance*0.15 else 'survived comfortably' if min_balance > start_balance*0.5 else 'got uncomfortably low at least once'})")
    print(f"  avg profit/month: ${total/(span_days/30.44):,.2f}   avg profit/year: ${total/(span_days/365.25):,.2f}")
    print(f"  final lot size in use: {trades[-1][3] if trades else 'n/a'}")
    # yearly breakdown
    by_year = defaultdict(float)
    for et, usd, hsl, lots, bal in trades:
        by_year[datetime.utcfromtimestamp(et).year] += usd
    print(f"  yearly P&L: " + ", ".join(f"{y}: ${v:+,.0f}" for y,v in sorted(by_year.items())))

RISK_FRAC = 0.35
for start_balance in [2500, 4000]:
    trades_fixed, bal_fixed, min_fixed = run_compounding(o_f,h_f,l_f,c_f,tm_f,N,sigs,start_balance,RISK_FRAC,0.30,1.00,False)
    summarize(trades_fixed, start_balance, bal_fixed, min_fixed, f"FIXED 0.05 lots, start ${start_balance}")

    trades_comp, bal_comp, min_comp = run_compounding(o_f,h_f,l_f,c_f,tm_f,N,sigs,start_balance,RISK_FRAC,0.30,1.00,True)
    summarize(trades_comp, start_balance, bal_comp, min_comp, f"COMPOUNDING (risk_frac={RISK_FRAC}), start ${start_balance}")
