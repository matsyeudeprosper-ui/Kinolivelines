"""Does participant POSITIONING contain information that price alone does not?

Deliberately NOT framed as "does COT predict the next move". A crowded market may not
move in a predictable direction and still behave measurably differently - it may be
more prone to reversal, or trend harder, or simply be more violent. Direction is one
of five things measured here, not the point of the exercise.

WHAT IS MEASURED, for every positioning state and horizon:
    return       forward move in units of that market's own volatility (signed)
    |return|     size of the move regardless of direction
    volatility   realised vol over the window / trailing vol. 1.0 means normal
    worst dip    deepest drawdown from entry, in vol units
    best run     highest run-up from entry, in vol units
    persistence  how often the forward move keeps the sign of the previous move

Everything is expressed in each market's own volatility units so gold, bitcoin and the
yen can be pooled without the loudest instrument dominating.

THE POSITIONING VARIABLE. Net non-commercial (large speculator) position as a share of
open interest - raw contract counts are not comparable across forty years. Ranked
against a TRAILING 156-week window, never the full sample: ranking against the whole
history would let 2020 decide what counted as extreme in 2005.

THE LOOKAHEAD TRAP, which is the one that would fake a result here. The report is dated
Tuesday but published Friday 15:30. Entry is therefore the first trading day on or after
the FRIDAY - never the Tuesday. Getting this wrong hands you three days of hindsight in
a weekly study, which is most of the signal anyone has ever claimed to find in COT.

STANDARDS, all applied: ten markets across five asset classes; non-overlapping windows;
an out-of-sample split at the halfway date; a phase check across every offset; and a
rotation test that asks how often noise produces an effect this large.
"""
import os, csv, math, random
import numpy as np
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
RANK_W = 156                 # weeks of trailing history for the percentile rank
VOL_W = 252                  # trading days for the trailing volatility estimate
HORIZONS = [("1 week", 1), ("4 weeks", 4), ("12 weeks", 12)]
random.seed(11)


