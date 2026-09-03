import json
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

REVERSAL = 2
PT = 0.01
TP_PTS = 100.0
SPREAD_PTS = 10.0
LOTS = 0.05; SCALE = LOTS/0.01
REL_SL_PCT = 0.40
BRICK_PCT = 50.0/64000.0  # matches today's 50pt brick at ~$64k exactly

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
print(f"M1 bars: {N}  {datetime.utcfromtimestamp(tm[0])} -> {datetime.utcfromtimestamp(tm[-1])}  ({span_days:.1f} days)\n")

def build_bricks_fixed(o,h,l,c,N):
    """today's LIVE mechanism: literal fixed 50pt brick"""
    revs = {}
    ao = ac = float(o[0]); d = 0; pd_ = 0
    BRICK=50.0
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

def build_bricks_relative(o,h,l,c,N,pct):
    """new candidate: brick = pct of CURRENT price, recomputed each bar
    (same convention as the H1 backtest scripts' signals_reversal)"""
    revs = {}
    ao = ac = float(o[0]); d = 0; pd_ = 0
    for i in range(N):
        B = c[i]*pct
        while True:
            up = (ao if d==-1 else ac) + B*(REVERSAL if d==-1 else 1)
            dn = (ao if d==1 else ac) - B*(REVERSAL if d==1 else 1)
            if c[i] >= up:
                base = ao if d==-1 else ac; ao,ac,d = base, base+B, 1
            elif c[i] <= dn:
                base = ao if d==1 else ac; ao,ac,d = base, base-B, -1
            else: break
            if pd_ and d != pd_: revs.setdefault(i,d)
            pd_ = d
    return revs

def run(o,h,l,c,tm,N,sigs):
    bal=0.0; wins=losses=0; pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
    loss_events=[]
    for j in range(N):
        if pending is not None:
            L,entry = pending; in_pos=True; pos_L=L; pos_entry=entry; pending=None
            pos_sl = entry*REL_SL_PCT
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
                usd = (-pos_sl if hsl else TP_PTS)*PT*SCALE
                bal += usd
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(tm[j]), round(usd,2)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events)

print("=== TODAY'S LIVE CONFIG: fixed 50pt brick + relative 40% SL ===")
sigs_fixed = build_bricks_fixed(o,h,l,c,N)
print(f"total signals: {len(sigs_fixed)}")
zf = run(o,h,l,c,tm,N,sigs_fixed)
print(f"  trades {zf['trades']}  win% {100*zf['wins']/zf['trades']:.2f}  losses {zf['losses']}  net ${zf['net']:.2f}   ${zf['net']/(span_days/30.44):.2f}/mo")
for L,t,usd in zf['loss_events']:
    print(f"    LOSS: {'BUY' if L else 'SELL'} {t}  ${usd}")

print(f"\n=== CANDIDATE: relative brick ({BRICK_PCT*100:.4f}% of price, matches 50pt at $64k) + relative 40% SL ===")
sigs_rel = build_bricks_relative(o,h,l,c,N,BRICK_PCT)
print(f"total signals: {len(sigs_rel)}")
zr = run(o,h,l,c,tm,N,sigs_rel)
print(f"  trades {zr['trades']}  win% {100*zr['wins']/zr['trades']:.2f}  losses {zr['losses']}  net ${zr['net']:.2f}   ${zr['net']/(span_days/30.44):.2f}/mo")
for L,t,usd in zr['loss_events']:
    print(f"    LOSS: {'BUY' if L else 'SELL'} {t}  ${usd}")

print(f"\nDIFFERENCE: ${zr['net']-zf['net']:+,.2f}")
