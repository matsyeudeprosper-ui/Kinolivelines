"""Owner 2026-09-27: "test if we can count the touch of the flip level
[the protected dot] as a count for the movement indicator (0/2h, main
structure)."

The movement gate (weather_gate, main structure): an entry is refused when
no main-structure break happened in the last 2 h ("aucun grand mouvement
depuis 2 h"). Candidate: a TOUCH of the protected dot (raw bar's wick
reaches the dot in force, close stays on the trend's side - the same
definition deployed today for the recovery re-arm) also counts as a
movement. One touch EPISODE counts once (consecutive touching bars are one
episode).

  A  deployed (incl. today's touch re-arm of the recovery continuation)
  B  A + touch episodes count toward the 2 h movement gate

Real B.Struct() generator; same recovery/bullet machinery as
review/recovery_touch_rearm_test.py.

    python review/touch_as_movement_test.py [spread]
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
sys.argv = ["touch_as_movement_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SPREAD = float(_A[0]) if _A else 7.0
LOT = 0.02
BLOT = 0.01
NB = 3.0
K = 2


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def simulate(R, spread, touch_moves):
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, tmarks = [], [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    run = pk = 0.0
    streak = 0
    curve = []
    day_key = None
    last_flip_t = None
    cont_used = True
    was_touching = False
    n_trades = n_opened_by_touch = 0
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        dk = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        if dk != day_key:
            day_key = dk
            curve.append(run)
        if pos:
            d, e, sl, tp, dist, mid, hit_mid = pos
            if not hit_mid and ((l <= mid) if d == 1 else (h >= mid)):
                hit_mid = True
                pos = (d, e, sl, tp, dist, mid, hit_mid)
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                pts = (B.RR * dist - spread) if win else -(dist + spread)
                debt = max(0.0, pk - run)
                run += pts * LOT
                fire = debt > 0.5 and streak < K
                if fire and hit_mid:
                    bpts = ((1.3 * dist - spread) if win
                            else -(dist / 2.0 + spread))
                    run += bpts * BLOT * NB
                streak = 0 if win else streak + 1
                pk = max(pk, run)
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
        if touched:
            if not was_touching:
                tmarks.append(t)          # one episode = one movement
            if cont_used and last_flip_t is not None:
                cont_used = False         # deployed 2026-09-27 re-arm
        was_touching = touched
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
            mv_main = (bisect.bisect_left(marks, t)
                       - bisect.bisect_left(marks, t - 7200))
            mv_touch = (bisect.bisect_left(tmarks, t)
                        - bisect.bisect_left(tmarks, t - 7200))
            mv2 = mv_main + (mv_touch if touch_moves else 0)
            if nv >= B.NERV_STORM or mv2 < 1:
                continue
            opened_by_touch = touch_moves and mv_main < 1
        else:
            opened_by_touch = False
        debt_now = max(0.0, pk - run)
        if flip:
            last_flip_t = t
            cont_used = False
        elif debt_now > 0.5:
            if not cont_used and last_flip_t is not None:
                cont_used = True
            else:
                continue
        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        tp = c + d * B.RR * dist
        pos = (d, c, float(slp), tp, dist, c - d * dist / 2.0, False)
        n_trades += 1
        if opened_by_touch:
            n_opened_by_touch += 1
    dd = 0.0
    pk2 = 0.0
    worst_debt = 0.0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
        worst_debt = max(worst_debt, pk2 - v)
    return dict(net=run, maxdd=dd, worst_debt=worst_debt, trades=n_trades,
                opened=n_opened_by_touch, episodes=len(tmarks))


def run_for(R, label):
    print(f"\n  {label}  {len(R)/1440:.1f} days, spread {SPREAD:.0f}")
    a = simulate(R, SPREAD, False)
    b = simulate(R, SPREAD, True)
    print(f"  {'rule':<48}{'trades':>7}{'net $':>9}{'max DD':>9}"
          f"{'worst debt':>11}{'gate opened by touch':>22}")
    for lab, r in (("A  deployed (touch re-arm included)", a),
                   ("B  + touch episodes count as a movement", b)):
        print(f"  {lab:<48}{r['trades']:>7}{r['net']:>9.2f}{r['maxdd']:>9.2f}"
              f"{r['worst_debt']:>11.2f}{r['opened']:>22}")
    print(f"    A vs B: {a['net']-b['net']:+.2f} net, {a['maxdd']-b['maxdd']:+.2f} DD, "
          f"{a['worst_debt']-b['worst_debt']:+.2f} worst debt  "
          f"(touch episodes: {b['episodes']})")


def main():
    sym, R = bars()
    run_for(R, f"{sym} FULL PERIOD")
    print("\n  HALVES (each independently)")
    mid = len(R) // 2
    run_for(R[:mid], "FIRST HALF")
    run_for(R[mid:], "SECOND HALF")
    print()


if __name__ == "__main__":
    main()
