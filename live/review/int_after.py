"""After unifying the rules: how often does the internal structure exist?"""
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
ms = marks[-60:]
alive = dead = 0
tot_dots = 0
mins_alive = mins_dead = 0
for i, m in enumerate(ms):
    t0 = m[0]
    t1 = ms[i+1][0] if i+1 < len(ms) else int(R[-1]["time"])
    w = [r for r in R if t0 < int(r["time"]) < t1]
    if len(w) < 10: continue
    kf = F.build(w)
    d, mk, tr, *_ = F.engine(kf) if len(kf) >= 10 else ([], [], 0)
    mins = (t1 - t0) // 60
    if tr != 0:
        alive += 1; mins_alive += mins
    else:
        dead += 1; mins_dead += mins
    tot_dots += len(d)
n = alive + dead
print(f"{n} fenetres internes examinees ({(mins_alive+mins_dead)/60:.0f} h au total)")
print(f"  structure interne PRESENTE : {alive}/{n} ({alive/n:.0%})  "
      f"= {mins_alive/60:.0f} h")
print(f"  structure interne ABSENTE  : {dead}/{n} ({dead/n:.0%})  "
      f"= {mins_dead/60:.0f} h")
print(f"  points internes au total : {tot_dots}")
