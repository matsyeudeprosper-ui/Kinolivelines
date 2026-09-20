"""Take only the first N trades after each flip - does capping help?

Owner 2026-09-20: "what if I only took the first 3 trades after each
flip (CHoCH)?"

The cap is applied INSIDE the replay, not by filtering results
afterwards. That matters: a trade refused by the cap never occupies the
one position slot, so a flip arriving minutes later can be taken instead
of being blocked. Post-filtering would miss that entirely.

"After each flip" counts TAKEN trades since the trend last turned:
  1 = the flip trade itself (first BOS of the new trend)
  2 = the first continuation, 3 = the second, and so on.

Live configuration: confirmation close, RR 0.8, awake gate, weather gate
on, one position at a time, spread paid. 41.7 days, 6 window anchors.
The bar is the usual one: better than uncapped on 5 of 6 anchors, or it
is not a finding.

    python review/flip_cap_test.py [spread_points]
"""
import bisect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_ARGS = sys.argv[1:]
sys.argv = ["flip_cap_test"]

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


def replay(R, cap, spread, rr=0.8, lot=0.02, balance=230.0):
    """cap = max TAKEN trades per flip; None = no cap."""
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, trades = [], [], []
    prev_trend = 0
    used_hi = used_lo = None
    pos = None
    ordn = 0
    capped_off = 0                 # signals the cap refused
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
                               "usd": pts * lot, "ord": od})
                pos = None
        hv, lv = eng.hi_v, eng.lo_v
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev_trend and eng.trend != 0:
            flips.append(t)
            prev_trend = eng.trend
            ordn = 0                        # a new trend restarts the count
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
        # THE CAP, before the position check: a refused trade leaves the
        # slot free, which is the whole point of simulating it here
        if cap is not None and ordn >= cap:
            capped_off += 1
            continue
        if pos:
            continue
        risk = abs(c - slp)
        if risk <= B.S_MIN_DIST or risk * lot > B.MAX_RISK_PCT * balance:
            continue
        ordn += 1
        pos = (d, c, slp, c + d * rr * risk, i, ordn)
    return trades, capped_off


def summ(tr):
    if not tr:
        return dict(n=0, per=0.0, wr=0.0, usd=0.0, R=0.0)
    return dict(n=len(tr), per=sum(x["R"] for x in tr) / len(tr),
                wr=100 * sum(1 for x in tr if x["win"]) / len(tr),
                usd=sum(x["usd"] for x in tr), R=sum(x["R"] for x in tr))


def main():
    spread = float(_ARGS[0]) if _ARGS else 7.0
    sym, R = bars()
    days = len(R) / 60 / 24
    print(f"  {sym}  {days:.1f} jours  spread {spread:.0f}  live config\n")
    CAPS = [(1, "only the flip trade"), (2, "flip + 1 continuation"),
            (3, "flip + 2 continuations"), (4, "flip + 3"),
            (None, "no cap (today)")]
    ANCH, step = 6, 600
    print(f"  {'rule':<26}{'trades':>7}{'/day':>7}{'win%':>8}"
          f"{'R/trade':>10}{'R tot':>8}{'$':>9}{'anch+':>7}{'refused':>9}")
    base = None
    for cap, lab in CAPS:
        rows, off0 = [], 0
        for a in range(ANCH):
            sub = R[a * step:]
            if len(sub) < 20000:
                break
            tr, off = replay(sub, cap, spread)
            rows.append(summ(tr))
            if a == 0:
                off0 = off
        b = rows[0]
        pa = sum(1 for r in rows if r["per"] > 0)
        if cap is None:
            base = b
        print(f"  {lab:<26}{b['n']:>7}{b['n']/days:>7.1f}{b['wr']:>7.1f}%"
              f"{b['per']:>+10.3f}{b['R']:>+8.1f}{b['usd']:>+9.2f}"
              f"{pa:>4}/{len(rows)}{off0:>9}")
    if base:
        print(f"\n  uncapped reference: {base['n']} trades, "
              f"{base['per']:+.3f} R/trade, {base['usd']:+.2f} $")


if __name__ == "__main__":
    main()
