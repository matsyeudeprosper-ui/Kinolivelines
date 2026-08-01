"""HOLDOUT VALIDATION - does the crowding effect replicate on markets never looked at?

The reversal-at-extremes result was discovered on gold, silver, four equity indices,
the yen, the euro and bitcoin. Re-testing it there would only measure how well it fits
the data that produced it. This runs on twenty markets that took no part in discovery:
grains, oilseeds, softs, livestock, industrial metals and secondary currencies.

NOTHING IS TUNED. Rank window 156 weeks, extreme = bottom or top 5%, middle = 20-80%,
one-week horizon, entry on the publication Friday. Identical to discovery. If a
parameter is touched to make this work, it stops being a holdout test.

THREE QUESTIONS, in the order they should be asked:

  1 REPLICATION   does the persistence gap appear at all? This is the whole test. The
                  return is not the interesting number - whether the BEHAVIOUR shifts
                  is.

  2 ASYMMETRY     crowded longs after a rally and crowded shorts after a decline are
                  not the same situation and there is no reason to assume they behave
                  alike. Long crowding is built by retail and momentum money chasing
                  strength; short crowding often means hedgers and distress. Split
                  them and the four cells are reported separately.

  3 MECHANISM     if the marginal buyer is exhausted, that should show up as more than
                  a reversal. Measured here, all against the same market's middle:
                    volatility    realised vol over the week / trailing vol
                    efficiency    |net move| / total distance travelled. Low means
                                  chop; a weakening trend should show lower efficiency
                    adverse       worst excursion AGAINST the prior direction, in vol
                                  units - the number that decides stop placement
                    favourable    best excursion WITH it
                    continuation  how often the move keeps going

The mechanism block is the one that could matter even if the reversal is untradeable:
knowing a crowded market chops harder and goes further against you before it resolves
is a risk-management fact, not a signal.
"""
import os, csv, math, random
import numpy as np
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
RANK_W, VOL_W, H = 156, 252, 1          # FROZEN - identical to discovery
N_ROT = 500
rng = random.Random(23)


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

    out, keep_k = [], []
    nd = 5 * H
    for k, i in enumerate(idx):
        if i is None or not np.isfinite(tvol[i]) or i + nd >= len(lc) or i - nd < 0:
            continue
        path = lc[i:i + nd + 1] - lc[i]
        scale = tvol[i] * math.sqrt(nd)
        prior = (lc[i] - lc[i - nd]) / scale
        fwd = path[-1] / scale
        if not (np.isfinite(prior) and np.isfinite(fwd)) or prior == 0:
            continue
        d_ = 1.0 if prior > 0 else -1.0
        signed = path * d_
        travel = np.abs(np.diff(lc[i:i + nd + 1])).sum()
        out.append({
            "dir": d_, "prior": prior, "fwd": fwd,
            "cont": float(np.sign(fwd) == d_),
            "vol": dr[i + 1:i + nd + 1].std() / tvol[i],
            "adverse": float(-signed.min() / scale),      # against the prior move
            "favour": float(signed.max() / scale),        # with it
            "eff": float(abs(path[-1]) / travel) if travel > 0 else np.nan,
        })
        keep_k.append(k)
    return out, keep_k


def trank(vals, order):
    n = len(order)
    out = np.full(n, np.nan)
    for t in range(RANK_W, n):
        out[t] = (vals[order[t - RANK_W:t]] < vals[order[t]]).mean()
    return out


px, cot = load("_holdout")
DS = {}
for m in sorted(cot):
    if m not in px or len(px[m]) < VOL_W + 60:
        continue
    dates = [d for d, _ in px[m]]
    closes = np.array([c for _, c in px[m]], float)
    recs, kk = build(dates, closes, cot[m])
    if len(recs) >= 200:
        DS[m] = (recs, np.array([v for _, v in cot[m]], float)[kk])

print("HOLDOUT VALIDATION - %d markets that took no part in discovery" % len(DS))
print("frozen: %dw rank, extremes = top/bottom 5%%, middle = 20-80%%, 1-week horizon\n"
      % RANK_W)


def persistence_gap(recs, rk):
    ex = [r["cont"] for r, v in zip(recs, rk) if np.isfinite(v) and (v <= .05 or v >= .95)]
    mid = [r["cont"] for r, v in zip(recs, rk) if np.isfinite(v) and .2 < v < .8]
    if len(ex) < 30 or len(mid) < 60:
        return None
    return np.mean(ex) - np.mean(mid), len(ex), len(mid)


# ---------------------------------------------------------------- 1 REPLICATION
print("=" * 94)
print("1. REPLICATION - persistence gap (extremes minus middle). NEGATIVE = reverses more")
print("%-15s %8s %8s %11s   %-15s %8s %8s %11s"
      % ("market", "n ext", "n mid", "GAP", "market", "n ext", "n mid", "GAP"))
print("-" * 94)
gaps, cells = {}, []
for m, (recs, vals) in DS.items():
    g = persistence_gap(recs, trank(vals, np.arange(len(vals))))
    if g:
        gaps[m] = g[0]
        cells.append("%-15s %8d %8d %+11.4f" % (m, g[1], g[2], g[0]))
for a in range(0, len(cells), 2):
    print("   ".join(cells[a:a + 2]))
