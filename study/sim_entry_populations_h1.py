"""Does PROXIMITY TO A LEVEL destroy the crowding effect? Tested with enough data to tell.

The M15 version of this question could not be answered: BTCUSDm M15 reaches back only 1.4
years, and 4-hour non-overlapping trades leave ~450 crowded observations, giving a 2SE of
5-6pp against an effect of 2-3pp. Every verdict there was "underpowered", including on
the population where the effect is known to be real. A test that cannot see the effect
where it exists cannot be used to argue it is missing anywhere else.

This runs the same comparison on the 7.3-year hourly Deribit series - the data the effect
was originally measured on - so the level-proximity condition is tested with power.

THE FOUR POPULATIONS, differing only in WHEN a trade opens:
    all bars     every hour. The reference: the effect is known to be here
    near level   within 0.06 x ATR(H4) of the previous closed H4 or D1 bar's high or
                 low. This is KinoliveLines' trigger rule shifted one timeframe up -
                 not its exact levels, but the same STRUCTURE: proximity to a recent
                 higher-timeframe extreme
    breakout     close beyond the previous 24 hours' range. A different trigger shape
    random       uniformly sampled, matched in count to the near-level population, to
                 separate "this filter kills it" from "any thinning kills it"

Direction, management, horizon and funding series are identical across all four. Only
entry timing varies.

PHASE POOLING FOR POWER. With a 4-hour hold there are 4 distinct chains of
non-overlapping trades. Each is a clean sample. All four are run and reported: the mean
across them, and how many agree in sign. This uses every hour without ever letting two
trades share a bar - the same discipline used throughout this project. It does not
shrink the error bar dishonestly; the per-chain 2SE is reported as-is.
"""
import os, math, random
import numpy as np, pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "recorder", "data")
STOP_ATR, RR, BE_R, HOLD = 0.8, 1.5, 1.0, 4        # 4 hourly bars = 4 hours
RANK_W, TOPQ, PROX, BRK_LOOK = 720, 0.05, 0.06, 24
SPREAD = 10.0                                       # the Exness BTCUSDm spread we pay
rng = random.Random(4242)

d = pd.read_csv(os.path.join(DATA, "hist_BTC_PERPETUAL.csv"))
hi, lo, cl = (d[c].to_numpy(float) for c in ("high", "low", "close"))
fund = d["interest_1h"].to_numpy(float)
N = len(cl)

pc = np.roll(cl, 1); pc[0] = cl[0]
tr = np.maximum(hi - lo, np.maximum(np.abs(hi - pc), np.abs(lo - pc)))
c = np.cumsum(tr)
atr1 = np.full(N, np.nan); atr1[14:] = (c[14:] - np.concatenate(([0], c[:-15]))) / 14

