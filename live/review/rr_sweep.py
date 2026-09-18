"""Where should the TP be measured from, and at what RR?

Owner 2026-09-18: "the RR is calculated from the broker entry. But I'd
like to take it from the BOS level. Even if we enter late because of the
confirmation candle I still want the RR from the BOS level - that means
the TP will be shorter, that's fine, quick exit. Also test a few TP RR to
see which gives higher profit and win rate."

Two anchors for the target:
  ENTREE  tp = entry + d * RR * (entry - stop)        <- what runs today
  BOS     tp = bos   + d * RR * (bos   - stop)        <- what is asked

The RISK is the same either way - entry to stop - because that is what the
broker takes. Only the target moves. A BOS-anchored target is nearer, so
it wins more often and earns less per win; the point of the test is
whether that trade is worth making.

Every configuration is run across several window anchors. The silence
filter chains from its first bar, so a different start rebuilds every
candle and signal - three findings died in this project for being tested
on one anchor only.

    python review/rr_sweep.py [spread_points]
"""
import bisect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
sys.argv = ["rr_sweep"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

RRS = (0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0)


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


def replay(R, rr, anchor, spread, gate=True, lot=0.02, balance=230.0):
    """anchor: 'entry' or 'bos'. Returns the trade list."""
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
            d, e, sl, tp, oi, late = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                risk = abs(e - sl)          # the broker's risk, always
                win = bool(hit_tp and not hit_sl)
                pts = ((tp - e) * d - spread) if win else -(risk + spread)
                trades.append({"R": pts / risk, "win": win,
                               "usd": pts * lot, "late": late,
                               "mins": i - oi})
                pos = None

        # the BOS level is the extreme as it stood BEFORE this bar, exactly
        # as the bot captures it
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
        if anchor == "bos" and lvl is not None:
            base = lvl
            span = abs(lvl - slp)
        else:
            base, span = c, risk
        if span <= 0:
            continue
        tp = base + d * rr * span
        # a target already behind price is an instant fill at entry: skip,
        # the bot would never place it
        if (d == 1 and tp <= c) or (d == -1 and tp >= c):
            continue
        pos = (d, c, slp, tp, i, abs(c - lvl) if lvl is not None else 0.0)
    return trades


def summ(tr):
    if not tr:
        return dict(n=0, R=0.0, per=0.0, wr=0.0, usd=0.0)
    return dict(n=len(tr), R=sum(x["R"] for x in tr),
                per=sum(x["R"] for x in tr) / len(tr),
                wr=100 * sum(1 for x in tr if x["win"]) / len(tr),
                usd=sum(x["usd"] for x in tr))


def main():
    spread = float(sys.argv[1]) if len(sys.argv) > 1 else 7.0
    sym, R = bars()
    days = len(R) / 60 / 24
    print(f"  {sym}  {len(R)} bougies M1 = {days:.1f} jours"
          f"   spread {spread:.0f} pts\n")

    tr = replay(R, 0.8, "entry", spread)
    if tr:
        lt = sorted(x["late"] for x in tr)
        print(f"  RETARD D'ENTREE (prix d'entree - niveau du BOS)")
        print(f"    median {lt[len(lt)//2]:.0f} pts,  moyen "
              f"{sum(lt)/len(lt):.0f} pts,  pire {lt[-1]:.0f} pts")
        st = sorted(abs(x["R"]) for x in tr)
        print()

    ANCH = 6
    step = 600
    for anchor in ("entry", "bos"):
        lbl = "TP depuis l'ENTREE (actuel)" if anchor == "entry" \
            else "TP depuis le NIVEAU DU BOS (demande)"
        print(f"  === {lbl} ===")
        print(f"  {'RR':>5}{'trades':>8}{'reussite':>10}{'R/trade':>10}"
              f"{'R total':>10}{'$':>10}{'ancrages +':>12}")
        for rr in RRS:
            rows = []
            for a in range(ANCH):
                sub = R[a * step:]
                if len(sub) < 20000:
                    break
                rows.append(summ(replay(sub, rr, anchor, spread)))
            base = rows[0]
            pos_anch = sum(1 for r in rows if r["per"] > 0)
            print(f"  {rr:>5.1f}{base['n']:>8}{base['wr']:>9.1f}%"
                  f"{base['per']:>+10.3f}{base['R']:>+10.1f}"
                  f"{base['usd']:>+10.2f}{pos_anch:>8}/{len(rows)}")
        print()


if __name__ == "__main__":
    main()