pooled = float(np.mean(list(gaps.values())))
neg = sum(1 for v in gaps.values() if v < 0)
print("-" * 94)
print("pooled gap %+.4f | %d of %d holdout markets reverse more at extremes"
      % (pooled, neg, len(gaps)))

rot = []
for _ in range(N_ROT):
    gs = []
    for m, (recs, vals) in DS.items():
        n = len(vals)
        off = rng.randrange(52, n - 52) if n > 130 else 0
        g = persistence_gap(recs, trank(vals, (np.arange(n) + off) % n))
        if g:
            gs.append(g[0])
    if gs:
        rot.append(float(np.mean(gs)))
rot = np.array(rot)
pct = float((rot <= pooled).mean())
print("rotation null: mean %+.4f sd %.4f | real gap at the %.1f%% point of %d rotations"
      % (rot.mean(), rot.std(), pct * 100, len(rot)))
print("VERDICT: %s\n" % ("REPLICATES" if pct <= 0.05 and neg >= 0.7 * len(gaps)
                         else "DOES NOT REPLICATE"))

# ---------------------------------------------------------------- 2 ASYMMETRY
CELLS = [
    ("crowded LONG  after rally",   lambda v, r: v >= .95 and r["dir"] > 0),
    ("crowded LONG  after decline", lambda v, r: v >= .95 and r["dir"] < 0),
    ("crowded SHORT after decline", lambda v, r: v <= .05 and r["dir"] < 0),
    ("crowded SHORT after rally",   lambda v, r: v <= .05 and r["dir"] > 0),
    ("middle (baseline)",           lambda v, r: .2 < v < .8),
]
print("=" * 94)
print("2. ASYMMETRY - the four crowded states are not the same situation")
print("%-28s %8s %10s %10s %10s" % ("state", "n", "continue", "fwd x dir", "raw fwd"))
print("-" * 94)
for label, sel in CELLS:
    c, fd, raw = [], [], []
    for m, (recs, vals) in DS.items():
        rk = trank(vals, np.arange(len(vals)))
        for r, v in zip(recs, rk):
            if np.isfinite(v) and sel(v, r):
                c.append(r["cont"]); fd.append(r["fwd"] * r["dir"]); raw.append(r["fwd"])
    if len(c) < 40:
        print("%-28s too few" % label); continue
    print("%-28s %8d %10.4f %10.4f %10.4f"
          % (label, len(c), np.mean(c), np.mean(fd), np.mean(raw)))

# ---------------------------------------------------------------- 3 MECHANISM
print("\n" + "=" * 94)
print("3. MECHANISM - what else changes in a crowded market?")
print("%-28s %8s %9s %11s %10s %11s %11s"
      % ("state", "n", "vol", "efficiency", "continue", "adverse", "favourable"))
print("-" * 94)
MECH = [("extremes (top/bottom 5%)", lambda v, r: v <= .05 or v >= .95),
        ("crowded LONG only",        lambda v, r: v >= .95),
        ("crowded SHORT only",       lambda v, r: v <= .05),
        ("middle (baseline)",        lambda v, r: .2 < v < .8)]
base = {}
for label, sel in MECH:
    acc = defaultdict(list)
    for m, (recs, vals) in DS.items():
        rk = trank(vals, np.arange(len(vals)))
        for r, v in zip(recs, rk):
            if np.isfinite(v) and sel(v, r):
                for k in ("vol", "eff", "cont", "adverse", "favour"):
                    if np.isfinite(r[k]):
                        acc[k].append(r[k])
    if len(acc["vol"]) < 40:
        print("%-28s too few" % label); continue
    row = {k: float(np.mean(acc[k])) for k in acc}
    if label.startswith("middle"):
        base = row
    print("%-28s %8d %9.4f %11.4f %10.4f %11.4f %11.4f"
          % (label, len(acc["vol"]), row["vol"], row["eff"], row["cont"],
             row["adverse"], row["favour"]))
if base:
    print("-" * 94)
    print("%-28s %8s %+9.1f%% %+10.1f%% %+9.1f%% %+10.1f%% %+10.1f%%"
          % ("extremes vs middle", "", 0, 0, 0, 0, 0) if False else "", end="")
    acc = defaultdict(list)
    for m, (recs, vals) in DS.items():
        rk = trank(vals, np.arange(len(vals)))
        for r, v in zip(recs, rk):
            if np.isfinite(v) and (v <= .05 or v >= .95):
                for k in ("vol", "eff", "cont", "adverse", "favour"):
                    if np.isfinite(r[k]):
                        acc[k].append(r[k])
    print("extremes vs middle, relative:  " + "  ".join(
        "%s %+.1f%%" % (k, (np.mean(acc[k]) / base[{"vol": "vol", "eff": "eff", "cont": "cont",
                                                    "adverse": "adverse", "favour": "favour"}[k]] - 1) * 100)
        for k in ("vol", "eff", "cont", "adverse", "favour")))

print("""
Replication is the only result that counts here. If the gap does not appear on markets
that had no hand in finding it, the discovery number was the shape of nine particular
histories and the honest move is to say so and stop.

If it DOES replicate, the mechanism block says whether it is tradeable as a signal or
only useful as a risk rule - a crowded market that chops more and travels further
against you is worth knowing about even when its direction stays unpredictable.""")