# higher-timeframe bars built from the hourly series
def agg(step):
    """Rolling high/low of each completed `step`-hour block, as of each hour."""
    H = np.full(N, np.nan); L = np.full(N, np.nan); A = np.full(N, np.nan)
    for b in range(1, N // step):
        s0, s1 = (b - 1) * step, b * step
        H[s1:s1 + step] = hi[s0:s1].max()
        L[s1:s1 + step] = lo[s0:s1].min()
        A[s1:s1 + step] = (hi[s0:s1].max() - lo[s0:s1].min())
    return H, L, A

h4H, h4L, h4R = agg(4)
d1H, d1L, _ = agg(24)
atr4 = pd.Series(h4R).rolling(14).mean().to_numpy()

def trailing_rank(v):
    out = np.full(N, np.nan)
    w = np.lib.stride_tricks.sliding_window_view(v, RANK_W)[:-1]
    out[RANK_W:] = (w < v[RANK_W:, None]).mean(axis=1)
    return out


frank = trailing_rank(fund)

# Entry-volatility rank. THIS IS NOT OPTIONAL. Funding extremes arrive after violent
# moves, so crowded entries sit at systematically higher ATR; comparing them to normal
# entries without holding volatility constant is the confound that inverted the sign of
# this very measurement once already (raw ETH said crowded was SAFER, stratified said
# riskier). Every comparison below is made within volatility quintiles.
vrank = trailing_rank(np.where(np.isfinite(atr1), atr1, 0.0))
NQ = 5


def run(i0, side, stop_d):
    entry = cl[i0] + side * SPREAD / 2
    stop, tgt = entry - side * stop_d, entry + side * stop_d * RR
    be_at = entry + side * stop_d * BE_R
    moved = False
    for k in range(1, HOLD + 1):
        j = i0 + k
        if j >= N:
            break
        hs = (lo[j] <= stop) if side > 0 else (hi[j] >= stop)
        ht = (hi[j] >= tgt) if side > 0 else (lo[j] <= tgt)
        if hs:
            return (0.0 if moved else -1.0), True
        if ht:
            return float(RR), False
        if not moved and ((hi[j] >= be_at) if side > 0 else (lo[j] <= be_at)):
            stop, moved = entry, True
    j = min(i0 + HOLD, N - 1)
    return side * (cl[j] - entry) / stop_d, False


base = np.where(np.isfinite(atr1) & (atr1 > 0) & np.isfinite(frank) & np.isfinite(vrank)
                & np.isfinite(atr4) & (atr4 > 0))[0]
base = base[(base > max(BRK_LOOK, 24) + 1) & (base < N - HOLD - 1)]

near = []
for i in base:
    tol = PROX * atr4[i]
    if any(abs(cl[i] - lv) <= tol for lv in (h4H[i], h4L[i], d1H[i], d1L[i])
           if np.isfinite(lv)):
        near.append(i)
near = np.array(near)

brk = np.array([i for i in base
                if cl[i] > hi[i - BRK_LOOK:i].max() or cl[i] < lo[i - BRK_LOOK:i].min()])

pool = [int(x) for x in base]; rng.shuffle(pool)
rand = np.array(sorted(pool[:len(near)]))

POPS = [("all bars", base), ("near level", near), ("breakout", brk), ("random", rand)]

print("DOES LEVEL PROXIMITY DESTROY THE CROWDING EFFECT?  7.3 years hourly BTC")
print("same direction (prior 4h move), management and funding for every population\n")
print("%-11s %8s %8s %11s %8s  %s"
      % ("population", "trades", "crowded", "gap (strat)", "2SE", "chains agreeing"))
print("-" * 78)

def stratified_gap(so, rk, vq):
    """Sample-weighted crowded-minus-normal stop-out gap, computed within vol quintiles."""
    crowd = (rk <= TOPQ) | (rk >= 1 - TOPQ)
    norm = (rk > 0.2) & (rk < 0.8)
    num = den = var = 0.0
    for q in range(NQ):
        m = vq == q
        e, o = so[m & crowd], so[m & norm]
        if len(e) < 25 or len(o) < 50:
            continue
        pe, po = e.mean(), o.mean()
        w = len(e)
        num += w * (pe - po); den += w
        var += w * w * (pe * (1 - pe) / len(e) + po * (1 - po) / len(o))
    if den == 0:
        return None
    return num / den, 2 * math.sqrt(var) / den, int(crowd.sum()), len(so)


for name, idx in POPS:
    idx = np.asarray(sorted(idx))
    cuts = np.quantile(vrank[idx], np.linspace(0, 1, NQ + 1)[1:-1])
    per_phase, tot_tr, tot_cr, ests, ses = [], 0, 0, [], []
    for ph in range(HOLD):
        seq, busy = [], -1
        for i in idx:
            if i > busy and (i - ph) % HOLD == 0:
                seq.append(int(i)); busy = i + HOLD
        if len(seq) < 150:
            continue
        so, rk, vq = [], [], []
        for i in seq:
            s = np.sign(cl[i] - cl[i - HOLD])
            if s == 0:
                continue
            R, stopped = run(i, s, STOP_ATR * atr1[i])
            so.append(float(stopped)); rk.append(frank[i])
            vq.append(int(np.searchsorted(cuts, vrank[i])))
        g = stratified_gap(np.array(so), np.array(rk), np.array(vq))
        if g is None:
            continue
        per_phase.append(g[0]); ests.append(g[0]); ses.append(g[1])
        tot_tr += g[3]; tot_cr += g[2]
    if not per_phase:
        print("%-11s too few" % name); continue
    dd = float(np.mean(ests))
    two = float(np.mean(ses))                      # per-chain SE, not shrunk by pooling
    pos = sum(1 for x in per_phase if (x > 0) == (dd > 0))
    print("%-11s %8d %8d %+10.1fpp %7.1fpp  %d of %d"
          % (name, tot_tr, tot_cr, 100 * dd, 100 * two, pos, len(per_phase)))

print("""
The reference row is 'all bars'. If the effect does not show up THERE, this test has no
power and nothing below it can be read. If it shows there and on 'random' but not on
'near level', the level condition is genuinely destroying it - and dropping the hlines
would recover a real risk signal. If it shows on 'all bars' but on neither of the two
thinned populations, then any sparse entry selection loses it and the hlines are not
specially to blame.""")
