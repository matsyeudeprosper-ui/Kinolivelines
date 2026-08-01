"""Does crowded BTC positioning widen the adverse excursion of a BTC trade?

The 30-market study found that positioning extremes do not predict direction but do
widen the distribution - adverse excursion +5.6% on twenty unseen markets and +12.4% on
the discovery set, the only measure to clear both its error bar and 70% market agreement
in two independent sets. The live system trades BTC, so the question is whether BTC
inherits that behaviour.

TWO TESTS, because the obvious data cannot answer it.

  PART A - CME BITCOIN COT, and why it is reported but not trusted.
  Bitcoin COT starts in 2018. After the frozen 156-week ranking window there are 278
  usable weeks, of which the top and bottom 5% are about 28. With adverse excursion
  scattered as widely as it is, that sample can only resolve a difference of ~26% of
  baseline; the effect being tested is 6%. It is underpowered by roughly 4x BEFORE a
  single number is computed. It is run anyway and its confidence interval printed,
  because a point estimate with an honest interval is worth more than silence - but an
  inconclusive test must not be read as a negative one.

  PART B - FUNDING RATE AS THE CROWDING MEASURE, which can actually answer it.
  A perpetual's funding rate is what one side pays to hold its position: the same
  crowding idea COT measures weekly, available hourly since 2019. 63,587 rows instead
  of 278. Funding was already shown to carry NO directional information, which is
  exactly what COT said - so testing it for RISK is a genuinely new question on data
  that has the power to settle it. ETH runs alongside as the replication.

WHAT IS MEASURED - the distribution, not just its mean, because the user asked for the
distribution and because risk lives in the tail:
    adverse excursion at the 50th, 75th, 90th and 95th percentile
    stop-out rate at 1.0x and 1.5x ATR - the practical question for a bot
    favourable excursion, as the control: if BOTH sides widen it is just volatility
    the ratio adverse/favourable - whether crowding is asymmetric

Two directional conventions, both reported:
    PRIOR-DIRECTION  excursion against the previous move. Frozen from the COT study.
    SYMMETRIC        the average of what a long and a short would each suffer. This is
                     the number a bot that can trade either way actually cares about.

FROZEN PARAMETERS: extremes = top/bottom 5%, middle = 20-80%, trailing rank window
720 hours for funding and 156 weeks for COT. Same as the study that produced the
hypothesis. Nothing here is tuned to BTC.
"""
import os, csv, math, random
import numpy as np
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
TOPQ, RANK_W_H, RANK_W_W, VOL_W = 0.05, 720, 156, 252
HORIZONS = [("4 hours", 4), ("8 hours", 8), ("1 day", 24), ("3 days", 72), ("1 week", 168)]
N_ROT = 300
rng = random.Random(97)


def trank(v, order, w):
    """Trailing percentile rank; vectorised so the rotation null stays affordable."""
    x = v[order]
    n = len(x)
    out = np.full(n, np.nan)
    if n <= w:
        return out
    win = np.lib.stride_tricks.sliding_window_view(x, w)[:-1]
    out[w:] = (win < x[w:, None]).mean(axis=1)
    return out


def excursions(hi, lo, cl, atr, hold):
    """Per-bar adverse/favourable excursion for a trade opened at that bar's close."""
    n = len(cl)
    adv_l = np.full(n, np.nan); adv_s = np.full(n, np.nan)
    fav_l = np.full(n, np.nan); fav_s = np.full(n, np.nan)
    for i in range(VOL_W, n - hold):
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        w = slice(i + 1, i + 1 + hold)
        mx, mn = hi[w].max(), lo[w].min()
        e = cl[i]
        adv_l[i] = (e - mn) / A            # a long suffers on the way down
        fav_l[i] = (mx - e) / A
        adv_s[i] = (mx - e) / A            # a short suffers on the way up
        fav_s[i] = (e - mn) / A
    return adv_l, fav_l, adv_s, fav_s


def summarise(vals, tag):
    a = np.asarray([x for x in vals if np.isfinite(x)])
    if len(a) < 30:
        return None
    return {"n": len(a), "mean": a.mean(), "p50": np.percentile(a, 50),
            "p75": np.percentile(a, 75), "p90": np.percentile(a, 90),
            "p95": np.percentile(a, 95),
            "stop10": float((a >= 1.0).mean()), "stop15": float((a >= 1.5).mean()),
            "se": a.std() / math.sqrt(len(a)), "tag": tag}


