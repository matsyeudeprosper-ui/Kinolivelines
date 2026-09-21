"""What constant-risk sizing actually does to the live path.

Owner 2026-09-21: "whatever the risk distance points are we always spend a
max 5 dollars, so the system figures out the lot required each time."

  lot = floor((budget / dist) / 0.01) * 0.01      (risk = dist * lot here)

Rounding DOWN makes the budget a ceiling, which is what "max" means - and
it has a consequence worth measuring rather than guessing: when the stop is
wider than budget/0.01 points, even the minimum lot costs more than the
budget, so the trade cannot be taken at all.

E009 (see mt5_e009_sizing) tested constant risk and found it halves the
drawdown AND the profit, with the random-lot control saying the widest-stop
trades are the BEST ones. This script re-measures that on today's live path
so the owner sees the size of the effect on their own configuration.

    python review/risk_sizing_test.py [budget] [spread]
"""
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_A = sys.argv[1:]
sys.argv = ["risk_sizing_test"]

import selector_test as S              # noqa: E402

BUDGET = float(_A[0]) if _A else 5.0
SPREAD = float(_A[1]) if len(_A) > 1 else 7.0
FIXED = 0.02


def lot_for(dist, budget):
    import math
    return round(math.floor((budget / dist) / 0.01) * 0.01, 2)


def main():
    sym, R = S.bars()
    days = len(R) / 1440
    base = S.replay(R, SPREAD)
    # selector_test records R and usd at a FIXED 0.02 lot; dist is
    # recoverable because usd = R * dist * lot
    rows = []
    for x in base:
        dist = abs(x["usd"] / (x["R"] * FIXED)) if x["R"] else 0.0
        if dist <= 0:
            continue
        rows.append({"R": x["R"], "win": x["win"], "dist": dist})
    print(f"\n  {sym}  {days:.1f} days  spread {SPREAD:.0f}  "
          f"budget ${BUDGET:.2f}  ({len(rows)} trades)\n")

    ds = sorted(r["dist"] for r in rows)
    q = lambda p: ds[min(len(ds) - 1, int(p * len(ds)))]
    print("  STOP DISTANCE (points)")
    print(f"    min {ds[0]:.0f}   p25 {q(.25):.0f}   median {q(.50):.0f}"
          f"   p75 {q(.75):.0f}   p95 {q(.95):.0f}   max {ds[-1]:.0f}")
    cut = BUDGET / 0.01
    lost = [r for r in rows if r["dist"] > cut]
    print(f"\n  TRADES THE BUDGET REFUSES  (stop > {cut:.0f} pts, because "
          f"even 0.01 lot costs more than ${BUDGET:.2f})")
    print(f"    {len(lost)} of {len(rows)} = {100*len(lost)/len(rows):.1f}%"
          f"   ({len(lost)/days:.2f} per day)")
    if lost:
        wr = 100 * sum(1 for r in lost if r["win"]) / len(lost)
        rr = sum(r["R"] for r in lost) / len(lost)
        print(f"    those trades were {wr:.1f}% winners, "
              f"{rr:+.3f} R/trade  <- what the rule gives up")

    kept = [r for r in rows if r["dist"] <= cut]
    lots = [lot_for(r["dist"], BUDGET) for r in kept]
    print(f"\n  LOT THE SYSTEM WOULD PICK  (on the {len(kept)} it still takes)")
    print(f"    min {min(lots):.2f}   median {st.median(lots):.2f}"
          f"   max {max(lots):.2f}   (today: flat {FIXED})")
    spend = [r["dist"] * l for r, l in zip(kept, lots)]
    print(f"    actual $ risked: min {min(spend):.2f}  median "
          f"{st.median(spend):.2f}  max {max(spend):.2f}")

    print("\n  MONEY, same trades, two sizings")
    f_usd = sum(r["R"] * r["dist"] * FIXED for r in rows)
    c_usd = sum(r["R"] * r["dist"] * l for r, l in zip(kept, lots))
    print(f"    fixed {FIXED} lot, every trade     "
          f"{len(rows):>4} trades   ${f_usd:+.2f}")
    print(f"    ${BUDGET:.0f} budget, wide stops dropped "
          f"{len(kept):>4} trades   ${c_usd:+.2f}")

    def dd(seq):
        peak = run = worst = 0.0
        for v in seq:
            run += v
            peak = max(peak, run)
            worst = min(worst, run - peak)
        return worst
    print(f"    worst drawdown: fixed ${dd([r['R']*r['dist']*FIXED for r in rows]):.2f}"
          f"   budget ${dd([r['R']*r['dist']*l for r, l in zip(kept, lots)]):.2f}")
    print()


if __name__ == "__main__":
    main()
