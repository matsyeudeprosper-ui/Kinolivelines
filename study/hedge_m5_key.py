"""The key tests on M5 - the closest usable proxy to the live M1 bot.

WHY M5. The bot builds bricks from M1 closes, but the broker only holds 56 days
of M1. M5 holds 278 days. Five-minute bricks are far nearer to one-minute ones
than the fifteen-minute bricks I had been leaning on, so this is the best
available answer to "does this design hold up over months" without pretending it
is the same strategy. It is not - different bar size means different bricks and
different signals. It is a proxy, and the closest one that exists.

THREE TESTS, all paired across brick anchors, all with the invariants:
  1. the hedge against the alternatives
  2. the reward sweep - does the hit rate still sit on the break-even line
  3. month by month for the hedge

Sessions are not repeated: rate-matched random hour-sets already matched or beat
every session on both M1 and M15, so that question is closed.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000)
mt5.shutdown()
MON = (R["time"][-1] - R["time"][0]) / 86400 / 30.4
print(f"BTCUSDm M5   {len(R)} bars   {MON:.1f} months   "
      f"{datetime.utcfromtimestamp(R['time'][0]):%Y-%m-%d} to "
      f"{datetime.utcfromtimestamp(R['time'][-1]):%Y-%m-%d}\n")

ANCH = [0, 2, 6, 14, 30, 60, 120]


def check(outs):
    return any((not x["ok"]) or (x["max_open"] > 2 and x is not None)
               or (x["cycles"] and max(x["cycles"]) > 60) for x in outs)


print("=" * 78)
print("1. THE HEDGE AGAINST THE ALTERNATIVES")
print("=" * 78)
ref = None
print(f"{'arm':<26}{'mean final':>12}{'vs current':>12}{'2SE':>8}{'better':>8}"
      f"{'trades/mo':>11}{'worst dd':>10}")
for arm, nm in (("any", "any direction (original)"),
                ("same", "same direction (demo now)"),
                ("hedge", "ONE HEDGE (live now)")):
    outs = []
    for a in ANCH:
        z = simulate(R, a, arm=arm)
        outs.append(z)
    eq = np.array([x["eq"] for x in outs])
    if ref is None:
        ref = eq; dd = np.zeros_like(eq)
    else:
        dd = eq - ref
    se = 2 * dd.std(ddof=1) / np.sqrt(len(dd)) if arm != "any" else 0.0
    mx = max(x["max_open"] for x in outs)
    bad = any((not x["ok"]) or (arm == "hedge" and x["max_open"] > 2)
              or (x["cycles"] and max(x["cycles"]) > 60) for x in outs)
    print(f"{nm:<26}{eq.mean():>12.2f}{dd.mean():>+12.2f}{se:>8.2f}"
          f"{(f'{int((dd>0).sum())}/{len(dd)}' if arm != 'any' else '-'):>8}"
          f"{np.mean([x['opened'] for x in outs])/MON:>11.0f}"
          f"{np.mean([x['mdd'] for x in outs]):>10.2f}"
          f"{'  INVARIANT FAIL' if bad else ''}")

print("\n" + "=" * 78)
print("2. REWARD SWEEP - is the hit rate still glued to the break-even line?")
print("=" * 78)
print(f"{'RR':<8}{'mean final':>12}{'hit%':>8}{'need%':>8}{'gap':>8}"
      f"{'hedges/mo':>11}{'worst dd':>10}")
for rw in (1.0, 1.5, 2.0, 2.5, 3.0):
    outs = [simulate(R, a, arm="hedge", reward=rw) for a in ANCH]
    eq = np.array([x["eq"] for x in outs])
    th = sum(x["hedges"] for x in outs); w = sum(x["won"] for x in outs)
    hit = 100 * w / max(1, th); need = 100 / (1 + rw)
    bad = any((not x["ok"]) or x["max_open"] > 2
              or (x["cycles"] and max(x["cycles"]) > 60) for x in outs)
    print(f"1:{rw:<6.1f}{eq.mean():>12.2f}{hit:>7.1f}%{need:>7.1f}%{hit-need:>+8.1f}"
          f"{th/len(ANCH)/MON:>11.0f}{np.mean([x['mdd'] for x in outs]):>10.2f}"
          f"{'  FAIL' if bad else ''}")
print(f"\n  total hedge trades behind these rates: "
      f"{sum(simulate(R, 0, arm='hedge', reward=r)['hedges'] for r in (1.0,1.5,2.0,2.5,3.0))} "
      f"across the five settings, one anchor")

print("\n" + "=" * 78)
print("3. MONTH BY MONTH, the hedge as deployed (1:1.5)")
print("=" * 78)
z = simulate(R, 0, arm="hedge")
ym = np.array([datetime.utcfromtimestamp(t).strftime("%Y-%m") for t in z["tm"]])
labs = sorted(set(ym)); prev = 1000.0; chg = []; dmax = []
for m in labs:
    seg = z["curve"][ym == m]
    full = np.concatenate(([prev], seg))
    pk = np.maximum.accumulate(full)
    dmax.append(float((pk - full).max()))
    chg.append(float(seg[-1] - prev)); prev = seg[-1]
chg = np.array(chg); dmax = np.array(dmax)
print(f"  final ${z['eq']:,.2f}   hedges {z['hedges']}  won {z['won']}  "
      f"stopped {z['stopped']}   hit {100*z['won']/max(1,z['hedges']):.1f}%")
print(f"  average month  ${chg.mean():>+8.2f}      median ${np.median(chg):>+8.2f}")
print(f"  best month     ${chg.max():>+8.2f}      worst  ${chg.min():>+8.2f}")
print(f"  profitable     {int((chg>0).sum())} of {len(chg)} months "
      f"({100*(chg>0).mean():.0f}%)")
print(f"  drawdown inside a month: average ${dmax.mean():.2f}, worst ${dmax.max():.2f}")
print(f"  worst drawdown overall:  ${z['mdd']:.2f}")
print()
for m, ch in zip(labs, chg):
    print(f"    {m}  ${ch:>+8.2f}")
