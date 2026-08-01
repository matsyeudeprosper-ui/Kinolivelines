"""Is a +6% adverse excursion big enough to change anything the bot does?

The effect is real: at a 4-hour horizon, crowded funding raises adverse excursion by
+0.061 ATR on BTC and +0.051 on ETH, same sign in all five volatility quintiles, and
past a two-sided rotation null on both. It matches the +5.6% found on twenty unseen
futures markets from weekly COT - a replication across genuinely unrelated data.

Statistical reality and practical usefulness are different questions though. A mean is
not what stops a trade out; a threshold is. So before simulating position-sizing rules,
measure the thing the rules would actually change:

    stop-out rate at 0.7x, 1.0x and 1.5x ATR - the band the live rules use
    the excursion at the 75th, 90th and 95th percentile - where risk actually lives

All of it stratified by entry volatility, because the unstratified version of this
comparison was pure ATR-denominator artefact at longer horizons.

WHY THIS GATES THE NEXT STEP. The live account has taken 19 trades. If crowding shifts
the stop-out rate by a fraction of a percentage point, no sizing rule keyed to it can
produce a detectable improvement in expectancy or drawdown - simulating three variants
would be measuring noise and dressing it up as a comparison. If the shift is a few
points, the simulation is worth building.
"""
import os, csv, math
import numpy as np
from collections import defaultdict

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "recorder", "data")
TOPQ, RANK_W, VOL_W, NQ, HOLD = 0.05, 720, 252, 5, 4
STOPS = [0.7, 1.0, 1.5]


def trank(v, w):
    n = len(v)
    out = np.full(n, np.nan)
    win = np.lib.stride_tricks.sliding_window_view(v, w)[:-1]
    out[w:] = (win < v[w:, None]).mean(axis=1)
    return out


for inst in ("BTC_PERPETUAL", "ETH_PERPETUAL"):
    p = os.path.join(DATA, "hist_%s.csv" % inst)
    if not os.path.exists(p):
        continue
    H = defaultdict(list)
    with open(p, encoding="utf-8") as f:
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
    frk, vrk = trank(fund, RANK_W), trank(atr, RANK_W)
    lc = np.log(cl)

    rows = []
    for ph in range(HOLD):
        for i in range(max(VOL_W, HOLD) + ph, len(cl) - HOLD, HOLD):
            A = atr[i]
            if not np.isfinite(A) or A <= 0 or not np.isfinite(frk[i]) or not np.isfinite(vrk[i]):
                continue
            d = np.sign(lc[i] - lc[i - HOLD])
            if d == 0:
                continue
            w = slice(i + 1, i + 1 + HOLD)
            e = cl[i]
            adv = (e - lo[w].min()) / A if d > 0 else (hi[w].max() - e) / A
            rows.append((adv, frk[i], vrk[i]))
    adv = np.array([r[0] for r in rows]); f = np.array([r[1] for r in rows])
    v = np.array([r[2] for r in rows])
    cuts = np.quantile(v, np.linspace(0, 1, NQ + 1)[1:-1])
    vq = np.searchsorted(cuts, v)
    crowd = (f <= TOPQ) | (f >= 1 - TOPQ)
    norm = (f > 0.2) & (f < 0.8)

    def strat(fn):
        """Sample-weighted mean of a per-stratum statistic, crowded minus normal."""
        num = den = var = 0.0
        for q in range(NQ):
            m = vq == q
            e, o = adv[m & crowd], adv[m & norm]
            if len(e) < 40 or len(o) < 80:
                continue
            a, b = fn(e), fn(o)
            w = len(e)
            # binomial variance for rates, sample variance otherwise
            se2 = (a * (1 - a) / len(e) + b * (1 - b) / len(o)) if 0 <= a <= 1 and 0 <= b <= 1 \
                else (e.var() / len(e) + o.var() / len(o))
            num += w * (a - b); den += w; var += w * w * se2
        return (num / den, 2 * math.sqrt(var) / den) if den else (float("nan"),) * 2

    print("=" * 84)
    print("%s   %s trades at the 4-hour horizon   (crowded %d / normal %d)"
          % (inst, f"{len(adv):,}", int(crowd.sum()), int(norm.sum())))
    print("  %-26s %10s %10s %11s %9s" % ("", "crowded", "normal", "difference", "2SE"))
    print("  " + "-" * 72)
    for s in STOPS:
        fn = lambda a, s=s: float((a >= s).mean())
        d, two = strat(fn)
        print("  %-26s %9.1f%% %9.1f%% %+10.2fpp %8.2fpp  %s"
              % ("stopped out at %.1fx ATR" % s,
                 fn(adv[crowd]) * 100, fn(adv[norm]) * 100, d * 100, two * 100,
                 "" if abs(d) > two else "(inside noise)"))
    print("  " + "-" * 72)
    for pctl in (75, 90, 95):
        fn = lambda a, p=pctl: float(np.percentile(a, p))
        d, two = strat(fn)
        print("  %-26s %10.3f %10.3f %+11.3f %9.3f"
              % ("p%d adverse excursion" % pctl,
                 fn(adv[crowd]), fn(adv[norm]), d, two))
    dm, twom = strat(lambda a: float(a.mean()))
    print("  %-26s %10.3f %10.3f %+11.3f %9.3f"
          % ("mean adverse excursion", adv[crowd].mean(), adv[norm].mean(), dm, twom))
    print()

print("""
Read the stop-out rows first - they are what a sizing or stop rule would move. A shift
of a fraction of a point cannot be exploited: it is far below the run-to-run variation
of a 19-trade account, so any backtest of "trade smaller when crowded" would be
reporting noise. A shift of several points would be worth engineering around.""")
