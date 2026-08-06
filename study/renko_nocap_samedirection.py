"""No cap, but same-direction adds. When does it blow up?

With any-direction adds and no cap the account died on M5 in ~3 months, killed
by a basket that ran to 39 positions and $3,189 underwater.

Same-direction adds are fewer, so the basket grows more slowly - but every
position now points the same way, so there is nothing offsetting anything. This
is textbook averaging down with no limit. Slower to fill, but each position
compounds the same bet.

Reports the death date, how deep it went, and the five worst baskets, on both
M5 and H1.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime

SPREAD = 10.0
BRICK, REV = 50.0, 2
TP, SL, PT, START = 250.0, 150.0, 0.01, 1000.0
NOCAP = 10 ** 9

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
SETS = {}
for tf, name in ((mt5.TIMEFRAME_M5, "M5"), (mt5.TIMEFRAME_H1, "H1")):
    r = mt5.copy_rates_from_pos("BTCUSDm", tf, 0, 80000)
    if name == "H1":
        r = r[r["time"] >= datetime(2022, 1, 1).timestamp()]     # trap 16
    SETS[name] = r
mt5.shutdown()


def run(R, same, cap):
    o, h, l, c = (R[k].astype(float) for k in ("open", "high", "low", "close"))
    tm = R["time"]; N = len(c)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None; cyc_dir = None
    start_j = None; worst = 0.0; maxpos = 0
    baskets = []; dead = None
    eq = START
    for j in range(N):
        if pending is not None:
            L = pending
            if len(ent) == 0:
                cyc_dir = L; start_j = j; worst = 0.0; maxpos = 0
            ent = np.append(ent, o[j] + SPREAD if L else o[j])
            lng = np.append(lng, L); pending = None
            maxpos = max(maxpos, len(ent))
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
            if pd_ and d != pd_ and pending is None:
                want = (d == 1)
                if len(ent) == 0:
                    ok = True
                elif rec and len(ent) <= cap:
                    ok = (want == cyc_dir) if same else True
                else:
                    ok = False
                if ok and j + 1 < N:
                    pending = want
            pd_ = d
        if len(ent):
            hit = np.where(lng, h[j] >= ent + TP, l[j] <= ent - TP - SPREAD)
            if hit.any():
                bal += float(hit.sum()) * TP * PT
                ent, lng = ent[~hit], lng[~hit]
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - SL, h[j] >= ent + SL + SPREAD).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j]-ent, ent-c[j]-SPREAD)) * PT) if len(ent) else 0.0
        worst = min(worst, flo)
        eq = bal + flo
        closed = None
        if rec and len(ent) and eq >= cyc:
            closed = 1
        elif len(ent) > cap:
            closed = 1
        if closed:
            bal = eq; ent = np.empty(0); lng = np.empty(0, dtype=bool); eq = bal
        if len(ent) == 0:
            if start_j is not None:
                baskets.append((start_j, j, -worst, maxpos)); start_j = None
            rec = False; cyc = bal; cyc_dir = None
        if eq <= 0:
            baskets.append((start_j if start_j is not None else j, j, -worst, maxpos))
            dead = j
            break
    return dict(eq=max(eq, 0.0), dead=dead, baskets=baskets, tm=tm)


for name in ("M5", "H1"):
    R = SETS[name]
    span = (R["time"][-1] - R["time"][0]) / 86400
    print("=" * 74)
    print(f"{name}   {datetime.utcfromtimestamp(R['time'][0]):%Y-%m-%d} to "
          f"{datetime.utcfromtimestamp(R['time'][-1]):%Y-%m-%d}   ({span:.0f} days)")
    print("=" * 74)
    for same, nm in ((False, "any direction, NO CAP"), (True, "SAME direction, NO CAP"),
                     (True, None)):
        if nm is None:
            z = run(R, True, 4)
            nm = "SAME direction, cap 4"
        else:
            z = run(R, same, NOCAP)
        b = z["baskets"]; tm = z["tm"]
        if z["dead"] is not None:
            dd = (tm[z["dead"]] - tm[0]) / 86400
            end = f"DIED {datetime.utcfromtimestamp(tm[z['dead']]):%Y-%m-%d} after {dd:.0f} days"
        else:
            end = f"survived, final ${z['eq']:,.2f}"
        deep = sorted(b, key=lambda x: -x[2])[:1]
        mp = max((x[3] for x in b), default=0)
        wd = deep[0][2] if deep else 0
        print(f"  {nm:<26}{end}")
        print(f"  {'':<26}worst basket ${wd:,.2f}, biggest {mp} positions")
    # timeline of the deep ones for same-direction no cap
    z = run(R, True, NOCAP)
    print(f"\n  SAME direction NO CAP - five worst baskets:")
    print(f"  {'started':<13}{'ended':<13}{'days':>6}{'positions':>11}{'deepest':>12}")
    for s, e, dep, mp in sorted(z["baskets"], key=lambda x: -x[2])[:5]:
        print(f"  {datetime.utcfromtimestamp(z['tm'][s]):%Y-%m-%d}   "
              f"{datetime.utcfromtimestamp(z['tm'][e]):%Y-%m-%d}   "
              f"{(z['tm'][e]-z['tm'][s])/86400:>5.1f}{mp:>11}{'$%.2f'%dep:>12}")
    print()
