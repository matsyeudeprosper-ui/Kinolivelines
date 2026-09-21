"""WHICH trades does the movement gate remove, and are they really that bad?

move_gate_test: the gate helps on 12/12 anchors, +0.033 R/trade, both
halves agree, positive at every spread - while costing only ~8 of 203
trades. A filter that drops 4% of the volume and moves the whole account
from -0.024 to +0.014 R/trade means the dropped trades must be dreadful.
Arithmetic SUGGESTED about -0.95 R each. Measuring says -0.173 R at 48.6%
wins - the guess was WRONG, because the gate does not merely subtract:
blocking a trade frees the single position slot, so the gated arm takes
DIFFERENT later trades (35 removed, 27 added, 8 fewer overall). Never
infer a subset from two totals when a position limit is in play.

    python review/move_gate_removed.py [spread]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_A = sys.argv[1:]
sys.argv = ["move_gate_removed"]

import move_gate_test as M             # noqa: E402

SPREAD = float(_A[0]) if _A else 7.0


def stats(tr):
    if not tr:
        return None
    r = [x["R"] for x in tr]
    return (len(tr), sum(r) / len(r),
            100 * sum(1 for x in tr if x["win"]) / len(tr),
            sum(x["usd"] for x in tr))


def main():
    sym, R = M.bars()
    print(f"\n  {sym}  {len(R)/1440:.1f} days  spread {SPREAD:.0f}\n")
    print(f"  {'anchor':>7}{'kept':>7}{'REMOVED':>9}{'R/trade':>10}"
          f"{'win%':>8}{'$':>9}")
    allrem = []
    for a in range(12):
        sub = R[a * 400:]
        if len(sub) < 20000:
            break
        off = M.replay(sub, False, SPREAD)
        on = M.replay(sub, True, SPREAD)
        keys = {(x["t"], round(x["dist"], 2)) for x in on}
        rem = [x for x in off if (x["t"], round(x["dist"], 2)) not in keys]
        s = stats(rem)
        if not s:
            print(f"  {a*400:>7}{len(on):>7}{0:>9}       none")
            continue
        allrem.append(rem)
        print(f"  {a*400:>7}{len(on):>7}{s[0]:>9}{s[1]:>+10.3f}"
              f"{s[2]:>7.1f}%{s[3]:>9.2f}")

    # the same trade appears under several anchors; count each once
    uniq = {}
    for rem in allrem:
        for x in rem:
            uniq[(x["t"], round(x["dist"], 2))] = x
    u = list(uniq.values())
    s = stats(u)
    print(f"\n  UNIQUE removed trades across all anchors: {s[0]}")
    print(f"    R/trade {s[1]:+.3f}   win {s[2]:.1f}%   ${s[3]:+.2f}")
    full = sum(1 for x in u if not x["win"])
    print(f"    losers {full}/{s[0]}  ({100*full/s[0]:.0f}%)")
    print()
    print("  NOTE: this file first GUESSED these would average about")
    print("  -0.95 R. They do not - see control(). Blocking a trade frees")
    print("  the position slot, so the gated arm takes DIFFERENT later")
    print("  trades: 35 removed, 27 ADDED, only 8 fewer overall.")
    print()




def control():
    """Two things the table above hides.

    1. It is NOT a subset. Blocking a trade frees the one-position slot, so
       the gated arm takes DIFFERENT later trades: 35 removed but only 8
       fewer overall means ~27 were added. The gate reshuffles as well as
       filters, and the reshuffle is not evidence about signal quality.
    2. The anchors are NOT independent. The removed set takes only TWO
       distinct values across 12 anchors (-0.173 x5, -0.149 x7), so "12/12
       anchors" is really about two observations, not twelve.

    So the honest question is narrow: are the trades with ZERO moves in 2 h
    worse than 35 trades drawn at random from the same pool?
    """
    import random
    sym, R = M.bars()
    off = M.replay(R, False, SPREAD)
    on = M.replay(R, True, SPREAD)
    keys = {(x["t"], round(x["dist"], 2)) for x in on}
    okeys = {(x["t"], round(x["dist"], 2)) for x in off}
    rem = [x for x in off if (x["t"], round(x["dist"], 2)) not in keys]
    add = [x for x in on if (x["t"], round(x["dist"], 2)) not in okeys]
    print(f"  gate OFF {len(off)} trades, ON {len(on)} - "
          f"{len(rem)} removed, {len(add)} ADDED by the freed slot")
    for lab, s in (("removed", stats(rem)), ("added", stats(add))):
        if s:
            print(f"    {lab:<8} {s[0]:>3} trades  {s[1]:+.3f} R  "
                  f"{s[2]:.1f}% win  ${s[3]:+.2f}")
    real = sum(x["R"] for x in rem) / len(rem)
    pool = [x["R"] for x in off]
    random.seed(5)
    hits = 0
    for _ in range(20000):
        if sum(random.sample(pool, len(rem))) / len(rem) <= real:
            hits += 1
    print(f"\n  PERMUTATION: 35 trades drawn at random from the same 203")
    print(f"    real zero-move mean {real:+.3f} R")
    print(f"    random draws at least as bad: {hits}/20000 -> p = {hits/20000:.3f}")
    print(f"    verdict: {'the zero-move trades really are worse' if hits/20000 < 0.05 else 'INSIDE what a random 35 produces'}\n")


if __name__ == "__main__":
    main()
    control()
