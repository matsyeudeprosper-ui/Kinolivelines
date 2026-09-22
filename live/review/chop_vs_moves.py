"""Does a HIGHER movement count mean a choppier market?

Owner 2026-09-22: "does the more movement in 1/2 the more choppy? For
example if I see 6/2 or 6/1 for internal structure."

Measured with the efficiency ratio (Kaufman):

    |last close - first close|  /  sum of every minute's absolute change

    1.00 = a straight line, price went somewhere
    0.10 = the same distance walked back and forth, went nowhere

So LOW efficiency is choppy. For every minute of the sample this counts the
confirmed breaks in the previous 2 h (the "grands mouvements" figure) and
the efficiency over that same 2 h, then buckets one by the other.

Also reports the distance actually travelled, because "choppy" and "quiet"
are different things and the count could mean either.

    python review/chop_vs_moves.py
"""
import json
import os
import statistics as st
import sys

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIVE)

import MetaTrader5 as mt5              # noqa: E402
import owl_chart_feed as F             # noqa: E402

WIN = 120          # minutes = the 2 h window the live rule uses
BUCKETS = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 5), (6, 99)]


def label(lo, hi):
    return f"{lo}" if lo == hi else (f"{lo}-{hi}" if hi < 99 else f"{lo}+")


def main():
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    assert mt5.initialize(path=u["terminal"]), mt5.last_error()
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 60000)
    mt5.shutdown()

    kept = F.build(R)
    marks = sorted(m[0] for m in F.engine(kept)[1])
    closes = [float(r["close"]) for r in R]
    times = [int(r["time"]) for r in R]
    print(f"\n  {sym}  {len(R)/1440:.1f} days   {len(marks)} confirmed breaks")
    print(f"  window {WIN} min (the live 2 h rule)\n")

    import bisect
    rows = {label(*b): [] for b in BUCKETS}
    for i in range(WIN, len(R)):
        t = times[i]
        n = (bisect.bisect_left(marks, t)
             - bisect.bisect_left(marks, t - WIN * 60))
        seg = closes[i - WIN:i + 1]
        path = sum(abs(seg[k] - seg[k - 1]) for k in range(1, len(seg)))
        if path <= 0:
            continue
        eff = abs(seg[-1] - seg[0]) / path
        for lo, hi in BUCKETS:
            if lo <= n <= hi:
                rows[label(lo, hi)].append((eff, path, abs(seg[-1] - seg[0])))
                break

    print(f"  {'breaks/2h':<11}{'minutes':>9}{'share':>8}"
          f"{'efficiency':>12}{'path pts':>10}{'net pts':>9}")
    tot = sum(len(v) for v in rows.values())
    for lo, hi in BUCKETS:
        k = label(lo, hi)
        v = rows[k]
        if not v:
            print(f"  {k:<11}{'-':>9}   none")
            continue
        print(f"  {k:<11}{len(v):>9}{100*len(v)/tot:>7.1f}%"
              f"{st.median(x[0] for x in v):>12.3f}"
              f"{st.median(x[1] for x in v):>10.0f}"
              f"{st.median(x[2] for x in v):>9.0f}")
    print("\n  efficiency: 1.00 = straight line, low = walked back and forth")
    print("  path = distance travelled, net = distance actually covered\n")


if __name__ == "__main__":
    main()
