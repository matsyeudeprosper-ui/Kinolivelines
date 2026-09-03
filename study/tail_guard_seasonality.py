"""Tail Guard (TP $1, SL = 1-in-100 percentile calibrated on first half)
run on the second-half (honest out-of-sample) period. Report: $/day,
$/week, $/month, trades/day, and performance by session and day-of-week.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
FROM = datetime(2022, 1, 1)
TP_USD = 1.0
TP_PTS = TP_USD / PT
CALIBRATE_WINDOW = 2000

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]
N = len(c)
HALF = N // 2


def signals_reversal(o, h, l, c, N):
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
            else:
                break
            if pd_ and d != pd_:
                revs.setdefault(i, d)
            pd_ = d
    return revs


def worst_adverse_distribution(o, h, l, c, N, sigs):
    vals = []
    for j, dirn in sigs.items():
        if j + 1 >= N: continue
        ent_bar = j + 1; SP = c[j] * SPCT; L = (dirn == 1)
        entry = o[ent_bar] + SP if L else o[ent_bar]
        end = min(N, ent_bar + CALIBRATE_WINDOW)
        worst = 0.0
        for k in range(ent_bar, end):
            adv = (entry - l[k]) if L else (h[k] - entry)
            if adv > worst: worst = adv
        vals.append(worst)
    return np.array(vals)


o1,h1,l1,c1 = o[:HALF],h[:HALF],l[:HALF],c[:HALF]
sig1 = signals_reversal(o1,h1,l1,c1,HALF)
dist1 = worst_adverse_distribution(o1,h1,l1,c1,HALF,sig1)
SL_USD = np.percentile(dist1, 99) * PT
SL_PTS = SL_USD / PT
print(f"SL calibrated (1-in-100, first half): ${SL_USD:.2f}\n")

o2,h2,l2,c2,tm2 = o[HALF:],h[HALF:],l[HALF:],c[HALF:],tm[HALF:]
N2 = N - HALF
sig2 = signals_reversal(o2,h2,l2,c2,N2)

trades = []  # (entry_time, exit_time, pnl_usd, hour_utc, dow)
pending = None; in_pos = False; pos_L = None; pos_entry = None; pos_entry_t = None
for j in range(N2):
    if pending is not None:
        L, entry, et = pending
        in_pos = True; pos_L = L; pos_entry = entry; pos_entry_t = et; pending = None
    if j in sig2 and j + 1 < N2 and not in_pos:
        L = (sig2[j] == 1); SP = c2[j] * SPCT
        entry = o2[j+1] + SP if L else o2[j+1]
        pending = (L, entry, tm2[j+1])
    if in_pos:
        tp_price = pos_entry + TP_PTS if pos_L else pos_entry - TP_PTS
        sl_price = pos_entry - SL_PTS if pos_L else pos_entry + SL_PTS
        hit_tp = (h2[j] >= tp_price) if pos_L else (l2[j] <= tp_price)
        hit_sl = (l2[j] <= sl_price) if pos_L else (h2[j] >= sl_price)
        if hit_tp and hit_sl:
            trades.append((pos_entry_t, tm2[j], -SL_PTS*PT)); in_pos = False
        elif hit_tp:
            trades.append((pos_entry_t, tm2[j], TP_PTS*PT)); in_pos = False
        elif hit_sl:
            trades.append((pos_entry_t, tm2[j], -SL_PTS*PT)); in_pos = False

et = np.array([t[0] for t in trades])
pnl = np.array([t[2] for t in trades])
dates = np.array([datetime.utcfromtimestamp(t) for t in et])
days_span = (et[-1]-et[0])/86400
print(f"trades: {len(trades)}   span: {days_span:.0f} days ({days_span/7:.1f} weeks, {days_span/30.44:.1f} months)")
print(f"total P&L: ${pnl.sum():+.2f}\n")

print("AVERAGES")
print(f"  per day    trades {len(trades)/days_span:.2f}   $ {pnl.sum()/days_span:+.3f}")
print(f"  per week   trades {len(trades)/(days_span/7):.2f}   $ {pnl.sum()/(days_span/7):+.2f}")
print(f"  per month  trades {len(trades)/(days_span/30.44):.2f}   $ {pnl.sum()/(days_span/30.44):+.2f}")

# by session (UTC hour buckets - rough Asian/London/NY split)
hours = np.array([d.hour for d in dates])
dows = np.array([d.weekday() for d in dates])  # 0=Mon .. 6=Sun

def sess(hr):
    if 0 <= hr < 8: return "Asian (00-08 UTC)"
    if 8 <= hr < 13: return "London (08-13 UTC)"
    if 13 <= hr < 21: return "NY/overlap (13-21 UTC)"
    return "Late US (21-24 UTC)"

print("\nBY SESSION (entry time, UTC)")
sessions = np.array([sess(hr) for hr in hours])
for s in ["Asian (00-08 UTC)","London (08-13 UTC)","NY/overlap (13-21 UTC)","Late US (21-24 UTC)"]:
    m = sessions == s
    n = m.sum()
    print(f"  {s:<24} trades {n:>4}  win% {100*np.mean(pnl[m]>0) if n else 0:5.1f}%  "
          f"total ${pnl[m].sum():>+8.2f}  avg/trade ${pnl[m].mean() if n else 0:>+6.3f}")

print("\nBY DAY OF WEEK (entry time, UTC)")
dow_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
for i,nm in enumerate(dow_names):
    m = dows == i
    n = m.sum()
    print(f"  {nm:<5} trades {n:>4}  win% {100*np.mean(pnl[m]>0) if n else 0:5.1f}%  "
          f"total ${pnl[m].sum():>+8.2f}  avg/trade ${pnl[m].mean() if n else 0:>+6.3f}")

print("\nBY CALENDAR MONTH (entry time)")
ym = np.array([d.strftime("%Y-%m") for d in dates])
for k in sorted(set(ym.tolist())):
    m = ym == k
    n = m.sum()
    print(f"  {k}  trades {n:>4}  total ${pnl[m].sum():>+8.2f}")

print("\nBY HOUR OF DAY (UTC, entry time)")
for hr in range(24):
    m = hours == hr
    n = m.sum()
    if n == 0: continue
    print(f"  {hr:02d}:00  trades {n:>4}  win% {100*np.mean(pnl[m]>0):5.1f}%  total ${pnl[m].sum():>+8.2f}")

print("\nTHE LOSS, in detail:")
loss_idx = np.where(pnl < 0)[0]
for i in loss_idx:
    et_, xt_, p_ = trades[i]
    print(f"  entry {datetime.utcfromtimestamp(et_)} UTC (hour {datetime.utcfromtimestamp(et_).hour:02d}, "
          f"{dow_names[datetime.utcfromtimestamp(et_).weekday()]})")
    print(f"  exit  {datetime.utcfromtimestamp(xt_)} UTC")
    print(f"  pnl   ${p_:+.2f}")
