"""H1: does the perpetual's premium/discount to its own index carry a tradeable edge?

MECHANISM. A perpetual swap never expires, so nothing forces it to equal spot. It trades
at a premium when leveraged longs are bidding for exposure and at a discount when
positions are being dumped. Market makers close the gap by taking the other side and
hedging in spot, so the deviation must revert - the only question is whether the
reversion is large and slow enough to clear a $10 spread.

WHY THIS IS NOT THE FUNDING TEST AGAIN. Measured on this very file:
corr(basis, funding) = 0.046. Essentially orthogonal. Funding is an eight-hour smoothed
average of the same pressure and has already been tested and found null for direction.
The instantaneous basis has never been tested at all.

DESIGN
  signal      basis = (perp close - index) / index, in basis points, ranked against its
              own trailing 720 hours so nothing uses information from the future
  direction   FADE the extreme (short a rich perp, buy a cheap one) is the mechanism's
              prediction. FOLLOW is carried as its mirror - if both look good the filter
              is selecting easy windows rather than a side
  control     random entries matched in count, run through identical machinery. Without
              this, drift reads as edge
  horizons    4h, 24h, 72h - where the spread costs 2.6%, 0.6% and 0.35% of ATR
  costs       the real $10 Exness spread on entry
  overlap     every phase of non-overlapping windows; no two trades share a bar
  confound    every comparison stratified by entry volatility, because funding-like
              extremes arrive after violent moves and an ATR-normalised measure inverts
              its own sign if that is ignored
  holdout     the final 18 months are never used to choose anything

PASS/FAIL, fixed before running: beat the matched random control by more than 2SE, keep
the sign in at least 4 of 5 volatility quintiles, replicate on ETH, survive a two-sided
rotation null, and hold on the untouched holdout. Anything less is not an edge.
"""
import os, math, random
import numpy as np, pandas as pd

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
RANK_W, TOPQ, NQ = 720, 0.05, 5
# The spread we actually pay, per instrument. Applying BTC's $10 to ETH (which trades
# near $1,900 with a $1.00 spread) inflates its cost tenfold and made every ETH number
# meaningless in the first run.
SPREADS = {"BTC_PERPETUAL": 10.0, "ETH_PERPETUAL": 1.0}
HORIZONS = [("4h", 4), ("24h", 24), ("72h", 72)]
HOLDOUT_FROM = "2025-02-01"
N_ROT = 300
rng = random.Random(31337)


def trank(v, w=RANK_W):
    out = np.full(len(v), np.nan)
    win = np.lib.stride_tricks.sliding_window_view(v, w)[:-1]
    out[w:] = (win < v[w:, None]).mean(axis=1)
    return out


def load(inst):
    d = pd.read_csv(os.path.join(DATA, "hist_%s.csv" % inst))
    hi, lo, cl = (d[c].to_numpy(float) for c in ("high", "low", "close"))
    idx = d["index_price"].to_numpy(float)
    basis = (cl - idx) / idx * 1e4
    pc = np.roll(cl, 1); pc[0] = cl[0]
    tr = np.maximum(hi - lo, np.maximum(np.abs(hi - pc), np.abs(lo - pc)))
    c = np.cumsum(tr)
    atr = np.full(len(cl), np.nan)
    atr[14:] = (c[14:] - np.concatenate(([0], c[:-15]))) / 14
    return d, hi, lo, cl, basis, atr


def fwd_net(cl, atr, i, h, side, spread):
    """Forward return over h hours in ATR units, after paying the spread once."""
    if i + h >= len(cl) or not np.isfinite(atr[i]) or atr[i] <= 0:
        return np.nan
    return (side * (cl[i + h] - cl[i]) - spread) / atr[i]


def stratified(vals_a, vals_b, vq):
    """Weighted mean of (a - b) within volatility strata, with pooled 2SE."""
    num = den = var = 0.0
    cells = []
    for q in range(NQ):
        m = vq == q
        a, b = vals_a[m], vals_b[m]
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
        if len(a) < 30 or len(b) < 30:
            cells.append(None); continue
        d = a.mean() - b.mean()
        w = len(a)
        num += w * d; den += w
        var += w * w * (a.var() / len(a) + b.var() / len(b))
        cells.append(d)
    if den == 0:
        return None
    return num / den, 2 * math.sqrt(var) / den, cells


