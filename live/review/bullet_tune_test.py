"""Find the BEST midpoint-bullet configuration, not whether to keep them.

Owner 2026-09-23: "think with me not against me - come up with a better
solution whenever you reject something."

The bullet has better geometry than the trade it reinforces. Entry e,
stop sl, dist = |e-sl|; the bullet goes on at the midpoint m, so:

    bullet risk   = dist/2          (half the main trade's)
    bullet reward = 0.8*dist + dist/2 = 1.3*dist
    bullet RR     ~ 2.6  against the main trade's 0.8

So a bullet only needs to win about 28% of the time to break even, while
the main trade needs 56%. That is why they can pay - and why the question
is WHEN they fire, not whether.

This walks the raw bars of every trade and answers first:
  - how often price reaches the midpoint at all
  - having reached it, how often the trade still finishes at TP

then grids the tunable parts: how many bullets, and whether to require a
calm market (the live rule) or the trade's own structure.

    python review/bullet_tune_test.py [spread]
"""
import bisect
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(HERE)
sys.path.insert(0, LIVE)
_A = sys.argv[1:]
sys.argv = ["bullet_tune_test"]

import MetaTrader5 as mt5              # noqa: E402
import structure_bos_bot as B          # noqa: E402
B.say = lambda *a, **k: None

SPREAD = float(_A[0]) if _A else 7.0
LOT = 0.02
BLOT = 0.01


def bars(n=60000):
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    if not mt5.initialize(path=u["terminal"]):
        raise SystemExit(f"MT5: {mt5.last_error()}")
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, n)
    mt5.shutdown()
    return sym, R


def trades_with_path(R, spread):
    """Every live-config trade, plus whether it touched its own midpoint
    and how nervous the market was when it did."""
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
            d, e, sl, tp, dist, mid, hit_mid, nv_mid = pos
            if not hit_mid:
                touched = (l <= mid) if d == 1 else (h >= mid)
                if touched:
                    hit_mid = True
                    nv_mid = (sorted(rng[max(0, i-60):i])[min(30, i-1)]
                              / max(sorted(rng[max(0, i-1440):i])
                                    [min(720, max(0, i-2))], 1e-9)
                              ) if i > 61 else 1.0
                    pos = (d, e, sl, tp, dist, mid, hit_mid, nv_mid)
            hit_sl = (l <= sl) if d == 1 else (h >= sl)
            hit_tp = (h >= tp) if d == 1 else (l <= tp)
            if hit_sl or hit_tp:
                win = bool(hit_tp and not hit_sl)
                out.append({"win": win, "dist": dist, "mid": hit_mid,
                            "nv": nv_mid, "t": t})
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
        pos = (d, c, float(slp), c + d * B.RR * dist, dist,
               c - d * dist / 2.0, False, 1.0)
    return out


def money(tr, nb, calm=None):
    """Total $ with nb bullets fired at the midpoint (calm filter optional)."""
    tot = 0.0
    for x in tr:
        dist = x["dist"]
        tot += ((B.RR * dist - SPREAD) if x["win"]
                else -(dist + SPREAD)) * LOT
        if nb and x["mid"] and (calm is None or x["nv"] <= calm):
            per = ((1.3 * dist - SPREAD) if x["win"]
                   else -(dist / 2.0 + SPREAD))
            tot += per * BLOT * nb
    return tot


def main():
    sym, R = bars()
    tr = trades_with_path(R, SPREAD)
    n = len(tr)
    mid = [x for x in tr if x["mid"]]
    midwin = [x for x in mid if x["win"]]
    print(f"\n  {sym}  {len(R)/1440:.1f} days, {n} trades, spread {SPREAD:.0f}\n")
    print("  THE GEOMETRY")
    print(f"    bullet risk = dist/2, reward = 1.3*dist  ->  RR ~2.6")
    print(f"    breakeven win rate for a bullet: "
          f"{100/(1+2.6):.0f}%   (main trade needs {100/(1+0.8):.0f}%)")
    print("\n  WHAT ACTUALLY HAPPENS")
    print(f"    reached the midpoint      {len(mid):>4} of {n}  "
          f"({100*len(mid)/n:.0f}%)")
    print(f"    ...and still won          {len(midwin):>4} of {len(mid)}  "
          f"({100*len(midwin)/len(mid):.0f}%)   <- vs {100/(1+2.6):.0f}% needed")
    print(f"    never pulled back         {n-len(mid):>4}  "
          f"({100*(n-len(mid))/n:.0f}%)  bullets cannot fire")

    print(f"\n  HOW MANY BULLETS  (no calm filter)")
    print(f"    {'bullets':>8}{'total $':>10}{'vs none':>10}")
    base = money(tr, 0)
    for nb in (0, 1, 2, 3, 4, 5):
        m = money(tr, nb)
        print(f"    {nb:>8}{m:>10.2f}{m-base:>+10.2f}")

    print(f"\n  CALM FILTER  (the live rule refuses above 1.00x)")
    print(f"    {'max nerv':>9}" + "".join(f"{'n='+str(k):>10}"
                                           for k in (1, 2, 3)))
    for calm in (None, 1.85, 1.30, 1.00, 0.80):
        lab = "no filter" if calm is None else f"{calm:.2f}x"
        row = f"    {lab:>9}"
        for nb in (1, 2, 3):
            row += f"{money(tr, nb, calm):>10.2f}"
        print(row)
    print()


if __name__ == "__main__":
    main()
