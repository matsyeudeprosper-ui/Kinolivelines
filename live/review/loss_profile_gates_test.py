"""Owner 2026-09-28, after the loss profile of Valere's account: the losing
positions were quick follow-ups (median 23 min after the previous close),
opened after a big hour (price already +375 pts), more often on weekends.
"Run the untested ideas replayed properly."

Three families, each as an extra brake ON TOP of the deployed rules
(flip + one continuation in debt, storm, movement, awake window, one trade
per level, tab/jar bullets - the harness of recovery_n_continuations_test):

  wait N     no entry within N minutes of the previous close (N = 30, 60)
  ext P      no entry when the previous hour moved more than P points
             in ANY direction (P = 300, 500)
  no-weekend / no-sunday   no entry on Saturday+Sunday / Sunday (UTC)

Same real B.Struct() engine, 41.7 days of M1, both halves independently.

    python review/loss_profile_gates_test.py [spread]
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
sys.argv = ["loss_profile_gates_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SPREAD = float(_A[0]) if _A else 7.0
LOT = 0.02
BLOT = 0.01
NB = 3.0
K = 2
N_CONT = 1


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def simulate(R, spread, gate):
    """gate = ('wait', minutes) | ('ext', points) | ('nowd', {weekday ints}) | None"""
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    closes = [float(r["close"]) for r in R]
    flips, marks = [], []
    prev = 0
    used_hi = used_lo = None
    pos = None
    run = pk = 0.0
    streak = 0
    curve = []
    day_key = None
    last_flip_t = None
    last_close_t = None
    cont_left = 0
    n_trades = wins = 0
    n_gate = 0
    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))
        dt_ = datetime.fromtimestamp(t, tz=timezone.utc)
        dk = dt_.strftime("%Y-%m-%d")
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
                last_close_t = t
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
        if touched and last_flip_t is not None and cont_left < N_CONT:
            cont_left = min(N_CONT, cont_left + 1)
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
        # ---- the candidate brake, on top of everything deployed ----
        if gate is not None:
            kind, val = gate
            blocked = False
            if kind == "wait":
                blocked = last_close_t is not None and t - last_close_t < val * 60
            elif kind == "ext":
                blocked = i >= 61 and abs(closes[i-1] - closes[i-61]) > val
            elif kind == "nowd":
                blocked = dt_.weekday() in val
            if blocked:
                n_gate += 1
                continue
        debt_now = max(0.0, pk - run)
        if flip:
            last_flip_t = t
            cont_left = N_CONT
        elif debt_now > 0.5:
            if cont_left > 0 and last_flip_t is not None:
                cont_left -= 1
            else:
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
                wr=(wins / n_trades * 100 if n_trades else 0.0), gated=n_gate)


CANDS = [("A  deployed (no extra brake)", None),
         ("wait 30 min after a close", ("wait", 30)),
         ("wait 60 min after a close", ("wait", 60)),
         ("no entry after a 300-pt hour", ("ext", 300)),
         ("no entry after a 500-pt hour", ("ext", 500)),
         ("no Sunday", ("nowd", {6})),
         ("no weekend (Sat+Sun)", ("nowd", {5, 6}))]


def run_for(R, label):
    print(f"\n  {label}  {len(R)/1440:.1f} days, spread {SPREAD:.0f}")
    print(f"  {'rule':<34}{'trades':>7}{'win%':>7}{'net $':>9}{'max DD':>9}"
          f"{'worst debt':>11}{'blocked':>8}")
    base = None
    for lab, g in CANDS:
        r = simulate(R, SPREAD, g)
        if base is None:
            base = r
        print(f"  {lab:<34}{r['trades']:>7}{r['wr']:>6.1f}%{r['net']:>9.2f}"
              f"{r['maxdd']:>9.2f}{r['worst_debt']:>11.2f}{r['gated']:>8}"
              + ("" if g is None else
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
