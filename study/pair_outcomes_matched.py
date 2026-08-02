"""What each outcome is worth in dollars under the matched-price mirror.

Worked from the real numbers now in force: 0.05 lots, a 20-point stop and 40-point target
on the demo, and the $10 spread this symbol actually quotes.

The point of the matched-price design is that there are only TWO outcomes, not four. Both
accounts close on the same tick at the same price, so the pair total is the same either
way. The interesting part is not the pair total - it is how unevenly the two accounts
share it, which decides how long the real-money balance lasts.
"""
import MetaTrader5 as mt5

LOTS = 0.05
DEMO_SL_PTS, DEMO_TP_PTS = 20.0, 40.0

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
mt5.symbol_select("BTCUSDm", True)
tk = mt5.symbol_info_tick("BTCUSDm")
SPREAD = round(tk.ask - tk.bid, 2)
MID = round((tk.ask + tk.bid) / 2, 2)
live_bal = None
mt5.shutdown()
mt5.initialize(path=r"C:\Projects\MT5-KinoliveTrader\terminal64.exe")
live_bal = mt5.account_info().balance
mt5.shutdown()

E = MID                                   # demo BUY fills on the ask, call it E
demo_sl, demo_tp = E - DEMO_SL_PTS, E + DEMO_TP_PTS
M = E - SPREAD                            # mirror SELLS, one spread away on the bid
live_tp, live_sl = demo_sl, demo_tp       # the swap: same prices, roles exchanged

print("MATCHED-PRICE MIRROR - what each outcome pays")
print("BTCUSDm %.2f, spread $%.2f, %.2f lots  ($%.2f per point)\n"
      % (MID, SPREAD, LOTS, LOTS))
print("  demo  BUY  @ %.2f    SL %.2f (-$%.2f)   TP %.2f (+$%.2f)"
      % (E, demo_sl, DEMO_SL_PTS * LOTS, demo_tp, DEMO_TP_PTS * LOTS))
print("  live  SELL @ %.2f    TP %.2f            SL %.2f" % (M, live_tp, live_sl))
print("                          ^^^^^^^^^^^^ the demo's two prices, roles swapped\n")

print("%-34s %9s %9s %9s" % ("outcome", "demo", "live", "PAIR"))
print("-" * 64)
rows = []
for name, px in (("price falls to %.2f (demo stop)" % demo_sl, demo_sl),
                 ("price rises to %.2f (demo target)" % demo_tp, demo_tp)):
    demo_pl = (px - E) * LOTS             # demo is long
    live_pl = (M - px) * LOTS             # mirror is short
    rows.append((demo_pl, live_pl))
    print("%-34s %+9.2f %+9.2f %+9.2f" % (name, demo_pl, live_pl, demo_pl + live_pl))
print("-" * 64)
print("%-34s %9s %9s %+9.2f" % ("there is no third outcome", "", "", rows[0][0] + rows[0][1]))

# How often each happens. A 20-point stop against a 40-point target is touched first
# about 40/(20+40) of the time on a driftless walk - the demo loses twice as often as
# it wins, by construction.
p_stop = DEMO_TP_PTS / (DEMO_SL_PTS + DEMO_TP_PTS)
print("\nThe demo's stop is nearer than its target, so it is hit about %.0f%% of the time."
      % (100 * p_stop))
demo_avg = p_stop * rows[0][0] + (1 - p_stop) * rows[1][0]
live_avg = p_stop * rows[0][1] + (1 - p_stop) * rows[1][1]
print("\n%-34s %9s %9s %9s" % ("expected per trade", "demo", "live", "PAIR"))
print("-" * 64)
print("%-34s %+9.2f %+9.2f %+9.2f" % ("", demo_avg, live_avg, demo_avg + live_avg))

print("""
THE UNEVEN SPLIT IS THE THING TO NOTICE. The demo comes out near zero, because its own
wins and losses cancel. The live account carries almost the entire spread - it collects
$%.2f on the common case and pays $%.2f on the rare one.""" % (rows[0][1], -rows[1][1]))

print("\nHOW LONG THE REAL MONEY LASTS at $%.2f" % live_bal)
for rate in (10, 20, 30):
    per_day = live_avg * rate
    print("   %2d pairs/day -> $%+.2f/day -> %4.1f days" % (rate, per_day, live_bal / -per_day))
