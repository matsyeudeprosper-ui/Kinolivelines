"""Owner 2026-09-25: "for recovery mode, we keep the flip BOS rule but
we also consider the first BOS in the same direction after a flip...
we take that first trade continuation happening after a flip."

So the deployed rule (FLIP-BOS only) becomes: FLIP-BOS always allowed,
PLUS the very next plain-BOS continuation that follows that flip - but
not any BOS beyond that one. Note for context: "first continuation
after a flip" was independently found to be the STRONGEST slice of all
in earlier research (mt5_owl_packages.md, 2026-09-19 flip_test.py:
+0.138 R/trade, 6/6 anchors - the flip trade itself was actually the
WEAKEST slice there). Different lens (that was ordinal position, this
is debt-specific), but a real reason to expect this could help.

  A  today (deployed): FLIP-BOS only while in debt
  B  FLIP-BOS + the first continuation after it, while in debt

Real B.Struct()/weather_gate() generator, same debt/bullet machinery as
every other recovery test today.

    python review/recovery_flip_plus_first_continuation_test.py [spread]
"""
import bisect
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["recovery_flip_plus_first_continuation_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SPREAD = float(_A[0]) if _A else 7.0
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


def simulate(R, spread, allow_first_continuation):
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks = [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    run = pk = 0.0
    streak = 0
    curve = []
    day_key = None
    last_flip_t = None
    continuation_used_since_flip = True   # nothing to "continue" yet
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
            nv = (sorted(rng[i-60:i])[30]
                  / max(sorted(rng[i-1440:i])[720], 1e-9))
            mv2 = (bisect.bisect_left(marks, t)
                   - bisect.bisect_left(marks, t - 7200))
            if nv >= B.NERV_STORM or mv2 < 1:
                continue
        debt_now = max(0.0, pk - run)
        if flip:
            last_flip_t = t
            continuation_used_since_flip = False
        elif debt_now > 0.5:
            if allow_first_continuation and not continuation_used_since_flip \
                    and last_flip_t is not None:
                continuation_used_since_flip = True   # this is the ONE we take
            else:
                continue        # plain BOS, not the first-after-flip: skipped
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
    return dict(net=run, maxdd=dd, worst_debt=worst_debt)


def run_for(R, label):
    print(f"\n  {label}  {len(R)/1440:.1f} days, spread {SPREAD:.0f}")
    a = simulate(R, SPREAD, False)
    b = simulate(R, SPREAD, True)
    print(f"  {'rule':<48}{'net $':>9}{'max DD':>9}{'worst debt':>11}")
    print(f"  {'A  FLIP-BOS only (deployed)':<48}"
          f"{a['net']:>9.2f}{a['maxdd']:>9.2f}{a['worst_debt']:>11.2f}")
    print(f"  {'B  FLIP-BOS + first continuation after it':<48}"
          f"{b['net']:>9.2f}{b['maxdd']:>9.2f}{b['worst_debt']:>11.2f}")
    print(f"    A vs B: {a['net']-b['net']:+.2f} net, "
          f"{a['maxdd']-b['maxdd']:+.2f} DD, "
          f"{a['worst_debt']-b['worst_debt']:+.2f} worst debt")


def main():
    sym, R = bars()
    run_for(R, f"{sym} FULL PERIOD")
    print("\n  HALVES (each independently)")
    mid = len(R) // 2
    run_for(R[:mid], "FIRST HALF")
    run_for(R[mid:], "SECOND HALF")
    print()


if __name__ == "__main__":
    main()
