"""H1 fresh+early combo on Pro BTCUSD: per-year P&L (mean of 6
anchors) - is the edge alive recently? 2026-09-08."""
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timezone
from hedge_engine import simulate
from run_fresh_early_combo_pro import fresh_rev_masks

mt5.initialize(path=r"C:\NestTerminals\u223985697\terminal64.exe")
R = mt5.copy_rates_from_pos("BTCUSD", mt5.TIMEFRAME_H1, 0, 80000)
mt5.shutdown()
mb, ms = fresh_rev_masks(R)

years = {}
for a in range(6):
    r = simulate(R, a=a, arm="same", spread=7.0,
                 entry_filter=("mask", mb, ms), day_stop=("cap", 2))
    assert r["ok"] and not r["dead"]
    curve = np.asarray(r["curve"], float)
    tm = np.asarray(r["tm"][:len(curve)], int)
    ys = np.array([datetime.fromtimestamp(int(t),
                   tz=timezone.utc).year for t in tm])
    for y in np.unique(ys):
        m = ys == y
        d = curve[m][-1] - (curve[m][0])
        years.setdefault(int(y), []).append(float(d))

print("year   meanP&L  min..max over 6 anchors")
for y in sorted(years):
    v = years[y]
    print(f"{y}: {np.mean(v):+8.2f}  {min(v):+8.2f} .. {max(v):+8.2f}")
tot = sum(np.mean(v) for v in years.values())
print(f"total mean {tot:+.2f}")
