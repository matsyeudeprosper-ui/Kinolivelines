"""Decisive test: stratified by volatility, does crowding widen BTC trade risk at 4-8h?

Where this stands. The raw effect at 1-3 day horizons was volatility mean-reversion -
funding extremes follow violent moves, ATR at entry is already swollen, and dividing
by it makes forward excursions look small. Controlling for entry volatility collapsed
it to nothing, exactly as a denominator artefact should.

But at 4 and 8 hours - which is the scale the live system actually trades - the
within-volatility differences came out POSITIVE in every quintile on both BTC and ETH,
around +5% of adverse excursion. That is the same sign and nearly the same size as the
COT result on thirty markets. It deserves a real test rather than the broken heuristic
that flagged it.

WHAT WAS WRONG WITH THAT HEURISTIC, so it is not repeated: it declared the effect
"surviving" when |within-quintile mean| exceeded half the |raw| difference. When the raw
difference is near zero - as it is at 4 hours, +0.004 - that test passes automatically
and means nothing. A stratified estimate has to be judged against its own error bar, not
against the unstratified number.

THE TEST HERE:
  * strata are quintiles of ATR-at-entry ranked against its own trailing 720 hours, so
    crowded and normal trades are only ever compared at similar volatility
  * the estimate is the sample-size-weighted mean of the within-stratum differences,
    with the correct pooled standard error
  * the rotation null is recomputed on the SAME stratified statistic - not the raw one -
    because the stratification itself could induce structure, and it is two-sided
  * every phase of the non-overlapping windows is used
  * BTC and ETH each stand alone; agreement between them is the replication

Frozen parameters: extremes top/bottom 5%, normal 20-80%, 720-hour trailing ranks,
trade taken in the direction of the prior move over the same horizon.
"""
import os, csv, math, random
import numpy as np
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
TOPQ, RANK_W, VOL_W, NQ = 0.05, 720, 252, 5
HORIZONS = [("4 hours", 4), ("8 hours", 8), ("1 day", 24)]
N_ROT = 400
rng = random.Random(2718)


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
    pc = np.roll(cl, 1); pc[0] = cl[0]
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - pc), np.abs(lo - pc)))
    atr = np.full(len(tr), np.nan)
    c = np.cumsum(tr)
    atr[14:] = (c[14:] - np.concatenate(([0], c[:-15]))) / 14
    return hi, lo, cl, np.array(H["interest_8h"], float), atr


def trade_arrays(hi, lo, cl, atr, hold):
    n = len(cl); lc = np.log(cl)
    adv = np.full(n, np.nan)
    lo_r = np.full(n, np.nan); hi_r = np.full(n, np.nan)
    for i in range(max(VOL_W, hold), n - hold):
        A = atr[i]
        if not np.isfinite(A) or A <= 0:
            continue
        d = np.sign(lc[i] - lc[i - hold])
        if d == 0:
            continue
        w = slice(i + 1, i + 1 + hold)
        mx, mn, e = hi[w].max(), lo[w].min(), cl[i]
        adv[i] = (e - mn) / A if d > 0 else (mx - e) / A
    return adv


def stratified(adv_v, vq, f_v):
    """Weighted mean of within-stratum (crowded - normal), with its pooled SE.

    Fully vectorised, and it has to be: the rotation null calls this hundreds of times
    per horizon. The first version indexed a Python list of ~50,000 trades five times
    per rotation and never finished.

    adv_v, vq and f_v are pre-sliced arrays over the selected trades - adverse excursion,
    volatility-quintile id, and funding rank. Only f_v changes between rotations; the
    volatility strata are fixed, which is what makes the comparison a controlled one.
    """
    crowd = (f_v <= TOPQ) | (f_v >= 1 - TOPQ)
    norm = (f_v > 0.2) & (f_v < 0.8)
    num = den = var = 0.0
    cells = []
    for q in range(NQ):
        mq = vq == q
        e = adv_v[mq & crowd]
        m = adv_v[mq & norm]
        if len(e) < 40 or len(m) < 80:
            cells.append(None); continue
        d = float(e.mean() - m.mean())
        w = len(e)
        se2 = e.var() / len(e) + m.var() / len(m)
        num += w * d; den += w; var += (w ** 2) * se2
        cells.append((d, len(e), len(m), 2 * math.sqrt(se2)))
    if den == 0:
        return None
    return num / den, 2 * math.sqrt(var) / den, cells


