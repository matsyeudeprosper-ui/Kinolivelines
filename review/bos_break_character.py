"""Does the break's own character say whether it will run?

Owner's question, 2026-09-29: "How do I know a BOS has the power to push? In
chop we hit the stop before the target. Is there an indicator, a sign in my
own data, or news to watch?"

Everything about the CONTEXT of a break is already closed on this account:
higher-timeframe alignment, hourly direction, room to target, order book,
funding, positioning, implied volatility and economic events (E012 separated
winners from losers at AUC 0.50, a coin toss). What had never been measured
is the break ITSELF, so this script measures three things on the same replay
the lab judges with:

  power  the breaking candle's range divided by the median range of the last
         60 minutes - "was the break itself violent?"
  age    how many minutes the broken level had stood, read BEFORE the engine
         moves it on the breaking bar - fresh against stale
  touch  how many times price had come within a tenth of a candle of that
         level without breaking it

WHY THE CONTROL MATTERS. A first pass showed a random number producing a
bucket that "wins in both halves" at +1.26 per trade. With 84 trades per
bucket that happens easily. So the real features are not judged against
zero, they are judged against 200 random features run through the exact same
machinery: a feature only counts if it beats almost all of them.

    python review/bos_break_character.py
"""
import os
import random
import sys

LIVE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live")
sys.path.insert(0, os.path.join(LIVE, "lab"))
sys.path.insert(0, LIVE)
import harness as H  # noqa: E402

DRAWS = 200


def buckets(rows, key, n=3):
    good = [r for r in rows if r.get(key) is not None]
    good.sort(key=lambda r: r[key])
    if len(good) < n * 8:
        return []
    size = len(good) // n
    return [(f"{p[0][key]:g}..{p[-1][key]:g}", p) for p in
            (good[k * size:] if k == n - 1 else good[k * size:(k + 1) * size] for k in range(n))]


def stat(part):
    if not part:
        return 0, 0.0, 0.0, 0.0
    w = sum(1 for r in part if r["win"])
    net = sum(r["pnl"] or 0 for r in part)
    return len(part), 100.0 * w / len(part), net, net / len(part)


def best_edge(rows, key, mid):
    """The best per-trade edge among buckets whose two halves agree in sign.
    This is the number a random feature has to beat."""
    best = None
    for _, part in buckets(rows, key):
        h1 = [r for r in part if r["t"] < mid]
        h2 = [r for r in part if r["t"] >= mid]
        if not h1 or not h2:
            continue
        _, _, _, p1 = stat(h1)
        _, _, _, p2 = stat(h2)
        if (p1 > 0) != (p2 > 0):
            continue
        _, _, _, per = stat(part)
        if best is None or per > best:
            best = per
    return best


def show(rows, key, label, mid):
    print(f"\n{label}")
    bs = buckets(rows, key)
    if not bs:
        print("  too few trades to split")
        return
    print(f"  {'bucket':>18} {'n':>4} {'won':>6} {'net':>9} {'per trade':>10}"
          f"   {'1st half':>16}   {'2nd half':>16}")
    for name, part in bs:
        n, wr, net, per = stat(part)
        h1 = [r for r in part if r["t"] < mid]
        h2 = [r for r in part if r["t"] >= mid]
        n1, _, _, p1 = stat(h1)
        n2, _, _, p2 = stat(h2)
        agree = "  both halves" if (h1 and h2 and (p1 > 0) == (p2 > 0)) else ""
        print(f"  {name:>18} {n:4d} {wr:5.1f}% {net:+9.2f} {per:+10.2f}"
              f"   {n1:3d} {p1:+6.2f}/tr   {n2:3d} {p2:+6.2f}/tr{agree}")


def verdict(rows, key, mid, rng):
    """Where the feature falls among DRAWS random features."""
    real = best_edge(rows, key, mid)
    if real is None:
        return f"{key:>6}: no bucket agrees on both halves -> nothing"
    draws = []
    for k in range(DRAWS):
        for r in rows:
            r["_r"] = rng.random()
        b = best_edge(rows, "_r", mid)
        if b is not None:
            draws.append(b)
    draws.sort()
    beat = sum(1 for d in draws if d < real)
    pct = 100.0 * beat / max(1, len(draws))
    med = draws[len(draws) // 2] if draws else 0.0
    call = "SIGNAL" if pct >= 95 else ("worth another look" if pct >= 90 else "noise")
    return (f"{key:>6}: best agreeing bucket {real:+.2f}/trade, beats {pct:.0f}% of "
            f"{len(draws)} random features (their median {med:+.2f}) -> {call}")


def main():
    H.TRACE = []
    sym, R = H.bars()
    res = H.simulate(R, 7.0, {})
    rows = [r for r in H.TRACE if r["win"] is not None]
    H.TRACE = None
    print(f"{sym}  {len(R)/1440:.1f} days  net {res['net']:+.2f}  "
          f"{res['trades']} trades, {len(rows)} closed inside the window")
    mid = sorted(r["t"] for r in rows)[len(rows) // 2]
    rng = random.Random(11)
    for r in rows:
        r["coin"] = rng.random()
    for key, lab in (("power", "POWER of the breaking candle (x the median minute of the last hour)"),
                     ("age", "AGE of the broken level, in minutes"),
                     ("touch", "TIMES the level was approached before it broke"),
                     ("coin", "CONTROL: one random number")):
        show(rows, key, lab, mid)
    print("\n=== against 200 random features, the same machinery ===")
    for key in ("power", "age", "touch", "coin"):
        print("  " + verdict(rows, key, mid, random.Random(29)))
    for kind, sel in (("changes of direction", lambda r: r["flip"]),
                      ("continuations", lambda r: not r["flip"])):
        part = [r for r in rows if sel(r)]
        n, wr, net, per = stat(part)
        print(f"\n--- {kind}: {n} trades, {wr:.1f}% won, net {net:+.2f} ({per:+.2f}/trade)")
        if len(part) >= 60:
            m2 = sorted(r["t"] for r in part)[len(part) // 2]
            for key in ("power", "age"):
                print("  " + verdict(part, key, m2, random.Random(31)))


if __name__ == "__main__":
    main()
