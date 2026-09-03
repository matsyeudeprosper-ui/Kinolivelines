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

# 4-year window only (exclude the 2020-2022 extension used for the 6yr test)
files = ['coinbase_m1_2yr_part0.json','coinbase_m1_2yr_part1.json',
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
N = len(times)
o = np.array([rows[t][0] for t in times]); h = np.array([rows[t][1] for t in times])
l = np.array([rows[t][2] for t in times]); c = np.array([rows[t][3] for t in times])
tm = np.array(times)
span_days = (tm[-1]-tm[0])/86400
print(f"M1 bars: {N}  {datetime.utcfromtimestamp(tm[0])} -> {datetime.utcfromtimestamp(tm[-1])}  ({span_days:.1f} days, {span_days/365.25:.2f} years)\n")

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

def run_baseline(o,h,l,c,tm,N,sigs):
    bal=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    loss_events=[]
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
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(usd,2)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events)

def run_capped_v2(o,h,l,c,tm,N,sigs,trigger_frac):
    bal=0.0; wins=losses=0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    loss_events=[]; ratchet_tighter_count=0
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trigger = trigger_frac*default_sl_usd
            if realized_cum >= trigger:
                sl_usd = min(max(realized_cum, 0.0), default_sl_usd)
                if sl_usd < default_sl_usd: ratchet_tighter_count += 1
            else:
                sl_usd = default_sl_usd
            pos_sl = sl_usd/LOTS
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
                bal += usd; realized_cum += usd
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(usd,2)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events, ratchet_tighter_count=ratchet_tighter_count)

zb = run_baseline(o,h,l,c,tm,N,sigs)
print(f"BASELINE (4yr): trades {zb['trades']}  losses {zb['losses']}  net ${zb['net']:,.2f}\n")

print("=== capped ratchet sweep, 4-year window ===")
for tf in [0.15,0.20,0.25,0.28,0.30,0.32,0.35,0.38,0.40,0.45,0.50,0.55]:
    z = run_capped_v2(o,h,l,c,tm,N,sigs,tf)
    print(f"trigger={100*tf:>5.1f}%: trades {z['trades']:>4} losses {z['losses']:>2}  net ${z['net']:>10,.2f}  diff ${z['net']-zb['net']:>+9,.2f}")
