import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0/64000.0, 10.0/64000.0
REV, PT = 2, 0.01
FROM = datetime(2022,1,1)
LOTS = 0.05; SCALE = LOTS/0.01
TP_USD = 5.0; TP_PTS = TP_USD/(PT*SCALE)   # =100
CALIBRATE_WINDOW = 2000
HT_FLOOR = 400.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o,h,l,c = (r[k].astype(float) for k in ("open","high","low","close"))
tm = r["time"]; N = len(c)
NSEG = 6
bounds = [int(N*i/NSEG) for i in range(NSEG+1)]

def signals_reversal(o,h,l,c,N):
    revs = {}; ao=ac=float(o[0]); d=0; pd_=0
    for i in range(N):
        B = c[i]*PCT
        while True:
            up = (ao if d==-1 else ac) + B*(REV if d==-1 else 1)
            dn = (ao if d==1 else ac) - B*(REV if d==1 else 1)
            if c[i] >= up:
                base = ao if d==-1 else ac; ao,ac,d = base, base+B, 1
            elif c[i] <= dn:
                base = ao if d==1 else ac; ao,ac,d = base, base-B, -1
            else: break
            if pd_ and d!=pd_: revs.setdefault(i,d)
            pd_ = d
    return revs

def worst_adverse_distribution(o,h,l,c,N,sigs):
    vals=[]
    for j,dirn in sigs.items():
        if j+1>=N: continue
        ent_bar=j+1; SP=c[j]*SPCT; L=(dirn==1)
        entry = o[ent_bar]+SP if L else o[ent_bar]
        end=min(N, ent_bar+CALIBRATE_WINDOW)
        worst=0.0
        for k in range(ent_bar,end):
            adv = (entry-l[k]) if L else (h[k]-entry)
            if adv>worst: worst=adv
        vals.append(worst)
    return np.array(vals)

i = 4
cal_end = bounds[i]
test_start, test_end = bounds[i], bounds[i+1]
oc,hc,lc,cc = o[:cal_end],h[:cal_end],l[:cal_end],c[:cal_end]
sigc = signals_reversal(oc,hc,lc,cc,cal_end)
dist = worst_adverse_distribution(oc,hc,lc,cc,cal_end,sigc)
SL_USD_DEFAULT = np.percentile(dist,99)*PT
SL_PTS_DEFAULT = SL_USD_DEFAULT/PT

ot,ht,lt,ct,tmt = o[test_start:test_end],h[test_start:test_end],l[test_start:test_end],c[test_start:test_end],tm[test_start:test_end]
Nt = test_end-test_start
sigt = signals_reversal(ot,ht,lt,ct,Nt)
d0 = datetime.utcfromtimestamp(tmt[0]).strftime("%Y-%m-%d")
d1 = datetime.utcfromtimestamp(tmt[-1]).strftime("%Y-%m-%d")
print(f"SEGMENT 4: {d0} to {d1}  default SL=${SL_USD_DEFAULT*SCALE:.2f} (per-trade at {LOTS} lots)")
print(f"total signals in segment: {len(sigt)}\n")

def run(o,h,l,c,tm,N,sigs,default_sl_pts,use_halftrail,track=False):
    default_sl_usd = default_sl_pts*PT*SCALE
    activation_usd = 2*HT_FLOOR
    realized_peak = 0.0
    bal_usd=0.0; wins=losses=0
    pending=None; in_pos=False; pos_L=None; pos_entry=None; pos_entry_t=None; pos_sl_pts=None; pos_entry_j=None
    events=[]
    for j in range(N):
        if pending is not None:
            L,entry,et,ej = pending; in_pos=True; pos_L=L; pos_entry=entry; pos_entry_t=et; pos_entry_j=ej; pending=None
            if use_halftrail and realized_peak >= activation_usd:
                sl_usd = max(realized_peak/2.0, HT_FLOOR)
            else:
                sl_usd = default_sl_usd
            pos_sl_pts = sl_usd/(PT*SCALE)
        if j in sigs and j+1<N and not in_pos:
            L=(sigs[j]==1); SP=c[j]*SPCT
            entry = o[j+1]+SP if L else o[j+1]
            pending=(L,entry,tm[j+1],j)
        if in_pos:
            tp_price = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            sl_price = pos_entry-pos_sl_pts if pos_L else pos_entry+pos_sl_pts
            hit_tp = (h[j]>=tp_price) if pos_L else (l[j]<=tp_price)
            hit_sl = (l[j]<=sl_price) if pos_L else (h[j]>=sl_price)
            if hit_tp or hit_sl:
                usd = (-pos_sl_pts if hit_sl else TP_PTS)*PT*SCALE
                bal_usd += usd
                if hit_sl: losses+=1
                else: wins+=1
                realized_peak = max(realized_peak, bal_usd)
                if track:
                    events.append(dict(entry_j=pos_entry_j, L=pos_L, entry_t=pos_entry_t, exit_j=j,
                                        sl_pts=pos_sl_pts, sl_usd=sl_usd, won=hit_tp, usd=round(usd,2)))
                in_pos=False
    return dict(trades=wins+losses, wins=wins, losses=losses, net=bal_usd, events=events)

