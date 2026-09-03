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
print(f"full range: {datetime.utcfromtimestamp(tm_f[0])} -> {datetime.utcfromtimestamp(tm_f[-1])}\n")

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

def run_capped_v2(o,h,l,c,tm,N,sigs,trigger_frac):
    bal=0.0; wins=losses=0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    loss_events=[]
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trigger = trigger_frac*default_sl_usd
            if realized_cum >= trigger:
                sl_usd = min(max(realized_cum, 0.0), default_sl_usd)
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

# three independent, non-overlapping ~2-year windows
segs = [
    ("2020-08-16 -> 2022-08-16", datetime(2020,8,16), datetime(2022,8,16)),
    ("2022-08-16 -> 2024-08-16", datetime(2022,8,16), datetime(2024,8,16)),
    ("2024-08-16 -> 2026-08-18", datetime(2024,8,16), datetime(2026,8,18)),
]

for label, d0, d1 in segs:
    mask = (tm_f >= d0.timestamp()) & (tm_f < d1.timestamp())
    ot,ht,lt,ct,tmt = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask]
    Nt = len(ct)
    sigt = build_bricks_signals(ot,ht,lt,ct,Nt)
    zb = run_baseline(ot,ht,lt,ct,tmt,Nt,sigt)
    print(f"=== {label} ({Nt} bars) ===")
    print(f"  BASELINE: trades {zb['trades']}  losses {zb['losses']}  net ${zb['net']:>10,.2f}")
    for tf in [0.20, 0.30, 0.40]:
        z = run_capped_v2(ot,ht,lt,ct,tmt,Nt,sigt,tf)
        print(f"  ratchet trigger={100*tf:>3.0f}%: trades {z['trades']:>4} losses {z['losses']:>2}  net ${z['net']:>10,.2f}  diff ${z['net']-zb['net']:>+9,.2f}")
    print()

print("\n\n=== DETAIL: segment 2 (2022-2024) losses under trigger=30% ===")
mask = (tm_f >= datetime(2022,8,16).timestamp()) & (tm_f < datetime(2024,8,16).timestamp())
ot,ht,lt,ct,tmt = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask]
Nt = len(ct)
sigt = build_bricks_signals(ot,ht,lt,ct,Nt)
zb2 = run_baseline(ot,ht,lt,ct,tmt,Nt,sigt)
z2 = run_capped_v2(ot,ht,lt,ct,tmt,Nt,sigt,0.30)
print(f"baseline losses:")
for L,et,usd in zb2['loss_events']:
    print(f"  {'BUY' if L else 'SELL'} entered {et}  ${usd}")
print(f"ratchet(30%) losses:")
for L,et,usd in z2['loss_events']:
    print(f"  {'BUY' if L else 'SELL'} entered {et}  ${usd}")

def run_soft_reset(o,h,l,c,tm,N,sigs,trigger_frac,loss_retain):
    """Same as capped_v2, but a loss only costs `loss_retain` fraction of its
    full amount toward realized_cum (e.g. loss_retain=0.5 means a loss only
    costs half as much 'memory', so banked protection survives small
    setbacks better). Wins still count in full."""
    bal=0.0; wins=losses=0; realized_cum=0.0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None; pos_et=None
    loss_events=[]
    for j in range(N):
        if pending is not None:
            L,entry,et = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_et=et; pending=None
            default_sl_usd = pos_entry*REL_SL_PCT*LOTS
            trigger = trigger_frac*default_sl_usd
            if realized_cum >= trigger:
                sl_usd = min(max(realized_cum, 0.0), default_sl_usd)
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
                bal += usd
                realized_cum += usd if usd > 0 else usd*loss_retain
                if hsl: losses+=1; loss_events.append((pos_L, datetime.utcfromtimestamp(pos_et), round(usd,2)))
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal, loss_events=loss_events)

print("\n\n=== SOFT RESET variant across all 3 independent segments ===")
for label, d0, d1 in segs:
    mask = (tm_f >= d0.timestamp()) & (tm_f < d1.timestamp())
    ot,ht,lt,ct,tmt = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask]
    Nt = len(ct)
    sigt = build_bricks_signals(ot,ht,lt,ct,Nt)
    zb = run_baseline(ot,ht,lt,ct,tmt,Nt,sigt)
    print(f"{label}: baseline ${zb['net']:,.2f}")
    for lr in [0.0, 0.25, 0.5, 0.75]:
        z = run_soft_reset(ot,ht,lt,ct,tmt,Nt,sigt,0.30,lr)
        print(f"  trigger=30% loss_retain={lr}: trades {z['trades']:>4} losses {z['losses']:>2}  net ${z['net']:>10,.2f}  diff ${z['net']-zb['net']:>+9,.2f}")
