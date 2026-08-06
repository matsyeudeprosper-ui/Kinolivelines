"""How much does the ARBITRARY start bar move the answer?

Two baseline runs an hour apart returned $529.88 and $785.61 on nearly the same
number of trades. The only thing that changed is where the 80,000-bar window
begins - and the brick series is anchored on the first bar's open, so shifting
the start shifts every brick boundary for the next 278 days.

If that alone swings the result by hundreds of dollars, then every session,
brick and take-profit comparison in this project is being read against a noise
floor nobody has measured. This measures it.

Same strategy, same data, same everything - only the first bar moves.
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


def run(a):
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    tp, sl = BRICK * TPB, BRICK * SLB
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None
    peak = START; mdd = 0.0; lo = START; eq = START
    opened = 0
    for j in range(N):
        if pending is not None:
            L = pending
            ent = np.append(ent, o[j] + SPREAD if L else o[j])
            lng = np.append(lng, L); opened += 1; pending = None
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
                if ((len(ent) == 0) or (rec and len(ent) <= CAP)) and j + 1 < N:
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
        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        if eq <= 0:
            return dict(eq=0.0, opened=opened, dead=True)
    return dict(eq=eq, opened=opened, dead=False)


print("SAME strategy, SAME data. Only the first bar of the series moves.\n")
print(f"{'start offset':<16}{'bars':>8}{'positions':>11}{'final':>13}")
res = []
for a in (0, 1, 2, 3, 6, 12, 24, 36, 48, 72, 96, 144, 288):
    z = run(a)
    res.append(z["eq"])
    print(f"{f'+{a} bars ({a*5}m)':<16}{len(R)-a:>8}{z['opened']:>11}"
          f"{('DIED' if z['dead'] else '$%,.2f' % z['eq'] if False else ('DIED' if z['dead'] else '$%.2f' % z['eq'])):>13}")
res = np.array(res)
print(f"\nspread across a 1-day shift in start bar:")
print(f"  min ${res.min():.2f}   max ${res.max():.2f}   "
      f"range ${res.max()-res.min():.2f}")
print(f"  mean ${res.mean():.2f}   std ${res.std(ddof=1):.2f}")
print(f"\n*** Any comparison smaller than about ${2*res.std(ddof=1):.0f} "
      f"(2 std) is inside this noise. ***")
