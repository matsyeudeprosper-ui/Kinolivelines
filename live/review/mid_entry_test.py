"""Enter at the MIDPOINT between the BOS level and the glowing dot, only
after the BOS has confirmed - versus entering at the confirmation close.

Owner 2026-09-18: "what if I always enter the trade at half the summit
and the low (glowing dot), only after there's a confirmation of BOS.
Still target 0.8, and also test 0.5 in that same case."

Rules simulated, per confirmed signal (same engine, gates and dedupe as
the live bot):
  - the BOS level is the extreme as it stood BEFORE the confirming bar
    (exactly what the bot captures); the stop is the glowing dot
  - a virtual LIMIT is placed at mid = (level + stop) / 2
  - it fills when a later bar's range reaches mid
  - it is cancelled if price hits the STOP before filling (the setup is
    dead), if a new signal replaces it, or after WAIT_BARS
  - once filled: SL at the dot, TP = mid + d * RR * (mid - stop)
  - one position at a time; spread paid both ways

Read RISK carefully: the midpoint halves the stop distance, so at a fixed
0.02 lot the dollars per trade halve too. R (per-unit-of-risk) is the fair
comparison; dollars are shown for the fixed lot the accounts run.

    python review/mid_entry_test.py [spread_points]
"""
import bisect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_ARGS = sys.argv[1:]            # keep the CLI before the reset below
sys.argv = ["mid_entry_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

WAIT_BARS = 240                        # a limit older than 4 h is stale


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8"))
        if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def replay(R, rr, mode, spread, lot=0.02, balance=230.0):
    """mode 'close' = enter at the confirmation close (today).
    mode 'mid'   = limit at the midpoint, fill on return."""
    eng = B.Struct()
    eng.quiet = True
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    flips, marks, trades = [], [], []
    prev_trend = 0
    used_hi = used_lo = None
    pos = None                 # (d, entry, sl, tp, i_open)
    lim = None                 # (d, mid, sl, i_set)
    signals = fills = dead = stale = 0

    for i, bar in enumerate(R):
        t = int(bar["time"])
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))

        # 1. resolve an open position on this bar
        if pos:
            d, e, sl, tp, oi = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                risk = abs(e - sl)
                win = bool(hit_tp and not hit_sl)
                pts = ((tp - e) * d - spread) if win else -(risk + spread)
                trades.append({"R": pts / risk, "win": win, "usd": pts * lot,
                               "mins": i - oi})
                pos = None

        # 2. a waiting midpoint limit: dead, stale, or filled?
        if lim and not pos:
            d, mid, sl, si = lim
            through_stop = (l <= sl) if d == 1 else (h >= sl)
            if through_stop:
                lim = None; dead += 1
            elif i - si > WAIT_BARS:
                lim = None; stale += 1
            else:
                reached = (l <= mid) if d == 1 else (h >= mid)
                if reached:
                    risk = abs(mid - sl)
                    tp = mid + d * rr * risk
                    pos = (d, mid, sl, tp, i)
                    lim = None; fills += 1

        hv, lv = eng.hi_v, eng.lo_v
        sig = eng.step(t, o, h, l, c)
        if eng.trend != prev_trend and eng.trend != 0:
            flips.append(t)
            prev_trend = eng.trend
        if sig is not None:
            marks.append(t)
        if sig is None:
            continue
        if not any(f > t - B.AWAKE_WIN for f in flips):
            continue
        d, slp = sig
        flip = bool(flips) and flips[-1] == t
        lvl = hv if d == 1 else lv
        if not flip:
            if (d == 1 and used_hi == lvl) or (d == -1 and used_lo == lvl):
                continue
            if d == 1:
                used_hi = lvl
            else:
                used_lo = lvl
        if i >= 1440:
            nv = (sorted(rng[i - 60:i])[30]
                  / max(sorted(rng[i - 1440:i])[720], 1e-9))
            mv2 = (bisect.bisect_left(marks, t)
                   - bisect.bisect_left(marks, t - 7200))
            if nv > 1.0 or mv2 < 1:
                continue
        if pos:
            continue
        signals += 1
        if mode == "close":
            risk = abs(c - slp)
            if risk <= B.S_MIN_DIST or risk * lot > B.MAX_RISK_PCT * balance:
                continue
            pos = (d, c, slp, c + d * rr * risk, i)
        else:
            if lvl is None:
                continue
            mid = (lvl + slp) / 2.0
            risk = abs(mid - slp)
            if risk <= B.S_MIN_DIST or risk * lot > B.MAX_RISK_PCT * balance:
                continue
            # a limit BEHIND price only makes sense if price is beyond it
            if (d == 1 and c <= mid) or (d == -1 and c >= mid):
                continue
            lim = (d, mid, slp, i)          # replaces any older one
    return trades, dict(signals=signals, fills=fills, dead=dead, stale=stale)


def summ(tr):
    if not tr:
        return dict(n=0, R=0.0, per=0.0, wr=0.0, usd=0.0)
    return dict(n=len(tr), R=sum(x["R"] for x in tr),
                per=sum(x["R"] for x in tr) / len(tr),
                wr=100 * sum(1 for x in tr if x["win"]) / len(tr),
                usd=sum(x["usd"] for x in tr))


def main():
    spread = float(_ARGS[0]) if _ARGS else 7.0
    sym, R = bars()
    days = len(R) / 60 / 24
    print(f"  {sym}  {len(R)} bougies = {days:.1f} jours   spread {spread:.0f}\n")
    CASES = [("cloture de confirmation, RR 0.8 (actuel)", "close", 0.8),
             ("MI-CHEMIN, RR 0.8", "mid", 0.8),
             ("MI-CHEMIN, RR 0.5", "mid", 0.5)]
    ANCH, step = 6, 600
    print(f"  {'cas':<42}{'trades':>7}{'reussite':>10}{'R/trade':>9}"
          f"{'R total':>9}{'$':>9}{'anc.+':>7}")
    extra = {}
    for lab, mode, rr in CASES:
        rows, info0 = [], None
        for a in range(ANCH):
            sub = R[a * step:]
            if len(sub) < 20000:
                break
            tr, info = replay(sub, rr, mode, spread)
            rows.append(summ(tr))
            if a == 0:
                info0 = info
        b = rows[0]
        pos_anch = sum(1 for r in rows if r["per"] > 0)
        print(f"  {lab:<42}{b['n']:>7}{b['wr']:>9.1f}%{b['per']:>+9.3f}"
              f"{b['R']:>+9.1f}{b['usd']:>+9.2f}{pos_anch:>4}/{len(rows)}")
        extra[lab] = info0
    print()
    for lab, inf in extra.items():
        if inf and "fills" in inf and inf["signals"]:
            print(f"  {lab:<42} signaux {inf['signals']:>4}  remplis "
                  f"{inf['fills']:>4} ({100*inf['fills']/inf['signals']:.0f}%)"
                  f"  stop touche avant {inf['dead']:>3}  perimes {inf['stale']:>3}")


if __name__ == "__main__":
    main()
