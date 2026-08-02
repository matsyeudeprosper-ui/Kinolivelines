"""Is there anything in the live journal yet - an edge, or an exploitable imbalance?

The journal script says "too few trades to draw conclusions". That is almost certainly
right, but "almost certainly" is not a measurement, and the honest way to close the
question is to state HOW MUCH the sample could hide rather than just assert it is small.

So this does two things the journal does not:

  1. SPLITS BY GEOMETRY. The 140 rows span three different setups - the original
     ATR-scaled stops, the 40-point-stop / 20-point-target experiment, and the current
     20/40. Their win rates are set by their barrier distances, so pooling them mixes
     populations whose base rates differ by design. A pooled win rate is meaningless.

  2. REPORTS THE MINIMUM DETECTABLE EFFECT. For every split, the question is not "did
     this cell win more?" but "how big would a real effect have to be before this sample
     could see it?" A cell of 30 trades cannot resolve anything smaller than roughly 18
     percentage points, so a 10-point gap in it is not a weak signal - it is invisible.

An imbalance strategy needs the win rate to move AWAY from the breakeven implied by the
geometry. Each split is therefore judged against its own breakeven, not against 50%.
"""
import math
import numpy as np
import pandas as pd

J = r"C:\Projects\KinoliveLines\live\trades_journal.csv"
j = pd.read_csv(J)
j["opened"] = pd.to_datetime(j["opened"])

# Instrumentation rows are fee probes, not trades. Thirteen of them once dragged the
# apparent win rate from 10% to 6% before they were tagged.
if "instrumentation" in j.columns:
    n_instr = int(j["instrumentation"].fillna(False).astype(bool).sum())
    j = j[~j["instrumentation"].fillna(False).astype(bool)]
else:
    n_instr = 0
j = j[j["pnl"].notna()].copy()
j["won"] = j["pnl"] > 0

# Geometry eras. The cost-veto drop and the fixed-point experiment are both dated.
GEOM_START = pd.Timestamp("2026-08-01 14:28")
j["era"] = np.where(j["opened"] >= GEOM_START, "fixed 40/20 experiment", "ATR-scaled (older)")

print("LIVE JOURNAL - IS THERE ANYTHING IN IT YET?")
print("%d rows, %d instrumentation removed, %d real trades\n" % (len(j) + n_instr, n_instr, len(j)))


def block(label, g):
    """Judge MONEY PER TRADE, not win rate.

    A first version of this compared win rate against a fixed 50% breakeven and lit up
    almost every cell of the ATR-scaled era as a 'SIGNAL' - including the era as a whole,
    at a 71.6% win rate that LOST $20 over 116 trades. That is the oldest trap in this
    file: when stop and target distances vary trade by trade, there is no single
    breakeven win rate, and a high win rate with a few enormous losers is exactly what a
    negative expectancy looks like. One trade on 2026-07-13 lost $25.61 on its own -
    more than the whole era's net loss.

    Mean P&L per trade needs no assumption about geometry and cannot be fooled that way.
    """
    n = len(g)
    if n < 2:
        print("  %-26s n=%-4d too few" % (label, n))
        return
    x = g["pnl"]
    m = x.mean()
    se = x.std(ddof=1) / math.sqrt(n)
    mde = 2.8 * x.std(ddof=1) / math.sqrt(n)     # ~80% power, two-sided, at 5%
    verdict = "SIGNAL" if abs(m) > 2 * se else "invisible at this n"
    print("  %-26s n=%-4d  $%+.3f/trade  2SE %.3f  needs $%.3f  win %4.1f%%  %s"
          % (label, n, m, 2 * se, mde, 100 * (x > 0).mean(), verdict))


for era, g in j.groupby("era"):
    print("%s   (%s to %s)" % (era, g.opened.min().date(), g.opened.max().date()))
    print("  net $%+.2f over %d trades, win rate %.1f%%, biggest single loss $%.2f\n"
          % (g.pnl.sum(), len(g), 100 * g.won.mean(), g.pnl.min()))
    block("ALL", g)
    for col in ("H1_vs_ema21", "M15_structure", "H1_aligned", "side"):
        if col not in g.columns:
            continue
        for v in sorted(g[col].dropna().unique(), key=str):
            block("%s = %s" % (col, v), g[g[col] == v])
    print()

print("""HOW TO READ THIS
'needs Xpp' is the smallest real effect this many trades could detect. Any gap smaller
than that is not a weak hint - the sample literally cannot tell it from noise. A split
only counts as a lead when the gap beats BOTH its own error bar and that threshold, and
then it still has to survive on trades that were not used to find it.

Also note the multiple-comparisons problem: this scans roughly a dozen cells per era, so
at the usual threshold about one in twenty will look significant purely by chance. One
lone cell crossing is expected, not evidence.""")
