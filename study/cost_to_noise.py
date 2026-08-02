"""Which instrument is cheapest to trade RELATIVE to how much it moves?

The squeeze this project keeps hitting: at short horizons BTC moves less than the $10
spread, so cost dominates; at long horizons the moves are big enough but every signal
tested is null. A cheaper broker cannot fix it - BTCUSDm at $10 round trip is already
near the cheapest available anywhere.

But cost is only half a ratio. What matters is spread DIVIDED BY how far the instrument
travels in the time you hold it. If some other symbol on this account has a cost-to-noise
ratio five times better, then the same size of edge that fails on BTC would pay there, and
nothing about the research has to change - only the instrument.

That is a different question from "does this indicator work", which is why it is worth
asking after twenty failed entry ideas.

Reported at two horizons because they answer different questions: M30 for the intraday
style actually being traded, D1 as the ceiling on what any longer-horizon idea could earn.
"""
import pandas as pd
import MetaTrader5 as mt5

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
syms = [s.name for s in mt5.symbols_get() if s.visible]
print("Visible symbols on this account: %d" % len(syms))
print(", ".join(syms), "\n")

rows = []
for s in syms:
    t = mt5.symbol_info_tick(s)
    if not t or t.ask <= 0:
        continue
    sp = t.ask - t.bid
    d = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_D1, 0, 30)
    h = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_M30, 0, 480)
    if d is None or h is None or len(d) < 20 or len(h) < 100:
        continue
    d, h = pd.DataFrame(d), pd.DataFrame(h)
    rows.append({"sym": s, "spread": sp,
                 "m30": (h.high - h.low).mean(), "d1": (d.high - d.low).mean()})
mt5.shutdown()

df = pd.DataFrame(rows)
df["pct_m30"] = 100 * df.spread / df.m30
df["pct_d1"] = 100 * df.spread / df.d1
df = df.sort_values("pct_m30")

print("COST AS A SHARE OF WHAT THE INSTRUMENT ACTUALLY MOVES")
print("Lower is better - it is the fraction of a typical move eaten by the spread.\n")
print("%-12s %10s %10s %10s %10s %10s"
      % ("symbol", "spread", "M30 range", "cost/M30", "D1 range", "cost/D1"))
print("-" * 68)
for _, r in df.iterrows():
    print("%-12s %10.2f %10.2f %9.1f%% %10.2f %9.2f%%"
          % (r["sym"], r["spread"], r["m30"], r["pct_m30"], r["d1"], r["pct_d1"]))

best = df.iloc[0]
btc = df[df.sym.str.contains("BTC")]
print("\nCheapest relative to its own movement: %s at %.1f%% of an M30 range."
      % (best["sym"], best["pct_m30"]))
if len(btc):
    b = btc.iloc[0]
    print("BTCUSDm is %.1f%% - a factor of %.1fx %s."
          % (b["pct_m30"], b["pct_m30"] / best["pct_m30"],
             "worse" if b["pct_m30"] > best["pct_m30"] else "better"))
    print("""
The order-book edge was 5x too small on BTC. So the question this answers is simple: is
any instrument here 5x cheaper relative to its noise? If yes, that is where to retest the
ideas that failed. If everything sits in the same band, the instrument is not the problem
and switching symbols is just twenty more failed tests in a new place.""")
