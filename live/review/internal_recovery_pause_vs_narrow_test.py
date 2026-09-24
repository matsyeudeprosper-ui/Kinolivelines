"""Owner 2026-09-24: demo's real drawdown is driven mostly by INTERNAL
structure trades (-$21.99 of its real losses, the single biggest
source), but the deployed recovery rule only restricts plain BOS -
internal keeps trading normally even while in debt. "Test whether to
narrow or paused entirely."

Three variants for internal structure specifically, only while debt >
0.5 (main structure keeps the already-deployed FLIP-BOS-only rule in
ALL THREE, unchanged - this test isolates the internal-structure
question only):

  A  today (deployed): internal trades normally, even in debt
  B  PAUSED: no internal trades at all while in debt
  C  NARROWED: internal trades only when the market is calm
     (nervosity <= 1.00x) - the SAME "calm" concept already used
     elsewhere in this bot for the midpoint bullet add, not a new idea

Real internal_structure() engine via the same pinned-window harness as
internal_flip_only_test.py - the internal track is built ONCE and
reused for all three passes (it is the expensive O(n^2) part).

    python review/internal_recovery_pause_vs_narrow_test.py [spread]
"""
import bisect
import json
import os
import sys

LIVE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LIVE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]

import MetaTrader5 as mt5              # noqa: E402
import owl_chart_feed as F             # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SP = float(_A[0]) if _A else 7.0
LOT = B.BASE_LOT
BLOT = 0.01
NB = 3.0
K = 2


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


def simulate(R, kt, itrend, iinv, iinv_t, ibrk1h, internal_mode):
    """internal_mode: 'normal' | 'pause' | 'narrow' - applies only while
    debt > 0.5. Main structure keeps the deployed FLIP-BOS-only-in-debt
    rule in every mode (unchanged, not what's being tested here)."""
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    eng = B.Struct()
    eng.quiet = True
    flips, marks_main = [], []
    prev = 0
    used_hi = used_lo = None
    last_int_t = None
    pos = None          # (kind, d, e, sl, tp, dist, mid, hit_mid)
    run = pk = 0.0
    streak = 0
    curve = []
    day_key = None

    ki = 0
    from datetime import datetime, timezone

    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        dk = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        if dk != day_key:
            day_key = dk
            curve.append(run)

        if pos:
            kind, d, e, sl, tp, dist, mid, hit_mid = pos
            if not hit_mid and ((l <= mid) if d == 1 else (h >= mid)):
                hit_mid = True
                pos = (kind, d, e, sl, tp, dist, mid, hit_mid)
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                pts = (B.RR * dist - SP) if win else -(dist + SP)
                debt = max(0.0, pk - run)
                run += pts * LOT
                fire = debt > 0.5 and streak < K
                if fire and hit_mid:
                    bpts = ((1.3 * dist - SP) if win
                            else -(dist / 2.0 + SP))
                    run += bpts * BLOT * NB
                streak = 0 if win else streak + 1
                pk = max(pk, run)
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
        nerv = None
        if i >= 1440:
            nv = (sorted(rng[i - 60:i])[30], sorted(rng[i - 1440:i])[720])
            nerv = nv[0] / max(nv[1], 1e-9)

        debt_now = max(0.0, pk - run)

        # --- INTERNAL, checked first, as live does ----------------------
        if have_track and iinv_t[ki] and iinv_t[ki] != last_int_t:
            last_int_t = iinv_t[ki]
            aligned_now = (itrend[ki] != 0 and itrend[ki] == eng.trend)
            allowed = True
            if debt_now > 0.5:
                if internal_mode == "pause":
                    allowed = False
                elif internal_mode == "narrow":
                    allowed = nerv is not None and nerv <= 1.00
            if not pos and nv is not None and aligned_now and allowed:
                g = gate(True, nv[0], nv[1], ibrk1h[ki])
                if not g:
                    dist = abs(c - iinv[ki])
                    if (dist > B.S_MIN_DIST
                            and dist * LOT <= B.MAX_RISK_PCT * 230.0):
                        tp = c + itrend[ki] * B.RR * dist
                        pos = ("INT", itrend[ki], c, float(iinv[ki]),
                               tp, dist, c - itrend[ki] * dist / 2.0, False)

        # --- MAIN, second, same slot - deployed FLIP-BOS-only-in-debt --
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
                skip_recovery_rule = debt_now > 0.5 and not flip
                if ok_dedupe and nv is not None and not skip_recovery_rule:
                    g = gate(False, nv[0], nv[1],
                            bisect.bisect_left(marks_main, t)
                            - bisect.bisect_left(marks_main, t - 7200))
                    if not g:
                        dist = abs(c - slp)
                        if (dist > B.S_MIN_DIST
                                and dist * LOT <= B.MAX_RISK_PCT * 230.0):
                            tp = c + d * B.RR * dist
                            pos = ("MAIN", d, c, float(slp), tp, dist,
                                   c - d * dist / 2.0, False)

    dd = 0.0
    pk2 = 0.0
    worst_debt = 0.0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
        worst_debt = max(worst_debt, pk2 - v)
    return dict(net=run, maxdd=dd, worst_debt=worst_debt)


def main():
    sym, R = bars()
    kept = F.build(R)
    days = len(R) / 1440
    print(f"\n  {sym}  {days:.1f} days, {len(R)} raw / {len(kept)} kept, "
          f"spread {SP:.0f}\n  building the internal track "
          f"(this is the slow part, built ONCE, reused 3x)...", flush=True)
    times, itrend, iinv, iinv_t, ibrk1h = build_internal_track(kept)
    print(f"  done: {len(times)} kept-candle steps\n", flush=True)

    print(f"  {'rule':<44}{'net $':>9}{'max DD':>9}{'worst debt':>11}")
    results = {}
    for mode, lab in (("normal", "A  today: internal normal, even in debt"),
                       ("pause", "B  PAUSE internal entirely while in debt"),
                       ("narrow", "C  NARROW: internal only when calm, in debt")):
        r = simulate(R, times, itrend, iinv, iinv_t, ibrk1h, mode)
        results[mode] = r
        print(f"  {lab:<44}{r['net']:>9.2f}{r['maxdd']:>9.2f}"
              f"{r['worst_debt']:>11.2f}")
    a = results["normal"]
    for mode, lab in (("pause", "Pause"), ("narrow", "Narrow")):
        b = results[mode]
        print(f"    A vs {lab}: {a['net']-b['net']:+.2f} net, "
              f"{a['maxdd']-b['maxdd']:+.2f} DD, "
              f"{a['worst_debt']-b['worst_debt']:+.2f} worst debt")
    print()


if __name__ == "__main__":
    main()
