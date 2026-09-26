"""Owner 2026-09-25: after testing "wait 2 reversal candles then enter"
(review/flip_pullback_entry_test.py, REJECTED both directions tried), the
owner asked for a structural version instead of counting candles: "test
first BOS that happens in direction of reversal candles after the flip,
even if it's in the internal structure."

So: after a main-structure flip (choc), don't count candles at all - wait
for the first actual BREAK OF STRUCTURE in the reversal direction (the
direction opposite the choc's own new trend), whether that break comes
from the MAIN structure engine (which would itself be the next re-flip
back) or from the INTERNAL structure engine (a smaller, faster break
nested inside the still-standing new main trend - internal_structure()
does NOT require internal to agree with main here, that's the whole point:
we WANT internal disagreeing with main, that disagreement is the signal).

  A  today (live): enter WITH the flip, immediately at the flip bar
  B  candidate: after the flip, wait for the first main-BOS OR
     internal-BOS in the reversal direction. Enter at that break's own
     close, SL at that break's own natural level (slp for main, iinv for
     internal - exactly what each engine already uses for its own
     trades). RR tested at 1.0 and 1.5.

One attempt per flip (consumed on the first qualifying break whether or
not it survives the risk/weather filters - a missed opportunity is not
retried). Timeout AWAKE_WIN (2h), same convention as every other test.
Real B.Struct()/F.internal_structure()/weather_gate() generator, same
pinned-window internal-track harness as the other internal tests.

    python review/flip_reversal_bos_entry_test.py [spread]
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
sys.argv = ["flip_reversal_bos_entry_test"]

import MetaTrader5 as mt5              # noqa: E402
import owl_chart_feed as F             # noqa: E402
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


def build_internal_track(kept, warmup=300):
    pin = {"t0": None, "start": None}
    times, trend, inv, inv_t, brk1h = [], [], [], [], []
    for j in range(warmup, len(kept)):
        pre = kept[:j + 1]
        r = F.engine(pre)
        nxt, iv, nxt_t, ivt, mflp = r[4], r[5], r[6], r[7], r[9]
        marks = r[1]
        res = F.internal_structure(pre, nxt, iv, ivt, mflp, marks, nxt_t,
                                   pre[-1][0], pin=pin)
        times.append(pre[-1][0])
        trend.append(res["i_trend"])
        inv.append(res["i_inv"])
        inv_t.append(res["i_inv_t"])
        brk1h.append(res["i_brk1h"])
    return times, trend, inv, inv_t, brk1h


def gate(need_int, nv_now, nv_ref, moves_1h_or_2h):
    cj = {"vol_now": nv_now, "vol_ref": nv_ref}
    if need_int:
        cj["int_brk_1h"] = moves_1h_or_2h
    else:
        cj["moves_2h"] = moves_1h_or_2h
    return B.weather_gate(need_int=need_int, cj=cj)


def simulate(R, kt, itrend, iinv, iinv_t, ibrk1h, spread, mode, rr):
    """mode: 'baseline' (live) | 'reversal_bos' (candidate, at given rr)"""
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
    from_int = 0
    ki = 0
    last_int_t = None
    wait_dir = wait_since = None

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

        while ki + 1 < len(kt) and kt[ki + 1] <= t:
            ki += 1
        have_track = kt and kt[0] <= t
        new_int_event = bool(have_track and iinv_t[ki]
                              and iinv_t[ki] != last_int_t)
        if new_int_event:
            last_int_t = iinv_t[ki]

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
                    if not gate(False, nv[0], nv[1], mv2):
                        dist = abs(c - slp)
                        if (dist > B.S_MIN_DIST
                                and dist * LOT <= B.MAX_RISK_PCT * 230.0):
                            tp = c + d * B.RR * dist
                            pos = (d, c, float(slp), tp, dist)
                            trades += 1
                            dist_sum += dist
        else:  # reversal_bos candidate
            if flip_now:
                wait_dir, wait_since = -eng.trend, t
            elif wait_dir is not None:
                if t - wait_since > B.AWAKE_WIN:
                    wait_dir = None
                else:
                    entry = sl = None
                    need_int = False
                    if new_int_event and itrend[ki] == wait_dir:
                        entry, sl, need_int = c, iinv[ki], True
                    elif sig is not None and sig[0] == wait_dir:
                        entry, sl = c, float(sig[1])
                    if entry is not None:
                        d = wait_dir
                        dist = abs(entry - sl)
                        if (not pos and nv is not None
                                and dist > B.S_MIN_DIST
                                and dist * LOT <= B.MAX_RISK_PCT * 230.0):
                            mv = (ibrk1h[ki] if need_int else
                                  bisect.bisect_left(marks, t)
                                  - bisect.bisect_left(marks, t - 7200))
                            if not gate(need_int, nv[0], nv[1], mv):
                                tp = entry + d * rr * dist
                                pos = (d, entry, sl, tp, dist)
                                trades += 1
                                dist_sum += dist
                                from_int += 1 if need_int else 0
                        wait_dir = None   # one attempt per flip

    dd = 0.0
    pk2 = 0.0
    worst_debt = 0.0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
        worst_debt = max(worst_debt, pk2 - v)
    return dict(net=run, maxdd=dd, worst_debt=worst_debt, trades=trades,
                wr=(wins / trades * 100 if trades else 0.0),
                avg_dist=(dist_sum / trades if trades else 0.0),
                from_int=from_int)


def run_for(R, kt, itrend, iinv, iinv_t, ibrk1h, label):
    print(f"\n  {label}  {len(R)/1440:.1f} days, spread {SPREAD:.0f}")
    a = simulate(R, kt, itrend, iinv, iinv_t, ibrk1h, SPREAD, "baseline", B.RR)
    b1 = simulate(R, kt, itrend, iinv, iinv_t, ibrk1h, SPREAD, "reversal_bos", 1.0)
    b2 = simulate(R, kt, itrend, iinv, iinv_t, ibrk1h, SPREAD, "reversal_bos", 1.5)
    print(f"  {'rule':<38}{'trades':>7}{'int%':>6}{'win%':>7}{'avgSL':>8}"
          f"{'net $':>9}{'worst debt':>11}")
    for lab, r in ((f"A  live: enter at flip, RR={B.RR}", a),
                   ("B  first BOS in reversal dir, RR=1.0", b1),
                   ("B  first BOS in reversal dir, RR=1.5", b2)):
        intpct = (r['from_int'] / r['trades'] * 100) if r['trades'] else 0.0
        print(f"  {lab:<38}{r['trades']:>7}{intpct:>5.0f}%{r['wr']:>6.1f}%"
              f"{r['avg_dist']:>8.1f}{r['net']:>9.2f}{r['worst_debt']:>11.2f}")


def main():
    sym, R = bars()
    kept = F.build(R)
    days = len(R) / 1440
    print(f"\n  {sym}  {days:.1f} days, {len(R)} raw / {len(kept)} kept, "
          f"spread {SPREAD:.0f}\n  building the internal track "
          f"(slow part, built ONCE, reused for all halves/rr)...", flush=True)
    times, itrend, iinv, iinv_t, ibrk1h = build_internal_track(kept)
    print(f"  done: {len(times)} kept-candle steps", flush=True)

    def track_slice(t0):
        j = bisect.bisect_left(times, t0)
        return (times[j:], itrend[j:], iinv[j:], iinv_t[j:], ibrk1h[j:])

    run_for(R, times, itrend, iinv, iinv_t, ibrk1h, f"{sym} FULL PERIOD")
    print("\n  HALVES (each independently)")
    mid = len(R) // 2
    t_mid = int(R[mid]["time"])
    kt2, it2, iv2, ivt2, ib2 = track_slice(t_mid)
    run_for(R[:mid], times, itrend, iinv, iinv_t, ibrk1h, "FIRST HALF")
    run_for(R[mid:], kt2, it2, iv2, ivt2, ib2, "SECOND HALF")
    print()


if __name__ == "__main__":
    main()
