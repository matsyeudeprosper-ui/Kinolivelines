"""Is the BUY-beats-SELL cell in the live journal real, or one runaway trade?

The journal scan lit up exactly one cell: BUY at +$0.327/trade against SELL at -$0.672.
Two reasons to distrust it before anything else. First, ten cells were scanned, so about
one crossing is expected by chance alone. Second, the SELL arm's error bar is nearly four
times the BUY arm's, which is the signature of one or two enormous trades rather than a
consistent difference.

The fix is not to delete inconvenient trades - it is to check whether the gap depends on
them. If BUY still beats SELL after the runaways are excluded, the effect is in the body
of the distribution and deserves a look. If it collapses, it was an operational failure
being read as a directional edge.
"""
import math
import pandas as pd

j = pd.read_csv(r"C:\Projects\KinoliveLines\live\trades_journal.csv")
j["opened"] = pd.to_datetime(j["opened"])
j = j[~j["instrumentation"].fillna(False).astype(bool)]
g = j[j.opened < pd.Timestamp("2026-08-01 14:28")].copy()

print("Worst 5 trades in the ATR-scaled era:")
for _, r in g.nsmallest(5, "pnl").iterrows():
    print("   %s  %-4s  $%7.2f   held %7.1f min" % (r.opened, r.side, r.pnl, r.duration_min))

print("\nPositions are meant to be force-closed at 120 minutes. Anything far beyond that")
print("was not managed by the rules, so it measures a supervision gap, not a direction.\n")


def compare(d, label):
    out = []
    for s in ("BUY", "SELL"):
        x = d[d.side == s].pnl
        if len(x) < 3:
            out.append((s, len(x), float("nan"), float("nan")))
            continue
        se = x.std(ddof=1) / math.sqrt(len(x))
        out.append((s, len(x), x.mean(), 2 * se))
    b, s_ = out
    gap = b[2] - s_[2]
    print("%-26s BUY n=%-3d $%+.3f (2SE %.3f)   SELL n=%-3d $%+.3f (2SE %.3f)   gap $%+.3f"
          % (label, b[1], b[2], b[3], s_[1], s_[2], s_[3], gap))


compare(g, "all trades")
compare(g[g.duration_min < 240], "held under 4 hours")
compare(g[g.pnl > -10], "excluding losses > $10")
compare(g[(g.duration_min < 240) & (g.pnl > -10)], "both filters")

print("""
If the gap shrinks toward zero once the runaways are removed, the 'BUY works' cell was
those trades and nothing more. Note that removing losers makes BOTH arms look better -
what matters is only whether the DIFFERENCE between them survives.""")
