"""Can $1,000 actually HOLD the diversified basket? Minimum lot sizes decide it.

portfolio_hold.py showed the mix works in percentage terms. Percentages are free; lots are
not. Every instrument has a minimum tradeable size, and the minimum notional that implies
(min_lot x contract_size x price) can be far larger than a small account.

This is the difference between a strategy that exists and one you can place. If the
minimum basket notional is $8,000, then holding it on $1,000 is not "the strategy at 1x" -
it is the strategy at 8x, which the leverage test showed gets liquidated.

So this computes, for each instrument, the smallest position that can be opened at all,
and then asks which SUBSET a given account can carry at a chosen leverage. The answer
determines whether the recommendation is "place these nine trades" or "this needs more
capital first".

Checked at $1,000, $5,000 and $10,000 so the capital threshold is visible rather than
asserted.
"""
import numpy as np, pandas as pd
import MetaTrader5 as mt5

SYMS = ["JP225m", "XAUUSDm", "US500m", "USTECm", "DE30m", "UK100m",
        "XAGUSDm", "USOILm", "BTCUSDm"]
ACCOUNTS = [1000, 5000, 10000]
TARGET_LEV = 1.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
rows = []
for s in SYMS:
    if not mt5.symbol_select(s, True):
        continue
    i = mt5.symbol_info(s)
    if i is None or i.ask <= 0:
        continue
    min_notional = i.volume_min * i.trade_contract_size * i.ask
    unit = i.point * i.trade_contract_size
    swap_yr = (abs(i.swap_long) * unit / (i.ask * i.trade_contract_size) * 365 * 100) \
        if i.swap_long < 0 else 0.0
    rows.append({"sym": s, "min_lot": i.volume_min, "step": i.volume_step,
                 "contract": i.trade_contract_size, "price": i.ask,
                 "min_notional": min_notional, "swap_yr": swap_yr})
mt5.shutdown()

df = pd.DataFrame(rows).sort_values("min_notional")
print("SMALLEST POSITION THAT CAN BE OPENED AT ALL")
print("%-10s %9s %10s %11s %14s %9s"
      % ("symbol", "min lot", "contract", "price", "min notional", "swap/yr"))
print("-" * 70)
for _, r in df.iterrows():
    print("%-10s %9.2f %10.0f %11.2f %14s %8.2f%%"
          % (r["sym"], r["min_lot"], r["contract"], r["price"],
             "$%,.0f" % r["min_notional"] if False else "${:,.0f}".format(r["min_notional"]),
             r["swap_yr"]))

total = df.min_notional.sum()
print("\nFULL 9-INSTRUMENT BASKET at minimum size: ${:,.0f} of notional".format(total))
print("To hold that at 1x you need ${:,.0f} of equity.".format(total))

print("\nWHAT EACH ACCOUNT SIZE CAN ACTUALLY CARRY (at %.1fx)" % TARGET_LEV)
print("%-10s %8s %-52s %s" % ("account", "names", "instruments", "forced leverage"))
print("-" * 92)
for acct in ACCOUNTS:
    budget = acct * TARGET_LEV
    # cheapest-first, since that maximises the number of names a small account can hold
    picked, spent = [], 0.0
    for _, r in df.iterrows():
        if spent + r["min_notional"] <= budget:
            picked.append(r["sym"]); spent += r["min_notional"]
    lev_if_all = total / acct
    print("%-10s %8d %-52s %.1fx if you forced all 9"
          % ("${:,}".format(acct), len(picked),
             ", ".join(s.replace("m", "") for s in picked) or "NONE",
             lev_if_all))

print("""
HOW TO READ THIS
The 'names' column is how many instruments the account can hold at the intended leverage.
Diversification is the entire benefit here, and it needs enough names to work - two or
three correlated indices is not a diversified book, it is one bet in three pieces.

If an account can only carry a couple of names, the honest answer is not to run a
degraded version of the strategy. It is that the strategy needs more capital, and until
then the money is better left accumulating than deployed into something that keeps the
drawdown of the real thing while losing the diversification that justified it.""")

feasible = df[df.min_notional <= 1000]
print("\nOn $1,000 at 1x, the instruments that fit at all: %s"
      % (", ".join(feasible.sym.tolist()) if len(feasible) else "NONE"))
if len(feasible):
    print("Combined minimum notional of those: ${:,.0f}".format(feasible.min_notional.sum()))
