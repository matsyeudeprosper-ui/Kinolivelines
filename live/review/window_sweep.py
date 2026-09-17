"""How long should the internal window be? Sweep it over the last drawn
candles and count the structure each length produces."""
import sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 20000)
mt5.shutdown()
R = [dict(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in R]
kept = F.build(R)
_, marks, *_ = F.engine(kept)
print(f"{len(kept)} bougies du chart au total\n")
print(f"  {'fenetre':>8s} | {'points':>6s} | {'evts':>5s} | {'tend':>4s} | "
      f"{'duree':>8s} | structure presente")
# how often does each window length give a usable structure? sample 40 times
import statistics
for n in (30, 40, 60, 80, 120, 200, 400):
    alive = 0; dots = 0; evts = 0; samples = 0
    for end in range(len(kept) - 1, max(n, len(kept) - 2400), -60):
        w = kept[max(0, end - n):end]
        if len(w) < 5: continue
        samples += 1
        d, m, tr, *_ = F.engine(w)
        if tr != 0: alive += 1
        dots += len(d); evts += len(m)
    w = kept[-n:]
    d, m, tr, *_ = F.engine(w)
    mins = (w[-1][0] - w[0][0]) // 60
    print(f"  {n:8d} | {len(d):6d} | {len(m):5d} | {tr:+4d} | "
          f"{mins:6d}m | {alive}/{samples} ({alive/max(samples,1):.0%})")
