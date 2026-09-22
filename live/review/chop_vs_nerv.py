"""Is NERVOSITY a chop meter?

Owner 2026-09-22, after the movement count turned out not to be one.

Nervosity is the feed's own formula: median candle range over the last 60
bars / median over the last 1440. So by construction it measures SIZE of
recent candles against the day - volatility, not direction. This checks
whether it happens to track chop anyway, using the same efficiency ratio:

    |net move| / distance walked        1.00 = straight line, low = chop

Bucketed on the card's own bands, so the words on the card are the rows.

    python review/chop_vs_nerv.py
"""
import json
import os
import statistics as st
import sys

LIVE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIVE)

import MetaTrader5 as mt5              # noqa: E402

STEP = 5           # sample every 5 minutes; the medians are the cost
BANDS = [(0.0, 1.00, "calme"), (1.00, 1.30, "vif"),
         (1.30, 1.85, "agite"), (1.85, 99.0, "tres agite")]


def main():
    u = next(x for x in json.load(open(os.path.join(
        LIVE, "owl_nest_users.json"), encoding="utf-8")) if x["id"] == "std")
    assert mt5.initialize(path=u["terminal"]), mt5.last_error()
    sym = "BTCUSD" if mt5.symbol_info("BTCUSD") else "BTCUSDm"
    R = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 60000)
    mt5.shutdown()
    rng = [float(r["high"]) - float(r["low"]) for r in R]
    cl = [float(r["close"]) for r in R]
    print(f"\n  {sym}  {len(R)/1440:.1f} days   sampled every {STEP} min\n")

    rows = {b[2]: [] for b in BANDS}
    for i in range(1440, len(R) - 60, STEP):
        nv = (sorted(rng[i - 60:i])[30]
              / max(sorted(rng[i - 1440:i])[720], 1e-9))
        seg = cl[i - 60:i + 1]          # the same hour nervosity looks at
        path = sum(abs(seg[k] - seg[k - 1]) for k in range(1, len(seg)))
        if path <= 0:
            continue
        eff = abs(seg[-1] - seg[0]) / path
        for lo, hi, name in BANDS:
            if lo <= nv < hi:
                rows[name].append((eff, path, abs(seg[-1] - seg[0]), nv))
                break

    print(f"  {'band':<12}{'nervosity':>11}{'samples':>9}{'share':>8}"
          f"{'efficiency':>12}{'path/1h':>9}{'net/1h':>8}")
    tot = sum(len(v) for v in rows.values())
    for lo, hi, name in BANDS:
        v = rows[name]
        if not v:
            print(f"  {name:<12}{'':>11}{'-':>9}   none")
            continue
        band = f"{lo:.2f}-{hi:.2f}" if hi < 99 else f">={lo:.2f}"
        print(f"  {name:<12}{band:>11}{len(v):>9}{100*len(v)/tot:>7.1f}%"
              f"{st.median(x[0] for x in v):>12.3f}"
              f"{st.median(x[1] for x in v):>9.0f}"
              f"{st.median(x[2] for x in v):>8.0f}")

    allv = [x for v in rows.values() for x in v]
    nv = [x[3] for x in allv]
    ef = [x[0] for x in allv]
    pa = [x[1] for x in allv]
    mn, me, mp = st.mean(nv), st.mean(ef), st.mean(pa)
    cn = (sum((a - mn) ** 2 for a in nv) ** 0.5)
    print("\n  CORRELATION with nervosity")
    for lab, ys, my in (("efficiency (chop)", ef, me), ("path walked", pa, mp)):
        cov = sum((a - mn) * (b - my) for a, b in zip(nv, ys))
        cy = (sum((b - my) ** 2 for b in ys) ** 0.5)
        print(f"    {lab:<20}{cov / (cn * cy + 1e-12):+.3f}")
    print()


if __name__ == "__main__":
    main()
