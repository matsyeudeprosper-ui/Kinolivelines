"""Is "same direction" real, or just "add less often"?

Same-direction and opposite-direction gained the SAME amount (+$120 vs +$123),
which is the signature of a rule whose benefit comes from how many trades it
removes rather than which ones. Both cut recovery adds from 340/month to ~215.

So: skip a RANDOM share of recovery adds at the same rate, with no direction rule
at all. If random skipping matches the gain, direction is doing nothing.

M1, paired across the same brick anchors.
"""
import numpy as np
import MetaTrader5 as mt5

SPREAD = 10.0
BRICK, REV = 50.0, 2
TP, SL, CAP, PT, START = 250.0, 150.0, 4, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000)
mt5.shutdown()
mon = (R["time"][-1] - R["time"][0]) / 86400 / 30.4


def run(a, mode, seed=0, keep=0.63):
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    rng = np.random.default_rng(seed)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None; cyc_dir = None
    adds = 0; caps = 0
    eq = START
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
        if eq <= 0:
            return dict(eq=0.0, adds=adds, caps=caps)
    return dict(eq=eq, adds=adds, caps=caps)


ANCH = [0, 1, 3, 7, 15, 31, 60, 120]
ref = np.array([run(a, "any")["eq"] for a in ANCH])
print("CONTROL - skip a RANDOM share of recovery adds, no direction rule\n")
print(f"{'rule':<24}{'vs current':>12}{'adds/mo':>9}{'caps/mo':>9}")

sm = [run(a, "same") for a in ANCH]
sd = np.array([x["eq"] for x in sm]) - ref
print(f"{'SAME direction (yours)':<24}{sd.mean():>+12.2f}"
      f"{np.mean([x['adds'] for x in sm])/mon:>9.0f}"
      f"{np.mean([x['caps'] for x in sm])/mon:>9.1f}")

op = [run(a, "opposite") for a in ANCH]
od = np.array([x["eq"] for x in op]) - ref
print(f"{'opposite direction':<24}{od.mean():>+12.2f}"
      f"{np.mean([x['adds'] for x in op])/mon:>9.0f}"
      f"{np.mean([x['caps'] for x in op])/mon:>9.1f}")
print()

got = []
for s_ in range(6):
    o_ = [run(a, "random", seed=1000 + s_) for a in ANCH]
    dd = np.array([x["eq"] for x in o_]) - ref
    got.append(dd.mean())
    print(f"{'random skip #' + str(s_ + 1):<24}{dd.mean():>+12.2f}"
          f"{np.mean([x['adds'] for x in o_])/mon:>9.0f}"
          f"{np.mean([x['caps'] for x in o_])/mon:>9.1f}")

got = np.array(got)
print()
print(f"random skipping : mean {got.mean():+.2f}   best {got.max():+.2f}   "
      f"std {got.std(ddof=1):.2f}")
print(f"your rule       : {sd.mean():+.2f}")
if got.max() >= sd.mean() * 0.75:
    print("\n  -> random skipping MATCHES it. The gain is fewer adds, not direction.")
else:
    print("\n  -> your rule STANDS APART from random skipping at the same rate.")
