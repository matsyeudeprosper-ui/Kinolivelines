"""Does "add less often in recovery" hold on M5 and H1, not just M1?

On M1 (56 days) every rule that halves recovery adds gained $90-$145 on 8 of 8
brick anchors. That is the strongest thing found in this project. But "fewer
trades helps" is exactly what a losing strategy shows on a short window, so it
has to survive longer samples before it means anything.

Same fixed 50-point brick and 10-point spread on all three timeframes, so the
comparison between rules is like-for-like. The absolute equity is not comparable
across timeframes and is not the point.

RULES
  any        every reversal is added (current bot)
  same       only adds in the first position's direction
  opposite   only adds against it
  random     skip a random share at the same rate - the control that showed the
             direction rules were not special on M1
"""
import sys
import numpy as np
import MetaTrader5 as mt5

SPREAD = 10.0
BRICK, REV = 50.0, 2
TP, SL, CAP, PT, START = 250.0, 150.0, 4, 0.01, 1000.0

TFS = {"M5": mt5.TIMEFRAME_M5, "H1": mt5.TIMEFRAME_H1}


def load(tf):
    mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
    r = mt5.copy_rates_from_pos("BTCUSDm", TFS[tf], 0, 80000)
    mt5.shutdown()
    if tf == "H1":                      # 2019-20 are daily bars wearing an H1
        import datetime as _dt          # label - trap 16
        r = r[r["time"] >= _dt.datetime(2022, 1, 1).timestamp()]
    return r


def run(R, a, mode, seed=0, keep=0.5):
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    rng = np.random.default_rng(seed)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None; cyc_dir = None
    adds = 0; caps = 0; peak = START; mdd = 0.0; eq = START
    for j in range(N):
        if pending is not None:
            L = pending
            if len(ent) == 0:
                cyc_dir = L
            else:
                adds += 1
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
                want = (d == 1)
                if len(ent) == 0:
                    ok = True
                elif rec and len(ent) <= CAP:
                    if mode == "same":       ok = (want == cyc_dir)
                    elif mode == "opposite": ok = (want != cyc_dir)
                    elif mode == "random":   ok = bool(rng.random() < keep)
                    else:                    ok = True
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
            return dict(eq=0.0, adds=adds, caps=caps, mdd=mdd, dead=True)
    return dict(eq=eq, adds=adds, caps=caps, mdd=mdd, dead=False)


ANCH = [0, 2, 6, 14, 30, 60]
for tf in ("M5", "H1"):
    R = load(tf)
    mon = (R["time"][-1] - R["time"][0]) / 86400 / 30.4
    print("=" * 74)
    print(f"{tf}   {len(R)} bars   {mon:.1f} months")
    print("=" * 74)
    ref = [run(R, a, "any") for a in ANCH]
    refeq = np.array([x["eq"] for x in ref])
    print(f"{'rule':<22}{'mean final':>12}{'vs current':>12}{'2SE':>8}{'better':>8}"
          f"{'adds/mo':>9}{'caps/mo':>9}{'drawdn':>9}")
    print(f"{'any (current)':<22}{refeq.mean():>12.2f}{0.0:>+12.2f}{0.0:>8.2f}{'-':>8}"
          f"{np.mean([x['adds'] for x in ref])/mon:>9.0f}"
          f"{np.mean([x['caps'] for x in ref])/mon:>9.1f}"
          f"{np.mean([x['mdd'] for x in ref]):>9.2f}")
    for mode in ("same", "opposite"):
        out = [run(R, a, mode) for a in ANCH]
        eqs = np.array([x["eq"] for x in out]); dd = eqs - refeq
        se = 2 * dd.std(ddof=1) / np.sqrt(len(dd))
        print(f"{mode:<22}{eqs.mean():>12.2f}{dd.mean():>+12.2f}{se:>8.2f}"
              f"{f'{int((dd>0).sum())}/{len(dd)}':>8}"
              f"{np.mean([x['adds'] for x in out])/mon:>9.0f}"
              f"{np.mean([x['caps'] for x in out])/mon:>9.1f}"
              f"{np.mean([x['mdd'] for x in out]):>9.2f}")
    rs = []
    for s_ in range(4):
        out = [run(R, a, "random", seed=500 + s_, keep=0.5) for a in ANCH]
        eqs = np.array([x["eq"] for x in out]); dd = eqs - refeq
        rs.append(dd.mean())
        print(f"{'random skip #' + str(s_+1):<22}{eqs.mean():>12.2f}{dd.mean():>+12.2f}"
              f"{'':>8}{f'{int((dd>0).sum())}/{len(dd)}':>8}"
              f"{np.mean([x['adds'] for x in out])/mon:>9.0f}"
              f"{np.mean([x['caps'] for x in out])/mon:>9.1f}"
              f"{np.mean([x['mdd'] for x in out]):>9.2f}")
    rs = np.array(rs)
    print(f"\n  random skipping: mean {rs.mean():+.2f}, best {rs.max():+.2f}")
    print()
