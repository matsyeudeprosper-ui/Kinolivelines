import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

BRICK, REVERSAL = 50.0, 2
PT = 0.01
TP_PTS = 100.0
SL_PTS_FIXED = 44439.0
SPREAD_PTS = 10.0
LOTS = 0.05; SCALE = LOTS/0.01

files = ['coinbase_m1_2yr_part0.json','coinbase_m1_2yr_part1.json','coinbase_m1_2yr_part2.json','coinbase_m1_extra_year.json','coinbase_m1_pilot.json']
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
N = len(times)
o = np.array([rows[t][0] for t in times]); h = np.array([rows[t][1] for t in times])
l = np.array([rows[t][2] for t in times]); c = np.array([rows[t][3] for t in times])
tm = np.array(times)
span_days = (tm[-1]-tm[0])/86400
print(f"M1 bars: {N}  {datetime.utcfromtimestamp(tm[0])} -> {datetime.utcfromtimestamp(tm[-1])}  ({span_days:.1f} days)")
print(f"price range across dataset: ${c.min():,.0f} -> ${c.max():,.0f}\n")

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

sigs = build_bricks_signals(o,h,l,c,N)
print(f"total signals: {len(sigs)}\n")

def run(o,h,l,c,tm,N,sigs,sl_mode,sl_param):
    """sl_mode: 'fixed' (sl_param = pts) or 'relative' (sl_param = fraction of entry price)"""
    bal_usd=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl_pts=None
    loss_events=[]
    for j in range(N):
        if pending is not None:
            L,entry = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_sl_pts = sl_param if sl_mode=='fixed' else entry*sl_param
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=SPREAD_PTS if L else 0.0
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry)
        if in_pos:
            tp_price = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            sl_price = pos_entry-pos_sl_pts if pos_L else pos_entry+pos_sl_pts
            hit_tp = (h[j]>=tp_price) if pos_L else (l[j]<=tp_price)
            hit_sl = (l[j]<=sl_price) if pos_L else (h[j]>=sl_price)
            if hit_tp or hit_sl:
                usd = (-pos_sl_pts if hit_sl else TP_PTS)*PT*SCALE
                bal_usd += usd
                if hit_sl:
                    losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(tm[j]), round(usd,2), round(pos_sl_pts,0)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal_usd, loss_events=loss_events)

print("=== FIXED nominal SL (today's live shape, 44439pts always) ===")
zF = run(o,h,l,c,tm,N,sigs,'fixed',SL_PTS_FIXED)
print(f"  trades {zF['trades']}  win% {100*zF['wins']/zF['trades']:.2f}  losses {zF['losses']}  net ${zF['net']:.2f}   ${zF['net']/(span_days/30.44):.2f}/mo")
for L,t,usd,slp in zF['loss_events']:
    print(f"    LOSS: {'BUY' if L else 'SELL'} {t}  ${usd}  (sl was {slp:.0f}pts)")

# what relative fraction does 44439pts correspond to, at a few different BTC price levels seen in the data?
for px in [28000, 63000, 114000]:
    print(f"  (44439pts at BTC=${px:,} = {100*44439/px:.1f}% of price)")

print("\n=== RELATIVE SL (as % of entry price, calibrated to roughly match current $ risk at today's ~$63k price ~= 70.5%) ===")
for pct in [0.10, 0.20, 0.30, 0.40, 0.50, 0.705, 1.0]:
    z = run(o,h,l,c,tm,N,sigs,'relative',pct)
    print(f"  {100*pct:>5.1f}% of entry price:  trades {z['trades']:>4}  win% {100*z['wins']/max(1,z['trades']):>5.2f}%  "
          f"losses {z['losses']:>2}  net ${z['net']:>10,.2f}   ${z['net']/(span_days/30.44):>7.2f}/mo")
    for L,t,usd,slp in z['loss_events']:
        px_at_loss = "?"
        print(f"      LOSS: {'BUY' if L else 'SELL'} {t}  ${usd}  (sl was {slp:.0f}pts)")

print("\n=== FINE SWEEP 25-55% ===")
for pct in [0.25, 0.28, 0.30, 0.32, 0.35, 0.38, 0.40, 0.42, 0.45, 0.48, 0.50, 0.52, 0.55]:
    z = run(o,h,l,c,tm,N,sigs,'relative',pct)
    print(f"  {100*pct:>5.1f}%:  trades {z['trades']:>4}  win% {100*z['wins']/max(1,z['trades']):>5.2f}%  "
          f"losses {z['losses']:>2}  net ${z['net']:>10,.2f}   ${z['net']/(span_days/30.44):>7.2f}/mo")
