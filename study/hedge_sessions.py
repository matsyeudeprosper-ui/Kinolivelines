"""Which session suits the HEDGE strategy - London, New York or Asia?

Only NEW CYCLES are restricted to the session. A hedge is always allowed, because
refusing to hedge an already-open trade when the clock runs out leaves it
unmanaged - a different and worse strategy than the one being tested.

THE CONTROL THAT MATTERS. The strategy loses, so trading in fewer hours cuts the
loss automatically. Asia is 8 hours of 24, London 9, New York 9. A random set of
the SAME WIDTH is run against each, and a session only counts if it beats random
sets of its own size. This exact control halved an apparent session effect on the
harvest strategy earlier today.

Broker server time is UTC+0, verified against the live tick, so these windows
mean what they say.

Paired across brick anchors. M1 and the clean M15.
"""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
DATA = {"M1": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000),
        "M15": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)}
mt5.shutdown()

ANCH = [0, 3, 9, 21, 45, 90]
SESS = {
    "Asia 00-08":      set(range(0, 8)),
    "London 07-16":    set(range(7, 16)),
    "New York 12-21":  set(range(12, 21)),
    "overlap 12-16":   set(range(12, 16)),
}
rng = np.random.default_rng(20260806)


def stats(R, hours):
    out = [simulate(R, a, arm="hedge", hours=hours) for a in ANCH]
    eq = np.array([x["eq"] for x in out])
    th = sum(x["hedges"] for x in out); w = sum(x["won"] for x in out)
    bad = any((not x["ok"]) or x["max_open"] > 2
              or (x["cycles"] and max(x["cycles"]) > 60) for x in out)
    return eq, np.mean([x["mdd"] for x in out]), \
        np.mean([x["opened"] for x in out]), (100 * w / max(1, th)), bad


for tf in ("M1", "M15"):
    R = DATA[tf]
    mon = (R["time"][-1] - R["time"][0]) / 86400 / 30.4
    print("=" * 86)
    print(f"{tf}   {mon:.1f} months   HEDGE strategy, new cycles restricted to each session")
    print("=" * 86)
    base, bmdd, bop, bhit, bbad = stats(R, None)
    print(f"{'session':<18}{'mean final':>12}{'vs all hours':>14}{'2SE':>8}{'better':>8}"
          f"{'trades/mo':>11}{'hit%':>7}{'worst dd':>10}")
    print(f"{'ALL HOURS':<18}{base.mean():>12.2f}{0.0:>+14.2f}{0.0:>8.2f}{'-':>8}"
          f"{bop/mon:>11.0f}{bhit:>6.1f}%{bmdd:>10.2f}")
    res = {}
    for nm, hrs in SESS.items():
        eq, mdd, op, hit, bad = stats(R, hrs)
        dd = eq - base
        se = 2 * dd.std(ddof=1) / np.sqrt(len(dd))
        res[nm] = (dd.mean(), len(hrs))
        print(f"{nm:<18}{eq.mean():>12.2f}{dd.mean():>+14.2f}{se:>8.2f}"
              f"{f'{int((dd>0).sum())}/{len(dd)}':>8}{op/mon:>11.0f}{hit:>6.1f}%{mdd:>10.2f}"
              f"{'  INVARIANT FAIL' if bad else ''}")

    print(f"\n  CONTROL - random hour-sets of the same width:")
    for nm, (real, width) in res.items():
        got = []
        for t in range(6):
            hrs = set(rng.choice(24, size=width, replace=False).tolist())
            eq, _, _, _, _ = stats(R, hrs)
            got.append((eq - base).mean())
        got = np.array(got)
        verdict = "beats random" if real > got.max() else "NOT distinguishable from trading fewer hours"
        print(f"    {nm:<18} real {real:>+8.2f}   random {width}h: "
              f"median {np.median(got):>+8.2f}  best {got.max():>+8.2f}   -> {verdict}")
    print()
