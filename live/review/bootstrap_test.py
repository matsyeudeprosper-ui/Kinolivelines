"""Old bootstrap (two consecutive HIGHER lows) vs new (two lows of any
price, first one counts) - on the live trading path.

Owner 2026-09-19: "two glowing dots = a structure", and "internal trades
follow the same rules as main trades". The chart engine was aligned; this
measures the same change on the BOT's engine before it is restarted on
real accounts, because a looser bootstrap ADDS entries - the flip trade of
every newly-born trend - and the flip trade was the weakest slice of the
week (review/flip_test.py: -0.039 R/trade, 0/6 anchors).

Both engines run on the same bars with the live configuration
(confirmation close, RR 0.8, awake gate, weather gate on, one position at a
time, spread 7). 6 window anchors.

    python review/bootstrap_test.py [spread_points]
"""
import bisect
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_ARGS = sys.argv[1:]
sys.argv = ["bootstrap_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as NEW        # noqa: E402
NEW.say = lambda *a, **k: None

# the pre-change bot, saved by the edit that changed it
# the copy must sit in live/ - the bot reads owl_secrets.json and
# owl_nest_users.json relative to its own file
_old_path = os.path.join(LIVE, "_old_bot_cmp.py")
_spec = importlib.util.spec_from_file_location("OLDBOT", _old_path)
OLD = importlib.util.module_from_spec(_spec)
sys.argv = ["bootstrap_test"]
_spec.loader.exec_module(OLD)
OLD.say = lambda *a, **k: None


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


def replay(M, R, spread, rr=0.8, lot=0.02, balance=230.0):
    eng = M.Struct()
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
            d, e, sl, tp, oi, fl = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                risk = abs(e - sl)
                win = bool(hit_tp and not hit_sl)
                pts = ((tp - e) * d - spread) if win else -(risk + spread)
                trades.append({"R": pts / risk, "win": win, "usd": pts * lot,
                               "flip": fl})
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
        if not any(f > t - M.AWAKE_WIN for f in flips):
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
        if risk <= M.S_MIN_DIST or risk * lot > M.MAX_RISK_PCT * balance:
            continue
        pos = (d, c, slp, c + d * rr * risk, i, flip)
    return trades, len(flips)


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
    print(f"  {sym}  {days:.1f} jours  spread {spread:.0f}  config en direct\n")
    ANCH, step = 6, 600
    rows = {"ANCIEN amorcage": [], "NOUVEAU amorcage": []}
    nfl = {"ANCIEN amorcage": 0, "NOUVEAU amorcage": 0}
    print(f"  {'moteur':<20}{'trades':>7}{'/jour':>7}{'reussite':>10}"
          f"{'R/trade':>10}{'R total':>9}{'$':>9}{'anc.+':>7}{'bascules':>10}")
    for lab, M in (("ANCIEN amorcage", OLD), ("NOUVEAU amorcage", NEW)):
        for a in range(ANCH):
            sub = R[a * step:]
            if len(sub) < 20000:
                break
            tr, nf = replay(M, sub, spread)
            rows[lab].append(summ(tr))
            if a == 0:
                nfl[lab] = nf
                flips_only = summ([x for x in tr if x["flip"]])
        b = rows[lab][0]
        pa = sum(1 for r in rows[lab] if r["per"] > 0)
        print(f"  {lab:<20}{b['n']:>7}{b['n']/days:>7.1f}{b['wr']:>9.1f}%"
              f"{b['per']:>+10.3f}{b['R']:>+9.1f}{b['usd']:>+9.2f}"
              f"{pa:>4}/{len(rows[lab])}{nfl[lab]:>10}")
        print(f"  {'  dont trades de bascule':<20}{flips_only['n']:>7}"
              f"{'':>7}{flips_only['wr']:>9.1f}%{flips_only['per']:>+10.3f}")
    a0, b0 = rows["ANCIEN amorcage"][0], rows["NOUVEAU amorcage"][0]
    print(f"\n  ecart nouveau - ancien : {b0['n']-a0['n']:+d} trades, "
          f"{b0['per']-a0['per']:+.3f} R/trade, {b0['usd']-a0['usd']:+.2f} $")


if __name__ == "__main__":
    main()
