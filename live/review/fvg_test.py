"""Does a Fair Value Gap on the confirming candle mark a better BOS?

Owner 2026-09-19: "I heard of things like the fair value gap. Could it be
used for a possible edge?" Of the ways to plug it in, the one that is not
a shorter target or a nearer entry (both lost this week) is a QUALITY
filter on the break: take only a BOS whose confirming move was impulsive
enough to leave a gap.

FVG on three consecutive candles ending at the confirmation candle:
  bullish  low[i]  > high[i-2]     (a hole between candle 1 and candle 3)
  bearish  high[i] < low[i-2]
Measured two ways, because this bot's engine reads the silence-filtered
chart: on the 3 RAW M1 bars, and on the 3 last KEPT (filtered) candles.
A gap smaller than the spread is also tested as "no gap".

Same replay as session_test: live config with the nervosity brake OFF
(more trades; the filter is about the candle, not the hour). 41.7 days,
6 window anchors. The bar to clear is the same as for everything else:
positive on 5 of 6 anchors, or it is buried.

    python review/fvg_test.py [spread_points]
"""
import bisect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_ARGS = sys.argv[1:]
sys.argv = ["fvg_test"]

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


def gap(c1, c3, d):
    """Size of the FVG between candle 1 and candle 3 in direction d, or 0.
    Candles as [t, o, h, l, c, ...] or MT5 rows."""
    h1, l1 = float(c1[2]), float(c1[3])
    h3, l3 = float(c3[2]), float(c3[3])
    if d == 1:
        return max(0.0, l3 - h1)
    return max(0.0, l1 - h3)


def replay(R, rr, spread, lot=0.02, balance=230.0):
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, trades = [], [], []
    prev_trend = 0
    used_hi = used_lo = None
    pos = None
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        if pos:
            d, e, sl, tp, oi, tag = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                risk = abs(e - sl)
                win = bool(hit_tp and not hit_sl)
                pts = ((tp - e) * d - spread) if win else -(risk + spread)
                trades.append(dict(R=pts / risk, win=win, usd=pts * lot, **tag))
                pos = None
        hv, lv = eng.hi_v, eng.lo_v
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev_trend and eng.trend != 0:
            flips.append(t)
            prev_trend = eng.trend
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
            mv2 = (bisect.bisect_left(marks, t)
                   - bisect.bisect_left(marks, t - 7200))
            if mv2 < 1:
                continue
        if pos:
            continue
        risk = abs(c - slp)
        if risk <= B.S_MIN_DIST or risk * lot > B.MAX_RISK_PCT * balance:
            continue
        # the FVG left by the confirming move, raw and on the chart
        g_raw = gap(R[i - 2], R[i], d) if i >= 2 else 0.0
        k = eng.kept
        g_kept = gap(k[-3], k[-1], d) if len(k) >= 3 else 0.0
        pos = (d, c, slp, c + d * rr * risk, i,
               dict(g_raw=g_raw, g_kept=g_kept))
    return trades


def summ(tr):
    if not tr:
        return dict(n=0, per=0.0, wr=0.0, usd=0.0)
    return dict(n=len(tr), per=sum(x["R"] for x in tr) / len(tr),
                wr=100 * sum(1 for x in tr if x["win"]) / len(tr),
                usd=sum(x["usd"] for x in tr))


def main():
    spread = float(_ARGS[0]) if _ARGS else 7.0
    sym, R = bars()
    days = len(R) / 60 / 24
    print(f"  {sym}  {days:.1f} jours  spread {spread:.0f}  RR 0.8"
          f"  frein nervosite OFF\n")
    ANCH, step = 6, 600
    BUCKETS = [
        ("tous les BOS (reference)", lambda x: True),
        ("FVG brut > 0 (3 bougies M1)", lambda x: x["g_raw"] > 0),
        ("sans FVG brut", lambda x: x["g_raw"] <= 0),
        (f"FVG brut >= spread ({spread:.0f})", lambda x: x["g_raw"] >= spread),
        ("FVG sur le graphique filtre", lambda x: x["g_kept"] > 0),
        ("sans FVG filtre", lambda x: x["g_kept"] <= 0),
    ]
    per = {b[0]: [] for b in BUCKETS}
    for a in range(ANCH):
        sub = R[a * step:]
        if len(sub) < 20000:
            break
        tr = replay(sub, 0.8, spread)
        for name, f in BUCKETS:
            per[name].append(summ([x for x in tr if f(x)]))
    print(f"  {'filtre':<32}{'trades':>7}{'reussite':>10}{'R/trade':>10}"
          f"{'$':>9}{'anc.+':>7}")
    for name, rs in per.items():
        b = rs[0]
        pa = sum(1 for r in rs if r["per"] > 0)
        print(f"  {name:<32}{b['n']:>7}{b['wr']:>9.1f}%{b['per']:>+10.3f}"
              f"{b['usd']:>+9.2f}{pa:>4}/{len(rs)}")
    print("\n  FVG brut > 0, par ancrage :")
    for i, r in enumerate(per["FVG brut > 0 (3 bougies M1)"]):
        print(f"    ancrage {i}: {r['n']:>3} trades  {r['wr']:5.1f}%  "
              f"{r['per']:+.3f} R/trade")


if __name__ == "__main__":
    main()
