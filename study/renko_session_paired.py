"""Session windows, tested PAIRED across many brick anchors.

The anchor test showed a 1-bar shift in where the series starts swings the final
equity by up to $240, with a std of $119 - so a single-anchor comparison cannot
resolve anything smaller than about $237.

The fix is pairing. Run baseline and blocked on the SAME anchor, take the
difference, then repeat over many anchors. Whatever the anchor does to the
brick series it does to both arms, so it largely cancels. What survives is the
session effect.

A window is only interesting if the difference is positive on MOST anchors, not
just on average - a mean dragged up by one lucky anchor is the same trap again.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = 10.0
BRICK, REV = 50.0, 2
TPB, SLB, CAP, PT, START = 5, 3, 4, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000)
mt5.shutdown()
HOUR = np.array([datetime.utcfromtimestamp(t).hour for t in R["time"]])


def run(a, block):
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    hour = HOUR[a:]; N = len(c)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    tp, sl = BRICK * TPB, BRICK * SLB
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None
    eq = START
    for j in range(N):
        if pending is not None:
            L = pending
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
                ok = (len(ent) == 0) or (rec and len(ent) <= CAP)
                if len(ent) == 0 and hour[j] in block:
                    ok = False
                if ok and j + 1 < N:
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
        out = None
        if rec and len(ent) and eq >= cyc:
            out = 1
        elif len(ent) > CAP:
            out = 1
        if out:
            bal = eq; ent = np.empty(0); lng = np.empty(0, dtype=bool); eq = bal
        if len(ent) == 0:
            rec = False; cyc = bal
        if eq <= 0:
            return 0.0
    return eq


ANCH = [0, 1, 2, 3, 5, 8, 12, 18, 24, 36, 48, 60, 72, 96, 120, 144, 200, 288]
wins = {
    "London 07-16":      set(range(7, 16)),
    "New York 12-21":    set(range(12, 21)),
    "London+NY 07-21":   set(range(7, 21)),
    "overlap 12-16":     set(range(12, 16)),
    "afternoon 12-22":   set(range(12, 22)),
    "Asia 00-08":        set(range(0, 8)),
}
print(f"paired over {len(ANCH)} brick anchors\n")
base = np.array([run(a, set()) for a in ANCH])
print(f"baseline across anchors: mean ${base.mean():.2f}, "
      f"min ${base.min():.2f}, max ${base.max():.2f}\n")
print(f"{'blocked window':<20}{'mean diff':>12}{'2SE':>9}{'better on':>12}{'verdict':>12}")
for nm, w in wins.items():
    got = np.array([run(a, w) for a in ANCH])
    d = got - base
    se = 2 * d.std(ddof=1) / np.sqrt(len(d))
    better = int((d > 0).sum())
    ok = (abs(d.mean()) > se) and (better >= len(d) - 3 or better <= 3)
    print(f"{nm:<20}{d.mean():>+12.2f}{se:>9.2f}{f'{better}/{len(d)}':>12}"
          f"{('REAL' if ok else 'noise'):>12}")
print("\n  'better on' = anchors where blocking beat trading all hours.")
print("  A real effect should win on nearly all of them, not just on average.")
