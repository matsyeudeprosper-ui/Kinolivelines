"""Only trade after a flip? Results by ORDER and AGE since the last flip.

Owner 2026-09-19: "test what would happen if we only took trades after a
flip happens."

Two readings, both measured:
  ORDER  1 = the flip trade itself (first BOS after a CHoCH), 2 = the
         first continuation, 3+ = later continuations
  AGE    hours between the last flip and this entry: <2h, 2-4h, >=4h
         (E007 found stale continuations, >=4h, lose on both halves)

Live configuration: confirmation close, RR 0.8, awake gate, weather gate
ON, one position at a time, spread paid. 41.7 days, 6 window anchors.
The bar is unchanged: positive on 5 of 6 anchors, or it is buried.

    python review/flip_test.py [spread_points]
"""
import bisect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_ARGS = sys.argv[1:]
sys.argv = ["flip_test"]

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


def replay(R, spread, gate=True, rr=0.8, lot=0.02, balance=230.0):
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, trades = [], [], []
    prev_trend = 0
    used_hi = used_lo = None
    pos = None
    ordn = 0                        # trades taken since the last flip
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
        if gate and i >= 1440:
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
        age_h = (t - flips[-1]) / 3600.0 if flips else 99.0
        pos = (d, c, slp, c + d * rr * risk, i,
               dict(ord=ordn, flip=flip, age=age_h))
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
    print(f"  {sym}  {days:.1f} jours  spread {spread:.0f}  config en direct\n")
    B_ = [
        ("tous (reference)",                 lambda x: True),
        ("1er : la bascule elle-meme",        lambda x: x["ord"] == 1),
        ("2e : 1re continuation",             lambda x: x["ord"] == 2),
        ("3e et plus",                        lambda x: x["ord"] >= 3),
        ("age < 2 h depuis la bascule",       lambda x: x["age"] < 2),
        ("age 2-4 h",                         lambda x: 2 <= x["age"] < 4),
        ("age >= 4 h",                        lambda x: x["age"] >= 4),
    ]
    per = {b[0]: [] for b in B_}
    ANCH, step = 6, 600
    for a in range(ANCH):
        sub = R[a * step:]
        if len(sub) < 20000:
            break
        tr = replay(sub, spread)
        for name, f in B_:
            per[name].append(summ([x for x in tr if f(x)]))
    print(f"  {'tranche':<32}{'trades':>7}{'/jour':>7}{'reussite':>10}"
          f"{'R/trade':>10}{'$':>9}{'anc.+':>7}")
    for name, rs in per.items():
        b = rs[0]
        pa = sum(1 for r in rs if r["per"] > 0)
        print(f"  {name:<32}{b['n']:>7}{b['n']/days:>7.1f}{b['wr']:>9.1f}%"
              f"{b['per']:>+10.3f}{b['usd']:>+9.2f}{pa:>4}/{len(rs)}")
    print("\n  la bascule seule, par ancrage :")
    for i, r in enumerate(per["1er : la bascule elle-meme"]):
        print(f"    ancrage {i}: {r['n']:>3} trades  {r['wr']:5.1f}%  "
              f"{r['per']:+.3f} R/trade  {r['usd']:+.2f} $")


if __name__ == "__main__":
    main()
