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

def run_dualcap(o,h,l,c,tm,N,sigs,trigger_frac,cap_frac):
    bal=0.0; wins=losses=0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
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
                if hsl: losses+=1
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal)

seg1 = ("2020-08-16 -> 2022-08-16", datetime(2020,8,16), datetime(2022,8,16))
label,d0,d1 = seg1
mask = (tm_f >= d0.timestamp()) & (tm_f < d1.timestamp())
ot,ht,lt,ct,tmt = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask]
Nt = len(ct)
sigt = build_bricks_signals(ot,ht,lt,ct,Nt)
zb = run_baseline(ot,ht,lt,ct,tmt,Nt,sigt)
print(f"seg1 baseline: ${zb['net']:,.2f}  losses={zb['losses']}")

print("\n=== fine cap sweep at trigger=35%, seg1 only, checking for a 2nd plateau near cap~80% ===")
for cap_frac in [0.74,0.76,0.78,0.80,0.82,0.84,0.86,0.88,0.90,0.92]:
    z = run_dualcap(ot,ht,lt,ct,tmt,Nt,sigt,0.35,cap_frac)
    print(f"cap={100*cap_frac:>5.1f}%  net=${z['net']:>9,.2f}  diff=${z['net']-zb['net']:>+9,.2f}  losses={z['losses']}")

print("\n=== same cap sweep at trigger=30% (below the seg2 threshold, for comparison) ===")
for cap_frac in [0.74,0.76,0.78,0.80,0.82,0.84,0.86,0.88,0.90,0.92,1.00]:
    z = run_dualcap(ot,ht,lt,ct,tmt,Nt,sigt,0.30,cap_frac)
    print(f"cap={100*cap_frac:>5.1f}%  net=${z['net']:>9,.2f}  diff=${z['net']-zb['net']:>+9,.2f}  losses={z['losses']}")

def run_twostage(o,h,l,c,tm,N,sigs,tA,capA,tB,capB):
    """Two-stage ratchet: arm loosely at tA (cap capA, normally 100%), then
    tighten further once realized_cum also crosses the higher tB (cap capB, tighter)."""
    bal=0.0; wins=losses=0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trigA = tA*default_sl_usd; trigB = tB*default_sl_usd
            capAusd = capA*default_sl_usd; capBusd = capB*default_sl_usd
            if realized_cum >= trigB:
                sl_usd = min(max(realized_cum,0.0), capBusd)
            elif realized_cum >= trigA:
                sl_usd = min(max(realized_cum,0.0), capAusd)
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
                if hsl: losses+=1
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal)

print("\n\n=== TWO-STAGE ratchet: tA=20%/capA=100%, tB=35%/capB=90%, all 3 segments ===")
segs = [
    ("2020-08-16 -> 2022-08-16", datetime(2020,8,16), datetime(2022,8,16)),
    ("2022-08-16 -> 2024-08-16", datetime(2022,8,16), datetime(2024,8,16)),
    ("2024-08-16 -> 2026-08-18", datetime(2024,8,16), datetime(2026,8,18)),
]
total_diff = 0.0
for label, d0, d1 in segs:
    mask = (tm_f >= d0.timestamp()) & (tm_f < d1.timestamp())
    ot2,ht2,lt2,ct2,tmt2 = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask]
    Nt2 = len(ct2)
    sigt2 = build_bricks_signals(ot2,ht2,lt2,ct2,Nt2)
    zb2 = run_baseline(ot2,ht2,lt2,ct2,tmt2,Nt2,sigt2)
    z2 = run_twostage(ot2,ht2,lt2,ct2,tmt2,Nt2,sigt2, 0.20,1.00, 0.35,0.90)
    diff = z2['net']-zb2['net']
    total_diff += diff
    print(f"{label}: baseline ${zb2['net']:>9,.2f}  twostage ${z2['net']:>9,.2f}  diff ${diff:>+9,.2f}  losses={z2['losses']}")
print(f"SUM diff: ${total_diff:+,.2f}")
