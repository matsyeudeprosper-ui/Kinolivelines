"""Across every past internal window, does the silence filter leave enough
structure to work with? Read-only."""
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
f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%m-%d %H:%M")
raw = lambda rs: [[int(r["time"]), float(r["open"]), float(r["high"]),
                   float(r["low"]), float(r["close"]),
                   1 if r["close"] >= r["open"] else -1] for r in rs]
print(f"{len(R)} bougies brutes, {len(marks)} evenements principaux\n")
print(f"  {'fenetre depuis':>14s} | {'duree':>6s} | {'brut':>5s} | "
      f"{'RAW pts':>7s} | {'FILTRE bougies':>14s} | {'FILTRE pts':>10s}")
rows_r = rows_f = 0; n = 0; blind = 0
for i, m in enumerate(marks[-40:]):
    t0 = m[0]
    t1 = marks[-40:][i+1][0] if i+1 < len(marks[-40:]) else int(R[-1]["time"])
    w = [r for r in R if t0 < int(r["time"]) < t1]
    if len(w) < 10: continue
    n += 1
    dr, *_ = F.engine(raw(w))[0:1]
    kf = F.build(w)
    df = F.engine(kf)[0] if len(kf) >= 10 else []
    rows_r += len(dr); rows_f += len(df)
    if not df: blind += 1
    mins = (t1 - t0) // 60
    print(f"  {f(t0):>14s} | {mins:5d}m | {len(w):5d} | {len(dr):7d} | "
          f"{len(kf):14d} | {len(df):10d}")
print(f"\n{n} fenetres: total {rows_r} points en BRUT, {rows_f} en FILTRE")
print(f"fenetres ou le filtre ne trouve AUCUNE structure : {blind}/{n} "
      f"({blind/n:.0%})")
