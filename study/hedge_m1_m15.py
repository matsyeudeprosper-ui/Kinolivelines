"""The hedge rule on M1 and M15, one engine, paired across anchors.

Replaces three scripts that each re-implemented the rule and disagreed by $300.
Everything here calls hedge_engine.simulate() - the rule exists in exactly one
place now.

Both invariants are checked on every single run and reported. If any fail, the
numbers above them are void.
"""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime
from hedge_engine import simulate

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
DATA = {"M1": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M1, 0, 80000),
        "M15": mt5.copy_rates_from_pos("BTCUSDm", mt5.TIMEFRAME_M15, 0, 80000)}
mt5.shutdown()

ANCH = [0, 1, 3, 7, 15, 31, 60, 120]

for tf in ("M1", "M15"):
    R = DATA[tf]
    mon = (R["time"][-1] - R["time"][0]) / 86400 / 30.4
    print("=" * 74)
    print(f"{tf}   {len(R)} bars   {mon:.1f} months   "
          f"{datetime.utcfromtimestamp(R['time'][0]):%Y-%m-%d} to "
          f"{datetime.utcfromtimestamp(R['time'][-1]):%Y-%m-%d}")
    print("=" * 74)

    runs = {}
    bad = []
    for arm in ("any", "hedge"):
        out = []
        for a in ANCH:
            z = simulate(R, a, arm=arm)
            out.append(z)
            if not z["ok"]:
                bad.append((arm, a, z.get("resid")))
            if arm == "hedge" and z["max_open"] > 2:
                bad.append((arm, a, f"max_open={z['max_open']}"))
            # a 2-position cycle at 0.01 lots cannot possibly gain more than
            # the target of both legs. This is the check that would have caught
            # the double-payment - it bounds the result instead of comparing
            # two numbers that were inflated together.
            if arm == "hedge" and z["cycles"]:
                worst = max(z["cycles"])
                if worst > 60.0:
                    bad.append((arm, a, f"a single cycle gained ${worst:.2f} - impossible"))
        runs[arm] = out

    ref = np.array([x["eq"] for x in runs["any"]])
    hg = np.array([x["eq"] for x in runs["hedge"]])
    dd = hg - ref
    se = 2 * dd.std(ddof=1) / np.sqrt(len(dd))

    print(f"  {'arm':<22}{'mean final':>12}{'lowest':>10}{'worst dd':>10}"
          f"{'trades/mo':>11}{'hedges/mo':>11}")
    for arm, nm in (("any", "current live bot"), ("hedge", "ONE HEDGE (yours)")):
        o = runs[arm]
        print(f"  {nm:<22}{np.mean([x['eq'] for x in o]):>12.2f}"
              f"{np.mean([x['lo'] for x in o]):>10.2f}"
              f"{np.mean([x['mdd'] for x in o]):>10.2f}"
              f"{np.mean([x['opened'] for x in o])/mon:>11.0f}"
              f"{np.mean([x['hedges'] for x in o])/mon:>11.0f}")
    print(f"\n  hedge vs current: {dd.mean():+.2f}   2SE {se:.2f}   "
          f"better on {int((dd>0).sum())}/{len(dd)} anchors")

    hh = runs["hedge"]
    tot_h = sum(x["hedges"] for x in hh)
    print(f"  hedge hit target {100*sum(x['won'] for x in hh)/max(1,tot_h):.0f}%, "
          f"stopped out {100*sum(x['stopped'] for x in hh)/max(1,tot_h):.0f}%   "
          f"(break-even at 1:1.5 needs 40%)")
    print(f"  most positions ever open: {max(x['max_open'] for x in hh)}   (rule says 2)")

    # monthly profile from the base anchor
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
    print(f"\n  PER MONTH ({len(chg)} months)")
    print(f"    average {chg.mean():+.2f}   median {np.median(chg):+.2f}   "
          f"best {chg.max():+.2f}   worst {chg.min():+.2f}")
    print(f"    profitable months {int((chg>0).sum())}/{len(chg)} "
          f"({100*(chg>0).mean():.0f}%)")
    print(f"    drawdown inside a month: average ${dmax.mean():.2f}, worst ${dmax.max():.2f}")

    print(f"\n  INVARIANTS: {'ALL PASS' if not bad else 'FAILED -> ' + str(bad[:3])}")
    print()
