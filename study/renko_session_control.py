"""Is it "avoid London/NY", or just "trade less"?

Blocking hours on a losing strategy cuts the loss automatically. The London/NY
windows block 9-14 of 24 hours, so a large part of the gain could be nothing
more than doing less of a bad thing.

The control: block a RANDOM set of hours of the SAME SIZE. If random blocks help
just as much, the session finding is an artifact of trade count and nothing else.

Paired across the same brick anchors so the anchor noise cancels.
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
    rec = False; pending = None; eq = START; opened = 0
    for j in range(N):
        if pending is not None:
            L = pending
            ent = np.append(ent, o[j] + SPREAD if L else o[j])
            lng = np.append(lng, L); pending = None; opened += 1
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
            return 0.0, opened
    return eq, opened


ANCH = [0, 5, 24, 96]
base = np.array([run(a, set())[0] for a in ANCH])
print(f"baseline mean ${base.mean():.2f} over {len(ANCH)} anchors\n")

tests = {
    "London+NY 07-21 (14h)": (set(range(7, 21)), 14),
    "afternoon 12-22 (10h)": (set(range(12, 22)), 10),
}
rng = np.random.default_rng(20260805)
for nm, (w, k) in tests.items():
    real = np.array([run(a, w)[0] for a in ANCH])
    dreal = (real - base).mean()
    # 20 random hour-sets of the same size, each paired over the same anchors
    rand = []
    for t in range(12):
        rw = set(rng.choice(24, size=k, replace=False).tolist())
        got = np.array([run(a, rw)[0] for a in ANCH])
        rand.append((got - base).mean())
    rand = np.array(rand)
    beat = int((rand >= dreal).sum())
    print(f"{nm}")
    print(f"   real block   {dreal:+8.2f}")
    print(f"   random {k}h    median {np.median(rand):+8.2f}   best {rand.max():+8.2f}   "
          f"std {rand.std(ddof=1):.2f}")
    print(f"   random matched or beat it in {beat}/12  ->  "
          f"{'NOT distinguishable from just trading less' if beat >= 2 else 'stands apart from random hour-blocks'}")
    print()
