"""Is a signal better when FEW moves have happened, or many?

Owner 2026-09-21: "which is better moment, when I still have few of flips
or more of them, I'm referring to the 1/2 and 1/1 movement indicator of
ours... sometimes it gets to 6/2 even."

The live rule only asks for >= 1 big move in the last 2 h. It never asks
HOW MANY. This buckets every trade by the count that stood at entry.

Covers the MAIN structure only ("grands mouvements / 2 h"). The small-move
count feeding the internal rule ("petits mouvements / 1 h") comes from the
internal engine, which this replay does not run - it cannot be answered
from this data and is not guessed at here.

Controls, same bar as everything else this week: 6 window anchors, the two
halves separately, and three spreads. A bucket that only works on one
anchor or one half is noise.

    python review/moves_count_test.py [spread]
"""
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_A = sys.argv[1:]
sys.argv = ["moves_count_test"]

import selector_test as S              # noqa: E402

SPREAD = float(_A[0]) if _A else 7.0
BUCKETS = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 99)]


def label(lo, hi):
    return f"{lo}" if lo == hi else (f"{lo}-{hi}" if hi < 99 else f"{lo}+")


def pick(tr, lo, hi):
    return [x for x in tr if lo <= (x.get("mv2") or 0) <= hi]


def summ(tr):
    if not tr:
        return None
    r = [x["R"] for x in tr]
    return dict(n=len(tr), per=sum(r) / len(r),
                wr=100 * sum(1 for x in tr if x["win"]) / len(tr),
                usd=sum(x["usd"] for x in tr),
                se=(st.pstdev(r) / len(r) ** 0.5) if len(r) > 1 else 0.0)


def main():
    sym, R = S.bars()
    days = len(R) / 1440
    print(f"\n  {sym}  {days:.1f} days  spread {SPREAD:.0f}  live config")
    print("  bucket = big moves in the 2 h before entry\n")

    ANCH, step = 6, 600
    per = {label(*b): [] for b in BUCKETS}
    base0 = None
    for a in range(ANCH):
        sub = R[a * step:]
        if len(sub) < 20000:
            break
        tr = S.replay(sub, SPREAD)
        if a == 0:
            base0 = tr
        for lo, hi in BUCKETS:
            per[label(lo, hi)].append(summ(pick(tr, lo, hi)))

    print(f"  {'moves/2h':<10}{'trades':>7}{'share':>8}{'win%':>8}"
          f"{'R/trade':>10}{'95% interval':>20}{'$':>9}{'anch+':>7}")
    tot = sum(len(pick(base0, *b)) for b in BUCKETS)
    for lo, hi in BUCKETS:
        k = label(lo, hi)
        rows = [r for r in per[k] if r]
        b = per[k][0]
        if not b:
            print(f"  {k:<10}{'-':>7}   no trades")
            continue
        pa = sum(1 for r in rows if r["per"] > 0)
        l_, h_ = b["per"] - 1.96 * b["se"], b["per"] + 1.96 * b["se"]
        print(f"  {k:<10}{b['n']:>7}{100*b['n']/tot:>7.1f}%{b['wr']:>7.1f}%"
              f"{b['per']:>+10.3f}   [{l_:+.3f},{h_:+.3f}]{b['usd']:>9.2f}"
              f"{pa:>4}/{len(rows)}")

    mid = sorted(x["t"] for x in base0)[len(base0) // 2]
    print("\n  THE TWO HALVES")
    for lo, hi in BUCKETS:
        k = label(lo, hi)
        h1 = summ([x for x in pick(base0, lo, hi) if x["t"] < mid])
        h2 = summ([x for x in pick(base0, lo, hi) if x["t"] >= mid])
        if not h1 or not h2:
            print(f"  {k:<10} too few to split")
            continue
        ag = "agree" if (h1["per"] > 0) == (h2["per"] > 0) else "DISAGREE"
        print(f"  {k:<10} 1st {h1['per']:+.3f} ({h1['n']:>3})   "
              f"2nd {h2['per']:+.3f} ({h2['n']:>3})   {ag}")

    print("\n  SPREAD")
    for sp in (0.0, 7.0, 15.0):
        tr = S.replay(R, sp)
        cells = []
        for lo, hi in BUCKETS:
            r = summ(pick(tr, lo, hi))
            cells.append(f"{label(lo,hi)}:{r['per']:+.3f}" if r
                         else f"{label(lo,hi)}:  -   ")
        print(f"    spread {sp:>4.0f}   " + "   ".join(cells))
    print()


if __name__ == "__main__":
    main()
