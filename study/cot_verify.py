"""Hammer the one thing the COT survey turned up: do positioning extremes REVERSE more?

The behaviour survey showed no directional edge (expected, and not the point) but did
show a persistence gap - the tendency for a move to keep its sign was lower at
positioning extremes than in the middle of the range:

    bottom 5%   0.476        bottom 5%   0.444
    middle      0.503        middle      0.517      (4-week horizon)
    top 5%      0.457        top 5%      0.505

That is the shape "extreme positioning increases reversal probability" predicts. It is
also exactly the shape that fourteen previous candidates had before they died, so it
gets the full treatment rather than a victory lap:

  PER MARKET      ten markets across five asset classes. A crowding effect should not
                  care whether the crowd is in gold or the yen. If it shows up in three
                  markets and not the rest, it is those three markets' history.

  OUT OF SAMPLE   split at the halfway date. Both halves must agree. This is the check
                  that no amount of in-sample cleverness can fake.

  ALL PHASES      at multi-week horizons there are several valid ways to lay down
                  non-overlapping windows. Every phase is its own clean sample, so all
                  of them get run - recovering the data that a single-phase test throws
                  away, without ever overlapping two windows (trap #5).

  ROTATION NULL   the important one. The positioning series is slid forward against the
                  price series by a random offset and the whole statistic recomputed,
                  500 times. Rotation preserves the autocorrelation of BOTH series
                  perfectly - it destroys only their alignment. If the real gap sits
                  comfortably inside the cloud of rotated gaps, the effect is what
                  slow-moving correlated series produce by accident. This also absorbs
                  the multiple-testing problem: many buckets were looked at, and the
                  rotated distribution reflects the same looking.
"""
import os, csv, math, random
import numpy as np
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
RANK_W, VOL_W = 156, 252
HORIZONS = [("1 week", 1), ("4 weeks", 4)]
N_ROT = 500
rng = random.Random(7)


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
                    cot[r["market"]].append(
                        (r["usable_from"],
                         (float(r["nc_long"]) - float(r["nc_short"])) / oi))
            except (ValueError, TypeError, KeyError): pass
    for m in px: px[m].sort()
    for m in cot: cot[m].sort()
    return px, cot


def build(dates, closes, rows):
    """Forward behaviour per weekly report, entered on the publication Friday."""
    lc = np.log(closes)
    dr = np.diff(lc, prepend=lc[0])
    tvol = np.full(len(lc), np.nan)
    for i in range(VOL_W, len(lc)):
        s = dr[i - VOL_W + 1:i + 1].std()
        tvol[i] = s if s > 0 else np.nan
    idx, j = [], 0
    for d, _ in rows:
        while j < len(dates) and dates[j] < d:
            j += 1
        idx.append(j if j < len(dates) else None)

    out = []
    for k, i in enumerate(idx):
        if i is None or not np.isfinite(tvol[i]):
            continue
        rec = {"k": k, "date": rows[k][0]}
        keep = False
        for hname, h in HORIZONS:
            nd = 5 * h
            if i + nd >= len(lc) or i - nd < 0:
                rec[hname] = None; continue
            path = lc[i:i + nd + 1] - lc[i]
            scale = tvol[i] * math.sqrt(nd)
            rec[hname] = {"ret": path[-1] / scale,
                          "prior": (lc[i] - lc[i - nd]) / scale,
                          "vol": dr[i + 1:i + nd + 1].std() / tvol[i]}
            keep = True
        if keep:
            out.append(rec)
    return out


def ranks_for(vals, order):
    """Trailing percentile rank of vals, walked in the given index order.

    `order` is what the rotation perturbs: the real test walks positioning in its own
    time order; a rotated test walks it starting from somewhere else, so the ranks stay
    internally consistent but no longer line up with the price dates.
    """
    n = len(order)
    out = np.full(n, np.nan)
    for t in range(RANK_W, n):
        win = vals[order[t - RANK_W:t]]
        out[t] = (win < vals[order[t]]).mean()
    return out


