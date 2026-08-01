"""Is the reversal really about POSITIONING, or just about the size of the prior move?

The verification run produced the strongest result of this whole search: at a 1-week
horizon, markets at positioning extremes kept the sign of their previous move 3.3
percentage points less often than markets in the middle of the positioning range, on
8 of 9 markets, at the 4.6% point of 500 rotations.

Before that gets called a finding it has to survive the obvious alternative, which is
the lesson that killed several earlier candidates:

    Positioning does not become extreme by itself. It becomes extreme BECAUSE price
    made a large move and speculators piled in. Large moves are also the ones most
    likely to give some back. So "extremes reverse more" may be nothing more than
    "big moves reverse more" - a pure price fact, already tested and already null,
    wearing a positioning costume.

THE TEST. Sort every week by the SIZE of its prior move, in that market's own
volatility units, into quintiles. Inside each quintile the prior moves are comparable,
so compare positioning extremes against positioning middles there. If the gap is really
about who holds the position, it survives inside the buckets. If it collapses once
prior-move size is held constant, positioning added nothing that price did not already
say - and this branch closes like the others.

A second block reports the same comparison using COMMERCIAL positioning (hedgers).

CAUTION ON READING THAT SECOND BLOCK - it is weaker than it looks, and the first
version of this script drew the wrong conclusion from it. Commercials are mechanically
the other side of the speculators: when specs are at an extreme long, commercials are
at an extreme short. Since the test flags BOTH tails as "extreme", the two blocks
select almost exactly the same weeks (1,458 vs 1,461 of them). Agreement between them
is therefore guaranteed by construction and proves nothing either way. It is kept only
as a consistency check that the data pipeline is doing what it claims; the block that
actually decides anything is the prior-move-size conditioning above it.
"""
import os, csv, math
import numpy as np
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
RANK_W, VOL_W, H = 156, 252, 1
NQ = 5


def load():
    px, cot = defaultdict(list), defaultdict(list)
    with open(os.path.join(DATA, "cot_prices.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try: px[r["market"]].append((r["date"], float(r["close"])))
            except (ValueError, TypeError): pass
    with open(os.path.join(DATA, "cot_positioning.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                oi = float(r["open_interest"])
                if oi > 0:
                    cot[r["market"]].append((
                        r["usable_from"],
                        (float(r["nc_long"]) - float(r["nc_short"])) / oi,
                        (float(r["c_long"]) - float(r["c_short"])) / oi))
            except (ValueError, TypeError, KeyError): pass
    for m in px: px[m].sort()
    for m in cot: cot[m].sort()
    return px, cot


def trailing_rank(v):
    out = np.full(len(v), np.nan)
    for t in range(RANK_W, len(v)):
        out[t] = (v[t - RANK_W:t] < v[t]).mean()
    return out


px, cot = load()
rows_all = []
for m in sorted(cot):
    if m not in px or len(px[m]) < VOL_W + 60:
        continue
    dates = [d for d, _ in px[m]]
    closes = np.array([c for _, c in px[m]], float)
    lc = np.log(closes)
    dr = np.diff(lc, prepend=lc[0])
    tvol = np.full(len(lc), np.nan)
    for i in range(VOL_W, len(lc)):
        s = dr[i - VOL_W + 1:i + 1].std()
        tvol[i] = s if s > 0 else np.nan

    spec = np.array([r[1] for r in cot[m]], float)
    comm = np.array([r[2] for r in cot[m]], float)
    rs, rc = trailing_rank(spec), trailing_rank(comm)

    j = 0
    for k, (d, _, _) in enumerate(cot[m]):
        while j < len(dates) and dates[j] < d:
            j += 1
        if j >= len(dates) or not np.isfinite(tvol[j]):
            continue
        nd = 5 * H
        if j + nd >= len(lc) or j - nd < 0:
            continue
        scale = tvol[j] * math.sqrt(nd)
        prior = (lc[j] - lc[j - nd]) / scale
        fwd = (lc[j + nd] - lc[j]) / scale
        if not (np.isfinite(rs[k]) and np.isfinite(prior) and np.isfinite(fwd)):
            continue
        rows_all.append({"m": m, "rs": rs[k], "rc": rc[k],
                         "aprior": abs(prior),
                         "same": float(np.sign(fwd) == np.sign(prior))})

print("CONTROL - does the reversal survive once prior-move SIZE is held constant?")
print("%d weekly observations across %d markets, 1-week horizon\n"
      % (len(rows_all), len({r["m"] for r in rows_all})))


def gap(rows, key):
    ex = [r["same"] for r in rows if r[key] <= 0.05 or r[key] >= 0.95]
    mid = [r["same"] for r in rows if 0.2 < r[key] < 0.8]
    if len(ex) < 30 or len(mid) < 60:
        return None
    g = np.mean(ex) - np.mean(mid)
    se = math.sqrt(np.var(ex) / len(ex) + np.var(mid) / len(mid))
    return g, len(ex), len(mid), se


for key, who in (("rs", "SPECULATORS (non-commercial)"), ("rc", "HEDGERS (commercial)")):
    print("=" * 84)
    print("positioning measured on %s" % who)
    g = gap(rows_all, key)
    print("  unconditional gap %+0.4f  (n_ext %d, n_mid %d, 2SE %.4f)"
          % (g[0], g[1], g[2], 2 * g[3]) if g else "  too few")

    # quintiles of prior-move size, computed within each market so a volatile market
    # does not fill the top bucket by itself
    qs = defaultdict(list)
    for m in {r["m"] for r in rows_all}:
        sub = [r for r in rows_all if r["m"] == m]
        cuts = np.quantile([r["aprior"] for r in sub], np.linspace(0, 1, NQ + 1)[1:-1])
        for r in sub:
            qs[int(np.searchsorted(cuts, r["aprior"]))].append(r)

    print("\n  %-22s %8s %8s %10s %10s" % ("prior-move size", "n extr", "n mid", "GAP", "2SE"))
    print("  " + "-" * 62)
    inside, signs = [], 0
    for q in range(NQ):
        gq = gap(qs[q], key)
        lbl = ["smallest 20%", "20-40%", "40-60%", "60-80%", "largest 20%"][q]
        if not gq:
            print("  %-22s too few" % lbl); continue
        inside.append(gq[0]); signs += 1 if gq[0] < 0 else 0
        print("  %-22s %8d %8d %+10.4f %10.4f" % (lbl, gq[1], gq[2], gq[0], 2 * gq[3]))
    if inside:
        print("  " + "-" * 62)
        print("  mean gap INSIDE prior-size buckets %+.4f | negative in %d of %d buckets"
              % (float(np.mean(inside)), signs, len(inside)))
    print()

print("""
VERDICT RULE. Compare the unconditional gap with the mean gap inside the prior-size
buckets. If conditioning on how big the previous move was makes the gap collapse toward
zero, positioning was a proxy for move size and carries no information of its own.

Do NOT read the hedger block as independent confirmation. It selects nearly the same
weeks as the speculator block, so the two agree by construction. Only the prior-size
conditioning discriminates.""")
