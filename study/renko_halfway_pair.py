"""Close the FIRST and SECOND position when price reaches their halfway point.

WHAT "HALFWAY" MEANS HERE
Two same-size positions in the same direction, opened at 100 and 90. Their
midpoint is 95. At 95 the first is -5 and the second is +5: they cancel. So
"price meets them halfway" is exactly "the pair sums to zero", and with the
spread charged it is "the pair sums to >= 0".

HOW THIS DIFFERS FROM THE PAIRING ALREADY TESTED
That one was greedy - biggest winner retires the biggest loser it can cover,
anywhere in the basket. This one pairs the two OLDEST positions specifically:
the original trade and the first add. In an averaging-down basket the oldest is
always the worst and the next is the one closest to rescuing it, so the pairing
is positional rather than opportunistic.

ARMS (all with same-direction adds, which is what is running live)
  same                    no pairing
  same + oldest pair      first and second close together at their midpoint
  same + greedy pair      the previously tested version, for comparison

Both windows again: M1 where the direction rule was found, M15 where it failed.
"""
import numpy as np
import MetaTrader5 as mt5

SPREAD = 10.0
BRICK, REV = 50.0, 2
TP, SL, CAP, PT, START = 250.0, 150.0, 4, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
DATA = {"M1": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000),
        "M15": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)}
mt5.shutdown()


def run(R, a, same, pair):
    """pair: None | 'oldest' | 'greedy'"""
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None; cyc_dir = None
    caps = 0; pairs = 0; eq = START; peak = START; mdd = 0.0
    for j in range(N):
        if pending is not None:
            L = pending
            if len(ent) == 0:
                cyc_dir = L
            ent = np.append(ent, o[j] + SPREAD if L else o[j])
            lng = np.append(lng, L); pending = None
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
                elif rec and len(ent) <= CAP:
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
        if pair and len(ent) >= 2:
            while len(ent) >= 2:
                p = np.where(lng, c[j] - ent, ent - c[j] - SPREAD) * PT
                if pair == "oldest":
                    # positions are held in the order they were opened
                    if p[0] + p[1] >= 0:
                        bal += p[0] + p[1]
                        ent, lng = ent[2:], lng[2:]
                        pairs += 1
                        continue
                    break
                else:
                    wi = np.flatnonzero(p > 0); li = np.flatnonzero(p < 0)
                    if len(wi) == 0 or len(li) == 0:
                        break
                    w = wi[np.argmax(p[wi])]
                    cand = li[p[li] + p[w] >= 0]
                    if len(cand) == 0:
                        break
                    lz = cand[np.argmin(p[cand])]
                    bal += p[w] + p[lz]
                    keep = np.ones(len(ent), dtype=bool); keep[[w, lz]] = False
                    ent, lng = ent[keep], lng[keep]
                    pairs += 1
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - SL, h[j] >= ent + SL + SPREAD).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j]-ent, ent-c[j]-SPREAD)) * PT) if len(ent) else 0.0
        eq = bal + flo
        closed = None
        if rec and len(ent) and eq >= cyc:
            closed = 1
        elif len(ent) > CAP:
            closed = 1; caps += 1
        if closed:
            bal = eq; ent = np.empty(0); lng = np.empty(0, dtype=bool); eq = bal
        if len(ent) == 0:
            rec = False; cyc = bal; cyc_dir = None
        peak = max(peak, eq); mdd = max(mdd, peak - eq)
        if eq <= 0:
            return dict(eq=0.0, caps=caps, pairs=pairs, mdd=mdd)
    return dict(eq=eq, caps=caps, pairs=pairs, mdd=mdd)


ANCH = [0, 3, 9, 21, 45, 90]
for tf in ("M1", "M15"):
    R = DATA[tf]
    mon = (R["time"][-1] - R["time"][0]) / 86400 / 30.4
    tag = "rule was FOUND here" if tf == "M1" else "CLEAN window"
    print("=" * 76)
    print(f"{tf}   {mon:.1f} months   ({tag})")
    print("=" * 76)
    ref = np.array([run(R, a, True, None)["eq"] for a in ANCH])
    print(f"{'arm':<26}{'mean final':>12}{'vs same':>10}{'2SE':>8}{'better':>8}"
          f"{'pairs/mo':>10}{'caps/mo':>9}")
    for same, pair, nm in ((True, None, "same, no pairing"),
                           (True, "oldest", "same + HALFWAY (1st&2nd)"),
                           (True, "greedy", "same + greedy pairing")):
        out = [run(R, a, same, pair) for a in ANCH]
        eqs = np.array([x["eq"] for x in out]); dd = eqs - ref
        se = 2 * dd.std(ddof=1) / np.sqrt(len(dd)) if pair else 0.0
        print(f"{nm:<26}{eqs.mean():>12.2f}{dd.mean():>+10.2f}{se:>8.2f}"
              f"{(f'{int((dd>0).sum())}/{len(dd)}' if pair else '-'):>8}"
              f"{np.mean([x['pairs'] for x in out])/mon:>10.0f}"
              f"{np.mean([x['caps'] for x in out])/mon:>9.1f}")
    print()
