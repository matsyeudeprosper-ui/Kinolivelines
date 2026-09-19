"""Weekday vs weekend - the live configuration, split by UTC day of entry.

Owner 2026-09-19: "what are the backtest results of weekends only?"

Same replay as rr_sweep (entry at the confirmation close, RR 0.8, weather
gate on, one position at a time, spread paid), with the ENTRY time kept on
each trade so it can be bucketed. Weekend = Saturday or Sunday UTC.

BTC trades 24/7 on this broker, so weekend trades exist; but 41.7 days is
only ~6 weekends, so read the weekend row as a small sample.

    python review/weekend_test.py [spread_points]
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
sys.argv = ["weekend_test"]

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
            d, e, sl, tp, oi, to = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                risk = abs(e - sl)
                win = bool(hit_tp and not hit_sl)
                pts = ((tp - e) * d - spread) if win else -(risk + spread)
                trades.append({"R": pts / risk, "win": win,
                               "usd": pts * lot, "t": to})
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
        pos = (d, c, slp, c + d * rr * risk, i, t)
    return trades


def summ(tr):
    if not tr:
        return dict(n=0, R=0.0, per=0.0, wr=0.0, usd=0.0)
    return dict(n=len(tr), R=sum(x["R"] for x in tr),
                per=sum(x["R"] for x in tr) / len(tr),
                wr=100 * sum(1 for x in tr if x["win"]) / len(tr),
                usd=sum(x["usd"] for x in tr))


def is_weekend(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).weekday() >= 5


def main():
    spread = float(_ARGS[0]) if _ARGS else 7.0
    sym, R = bars()
    days = len(R) / 60 / 24
    t0 = int(R[0]["time"])
    wk_days = sum(1 for k in range(int(days) + 1)
                  if is_weekend(t0 + k * 86400))
    print(f"  {sym}  {days:.1f} jours dont ~{wk_days} jours de week-end"
          f"   spread {spread:.0f}   (RR 0.8, freins actifs)\n")
    ANCH, step = 6, 600
    rows = {"semaine": [], "week-end": []}
    for a in range(ANCH):
        sub = R[a * step:]
        if len(sub) < 20000:
            break
        tr = replay(sub, 0.8, spread)
        rows["week-end"].append(summ([x for x in tr if is_weekend(x["t"])]))
        rows["semaine"].append(summ([x for x in tr if not is_weekend(x["t"])]))
    print(f"  {'':10}{'trades':>8}{'/jour':>8}{'reussite':>10}{'R/trade':>10}"
          f"{'R total':>9}{'$':>9}{'anc.+':>7}")
    for lab, rs in rows.items():
        b = rs[0]
        nd = wk_days if lab == "week-end" else days - wk_days
        pos_anch = sum(1 for r in rs if r["per"] > 0)
        print(f"  {lab:<10}{b['n']:>8}{b['n']/max(nd,1):>8.1f}{b['wr']:>9.1f}%"
              f"{b['per']:>+10.3f}{b['R']:>+9.1f}{b['usd']:>+9.2f}"
              f"{pos_anch:>4}/{len(rs)}")
    # per-anchor detail for the weekend, since the sample is small
    print("\n  week-end, par ancrage :")
    for i, r in enumerate(rows["week-end"]):
        print(f"    ancrage {i}: {r['n']:>3} trades  {r['wr']:5.1f}%  "
              f"{r['per']:+.3f} R/trade  {r['usd']:+.2f} $")


if __name__ == "__main__":
    main()
