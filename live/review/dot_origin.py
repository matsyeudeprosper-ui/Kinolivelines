"""Where does each internal dot come from? Tag the three places the engine
appends one: a flip BOS, a continuation BOS, or the trend-0 bootstrap."""
import inspect, sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F

src = inspect.getsource(F.engine)
# tag each append site without touching the logic
src = src.replace("""                    dots.append(nd)
                    prot_lo = nd
                    up_st = dn_st = 0""",
"""                    dots.append(nd); ORIG.append('BOS de flip')
                    prot_lo = nd
                    up_st = dn_st = 0""")
src = src.replace("""                    dots.append(nd)
                    prot_hi = nd
                    up_st = dn_st = 0""",
"""                    dots.append(nd); ORIG.append('BOS de flip')
                    prot_hi = nd
                    up_st = dn_st = 0""")
src = src.replace("""                elif trend == 1:
                    dots.append(nd)
                    prot_lo = nd""",
"""                elif trend == 1:
                    dots.append(nd); ORIG.append('BOS continuation')
                    prot_lo = nd""")
src = src.replace("""                elif trend == -1:
                    dots.append(nd)
                    prot_hi = nd""",
"""                elif trend == -1:
                    dots.append(nd); ORIG.append('BOS continuation')
                    prot_hi = nd""")
src = src.replace("""                        up_st += 1
                        dots.append(nd)""",
"""                        up_st += 1
                        dots.append(nd); ORIG.append('AMORCAGE (aucun BOS)')""")
src = src.replace("""                        dn_st += 1
                        dots.append(nd)""",
"""                        dn_st += 1
                        dots.append(nd); ORIG.append('AMORCAGE (aucun BOS)')""")
src = src.replace("def engine(kept):", "def engine_t(kept):", 1)
ns = {"ORIG": []}
exec(src, F.__dict__ | ns, ns)

if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 3000)
mt5.shutdown()
R = [dict(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in R]
kept = F.build(R)
out = F.engine(kept)
t0 = out[7] or out[1][-1][0]
rows = [[int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]),
         float(r["close"]), 1 if r["close"] >= r["open"] else -1]
        for r in R[:-1] if int(r["time"]) > t0]
ns["ORIG"].clear()
dots = ns["engine_t"](rows)[0]
f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%H:%M")
from collections import Counter
c = Counter(ns["ORIG"])
print(f"fenetre interne : {len(dots)} points au total\n")
for k, v in c.most_common():
    print(f"  {v:3d}  {k}")
print("\n  detail des 12 derniers :")
for (t, v, k), o in list(zip(dots, ns["ORIG"]))[-12:]:
    print(f"     {f(t)}  {v:9.2f}  {'BAS' if k == 1 else 'HAUT'}   {o}")
