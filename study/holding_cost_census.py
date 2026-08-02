"""Who actually makes money at a CFD broker? Measure the cost of HOLDING, not trading.

The whole project so far attacked short horizons, where a $10 spread is a huge share of a
$188 half-hour range. At a daily or weekly horizon the spread stops mattering - it is
0.3-0.6% of a daily range on the good instruments. So the obvious question is whether the
profitable minority of retail accounts are simply people HOLDING things that went up,
rather than trading anything.

That reframes the problem completely. At long horizons the enemy is no longer the spread.
It is SWAP - the overnight financing charged on every leveraged position, every night,
forever. A 10%/yr swap silently eats the entire equity risk premium; a 0%/yr swap leaves
buy-and-hold intact.

This measures it directly for the instruments on the account, and pairs it against what
each instrument actually did, so the comparison is concrete rather than theoretical:

    swap cost per year   vs   the asset's own annualised return

If financing exceeds the return, holding is a losing proposition no matter how right the
directional call is, and the profitable accounts must be doing something else. If
financing is small, then buy-and-hold is available here and the last twenty tests were
simply aimed at the wrong horizon.

Swap is quoted per LOT per night. Contract size differs wildly across instruments, so
everything is converted to a percentage of NOTIONAL - the only unit that compares a
$63,000 bitcoin CFD against a $2,700 gold CFD. Getting this wrong by the contract-size
factor already produced one wrong answer earlier today.
"""
import pandas as pd
import MetaTrader5 as mt5

WATCH = ["BTCUSDm", "ETHUSDm", "XAUUSDm", "XAGUSDm", "USOILm", "US500m", "USTECm",
         "US30m", "DE30m", "JP225m", "UK100m", "EURUSDm", "GBPUSDm", "USDJPYm",
         "AAPLm", "MSFTm", "NVDAm", "AMZNm", "TSLAm"]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
rows = []
for s in WATCH:
    if not mt5.symbol_select(s, True):
        continue
    i = mt5.symbol_info(s)
    d = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 1300)
    if i is None or d is None or len(d) < 250 or i.ask <= 0:
        continue
    d = pd.DataFrame(d)
    d["t"] = pd.to_datetime(d["time"], unit="s")
    # UNITS. Every instrument on this account reports swap_mode 1 = POINTS, so the raw
    # swap figure is NOT currency. One point is worth (point * contract_size) in the quote
    # currency, so a night costs swap * point * contract_size.
    #
    # This is easy to get wrong and I got it wrong first: for the stock CFDs
    # point * contract = 0.01 * 100 = 1, so the raw number happens to equal dollars, and
    # assuming that holds everywhere reported BTC swap as 722%/yr instead of 7.2%. Third
    # units error of the day - always read swap_mode and convert explicitly.
    per_night = lambda sw: abs(sw) * i.point * i.trade_contract_size
    notional = i.ask * i.trade_contract_size
    yrs = (d.t.iloc[-1] - d.t.iloc[0]).days / 365.25
    total = d.close.iloc[-1] / d.close.iloc[0] - 1
    sgn = lambda sw: (1 if sw < 0 else -1)          # negative swap = a charge you pay
    rows.append({
        "sym": s,
        "yrs": yrs,
        # 365 nights. Most instruments triple-charge one night a week, so this is a FLOOR
        # on the true cost, not a worst case.
        "swap_long_yr": sgn(i.swap_long) * 100 * 365 * per_night(i.swap_long) / notional,
        "swap_short_yr": sgn(i.swap_short) * 100 * 365 * per_night(i.swap_short) / notional,
        "asset_yr": 100 * ((1 + total) ** (1 / yrs) - 1),
        "spread_pct": 100 * (i.ask - i.bid) / i.ask,
    })
mt5.shutdown()

df = pd.DataFrame(rows)
print("COST OF HOLDING, PER YEAR, AS A %% OF NOTIONAL")
print("Positive swap = you PAY. Negative = you are PAID.\n")
print("%-9s %6s %10s %11s %11s %12s   %s"
      % ("symbol", "yrs", "spread", "swap LONG", "swap SHORT", "asset/yr", "long net"))
print("-" * 84)
for _, r in df.sort_values("swap_long_yr").iterrows():
    net = r["asset_yr"] - r["swap_long_yr"]
    print("%-9s %6.1f %9.3f%% %10.2f%% %10.2f%% %11.1f%% %+11.1f%%"
          % (r["sym"], r["yrs"], r["spread_pct"], r["swap_long_yr"],
             r["swap_short_yr"], r["asset_yr"], net))

print("""
'long net' is what a leveraged BUY-AND-HOLD would have earned per year after financing,
assuming the asset repeats its own history - which it will not, but it sets the scale.

READ THE SWAP COLUMN FIRST. Financing is charged whether you are right or wrong and
compounds every single night. An instrument whose swap exceeds its own historical return
cannot be held profitably at all, however good the entry.""")

worst = df.loc[df.swap_long_yr.idxmax()]
best = df.loc[df.swap_long_yr.idxmin()]
print("cheapest to hold long : %-9s %.2f%%/yr" % (best["sym"], best["swap_long_yr"]))
print("dearest to hold long  : %-9s %.2f%%/yr" % (worst["sym"], worst["swap_long_yr"]))
paid = df[(df.swap_long_yr < 0) | (df.swap_short_yr < 0)]
if len(paid):
    print("\nInstruments where one side is PAID to hold (negative swap):")
    for _, r in paid.iterrows():
        side = "LONG" if r["swap_long_yr"] < 0 else "SHORT"
        print("   %-9s %s  %+.2f%%/yr" % (r["sym"], side,
                                          -min(r["swap_long_yr"], r["swap_short_yr"])))
