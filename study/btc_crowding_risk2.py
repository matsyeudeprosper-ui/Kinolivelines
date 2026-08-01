"""Corrected test: does crowded BTC funding change trade risk, once volatility is held constant?

THREE FIXES over the first version, two of which were my own errors:

  1 THE ASYMMETRY TEST WAS VACUOUS. "Symmetric adverse" was defined as the average of
    what a long and a short each suffer = ((entry-low) + (high-entry))/2, and symmetric
    favourable as ((high-entry) + (entry-low))/2. Those are the same number - half the
    range - so the two columns printed identical values in every row and the verdict
    "symmetric widening, just volatility" was arithmetic rather than evidence. Adverse
    and favourable are only distinct once a DIRECTION is fixed, so everything here is
    measured on a directional trade.

  2 THE ROTATION NULL WAS ONE-SIDED THE WRONG WAY. It asked how often rotations
    exceeded the real value, while the real value was negative, and duly reported
    "not distinguishable from noise" for an effect at the 0.7% tail. Now two-sided.

  3 THE VOLATILITY CONFOUND, which is the substantive one. Excursions are divided by
    ATR at entry. Funding extremes tend to arrive after violent moves, when ATR is
    already elevated; volatility then mean-reverts, so the forward excursion divided by
    a swollen denominator shrinks for reasons that have nothing to do with positioning.
    That alone could manufacture the entire "crowded markets are calmer" result.

    The fix: rank ATR at entry against its own trailing 720 hours and compare crowded
    against normal INSIDE each volatility quintile. Within a quintile the denominators
    are comparable, so anything left is positioning.

Directional convention: the trade is taken in the direction of the prior move over the
same horizon, matching the COT study that produced the hypothesis. Adverse is the worst
excursion against it; favourable the best with it. Frozen parameters throughout -
extremes top/bottom 5%, middle 20-80%, 720-hour trailing rank.
"""
import os, csv, math, random
import numpy as np
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
TOPQ, RANK_W, VOL_W = 0.05, 720, 252
HORIZONS = [("4 hours", 4), ("8 hours", 8), ("1 day", 24), ("3 days", 72)]
N_ROT, NQ = 300, 5
rng = random.Random(1234)


def trank(v, order, w):
    x = v[order]; n = len(x)
    out = np.full(n, np.nan)
    if n <= w:
        return out
    win = np.lib.stride_tricks.sliding_window_view(x, w)[:-1]
    out[w:] = (win < x[w:, None]).mean(axis=1)
    return out


def load(inst):
    H = defaultdict(list)
    with open(os.path.join(DATA, "hist_%s.csv" % inst), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k in ("high", "low", "close", "interest_8h"):
                H[k].append(float(r[k]))
    hi, lo, cl = (np.array(H[k], float) for k in ("high", "low", "close"))
    fund = np.array(H["interest_8h"], float)
    pc = np.roll(cl, 1); pc[0] = cl[0]
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - pc), np.abs(lo - pc)))
    atr = np.full(len(tr), np.nan)
    c = np.cumsum(tr)
    atr[14:] = (c[14:] - np.concatenate(([0], c[:-15]))) / 14
    return hi, lo, cl, fund, atr


def trades(hi, lo, cl, atr, hold):
    """Directional trade at each bar: adverse and favourable against the prior move."""
    n = len(cl)
    lc = np.log(cl)
    adv = np.full(n, np.nan); fav = np.full(n, np.nan); dirn = np.zeros(n)
    for i in range(max(VOL_W, hold), n - hold):
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        d = np.sign(lc[i] - lc[i - hold])
        if d == 0:
            continue
        w = slice(i + 1, i + 1 + hold)
        mx, mn, e = hi[w].max(), lo[w].min(), cl[i]
        if d > 0:
            adv[i] = (e - mn) / A; fav[i] = (mx - e) / A
        else:
            adv[i] = (mx - e) / A; fav[i] = (e - mn) / A
        dirn[i] = d
    return adv, fav, dirn


def stat(a):
    a = np.asarray([x for x in a if np.isfinite(x)])
    if len(a) < 40:
        return None
    return {"n": len(a), "mean": float(a.mean()), "p90": float(np.percentile(a, 90)),
            "stop": float((a >= 1.0).mean()), "se": float(a.std() / math.sqrt(len(a)))}