def gap(recs, rk, hname, h, phase_all=True):
    """(extreme persistence - middle persistence, n_extreme) pooled over phases."""
    ex_hit = ex_n = mid_hit = mid_n = 0
    phases = range(h) if phase_all else [0]
    for ph in phases:
        for t in range(ph, len(recs), h):
            r, v = recs[t], rk[t]
            if not np.isfinite(v) or not r.get(hname):
                continue
            d = r[hname]
            if not (np.isfinite(d["prior"]) and np.isfinite(d["ret"])):
                continue
            same = np.sign(d["ret"]) == np.sign(d["prior"])
            if v <= 0.05 or v >= 0.95:
                ex_n += 1; ex_hit += same
            elif 0.2 < v < 0.8:
                mid_n += 1; mid_hit += same
    if ex_n < 30 or mid_n < 60:
        return None
    return (ex_hit / ex_n - mid_hit / mid_n, ex_n, mid_n)


px, cot = load()
DATA_M = {}
for m in sorted(cot):
    if m not in px or len(px[m]) < VOL_W + 60:
        continue
    dates = [d for d, _ in px[m]]
    closes = np.array([c for _, c in px[m]], float)
    recs = build(dates, closes, cot[m])
    vals = np.array([v for _, v in cot[m]], float)
    # keep positioning aligned to the records that survived
    vals = vals[[r["k"] for r in recs]]
    if len(recs) >= 200:
        DATA_M[m] = (recs, vals)

print("REVERSAL AT POSITIONING EXTREMES - full verification")
print("persistence = how often the forward move keeps the sign of the prior move")
print("gap = extremes minus middle. NEGATIVE means extremes reverse more.\n")

for hname, h in HORIZONS:
    print("=" * 92)
    print("HORIZON %s   (all %d phase%s pooled)" % (hname, h, "" if h == 1 else "s"))
    print("%-9s %8s %8s %10s %11s %11s   %s"
          % ("market", "n extr", "n mid", "GAP", "first half", "second half", "halves agree"))
    print("-" * 92)
    real_gaps, agree_all = [], 0
    for m, (recs, vals) in DATA_M.items():
        order = np.arange(len(vals))
        rk = ranks_for(vals, order)
        g = gap(recs, rk, hname, h)
        if not g:
            print("%-9s too few" % m); continue
        half = len(recs) // 2
        g1 = gap(recs[:half], rk[:half], hname, h)
        g2 = gap(recs[half:], rk[half:], hname, h)
        both = (g1 and g2 and (g1[0] < 0) == (g2[0] < 0))
        agree_all += 1 if both else 0
        real_gaps.append(g[0])
        print("%-9s %8d %8d %+10.4f %11s %11s   %s"
              % (m, g[1], g[2], g[0],
                 "%+.4f" % g1[0] if g1 else "-",
                 "%+.4f" % g2[0] if g2 else "-",
                 "yes" if both else "no"))
    if not real_gaps:
        print(); continue
    pooled = float(np.mean(real_gaps))
    neg = sum(1 for x in real_gaps if x < 0)
    print("-" * 92)
    print("pooled gap %+.4f | %d of %d markets reverse more at extremes | "
          "%d of %d agree across halves"
          % (pooled, neg, len(real_gaps), agree_all, len(real_gaps)))

    # ---- rotation null ----
    rot = []
    for _ in range(N_ROT):
        gs = []
        for m, (recs, vals) in DATA_M.items():
            n = len(vals)
            off = rng.randrange(52, n - 52) if n > 130 else 0
            order = (np.arange(n) + off) % n
            rk = ranks_for(vals, order)
            g = gap(recs, rk, hname, h)
            if g:
                gs.append(g[0])
        if gs:
            rot.append(float(np.mean(gs)))
    rot = np.array(rot)
    pct = float((rot <= pooled).mean())
    print("rotation null: mean %+.4f, sd %.4f | real gap sits at the %.1f%% point of %d rotations"
          % (rot.mean(), rot.std(), pct * 100, len(rot)))
    verdict = ("REAL - outside the noise cloud" if pct <= 0.05 and neg >= len(real_gaps) * 0.7
               else "not distinguishable from noise")
    print("VERDICT: %s\n" % verdict)

print("""
The rotation null is the line that decides this. A gap that lands inside the middle of
the rotated cloud is what two slow-moving series produce when they are lined up at
random - no amount of consistency across markets rescues it, because the rotations are
just as consistent.""")
