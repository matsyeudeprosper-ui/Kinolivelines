"""Cross-sectional momentum and reversal on the 19 US stock CFDs.

THE IDEA, and why it is different from everything that failed. Every previous attempt
tried to TIME one instrument - predict whether BTC goes up or down next. This ranks names
against each other on the same day and holds long the top and short the bottom in equal
size. It never needs to know where the market is going, only which names do better than
which. That is a different statistical object, and it is the standard construction behind
most surviving systematic equity strategies.

PREREGISTERED BEFORE LOOKING AT ANY RESULT
  lookbacks  L : 5, 10, 21, 63, 126 trading days
  holds      H : 5, 10, 21 trading days
  legs       K : 5 names long, 5 short, equal weight, dollar neutral
  primary metric : mean net return per rebalance, and its t-statistic
  decision rule  : a cell counts ONLY if it clears its error bar in the DEV half AND
                   keeps the same sign with t > 1.5 in the HOLDOUT half. Anything found
                   in dev alone is treated as noise, because 15 cells are being scanned.
  controls       : the same book built on a RANDOM ranking, run 200 times. If real
                   ranking does not separate from random, there is nothing here.

RIGOR NOTES, each one earned by a mistake in this project
  * NON-OVERLAPPING holds. Overlapping windows shrank standard errors 5.3x elsewhere here.
  * COSTS IN FROM THE START, not bolted on. Both legs pay spread every rebalance and swap
    every night. A gross result with costs added later is how BTC looked tractable for
    eleven attempts.
  * The random control exists because drift reads as edge without it.
  * The dev/holdout split is by DATE, never shuffled - shuffling leaks the future.
"""
import math
import numpy as np, pandas as pd
import MetaTrader5 as mt5

STOCKS = ["TSLA", "AMZN", "INTC", "TSM", "ORCL", "AVGO", "AAPL", "MS", "ADBE", "NVDA",
          "CSCO", "INTU", "HD", "IBM", "AMD", "GOOGL", "PEP", "MCD", "MSFT"]
LOOKBACKS = [5, 10, 21, 63, 126]
HOLDS = [5, 10, 21]
K = 5
rng = np.random.default_rng(20260802)

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
allsyms = {s.name: s for s in mt5.symbols_get()}
series, cost = {}, {}
for base in STOCKS:
    name = next((n for n in allsyms if n.upper() == base + "M"), None)
    if name is None:
        continue
    mt5.symbol_select(name, True)
    r = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_D1, 0, 5000)
    s = mt5.symbol_info(name)
    if r is None or len(r) == 0 or s is None:
        continue
    d = pd.DataFrame(r)
    d["t"] = pd.to_datetime(d["time"], unit="s").dt.normalize()
    ser = d.set_index("t")["close"].astype(float)
    series[name] = ser[~ser.index.duplicated(keep="last")]
    notional = s.ask * s.trade_contract_size
    cost[name] = {
        # one full spread per round trip, as a fraction of notional
        "spread": (s.ask - s.bid) / s.ask if s.ask > 0 else 0.0006,
        "swap_long": abs(s.swap_long) / notional if notional > 0 else 0.0003,
        "swap_short": abs(s.swap_short) / notional if notional > 0 else 0.0003,
    }
mt5.shutdown()

px = pd.DataFrame(series).sort_index().dropna()
names = list(px.columns)
C = pd.DataFrame(cost).T.reindex(names)
print("PANEL: %d names, %d common days, %s to %s"
      % (len(names), len(px), px.index.min().date(), px.index.max().date()))
print("median round-trip spread %.4f%% of notional, median swap %.4f%%/night\n"
      % (100 * C.spread.median(), 100 * C[["swap_long", "swap_short"]].mean(axis=1).median()))

SPLIT = px.index[int(len(px) * 0.6)]
print("dev  : %s to %s" % (px.index.min().date(), SPLIT.date()))
print("hold : %s to %s\n" % (SPLIT.date(), px.index.max().date()))

P = px.to_numpy(float)
dates = px.index


