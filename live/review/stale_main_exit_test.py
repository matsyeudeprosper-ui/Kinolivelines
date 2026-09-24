"""Would cutting a STALLING main trade early beat letting it run to its
natural SL/TP?

Owner 2026-09-24, after reviewing CROC (a different, unrelated demo bot):
CROC's own trade log shows winners resolving in a median 2.8 min and
losers dragging on for a median 10 min - the same "stale trades tend to
lose" pattern this project already found on the structure bot's ENTRY
side (E007: stale continuations lose both halves). This tests whether
the same idea helps on the EXIT side of a MAIN trade: if a trade has been
open N minutes and is still not favorable, close it now instead of
waiting for its SL or TP.

Uses the same faithful MAIN-trade generator as bullet_tune_test.py
(real B.Struct(), weather_gate(), AWAKE_WIN, dedupe - identical to the
live entry logic), extended to record the trade's own close-price path
every minute until it naturally exits, so a stall rule can be applied
AFTER the fact without re-simulating.

A rule is (N minutes, not-yet-favorable = running pnl <= threshold*dist).
Exiting early still pays the spread once, same convention as every other
cost model in this project.

    python review/stale_main_exit_test.py [spread]
"""
import bisect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["stale_main_exit_test"]

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


def trades_with_full_path(R, spread):
    """Every live-config MAIN trade, plus its own close-price path (one
    sample per minute since entry) until it naturally hits SL or TP."""
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, out = [], [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        if pos:
            d, e, sl, tp, dist, e_t, path = pos
            path.append(c)
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                out.append({"win": win, "dist": dist, "d": d, "e": e,
                            "path": path, "t": e_t})
                pos = None
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev and eng.trend != 0:
            flips.append(t)
            prev = eng.trend
        if sig is not None:
            marks.append(t)
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
        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        pos = (d, c, float(slp), c + d * B.RR * dist, dist, t, [])
    return out


def outcome(x, rule):
    """rule = None (today's live behaviour) or (n_min, frac) - close at
    market once the trade has been open >= n_min minutes AND its running
    pnl is still <= frac*dist (frac=0 -> still not in profit at all)."""
    dist, d, e = x["dist"], x["d"], x["e"]
    if rule is not None:
        n_min, frac = rule
        if n_min < len(x["path"]):
            price_now = x["path"][n_min - 1] if n_min > 0 else e
            pnl_now = d * (price_now - e)
            if pnl_now <= frac * dist:
                return pnl_now - SPREAD          # closed early, pays spread
    pts = (B.RR * dist - SPREAD) if x["win"] else -(dist + SPREAD)
    return pts


def summarize(tr, rule):
    pts = [outcome(x, rule) for x in tr]
    usd = sum(p * LOT for p in pts)
    wins = sum(1 for p in pts if p > 0)
    return dict(n=len(tr), usd=usd, wr=100 * wins / len(tr) if tr else 0)


def run_for(R, label):
    tr = trades_with_full_path(R, SPREAD)
    if not tr:
        print(f"\n  {label}: no trades\n")
        return
    durs = sorted(len(x["path"]) for x in tr)
    print(f"\n  {label}  {len(R)/1440:.1f} days, {len(tr)} MAIN trades, "
          f"spread {SPREAD:.0f}")
    print(f"    duration (minutes held): median {durs[len(durs)//2]}  "
          f"p25 {durs[len(durs)//4]}  p75 {durs[3*len(durs)//4]}")
    base = summarize(tr, None)
    print(f"\n  {'rule':<38}{'trades':>7}{'win%':>7}{'net $':>9}{'vs base':>9}")
    print(f"  {'today (run to natural SL/TP)':<38}{base['n']:>7}"
          f"{base['wr']:>6.0f}%{base['usd']:>9.2f}{'':>9}")
    best = None
    for n_min in (15, 30, 60, 120, 240, 480):
        for frac in (0.0, -0.3):
            r = summarize(tr, (n_min, frac))
            lab = (f"cut @{n_min}m if pnl<={frac:+.1f}xdist")
            print(f"  {lab:<38}{r['n']:>7}{r['wr']:>6.0f}%{r['usd']:>9.2f}"
                  f"{r['usd']-base['usd']:>+9.2f}")
            if best is None or r["usd"] > best[1]:
                best = (lab, r["usd"])
    print(f"\n  best: {best[0]}  ({best[1]-base['usd']:+.2f} vs today)")
    return tr


def main():
    sym, R = bars()
    run_for(R, f"{sym} FULL PERIOD")
    print("\n  HALVES (each independently, own signal set)")
    mid = len(R) // 2
    run_for(R[:mid], "FIRST HALF")
    run_for(R[mid:], "SECOND HALF")
    print()


if __name__ == "__main__":
    main()
