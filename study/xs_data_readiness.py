"""Before any cross-sectional work: is there enough history, and does it line up?

The cheapest possible failure. A cross-sectional test ranks instruments against each
other on the same day, so it needs (a) enough days to have any power at all and (b) days
that actually OVERLAP across names - 19 stocks with deep history are useless if they only
share three months.

This is deliberately run before writing any strategy, for the same reason the BTC/ETH
pair idea was killed in ten minutes by a feasibility test instead of after a session of
EA code. If the history is thin, the branch closes here at zero cost.

What "enough" means, stated before looking: a long/short book rebalanced weekly gets
about 52 independent observations a year. Detecting a Sharpe of 0.5 at 80% power needs
roughly 130 independent periods, so about 2.5 years of weekly rebalances. Less than ~2
years of common history and this cannot be settled either way - which is a finding, not
a failure.
"""
import pandas as pd
import MetaTrader5 as mt5

STOCKS = ["TSLA", "AMZN", "INTC", "TSM", "ORCL", "AVGO", "AAPL", "MS", "ADBE", "NVDA",
          "CSCO", "INTU", "HD", "IBM", "AMD", "GOOGL", "PEP", "MCD", "MSFT"]

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
allsyms = {s.name: s for s in mt5.symbols_get()}

series = {}
meta = []
for base in STOCKS:
    name = next((n for n in allsyms if n.upper() == base + "M"), None) \
        or next((n for n in allsyms if n.upper().startswith(base)), None)
    if name is None:
        meta.append({"base": base, "sym": None, "bars": 0}); continue
    mt5.symbol_select(name, True)
    r = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_D1, 0, 5000)
    if r is None or len(r) == 0:
        meta.append({"base": base, "sym": name, "bars": 0}); continue
    d = pd.DataFrame(r)
    d["t"] = pd.to_datetime(d["time"], unit="s").dt.normalize()
    s = d.set_index("t")["close"].astype(float)
    s = s[~s.index.duplicated(keep="last")]
    series[name] = s
    meta.append({"base": base, "sym": name, "bars": len(s),
                 "first": s.index.min().date(), "last": s.index.max().date()})
mt5.shutdown()

md = pd.DataFrame(meta)
print("PER-SYMBOL DAILY HISTORY")
print("%-8s %-9s %7s  %-12s %-12s" % ("base", "symbol", "bars", "first", "last"))
print("-" * 54)
for _, r in md.sort_values("bars", ascending=False).iterrows():
    print("%-8s %-9s %7d  %-12s %-12s"
          % (r["base"], r["sym"] or "-", r["bars"],
             r.get("first", "-"), r.get("last", "-")))

if not series:
    raise SystemExit("\nNo stock series returned. Branch cannot start.")

px = pd.DataFrame(series).sort_index()
print("\nCOMBINED PANEL")
print("  %d symbols, %d calendar rows, %s to %s"
      % (px.shape[1], px.shape[0], px.index.min().date(), px.index.max().date()))

# Rows where every name has a price. That is what a cross-sectional rank actually needs.
full = px.dropna()
cover = px.notna().sum(axis=1)
print("  rows with ALL %d names priced: %d" % (px.shape[1], len(full)))
print("  rows with at least 10 names:   %d" % (cover >= 10).sum())
if len(full):
    print("  common window: %s to %s" % (full.index.min().date(), full.index.max().date()))
    yrs = (full.index.max() - full.index.min()).days / 365.25
    print("  common history: %.2f years  ->  ~%d weekly rebalances" % (yrs, yrs * 52))
    print("\n  VERDICT: %s" % (
        "enough to test a Sharpe ~0.5 idea" if yrs >= 2.5 else
        "thin - can screen for a large effect only, cannot settle a small one"
        if yrs >= 1.0 else
        "TOO SHORT to conclude anything. Do not build on this."))

print("""
Note on what daily CFD bars are and are not. These are the broker's own daily candles for
a CFD on the stock, not the exchange's official close, and they cover only the hours the
broker quotes. They are fine for ranking names against each other, which is all a
cross-sectional test needs. They are NOT a substitute for proper adjusted close data if
anything here ever turns into a real allocation.""")
