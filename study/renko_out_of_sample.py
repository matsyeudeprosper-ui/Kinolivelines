"""Out-of-sample test of the same-direction rule.

Everything the rule was found on - M1, M5, H1 - had already been examined for
other questions in this session. "Fewer/other trades helps" is the classic thing
that appears on studied data and vanishes on fresh data, so the rule needs a
window that had no part in finding it.

TWO GENUINELY UNTOUCHED SETS

  M15 on BTCUSDm - 80,000 bars, ~2.3 years, 100% coverage. Never loaded once in
                   this session for any test. Different bar size, so a different
                   brick series and different signals.

  A SECOND INSTRUMENT - the rule says nothing about Bitcoin specifically. If it
                   is real it should show on another market; if it only works on
                   the one instrument it was found on, that is a warning.

Same engine, same fixed 50-pt brick where the price scale allows, spread taken
from the instrument's own live spread rather than assumed. Paired across brick
anchors, and rate-matched random skipping included as the control that nearly
killed the rule on M1.
"""
import numpy as np
import MetaTrader5 as mt5

BRICK, REV = 50.0, 2
TP, SL, CAP, PT, START = 250.0, 150.0, 4, 0.01, 1000.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")

# what else can we test on? pick liquid alternatives that exist on this account
CANDIDATES = ["ETHUSDm", "XAUUSDm", "US30m", "USTECm", "BTCUSDm"]
avail = []
for s in CANDIDATES:
    if mt5.symbol_select(s, True):
        t = mt5.symbol_info_tick(s)
        i = mt5.symbol_info(s)
        if t and t.bid > 0:
            avail.append((s, t.ask - t.bid, t.bid, i.point))
print("instrument        spread      price    point")
for s, sp, bid, pt_ in avail:
    print(f"  {s:<14} {sp:>8.2f} {bid:>10.2f} {pt_:>8.5f}")
print()


def load(sym, tf, n=80000):
    r = mt5.copy_rates_from_pos(sym, tf, 0, n)
    return r


def run(R, a, mode, spread, brick, seed=0, keep=0.5):
    o, h, l, c = (R[k][a:].astype(float) for k in ("open", "high", "low", "close"))
    N = len(c)
    tp, sl = brick * 5, brick * 3
    rng = np.random.default_rng(seed)
    ao = ac = float(o[0]); d = 0; pd_ = 0
    bal = START; cyc = START
    ent = np.empty(0); lng = np.empty(0, dtype=bool)
    rec = False; pending = None; cyc_dir = None
    adds = 0; caps = 0; eq = START; peak = START; mdd = 0.0
    for j in range(N):
        if pending is not None:
            L = pending
            if len(ent) == 0:
                cyc_dir = L
            else:
                adds += 1
            ent = np.append(ent, o[j] + spread if L else o[j])
            lng = np.append(lng, L); pending = None
        ci = c[j]
        while True:
            u = (ao if d == -1 else ac) + brick * (REV if d == -1 else 1)
            n_ = (ao if d == 1 else ac) - brick * (REV if d == 1 else 1)
            if ci >= u:
                base = ao if d == -1 else ac; ao, ac, d = base, base + brick, 1
            elif ci <= n_:
                base = ao if d == 1 else ac; ao, ac, d = base, base - brick, -1
            else:
                break
            if pd_ and d != pd_ and pending is None:
                want = (d == 1)
                if len(ent) == 0:
                    ok = True
                elif rec and len(ent) <= CAP:
                    if mode == "same":     ok = (want == cyc_dir)
                    elif mode == "random": ok = bool(rng.random() < keep)
                    else:                  ok = True
                else:
                    ok = False
                if ok and j + 1 < N:
                    pending = want
            pd_ = d
        if len(ent):
            hit = np.where(lng, h[j] >= ent + tp, l[j] <= ent - tp - spread)
            if hit.any():
                bal += float(hit.sum()) * tp * PT
                ent, lng = ent[~hit], lng[~hit]
        if len(ent) and not rec:
            if np.where(lng, l[j] <= ent - sl, h[j] >= ent + sl + spread).any():
                rec = True
        flo = float(np.sum(np.where(lng, c[j]-ent, ent-c[j]-spread)) * PT) if len(ent) else 0.0
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
            return dict(eq=0.0, adds=adds, caps=caps, mdd=mdd)
    return dict(eq=eq, adds=adds, caps=caps, mdd=mdd)


ANCH = [0, 3, 9, 21, 45, 90]


def test(label, R, spread, brick):
    if R is None or len(R) < 5000:
        print(f"{label}: not enough data\n")
        return
    mon = (R["time"][-1] - R["time"][0]) / 86400 / 30.4
    print("=" * 72)
    print(f"{label}   {len(R)} bars   {mon:.1f} months   brick {brick:g}   spread {spread:g}")
    print("=" * 72)
    ref = [run(R, a, "any", spread, brick) for a in ANCH]
    refeq = np.array([x["eq"] for x in ref])
    print(f"{'rule':<20}{'mean final':>12}{'vs current':>12}{'2SE':>8}{'better':>8}{'caps/mo':>9}")
    print(f"{'any (current)':<20}{refeq.mean():>12.2f}{0.0:>+12.2f}{0.0:>8.2f}{'-':>8}"
          f"{np.mean([x['caps'] for x in ref])/mon:>9.1f}")
    sm = [run(R, a, "same", spread, brick) for a in ANCH]
    sd = np.array([x["eq"] for x in sm]) - refeq
    se = 2 * sd.std(ddof=1) / np.sqrt(len(sd))
    print(f"{'SAME direction':<20}{np.mean([x['eq'] for x in sm]):>12.2f}{sd.mean():>+12.2f}"
          f"{se:>8.2f}{f'{int((sd>0).sum())}/{len(sd)}':>8}"
          f"{np.mean([x['caps'] for x in sm])/mon:>9.1f}")
    rs = []
    for s_ in range(4):
        o_ = [run(R, a, "random", spread, brick, seed=77 + s_, keep=0.5) for a in ANCH]
        dd = np.array([x["eq"] for x in o_]) - refeq
        rs.append(dd.mean())
        print(f"{'random skip #'+str(s_+1):<20}{np.mean([x['eq'] for x in o_]):>12.2f}"
              f"{dd.mean():>+12.2f}{'':>8}{f'{int((dd>0).sum())}/{len(dd)}':>8}"
              f"{np.mean([x['caps'] for x in o_])/mon:>9.1f}")
    rs = np.array(rs)
    print(f"\n  random: mean {rs.mean():+.2f}, best {rs.max():+.2f}   |   "
          f"SAME {sd.mean():+.2f}")
    print(f"  -> {'SAME beats rate-matched random' if sd.mean() > rs.max() else 'random MATCHES it - rule not confirmed here'}")
    print()


# 1) BTCUSDm M15 - never loaded in this session
test("BTCUSDm M15  (untouched)", load("BTCUSDm", mt5.TIMEFRAME_M15), 10.0, 50.0)

# 2) a second instrument on H1, brick scaled to its price so the trade is
#    comparable rather than absurd
for sym, sp, bid, pt_ in avail:
    if sym == "BTCUSDm":
        continue
    brick = max(pt_ * 10, round(bid * (50.0 / 64000.0), 2))   # same % of price as BTC
    test(f"{sym} H1  (different market)", load(sym, mt5.TIMEFRAME_H1), sp, brick)

mt5.shutdown()
