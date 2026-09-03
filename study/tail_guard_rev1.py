"""Widen the eligible-signal definition: REV=1 (reversal fires after just
1 brick against the trend, instead of 2) instead of changing the entry
GATING (cap stays at 1 - the only version that survived multi-anchor).
Everything else identical: TP $1, SL = 1-in-100 percentile per-anchor,
multi-anchor validated the same way.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 1, 0.01   # <-- widened from 2 to 1
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


def run(o,h,l,c,tm,N,sigs,SL_PTS):
    bal = 1000.0; peak = bal; mdd = 0.0; lo = bal
    wins = losses = 0; pnl_list = []
    pending = None; in_pos = False; pos_L=None; pos_entry=None
    signals_seen = 0; skipped = 0
    for j in range(N):
        if pending is not None:
            L, entry = pending
            in_pos = True; pos_L=L; pos_entry=entry; pending=None
        if j in sigs and j+1 < N:
            signals_seen += 1
            if not in_pos:
                L = (sigs[j]==1); SP = c[j]*SPCT
                entry = o[j+1]+SP if L else o[j+1]
                pending = (L, entry)
            else:
                skipped += 1
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
            return dict(dead=True)
    pnl = np.array(pnl_list) if pnl_list else np.array([0.0])
    span_days = (tm[-1]-tm[0])/86400
    return dict(dead=False, trades=len(pnl), wins=wins, losses=losses, end=bal, lo=lo,
                mdd=mdd, winrate=100*wins/max(1,len(pnl)), trades_per_day=len(pnl)/span_days,
                signals=signals_seen, skipped=skipped)


print(f"REV={REV} (widened from 2)\n")
print(f"{'anchor':>7} {'test period':>23} {'SL($)':>8} {'sigs':>6} {'skip%':>6} {'trades':>7} {'tr/day':>7} {'win%':>6} {'ended':>10} {'lowest':>9}")
results = []
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
    z = run(ot,ht,lt,ct,tmt,Nt,sigt,SL_PTS)
    d0 = datetime.utcfromtimestamp(tmt[0]).strftime("%Y-%m-%d")
    d1 = datetime.utcfromtimestamp(tmt[-1]).strftime("%Y-%m-%d")
    results.append(z)
    if z["dead"]:
        print(f"seg {i:>3}   {d0} to {d1}   *** DIED ***  (SL ${SL_USD:.2f})")
    else:
        print(f"seg {i:>3}   {d0} to {d1}  ${SL_USD:>7.2f} {z['signals']:>6} {100*z['skipped']/z['signals']:>5.1f}% "
              f"{z['trades']:>7} {z['trades_per_day']:>6.2f} {z['winrate']:>5.1f}% ${z['end']:>9,.2f} ${z['lo']:>8,.2f}")

n_dead = sum(1 for z in results if z["dead"])
n_profit = sum(1 for z in results if not z["dead"] and z["end"] > 1000)
print(f"\nSUMMARY: died {n_dead}/{len(results)}   profitable {n_profit}/{len(results)}   losing-but-survived {len(results)-n_dead-n_profit}/{len(results)}")
