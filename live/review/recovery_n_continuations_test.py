"""Owner 2026-09-27: "test if I allow taking the first 2 trades of a new
trend after the flip during recovery mode."

Deployed (debt > 0.5): the FLIP-BOS itself, plus ONE plain-BOS continuation
after it (the allowance is re-armed by the flip and by a touch of the
protected dot). So the flip is trade #1 of the new trend and the
continuation is trade #2 - "the first 2 trades" is the live rule.

Candidates: the flip plus N continuations, N = 1 (deployed), 2, 3. A flip
resets the allowance to N; each plain BOS in debt consumes one; a touch of
the protected dot gives ONE back (never above N). Everything else is the
deployed replay of review/recovery_touch_rearm_test.py: real B.Struct()
engine, awake window, one trade per broken level, storm + movement gates,
S_MIN_DIST, risk cap, tab/jar bullets.

    python review/recovery_n_continuations_test.py [spread]
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
sys.argv = ["recovery_n_continuations_test"]

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


def simulate(R, spread, n_cont):
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks = [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    run = pk = 0.0
    streak = 0
    curve = []
    day_key = None
    last_flip_t = None
    cont_left = 0
    n_trades = wins = 0
    n_debt_cont = n_debt_flip = n_refused = 0
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
                wins += 1 if win else 0
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
        if touched and last_flip_t is not None and cont_left < n_cont:
            cont_left = min(n_cont, cont_left + 1)
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
            cont_left = n_cont
            if debt_now > 0.5:
                n_debt_flip += 1
        elif debt_now > 0.5:
            if cont_left > 0 and last_flip_t is not None:
                cont_left -= 1
                n_debt_cont += 1
            else:
                n_refused += 1
                continue
        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        tp = c + d * B.RR * dist
        pos = (d, c, float(slp), tp, dist, c - d * dist / 2.0, False)
        n_trades += 1
    dd = 0.0
    pk2 = 0.0
    worst_debt = 0.0
    for v in curve:
        pk2 = max(pk2, v)
        dd = min(dd, v - pk2)
        worst_debt = max(worst_debt, pk2 - v)
    return dict(net=run, maxdd=dd, worst_debt=worst_debt, trades=n_trades,
                wr=(wins / n_trades * 100 if n_trades else 0.0),
                debt_flip=n_debt_flip, debt_cont=n_debt_cont,
                refused=n_refused)


def run_for(R, label):
    print(f"\n  {label}  {len(R)/1440:.1f} days, spread {SPREAD:.0f}")
    print(f"  {'rule':<40}{'trades':>7}{'win%':>7}{'net $':>9}{'max DD':>9}"
          f"{'worst debt':>11}{'cont@debt':>10}{'refused':>8}")
    base = None
    for n in (1, 0, 2, 3):
        r = simulate(R, SPREAD, n)
        if base is None:
            base = r
        lab = ("A  deployed: flip + 1 continuation" if n == 1
               else ("C  flip only, no continuation in debt" if n == 0
                     else f"B  flip + {n} continuations"))
        print(f"  {lab:<40}{r['trades']:>7}{r['wr']:>6.1f}%{r['net']:>9.2f}"
              f"{r['maxdd']:>9.2f}{r['worst_debt']:>11.2f}{r['debt_cont']:>10}"
              f"{r['refused']:>8}"
              + ("" if n == 1 else
                 f"   ({r['net']-base['net']:+.2f} net, "
                 f"{r['worst_debt']-base['worst_debt']:+.2f} worst debt vs A)"))


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
