"""In recovery, only add trades in the SAME direction as the first one.

CURRENT: every reversal is added, whichever way it points. That is what produced
the live basket of 2 SELLs + 2 BUYs all losing at once - price sat between them
and every leg was on the wrong side.

TESTED HERE
  same      only add in the first position's direction (averaging down)
  any       current behaviour
  opposite  only add AGAINST the first position (hedging) - included as the
            obvious alternative, so "same is better" cannot just mean
            "fewer trades is better"

Fewer adds is itself a change, so trade counts are reported next to the money.

M1, paired across brick anchors, 2SE from the paired differences.
"""
import numpy as np
import MetaTrader5 as mt5

SPREAD = 10.0
BRICK, REV = 50.0, 2
TP, SL, CAP, PT, START = 250.0, 150.0, 4, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
mt5.shutdown()
days = (R["time"][-1] - R["time"][0]) / 86400
mon = days / 30.4
print(f"M1, {days:.0f} days ({mon:.1f} months)\n")


def run(a, mode, seed=0, keep=0.63):
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    rng = np.random.default_rng(seed)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None; incyc = False
    cyc_dir = None                      # direction of the FIRST position
    peak = START; mdd = 0.0; lo = START; eq = START
    opened = 0; adds = 0; skipped = 0; caps = 0; maxpos = 0; wf = 0.0
    for j in range(N):
        if pending is not None:
            L = pending
            if len(ent) == 0:
                incyc = True; cyc_dir = L
            else:
                adds += 1
            ent = np.append(ent, o[j] + SPREAD if L else o[j])
            lng = np.append(lng, L); pending = None
            opened += 1; maxpos = max(maxpos, len(ent))
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
                want = (d == 1)
                if len(ent) == 0:
                    ok = True
                elif rec and len(ent) <= CAP:
                    if mode == "same":       ok = (want == cyc_dir)
                    elif mode == "opposite": ok = (want != cyc_dir)
                    elif mode == "random":   ok = (rng.random() < keep)
                    else:                    ok = True
                    if not ok:
                        skipped += 1
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
        wf = min(wf, flo)
        eq = bal + flo
        closed = None
        if rec and len(ent) and eq >= cyc:
            closed = 1
        elif len(ent) > CAP:
            closed = 1; caps += 1
        if closed:
            bal = eq; incyc = False
            ent = np.empty(0); lng = np.empty(0, dtype=bool); eq = bal
        if len(ent) == 0:
            incyc = False; rec = False; cyc = bal; cyc_dir = None
        peak = max(peak, eq); mdd = max(mdd, peak - eq); lo = min(lo, eq)
        if eq <= 0:
            return dict(eq=0.0, dead=True, opened=opened, adds=adds, skipped=skipped,
                        caps=caps, maxpos=maxpos, wf=wf, mdd=mdd, lo=0.0)
    return dict(eq=eq, dead=False, opened=opened, adds=adds, skipped=skipped,
                caps=caps, maxpos=maxpos, wf=wf, mdd=mdd, lo=lo)


ANCH = [0, 1, 3, 7, 15, 31, 60, 120]
ref = np.array([run(a, "any")["eq"] for a in ANCH])
same = np.array([run(a, "same")["eq"] for a in ANCH]) - ref
print("CONTROL: skip a RANDOM share of recovery adds, no direction rule at all
")
print(f"{'rule':<26}{'vs current':>12}{'adds/mo':>9}{'caps/mo':>9}")
print(f"{'SAME direction (yours)':<26}{same.mean():>+12.2f}"
      f"{np.mean([run(a,'same')['adds'] for a in ANCH])/mon:>9.0f}"
      f"{np.mean([run(a,'same')['caps'] for a in ANCH])/mon:>9.1f}")
outs = []
for sd in range(6):
    o_ = [run(a, "random", seed=1000+sd) for a in ANCH]
    dd = np.array([x["eq"] for x in o_]) - ref
    outs.append(dd.mean())
    print(f"{'random skip #'+str(sd+1):<26}{dd.mean():>+12.2f}"
          f"{np.mean([x['adds'] for x in o_])/mon:>9.0f}"
          f"{np.mean([x['caps'] for x in o_])/mon:>9.1f}")
outs = np.array(outs)
print(f"
  random skipping: mean {outs.mean():+.2f}, best {outs.max():+.2f}, "
      f"std {outs.std(ddof=1):.2f}")
print(f"  your rule {same.mean():+.2f}  ->  "
      f"{'MATCHED by random skipping - the gain is fewer adds, not direction' if outs.max() >= same.mean()*0.75 else 'STANDS APART from random skipping'}")
