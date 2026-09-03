"""Direct question: is the combo better WITH or WITHOUT the $20/day stop?
Same rule, same signals, same 6 anchors - only the daily $ cap differs.
"""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate
from combo_period_stats import fresh_rev_masks

ANCH = range(6)

mt5.initialize(path=r"C:\Program Files\MetaTrader 5\terminal64.exe")
data = {name: mt5.copy_rates_from_pos("BTCUSDm", tf, 0, 80000)
        for name, tf in (("M1", mt5.TIMEFRAME_M1), ("M5", mt5.TIMEFRAME_M5),
                         ("M15", mt5.TIMEFRAME_M15), ("H1", mt5.TIMEFRAME_H1))}
mt5.shutdown()

print(f"{'TF':<4} {'no-cap mean':>12} {'w/cap mean':>12} {'diff':>9}  "
      f"{'no-cap worst-anchor':>20} {'w/cap worst-anchor':>20}  "
      f"{'no-cap dead':>12} {'w/cap dead':>11}")
for name, R in data.items():
    mb, ms = fresh_rev_masks(R, 150.0)
    a_eq, b_eq, a_dead, b_dead = [], [], 0, 0
    for a in ANCH:
        ra = simulate(R, a=a, arm="same", entry_filter=("mask", mb, ms),
                      day_stop=("cap", 2))
        rb = simulate(R, a=a, arm="same", entry_filter=("mask", mb, ms),
                      day_stop=("cap", 2), daily_loss_limit=20.0)
        assert ra["ok"] and rb["ok"]
        a_eq.append(ra["eq"]); b_eq.append(rb["eq"])
        a_dead += ra["dead"]; b_dead += rb["dead"]
    a_eq = np.array(a_eq); b_eq = np.array(b_eq)
    print(f"{name:<4} {a_eq.mean():12.2f} {b_eq.mean():12.2f} "
          f"{b_eq.mean()-a_eq.mean():+9.2f}  "
          f"{a_eq.min():20.2f} {b_eq.min():20.2f}  "
          f"{a_dead:12d} {b_dead:11d}")
