"""Trail the month's profit: stop opening new cycles once the month gives back
X from its own peak.

The user's idea: the account climbs to about +$31 in a typical month and hands
back $49 before the month ends. A monthly trailing stop should keep some of the
climb.

WHAT IT DOES AND DOES NOT DO
It blocks NEW cycles only. Open positions are still managed and hedges still
allowed - freezing mid-cycle would leave a stopless trade unattended, which is a
different and worse strategy.

THE CONTROL. This strategy loses, so anything that reduces trading improves it.
A trailing stop reduces trading. So each setting is compared against simply
stopping the month after the same number of trades, with no cleverness at all.
If plain "trade less" matches it, the trailing rule is doing nothing.

M5 (10 months) and M15 (29 months). M15 carries more weight here: a monthly rule
needs a sample of months, and ten is not one.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
DATA = {"M5": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M5, 0, 80000),
        "M15": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)}
mt5.shutdown()
ANCH = [0, 3, 9, 21, 45, 90]


def monthly(z):
    ym = np.array([datetime.utcfromtimestamp(t).strftime("%Y-%m") for t in z["tm"]])
    prev = 1000.0; ch = []
    for m in sorted(set(ym)):
        seg = z["curve"][ym == m]
        ch.append(float(seg[-1] - prev)); prev = seg[-1]
    return np.array(ch)


for tf in ("M5", "M15"):
    R = DATA[tf]
    mon = (R["time"][-1] - R["time"][0]) / 86400 / 30.4
    print("=" * 84)
    print(f"{tf}   {mon:.1f} months   monthly trailing stop on the hedge strategy")
    print("=" * 84)
    base = [simulate(R, a, arm="hedge") for a in ANCH]
    beq = np.array([x["eq"] for x in base])
    bm = monthly(simulate(R, 0, arm="hedge"))
    print(f"{'rule':<24}{'mean final':>12}{'vs none':>10}{'2SE':>8}{'better':>8}"
          f"{'avg month':>11}{'months +':>10}{'trades/mo':>11}")
    print(f"{'no trail':<24}{beq.mean():>12.2f}{0.0:>+10.2f}{0.0:>8.2f}{'-':>8}"
          f"{bm.mean():>+11.2f}{f'{int((bm>0).sum())}/{len(bm)}':>10}"
          f"{np.mean([x['opened'] for x in base])/mon:>11.0f}")
    for tr in (10.0, 20.0, 30.0, 40.0, 60.0):
        outs = [simulate(R, a, arm="hedge", month_trail=tr) for a in ANCH]
        eq = np.array([x["eq"] for x in outs]); dd = eq - beq
        se = 2 * dd.std(ddof=1) / np.sqrt(len(dd))
        mm = monthly(simulate(R, 0, arm="hedge", month_trail=tr))
        bad = any((not x["ok"]) or x["max_open"] > 2
                  or (x["cycles"] and max(x["cycles"]) > 60) for x in outs)
        print(f"{'give back $%.0f' % tr:<24}{eq.mean():>12.2f}{dd.mean():>+10.2f}{se:>8.2f}"
              f"{f'{int((dd>0).sum())}/{len(dd)}':>8}{mm.mean():>+11.2f}"
              f"{f'{int((mm>0).sum())}/{len(mm)}':>10}"
              f"{np.mean([x['opened'] for x in outs])/mon:>11.0f}"
              f"{'  FAIL' if bad else ''}")
    print()
