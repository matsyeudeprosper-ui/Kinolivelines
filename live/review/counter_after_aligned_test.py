"""Internal counter-trend trade, but ONLY when it follows an aligned one.

Owner 2026-09-23: "if in an internal structure I only look for counter
trades against the main structure trend, but only having seen a trade of
the same trend pass. That way the counter-trend trade comes right after
the reversal."

Different from the 2026-09-22 counter-trend-internal test (which took
EVERY counter-trend internal signal and found no advantage, worse
dollars). This is narrower: watch the internal structure's own signal
sequence, and take a counter-trend signal ONLY when the immediately
PRECEDING internal signal was aligned with the main trend - i.e. internal
structure confirmed the main direction, then reversed. The reversal is
what gets traded, not a counter-trend signal in isolation.

Built on the same combined simulation as internal_trades_test.py (real
owl_chart_feed.internal_structure(), one shared position slot, today's
live gates). Aligned-internal trading is left exactly as it runs today;
this only ADDS the narrow counter-trend case as its own tracked group, so
its own quality can be read without changing what already exists.

SCALE: 30000 raw M1 bars (~20.8 days) - same O(n^2) constraint as the
other internal-track scripts. Run in background.

    python review/counter_after_aligned_test.py [spread]
"""
import bisect
import json
import os
import statistics as st
import sys

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIVE)
_A = sys.argv[1:]

import MetaTrader5 as mt5              # noqa: E402
import owl_chart_feed as F             # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SP = float(_A[0]) if _A else 7.0
LOT = B.BASE_LOT
BAL = 230.0


def bars(n=30000):
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


def main():
    sym, R = bars()
    kept = F.build(R)
    days = len(R) / 1440
    print(f"\n  {sym}  {days:.1f} days, {len(R)} raw / {len(kept)} kept, "
          f"spread {SP:.0f}\n  building the internal track "
          f"(this is the slow part)...", flush=True)
    times, itrend, iinv, iinv_t, ibrk1h = build_internal_track(kept)
    print(f"  done: {len(times)} kept-candle steps\n", flush=True)

    rng = [float(r["high"]) - float(r["low"]) for r in R]
    eng = B.Struct()
    eng.quiet = True
    flips, marks_main = [], []
    prev = 0
    used_hi = used_lo = None
    last_int_t = None
    last_int_aligned = None    # was the MOST RECENT internal signal
                                # aligned with the main trend at its time?
    pos = None
    trades = []

    kt = list(times)
    ki = 0

    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        if pos:
            kind, d, e, sl, tp, dist = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                pts = (B.RR * dist - SP) if win else -(dist + SP)
                trades.append({"kind": kind, "t": t, "R": pts / dist,
                               "win": win, "usd": pts * LOT})
                pos = None

        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev and eng.trend != 0:
            flips.append(t)
            prev = eng.trend
        if sig is not None:
            marks_main.append(t)

        while ki + 1 < len(kt) and kt[ki + 1] <= t:
            ki += 1
        have_track = kt and kt[0] <= t

        nv = None
        if i >= 1440:
            nv = (sorted(rng[i - 60:i])[30], sorted(rng[i - 1440:i])[720])

        # --- INTERNAL, checked FIRST each bar, as the live bot does -----
        if have_track and iinv_t[ki] and iinv_t[ki] != last_int_t:
            last_int_t = iinv_t[ki]
            aligned_now = (itrend[ki] != 0 and itrend[ki] == eng.trend)
            counter_now = (itrend[ki] != 0 and itrend[ki] == -eng.trend)
            take_kind = None
            if not pos and nv is not None:
                if aligned_now:
                    take_kind = "INT"
                elif counter_now and last_int_aligned is True:
                    # the narrow case: a counter-trend signal that comes
                    # right after an aligned one
                    take_kind = "COUNTER"
            if take_kind and not pos:
                g = gate(True, nv[0], nv[1], ibrk1h[ki])
                if not g:
                    dist = abs(c - iinv[ki])
                    if (dist > B.S_MIN_DIST
                            and dist * LOT <= B.MAX_RISK_PCT * BAL):
                        tp = c + itrend[ki] * B.RR * dist
                        pos = (take_kind, itrend[ki], c, float(iinv[ki]),
                               tp, dist)
            # update the alignment memory AFTER deciding, using this
            # signal's own alignment - whether or not it was traded
            if aligned_now:
                last_int_aligned = True
            elif counter_now:
                last_int_aligned = False

        # --- MAIN, second, same position slot ---------------------------
        if sig is not None and not pos:
            if any(f > t - B.AWAKE_WIN for f in flips):
                d, slp = sig
                flip = bool(flips) and flips[-1] == t
                ok_dedupe = True
                if not flip:
                    lvl = eng.hi_v if d == 1 else eng.lo_v
                    if (d == 1 and used_hi == lvl) or \
                       (d == -1 and used_lo == lvl):
                        ok_dedupe = False
                    elif d == 1:
                        used_hi = lvl
                    else:
                        used_lo = lvl
                if ok_dedupe and nv is not None:
                    g = gate(False, nv[0], nv[1],
                            bisect.bisect_left(marks_main, t)
                            - bisect.bisect_left(marks_main, t - 7200))
                    if not g:
                        dist = abs(c - slp)
                        if (dist > B.S_MIN_DIST
                                and dist * LOT <= B.MAX_RISK_PCT * BAL):
                            tp = c + d * B.RR * dist
                            pos = ("MAIN", d, c, float(slp), tp, dist)

    def summ(tr):
        if not tr:
            return None
        r = [x["R"] for x in tr]
        se = st.pstdev(r) / len(r) ** 0.5 if len(r) > 1 else 0.0
        per = sum(r) / len(r)
        return dict(n=len(tr), per=per, se=se,
                    wr=100 * sum(1 for x in tr if x["win"]) / len(tr),
                    usd=sum(x["usd"] for x in tr))

    main_tr = [x for x in trades if x["kind"] == "MAIN"]
    int_tr = [x for x in trades if x["kind"] == "INT"]
    ctr_tr = [x for x in trades if x["kind"] == "COUNTER"]
    print(f"  {'group':<38}{'trades':>7}{'win%':>8}{'R/trade':>10}"
          f"{'95% CI':>20}{'$':>9}")
    for lab, tr in (("MAIN", main_tr),
                    ("INTERNAL aligned (today's rule)", int_tr),
                    ("COUNTER after an aligned one (new)", ctr_tr)):
        s2 = summ(tr)
        if not s2:
            print(f"  {lab:<38}{'-':>7}   none")
            continue
        lo, hi = s2["per"] - 1.96 * s2["se"], s2["per"] + 1.96 * s2["se"]
        print(f"  {lab:<38}{s2['n']:>7}{s2['wr']:>7.1f}%"
              f"{s2['per']:>+10.3f}   [{lo:+.3f},{hi:+.3f}]{s2['usd']:>9.2f}")

    if ctr_tr:
        mid = sorted(x["t"] for x in ctr_tr)[len(ctr_tr) // 2]
        h1 = summ([x for x in ctr_tr if x["t"] < mid])
        h2 = summ([x for x in ctr_tr if x["t"] >= mid])
        print("\n  THE TWO HALVES (counter-after-aligned)")
        if h1 and h2:
            ag = "agree" if (h1["per"] > 0) == (h2["per"] > 0) else "DISAGREE"
            print(f"    1st {h1['per']:+.3f} ({h1['n']:>3})   "
                  f"2nd {h2['per']:+.3f} ({h2['n']:>3})   {ag}")
        else:
            print("    too few to split")
    print()


if __name__ == "__main__":
    main()
