"""Does activity help a trade reach its target? Results by session of ENTRY.

Owner 2026-09-19: "isn't it when there's activity, like during New York,
that we have the best chance to win a trade, because it will reach its
target easily?"

Same replay as the live config (confirmation close, RR 0.8, awake gate,
movement gate, one position at a time, spread paid) but with the
NERVOSITY brake OFF - otherwise New York barely exists in the sample,
because that brake blocks 8 of 10 signals there. Each trade is bucketed by
the UTC hour it was ENTERED.

Sessions (UTC):  Asia 0-7  |  London 7-13  |  New York 13-20  |  late 20-24

    python review/session_test.py [spread_points]
"""
import bisect
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_ARGS = sys.argv[1:]
sys.argv = ["session_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SESS = [("Asie 0-7h", 0, 7), ("Londres 7-13h", 7, 13),
        ("New York 13-20h", 13, 20), ("soiree 20-24h", 20, 24)]


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


def replay(R, rr, spread, nerv_gate, lot=0.02, balance=230.0):
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
            d, e, sl, tp, oi, to = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                risk = abs(e - sl)
                win = bool(hit_tp and not hit_sl)
                pts = ((tp - e) * d - spread) if win else -(risk + spread)
                trades.append({"R": pts / risk, "win": win,
                               "usd": pts * lot, "t": to, "mins": i - oi})
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
            if nerv_gate:
                nv = (sorted(rng[i - 60:i])[30]
                      / max(sorted(rng[i - 1440:i])[720], 1e-9))
                if nv > 1.0:
                    continue
        if pos:
            continue
        risk = abs(c - slp)
        if risk <= B.S_MIN_DIST or risk * lot > B.MAX_RISK_PCT * balance:
            continue
        pos = (d, c, slp, c + d * rr * risk, i, t)
    return trades


def summ(tr):
    if not tr:
        return dict(n=0, R=0.0, per=0.0, wr=0.0, usd=0.0, mins=0)
    ms = sorted(x["mins"] for x in tr)
    return dict(n=len(tr), R=sum(x["R"] for x in tr),
                per=sum(x["R"] for x in tr) / len(tr),
                wr=100 * sum(1 for x in tr if x["win"]) / len(tr),
                usd=sum(x["usd"] for x in tr), mins=ms[len(ms) // 2])


def hour(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).hour


def main():
    spread = float(_ARGS[0]) if _ARGS else 7.0
    sym, R = bars()
    days = len(R) / 60 / 24
    print(f"  {sym}  {days:.1f} jours  spread {spread:.0f}  RR 0.8"
          f"  frein nervosite OFF (sinon New York n'existe pas)\n")
    ANCH, step = 6, 600
    per = {s[0]: [] for s in SESS}
    for a in range(ANCH):
        sub = R[a * step:]
        if len(sub) < 20000:
            break
        tr = replay(sub, 0.8, spread, nerv_gate=False)
        for name, h0, h1 in SESS:
            per[name].append(summ([x for x in tr if h0 <= hour(x["t"]) < h1]))
    print(f"  {'session (UTC)':<18}{'trades':>7}{'reussite':>10}{'R/trade':>10}"
          f"{'$':>9}{'duree med.':>12}{'anc.+':>7}")
    for name, rs in per.items():
        b = rs[0]
        pa = sum(1 for r in rs if r["per"] > 0)
        print(f"  {name:<18}{b['n']:>7}{b['wr']:>9.1f}%{b['per']:>+10.3f}"
              f"{b['usd']:>+9.2f}{b['mins']:>9} min{pa:>4}/{len(rs)}")
    print("\n  New York, par ancrage :")
    for i, r in enumerate(per["New York 13-20h"]):
        print(f"    ancrage {i}: {r['n']:>3} trades  {r['wr']:5.1f}%  "
              f"{r['per']:+.3f} R/trade")


if __name__ == "__main__":
    main()
