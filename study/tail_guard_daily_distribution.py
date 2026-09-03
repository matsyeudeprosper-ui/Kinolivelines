import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import Counter

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
TP_USD = 1.0; TP_PTS = TP_USD / PT
CALIBRATE_WINDOW = 2000
FROM = datetime(2022, 1, 1)

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c)
NSEG = 6
bounds = [int(N * i / NSEG) for i in range(NSEG + 1)]


def signals_reversal(o,h,l,c,N):
    revs = {}; ao = ac = float(o[0]); d = 0; pd_ = 0
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                base = ao if d == -1 else ac; ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                base = ao if d == 1 else ac; ao, ac, d = base, base - B, -1
            else: break
            if pd_ and d != pd_: revs.setdefault(i, d)
            pd_ = d
    return revs


def worst_adverse_distribution(o,h,l,c,N,sigs):
    vals = []
    for j, dirn in sigs.items():
        if j+1 >= N: continue
        ent_bar = j+1; SP = c[j]*SPCT; L = (dirn==1)
        entry = o[ent_bar]+SP if L else o[ent_bar]
        end = min(N, ent_bar+CALIBRATE_WINDOW)
        worst = 0.0
        for k in range(ent_bar, end):
            adv = (entry-l[k]) if L else (h[k]-entry)
            if adv > worst: worst = adv
        vals.append(worst)
    return np.array(vals)


all_entry_days = []
all_days_in_span = []
for i in range(1, NSEG):
    cal_end = bounds[i]
    test_start, test_end = bounds[i], bounds[i+1]
    oc,hc,lc,cc = o[:cal_end],h[:cal_end],l[:cal_end],c[:cal_end]
    sigc = signals_reversal(oc,hc,lc,cc,cal_end)
    dist = worst_adverse_distribution(oc,hc,lc,cc,cal_end,sigc)
    SL_USD = np.percentile(dist, 99) * PT
    SL_PTS = SL_USD / PT
    ot,ht,lt,ct,tmt = o[test_start:test_end],h[test_start:test_end],l[test_start:test_end],c[test_start:test_end],tm[test_start:test_end]
    Nt = test_end - test_start
    sigt = signals_reversal(ot,ht,lt,ct,Nt)

    pending = None; in_pos = False; pos_L=None; pos_entry=None
    for j in range(Nt):
        if pending is not None:
            L, entry = pending
            in_pos = True; pos_L=L; pos_entry=entry; pending=None
        if j in sigt and j+1 < Nt and not in_pos:
            L = (sigt[j]==1); SP = ct[j]*SPCT
            entry = ot[j+1]+SP if L else ot[j+1]
            pending = (L, entry)
        if in_pos:
            tp_price = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            sl_price = pos_entry-SL_PTS if pos_L else pos_entry+SL_PTS
            hit_tp = (ht[j]>=tp_price) if pos_L else (lt[j]<=tp_price)
            hit_sl = (lt[j]<=sl_price) if pos_L else (ht[j]>=sl_price)
            if hit_tp or hit_sl:
                all_entry_days.append(datetime.utcfromtimestamp(tmt[j]).date())
                in_pos = False
    for t in tmt:
        all_days_in_span.append(datetime.utcfromtimestamp(t).date())

day_counts = Counter(all_entry_days)
total_days = len(set(all_days_in_span))
dist = Counter(day_counts.values())

print(f"total calendar days spanned across all 5 test segments: {total_days}")
print(f"total trades: {sum(day_counts.values())}\n")

zero_days = total_days - len(day_counts)
print(f"days with 0 trades:   {zero_days:>5}  ({100*zero_days/total_days:.1f}%)")
for k in sorted(dist):
    n = dist[k]
    print(f"days with exactly {k} trade{'s' if k>1 else ' '}: {n:>5}  ({100*n/total_days:.1f}%)")

at_least_1 = sum(v for k,v in dist.items() if k>=1)
at_least_2 = sum(v for k,v in dist.items() if k>=2)
at_least_3 = sum(v for k,v in dist.items() if k>=3)
print(f"\nchance of AT LEAST 1 trade on a given day: {100*at_least_1/total_days:.1f}%")
print(f"chance of AT LEAST 2 trades on a given day: {100*at_least_2/total_days:.1f}%")
print(f"chance of AT LEAST 3 trades on a given day: {100*at_least_3/total_days:.1f}%")
print(f"\naverage trades/day (all days): {sum(day_counts.values())/total_days:.2f}")
print(f"average trades/day (only active days): {sum(day_counts.values())/len(day_counts):.2f}")