base = run(ot,ht,lt,ct,tmt,Nt,sigt,SL_PTS_DEFAULT,False,track=True)
ht_ = run(ot,ht,lt,ct,tmt,Nt,sigt,SL_PTS_DEFAULT,True,track=True)

print(f"BASELINE: {base['trades']}tr {base['wins']}W {base['losses']}L  net ${base['net']:.2f}")
print(f"HALF TRAIL: {ht_['trades']}tr {ht_['wins']}W {ht_['losses']}L  net ${ht_['net']:.2f}\n")

base_entry_js = set(e['entry_j'] for e in base['events'])
ht_entry_js = set(e['entry_j'] for e in ht_['events'])
only_in_ht = ht_entry_js - base_entry_js
only_in_base = base_entry_js - ht_entry_js
common = base_entry_js & ht_entry_js
print(f"signals traded in BASELINE: {len(base_entry_js)}")
print(f"signals traded in HALF TRAIL: {len(ht_entry_js)}")
print(f"  common to both: {len(common)}")
print(f"  ONLY in Half Trail (extra trades baseline never attempted): {len(only_in_ht)}")
print(f"  ONLY in baseline (baseline attempted, HT never got to): {len(only_in_base)}\n")

# outcome breakdown of the "extra" trades
extra_events = [e for e in ht_['events'] if e['entry_j'] in only_in_ht]
extra_wins = sum(1 for e in extra_events if e['won'])
extra_losses = sum(1 for e in extra_events if not e['won'])
print(f"Of the {len(extra_events)} EXTRA trades (only Half Trail took them):")
print(f"  wins: {extra_wins}   losses: {extra_losses}")
extra_win_usd = sum(e['usd'] for e in extra_events if e['won'])
extra_loss_usd = sum(e['usd'] for e in extra_events if not e['won'])
print(f"  extra win $: {extra_win_usd:.2f}   extra loss $: {extra_loss_usd:.2f}   net from extras: {extra_win_usd+extra_loss_usd:.2f}\n")

# now the 4 actual losses -- check if they're in the "extra" set or in "common" set
print("=== The 4 Half Trail losses -- were they extra (baseline never took) or common (baseline also took, just different SL)? ===")
for e in ht_['events']:
    if not e['won']:
        tag = "EXTRA (baseline never attempted this signal)" if e['entry_j'] in only_in_ht else "COMMON (baseline also traded this exact entry)"
        print(f"  {'BUY' if e['L'] else 'SELL'} entry_j={e['entry_j']} {datetime.utcfromtimestamp(e['entry_t'])}  SL=${e['sl_usd']:.2f}  loss=${e['usd']:.2f}   -> {tag}")

# for the COMMON-tagged losses, what did baseline do with that same entry_j?
print("\n=== For any COMMON losses, what was baseline's outcome on that same entry? ===")
base_by_j = {e['entry_j']: e for e in base['events']}
for e in ht_['events']:
    if not e['won'] and e['entry_j'] in common:
        be = base_by_j[e['entry_j']]
        print(f"  entry_j={e['entry_j']}: HT={'WIN' if e['won'] else 'LOSS'} ${e['usd']:.2f}  |  baseline={'WIN' if be['won'] else 'LOSS'} ${be['usd']:.2f}")
