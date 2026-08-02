"""Can you actually make money on this account by HOLDING? Test it properly.

Every systematic test in this project has failed for the same reason - the universe is too
small and too correlated to resolve any realistic edge. But that is a statement about
MEASURING edges, not about whether anybody profits here. Regulators put the retail loss
rate at 70-85%, so 15-30% of accounts do make money, and the question worth answering is
what those accounts are plausibly doing.

The most plausible answer is the least clever one: holding something that went up. The
holding-cost census showed financing is 0-7%/yr on this account, which is affordable
against assets that returned 15-40%/yr. Arithmetically that works.

So this tests it honestly, which means testing the part that kills people: DRAWDOWN AND
MARGIN. A strategy that returns 23%/yr and gets margin-called in March 2020 returns
nothing - the account is closed before the recovery. Reporting CAGR without the equity
path is how leveraged buy-and-hold gets sold to people who then lose everything.

WHAT IS MODELLED
  * daily equity path, marked to market, financing charged every night on the notional
  * a MARGIN CALL when equity falls below the maintenance requirement, at which point the
    position is closed and the run is over - no recovery, because there is no account left
  * leverage from 1x to 5x on the same asset, so the trade-off is visible rather than
    argued

Exness margin requirements vary by instrument and tier; 1% maintenance (100:1) is assumed,
which is generous. A stricter requirement makes the high-leverage rows fail sooner, never
later, so the conclusions below are the optimistic case.
"""
import numpy as np, pandas as pd
import MetaTrader5 as mt5

SYMS = ["JP225m", "XAUUSDm", "US500m", "USTECm", "DE30m", "BTCUSDm", "XAGUSDm"]
LEVERAGES = [1, 2, 3, 5]
MAINT = 0.01                       # maintenance margin as a share of notional

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
data = {}
for s in SYMS:
    if not mt5.symbol_select(s, True):
        continue
    i = mt5.symbol_info(s)
    r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 5000)
    if i is None or r is None or len(r) < 400:
        continue
    d = pd.DataFrame(r)
    d["t"] = pd.to_datetime(d["time"], unit="s")
    unit = i.point * i.trade_contract_size
    notional = i.ask * i.trade_contract_size
    data[s] = {
        "px": d.set_index("t")["close"].astype(float),
        "swap_day": (abs(i.swap_long) * unit / notional) if i.swap_long < 0 else 0.0,
        "spread": (i.ask - i.bid) / i.ask,
    }
mt5.shutdown()


def simulate(px, swap_day, spread, lev):
    """Equity path for a leveraged long BOUGHT ONCE and held. Returns (cagr, maxdd, blown).

    FIXED NOTIONAL, which is what buy-and-hold actually is: you open a position of size
    lev x E0 and leave it. The position is not rebalanced daily, so a rise builds a buffer
    that a later fall has to eat through before margin becomes an issue.

    A first version compounded lev x daily return and declared the account blown at an
    EQUITY drawdown of 1/lev. That is about twice as harsh as reality - at 2x, wiping the
    equity needs the ASSET to halve, not to fall 25% - and it reported every instrument
    blown at 2x, which was simply wrong. Liquidation is now the real condition: equity
    below the maintenance requirement on the notional being carried.
    """
    p = px.to_numpy(float)
    n_units = lev / p[0]                          # notional lev x E0, E0 = 1
    fin = 0.0
    eq_path = []
    for k in range(1, len(p)):
        fin += swap_day * lev                     # financing on the fixed notional
        eq = 1.0 - spread * lev + n_units * (p[k] - p[0]) - fin
        eq_path.append(eq)
        if eq <= MAINT * lev:                     # margin call - position closed, over
            return None, 1.0, True
    eq_path = np.array(eq_path)
    peak = np.maximum.accumulate(np.maximum(eq_path, 1e-9))
    maxdd = float(np.max(1.0 - eq_path / peak))
    yrs = (px.index[-1] - px.index[0]).days / 365.25
    final = eq_path[-1]
    return (final ** (1 / yrs) - 1) if final > 0 else None, maxdd, final <= 0


print("LEVERAGED BUY-AND-HOLD, net of spread and nightly financing")
print("'blown' = equity wiped out before the end. There is no recovery from that.\n")
print("%-9s %6s %8s %10s %10s %10s %10s"
      % ("symbol", "yrs", "swap/yr", "1x", "2x", "3x", "5x"))
print("-" * 70)
for s, d in data.items():
    yrs = (d["px"].index[-1] - d["px"].index[0]).days / 365.25
    cells = []
    for lev in LEVERAGES:
        cagr, dd, blown = simulate(d["px"], d["swap_day"], d["spread"], lev)
        cells.append("BLOWN" if blown else "%+.1f%%" % (100 * cagr))
    print("%-9s %6.1f %7.2f%% %10s %10s %10s %10s"
          % (s, yrs, 100 * 365 * d["swap_day"], *cells))

print("\nMAXIMUM DRAWDOWN ALONG THE WAY (the number that decides whether you hold on)")
print("%-9s %10s %10s %10s %10s" % ("symbol", "1x", "2x", "3x", "5x"))
print("-" * 54)
for s, d in data.items():
    cells = []
    for lev in LEVERAGES:
        cagr, dd, blown = simulate(d["px"], d["swap_day"], d["spread"], lev)
        cells.append("BLOWN" if blown else "-%.0f%%" % (100 * dd))
    print("%-9s %10s %10s %10s %10s" % (s, *cells))

print("""
HOW TO READ THIS
The 1x column is the honest one: it is what owning the asset would have done, minus
financing you would not pay if you simply owned it. Every column to the right is the same
bet with a shorter fuse - the returns scale linearly, the drawdowns scale linearly, and
survival does not scale at all, it just ends.

If a row blows up at 3x or 5x, that is the mechanism behind the 70-85% retail loss rate.
It is not that those traders picked the wrong asset. They picked a reasonable asset and
sized it so that an ordinary drawdown closed the account before the recovery arrived.""")
