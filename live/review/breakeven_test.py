"""Move the stop to entry once the trade is X% of the way to target.

Owner 2026-09-23: "at the trade level, is there any trailing or breakeven
strategy for better balance profit?"

Trailing to each new dot and cutting on the opposite dot were both tested
and both lost. Breakeven is a different mechanism and is untested: it does
nothing while a trade goes against you, and only arms once the trade is
already part-way to target.

Walked bar by bar on raw M1. For each trade we record how far toward the
target price travelled BEFORE it resolved, so a breakeven rule at any
threshold can be scored exactly:

  never reached X%  -> unchanged
  reached X%, then went to TP  -> unchanged (a win)
  reached X%, then came back to entry -> 0 instead of a full loss,
      UNLESS it would have recovered and won, in which case the rule
      COSTS the win. Both cases are counted from the real path.

    python review/breakeven_test.py [spread]
"""
import bisect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["breakeven_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SP = float(_A[0]) if _A else 7.0
LOT = 0.02


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def paths(R):
    """Every live trade with the bar path it took, as fractions of the
    distance to target reached before each touch of entry."""
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, out = [], [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        if pos:
            d, e, sl, tp, dist, best, back = pos
            fav = ((h - e) if d == 1 else (e - l)) / (B.RR * dist)
            best = max(best, fav)
            # did it return to entry after reaching a high-water fraction?
            if best > 0 and ((l <= e) if d == 1 else (h >= e)):
                back = max(back, best)      # remember the best before return
            pos = (d, e, sl, tp, dist, best, back)
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                out.append({"win": bool(hit_tp and not hit_sl), "dist": dist,
                            "best": best, "back": back})
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
        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        pos = (d, c, float(slp), c + d * B.RR * dist, dist, 0.0, 0.0)
    return out


def money(tr, thr):
    """thr = None for no rule, else the fraction of the way to TP that arms
    the breakeven stop."""
    tot = 0.0
    saved = cost = 0
    for x in tr:
        d = x["dist"]
        if thr is None or x["back"] < thr:
            tot += ((B.RR * d - SP) if x["win"] else -(d + SP)) * LOT
            continue
        # the stop was at entry and price came back to it
        tot += (-SP) * LOT
        if x["win"]:
            cost += 1            # would have won; the rule took it away
        else:
            saved += 1           # would have lost the full stop
    return tot, saved, cost


def main():
    sym, R = bars()
    tr = paths(R)
    print(f"\n  {sym}  {len(R)/1440:.1f} days, {len(tr)} trades, "
          f"spread {SP:.0f}\n")
    base, _, _ = money(tr, None)
    print(f"  no rule: ${base:+.2f}\n")
    print(f"  {'arm at':>8}{'net $':>10}{'vs none':>10}"
          f"{'losses saved':>14}{'wins lost':>11}")
    for thr in (0.25, 0.40, 0.50, 0.60, 0.75, 0.90):
        m, s, c = money(tr, thr)
        print(f"  {thr*100:>7.0f}%{m:>10.2f}{m-base:>+10.2f}{s:>14}{c:>11}")
    print()


if __name__ == "__main__":
    main()
