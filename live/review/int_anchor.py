"""How much does the INTERNAL structure depend on where its window starts?
Shift the start by a few candles and see if the published verdict moves."""
import sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 2000)
mt5.shutdown()
R = [dict(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in R]
kept = F.build(R)
_, marks, *_ = F.engine(kept)
t0 = marks[-1][0]
rows = [r for r in R[:-1] if int(r["time"]) > t0]
raw = lambda rs: [[int(r["time"]), float(r["open"]), float(r["high"]),
                   float(r["low"]), float(r["close"]),
                   1 if r["close"] >= r["open"] else -1] for r in rs]
print(f"fenetre interne actuelle: {len(rows)} bougies brutes\n")
print(f"  {'depart decale de':>18s} | {'bougies':>7s} | {'tend':>4s} | "
      f"{'BOS':>9s} | {'CHoCH':>9s} | pts")
base = None
for sh in (0, 1, 2, 3, 5, 10, 20, 40):
    c = raw(rows[sh:])
    if len(c) < 10: continue
    d, m, tr, ch, nx, iv, *_ = F.engine(c)
    if base is None: base = (tr, nx, iv)
    flag = "" if (tr, nx, iv) == base else "   <-- DIFFERENT"
    print(f"  {('+' + str(sh)):>18s} | {len(c):7d} | {tr:+4d} | "
          f"{(f'{nx:.2f}' if nx else '-'):>9s} | "
          f"{(f'{iv:.2f}' if iv else '-'):>9s} | {len(d):3d}{flag}")
