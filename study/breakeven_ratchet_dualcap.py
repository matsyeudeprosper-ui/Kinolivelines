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
N_full = len(times)
o_f = np.array([rows[t][0] for t in times]); h_f = np.array([rows[t][1] for t in times])
l_f = np.array([rows[t][2] for t in times]); c_f = np.array([rows[t][3] for t in times])
tm_f = np.array(times)

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

def run_dualcap(o,h,l,c,tm,N,sigs,trigger_frac,cap_frac):
    """trigger_frac and cap_frac both fractions of default_sl_usd. Once
    realized_cum crosses trigger, SL = min(realized_cum, cap_frac*default) -
    a PERMANENTLY tighter ceiling, not just capped at full default."""
    bal=0.0; wins=losses=0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    loss_events=[]
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trigger = trigger_frac*default_sl_usd
            cap = cap_frac*default_sl_usd
            if realized_cum >= trigger:
                sl_usd = min(max(realized_cum, 0.0), cap)
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
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events)

segs = [
    ("2020-08-16 -> 2022-08-16", datetime(2020,8,16), datetime(2022,8,16)),
    ("2022-08-16 -> 2024-08-16", datetime(2022,8,16), datetime(2024,8,16)),
    ("2024-08-16 -> 2026-08-18", datetime(2024,8,16), datetime(2026,8,18)),
]

results = {}
for label, d0, d1 in segs:
    mask = (tm_f >= d0.timestamp()) & (tm_f < d1.timestamp())
    ot,ht,lt,ct,tmt = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask]
    Nt = len(ct)
    sigt = build_bricks_signals(ot,ht,lt,ct,Nt)
    zb = run_baseline(ot,ht,lt,ct,tmt,Nt,sigt)
    print(f"=== {label} === baseline ${zb['net']:,.2f}")
    for cap_frac in [0.5, 0.6, 0.7, 0.8, 0.9]:
        for tf in [0.2, 0.3]:
            z = run_dualcap(ot,ht,lt,ct,tmt,Nt,sigt,tf,cap_frac)
            key = (tf,cap_frac)
            results.setdefault(key, []).append(z['net']-zb['net'])
            print(f"  trigger={100*tf:.0f}% cap={100*cap_frac:.0f}%: trades {z['trades']:>4} losses {z['losses']:>2}  net ${z['net']:>10,.2f}  diff ${z['net']-zb['net']:>+9,.2f}")
    print()

print("=== SUMMED across all 3 segments ===")
for key, diffs in results.items():
    tf, cap_frac = key
    print(f"trigger={100*tf:.0f}% cap={100*cap_frac:.0f}%: sum diff ${sum(diffs):>+10,.2f}   (per-seg: {[f'{d:+.0f}' for d in diffs]})")

print("\n\n=== FINE SWEEP: cap 75-95%, trigger 15-35% ===")
results2 = {}
for label, d0, d1 in segs:
    mask = (tm_f >= d0.timestamp()) & (tm_f < d1.timestamp())
    ot,ht,lt,ct,tmt = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask]
    Nt = len(ct)
    sigt = build_bricks_signals(ot,ht,lt,ct,Nt)
    zb = run_baseline(ot,ht,lt,ct,tmt,Nt,sigt)
    for cap_frac in [0.75, 0.80, 0.85, 0.88, 0.90, 0.92, 0.95]:
        for tf in [0.15, 0.20, 0.25, 0.30, 0.35]:
            z = run_dualcap(ot,ht,lt,ct,tmt,Nt,sigt,tf,cap_frac)
            key = (tf,cap_frac)
            results2.setdefault(key, []).append(z['net']-zb['net'])

print("trigger  cap    seg1      seg2      seg3      SUM")
for tf in [0.15, 0.20, 0.25, 0.30, 0.35]:
    for cap_frac in [0.75, 0.80, 0.85, 0.88, 0.90, 0.92, 0.95]:
        diffs = results2[(tf,cap_frac)]
        print(f"{100*tf:>5.0f}%  {100*cap_frac:>4.0f}%  {diffs[0]:>+8.0f}  {diffs[1]:>+8.0f}  {diffs[2]:>+8.0f}  {sum(diffs):>+9.0f}")

print("\n\n=== targeted: trigger 33-40%, cap 82-96% (does seg2 staying positive hold up?) ===")
results3 = {}
for label, d0, d1 in segs:
    mask = (tm_f >= d0.timestamp()) & (tm_f < d1.timestamp())
    ot,ht,lt,ct,tmt = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask]
    Nt = len(ct)
    sigt = build_bricks_signals(ot,ht,lt,ct,Nt)
    zb = run_baseline(ot,ht,lt,ct,tmt,Nt,sigt)
    for cap_frac in [0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94, 0.96]:
        for tf in [0.33, 0.34, 0.35, 0.36, 0.37, 0.38, 0.40]:
            z = run_dualcap(ot,ht,lt,ct,tmt,Nt,sigt,tf,cap_frac)
            key = (tf,cap_frac)
            results3.setdefault(key, []).append(z['net']-zb['net'])

print("trigger  cap    seg1      seg2      seg3      SUM")
for tf in [0.33, 0.34, 0.35, 0.36, 0.37, 0.38, 0.40]:
    for cap_frac in [0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94, 0.96]:
        diffs = results3[(tf,cap_frac)]
        print(f"{100*tf:>5.0f}%  {100*cap_frac:>4.0f}%  {diffs[0]:>+8.0f}  {diffs[1]:>+8.0f}  {diffs[2]:>+8.0f}  {sum(diffs):>+9.0f}")

print("\n\n=== cliff-mapping: trigger 34.0-37.0% in 0.25% steps, cap 88/90/92% ===")
results4 = {}
for label, d0, d1 in segs:
    mask = (tm_f >= d0.timestamp()) & (tm_f < d1.timestamp())
    ot,ht,lt,ct,tmt = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask]
    Nt = len(ct)
    sigt = build_bricks_signals(ot,ht,lt,ct,Nt)
    zb = run_baseline(ot,ht,lt,ct,tmt,Nt,sigt)
    for cap_frac in [0.88, 0.90, 0.92]:
        tf = 0.340
        while tf <= 0.3701:
            z = run_dualcap(ot,ht,lt,ct,tmt,Nt,sigt,tf,cap_frac)
            key = (round(tf,4),cap_frac)
            results4.setdefault(key, []).append(z['net']-zb['net'])
            tf += 0.0025

print("trigger  cap    seg1      seg2      seg3      SUM")
for cap_frac in [0.88, 0.90, 0.92]:
    tf = 0.340
    while tf <= 0.3701:
        key = (round(tf,4),cap_frac)
        diffs = results4[key]
        print(f"{100*tf:>6.2f}%  {100*cap_frac:>4.0f}%  {diffs[0]:>+8.0f}  {diffs[1]:>+8.0f}  {diffs[2]:>+8.0f}  {sum(diffs):>+9.0f}")
    print()
