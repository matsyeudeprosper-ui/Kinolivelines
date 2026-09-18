"""Is the nervosity gate better than no gate? Tested the way that catches
a false positive.

Three findings were retracted in this project on 2026-09-17 because they
were measured with the window held FIXED. Permutation and random-direction
controls cannot see anchor sensitivity: the silence filter chains from its
first bar, so starting the replay one bar earlier rebuilds every candle,
every dot and every signal. A rule that only works on one starting point
is not a rule.

So this measures the gate PAIRED within each anchor - same bars, same
engine, gate on vs gate off - and then asks whether the difference keeps
its sign across anchors and across both halves of the sample.

Costs are included: a trade pays the spread on the way in and out.

    python review/nerv_gate_test.py [anchors] [spread_points]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
sys.argv = ["nerv_gate_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

import bisect                          # noqa: E402
import json                            # noqa: E402


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


def replay(R, use_gate, spread, lot=0.02, balance=230.0):
    """One pass. Returns the list of trades, each with its R after costs."""
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
            d, e, sl, tp, oi = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                dist = abs(e - sl)
                win = bool(hit_tp and not hit_sl)
                # the spread is paid whichever way it ends
                pts = (B.RR * dist - spread) if win else -(dist + spread)
                trades.append({"t": t, "R": pts / dist, "win": win,
                               "usd": pts * lot, "dist": dist})
                pos = None

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
        if not flip:
            lvl = eng.hi_v if d == 1 else eng.lo_v
            if (d == 1 and used_hi == lvl) or (d == -1 and used_lo == lvl):
                continue
            if d == 1:
                used_hi = lvl
            else:
                used_lo = lvl
        if use_gate and i >= 1440:
            nv = (sorted(rng[i - 60:i])[30]
                  / max(sorted(rng[i - 1440:i])[720], 1e-9))
            mv2 = (bisect.bisect_left(marks, t)
                   - bisect.bisect_left(marks, t - 7200))
            # ONLY the nervosity half is under test here; the movement rule
            # stays on in both arms so the comparison isolates one thing
            if nv > 1.0:
                continue
            if mv2 < 1:
                continue
        elif i >= 1440:
            mv2 = (bisect.bisect_left(marks, t)
                   - bisect.bisect_left(marks, t - 7200))
            if mv2 < 1:
                continue
        if pos:
            continue
        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST:
            continue
        if dist * lot > B.MAX_RISK_PCT * balance:
            continue
        pos = (d, c, slp, c + d * B.RR * dist, i)
    return trades


def summ(tr):
    if not tr:
        return dict(n=0, R=0.0, per=0.0, wr=0.0, usd=0.0)
    R = sum(x["R"] for x in tr)
    return dict(n=len(tr), R=R, per=R / len(tr),
                wr=100 * sum(1 for x in tr if x["win"]) / len(tr),
                usd=sum(x["usd"] for x in tr))


def main():
    n_anchor = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    spread = float(sys.argv[2]) if len(sys.argv) > 2 else 7.0
    sym, R = bars()
    print(f"  {sym}  {len(R)} bougies M1 = {len(R)/60/24:.1f} jours"
          f"   spread {spread:.0f} points\n")
    step = 400
    print(f"  {'depart':>7}{'SANS frein':>26}{'AVEC frein':>26}"
          f"{'ecart R/trade':>15}")
    print(f"  {'':7}{'n':>6}{'R':>9}{'R/trade':>11}"
          f"{'n':>6}{'R':>9}{'R/trade':>11}{'':15}")
    diffs, rows = [], []
    for a in range(n_anchor):
        off = a * step
        sub = R[off:]
        if len(sub) < 20000:
            break
        off_tr = summ(replay(sub, False, spread))
        on_tr = summ(replay(sub, True, spread))
        d = on_tr["per"] - off_tr["per"]
        diffs.append(d)
        rows.append((off, off_tr, on_tr, d))
        print(f"  {off:>7}{off_tr['n']:>6}{off_tr['R']:>9.1f}"
              f"{off_tr['per']:>11.3f}"
              f"{on_tr['n']:>6}{on_tr['R']:>9.1f}{on_tr['per']:>11.3f}"
              f"{d:>+15.3f}")
    pos = sum(1 for d in diffs if d > 0)
    print(f"\n  le frein aide sur {pos}/{len(diffs)} ancrages")
    print(f"  ecart moyen R/trade : {sum(diffs)/len(diffs):+.3f}")
    print(f"  pire / meilleur     : {min(diffs):+.3f} / {max(diffs):+.3f}")

    # both halves, on the natural anchor
    print("\n  --- les deux moities (ancrage 0) ---")
    half = len(R) // 2
    for lab, sub in (("1re moitie", R[:half]), ("2e moitie", R[half:])):
        a, b = summ(replay(sub, False, spread)), summ(replay(sub, True, spread))
        print(f"  {lab:<12} sans {a['R']:>7.1f}R ({a['per']:+.3f}/trade, "
              f"{a['n']:>3}) | avec {b['R']:>7.1f}R ({b['per']:+.3f}/trade, "
              f"{b['n']:>3}) | ecart {b['per']-a['per']:+.3f}")

    print("\n  --- sensibilite au spread (ancrage 0) ---")
    for sp in (0.0, 7.0, 15.0):
        a, b = summ(replay(R, False, sp)), summ(replay(R, True, sp))
        print(f"  spread {sp:>4.0f} pts : sans {a['per']:+.3f}/trade"
              f"  avec {b['per']:+.3f}/trade  ecart {b['per']-a['per']:+.3f}"
              f"   ($ {a['usd']:+.2f} vs {b['usd']:+.2f})")


if __name__ == "__main__":
    main()
