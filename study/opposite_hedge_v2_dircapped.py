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

ok = mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
rh1 = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
FROM_H1 = datetime(2022,1,1)
keep = rh1["time"] >= FROM_H1.timestamp()
rh1 = rh1[keep]
NH1 = len(rh1); NSEG=6
bounds = [int(NH1*i/NSEG) for i in range(NSEG+1)]
seg_dates = []
for i in range(1, NSEG):
    d0 = datetime.utcfromtimestamp(rh1["time"][bounds[i]])
    d1 = datetime.utcfromtimestamp(rh1["time"][bounds[i+1]-1])
    seg_dates.append((d0, d1))

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
    bal=0.0; wins=losses=0; pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_sl=None
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
                if hsl: losses+=1
                else: wins+=1
                in_pos=False
    return dict(trades=wins+losses, losses=losses, net=bal)

def run_direction_capped(o,h,l,c,tm,N,sigs):
    """At most ONE open position per direction (max 2 total: one BUY, one
    SELL). A new signal only opens if that DIRECTION doesn't already have
    an open position - regardless of which one is 'older'/'primary'. This
    is the fix: prevents two same-direction exposures ever coexisting."""
    bal=0.0; wins=losses=0; loss_events=[]
    slots = {True: None, False: None}  # direction -> (entry, sl) or None
    pending = {True: None, False: None}
    for j in range(N):
        for d in (True, False):
            if pending[d] is not None:
                entry = pending[d]; pending[d] = None
                slots[d] = (entry, entry*REL_SL_PCT)
        if j in sigs and j+1<N:
            sig_L = (sigs[j]==1)
            if slots[sig_L] is None and pending[sig_L] is None:
                SP=SPREAD_PTS if sig_L else 0.0
                entry = o[j+1]+SP if sig_L else o[j+1]
                pending[sig_L] = entry
        for d in (True, False):
            if slots[d] is not None:
                entry, sl = slots[d]
                tpp = entry+TP_PTS if d else entry-TP_PTS
                slp = entry-sl if d else entry+sl
                htp = (h[j]>=tpp) if d else (l[j]<=tpp)
                hsl = (l[j]<=slp) if d else (h[j]>=slp)
                if htp or hsl:
                    usd = (-sl if hsl else TP_PTS)*PT*SCALE
                    bal += usd
                    if hsl: losses+=1; loss_events.append((d, datetime.utcfromtimestamp(tm[j]), round(usd,2)))
                    else: wins+=1
                    slots[d] = None
    return dict(trades=wins+losses, losses=losses, net=bal, loss_events=loss_events)

print("="*100)
total_base=0; total_capped=0
for i,(d0,d1) in enumerate(seg_dates,1):
    mask = (tm_f >= d0.timestamp()) & (tm_f <= d1.timestamp())
    ot,ht,lt,ct,tmt = o_f[mask],h_f[mask],l_f[mask],c_f[mask],tm_f[mask]
    Nt = len(ct)
    sigt = build_bricks_signals(ot,ht,lt,ct,Nt)
    zb = run_baseline(ot,ht,lt,ct,tmt,Nt,sigt)
    zc = run_direction_capped(ot,ht,lt,ct,tmt,Nt,sigt)
    total_base += zb['net']; total_capped += zc['net']
    print(f"\n=== SEGMENT {i}: {d0.date()} to {d1.date()} ===")
    print(f"  BASELINE (single pos):        {zb['trades']:>4} trades  {zb['losses']} losses  net ${zb['net']:>10,.2f}")
    print(f"  DIRECTION-CAPPED (max 1/side): {zc['trades']:>4} trades  {zc['losses']} losses  net ${zc['net']:>10,.2f}   (diff: ${zc['net']-zb['net']:+,.2f})")
    for d,t,usd in zc['loss_events']:
        print(f"      LOSS: {'BUY' if d else 'SELL'} {t}  ${usd}")
print("="*100)
print(f"\nTOTAL across 5 segments: baseline ${total_base:,.2f}  direction-capped ${total_capped:,.2f}  diff ${total_capped-total_base:+,.2f}")
