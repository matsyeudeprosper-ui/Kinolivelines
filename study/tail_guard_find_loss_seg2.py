"""Identify the exact losing trade(s) in segment 2 (2023-07-17 to 2024-04-24,
the only real loss among the 5 anchors: 18 trades, 1 loss, ended $750.40)
and show what the segment looks like with that trade removed.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
TP_PTS = 100.0
FROM = datetime(2022, 1, 1)


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


def worst_adverse_distribution(o, h, l, c, N, sigs, window=2000):
    vals = []
    for j, dirn in sigs.items():
        if j + 1 >= N:
            continue
        ent_bar = j + 1; SP = c[j] * SPCT; L = (dirn == 1)
        entry = o[ent_bar] + SP if L else o[ent_bar]
        end = min(N, ent_bar + window)
        worst = 0.0
        for k in range(ent_bar, end):
            adv = (entry - l[k]) if L else (h[k] - entry)
            if adv > worst:
                worst = adv
        vals.append(worst)
    return np.array(vals)


mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]; N = len(c)

NSEG = 6
bounds = [int(N * i / NSEG) for i in range(NSEG + 1)]
i = 2  # segment 2
cal_end = bounds[i]
test_start, test_end = bounds[i], bounds[i + 1]

oc, hc, lc, cc = o[:cal_end], h[:cal_end], l[:cal_end], c[:cal_end]
sigc = signals_reversal(oc, hc, lc, cc, cal_end)
dist = worst_adverse_distribution(oc, hc, lc, cc, cal_end, sigc)
SL_USD = np.percentile(dist, 99) * PT
SL_PTS = SL_USD / PT
print(f"seg2 calibrated SL: ${SL_USD:.2f} ({SL_PTS:.0f} pts)")

ot, ht, lt, ct, tmt = o[test_start:test_end], h[test_start:test_end], l[test_start:test_end], c[test_start:test_end], tm[test_start:test_end]
Nt = test_end - test_start
sigt = signals_reversal(ot, ht, lt, ct, Nt)

pending = None; in_pos = False; pos_L = None; pos_entry = None; pos_entry_t = None
trades = []
for j in range(Nt):
    if pending is not None:
        L, entry, et = pending
        in_pos = True; pos_L = L; pos_entry = entry; pos_entry_t = et; pending = None
    if j in sigt and j + 1 < Nt and not in_pos:
        L = (sigt[j] == 1); SP = ct[j] * SPCT
        entry = ot[j + 1] + SP if L else ot[j + 1]
        pending = (L, entry, tmt[j + 1])
    if in_pos:
        tp_price = pos_entry + TP_PTS if pos_L else pos_entry - TP_PTS
        sl_price = pos_entry - SL_PTS if pos_L else pos_entry + SL_PTS
        hit_tp = (ht[j] >= tp_price) if pos_L else (lt[j] <= tp_price)
        hit_sl = (lt[j] <= sl_price) if pos_L else (ht[j] >= sl_price)
        if hit_tp or hit_sl:
            outcome = "LOSS" if hit_sl else "WIN"
            pnl = -SL_PTS * PT if hit_sl else TP_PTS * PT
            dur_h = (tmt[j] - pos_entry_t) / 3600
            trades.append(dict(side="BUY" if pos_L else "SELL", entry_t=pos_entry_t, exit_t=tmt[j],
                                dur_h=dur_h, outcome=outcome, pnl=pnl))
            in_pos = False

print(f"\ntotal trades in seg2: {len(trades)}\n")
for t in trades:
    et = datetime.utcfromtimestamp(t["entry_t"]).strftime("%Y-%m-%d %H:%M")
    xt = datetime.utcfromtimestamp(t["exit_t"]).strftime("%Y-%m-%d %H:%M")
    flag = "  <<<< THE LOSS" if t["outcome"] == "LOSS" else ""
    print(f"  {t['side']:4}  entry {et}  exit {xt}  dur {t['dur_h']:6.1f}h  {t['outcome']:4}  ${t['pnl']:+8.2f}{flag}")

total_with = sum(t["pnl"] for t in trades)
total_without = sum(t["pnl"] for t in trades if t["outcome"] != "LOSS")
n_losses = sum(1 for t in trades if t["outcome"] == "LOSS")
print(f"\nWITH the loss(es):    net ${total_with:+.2f}  ({len(trades)} trades, {n_losses} loss)")
print(f"WITHOUT the loss(es): net ${total_without:+.2f}  ({len(trades)-n_losses} trades, 0 losses)")
print(f"\n(removing it after the fact is hindsight bias - there was nothing")
print(f"visible BEFORE this trade that marked it different from the 17 winners)")