def block(title, rows):
    print("  %-26s %7s %7s %7s %7s %7s %7s %8s %8s"
          % (title, "n", "mean", "p50", "p75", "p90", "p95", "hit1.0x", "hit1.5x"))
    print("  " + "-" * 96)
    for label, s in rows:
        if s is None:
            print("  %-26s too few" % label); continue
        print("  %-26s %7d %7.3f %7.3f %7.3f %7.3f %7.3f %7.1f%% %7.1f%%"
              % (label, s["n"], s["mean"], s["p50"], s["p75"], s["p90"], s["p95"],
                 s["stop10"] * 100, s["stop15"] * 100))


# ===================================================================== PART A
print("=" * 100)
print("PART A - CME BITCOIN COT.  UNDERPOWERED BY ~4x; reported with its interval only.")
print("=" * 100)

cot_v, cot_d = [], []
with open(os.path.join(DATA, "cot_positioning.csv"), encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["market"] == "bitcoin":
            oi = float(r["open_interest"])
            if oi > 0:
                cot_d.append(r["usable_from"])
                cot_v.append((float(r["nc_long"]) - float(r["nc_short"])) / oi)
pxd, pxo, pxh, pxl, pxc = [], [], [], [], []
with open(os.path.join(DATA, "cot_prices.csv"), encoding="utf-8") as f:
    for r in csv.DictReader(f):
        if r["market"] == "bitcoin":
            pxd.append(r["date"]); pxh.append(float(r["high"]))
            pxl.append(float(r["low"])); pxc.append(float(r["close"]))
hi, lo, cl = map(lambda x: np.array(x, float), (pxh, pxl, pxc))
pc = np.roll(cl, 1); pc[0] = cl[0]
tr = np.maximum(hi - lo, np.maximum(np.abs(hi - pc), np.abs(lo - pc)))
atr = np.convolve(tr, np.ones(14) / 14, mode="full")[:len(tr)]
atr[:14] = np.nan

rk = trank(np.array(cot_v, float), np.arange(len(cot_v)), RANK_W_W)
for hname, days in (("1 day", 1), ("3 days", 3), ("1 week", 5), ("2 weeks", 10)):
    aL, fL, aS, fS = excursions(hi, lo, cl, atr, days)
    ex, mid = [], []
    j = 0
    for k, d in enumerate(cot_d):
        while j < len(pxd) and pxd[j] < d:
            j += 1
        if j >= len(pxd) or not np.isfinite(rk[k]) or not np.isfinite(aL[j]):
            continue
        sym = (aL[j] + aS[j]) / 2
        (ex if (rk[k] <= TOPQ or rk[k] >= 1 - TOPQ) else mid if 0.2 < rk[k] < 0.8 else []).append(sym)
    se = summarise(ex, "ex"); sm = summarise(mid, "mid")
    if not se or not sm:
        print("\n  %-9s too few" % hname); continue
    diff = se["mean"] - sm["mean"]
    two = 2 * math.sqrt(se["se"] ** 2 + sm["se"] ** 2)
    print("\n  horizon %s  |  extremes n=%d  middle n=%d" % (hname, se["n"], sm["n"]))
    print("     symmetric adverse excursion: extremes %.3f vs middle %.3f"
          % (se["mean"], sm["mean"]))
    print("     difference %+.3f  95%% interval [%+.3f, %+.3f]  -> %s"
          % (diff, diff - two, diff + two,
             "cannot distinguish from zero" if abs(diff) < two else "outside the interval"))

# ===================================================================== PART B
print("\n" + "=" * 100)
print("PART B - FUNDING-RATE CROWDING ON BTC AND ETH.  7.3 years hourly; this one has power.")
print("=" * 100)

for inst in ("BTC_PERPETUAL", "ETH_PERPETUAL"):
    p = os.path.join(DATA, "hist_%s.csv" % inst)
    if not os.path.exists(p):
        print("\n%s: no cache" % inst); continue
    H = defaultdict(list)
    with open(p, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k in ("high", "low", "close", "interest_8h"):
                H[k].append(float(r[k]))
    hi, lo, cl = (np.array(H[k], float) for k in ("high", "low", "close"))
    fund = np.array(H["interest_8h"], float)
    pc = np.roll(cl, 1); pc[0] = cl[0]
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - pc), np.abs(lo - pc)))
    atr = np.convolve(tr, np.ones(14) / 14, mode="full")[:len(tr)]
    atr[:14] = np.nan
    rk = trank(fund, np.arange(len(fund)), RANK_W_H)
    lc = np.log(cl)

    print("\n%s  %s hourly rows" % (inst, f"{len(cl):,}"))
    for hname, hold in HORIZONS:
        aL, fL, aS, fS = excursions(hi, lo, cl, atr, hold)
        prior = np.full(len(cl), np.nan)
        prior[hold:] = lc[hold:] - lc[:-hold]
        buckets = defaultdict(lambda: defaultdict(list))
        for ph in range(hold):                       # every phase; none overlap
            for i in range(VOL_W + ph, len(cl) - hold, hold):
                v = rk[i]
                if not np.isfinite(v) or not np.isfinite(aL[i]) or not np.isfinite(prior[i]):
                    continue
                grp = ("extreme" if (v <= TOPQ or v >= 1 - TOPQ)
                       else "middle" if 0.2 < v < 0.8 else None)
                if grp is None:
                    continue
                buckets[grp]["sym"].append((aL[i] + aS[i]) / 2)
                buckets[grp]["symfav"].append((fL[i] + fS[i]) / 2)
                if prior[i] > 0:
                    buckets[grp]["prior"].append(aL[i])
                elif prior[i] < 0:
                    buckets[grp]["prior"].append(aS[i])
        se, sm = summarise(buckets["extreme"]["sym"], "e"), summarise(buckets["middle"]["sym"], "m")
        if not se or not sm:
            continue
        print("\n  horizon %s" % hname)
        block("adverse (symmetric)",
              [("crowded (top/bottom 5%)", se), ("normal (20-80%)", sm)])
        d = se["mean"] - sm["mean"]
        two = 2 * math.sqrt(se["se"] ** 2 + sm["se"] ** 2)
        fe = summarise(buckets["extreme"]["symfav"], "e")
        fm = summarise(buckets["middle"]["symfav"], "m")
        pe = summarise(buckets["extreme"]["prior"], "e")
        pm = summarise(buckets["middle"]["prior"], "m")
        print("  %-26s %+.3f (%+.1f%%)  2SE %.3f  %s"
              % ("adverse difference", d, d / sm["mean"] * 100, two,
                 "<== REAL" if abs(d) > two else "inside noise"))
        if fe and fm:
            df = fe["mean"] - fm["mean"]
            print("  %-26s %+.3f (%+.1f%%)   -> %s"
                  % ("favourable difference", df, df / fm["mean"] * 100,
                     "asymmetric: risk grows faster than reward"
                     if d > 0 and df < d * 0.6 else "symmetric widening (just volatility)"))
        if pe and pm:
            dp = pe["mean"] - pm["mean"]
            print("  %-26s %+.3f (%+.1f%%)" % ("prior-direction adverse", dp,
                                               dp / pm["mean"] * 100))

    # rotation null on the headline horizon
    hold = 24
    aL, fL, aS, fS = excursions(hi, lo, cl, atr, hold)
    sym = (aL + aS) / 2
    def gapfor(rr):
        e, m = [], []
        for i in range(VOL_W, len(cl) - hold, hold):
            v = rr[i]
            if not np.isfinite(v) or not np.isfinite(sym[i]):
                continue
            if v <= TOPQ or v >= 1 - TOPQ: e.append(sym[i])
            elif 0.2 < v < 0.8:            m.append(sym[i])
        return (np.mean(e) - np.mean(m)) if len(e) > 30 and len(m) > 60 else None
    real = gapfor(rk)
    rot = []
    n = len(fund)
    for _ in range(N_ROT):
        off = rng.randrange(RANK_W_H, n - RANK_W_H)
        g = gapfor(trank(fund, (np.arange(n) + off) % n, RANK_W_H))
        if g is not None:
            rot.append(g)
    rot = np.array(rot)
    if real is not None and len(rot):
        pct = float((rot >= real).mean())
        print("\n  rotation null (1-day horizon): real %+.4f | rotated mean %+.4f sd %.4f"
              % (real, rot.mean(), rot.std()))
        print("  real sits at the %.1f%% tail of %d rotations -> %s"
              % (pct * 100, len(rot),
                 "REAL" if pct <= 0.05 else "not distinguishable from noise"))

print("""
READING IT. Part A cannot decide anything - if its interval spans zero that is the
sample size talking, not the market. Part B is the test with the power.

The number that matters is whether ADVERSE grows faster than FAVOURABLE. If both widen
equally, crowding is just a volatility proxy and an ATR-based stop already adapts to it
automatically - there would be nothing to add to the risk engine. Only an asymmetric
widening, where the market goes further against a position than for it, is new
information worth acting on.""")
