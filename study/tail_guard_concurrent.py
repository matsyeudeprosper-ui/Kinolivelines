"""Same Tail Guard rule (TP $1, SL $311.48 = 1-in-100), but allow MULTIPLE
concurrent positions instead of skipping new signals while one is open.
Each position is independent - same TP/SL, tracked separately. Capped at
various max-concurrent levels to see the frequency/risk tradeoff.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
TP_USD = 1.0; TP_PTS = TP_USD / PT
SL_USD = 311.48; SL_PTS = SL_USD / PT

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c); HALF = N // 2

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


def run(o,h,l,c,tm,N,sigs,max_concurrent):
    bal = 1000.0; peak = bal; mdd = 0.0; lo = bal
    wins = losses = 0; pnl_list = []
    open_positions = []  # list of [L, entry, entry_t]
    pending_new = None
    max_seen_concurrent = 0
    trade_days = set()
    for j in range(N):
        if pending_new is not None:
            open_positions.append(pending_new)
            pending_new = None
        if j in sigs and j+1 < N and len(open_positions) < max_concurrent:
            L = (sigs[j]==1); SP = c[j]*SPCT
            entry = o[j+1]+SP if L else o[j+1]
            pending_new = [L, entry, tm[j+1]]
            trade_days.add(datetime.utcfromtimestamp(tm[j+1]).date())
        max_seen_concurrent = max(max_seen_concurrent, len(open_positions))
        still_open = []
        for pos in open_positions:
            L, entry, et = pos
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
            return dict(dead=True)
    pnl = np.array(pnl_list) if pnl_list else np.array([0.0])
    span_days = (tm[-1]-tm[0])/86400
    return dict(dead=False, trades=len(pnl), wins=wins, losses=losses, end=bal, lo=lo,
                mdd=mdd, mddp=100*mdd/peak if peak else 0, exp=pnl.mean(), worst=pnl.min(),
                winrate=100*wins/max(1,len(pnl)), max_seen=max_seen_concurrent,
                trade_days=len(trade_days), span_days=span_days)


o2,h2,l2,c2,tm2 = o[HALF:],h[HALF:],l[HALF:],c[HALF:],tm[HALF:]
N2 = N - HALF
sig2 = signals_reversal(o2,h2,l2,c2,N2)

print(f"second half span: {(tm2[-1]-tm2[0])/86400:.0f} days\n")
print(f"{'max concurrent':>15} {'trades':>7} {'trades/day':>11} {'days w/>=1 trade':>17} {'win%':>6} {'ended':>10} {'lowest':>9} {'worstDD':>9} {'maxseen':>8}")
for cap in (1, 2, 3, 5, 10, 20, 50):
    z = run(o2,h2,l2,c2,tm2,N2,sig2,cap)
    if z["dead"]:
        print(f"{cap:>15}  *** DIED ***")
        continue
    print(f"{cap:>15} {z['trades']:>7} {z['trades']/z['span_days']:>10.2f} {z['trade_days']:>16}/{int(z['span_days']):<4} "
          f"{z['winrate']:>5.1f}% ${z['end']:>9,.2f} ${z['lo']:>8,.2f} ${z['mdd']:>8,.2f} {z['max_seen']:>8}")
