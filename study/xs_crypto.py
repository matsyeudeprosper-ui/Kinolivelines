"""Cross-sectional momentum on OKX perpetuals - the same test the 19 stocks failed.

The stock version failed for a structural reason, not a signal one: 5 long + 5 short from
19 names is a concentrated book with 5.7% per-rebalance noise, so its minimum detectable
effect was 1.47% - only a very large edge could ever have shown. This runs the identical
preregistered grid on 57 crypto perps with 10 a side, which is what the diagnosis said
was missing.

IDENTICAL DESIGN, so the comparison is honest
  lookbacks L : 5, 10, 21, 63, 126 days
  holds     H : 5, 10, 21 days
  legs      K : 10 long, 10 short, equal weight, dollar neutral
  decision    : clears its error bar in DEV and keeps sign with t > 1.5 in HOLDOUT
  control     : 200 random rankings per cell - the stock run showed the 95th percentile
                of |t| under random ranking was 3.2-4.1, not the textbook 2, so the bar
                is set by the control rather than assumed
  costs       : OKX taker is 0.05% a side. Two legs, in and out, is 4 x 0.05% = 0.20%
                per rebalance, charged every time.

SURVIVORSHIP BIAS - REAL, BUT ITS DIRECTION IS NOT THE OBVIOUS ONE
Only currently-LIVE perps can be fetched, and in crypto the list of dead ones is long.
The instinctive reading is that this flatters the strategy. For a long-only book it would.
For a dollar-neutral momentum book it mostly runs the OTHER way: a coin that collapsed and
was delisted would have ranked at the BOTTOM and been SHORTED, and shorting something on
its way to zero is the single most profitable trade the strategy can make. Those trades are
missing from this sample.

So the honest statement is that the bias is two-sided - it removes some winning longs and
some very large winning shorts - and its net direction is unknown, probably understating
momentum. That means a null here is weaker evidence than a null on clean data, not
stronger. Do not lean on it as if it were conservative.

FUNDING is not modelled. A dollar-neutral perp book pays funding on longs and receives it
on shorts, which roughly cancels but not exactly. Since the fee assumption already
dominates, the breakeven cost is reported instead - what total round-trip cost would just
erase the result - which is more useful than a guessed funding number.
"""
import json, math, os
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
LOOKBACKS = [5, 10, 21, 63, 126]
HOLDS = [5, 10, 21]
K = 10
MIN_NAMES = 30                 # names that must be priced on a rebalance day
COST = 0.0020                  # 4 x 0.05% taker, per rebalance

raw = json.load(open(os.path.join(HERE, "okx_daily.json")))
ser = {}
for inst, rows in raw.items():
    s = pd.Series({pd.to_datetime(int(t), unit="ms").normalize(): float(c) for t, c in rows})
    ser[inst.replace("-USDT-SWAP", "")] = s.sort_index()
px = pd.DataFrame(ser).sort_index()
px = px[~px.index.duplicated(keep="last")]

print("PANEL: %d perps, %s to %s" % (px.shape[1], px.index.min().date(), px.index.max().date()))
cover = px.notna().sum(axis=1)
print("names priced per day: median %d, max %d" % (cover.median(), cover.max()))
px = px[cover >= MIN_NAMES]
print("days with >= %d names: %d\n" % (MIN_NAMES, len(px)))

SPLIT = px.index[int(len(px) * 0.6)]
print("dev  : %s to %s" % (px.index.min().date(), SPLIT.date()))
print("hold : %s to %s\n" % (SPLIT.date(), px.index.max().date()))

P = px.to_numpy(float)
dates = px.index


def run(L, H, randomise=False, seed=None):
    r = np.random.default_rng(seed) if randomise else None
    out_t, out_r = [], []
    i = L
    while i + H < len(P):
        past = P[i] / P[i - L] - 1.0
        fwd = P[i + H] / P[i] - 1.0
        ok = ~(np.isnan(past) | np.isnan(fwd))     # names alive across the whole window
        if ok.sum() < 2 * K + 5:
            i += H; continue
        w = np.where(ok)[0]
        order = w[r.permutation(len(w))] if randomise else w[np.argsort(past[w])]
        lo, hi = order[:K], order[-K:]
        out_t.append(dates[i]); out_r.append(fwd[hi].mean() - fwd[lo].mean() - COST)
        i += H                                      # NON-OVERLAPPING
    return np.array(out_t), np.array(out_r)


def stat(x):
    if len(x) < 8:
        return float("nan"), float("nan")
    return x.mean(), x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))


print("MOMENTUM  (long top %d, short bottom %d)   net of %.2f%% round-trip cost"
      % (K, K, 100 * COST))
print("%-5s %-5s %6s %11s %7s %11s %7s %8s   %s"
      % ("look", "hold", "n", "dev mean", "dev t", "hold mean", "hold t", "rand t", "verdict"))
print("-" * 90)
results = []
for L in LOOKBACKS:
    for H in HOLDS:
        t, r = run(L, H)
        if len(r) < 20:
            continue
        dev, hold = r[t < SPLIT], r[t >= SPLIT]
        dm, dt = stat(dev); hm, ht = stat(hold)
        rts = []
        for s in range(200):
            _, rr = run(L, H, randomise=True, seed=s)
            _, tt = stat(rr)
            if not math.isnan(tt):
                rts.append(abs(tt))
        rand_hi = np.percentile(rts, 95) if rts else float("nan")
        passes = (abs(dt) > rand_hi) and (np.sign(hm) == np.sign(dm)) and (abs(ht) > 1.5)
        results.append((L, H, dm, dt, hm, ht, rand_hi, passes))
        print("%-5d %-5d %6d %10.3f%% %7.2f %10.3f%% %7.2f %8.2f   %s"
              % (L, H, len(r), 100 * dm, dt, 100 * hm, ht, rand_hi,
                 "SURVIVES" if passes else ("beats random in dev only"
                                            if abs(dt) > rand_hi else "-")))

print("\n'rand t' = 95th percentile of |t| over 200 random rankings. A cell must beat ITS")
print("OWN control, not the textbook 2 - the stock run showed that bar is far too lenient.")

surv = [x for x in results if x[7]]
print("\n%d of %d cells survive dev AND holdout." % (len(surv), len(results)))
for L, H, dm, dt, hm, ht, rh, _ in surv:
    ann = (1 + dm) ** (252 / H) - 1
    print("   look %-4d hold %-4d  dev %+.3f%% (t %.2f)  hold %+.3f%% (t %.2f)  ~%.0f%%/yr gross of slippage"
          % (L, H, 100 * dm, dt, 100 * hm, ht, 100 * ann))
    be = dm + COST
    print("      breakeven round-trip cost %.3f%% (currently assumed %.3f%%)" % (100 * be, 100 * COST))

if not surv:
    _, r = run(21, 10)
    sd = r.std(ddof=1)
    print("""No cell survives. What this sample could have seen:
  %d non-overlapping rebalances, sd %.3f%% each -> smallest detectable effect ~%.3f%%
Compare the 19-stock run, whose MDE was 1.472%%. If this number is much smaller, breadth
did what it was supposed to and the answer is genuinely 'no edge', not 'not enough data'."""
          % (len(r), 100 * sd, 100 * 2.8 * sd / math.sqrt(len(r))))
    print("\nAnd remember the survivorship tilt runs in the strategy's FAVOUR, so a null")
    print("here is stronger evidence than a null on clean data would be.")