def run(L, H, randomise=False, seed=None):
    """Non-overlapping long/short rebalances. Returns (dates, net returns)."""
    r = np.random.default_rng(seed) if randomise else None
    out_t, out_r = [], []
    i = L
    while i + H < len(P):
        past = P[i] / P[i - L] - 1.0
        fwd = P[i + H] / P[i] - 1.0
        if np.isnan(past).any() or np.isnan(fwd).any():
            i += H; continue
        order = r.permutation(len(names)) if randomise else np.argsort(past)
        lo, hi = order[:K], order[-K:]              # weakest, strongest
        # long the strongest, short the weakest - momentum. Reversal is the sign flip,
        # reported separately rather than as a second scan of the same data.
        gross = fwd[hi].mean() - fwd[lo].mean()
        c = (C.spread.to_numpy()[hi].mean() + C.spread.to_numpy()[lo].mean()
             + H * (C.swap_long.to_numpy()[hi].mean() + C.swap_short.to_numpy()[lo].mean()))
        out_t.append(dates[i]); out_r.append(gross - c)
        i += H                                       # NON-OVERLAPPING
    return np.array(out_t), np.array(out_r)


def stat(x):
    if len(x) < 8:
        return float("nan"), float("nan")
    return x.mean(), x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))


print("MOMENTUM  (long top %d, short bottom %d)   net of spread and swap" % (K, K))
print("%-6s %-6s %6s %11s %7s %11s %7s %9s   %s"
      % ("look", "hold", "n", "dev mean", "dev t", "hold mean", "hold t", "rand t", "verdict"))
print("-" * 92)
results = []
for L in LOOKBACKS:
    for H in HOLDS:
        t, r = run(L, H)
        if len(r) < 20:
            continue
        dev, hold = r[t < SPLIT], r[t >= SPLIT]
        dm, dt = stat(dev)
        hm, ht = stat(hold)
        # random control on the same grid
        rts = []
        for s in range(200):
            _, rr = run(L, H, randomise=True, seed=s)
            _, tt = stat(rr)
            if not math.isnan(tt):
                rts.append(tt)
        rand_hi = np.percentile(np.abs(rts), 95) if rts else float("nan")
        passes = (abs(dt) > 2) and (np.sign(hm) == np.sign(dm)) and (abs(ht) > 1.5)
        verdict = "SURVIVES" if passes else ("dev only" if abs(dt) > 2 else "-")
        results.append((L, H, dm, dt, hm, ht, rand_hi, passes))
        print("%-6d %-6d %6d %10.3f%% %7.2f %10.3f%% %7.2f %9.2f   %s"
              % (L, H, len(r), 100 * dm, dt, 100 * hm, ht, rand_hi, verdict))

print("\n'rand t' is the 95th percentile of |t| from 200 random rankings on the same grid.")
print("A real t below that is indistinguishable from ranking the names by coin flip.")

surv = [x for x in results if x[7]]
print("\n%d of %d cells survive dev AND holdout." % (len(surv), len(results)))
if surv:
    print("Surviving cells (these are the ONLY ones worth a second look):")
    for L, H, dm, dt, hm, ht, rh, _ in surv:
        print("   look %-4d hold %-4d   dev %+.3f%% (t %.2f)   holdout %+.3f%% (t %.2f)"
              % (L, H, 100 * dm, dt, 100 * hm, ht))
else:
    allr = np.concatenate([run(L, H)[1] for L in LOOKBACKS for H in HOLDS])
    sd = allr.std(ddof=1)
    n_typ = len(run(21, 10)[1])
    mde = 2.8 * sd / math.sqrt(n_typ)
    print("""Nothing survives. Before calling that a null, the size it could have missed:
  typical cell has %d non-overlapping rebalances, sd %.3f%% per rebalance
  smallest detectable effect ~ %.3f%% per rebalance
An edge below that is invisible here regardless of whether it exists.""" % (n_typ, 100 * sd, 100 * mde))
    print("\nREVERSAL is the same book with the sign flipped, so its t-stats are the")
    print("negatives of the momentum column above - it is already answered here.")
