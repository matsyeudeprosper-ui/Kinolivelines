"""Is the "3 moves" bucket real, or the best of five guesses?

moves_count_test found bucket 3 at +0.164 R/trade, 68.1% win, 6/6 anchors,
halves agreeing, positive at every spread - while 1, 2, 4-5 and 6+ are all
flat or negative. A single spike with negative neighbours on BOTH sides is
not a mechanism; a real "more/fewer moves is better" effect would show a
SLOPE. So two questions:

  1. SLOPE     does R/trade rise or fall with the count at all?
  2. SHUFFLE   reassign the counts at random, keep the outcomes. How often
               does the BEST of five buckets beat +0.164 by luck? That is
               the honest test, because bucket 3 was chosen by looking.

    python review/moves_count_controls.py
"""
import os
import random
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.argv = ["moves_count_controls"]

import selector_test as S              # noqa: E402

BUCKETS = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 99)]
REAL = 3


def mean(v):
    return sum(v) / len(v) if v else 0.0


def main():
    sym, R = S.bars()
    tr = S.replay(R, 7.0)
    tr = [x for x in tr if x.get("mv2")]
    print(f"\n  {sym}  {len(tr)} trades with a movement count\n")

    # 1. slope
    xs = [min(x["mv2"], 8) for x in tr]
    ys = [x["R"] for x in tr]
    mx, my = mean(xs), mean(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    slope = cov / vx if vx else 0.0
    sy = st.pstdev(ys) or 1e-9
    r = cov / ((vx ** 0.5) * (sy * len(ys) ** 0.5) + 1e-9)
    print("  1. SLOPE  (does quality move WITH the count?)")
    print(f"     slope {slope:+.4f} R per extra move,  correlation {r:+.3f}")
    print(f"     verdict: {'a real trend' if abs(r) > 0.15 else 'no trend - flat'}")

    # 2. shuffle, scoring the BEST bucket each time
    counts = [x["mv2"] for x in tr]
    outs = [x["R"] for x in tr]
    real_best = -9.0
    for lo, hi in BUCKETS:
        v = [o for c, o in zip(counts, outs) if lo <= c <= hi]
        if len(v) >= 10:
            real_best = max(real_best, mean(v))
    random.seed(7)
    hits = 0
    sims = 4000
    for _ in range(sims):
        random.shuffle(counts)
        best = -9.0
        for lo, hi in BUCKETS:
            v = [o for c, o in zip(counts, outs) if lo <= c <= hi]
            if len(v) >= 10:
                best = max(best, mean(v))
        if best >= real_best:
            hits += 1
    print("\n  2. SHUFFLE  (counts reassigned at random, 4000 times)")
    print(f"     real BEST bucket: {real_best:+.3f}")
    print(f"     random runs whose best bucket matched or beat it: "
          f"{hits}/{sims}  ->  p = {hits/sims:.3f}")
    print(f"     verdict: {'survives' if hits/sims < 0.05 else 'INSIDE what chance produces'}")
    print()


if __name__ == "__main__":
    main()
