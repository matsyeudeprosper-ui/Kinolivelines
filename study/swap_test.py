"""Swap / overnight-financing census on the 19 tradeable US stock CFDs.

Cross-sectional equity holds for days to weeks and runs long AND short, so
the binding cost is nightly financing on BOTH legs, not the spread. This
measures it and converts everything to one comparable number: annual % of
notional for a market-neutral pair.

Also reports:
  * breakeven holding period - the number of nights at which accumulated
    swap equals the round-trip spread. Below it spread dominates; above it
    financing does.
  * D1 history depth, since a cross-sectional backtest needs years.
  * the 3-day rollover weekday (triple swap).

Market Watch is restored on exit.
"""
import MetaTrader5 as mt5, pandas as pd, numpy as np, os

STOCKS = ["TSLAm","AMZNm","INTCm","TSMm","ORCLm","AVGOm","AAPLm","MSm","ADBEm",
          "NVDAm","CSCOm","INTUm","HDm","IBMm","AMDm","GOOGLm","PEPm","MCDm","MSFTm"]
OUT = os.path.dirname(os.path.abspath(__file__))

SWAP_MODE = {0:"DISABLED", 1:"POINTS", 2:"CCY_SYMBOL", 3:"CCY_MARGIN", 4:"CCY_DEPOSIT",
             5:"INTEREST_CURRENT", 6:"INTEREST_OPEN", 7:"REOPEN_CURRENT", 8:"REOPEN_BID"}
DAYS = {0:"Sun",1:"Mon",2:"Tue",3:"Wed",4:"Thu",5:"Fri",6:"Sat"}

if not mt5.initialize():
    raise SystemExit(mt5.last_error())
original = {s.name for s in mt5.symbols_get() if s.visible}

rows = []
for name in STOCKS:
    if not mt5.symbol_select(name, True):
        print(f"{name}: cannot select"); continue
    si = mt5.symbol_info(name)
    if si is None: continue
    tick = mt5.symbol_info_tick(name)
    price = tick.bid if tick and tick.bid > 0 else si.bid
    if price <= 0:
        d = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_D1, 0, 1)
        price = d[0]['close'] if d is not None and len(d) else np.nan

    mode = si.swap_mode
    sl, ss = si.swap_long, si.swap_short
    notional = si.trade_contract_size * price          # per 1.0 lot

    # nightly cost as % of notional, per leg (negative = you pay)
    if mode == 1:                                       # points
        long_pct  = sl * si.point / price * 100.0
        short_pct = ss * si.point / price * 100.0
    elif mode in (2, 3, 4):                             # money per lot per night
        long_pct  = sl / notional * 100.0 if notional else np.nan
        short_pct = ss / notional * 100.0 if notional else np.nan
    elif mode in (5, 6):                                # annual interest %
        long_pct  = sl / 360.0
        short_pct = ss / 360.0
    else:
        long_pct = short_pct = np.nan

    # market-neutral pair: one long + one short, both charged every night
    pair_night = long_pct + short_pct
    pair_annual = pair_night * 365.0

    dd = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_D1, 0, 5000)
    if dd is not None and len(dd):
        t = pd.to_datetime(pd.DataFrame(dd)['time'], unit='s')
        hist_days, first = (t.iloc[-1]-t.iloc[0]).days, t.iloc[0].date()
        nbars = len(dd)
    else:
        hist_days, first, nbars = 0, None, 0

    # spread as % of notional, round trip
    h1 = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_H1, 0, 300)
    spread_pct = np.nan
    if h1 is not None and len(h1):
        spread_pct = np.median(pd.DataFrame(h1)['spread'].values) * si.point / price * 100.0

    breakeven = abs(spread_pct / pair_night) if pair_night and pair_night < 0 else np.nan

    rows.append({'symbol':name,'price':price,'mode':SWAP_MODE.get(mode,mode),
                 'swap_long_raw':sl,'swap_short_raw':ss,
                 'long_%/night':long_pct,'short_%/night':short_pct,
                 'pair_%/night':pair_night,'pair_%/year':pair_annual,
                 'spread_%':spread_pct,'breakeven_nights':breakeven,
                 'rollover':DAYS.get(si.swap_rollover3days,'?'),
                 'd1_bars':nbars,'hist_days':hist_days,'first_bar':first})

for s in mt5.symbols_get():
    if s.name not in original:
        mt5.symbol_select(s.name, False)
mt5.shutdown()

df = pd.DataFrame(rows)
df.to_csv(os.path.join(OUT,"swap_census.csv"), index=False)
pd.set_option('display.width', 250)

print("="*128)
print("SWAP / OVERNIGHT FINANCING - 19 tradeable US stock CFDs")
print("="*128)
print(df[['symbol','mode','swap_long_raw','swap_short_raw','long_%/night','short_%/night',
          'pair_%/night','pair_%/year','rollover']]
      .to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

print("\n" + "="*128)
print("COST STRUCTURE - spread vs financing")
print("="*128)
print(df[['symbol','spread_%','pair_%/night','breakeven_nights','d1_bars','hist_days','first_bar']]
      .to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

print("\n" + "="*128)
print("VERDICT INPUTS")
print("="*128)
pa = df['pair_%/year'].dropna()
if len(pa):
    print(f"  market-neutral pair financing, median : {pa.median():>10.2f} % / year")
    print(f"                                  worst : {pa.min():>10.2f} % / year")
    print(f"                                   best : {pa.max():>10.2f} % / year")
    print(f"  median breakeven holding period       : {df['breakeven_nights'].median():>10.1f} nights")
    print(f"  median round-trip spread              : {df['spread_%'].median():>10.4f} % of notional")
    print(f"  median D1 history                     : {df['hist_days'].median():>10.0f} days")
print("\n  A simple cross-sectional equity strategy on ~19 names grosses maybe")
print("  5-15%/year. If |pair financing| eats most of that, the door is shut.")
print(f"\n  full table -> {os.path.join(OUT,'swap_census.csv')}")