for inst in ("BTC_PERPETUAL", "ETH_PERPETUAL"):
    p = os.path.join(DATA, "hist_%s.csv" % inst)
    if not os.path.exists(p):
        print("%s: no cache\n" % inst); continue
    hi, lo, cl, fund, atr = load(inst)
    frk = trank(fund, np.arange(len(fund)), RANK_W)
    vrk = trank(atr, np.arange(len(atr)), RANK_W)          # where entry vol sits
    print("=" * 100)
    print("%s  %s hourly rows" % (inst, f"{len(cl):,}"))

    for hname, hold in HORIZONS:
        adv, fav, dirn = trades(hi, lo, cl, atr, hold)
        idx = [i for ph in range(hold)
               for i in range(max(VOL_W, hold) + ph, len(cl) - hold, hold)]
        idx = [i for i in idx if np.isfinite(adv[i]) and np.isfinite(frk[i])
               and np.isfinite(vrk[i]) and dirn[i] != 0]
        crowd = lambda i: frk[i] <= TOPQ or frk[i] >= 1 - TOPQ
        norm = lambda i: 0.2 < frk[i] < 0.8

        ce, ne = stat([adv[i] for i in idx if crowd(i)]), stat([adv[i] for i in idx if norm(i)])
        cf, nf = stat([fav[i] for i in idx if crowd(i)]), stat([fav[i] for i in idx if norm(i)])
        if not (ce and ne and cf and nf):
            continue
        d_a, d_f = ce["mean"] - ne["mean"], cf["mean"] - nf["mean"]
        two_a = 2 * math.sqrt(ce["se"] ** 2 + ne["se"] ** 2)

        print("\n  horizon %-8s  crowded n=%d   normal n=%d" % (hname, ce["n"], ne["n"]))
        print("     %-24s %8s %8s %9s %9s" % ("", "crowded", "normal", "diff", "2SE"))
        print("     %-24s %8.3f %8.3f %+9.3f %9.3f  %s"
              % ("adverse (vs prior dir)", ce["mean"], ne["mean"], d_a, two_a,
                 "significant" if abs(d_a) > two_a else "noise"))
        print("     %-24s %8.3f %8.3f %+9.3f" % ("favourable", cf["mean"], nf["mean"], d_f))
        print("     %-24s %8.3f %8.3f %+9.3f"
              % ("adverse/favourable", ce["mean"] / max(cf["mean"], 1e-9),
                 ne["mean"] / max(nf["mean"], 1e-9),
                 ce["mean"] / max(cf["mean"], 1e-9) - ne["mean"] / max(nf["mean"], 1e-9)))
        print("     %-24s %7.1f%% %7.1f%% %+8.1fpp"
              % ("hit 1.0x ATR", ce["stop"] * 100, ne["stop"] * 100,
                 (ce["stop"] - ne["stop"]) * 100))

        # ---- the control: same comparison inside entry-volatility quintiles ----
        cuts = np.quantile([vrk[i] for i in idx], np.linspace(0, 1, NQ + 1)[1:-1])
        inside, sig = [], 0
        print("     %-24s" % "within entry-vol quintiles:", end="")
        for q in range(NQ):
            sub = [i for i in idx if int(np.searchsorted(cuts, vrk[i])) == q]
            a, b = stat([adv[i] for i in sub if crowd(i)]), stat([adv[i] for i in sub if norm(i)])
            if not (a and b):
                print(" %-9s" % "-", end=""); continue
            dd = a["mean"] - b["mean"]
            inside.append(dd)
            if abs(dd) > 2 * math.sqrt(a["se"] ** 2 + b["se"] ** 2):
                sig += 1
            print(" %+8.3f" % dd, end="")
        if inside:
            m = float(np.mean(inside))
            print("\n     %-24s %+.3f  (raw %+.3f -> %s)"
                  % ("mean inside quintiles", m, d_a,
                     "SURVIVES the volatility control" if abs(m) > 0.5 * abs(d_a)
                     else "COLLAPSES - it was the ATR denominator"))

    # ---- two-sided rotation null at the 1-day horizon ----
    hold = 24
    adv, fav, dirn = trades(hi, lo, cl, atr, hold)
    base = [i for i in range(max(VOL_W, hold), len(cl) - hold, hold)
            if np.isfinite(adv[i]) and dirn[i] != 0]

    def gap(rr):
        e = [adv[i] for i in base if np.isfinite(rr[i]) and (rr[i] <= TOPQ or rr[i] >= 1 - TOPQ)]
        m = [adv[i] for i in base if np.isfinite(rr[i]) and 0.2 < rr[i] < 0.8]
        return (float(np.mean(e)) - float(np.mean(m))) if len(e) > 40 and len(m) > 80 else None

    real = gap(frk)
    rot = []
    n = len(fund)
    for _ in range(N_ROT):
        off = rng.randrange(RANK_W, n - RANK_W)
        g = gap(trank(fund, (np.arange(n) + off) % n, RANK_W))
        if g is not None:
            rot.append(g)
    rot = np.array(rot)
    if real is not None and len(rot):
        # TWO-SIDED: how often is a rotation at least as extreme, either way?
        centre = rot.mean()
        pct = float((np.abs(rot - centre) >= abs(real - centre)).mean())
        print("\n  rotation null (1 day, two-sided): real %+.4f | rotated %+.4f sd %.4f"
              % (real, centre, rot.std()))
        print("  %.1f%% of %d rotations were at least this far from centre -> %s\n"
              % (pct * 100, len(rot), "REAL" if pct <= 0.05 else "noise"))

print("""
The line that decides it is "mean inside quintiles". Comparing crowded against normal
within a volatility band removes the ATR-denominator artefact. If the difference holds
up there, crowding genuinely changes trade risk on BTC. If it collapses, the raw result
was volatility mean-reversion and there is nothing here for the risk engine - which
would close this branch exactly as agreed.""")