for inst in ("BTC_PERPETUAL", "ETH_PERPETUAL"):
    p = os.path.join(DATA, "hist_%s.csv" % inst)
    if not os.path.exists(p):
        continue
    d, hi, lo, cl, basis, atr = load(inst)
    spread = SPREADS[inst]
    brank = trank(basis)
    vrank = trank(np.where(np.isfinite(atr), atr, 0.0))
    utc = pd.to_datetime(d["utc"])
    hold_mask = (utc >= HOLDOUT_FROM).to_numpy()

    print("=" * 104)
    print("%s   %s hourly rows   basis sd %.1f bp   corr with funding %.3f"
          % (inst, f"{len(cl):,}", np.nanstd(basis),
             np.corrcoef(basis, d["interest_8h"])[0, 1]))

    for period, pmask in (("DEVELOPMENT", ~hold_mask), ("HOLDOUT (untouched)", hold_mask)):
        print("\n  %s   %s hours" % (period, f"{int(pmask.sum()):,}"))
        print("    %-6s %-8s %9s %10s %10s %9s  %s"
              % ("horiz", "arm", "n", "mean R", "vs random", "2SE", "quintiles"))
        print("    " + "-" * 78)
        for hname, h in HORIZONS:
            ok = np.where(np.isfinite(atr) & (atr > 0) & np.isfinite(brank)
                          & np.isfinite(vrank) & pmask)[0]
            ok = ok[(ok > RANK_W) & (ok < len(cl) - h - 1)]
            if len(ok) < 500:
                continue
            cuts = np.quantile(vrank[ok], np.linspace(0, 1, NQ + 1)[1:-1])
            rich = ok[brank[ok] >= 1 - TOPQ]
            cheap = ok[brank[ok] <= TOPQ]
            # THE CONTROL MUST BE VOLATILITY-MATCHED. Basis extremes arrive after violent
            # moves, so signal entries sit at high ATR while a freely-drawn control sits
            # at average ATR. ATR is the denominator, so the control's returns come out
            # larger in magnitude and the signal appears to beat it on BOTH arms - which
            # is exactly what the first run showed. Each control is therefore drawn from
            # the SAME volatility quintile as the trade it is standing in for.
            by_q = {q: [int(x) for x in ok
                        if int(np.searchsorted(cuts, vrank[x])) == q] for q in range(NQ)}
            for arm in ("FADE", "FOLLOW"):
                sig, ctrl, vq = [], [], []
                for grp, s0 in ((rich, -1 if arm == "FADE" else +1),
                                (cheap, +1 if arm == "FADE" else -1)):
                    seq, busy = [], -1
                    for i in grp:
                        if i > busy:
                            seq.append(int(i)); busy = i + h
                    for i in seq:
                        q = int(np.searchsorted(cuts, vrank[i]))
                        cand = by_q.get(q) or []
                        if len(cand) < 20:
                            continue
                        v = fwd_net(cl, atr, i, h, s0, spread)
                        j = cand[rng.randrange(len(cand))]
                        c = fwd_net(cl, atr, j, h, s0, spread)   # same side, same vol band
                        if np.isfinite(v) and np.isfinite(c):
                            sig.append(v); ctrl.append(c); vq.append(q)
                if len(sig) < 150:
                    continue
                sig, ctrl, vq = np.array(sig), np.array(ctrl), np.array(vq)
                st = stratified(sig, ctrl, vq)
                if st is None:
                    continue
                est, two, cells = st
                agree = sum(1 for c in cells if c is not None and (c > 0) == (est > 0))
                got = sum(1 for c in cells if c is not None)
                flag = "  <== BEATS RANDOM" if est > two and agree >= 4 else ""
                print("    %-6s %-8s %9d %10.4f %10.4f %9.4f  %d of %d%s"
                      % (hname, arm, len(sig), sig.mean(), est, two, agree, got, flag))
    print()

print("""
'vs random' is the only column that means anything - it is the signal minus a matched
random entry taken on the same side, so drift and the spread are already inside both.
A positive mean R with a 'vs random' near zero is the market going up, not an edge.

FADE and FOLLOW are the same trades with the sign flipped, so they must come out roughly
mirrored. If both are positive the volatility stratification or the control is broken,
not the market.""")
