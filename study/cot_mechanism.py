"""The reversal died on holdout. Something else survived it - test that properly.

Holdout killed the signal: the persistence gap fell from -0.0327 to -0.0103, only 11
of 20 unseen markets agreed, and the rotation null put it at the 12.2% point. Crowded
positioning does not tell you which way price goes. That branch is closed.

But the mechanism block showed something the reversal test was not looking at, and it
showed it on markets that had no hand in the discovery:

    volatility          +6.3% vs the middle of the positioning range
    adverse excursion   +5.6%
    continuation        -2.3%

And the discovery run had already shown the same shape without anyone noticing - vol
0.872 and 0.846 at the extremes against 0.813 in the middle, roughly +6%. The same
number in two independent market sets is worth more than any single-set p-value.

WHY THIS COULD BE REAL WHERE THE REVERSAL WAS NOT. Persistence is a coin-flip
statistic: every observation contributes one bit, so a 3-point gap needs enormous
samples to separate from noise. Realised volatility is a continuous measurement with
far less noise per observation. An effect can be genuinely present and invisible in
the first while obvious in the second.

WHAT IS TESTED HERE, on both market sets independently:
    volatility ratio     realised vol over the next week / trailing vol
    adverse excursion    worst move against the prior direction, in vol units
    favourable excursion best move with it
    efficiency           |net| / distance travelled - is a crowded market choppier?

Each gets: per-market agreement, a two-sample error bar, and the same rotation null
used everywhere else - positioning slid against price 500 times, preserving both
series' autocorrelation and destroying only their alignment.

THE ASYMMETRY CELL. The holdout also flagged crowded SHORT after a decline as unusual
(continuation 0.445 vs 0.496, forward +0.106). That hypothesis was generated ON the
holdout, so re-testing it there would be circular. It is therefore tested on the
DISCOVERY set, which is out-of-sample for this particular question.
"""
import os, csv, math, random
import numpy as np
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
RANK_W, VOL_W, H = 156, 252, 1
N_ROT = 500
rng = random.Random(41)
MEASURES = [("volatility", "vol"), ("adverse", "adverse"),
            ("favourable", "favour"), ("efficiency", "eff")]


