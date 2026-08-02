"""How reliable is that 15%/yr basket figure? Rolling windows, not a single headline.

A single CAGR over one window is the most misleading number in finance. It tells you what
happened once, in one period, and says nothing about the range of outcomes. The basket
result in portfolio_hold.py was exactly that: one number over 2019-2026, with no
out-of-sample split and no control - unlike every systematic test in this project, which
had both.

That difference matters and was not made clear enough when the figure was first reported.
A hold portfolio has no fitted signal, so it does not overfit the way a trading rule does,
but the RETURN ESTIMATE is still entirely a property of the period observed. This shows
the distribution instead of the headline:

  * rolling 1-year and 3-year returns, so the worst stretch is visible
  * the share of windows that lost money
  * the deepest drawdown and how long it took to recover
  * the same for the pre-2022 and post-2022 halves, which is the closest thing to an
    out-of-sample split available in 7 years of data

The reference case worth remembering while reading it: the Nikkei peaked in 1989 and did
not recover for THIRTY-FOUR years. JP225 is the top-ranked instrument in this study. A
backtest starting in 2019 cannot see that, and no amount of statistics on this window
will reveal it.
"""
import numpy as np, pandas as pd
import MetaTrader5 as mt5

SYMS = ["JP225m", "XAUUSDm", "US500m", "USTECm", "DE30m", "UK100m",
        "XAGUSDm", "USOILm", "BTCUSDm"]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
px, swap, spr = {}, {}, {}
for s in SYMS:
    if not mt5.symbol_select(s, True):
        continue
    i = mt5.symbol_info(s)
    r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 5000)
    if i is None or r is None or len(r) < 500 or i.ask <= 0:
        continue
    d = pd.DataFrame(r)
    d["t"] = pd.to_datetime(d["time"], unit="s").dt.normalize()
    px[s] = d.set_index("t")["close"].astype(float)
    unit = i.point * i.trade_contract_size
    swap[s] = (abs(i.swap_long) * unit / (i.ask * i.trade_contract_size)) if i.swap_long < 0 else 0.0
mt5.shutdown()

P = pd.DataFrame(px).sort_index().dropna()
R = P.pct_change().fillna(0.0)
w = np.ones(P.shape[1]) / P.shape[1]
daily_swap = float((pd.Series(swap).reindex(P.columns).to_numpy() * w).sum())
gross = (R.to_numpy() * w).sum(axis=1) - daily_swap          # equal weight, 1x, net
eq = pd.Series(np.cumprod(1.0 + gross), index=P.index)

print("EQUAL-WEIGHT BASKET, 1x, net of financing")
print("%s to %s\n" % (P.index.min().date(), P.index.max().date()))

for win, label in ((252, "1 year"), (756, "3 years")):
    if len(eq) <= win:
        continue
    roll = (eq.shift(-win) / eq - 1.0).dropna()
    ann = (1 + roll) ** (252 / win) - 1
    print("ROLLING %s RETURNS (%d overlapping windows)" % (label.upper(), len(roll)))
    print("   best   %+7.1f%%      median %+7.1f%%      worst %+7.1f%%"
          % (100 * ann.max(), 100 * ann.median(), 100 * ann.min()))
    print("   windows that LOST money: %.0f%%\n" % (100 * (roll < 0).mean()))

peak = eq.cummax()
dd = 1 - eq / peak
worst_i = dd.idxmax()
print("DEEPEST DRAWDOWN: %.0f%% on %s" % (100 * dd.max(), worst_i.date()))
recovered = eq[eq.index > worst_i]
back = recovered[recovered >= peak.loc[worst_i]]
if len(back):
    print("   recovered on %s - %d days underwater"
          % (back.index[0].date(), (back.index[0] - worst_i).days))
else:
    print("   NEVER recovered within the sample")
under = (dd > 0.05).mean()
print("   %.0f%% of all days were more than 5%% below a prior peak" % (100 * under))

half = P.index[len(P) // 2]
print("\nCLOSEST THING TO OUT-OF-SAMPLE (split at %s)" % half.date())
for lab, mask in (("first half ", P.index <= half), ("second half", P.index > half)):
    g = gross[mask]
    yrs = mask.sum() / 252
    c = np.prod(1 + g) ** (1 / yrs) - 1
    e = np.cumprod(1 + g)
    d2 = float(np.max(1 - e / np.maximum.accumulate(e)))
    print("   %s  %+6.1f%%/yr   max DD %3.0f%%" % (lab, 100 * c, 100 * d2))

print("""
WHAT THIS DOES AND DOES NOT ESTABLISH
It establishes that a diversified basket had a better return-per-unit-of-drawdown than any
single instrument in this window. That part is arithmetic and it is robust - it follows
from correlations below 1, not from the period.

It does NOT establish the return. That number is a property of 2019-2026 and nothing else.
The Nikkei took thirty-four years to regain its 1989 peak; the S&P took twenty-five to
regain 1929 in real terms. Windows like that exist and this sample contains none of them.

Nothing here is guaranteed. A hold portfolio is a bet that risk assets rise over the
holding period. It is a reasonable bet with a long history behind it, and it can still
lose money for a decade.""")
