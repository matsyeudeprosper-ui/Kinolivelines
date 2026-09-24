"""Control for review/recovery_flip_only_test.py: is "only flip-BOS
while in debt" really about SELECTION QUALITY, or just an artifact of
trading less during debt - the same mechanism that made the minute and
Late-session recovery ideas WORSE, not better?

Runs many random trials that skip debt-period signals at THE SAME RATE
as the flip-only rule (matched volume, no quality info used), and
checks where the real flip-only result falls in that distribution -
same "selection not size" control already used for the bullet-streak
rule (review/bullet_tune_test.py streak_rule()).

    python review/recovery_flip_only_control.py [spread] [trials]
"""
import bisect
import json
import os
import random
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["recovery_flip_only_control"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SPREAD = float(_A[0]) if len(_A) > 0 else 7.0
TRIALS = int(_A[1]) if len(_A) > 1 else 500
LOT = 0.02
BLOT = 0.01
NB = 3.0
K = 2


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def simulate(R, spread, mode, skip_prob=0.0, rng_obj=None):
    """mode: 'all' (today), 'flip_only' (the real rule),
    'random' (skip a debt-period candidate with prob skip_prob,
    ignoring flip - the control)."""
    eng = B.Struct()
    eng.quiet = True
    rngv = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks = [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    run = pk = 0.0
    streak = 0
    curve = []
    day_key = None
    n_candidates_in_debt = 0
    n_skipped_in_debt = 0
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        dk = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        if dk != day_key:
            day_key = dk
            curve.append(run)
        if pos:
            d, e, sl, tp, dist, mid, hit_mid = pos
            if not hit_mid and ((l <= mid) if d == 1 else (h >= mid)):
                hit_mid = True
                pos = (d, e, sl, tp, dist, mid, hit_mid)
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                pts = (B.RR * dist - spread) if win else -(dist + spread)
                debt = max(0.0, pk - run)
                run += pts * LOT
                fire = debt > 0.5 and streak < K
                if fire and hit_mid:
                    bpts = ((1.3 * dist - spread) if win
                            else -(dist / 2.0 + spread))
                    run += bpts * BLOT * NB
                streak = 0 if win else streak + 1
                pk = max(pk, run)
                pos = None
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev and eng.trend != 0:
            flips.append(t)
            prev = eng.trend
        if sig is not None:
            marks.append(t)
        if sig is None or pos:
            continue
        if not any(f > t - B.AWAKE_WIN for f in flips):
            continue
        d, slp = sig
        flip = bool(flips) and flips[-1] == t
        if not flip:
            lvl = eng.hi_v if d == 1 else eng.lo_v
            if (d == 1 and used_hi == lvl) or (d == -1 and used_lo == lvl):
                continue
            if d == 1:
                used_hi = lvl
            else:
                used_lo = lvl
        if i >= 1440:
            nv = (sorted(rngv[i-60:i])[30]
                  / max(sorted(rngv[i-1440:i])[720], 1e-9))
            mv2 = (bisect.bisect_left(marks, t)
                   - bisect.bisect_left(marks, t - 7200))
            if nv >= B.NERV_STORM or mv2 < 1:
                continue
        debt_now = max(0.0, pk - run)
        if debt_now > 0.5:
            n_candidates_in_debt += 1
            if mode == "flip_only" and not flip:
                n_skipped_in_debt += 1
                continue
            if mode == "random" and rng_obj.random() < skip_prob:
                n_skipped_in_debt += 1
                continue
        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        tp = c + d * B.RR * dist
        pos = (d, c, float(slp), tp, dist, c - d * dist / 2.0, False)
    dd = 0.0
    pk2 = 0.0
    worst_debt = 0.0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
        worst_debt = max(worst_debt, pk2 - v)
    return dict(net=run, maxdd=dd, worst_debt=worst_debt,
                n_cand=n_candidates_in_debt, n_skip=n_skipped_in_debt)


def main():
    sym, R = bars()
    real = simulate(R, SPREAD, "flip_only")
    skip_rate = real["n_skip"] / real["n_cand"] if real["n_cand"] else 0
    print(f"\n  {sym} full period, spread {SPREAD:.0f}")
    print(f"  flip-only-in-debt: net=${real['net']:.2f} "
          f"worst_debt=${real['worst_debt']:.2f} "
          f"(skipped {real['n_skip']}/{real['n_cand']} debt-period "
          f"candidates = {100*skip_rate:.0f}%)")

    rng_obj = random.Random(42)
    net_hits = 0
    dd_hits = 0
    nets, dds = [], []
    for _ in range(TRIALS):
        r = simulate(R, SPREAD, "random", skip_prob=skip_rate, rng_obj=rng_obj)
        nets.append(r["net"])
        dds.append(r["worst_debt"])
        if r["net"] >= real["net"]:
            net_hits += 1
        if r["worst_debt"] <= real["worst_debt"]:
            dd_hits += 1
    nets.sort()
    dds.sort()
    print(f"\n  {TRIALS} random trials skipping debt-period candidates at "
          f"the SAME rate ({100*skip_rate:.0f}%), blind to flip/not-flip:")
    print(f"    random net $:        median {nets[len(nets)//2]:+.2f}  "
          f"range [{nets[0]:+.2f}, {nets[-1]:+.2f}]")
    print(f"    random worst debt:   median {dds[len(dds)//2]:.2f}  "
          f"range [{dds[0]:.2f}, {dds[-1]:.2f}]")
    print(f"\n  flip-only's net $ beaten or matched by {net_hits}/{TRIALS} "
          f"random trials ({100*net_hits/TRIALS:.1f}%)")
    print(f"  flip-only's SMALLER worst-debt beaten or matched by "
          f"{dd_hits}/{TRIALS} random trials ({100*dd_hits/TRIALS:.1f}%)")
    print()


if __name__ == "__main__":
    main()
