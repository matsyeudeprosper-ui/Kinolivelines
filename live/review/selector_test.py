"""Two ways of choosing WHICH signals to execute for real.

Owner 2026-09-20:
  A. "a version that only does one trade after each virtual loss"
  B. "one that only takes the 2nd trade of a trend"

Both are selectors over the SAME baseline sequence: the bot keeps
tracking its normal one-at-a-time behaviour, and only some of those
trades are actually placed. So the signal list is identical in every
arm and the arms are directly comparable.

  A  after a trade resolves as a LOSS, arm; the next trade is real;
     then disarm until the next loss. A losing real trade re-arms, so
     consecutive losses give consecutive real trades.
  B  only the 2nd taken trade of each trend.

HEALTH WARNING on A: it was suggested by test D of trend_decay_test
(after a loss 68.4% vs 61.1% base) - an idea found IN this data. Re-testing
it on the same 41.7 days cannot confirm it. The halves are reported
separately for exactly that reason; agreement across halves and anchors
is the minimum, and even then it needs forward data.

B is the SNIPER variant, which ran live and hit its -$80 kill line on
2026-09-18 after 25 real trades. One forward test outranks any replay.

    python review/selector_test.py [spread_points]
"""
import bisect
import json
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_ARGS = sys.argv[1:]
sys.argv = ["selector_test"]

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
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, trades = [], [], []
    prev_trend = 0
    used_hi = used_lo = None
    pos = None
    ordn = 0
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        if pos:
            d, e, sl, tp, oi, od = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                risk = abs(e - sl)
                win = bool(hit_tp and not hit_sl)
                pts = ((tp - e) * d - spread) if win else -(risk + spread)
                trades.append({"R": pts / risk, "win": win,
                               "usd": pts * lot, "ord": od, "t": t})
                pos = None
        hv, lv = eng.hi_v, eng.lo_v
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev_trend and eng.trend != 0:
            flips.append(t)
            prev_trend = eng.trend
            ordn = 0
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
        pos = (d, c, slp, c + d * rr * risk, i, ordn)
    return trades


def sel_after_loss(tr):
    """A: one real trade after each loss."""
    out, armed = [], False
    for x in tr:
        if armed:
            out.append(x)
            armed = False
        if not x["win"]:
            armed = True          # a losing REAL trade re-arms too
    return out


def sel_second(tr):
    return [x for x in tr if x["ord"] == 2]


def summ(tr):
    if not tr:
        return dict(n=0, per=0.0, wr=0.0, usd=0.0, R=0.0, se=0.0)
    r = [x["R"] for x in tr]
    return dict(n=len(tr), per=sum(r) / len(r),
                wr=100 * sum(1 for x in tr if x["win"]) / len(tr),
                usd=sum(x["usd"] for x in tr), R=sum(r),
                se=(st.pstdev(r) / len(r) ** 0.5) if len(r) > 1 else 0.0)


def main():
    spread = float(_ARGS[0]) if _ARGS else 7.0
    sym, R = bars()
    days = len(R) / 60 / 24
    print(f"  {sym}  {days:.1f} jours  spread {spread:.0f}  live config\n")
    SELS = [("all signals (today)", lambda t: t),
            ("A: after each loss", sel_after_loss),
            ("B: 2nd of each trend", sel_second)]
    ANCH, step = 6, 600
    per = {k: [] for k, _ in SELS}
    base0 = None
    for a in range(ANCH):
        sub = R[a * step:]
        if len(sub) < 20000:
            break
        tr = replay(sub, spread)
        if a == 0:
            base0 = tr
        for lab, f in SELS:
            per[lab].append(summ(f(tr)))
    print(f"  {'rule':<24}{'trades':>7}{'/day':>7}{'win%':>8}{'R/trade':>10}"
          f"{'95% interval':>20}{'$':>9}{'anch+':>7}")
    for lab, _ in SELS:
        b = per[lab][0]
        pa = sum(1 for r in per[lab] if r["per"] > 0)
        lo, hi = b["per"] - 1.96 * b["se"], b["per"] + 1.96 * b["se"]
        print(f"  {lab:<24}{b['n']:>7}{b['n']/days:>7.2f}{b['wr']:>7.1f}%"
              f"{b['per']:>+10.3f}   [{lo:+.3f},{hi:+.3f}]{b['usd']:>9.2f}"
              f"{pa:>4}/{len(per[lab])}")
    # halves - the control that matters for an idea found in this data
    mid = sorted(x["t"] for x in base0)[len(base0) // 2]
    print("\n  THE TWO HALVES (same rules, each half on its own)")
    for lab, f in SELS:
        h1 = summ([x for x in f(base0) if x["t"] < mid])
        h2 = summ([x for x in f(base0) if x["t"] >= mid])
        agree = "agree" if (h1["per"] > 0) == (h2["per"] > 0) else "DISAGREE"
        print(f"  {lab:<24} 1st {h1['per']:+.3f} ({h1['n']:>3})   "
              f"2nd {h2['per']:+.3f} ({h2['n']:>3})   {agree}")


if __name__ == "__main__":
    main()
