"""Does overnight financing kill the US-stock cross-sectional idea before it starts?

The cost census of 2026-07-30 found 19 economically tradeable US stock CFDs on this
account and called them "the only genuine cross-sectional universe here". It also flagged,
in capitals, that only SPREAD had been measured and that swap was unmeasured and possibly
decisive - because a cross-sectional book holds positions for days or weeks, where nightly
financing on BOTH legs dominates a one-off spread entirely.

That is the number this measures, and it decides whether the one remaining untried family
is viable at all. It is worth doing before any strategy work, for the same reason the
BTC/ETH pair idea was killed in ten minutes by a feasibility test rather than after a
session of EA writing.

Swap is quoted per lot per night. What matters is swap as a fraction of the daily move,
because that is what it competes with:

    daily drag = |swap long| + |swap short|      (a market-neutral book pays both legs)
    the bar    = the stock's average daily range

If financing eats a large share of the daily range, no cross-sectional signal at a
multi-day horizon survives it, and this branch closes without writing a strategy.
"""
import pandas as pd
import MetaTrader5 as mt5

STOCKS = ["TSLA", "AMZN", "INTC", "TSM", "ORCL", "AVGO", "AAPL", "MS", "ADBE", "NVDA",
          "CSCO", "INTU", "HD", "IBM", "AMD", "GOOGL", "PEP", "MCD", "MSFT"]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
allsyms = {s.name: s for s in mt5.symbols_get()}          # ALL, not just visible
print("symbols_get() returns %d symbols (visible-only would undercount badly)\n" % len(allsyms))

MODE = {0: "points", 1: "symbol ccy", 2: "% annual", 3: "margin ccy",
        4: "% annual", 5: "% annual", 6: "points", 7: "reopen"}

rows = []
for base in STOCKS:
    name = next((n for n in allsyms if n.upper().startswith(base) and "m" in n[-2:]), None)
    if name is None:
        name = next((n for n in allsyms if n.upper().startswith(base)), None)
    if name is None:
        print("  %s: not found" % base); continue
    mt5.symbol_select(name, True)
    s = mt5.symbol_info(name)
    d = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_D1, 0, 60)
    if d is None or len(d) < 20:
        print("  %s: no daily data" % name); continue
    d = pd.DataFrame(d)
    rng = (d.high - d.low).mean()
    px = float(d.close.iloc[-1])
    rows.append({"sym": name, "px": px, "d1_range": rng,
                 "swap_long": s.swap_long, "swap_short": s.swap_short,
                 "mode": MODE.get(s.swap_mode, s.swap_mode),
                 "spread": (s.ask - s.bid) if s.ask > 0 else float("nan"),
                 "min_lot": s.volume_min, "contract": s.trade_contract_size})
mt5.shutdown()

df = pd.DataFrame(rows)
if df.empty:
    raise SystemExit("no stock symbols resolved - check the naming convention")

# UNITS. Swap is quoted per LOT. The daily range comes back per SHARE. On this account a
# stock CFD lot is 100 shares, so comparing the two directly overstates financing by
# exactly that factor - a first run of this script reported a median of 120% of the daily
# range and nearly closed a viable branch on the strength of it. The real figure is ~1%.
# Always convert the range to per-lot before dividing.
df["range_per_lot"] = df.d1_range * df.contract
df["notional_per_lot"] = df.px * df.contract
df["nightly_both_legs"] = df.swap_long.abs() + df.swap_short.abs()
df["pct_of_range"] = 100 * df.nightly_both_legs / df.range_per_lot
df["pct_of_notional"] = 100 * df.nightly_both_legs / df.notional_per_lot

print("%-10s %11s %11s %10s %10s %11s %11s %11s"
      % ("symbol", "notional/lot", "range/lot", "swap L", "swap S", "both/night",
         "% of range", "% notional"))
print("-" * 92)
for _, r in df.sort_values("pct_of_range").iterrows():
    print("%-10s %11.0f %11.0f %10.2f %10.2f %11.2f %10.2f%% %10.3f%%"
          % (r["sym"], r["notional_per_lot"], r["range_per_lot"],
             r["swap_long"], r["swap_short"], r["nightly_both_legs"],
             r["pct_of_range"], r["pct_of_notional"]))

print("\nswap_mode reported: %s" % df["mode"].unique().tolist())
print("(mode matters - 'points' and '%% annual' are not the same units; if this says")
print(" percent-annual the raw numbers above are rates, not currency, and the")
print(" per-night currency cost must be derived from notional before judging.)")

med = df.pct_of_range.median()
print("\nMedian nightly financing on both legs = %.1f%% of one day's range." % med)
print("""
HOW TO JUDGE IT. A cross-sectional book rebalancing weekly holds ~5 nights, so multiply
by five to compare against a single day's move. If that product is a large share of the
range, financing alone outruns any realistic edge and this branch is closed before a
strategy is written - which is the cheap outcome, not the disappointing one.""")
print("Five nights of financing = %.1f%% of one daily range." % (5 * med))
