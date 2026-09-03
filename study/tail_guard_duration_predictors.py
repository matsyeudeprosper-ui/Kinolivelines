"""Does anything observable AT ENTRY TIME predict how long a trade will
take? Test candidate 1: recent volatility (ATR14, H1). Correlate with
actual trade duration across the full cap=1 Tail Guard trade history
(using per-anchor calibrated SL, same as the multi-anchor validation).
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

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

# ATR14 on H1, computed causally (only past bars)
tr = np.zeros(N)
for i in range(1, N):
    tr[i] = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
atr14 = np.zeros(N)
for i in range(14, N):
    atr14[i] = tr[i-13:i+1].mean()

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


def run_with_atr(o,h,l,c,tm,atr,offset,N,sigs,SL_PTS):
    bal = 1000.0
    pending = None; in_pos = False; pos_L=None; pos_entry=None; pos_entry_t=None; pos_atr=None
    trades = []
    for j in range(N):
        if pending is not None:
            L, entry, et, a = pending
            in_pos = True; pos_L=L; pos_entry=entry; pos_entry_t=et; pos_atr=a; pending=None
        if j in sigs and j+1 < N and not in_pos:
            L = (sigs[j]==1); SP = c[j]*SPCT
            entry = o[j+1]+SP if L else o[j+1]
            a = atr[offset+j]  # ATR AT signal bar (causal, known before entry)
            pending = (L, entry, tm[j+1], a)
        if in_pos:
            tp_price = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            sl_price = pos_entry-SL_PTS if pos_L else pos_entry+SL_PTS
            hit_tp = (h[j]>=tp_price) if pos_L else (l[j]<=tp_price)
            hit_sl = (l[j]<=sl_price) if pos_L else (h[j]>=sl_price)
            if hit_tp or hit_sl:
                dur_h = (tm[j]-pos_entry_t)/3600
                won = hit_tp and not hit_sl
                trades.append((pos_atr, dur_h, won))
                in_pos = False
    return trades


all_trades = []
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
    trs = run_with_atr(ot,ht,lt,ct,tmt,atr14,test_start,Nt,sigt,SL_PTS)
    all_trades.extend(trs)

atrs = np.array([t[0] for t in all_trades])
durs = np.array([t[1] for t in all_trades])
wons = np.array([t[2] for t in all_trades])
atr_pct = np.array([(atrs[i] / c[bounds[1]]) for i in range(len(atrs))])  # rough normalization

print(f"total trades pooled across 5 anchors: {len(all_trades)}\n")
corr = np.corrcoef(atrs, durs)[0,1]
print(f"correlation(ATR at entry, duration): {corr:+.3f}")
corr_log = np.corrcoef(atrs, np.log1p(durs))[0,1]
print(f"correlation(ATR at entry, log(1+duration)): {corr_log:+.3f}\n")

# bucket by ATR quartile, look at median/mean duration and loss rate
q = np.percentile(atrs, [25,50,75])
buckets = np.digitize(atrs, q)
print("BY ATR QUARTILE AT ENTRY")
for b in range(4):
    m = buckets == b
    n = m.sum()
    if n == 0: continue
    print(f"  Q{b+1} (n={n:>4})  median dur {np.median(durs[m]):>6.1f}h  mean dur {durs[m].mean():>7.1f}h  "
          f"win% {100*wons[m].mean():5.1f}%  worst dur {durs[m].max():>7.0f}h ({durs[m].max()/24:.0f}d)")

print(f"\nthe 2 known real losses - their ATR percentile at entry:")
loss_mask = ~wons
for a, d in zip(atrs[loss_mask], durs[loss_mask]):
    pctile = 100*np.mean(atrs <= a)
    print(f"  ATR={a:.1f}  (percentile {pctile:.0f} of all trades)  duration {d:.0f}h ({d/24:.1f}d)")
