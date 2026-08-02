"""Does carry actually pay? Deribit BTC and ETH perps, 7.3 years, hourly.

Carry is the first idea tested here that does not try to predict anything. A perpetual
swap pays funding between longs and shorts every hour on Deribit. When funding is
positive, shorts get paid simply for being short. That payment exists whether the price
moves or not, which is what makes it a different KIND of edge from the twenty timing
ideas that failed.

THREE VERSIONS ARE TESTED, and the difference between them is the entire point.

  1. FUNDING ALONE. What the yield looks like if you quote it the way it is usually
     quoted - annualised, price ignored. This is the number that makes carry look free.

  2. NAKED SHORT. Collect funding, but take the price move too. This is what you would
     actually get on a broker with no spot leg, which includes Exness.

  3. DELTA-NEUTRAL (cash and carry). Short the perp, hold the coin. The price legs
     cancel, leaving the funding. This is the real trade institutions run, and it needs
     a venue where you can hold spot - which Exness is not.

Whether the gap between 1 and 2 is large is the whole question. A carry yield that is
entirely given back in price is not income, it is a disguised short position.

Costs: Deribit-style taker 0.05% each way, charged once per position, plus for the
delta-neutral version a second 0.05% each way on the spot leg. Held positions pay no
further spread, which is what makes carry attractive relative to the short-horizon ideas
that paid it on every trade.
"""
import math
import numpy as np, pandas as pd

FEE_ONE_WAY = 0.0005
HOURS_YEAR = 24 * 365.25


def load(path):
    d = pd.read_csv(path)
    d["t"] = pd.to_datetime(d["utc"])
    d = d.dropna(subset=["interest_1h", "close"]).sort_values("t").reset_index(drop=True)
    return d


for name, path in (("BTC", r"C:\Projects\KinoliveLines\recorder\data\hist_BTC_PERPETUAL.csv"),
                   ("ETH", r"C:\Projects\KinoliveLines\recorder\data\hist_ETH_PERPETUAL.csv")):
    d = load(path)
    f = d["interest_1h"].to_numpy(float)         # funding paid by longs to shorts, hourly
    px = d["close"].to_numpy(float)
    yrs = (d.t.iloc[-1] - d.t.iloc[0]).days / 365.25

    print("=" * 78)
    print("%s   %s to %s   %.2f years, %d hourly rows"
          % (name, d.t.iloc[0].date(), d.t.iloc[-1].date(), yrs, len(d)))

    # ---- 1. funding alone ---------------------------------------------------------
    short_funding = f.sum()                      # a short RECEIVES positive funding
    print("\n1. FUNDING ALONE (the number usually quoted)")
    print("   total funding to a short over the period : %+.1f%%" % (100 * short_funding))
    print("   annualised                               : %+.2f%%/yr" % (100 * short_funding / yrs))
    print("   share of hours funding was positive      : %.1f%%" % (100 * (f > 0).mean()))

    # ---- 2. naked short -----------------------------------------------------------
    price_ret = px[-1] / px[0] - 1.0
    naked = short_funding - price_ret - 2 * FEE_ONE_WAY
    print("\n2. NAKED SHORT (funding AND the price move - what a broker with no spot gives)")
    print("   price went                               : %+.1f%%" % (100 * price_ret))
    print("   short's price P&L                        : %+.1f%%" % (-100 * price_ret))
    print("   funding collected                        : %+.1f%%" % (100 * short_funding))
    print("   NET                                      : %+.1f%%  (%+.2f%%/yr)"
          % (100 * naked, 100 * naked / yrs))

    # ---- 3. delta neutral ---------------------------------------------------------
    neutral = short_funding - 4 * FEE_ONE_WAY    # two legs, in and out
    print("\n3. DELTA NEUTRAL (short perp + hold spot - the real carry trade)")
    print("   NET                                      : %+.1f%%  (%+.2f%%/yr)"
          % (100 * neutral, 100 * neutral / yrs))

    # ---- is it stable, or one lucky era? ------------------------------------------
    d["yr"] = d.t.dt.year
    print("\n   funding to a short, by calendar year:")
    line = "   "
    for y, g in d.groupby("yr"):
        ann = g["interest_1h"].sum() / (len(g) / HOURS_YEAR)
        line += "%d %+.1f%%  " % (y, 100 * ann)
    print(line)
    yearly = d.groupby("yr")["interest_1h"].apply(lambda g: g.sum() / (len(g) / HOURS_YEAR))
    pos_years = (yearly > 0).sum()
    print("   positive in %d of %d years" % (pos_years, len(yearly)))

    # Non-overlapping 30-day blocks, so the error bar is not inflated by autocorrelation.
    block = 24 * 30
    blocks = np.array([f[i:i + block].sum() for i in range(0, len(f) - block, block)])
    m = blocks.mean()
    se2 = 2 * blocks.std(ddof=1) / math.sqrt(len(blocks))
    print("\n   %d non-overlapping 30-day blocks: mean %+.3f%% +/- %.3f%% (2SE)"
          % (len(blocks), 100 * m, 100 * se2))
    print("   %s" % ("funding income is reliably positive"
                     if m - se2 > 0 else "not distinguishable from zero"))

print("""
=============================================================================
WHAT TO TAKE FROM THIS
Compare line 1 against line 2 for each coin. If the annualised funding looks generous but
the naked short is negative, the yield was never income - it was payment for standing in
front of a rising market, and the market collected it back.

Line 3 is the only version that keeps the funding without the price risk, and it needs a
venue where spot and perp sit in one account. Exness has no spot leg, so line 3 is not
available there at any size. That is a venue fact, not a strategy choice.""")
