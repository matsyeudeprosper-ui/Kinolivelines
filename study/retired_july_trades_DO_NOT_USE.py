"""Every trade the hedge strategy would have taken in July 2026, one per line.

Simulated on M1 - the live bot only started today, so there is no real July
history to show. Same engine as everything else, no trail (the trail version
stops on 1 July and takes nothing else all month, so there would be one row).

Columns: when it opened, first trade or hedge, direction, entry, when it closed,
why it closed, and the money.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD, BRICK, REV = 10.0, 50.0, 2
TP, TRIG, PT, START = 250.0, 150.0, 0.01, 1000.0
REWARD, HRISK = 1.5, 1.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
mt5.shutdown()
o, h, l, c = (R[k].astype(float) for k in ("open", "high", "low", "close"))
tm = R["time"]; N = len(c)

ao = ac = float(o[0]); d = 0; pd_ = 0
bal = START
f = None      # dict: px, long, t
hg = None
rec = False; pending = None
trades = []


def rec_trade(kind, side, px, tin, tout, why, pnl):
    trades.append(dict(kind=kind, side=side, px=px, tin=tin, tout=tout,
                       why=why, pnl=pnl))


for j in range(N):
    if pending is not None:
        kind, L, ptp, psl = pending
        px = o[j] + SPREAD if L else o[j]
        if kind == "first":
            f = dict(px=px, long=L, t=tm[j], tp=TP, sl=0.0)
        else:
            hg = dict(px=px, long=L, t=tm[j], tp=ptp, sl=psl)
        pending = None
    ci = c[j]
    while True:
        u = (ao if d == -1 else ac) + BRICK * (REV if d == -1 else 1)
        n_ = (ao if d == 1 else ac) - BRICK * (REV if d == 1 else 1)
        if ci >= u:
            base = ao if d == -1 else ac; ao, ac, d = base, base + BRICK, 1
        elif ci <= n_:
            base = ao if d == 1 else ac; ao, ac, d = base, base - BRICK, -1
        else:
            break
        if pd_ and d != pd_ and pending is None and j + 1 < N:
            want = (d == 1)
            if f is None and hg is None:
                pending = ("first", want, TP, 0.0)
            elif rec and hg is None and f is not None and want != f["long"]:
                dn = max(((f["px"] - c[j]) if f["long"] else (c[j] - f["px"])), BRICK)
                pending = ("hedge", want, REWARD * dn, HRISK * dn)
        pd_ = d

    # first trade target
    if f is not None:
        if (h[j] >= f["px"] + TP) if f["long"] else (l[j] <= f["px"] - TP - SPREAD):
            bal += TP * PT
            rec_trade("first", "BUY" if f["long"] else "SELL", f["px"], f["t"],
                      tm[j], "target", TP * PT)
            f = None
            if hg is None:
                rec = False
    # hedge
    if hg is not None:
        hitT = (h[j] >= hg["px"] + hg["tp"]) if hg["long"] else (l[j] <= hg["px"] - hg["tp"] - SPREAD)
        hitS = (l[j] <= hg["px"] - hg["sl"]) if hg["long"] else (h[j] >= hg["px"] + hg["sl"] + SPREAD)
        if hitS:
            bal -= hg["sl"] * PT
            rec_trade("hedge", "BUY" if hg["long"] else "SELL", hg["px"], hg["t"],
                      tm[j], "STOPPED", -hg["sl"] * PT)
            hg = None
            if f is not None:
                p = ((c[j] - f["px"]) if f["long"] else (f["px"] - c[j] - SPREAD)) * PT
                bal += p
                rec_trade("first", "BUY" if f["long"] else "SELL", f["px"], f["t"],
                          tm[j], "closed with hedge", p)
                f = None
            rec = False
        elif hitT:
            bal += hg["tp"] * PT
            rec_trade("hedge", "BUY" if hg["long"] else "SELL", hg["px"], hg["t"],
                      tm[j], "target", hg["tp"] * PT)
            hg = None
            if f is not None:
                p = ((c[j] - f["px"]) if f["long"] else (f["px"] - c[j] - SPREAD)) * PT
                bal += p
                rec_trade("first", "BUY" if f["long"] else "SELL", f["px"], f["t"],
                          tm[j], "closed with hedge", p)
                f = None
            rec = False
    if f is not None and not rec:
        if (l[j] <= f["px"] - TRIG) if f["long"] else (h[j] >= f["px"] + TRIG + SPREAD):
            rec = True
    # pair back to zero
    if rec and (f is not None or hg is not None):
        flo = 0.0
        if f is not None:
            flo += ((c[j] - f["px"]) if f["long"] else (f["px"] - c[j] - SPREAD)) * PT
        if hg is not None:
            flo += ((c[j] - hg["px"]) if hg["long"] else (hg["px"] - c[j] - SPREAD)) * PT
        if flo >= 0:
            if f is not None:
                p = ((c[j] - f["px"]) if f["long"] else (f["px"] - c[j] - SPREAD)) * PT
                bal += p
                rec_trade("first", "BUY" if f["long"] else "SELL", f["px"], f["t"],
                          tm[j], "back to zero", p); f = None
            if hg is not None:
                p = ((c[j] - hg["px"]) if hg["long"] else (hg["px"] - c[j] - SPREAD)) * PT
                bal += p
                rec_trade("hedge", "BUY" if hg["long"] else "SELL", hg["px"], hg["t"],
                          tm[j], "back to zero", p); hg = None
            rec = False

jul = [t for t in trades
       if datetime.utcfromtimestamp(t["tin"]).strftime("%Y-%m") == "2026-07"]
print(f"JULY 2026 - every trade the hedge strategy would have taken on M1")
print(f"{len(jul)} trades\n")
print(f"{'opened':<17}{'closed':<17}{'type':<7}{'side':<6}{'entry':>10}"
      f"{'why it closed':<20}{'P&L':>8}   run")
run = 0.0
for t in jul:
    run += t["pnl"]
    print(f"{datetime.utcfromtimestamp(t['tin']):%d %b %H:%M}    "
          f"{datetime.utcfromtimestamp(t['tout']):%d %b %H:%M}    "
          f"{t['kind']:<7}{t['side']:<6}{t['px']:>10.2f}"
          f"{t['why']:<20}{t['pnl']:>+8.2f}{run:>+8.2f}")

p = np.array([t["pnl"] for t in jul])
w = p > 0
print()
print(f"  trades      {len(p)}")
print(f"  winners     {int(w.sum())} ({100*w.mean():.0f}%)   total +{p[w].sum():.2f}   avg +{p[w].mean():.2f}")
print(f"  losers      {int((~w).sum())} ({100*(~w).mean():.0f}%)   total {p[~w].sum():.2f}   avg {p[~w].mean():.2f}")
print(f"  NET         {p.sum():+.2f}")
print()
from collections import Counter
print("  by reason:")
for k, n in Counter(t["why"] for t in jul).most_common():
    s = sum(t["pnl"] for t in jul if t["why"] == k)
    print(f"    {k:<22}{n:>4} trades   {s:>+9.2f}")
print()
print("  by hour opened (UTC):")
hh = Counter(datetime.utcfromtimestamp(t["tin"]).hour for t in jul)
for k in sorted(hh):
    s = sum(t["pnl"] for t in jul if datetime.utcfromtimestamp(t["tin"]).hour == k)
    print(f"    {k:02d}:00  {hh[k]:>4} trades   {s:>+9.2f}")
