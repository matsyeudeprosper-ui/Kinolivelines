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
    bal = 1000.0
    pending = None; in_pos = False; pos_L=None; pos_entry=None; pos_entry_t=None
    trades = []
    for j in range(N):
        if pending is not None:
            L, entry, et = pending
            in_pos = True; pos_L=L; pos_entry=entry; pos_entry_t=et; pending=None
        if j in sigs and j+1 < N and not in_pos:
            L = (sigs[j]==1); SP = c[j]*SPCT
            entry = o[j+1]+SP if L else o[j+1]
            pending = (L, entry, tm[j+1])
        if in_pos:
            tp_price = pos_entry+TP_PTS if pos_L else pos_entry-TP_PTS
            sl_price = pos_entry-SL_PTS if pos_L else pos_entry+SL_PTS
            hit_tp = (h[j]>=tp_price) if pos_L else (l[j]<=tp_price)
            hit_sl = (l[j]<=sl_price) if pos_L else (h[j]>=sl_price)
            if hit_tp or hit_sl:
                dur_h = (tm[j]-pos_entry_t)/3600
                won = hit_tp and not hit_sl
                trades.append((pos_L, dur_h, won))
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
    trs = run(ot,ht,lt,ct,tmt,Nt,sigt,SL_PTS)
    all_trades.extend(trs)

Ls = np.array([t[0] for t in all_trades])
durs = np.array([t[1] for t in all_trades])
wons = np.array([t[2] for t in all_trades])

print(f"total trades pooled: {len(all_trades)}\n")
for lbl, mask in (("BUY", Ls), ("SELL", ~Ls)):
    m = mask
    n = m.sum()
    print(f"{lbl:<5} n={n:>4}  win% {100*wons[m].mean():5.1f}%  losses {int((~wons[m]).sum())}  "
          f"mean dur {durs[m].mean():>7.1f}h  median dur {np.median(durs[m]):>5.1f}h  worst dur {durs[m].max():>7.0f}h ({durs[m].max()/24:.0f}d)")

print(f"\nthe 2 known real losses - direction:")
loss_mask = ~wons
for Lv, d in zip(Ls[loss_mask], durs[loss_mask]):
    print(f"  {'BUY' if Lv else 'SELL'}  duration {d:.0f}h ({d/24:.1f}d)")