for inst in ("BTC_PERPETUAL", "ETH_PERPETUAL"):
    if not os.path.exists(os.path.join(DATA, "hist_%s.csv" % inst)):
        print("%s: no cache\n" % inst); continue
    hi, lo, cl, fund, atr = load(inst)
    frk = trank(fund, np.arange(len(fund)), RANK_W)
    vrk = trank(atr, np.arange(len(atr)), RANK_W)
    print("=" * 98)
    print("%s   %s hourly rows   (positive = crowded trades suffer MORE)" % (inst, f"{len(cl):,}"))

    for hname, hold in HORIZONS:
        adv = trade_arrays(hi, lo, cl, atr, hold)
        idx = [i for ph in range(hold)
               for i in range(max(VOL_W, hold) + ph, len(cl) - hold, hold)]
        idx = [i for i in idx if np.isfinite(adv[i]) and np.isfinite(frk[i]) and np.isfinite(vrk[i])]
        if len(idx) < 500:
            continue
        ii = np.array(idx)
        adv_v = adv[ii]
        cuts = np.quantile(vrk[ii], np.linspace(0, 1, NQ + 1)[1:-1])
        vq = np.searchsorted(cuts, vrk[ii])          # fixed strata, never rotated
        res = stratified(adv_v, vq, frk[ii])
        if not res:
            continue
        est, two, cells = res
        same = sum(1 for c in cells if c and (c[0] > 0) == (est > 0))
        got = sum(1 for c in cells if c)

        print("\n  horizon %s" % hname)
        print("     %-14s %9s %9s %10s %9s" % ("vol quintile", "n crowd", "n normal", "diff", "2SE"))
        for q, c in enumerate(cells):
            if not c:
                print("     %-14s %9s" % ("Q%d" % (q + 1), "too few")); continue
            print("     %-14s %9d %9d %+10.3f %9.3f" % ("Q%d" % (q + 1), c[1], c[2], c[0], c[3]))
        print("     %-14s %19s %+10.3f %9.3f   %d of %d same sign"
              % ("STRATIFIED", "", est, two, same, got))

        # Two-sided rotation null on the stratified statistic itself.
        #
        # The rank array is rolled directly rather than re-ranking rotated funding.
        # Both destroy the alignment between positioning and price, but rolling the
        # finished ranks keeps every value computed from the history it genuinely had,
        # and avoids re-running a 46-million-comparison rank for each of 400 draws.
        rot = []
        n = len(frk)
        for _ in range(N_ROT):
            off = rng.randrange(RANK_W, n - RANK_W)
            rr = stratified(adv_v, vq, np.roll(frk, off)[ii])
            if rr:
                rot.append(rr[0])
        rot = np.array(rot)
        if len(rot) > 50:
            centre = rot.mean()
            pct = float((np.abs(rot - centre) >= abs(est - centre)).mean())
            verdict = ("REAL" if pct <= 0.05 and abs(est) > two and same >= 4
                       else "not distinguishable from noise")
            print("     rotation null: rotated %+.4f sd %.4f | real at %.1f%% two-sided -> %s"
                  % (centre, rot.std(), pct * 100, verdict))
    print()

print("""
To count, a horizon needs all three: the stratified estimate beyond its own 2SE, the
same sign in at least 4 of 5 volatility quintiles, and a rotation p at or under 5% -
and then the same thing on the other instrument. Anything less and this branch closes,
which is the agreed outcome and a perfectly good one: it would mean crowding shows up
across thirty diverse futures markets but not in crypto perpetuals at trading horizons,
and the live risk engine stays as it is.""")
