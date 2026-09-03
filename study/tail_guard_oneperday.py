"""Test: allow at most ONE NEW trade to open per calendar day, regardless
of how many are already running (no separate concurrency cap). If a trade
carries into the next day, that day can still open its own new one.
Same TP=$1 / SL=1-in-100 percentile. Multi-anchor validated (6 segments,
same as before) to catch any dangerous concurrency buildup.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
TP_USD = 1.0; TP_PTS = TP_USD / PT
CALIBRATE_WINDOW = 2000

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
    open_positions = []; pending_new = None
    last_new_day = None
    max_seen = 0
    for j in range(N):
        if pending_new is not None:
            open_positions.append(pending_new); pending_new = None
        this_day = datetime.utcfromtimestamp(tm[j]).date()
        if j in sigs and j+1 < N and this_day != last_new_day:
            L = (sigs[j]==1); SP = c[j]*SPCT
            entry = o[j+1]+SP if L else o[j+1]
            pending_new = [L, entry]
            last_new_day = this_day
        max_seen = max(max_seen, len(open_positions) + (1 if pending_new else 0))
        still_open = []
        for pos in open_positions:
            L, entry = pos
            tp_price = entry+TP_PTS if L else entry-TP_PTS
            sl_price = entry-SL_PTS if L else entry+SL_PTS
            hit_tp = (h[j]>=tp_price) if L else (l[j]<=tp_price)
            hit_sl = (l[j]<=sl_price) if L else (h[j]>=sl_price)
            if hit_tp and hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses += 1
            elif hit_tp:
                bal += TP_PTS*PT; pnl_list.append(TP_PTS*PT); wins += 1
            elif hit_sl:
                bal -= SL_PTS*PT; pnl_list.append(-SL_PTS*PT); losses += 1
            else:
                still_open.append(pos)
        open_positions = still_open
        flo = sum(((c[j]-p[1]) if p[0] else (p[1]-c[j])) for p in open_positions) * PT
        eq = bal + flo
        peak = max(peak, eq); mdd = max(mdd, peak-eq); lo = min(lo, eq)
        if eq <= 0:
            return dict(dead=True, max_seen=max_seen)
    pnl = np.array(pnl_list) if pnl_list else np.array([0.0])
    span_days = (tm[-1]-tm[0])/86400
    return dict(dead=False, trades=len(pnl), wins=wins, losses=losses, end=bal, lo=lo,
                mdd=mdd, mddp=100*mdd/peak if peak else 0, winrate=100*wins/max(1,len(pnl)),
                max_seen=max_seen, trades_per_day=len(pnl)/span_days)


print(f"{'anchor':>7} {'test period':>23} {'SL($)':>8} {'trades':>7} {'tr/day':>7} {'maxconc':>8} {'win%':>6} {'ended':>10} {'lowest':>9} {'worstDD':>9}")
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
        print(f"seg {i:>3}   {d0} to {d1}   *** DIED ***  (SL ${SL_USD:.2f}, max concurrent reached: {z['max_seen']})")
    else:
        print(f"seg {i:>3}   {d0} to {d1}  ${SL_USD:>7.2f} {z['trades']:>7} {z['trades_per_day']:>6.2f} {z['max_seen']:>8} "
              f"{z['winrate']:>5.1f}% ${z['end']:>9,.2f} ${z['lo']:>8,.2f} ${z['mdd']:>8,.2f}")

n_dead = sum(1 for z in results if z["dead"])
n_profit = sum(1 for z in results if not z["dead"] and z["end"] > 1000)
print(f"\nSUMMARY: died {n_dead}/{len(results)}   profitable {n_profit}/{len(results)}   losing-but-survived {len(results)-n_dead-n_profit}/{len(results)}")
