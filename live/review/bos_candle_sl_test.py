"""Owner 2026-09-27: "Entry at the BOS confirmation candle and SL at the low
of that candle, then give me results for 1:1 and 1:1.5 and 1:2 RR."

Today (live): a BOS is confirmed by the M1 candle whose close breaks the
level; the bot enters at that close and puts the stop at the structure's
own level (slp: the protected dot / swing the engine hands back), TP at
B.RR times that distance.

Candidate: same entry candle, same close, but the stop sits at the LOW of
the confirmation candle for a buy (HIGH for a sell) - a much tighter
stop - with TP at 1.0, 1.5 and 2.0 times that smaller distance.

Everything else is the live rule set, unchanged for both:
  - AWAKE_WIN: a signal only counts within 2 h of the last flip
  - one trade per broken level (used_hi / used_lo)
  - storm exception (nervosity >= NERV_STORM) and the 2 h movement rule
  - S_MIN_DIST (a stop closer than this is refused) and the risk cap
  - recovery as deployed: while in debt, plain BOS refused except the one
    continuation re-armed by a flip or by a touch of the protected dot
  - no bullets / jar (money management, not entry geometry)

Real B.Struct() / B.weather_gate() generator, same replay as
review/recovery_touch_rearm_test.py. Full period plus two independent
halves; spread as argument (7 default, 10 for the cautious view).

    python review/bos_candle_sl_test.py [spread]
"""
import bisect
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["bos_candle_sl_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SPREAD = float(_A[0]) if _A else 7.0
LOT = 0.02


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def simulate(R, spread, candle_sl, rr):
    """candle_sl False -> live stop (structure level, TP at B.RR)
       candle_sl True  -> stop at the confirmation candle's low/high, TP at rr"""
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks = [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    run = pk = 0.0
    curve = []
    day_key = None
    last_flip_t = None
    cont_used = True
    n_trades = wins = 0
    n_tight = n_risk = 0
    dist_sum = 0.0
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        dk = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        if dk != day_key:
            day_key = dk
            curve.append(run)
        if pos:
            d, e, sl, tp, dist, r_ = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                pts = (r_ * dist - spread) if win else -(dist + spread)
                run += pts * LOT
                pk = max(pk, run)
                wins += 1 if win else 0
                pos = None
        touched = False
        if eng.trend == 1 and eng.prot_lo is not None:
            touched = l <= eng.prot_lo[1] <= c
        elif eng.trend == -1 and eng.prot_hi is not None:
            touched = c <= eng.prot_hi[1] <= h
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev and eng.trend != 0:
            flips.append(t)
            prev = eng.trend
        if sig is not None:
            marks.append(t)
        if touched and cont_used and last_flip_t is not None:
            cont_used = False
        if sig is None or pos:
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
        if i >= 1440:
            nv = (sorted(rng[i-60:i])[30]
                  / max(sorted(rng[i-1440:i])[720], 1e-9))
            mv2 = (bisect.bisect_left(marks, t)
                   - bisect.bisect_left(marks, t - 7200))
            if nv >= B.NERV_STORM or mv2 < 1:
                continue
        debt_now = max(0.0, pk - run)
        if flip:
            last_flip_t = t
            cont_used = False
        elif debt_now > 0.5:
            if not cont_used and last_flip_t is not None:
                cont_used = True
            else:
                continue
        if candle_sl:
            sl = l if d == 1 else h
            r_ = rr
        else:
            sl = float(slp)
            r_ = B.RR
        dist = abs(c - sl)
        if dist <= B.S_MIN_DIST:
            n_tight += 1
            continue
        if dist * LOT > B.MAX_RISK_PCT * 230.0:
            n_risk += 1
            continue
        tp = c + d * r_ * dist
        pos = (d, c, sl, tp, dist, r_)
        n_trades += 1
        dist_sum += dist
    dd = 0.0
    pk2 = 0.0
    worst_debt = 0.0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
        worst_debt = max(worst_debt, pk2 - v)
    return dict(net=run, maxdd=dd, worst_debt=worst_debt, trades=n_trades,
                wr=(wins / n_trades * 100 if n_trades else 0.0),
                avg_dist=(dist_sum / n_trades if n_trades else 0.0),
                tight=n_tight, risk=n_risk)


def run_for(R, label):
    print(f"\n  {label}  {len(R)/1440:.1f} days, spread {SPREAD:.0f}")
    rows = [(f"A  live: SL at structure, RR={B.RR}", simulate(R, SPREAD, False, B.RR))]
    for rr in (1.0, 1.5, 2.0):
        rows.append((f"B  SL at candle low/high, RR={rr}", simulate(R, SPREAD, True, rr)))
    print(f"  {'rule':<38}{'trades':>7}{'tight':>6}{'win%':>7}{'avgSL':>7}"
          f"{'net $':>9}{'max DD':>9}{'worst debt':>11}")
    for lab, r in rows:
        print(f"  {lab:<38}{r['trades']:>7}{r['tight']:>6}{r['wr']:>6.1f}%"
              f"{r['avg_dist']:>7.1f}{r['net']:>9.2f}{r['maxdd']:>9.2f}"
              f"{r['worst_debt']:>11.2f}")


def main():
    sym, R = bars()
    print(f"  S_MIN_DIST={B.S_MIN_DIST}  live RR={B.RR}  lot {LOT}  "
          f"risk cap {B.MAX_RISK_PCT*230.0:.2f} $/trade")
    run_for(R, f"{sym} FULL PERIOD")
    print("\n  HALVES (each independently)")
    mid = len(R) // 2
    run_for(R[:mid], "FIRST HALF")
    run_for(R[mid:], "SECOND HALF")
    print()


if __name__ == "__main__":
    main()
