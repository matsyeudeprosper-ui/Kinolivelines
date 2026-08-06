"""Cap at 3 positions instead of 4 - paired across anchors.

A tighter cap cuts the basket short: more cap hits, but each one smaller because
fewer positions are open when it fires. Which way that nets out is the question.

Paired across brick anchors, because a one-bar shift in where the series starts
swings a single run by up to $240. Only differences that hold on nearly every
anchor count.

M1, the timeframe the live bot actually runs on.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = 10.0
BRICK, REV = 50.0, 2
TPB, SLB, PT, START = 5, 3, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
mt5.shutdown()
days = (R["time"][-1] - R["time"][0]) / 86400
mon = days / 30.4
print(f"M1 {len(R)} bars, {days:.0f} days ({mon:.1f} months)\n")


def run(a, cap):
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c); tp, sl = BRICK * TPB, BRICK * SLB
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None; incyc = False
    peak = START; mdd = 0.0; lo = START; eq = START
    by = {"tp": [], "rec": [], "cap": []}
    for j in range(N):
        if pending is not None:
            L = pending
            if len(ent) == 0: incyc = True
            ent = np.append(ent, o[j] + SPREAD if L else o[j])
            lng = np.append(lng, L); pending = None
        ci = c[j]
        while True:
            u = (ao if d == -1 else ac) + BRICK * (REV if d == -1 else 1)
            n = (ao if d == 1 else ac) - BRICK * (REV if d == 1 else 1)
            if ci >= u:
                base = ao if d == -1 else ac; ao, ac, d = base, base + BRICK, 1
            elif ci <= n:
                base = ao if d == 1 else ac; ao, ac, d = base, base - BRICK, -1
            else:
                break
            if pd_ and d != pd_ and pending is None:
                if ((len(ent) == 0) or (rec and len(ent) <= cap)) and j + 1 < N:
                    pending = (d == 1)
            pd_ = d
        if len(ent):
            hit = np.where(lng, h[j] >= ent + tp, l[j] <= ent - tp - SPREAD)
            if hit.any():
                bal += float(hit.sum()) * tp * PT
                ent, lng = ent[~hit], lng[~hit]
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - sl, h[j] >= ent + sl + SPREAD).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j]-ent, ent-c[j]-SPREAD)) * PT) if len(ent) else 0.0
        eq = bal + flo
        closed = None
        if rec and len(ent) and eq >= cyc:
            closed = "rec"
        elif len(ent) > cap:
            closed = "cap"
        if closed:
            by[closed].append(eq - cyc); incyc = False; bal = eq
            ent = np.empty(0); lng = np.empty(0, dtype=bool); eq = bal
        if len(ent) == 0:
            if incyc and closed is None:
                by["tp"].append(bal - cyc); incyc = False
            rec = False; cyc = bal
        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        if eq <= 0:
            return dict(eq=0.0, mdd=mdd, lo=0.0, by=by, dead=True)
    return dict(eq=eq, mdd=mdd, lo=lo, by=by, dead=False)


ANCH = [0, 1, 3, 7, 15, 31, 60, 120]
ref = np.array([run(a, 4)["eq"] for a in ANCH])
print(f"{'cap':<6}{'mean final':>12}{'vs cap 4':>11}{'2SE':>8}{'better on':>11}"
      f"{'caps/mo':>10}{'avg cap':>10}{'drawdown':>11}")
for cap in (2, 3, 4, 5, 6):
    out = [run(a, cap) for a in ANCH]
    got = np.array([x["eq"] for x in out])
    dd = got - ref
    se = 2 * dd.std(ddof=1) / np.sqrt(len(dd)) if cap != 4 else 0.0
    ncap = np.mean([len(x["by"]["cap"]) for x in out])
    acap = np.mean([np.mean(x["by"]["cap"]) if x["by"]["cap"] else 0 for x in out])
    mdd = np.mean([x["mdd"] for x in out])
    print(f"{cap:<6}{got.mean():>12.2f}{dd.mean():>+11.2f}{se:>8.2f}"
          f"{f'{int((dd>0).sum())}/{len(dd)}':>11}{ncap/mon:>10.1f}"
          f"{acap:>10.2f}{mdd:>11.2f}")
print("\n  cap 4 is what runs live.")
