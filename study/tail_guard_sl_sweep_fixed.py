"""How many real losses does a FIXED SL produce across all 5 validated
periods, and is there a wider fixed SL that avoids all of them entirely?
TP fixed at 100pts ($1 at 0.01 lots). Sweep SL from $444.39 upward.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

PCT, SPCT = 50.0 / 64000.0, 10.0 / 64000.0
REV, PT = 2, 0.01
TP_PTS = 100.0
FROM = datetime(2022, 1, 1)


def signals_reversal(o, h, l, c, N):
    revs = {}
    ao = ac = float(o[0])
    d = 0
    pd_ = 0
    for i in range(N):
        B = c[i] * PCT
        while True:
            up = (ao if d == -1 else ac) + B * (REV if d == -1 else 1)
            dn = (ao if d == 1 else ac) - B * (REV if d == 1 else 1)
            if c[i] >= up:
                base = ao if d == -1 else ac
                ao, ac, d = base, base + B, 1
            elif c[i] <= dn:
                base = ao if d == 1 else ac
                ao, ac, d = base, base - B, -1
            else:
                break
            if pd_ and d != pd_:
                revs.setdefault(i, d)
            pd_ = d
    return revs


def run(o, h, l, c, N, sigs, SL_PTS, TP_PTS):
    bal = 1000.0
    lo = bal
    wins = losses = 0
    for j in range(N):
        pass
    pending = None
    in_pos = False
    pos_L = None
    pos_entry = None
    for j in range(N):
        if pending is not None:
            L, entry = pending
            in_pos = True
            pos_L = L
            pos_entry = entry
            pending = None
        if j in sigs and j + 1 < N and not in_pos:
            L = (sigs[j] == 1)
            SP = c[j] * SPCT
            entry = o[j + 1] + SP if L else o[j + 1]
            pending = (L, entry)
        if in_pos:
            tp_price = pos_entry + TP_PTS if pos_L else pos_entry - TP_PTS
            sl_price = pos_entry - SL_PTS if pos_L else pos_entry + SL_PTS
            hit_tp = (h[j] >= tp_price) if pos_L else (l[j] <= tp_price)
            hit_sl = (l[j] <= sl_price) if pos_L else (h[j] >= sl_price)
            if hit_tp and hit_sl:
                bal -= SL_PTS * PT
                losses += 1
                in_pos = False
            elif hit_tp:
                bal += TP_PTS * PT
                wins += 1
                in_pos = False
            elif hit_sl:
                bal -= SL_PTS * PT
                losses += 1
                in_pos = False
        lo = min(lo, bal)
        if bal <= 0:
            return dict(dead=True, losses=losses, wins=wins, end=bal, lo=lo)
    return dict(dead=False, losses=losses, wins=wins, end=bal, lo=lo,
                trades=wins + losses)


mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
r = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
keep = r["time"] >= FROM.timestamp()
r = r[keep]
o, h, l, c = (r[k].astype(float) for k in ("open", "high", "low", "close"))
tm = r["time"]
N = len(c)
NSEG = 6
bounds = [int(N * i / NSEG) for i in range(NSEG + 1)]

for SL_USD in (444.39, 500, 550, 600, 650, 700, 800, 900, 1000):
    SL_PTS = SL_USD / PT
    total_losses = 0
    total_trades = 0
    seg_losses = []
    for i in range(1, NSEG):
        test_start, test_end = bounds[i], bounds[i + 1]
        ot, ht, lt, ct = o[test_start:test_end], h[test_start:test_end], l[test_start:test_end], c[test_start:test_end]
        Nt = test_end - test_start
        sigt = signals_reversal(ot, ht, lt, ct, Nt)
        z = run(ot, ht, lt, ct, Nt, sigt, SL_PTS, TP_PTS)
        total_losses += z["losses"]
        total_trades += z.get("trades", z["losses"] + z["wins"])
        seg_losses.append(z["losses"])
    print("SL $%7.2f  ->  losses per segment %s  total losses %d / %d trades" % (
        SL_USD, seg_losses, total_losses, total_trades))