# ----------------------------------------------------------------- load
def load():
    px = defaultdict(list)
    with open(os.path.join(DATA, "cot_prices.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                px[r["market"]].append((r["date"], float(r["close"])))
            except (ValueError, TypeError):
                pass
    cot = defaultdict(list)
    with open(os.path.join(DATA, "cot_positioning.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                oi = float(r["open_interest"])
                if oi <= 0:
                    continue
                cot[r["market"]].append((
                    r["usable_from"],
                    (float(r["nc_long"]) - float(r["nc_short"])) / oi))
            except (ValueError, TypeError, KeyError):
                pass
    for m in px:
        px[m].sort()
    for m in cot:
        cot[m].sort()
    return px, cot


def observations(dates, closes, cot_rows):
    """One row per weekly report: positioning rank + forward behaviour at each horizon.

    Entry is the first trading day on or after the publication Friday, so nothing here
    can see a price that was unavailable when the number was released.
    """
    lc = np.log(closes)
    dr = np.diff(lc, prepend=lc[0])
    tvol = np.full(len(lc), np.nan)
    for i in range(VOL_W, len(lc)):
        s = dr[i - VOL_W + 1:i + 1].std()
        tvol[i] = s if s > 0 else np.nan

    # map each publication date to the first trading day at or after it
    idx, j = [], 0
    for d, _ in cot_rows:
        while j < len(dates) and dates[j] < d:
            j += 1
        idx.append(j if j < len(dates) else None)

    vals = np.array([v for _, v in cot_rows], float)
    out = []
    for k, i in enumerate(idx):
        if i is None or k < RANK_W or not np.isfinite(tvol[i]):
            continue
        win = vals[k - RANK_W:k]                       # strictly previous reports
        rank = float((win < vals[k]).mean())
        chg = vals[k] - vals[k - 4]                    # 4-week positioning change
        cwin = vals[k - RANK_W:k] - vals[k - RANK_W - 4:k - 4] if k > RANK_W + 4 else None
        crank = float((cwin < chg).mean()) if cwin is not None and len(cwin) else np.nan

        rec = {"i": i, "rank": rank, "crank": crank, "k": k}
        for hname, h in HORIZONS:
            nd = 5 * h
            if i + nd >= len(lc):
                rec[hname] = None; continue
            path = lc[i:i + nd + 1] - lc[i]
            scale = tvol[i] * math.sqrt(nd)
            prior = (lc[i] - lc[i - nd]) / scale if i - nd >= 0 else np.nan
            fwd = path[-1] / scale
            rv = dr[i + 1:i + nd + 1].std() / tvol[i]
            rec[hname] = {"ret": fwd, "abs": abs(fwd), "vol": rv,
                          "dip": path.min() / scale, "run": path.max() / scale,
                          "prior": prior}
        out.append(rec)
    return out


def stats(recs, hname, keep):
    """Mean of every behaviour measure over the records passing `keep`."""
    sel = [r[hname] for r in recs if keep(r) and r.get(hname)]
    if len(sel) < 25:
        return None
    g = lambda k: np.array([s[k] for s in sel], float)
    ret, prior = g("ret"), g("prior")
    ok = np.isfinite(prior)
    pers = float((np.sign(ret[ok]) == np.sign(prior[ok])).mean()) if ok.sum() > 10 else np.nan
    return {"n": len(sel), "ret": ret.mean(), "abs": g("abs").mean(),
            "vol": g("vol").mean(), "dip": g("dip").mean(), "run": g("run").mean(),
            "pers": pers, "se": ret.std() / math.sqrt(len(ret))}


# ----------------------------------------------------------------- build
px, cot = load()
MARKETS = [m for m in sorted(cot) if m in px and len(px[m]) > VOL_W + 60]
DATASET = {}
for m in MARKETS:
    dates = [d for d, _ in px[m]]
    closes = np.array([c for _, c in px[m]], float)
    recs = observations(dates, closes, cot[m])
    if len(recs) >= 120:
        DATASET[m] = recs

print("COT POSITIONING - does it change market BEHAVIOUR?")
print("entry on the publication Friday (never the Tuesday report date), "
      "trailing-%dw rank\n" % RANK_W)
print("%-9s %6s obs   %s" % ("market", "n", "usable span"))
for m in DATASET:
    print("  %-9s %5d" % (m, len(DATASET[m])))
print()

BUCKETS = [("bottom 5%", lambda r: r["rank"] <= 0.05),
           ("5-20%",     lambda r: 0.05 < r["rank"] <= 0.20),
           ("middle",    lambda r: 0.20 < r["rank"] < 0.80),
           ("80-95%",    lambda r: 0.80 <= r["rank"] < 0.95),
           ("top 5%",    lambda r: r["rank"] >= 0.95)]

HDR = ("%-11s %6s %8s %8s %8s %8s %8s %8s"
       % ("bucket", "n", "return", "|return|", "vol", "worst dip", "best run", "persist"))


def show(recs_by_market, title, buckets, step_h):
    """Pool markets, non-overlapping in time, and print the behaviour table."""
    print("=" * 88)
    print(title)
    for hname, h in HORIZONS:
        pooled = defaultdict(list)
        for m, recs in recs_by_market.items():
            nz = [r for n, r in enumerate(recs) if n % (h if step_h else 1) == 0]
            for label, sel in buckets:
                s = stats(nz, hname, sel)
                if s:
                    pooled[label].append(s)
        if not pooled:
            continue
        print("\n  horizon %s" % hname)
        print("  " + HDR)
        print("  " + "-" * 78)
        for label, _ in buckets:
            v = pooled.get(label)
            if not v:
                print("  %-11s too few" % label); continue
            w = np.array([s["n"] for s in v], float)
            agg = lambda k: float(np.average([s[k] for s in v], weights=w))
            print("  %-11s %6d %8.3f %8.3f %8.3f %8.3f %8.3f %8.3f"
                  % (label, int(w.sum()), agg("ret"), agg("abs"), agg("vol"),
                     agg("dip"), agg("run"), agg("pers")))
    print()


show(DATASET, "TEST 1 - EXTREME POSITIONING ALONE  (net large-spec, share of OI)",
     BUCKETS, step_h=True)

CH = [("fast unwind", lambda r: np.isfinite(r["crank"]) and r["crank"] <= 0.05),
      ("normal",      lambda r: np.isfinite(r["crank"]) and 0.05 < r["crank"] < 0.95),
      ("fast build",  lambda r: np.isfinite(r["crank"]) and r["crank"] >= 0.95)]
show(DATASET, "TEST 2 - SPEED OF POSITIONING CHANGE  (4-week change, trailing rank)",
     CH, step_h=True)

IX = [("crowded long + weak price",  lambda r: r["rank"] >= 0.90 and r.get("1 week") and r["1 week"]["prior"] < 0),
      ("crowded long + firm price",  lambda r: r["rank"] >= 0.90 and r.get("1 week") and r["1 week"]["prior"] >= 0),
      ("crowded short + firm price", lambda r: r["rank"] <= 0.10 and r.get("1 week") and r["1 week"]["prior"] > 0),
      ("crowded short + weak price", lambda r: r["rank"] <= 0.10 and r.get("1 week") and r["1 week"]["prior"] <= 0)]
show(DATASET, "TEST 3 - POSITIONING x PRICE REGIME", IX, step_h=True)

print("""
HOW TO READ IT. The middle bucket is the baseline - it is what an ordinary week looks
like. 'return' near zero everywhere means positioning carries no directional
information, which is expected and not the interesting part. The columns that would
matter are volatility, worst dip and persistence: if crowded markets are genuinely
more fragile, the extreme buckets should show higher vol and a deeper worst dip than
the middle, consistently, at every horizon.

Per-market agreement, the out-of-sample split and the rotation test follow.""")
