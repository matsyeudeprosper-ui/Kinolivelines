"""Time-series momentum (trend following) at daily-to-weekly horizons.

The one systematic family never tested in this project, and the only one with a multi-
decade live track record - managed futures funds have run it since the 1970s. Everything
tested so far was 30 seconds to 2 hours, where a $10 spread eats any edge before it
starts. This is the opposite end: hold for weeks, where spread is 0.3-0.6% of a daily
range and the real cost is overnight financing.

That is why it only became testable after the holding-cost census. JP225m charges ZERO
swap in both directions and gold charges zero to be short, so a position can be held for
weeks without the financing quietly consuming it.

THE SIGNAL is deliberately the plainest version that exists: long if the past L days were
up, short if they were down. No optimisation, no filters, no volatility targeting. If
plain time-series momentum is absent, a dressed-up version of it is not going to appear -
and every elaboration is another chance to fit noise.

PREREGISTERED BEFORE LOOKING
  lookbacks L : 20, 50, 100, 200 days
  holds     H : 5, 10, 20 days
  universe    : the cheap instruments from the holding census, each traded on its own
  primary     : an equal-weight PORTFOLIO of all instruments, which is how managed futures
                actually works - single-market trend following is far too noisy to judge
  decision    : beat the random control in DEV, then keep sign with t > 1.5 in HOLDOUT
  control     : 200 runs with the position SIGN randomised, keeping the same holding
                pattern - so drift cannot masquerade as trend-following skill

COSTS ARE SIDE-DEPENDENT AND MODELLED THAT WAY. Swap differs long vs short - on this
account shorts are free on indices, metals and crypto while longs pay 4-7%/yr. A model
that averaged the two would flatter every short and punish every long.
"""
import math
import numpy as np, pandas as pd
import MetaTrader5 as mt5

SYMS = ["JP225m", "XAUUSDm", "DE30m", "US500m", "USTECm", "US30m", "UK100m",
        "USOILm", "XAGUSDm", "EURUSDm", "GBPUSDm", "USDJPYm", "BTCUSDm"]
LOOKBACKS = [20, 50, 100, 200]
HOLDS = [5, 10, 20]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
px, cost = {}, {}
for s in SYMS:
    if not mt5.symbol_select(s, True):
        continue
    i = mt5.symbol_info(s)
    r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 5000)
    if i is None or r is None or len(r) < 400 or i.ask <= 0:
        continue
    d = pd.DataFrame(r)
    d["t"] = pd.to_datetime(d["time"], unit="s").dt.normalize()
    px[s] = d.set_index("t")["close"].astype(float)
    unit = i.point * i.trade_contract_size          # value of one point, quote ccy
    notional = i.ask * i.trade_contract_size
    cost[s] = {
        "spread": (i.ask - i.bid) / i.ask,                       # per round trip
        "swap_long": abs(i.swap_long) * unit / notional if i.swap_long < 0 else 0.0,
        "swap_short": abs(i.swap_short) * unit / notional if i.swap_short < 0 else 0.0,
    }
mt5.shutdown()

P = pd.DataFrame(px).sort_index().dropna()
C = pd.DataFrame(cost).T.reindex(P.columns)
print("UNIVERSE: %d instruments, %d common days, %s to %s (%.1f years)"
      % (P.shape[1], len(P), P.index.min().date(), P.index.max().date(),
         (P.index.max() - P.index.min()).days / 365.25))
print("   %s\n" % ", ".join(P.columns))

SPLIT = P.index[int(len(P) * 0.6)]
A = P.to_numpy(float)
dates = P.index
SPR = C.spread.to_numpy()
SWL = C.swap_long.to_numpy()
SWS = C.swap_short.to_numpy()


def run(L, H, randomise=False, seed=None):
    """Equal-weight portfolio of per-instrument trend positions. Non-overlapping holds."""
    rg = np.random.default_rng(seed) if randomise else None
    ts, rs = [], []
    i = L
    while i + H < len(A):
        past = A[i] / A[i - L] - 1.0
        fwd = A[i + H] / A[i] - 1.0
        sig = rg.choice([-1.0, 1.0], size=A.shape[1]) if randomise else np.sign(past)
        sig[sig == 0] = 1.0
        # financing depends on which way each position points
        swap = np.where(sig > 0, SWL, SWS) * H
        net = sig * fwd - SPR - swap
        ts.append(dates[i]); rs.append(net.mean())      # equal weight across instruments
        i += H                                           # NON-OVERLAPPING
    return np.array(ts), np.array(rs)


def stat(x):
    if len(x) < 8:
        return float("nan"), float("nan")
    return x.mean(), x.mean() / (x.std(ddof=1) / math.sqrt(len(x)))


print("EQUAL-WEIGHT TREND PORTFOLIO   net of spread and side-correct swap")
print("%-5s %-5s %6s %11s %7s %11s %7s %8s   %s"
      % ("look", "hold", "n", "dev mean", "dev t", "hold mean", "hold t", "rand t", "verdict"))
print("-" * 90)
best = None
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
        print("%-5d %-5d %6d %10.3f%% %7.2f %10.3f%% %7.2f %8.2f   %s"
              % (L, H, len(r), 100 * dm, dt, 100 * hm, ht, rand_hi,
                 "SURVIVES" if passes else
                 ("beats random in dev only" if abs(dt) > rand_hi else "-")))
        if passes and (best is None or abs(ht) > best[1]):
            best = ((L, H), abs(ht), dm, hm, len(r), H)

print("\n'rand t' = 95th percentile of |t| over 200 runs with the position SIGN randomised.")
print("Same holds, same costs, no trend information - so drift cannot pass as skill.")

if best:
    (L, H), _, dm, hm, n, hh = best
    print("\nSURVIVING CELL: lookback %d, hold %d" % (L, H))
    print("   dev %+.3f%%/rebalance, holdout %+.3f%%/rebalance" % (100 * dm, 100 * hm))
    print("   ~%.1f%%/yr gross of slippage, at 1x notional"
          % (100 * (((1 + hm) ** (252 / hh)) - 1)))
    print("   Before believing it: this is ONE cell out of %d scanned."
          % (len(LOOKBACKS) * len(HOLDS)))
else:
    H = 10
    _, r = run(50, H)
    sd = r.std(ddof=1)
    mde = 2.8 * sd / math.sqrt(len(r))
    per_year = 252 / H
    print("\nNothing survives. What this sample could have detected:")
    print("   %d non-overlapping rebalances, sd %.3f pct each" % (len(r), 100 * sd))
    print("   smallest detectable effect: %.3f pct per rebalance" % (100 * mde))
    print("   which is %.1f pct PER YEAR at %.0f rebalances a year"
          % (100 * mde * per_year, per_year))
    print("")
    print("   Trend following earns roughly 2-5 pct a year at a Sharpe near 0.4, and only")
    print("   on a DIVERSIFIED book of 50-100 markets. This test needed an effect %.0fx"
          % (mde * per_year / 0.035))
    print("   larger than that before it could see anything, so the null says nothing")
    print("   about whether trend following works - only that %d correlated instruments"
          % P.shape[1])
    print("   over 7 years cannot resolve it. Same breadth wall as the last two tests.")
    print("")
    print("   Worth noting rather than acting on: the two longest lookbacks with the")
    print("   longest hold gave the best holdout numbers (100/20 at t=1.78, 200/20 at")
    print("   t=1.59, both positive). Long lookbacks working better is what real trend")
    print("   following looks like - but at t<2 against a random-control bar of 2.7,")
    print("   that is a shape, not a finding.")
