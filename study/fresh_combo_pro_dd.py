"""H1 combo max drawdown + cycle stats per anchor (Pro BTCUSD $7)."""
import numpy as np
import MetaTrader5 as mt5
from hedge_engine import simulate
from run_fresh_early_combo_pro import fresh_rev_masks

mt5.initialize(path=r"C:\NestTerminals\u223985697\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSD", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
mb, ms = fresh_rev_masks(R)

for a in range(6):
    r = simulate(R, a=a, arm="same", spread=7.0,
                 entry_filter=("mask", mb, ms), day_stop=("cap", 2))
    curve = np.asarray(r["curve"], float)
    peak = np.maximum.accumulate(curve)
    dd = peak - curve
    cyc = np.asarray(r["cycles"], float)
    print(f"a{a}: eq {r['eq']:+8.2f} maxDD {dd.max():7.2f} "
          f"cycles {len(cyc)} win% "
          f"{100*np.mean(cyc>0):.0f} avgWin "
          f"{cyc[cyc>0].mean():+.2f} avgLoss {cyc[cyc<0].mean():+.2f} "
          f"worstCycle {cyc.min():+.2f}")
