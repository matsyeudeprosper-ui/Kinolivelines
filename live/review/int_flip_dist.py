"""Distribution of INTERNAL flips per 2 h, so the weather boundaries are
measured rather than copied from the main structure."""
import inspect, sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 20000)
mt5.shutdown()
R = [dict(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in R]
kept = F.build(R)

# record when the MAIN protected dot moves, so each sample knows its window
src = inspect.getsource(F.engine)
src = src.replace("                    prot_lo = nd",
                  "                    prot_lo = nd; PT.append((t, nd[0]))")
src = src.replace("                    prot_hi = nd",
                  "                    prot_hi = nd; PT.append((t, nd[0]))")
src = src.replace("def engine(kept, snap=None):", "def engine_p(kept, snap=None):", 1)
ns = {"PT": []}
exec(src, F.__dict__ | ns, ns)
ns["engine_p"](kept)
PT = ns["PT"]

def window_start(now):
    best = 0
    for t, pt in PT:
        if t <= now:
            best = pt
        else:
            break
    return best

counts = []
t_end = int(R[-1]["time"])
t_beg = int(kept[300][0])
step = 1800                                  # a sample every 30 min
now = t_beg + 7200
while now <= t_end:
    k = [x for x in kept if x[0] <= now]
    t0 = window_start(now)
    inner = [x for x in k if x[0] > t0][-F.INT_MAX:]
    n = 0
    if len(inner) >= 5:
        _, imk, *_ = F.engine(inner)
        n = sum(1 for m in imk if m[2] == "bos" and m[0] > now - 7200)
    counts.append(n)
    now += step
from collections import Counter
c = Counter(counts)
tot = len(counts)
print(f"{tot} releves sur "
      f"{(t_end - t_beg) / 86400:.1f} jours, un toutes les 30 min\n")
print(f"  {'flips/2h':>8s} | {'n':>5s} | {'part':>6s} | cumul")
cum = 0
for k_ in sorted(c):
    cum += c[k_]
    print(f"  {k_:8d} | {c[k_]:5d} | {c[k_]/tot:5.0%} | {cum/tot:5.0%}")
s = sorted(counts)
q = lambda p: s[min(len(s) - 1, int(len(s) * p))]
print(f"\n  mediane {q(.5)}   p60 {q(.6)}   p75 {q(.75)}   "
      f"p85 {q(.85)}   p95 {q(.95)}   max {max(s)}")
print(f"  part a zero : {c[0]/tot:.0%}")
