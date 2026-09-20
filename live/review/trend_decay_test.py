"""Do the LATER trades of a trend lose more often?

Owner 2026-09-20: "isn't it that the more trades you take in a trend,
the closer you get to a loss, because one of them will eventually lose -
and I was thinking it's those later ones."

Two different claims live in that sentence, and they need separate tests:

  A. DECAY - a trade's chance of losing rises with its position in the
     trend. Testable: win rate at ordinal 1, 2, 3, 4+.
  B. THE LAST ONE LOSES - a trend ends because a trade failed. Testable:
     how often the final trade of a trend is a loss, versus the base
     rate. If B is true but A is false, the loser is NOT predictable by
     position, only identifiable afterwards - so no cap can dodge it.

Also reported: where the FIRST loss falls inside trends of each length,
and whether the trade right after a win is better or worse than average
(a streak effect would show up there).

Live configuration, 41.7 days, 6 window anchors.

    python review/trend_decay_test.py [spread_points]
"""
import bisect
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_ARGS = sys.argv[1:]
sys.argv = ["trend_decay_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8"))
        if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def replay(R, spread, rr=0.8, lot=0.02, balance=230.0):
    """Returns trades tagged with their trend id and ordinal."""
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, trades = [], [], []
    prev_trend = 0
    used_hi = used_lo = None
    pos = None
    ordn, trend_id = 0, 0
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        if pos:
            d, e, sl, tp, oi, od, tid = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                risk = abs(e - sl)
                win = bool(hit_tp and not hit_sl)
                pts = ((tp - e) * d - spread) if win else -(risk + spread)
                trades.append({"R": pts / risk, "win": win,
                               "ord": od, "trend": tid})
                pos = None
        hv, lv = eng.hi_v, eng.lo_v
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev_trend and eng.trend != 0:
            flips.append(t)
            prev_trend = eng.trend
            ordn = 0
            trend_id += 1
        if sig is not None:
            marks.append(t)
        if sig is None:
            continue
        if not any(f > t - B.AWAKE_WIN for f in flips):
            continue
        d, slp = sig
        flip = bool(flips) and flips[-1] == t
        lvl = hv if d == 1 else lv
        if not flip:
            if (d == 1 and used_hi == lvl) or (d == -1 and used_lo == lvl):
                continue
            if d == 1:
                used_hi = lvl
            else:
                used_lo = lvl
        if i >= 1440:
            nv = (sorted(rng[i - 60:i])[30]
                  / max(sorted(rng[i - 1440:i])[720], 1e-9))
            mv2 = (bisect.bisect_left(marks, t)
                   - bisect.bisect_left(marks, t - 7200))
            if nv > 1.0 or mv2 < 1:
                continue
        if pos:
            continue
        risk = abs(c - slp)
        if risk <= B.S_MIN_DIST or risk * lot > B.MAX_RISK_PCT * balance:
            continue
        ordn += 1
        pos = (d, c, slp, c + d * rr * risk, i, ordn, trend_id)
    return trades


def wr(tr):
    return (100 * sum(1 for x in tr if x["win"]) / len(tr)) if tr else 0.0


def main():
    spread = float(_ARGS[0]) if _ARGS else 7.0
    sym, R = bars()
    days = len(R) / 60 / 24
    print(f"  {sym}  {days:.1f} jours  spread {spread:.0f}  live config\n")
    ANCH, step = 6, 600
    per_ord = defaultdict(list)          # anchor 0 detail
    anchors_ord = []                     # per-anchor win rates
    for a in range(ANCH):
        sub = R[a * step:]
        if len(sub) < 20000:
            break
        tr = replay(sub, spread)
        buckets = defaultdict(list)
        for x in tr:
            k = min(x["ord"], 4)
            buckets[k].append(x)
            if a == 0:
                per_ord[k].append(x)
        anchors_ord.append({k: wr(v) for k, v in buckets.items()})
        if a == 0:
            all0 = tr

    base = wr(all0)
    print("  A. DOES IT DECAY? win rate by position in the trend")
    print(f"  {'position':<22}{'trades':>7}{'win%':>8}{'vs base':>10}"
          f"   per-anchor win%")
    for k in sorted(per_ord):
        lab = {1: "1st (the flip)", 2: "2nd", 3: "3rd",
               4: "4th and later"}[k]
        v = per_ord[k]
        spread_txt = " ".join(f"{a.get(k, 0):.0f}" for a in anchors_ord)
        print(f"  {lab:<22}{len(v):>7}{wr(v):>7.1f}%{wr(v)-base:>+9.1f}"
              f"   {spread_txt}")
    print(f"  {'ALL':<22}{len(all0):>7}{base:>7.1f}%")

    # B. the last trade of each trend
    byt = defaultdict(list)
    for x in all0:
        byt[x["trend"]].append(x)
    seqs = [sorted(v, key=lambda y: y["ord"]) for v in byt.values()]
    multi = [s for s in seqs if len(s) >= 2]
    last_loss = sum(1 for s in seqs if not s[-1]["win"])
    print(f"\n  B. THE LAST TRADE OF EACH TREND")
    print(f"     {len(seqs)} trends produced a trade; "
          f"{last_loss} of them ended on a LOSS = {100*last_loss/len(seqs):.0f}%")
    print(f"     base loss rate is {100-base:.0f}% - "
          f"{'the last trade IS more often a loser' if 100*last_loss/len(seqs) > (100-base)+5 else 'no real excess'}")

    # where the first loss falls, by trend length
    print(f"\n  C. IN TRENDS WITH N TRADES, WHICH ONE IS THE FIRST LOSS?")
    bylen = defaultdict(lambda: defaultdict(int))
    for s in seqs:
        n = min(len(s), 4)
        first = next((i + 1 for i, x in enumerate(s) if not x["win"]), 0)
        bylen[n][min(first, 4)] += 1
    for n in sorted(bylen):
        tot = sum(bylen[n].values())
        parts = ", ".join(f"{p if p else 'none'}:{c}" for p, c in sorted(bylen[n].items()))
        print(f"     {n}{'+' if n == 4 else ''} trades ({tot} trends): {parts}")

    # D. streaks
    aw, al = [], []
    for s in seqs:
        for i in range(1, len(s)):
            (aw if s[i - 1]["win"] else al).append(s[i])
    print(f"\n  D. THE TRADE RIGHT AFTER...")
    print(f"     a WIN : {len(aw):>3} trades, {wr(aw):.1f}% win")
    print(f"     a LOSS: {len(al):>3} trades, {wr(al):.1f}% win")
    print(f"     base  : {len(all0):>3} trades, {base:.1f}% win")


if __name__ == "__main__":
    main()
