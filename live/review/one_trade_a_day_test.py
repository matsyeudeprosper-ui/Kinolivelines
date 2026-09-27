"""Owner 2026-09-27: "How often would we win/lose if we only took one trade
a day - the first that shows? What would happen?"

Same replay as review/recovery_touch_rearm_test.py (real B.Struct()
engine, awake window, one trade per broken level, storm + movement gates,
S_MIN_DIST, risk cap, the deployed recovery rule with flip + touch re-arm,
no bullets / jar). Candidate: after the FIRST entry of a UTC day (the
first signal that passes every gate), nothing else that day.

  A  deployed: every allowed signal
  B  one trade a day: the first allowed entry, then wait for tomorrow

Full period + two halves, spreads 7 and 10.

    python review/one_trade_a_day_test.py [spread]
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
sys.argv = ["one_trade_a_day_test"]

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


def simulate(R, spread, one_a_day):
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
    traded_day = None
    n_trades = wins = 0
    days_with_trade = set()
    day_pnl = {}
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        dk = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        if dk != day_key:
            day_key = dk
            curve.append(run)
        if pos:
            d, e, sl, tp, dist, dk0 = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                pts = (B.RR * dist - spread) if win else -(dist + spread)
                run += pts * LOT
                day_pnl[dk0] = day_pnl.get(dk0, 0.0) + pts * LOT
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
        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        if one_a_day and traded_day == dk:
            continue                       # the day's one trade is taken
        traded_day = dk
        days_with_trade.add(dk)
        tp = c + d * B.RR * dist
        pos = (d, c, float(slp), tp, dist, dk)
        n_trades += 1
    dd = 0.0
    pk2 = 0.0
    worst_debt = 0.0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
        worst_debt = max(worst_debt, pk2 - v)
    gd = sum(1 for v in day_pnl.values() if v > 0.005)
    rd = sum(1 for v in day_pnl.values() if v < -0.005)
    return dict(net=run, maxdd=dd, worst_debt=worst_debt, trades=n_trades,
                wr=(wins / n_trades * 100 if n_trades else 0.0),
                days=len(days_with_trade), gd=gd, rd=rd)


def run_for(R, label):
    ndays = len(R) / 1440
    print(f"\n  {label}  {ndays:.1f} days, spread {SPREAD:.0f}")
    print(f"  {'rule':<30}{'trades':>7}{'/day':>6}{'win%':>7}{'net $':>9}"
          f"{'max DD':>9}{'worst debt':>11}{'green d':>8}{'red d':>7}")
    for lab, one in (("A  deployed: every signal", False),
                     ("B  one trade a day (first)", True)):
        r = simulate(R, SPREAD, one)
        print(f"  {lab:<30}{r['trades']:>7}{r['trades']/ndays:>6.2f}{r['wr']:>6.1f}%"
              f"{r['net']:>9.2f}{r['maxdd']:>9.2f}{r['worst_debt']:>11.2f}"
              f"{r['gd']:>8}{r['rd']:>7}")


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