def load(sfx):
    px, cot = defaultdict(list), defaultdict(list)
    with open(os.path.join(DATA, "cot_prices%s.csv" % sfx), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try: px[r["market"]].append((r["date"], float(r["close"])))
            except (ValueError, TypeError): pass
    with open(os.path.join(DATA, "cot_positioning%s.csv" % sfx), encoding="utf-8") as f:
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
    out, kk = [], []
    nd = 5 * H
    for k, i in enumerate(idx):
        if i is None or not np.isfinite(tvol[i]) or i + nd >= len(lc) or i - nd < 0:
            continue
        path = lc[i:i + nd + 1] - lc[i]
        scale = tvol[i] * math.sqrt(nd)
        prior = (lc[i] - lc[i - nd]) / scale
        if not np.isfinite(prior) or prior == 0:
            continue
        d_ = 1.0 if prior > 0 else -1.0
        signed = path * d_
        travel = np.abs(np.diff(lc[i:i + nd + 1])).sum()
        out.append({"dir": d_, "fwd": path[-1] / scale,
                    "cont": float(np.sign(path[-1]) == d_),
                    "vol": dr[i + 1:i + nd + 1].std() / tvol[i],
                    "adverse": float(-signed.min() / scale),
                    "favour": float(signed.max() / scale),
                    "eff": float(abs(path[-1]) / travel) if travel > 0 else np.nan})
        kk.append(k)
    return out, kk


def trank(vals, order):
    """Trailing percentile rank, vectorised.

    The obvious loop - for each week, slice the previous 156 and count how many were
    smaller - costs RANK_W operations per week. That is fine once, but the rotation
    null runs it 500 times per market and the whole thing turns into roughly a billion
    Python-level comparisons. A sliding-window view does the same arithmetic inside
    numpy in one shot, which is what makes 500 rotations on two market sets practical.
    """
    v = vals[order]
    n = len(v)
    out = np.full(n, np.nan)
    if n <= RANK_W:
        return out
    win = np.lib.stride_tricks.sliding_window_view(v, RANK_W)[:-1]   # rows end at t-1
    out[RANK_W:] = (win < v[RANK_W:, None]).mean(axis=1)
    return out


def dataset(sfx):
    px, cot = load(sfx)
    ds = {}
    for m in sorted(cot):
        if m not in px or len(px[m]) < VOL_W + 60:
            continue
        recs, kk = build([d for d, _ in px[m]],
                         np.array([c for _, c in px[m]], float), cot[m])
        if len(recs) >= 200:
            ds[m] = (recs, np.array([v for _, v in cot[m]], float)[kk])
    return ds


def ratio(recs, rk, key):
    """(extreme mean / middle mean, extreme mean - middle mean, 2SE of the difference)"""
    ex = [r[key] for r, v in zip(recs, rk)
          if np.isfinite(v) and (v <= .05 or v >= .95) and np.isfinite(r[key])]
    mid = [r[key] for r, v in zip(recs, rk)
           if np.isfinite(v) and .2 < v < .8 and np.isfinite(r[key])]
    if len(ex) < 30 or len(mid) < 60 or np.mean(mid) == 0:
        return None
    diff = float(np.mean(ex) - np.mean(mid))
    se = math.sqrt(np.var(ex) / len(ex) + np.var(mid) / len(mid))
    return float(np.mean(ex) / np.mean(mid)), diff, 2 * se, len(ex), len(mid)


for sfx, title in (("_holdout", "HOLDOUT (20 unseen markets)"),
                   ("", "DISCOVERY (9 markets)")):
    ds = dataset(sfx)
    print("=" * 96)
    print("%s - does crowding change the DISTRIBUTION?  %d markets" % (title, len(ds)))
    print("%-13s %10s %10s %10s %10s   %s"
          % ("measure", "extremes", "middle", "ratio", "2SE(diff)", "markets same direction"))
    print("-" * 96)
    for label, key in MEASURES:
        per, exm, midm = [], [], []
        for m, (recs, vals) in ds.items():
            r = ratio(recs, trank(vals, np.arange(len(vals))), key)
            if r:
                per.append(r[0] - 1.0)
                exm.append(np.mean([x[key] for x in recs
                                    if np.isfinite(x[key])]))
        # pooled across all observations, not an average of averages
        allex, allmid = [], []
        for m, (recs, vals) in ds.items():
            rk = trank(vals, np.arange(len(vals)))
            for r, v in zip(recs, rk):
                if not np.isfinite(v) or not np.isfinite(r[key]):
                    continue
                if v <= .05 or v >= .95: allex.append(r[key])
                elif .2 < v < .8:        allmid.append(r[key])
        if len(allex) < 40 or not per:
            print("%-13s too few" % label); continue
        e, mdn = float(np.mean(allex)), float(np.mean(allmid))
        se2 = 2 * math.sqrt(np.var(allex) / len(allex) + np.var(allmid) / len(allmid))
        up = sum(1 for x in per if (x > 0) == (e - mdn > 0))
        star = " <==" if abs(e - mdn) > se2 and up >= 0.7 * len(per) else ""
        print("%-13s %10.4f %10.4f %9.1f%% %10.4f   %d of %d%s"
              % (label, e, mdn, (e / mdn - 1) * 100, se2, up, len(per), star))

    # rotation null on the volatility ratio - the headline measure
    real = None
    rk_all = {m: trank(v, np.arange(len(v))) for m, (_, v) in ds.items()}
    ex, mid = [], []
    for m, (recs, _) in ds.items():
        for r, v in zip(recs, rk_all[m]):
            if np.isfinite(v) and np.isfinite(r["vol"]):
                (ex if (v <= .05 or v >= .95) else mid if .2 < v < .8 else []).append(r["vol"])
    real = float(np.mean(ex) - np.mean(mid))
    rot = []
    for _ in range(N_ROT):
        e2, m2 = [], []
        for m, (recs, vals) in ds.items():
            n = len(vals)
            off = rng.randrange(52, n - 52) if n > 130 else 0
            rk = trank(vals, (np.arange(n) + off) % n)
            for r, v in zip(recs, rk):
                if np.isfinite(v) and np.isfinite(r["vol"]):
                    (e2 if (v <= .05 or v >= .95) else m2 if .2 < v < .8 else []).append(r["vol"])
        if e2 and m2:
            rot.append(float(np.mean(e2) - np.mean(m2)))
    rot = np.array(rot)
    pct = float((rot >= real).mean())
    print("-" * 96)
    print("volatility rotation null: real %+.4f | rotated mean %+.4f sd %.4f | "
          "real at the %.1f%% tail of %d" % (real, rot.mean(), rot.std(), pct * 100, len(rot)))
    print("VERDICT: %s\n" % ("VOLATILITY EFFECT IS REAL" if pct <= 0.05
                             else "not distinguishable from noise"))

# ---- the asymmetry cell, tested where it was NOT found ----
print("=" * 96)
print("ASYMMETRY CHECK - 'crowded SHORT after a decline bounces' was spotted on the")
print("holdout, so it is tested here on the DISCOVERY set, which is out-of-sample for it.")
ds = dataset("")
print("%-30s %8s %10s %10s %10s" % ("state", "n", "continue", "raw fwd", "2SE"))
print("-" * 96)
for label, sel in [("crowded SHORT after decline", lambda v, r: v <= .05 and r["dir"] < 0),
                   ("crowded LONG after rally",    lambda v, r: v >= .95 and r["dir"] > 0),
                   ("middle (baseline)",           lambda v, r: .2 < v < .8)]:
    c, f = [], []
    for m, (recs, vals) in ds.items():
        rk = trank(vals, np.arange(len(vals)))
        for r, v in zip(recs, rk):
            if np.isfinite(v) and sel(v, r):
                c.append(r["cont"]); f.append(r["fwd"])
    if len(c) < 40:
        print("%-30s too few" % label); continue
    print("%-30s %8d %10.4f %10.4f %10.4f"
          % (label, len(c), np.mean(c), np.mean(f), 2 * np.std(f) / math.sqrt(len(f))))

print("""
If volatility clears its rotation null on BOTH market sets, the finding is that crowded
positioning widens the distribution without shifting its centre - more movement, deeper
excursions against you, no directional information. That is a risk rule, not a signal:
it says size smaller and give stops more room when positioning is extreme, and it says
nothing about which way to bet.""")
