"""Owner 2026-09-25: "After a flip (choc) when price breaks the protected
glowing dot, we wait 2 consecutive reversal candles and enter the trade,
SL at the pick or deep just created by that reversal, for a 1:1 or 1:1.5
RR."

This is a NEW entry mechanism for the flip/CHoCH trade specifically (not
plain-BOS continuations, not internal structure) - a candidate REPLACEMENT
for how the bot enters when eng.trend flips:

  A  today (live): enter immediately at the flip bar, SL at the broken
     structure level (slp from the signal), RR = B.RR (0.8 live)
  B  candidate: after the flip, wait for the first 2 CONSECUTIVE candles
     that move against the new trend (the pullback/reversal). Enter at
     the close of the 2nd one. SL = the low (bull) / high (bear) made by
     those 2 candles. RR tested at 1.0 and 1.5.

"2 consecutive" resets on any candle that breaks the streak - only an
unbroken pair counts. One attempt per flip: if a new flip happens before
the pullback completes, the pending setup is dropped and replaced by the
new flip's. If no pullback completes within AWAKE_WIN (2h), the setup
expires with no trade (same staleness window the live bot already uses
for continuations).

Real B.Struct()/weather_gate() generator, same dedupe/awake/risk-filter
machinery as every other entry test this project has run.

    python review/flip_pullback_entry_test.py [spread]
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
sys.argv = ["flip_pullback_entry_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SPREAD = float(_A[0]) if _A else 7.0
LOT = B.BASE_LOT


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def gate(nv_now, nv_ref, moves_2h):
    return B.weather_gate(need_int=False,
                          cj={"vol_now": nv_now, "vol_ref": nv_ref,
                              "moves_2h": moves_2h})


def simulate(R, spread, mode, rr):
    """mode: 'baseline' (live) | 'pullback' (candidate, at given rr)"""
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks = [], []
    prev = 0
    pos = None            # (d, entry, sl, tp, dist)
    run = pk = 0.0
    curve = []
    day_key = None
    trades = wins = 0
    dist_sum = 0.0

    wait_dir = wait_since = rev_extreme = None
    rev_count = 0

    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        dk = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        if dk != day_key:
            day_key = dk
            curve.append(run)

        if pos:
            d, e, sl, tp, dist = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                pts = (rr * dist - spread) if win else -(dist + spread)
                run += pts * LOT
                pk = max(pk, run)
                wins += 1 if win else 0
                pos = None

        sig = eng.step(t, o, h, l, c)
        flip_now = False
        if eng.trend != prev and eng.trend != 0:
            flips.append(t)
            prev = eng.trend
            flip_now = True
        if sig is not None:
            marks.append(t)

        nv = None
        if i >= 1440:
            nv = (sorted(rng[i-60:i])[30], sorted(rng[i-1440:i])[720])

        if mode == "baseline":
            if sig is not None and not pos:
                d, slp = sig
                flip = flip_now and bool(flips) and flips[-1] == t
                if flip and nv is not None:
                    mv2 = (bisect.bisect_left(marks, t)
                           - bisect.bisect_left(marks, t - 7200))
                    if not gate(nv[0], nv[1], mv2):
                        dist = abs(c - slp)
                        if (dist > B.S_MIN_DIST
                                and dist * LOT <= B.MAX_RISK_PCT * 230.0):
                            tp = c + d * rr * dist
                            pos = (d, c, float(slp), tp, dist)
                            trades += 1
                            dist_sum += dist
        else:  # pullback candidate
            if flip_now:
                wait_dir, wait_since = eng.trend, t
                rev_count, rev_extreme = 0, None
            elif wait_dir is not None:
                if t - wait_since > B.AWAKE_WIN:
                    wait_dir = None
                else:
                    is_rev = (c < o) if wait_dir == 1 else (c > o)
                    if is_rev:
                        ext = l if wait_dir == 1 else h
                        rev_extreme = (ext if rev_count == 0 else
                                       (min(rev_extreme, ext) if wait_dir == 1
                                        else max(rev_extreme, ext)))
                        rev_count += 1
                        if rev_count >= 2:
                            d, entry, sl = wait_dir, c, rev_extreme
                            dist = abs(entry - sl)
                            if (not pos and nv is not None
                                    and dist > B.S_MIN_DIST
                                    and dist * LOT <= B.MAX_RISK_PCT * 230.0):
                                mv2 = (bisect.bisect_left(marks, t)
                                       - bisect.bisect_left(marks, t - 7200))
                                if not gate(nv[0], nv[1], mv2):
                                    tp = entry + d * rr * dist
                                    pos = (d, entry, sl, tp, dist)
                                    trades += 1
                                    dist_sum += dist
                            wait_dir = None   # one attempt per flip
                    else:
                        rev_count, rev_extreme = 0, None

    dd = 0.0
    pk2 = 0.0
    worst_debt = 0.0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
        worst_debt = max(worst_debt, pk2 - v)
    return dict(net=run, maxdd=dd, worst_debt=worst_debt, trades=trades,
                wr=(wins / trades * 100 if trades else 0.0),
                avg_dist=(dist_sum / trades if trades else 0.0))


def run_for(R, label):
    print(f"\n  {label}  {len(R)/1440:.1f} days, spread {SPREAD:.0f}")
    a = simulate(R, SPREAD, "baseline", B.RR)
    b1 = simulate(R, SPREAD, "pullback", 1.0)
    b2 = simulate(R, SPREAD, "pullback", 1.5)
    print(f"  {'rule':<40}{'trades':>7}{'win%':>7}{'avgSL':>8}"
          f"{'net $':>9}{'worst debt':>11}")
    for lab, r in ((f"A  live: enter at flip, RR={B.RR}", a),
                   ("B  wait 2 reversal candles, RR=1.0", b1),
                   ("B  wait 2 reversal candles, RR=1.5", b2)):
        print(f"  {lab:<40}{r['trades']:>7}{r['wr']:>6.1f}%"
              f"{r['avg_dist']:>8.1f}{r['net']:>9.2f}{r['worst_debt']:>11.2f}")


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
