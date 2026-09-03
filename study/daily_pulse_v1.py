"""New strategy design, separate from Tail Guard: goal is regular DAILY
activity, not near-certain wins. Same entry (A0 reversal brick), cap=1,
TP=$1, but SL is a much smaller, conventional level instead of a rare-event
percentile - accept frequent moderate losses in exchange for fast
resolution and daily cadence. Testing several SL percentiles to compare.
Multi-anchor validated the same way as Tail Guard.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from collections import Counter

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
TP_USD = 1.0; TP_PTS = TP_USD / PT
CALIBRATE_WINDOW = 500  # shorter - we care about TYPICAL adverse move, not rare tail
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


def adverse_before_tp_distribution(o,h,l,c,N,sigs):
    """MAE before hitting the $1 target (not unconstrained worst-ever)."""
    vals = []
    for j, dirn in sigs.items():
        if j+1 >= N: continue
        ent_bar = j+1; SP = c[j]*SPCT; L = (dirn==1)
        entry = o[ent_bar]+SP if L else o[ent_bar]
        end = min(N, ent_bar+CALIBRATE_WINDOW)
        best = 0.0; worst = 0.0
        for k in range(ent_bar, end):
            fav = (h[k]-entry) if L else (entry-l[k])
            adv = (entry-l[k]) if L else (h[k]-entry)
            if adv > worst: worst = adv
            if fav > best: best = fav
            if best >= TP_PTS:
                break
        vals.append(worst)
    return np.array(vals)


def run(o,h,l,c,tm,N,sigs,SL_PTS):
    bal = 1000.0; peak = bal; mdd = 0.0; lo = bal
    wins = losses = 0; pnl_list = []
    pending = None; in_pos = False; pos_L=None; pos_entry=None
    entry_days = []
    for j in range(N):
        if pending is not None:
            L, entry = pending
            in_pos = True; pos_L=L; pos_entry=entry; pending=None
        if j in sigs and j+1 < N and not in_pos:
            L = (sigs[j]==1); SP = c[j]*SPCT
            entry = o[j+1]+SP if L else o[j+1]
            pending = (L, entry)
            entry_days.append(datetime.utcfromtimestamp(tm[j+1]).date())
        if in_pos:
            tp_price = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            sl_price = pos_entry-SL_PTS if pos_L else pos_entry+SL_PTS
            hit_tp = (h[j]>=tp_price) if pos_L else (l[j]<=tp_price)
            hit_sl = (l[j]<=sl_price) if pos_L else (h[j]>=sl_price)
            if hit_tp and hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses+=1; in_pos=False
            elif hit_tp:
                bal += TP_PTS*PT; pnl_list.append(TP_PTS*PT); wins+=1; in_pos=False
            elif hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses+=1; in_pos=False
        peak = max(peak, bal); mdd = max(mdd, peak-bal); lo = min(lo, bal)
        if bal <= 0:
            return dict(dead=True, entry_days=entry_days)
    pnl = np.array(pnl_list) if pnl_list else np.array([0.0])
    return dict(dead=False, trades=len(pnl), wins=wins, losses=losses, end=bal, lo=lo, mdd=mdd,
                winrate=100*wins/max(1,len(pnl)), entry_days=entry_days)


for SL_PCTILE in (50, 60, 70, 75):
    print(f"\n{'='*90}\nSL = {SL_PCTILE}th percentile of adverse-move-before-TP (calibrated per-anchor)\n{'='*90}")
    print(f"{'anchor':>7} {'SL($)':>8} {'trades':>7} {'win%':>6} {'ended':>10} {'lowest':>9}")
    results = []
    all_entry_days = []; all_span_days = []
    for i in range(1, NSEG):
        cal_end = bounds[i]
        test_start, test_end = bounds[i], bounds[i+1]
        oc,hc,lc,cc = o[:cal_end],h[:cal_end],l[:cal_end],c[:cal_end]
        sigc = signals_reversal(oc,hc,lc,cc,cal_end)
        dist = adverse_before_tp_distribution(oc,hc,lc,cc,cal_end,sigc)
        SL_USD = np.percentile(dist, SL_PCTILE) * PT
        SL_PTS = SL_USD / PT
        ot,ht,lt,ct,tmt = o[test_start:test_end],h[test_start:test_end],l[test_start:test_end],c[test_start:test_end],tm[test_start:test_end]
        Nt = test_end - test_start
        sigt = signals_reversal(ot,ht,lt,ct,Nt)
        z = run(ot,ht,lt,ct,tmt,Nt,sigt,SL_PTS)
        results.append(z)
        all_entry_days.extend(z["entry_days"])
        all_span_days.extend([datetime.utcfromtimestamp(t).date() for t in tmt])
        if z["dead"]:
            print(f"seg {i:>3} ${SL_USD:>7.2f}   *** DIED ***")
        else:
            print(f"seg {i:>3} ${SL_USD:>7.2f} {z['trades']:>7} {z['winrate']:>5.1f}% ${z['end']:>9,.2f} ${z['lo']:>8,.2f}")
    n_dead = sum(1 for z in results if z["dead"])
    day_counter = Counter(all_entry_days)
    total_days = len(set(all_span_days))
    pct_active = 100*len(day_counter)/total_days
    print(f"died {n_dead}/5   days with >=1 trade: {pct_active:.1f}%   avg trades/day: {sum(day_counter.values())/total_days:.2f}")
