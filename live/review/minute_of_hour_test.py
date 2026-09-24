"""Owner 2026-09-24: "test what would have happened if our main bot
used that winning range of the hour [minute 30-59] from the beginning
of the bot until now."

NOT a filter on the real closed deals - that has a known trap
(mt5_owl_packages.md, "movement gate removed"): skipping a trade frees
the ONE position slot the bot allows, so the freed slot goes to
whatever the NEXT signal actually is, which the real history alone
cannot show. This re-runs the REAL live-equivalent generator (same
B.Struct(), weather_gate(), AWAKE_WIN, dedupe as every other test today)
and adds the minute rule as an entry condition, so a skipped minute-
0-29 signal correctly lets the engine keep scanning for whatever comes
next - exactly what deploying this rule would actually do.

    python review/minute_of_hour_test.py [spread]
"""
import bisect
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["minute_of_hour_test"]

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


def trades(R, spread, minute_rule=None):
    """minute_rule=None -> today (every valid signal). minute_rule=(lo,hi)
    -> only take a signal whose entry minute-of-hour falls in [lo,hi);
    otherwise skip it and keep scanning (frees the slot, faithful to
    what the live bot's one-position-at-a-time rule actually does)."""
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
            d, e, sl, tp, dist = pos
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                out.append({"win": win, "dist": dist, "t": t})
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
        if minute_rule is not None:
            minute = datetime.fromtimestamp(t, tz=timezone.utc).minute
            lo, hi = minute_rule
            if not (lo <= minute < hi):
                continue        # skip - frees the slot, keeps scanning
        dist = abs(c - slp)
        if dist <= B.S_MIN_DIST or dist * LOT > B.MAX_RISK_PCT * 230.0:
            continue
        pos = (d, c, float(slp), c + d * B.RR * dist, dist)
    return out


def money(tr, spread):
    pts = [(B.RR * x["dist"] - spread) if x["win"] else -(x["dist"] + spread)
           for x in tr]
    usd = [p * LOT for p in pts]
    wins = sum(1 for x in tr if x["win"])
    return dict(n=len(tr), usd=sum(usd), wr=100*wins/len(tr) if tr else 0)


def run_for(R, label):
    print(f"\n  {label}  {len(R)/1440:.1f} days, spread {SPREAD:.0f}")
    base = trades(R, SPREAD, None)
    only3059 = trades(R, SPREAD, (30, 60))
    only0029 = trades(R, SPREAD, (0, 30))
    for lab, tr in (("today (every valid signal)", base),
                    ("ONLY minute 30-59 (the proposal)", only3059),
                    ("ONLY minute 0-29 (for contrast)", only0029)):
        m = money(tr, SPREAD)
        print(f"    {lab:<36}n={m['n']:>4}  win%={m['wr']:5.1f}  "
              f"net=${m['usd']:+9.2f}")
    return base, only3059


def main():
    sym, R = bars()
    run_for(R, f"{sym} FULL PERIOD (~42 days, standard test window)")
    print("\n  HALVES (each independently)")
    mid = len(R) // 2
    run_for(R[:mid], "FIRST HALF")
    run_for(R[mid:], "SECOND HALF")
    print()


if __name__ == "__main__":
    main()
