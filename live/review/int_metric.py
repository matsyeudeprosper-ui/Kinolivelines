"""Three candidate metrics for internal weather, same 2 h windows."""
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
        if t <= now: best = pt
        else: break
    return best
A = []; B = []; C = []
t_end = int(R[-1]["time"]); t_beg = int(kept[300][0])
now = t_beg + 7200
while now <= t_end:
    k = [x for x in kept if x[0] <= now]
    inner = [x for x in k if x[0] > window_start(now)][-F.INT_MAX:]
    a = b = c = 0
    if len(inner) >= 5:
        idots, imk, *_ = F.engine(inner)
        a = sum(1 for m in imk if m[2] == "bos" and m[0] > now - 7200)
        b = sum(1 for m in imk if m[0] > now - 7200)
        c = sum(1 for d_ in idots if d_[0] > now - 7200)
    A.append(a); B.append(b); C.append(c)
    now += 1800
from collections import Counter
def show(name, xs):
    s = sorted(xs); n = len(s)
    q = lambda p: s[min(n - 1, int(n * p))]
    z = sum(1 for x in xs if x == 0) / n
    print(f"  {name:<26s} zero {z:4.0%} | med {q(.5):2d} | p60 {q(.6):2d} | "
          f"p80 {q(.8):2d} | p90 {q(.9):2d} | max {max(s):2d}")
print(f"{len(A)} releves, 13.4 jours\n")
show("A flips internes / 2h", A)
show("B tous evenements / 2h", B)
show("C cassures (points) / 2h", C)
print("\n  repartition de C :")
c = Counter(C); tot = len(C); cum = 0
for k_ in sorted(c):
    cum += c[k_]
    if k_ <= 10 or c[k_] > 5:
        print(f"     {k_:3d} cassures | {c[k_]:4d} | {c[k_]/tot:4.0%} | cumul {cum/tot:4.0%}")
