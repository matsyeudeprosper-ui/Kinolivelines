"""At the bearish flip of 08:15, what does each candidate rule give?"""
import inspect, sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
src = inspect.getsource(F.engine)
src = src.replace("""                if choch == -1 and trend != -1:""",
"""                if choch == -1 and trend != -1:
                    TR.append(dict(t=t, leg_top=hi_v, leg_top_t=kept[hi_i][0],
                                   span_max=m[2], span_max_t=m[0],
                                   span_n=len(span),
                                   span_a=span[0][0], span_b=span[-1][0]))""")
src = src.replace("def engine(kept, snap=None):", "def engine_t(kept, snap=None):", 1)
ns = {"TR": []}
exec(src, F.__dict__ | ns, ns)
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 3000)
mt5.shutdown()
R = [dict(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in R]
kept = F.build(R)
out = F.engine(kept)
t0 = out[7] or out[1][-1][0]
inner = [k for k in kept if k[0] > t0][-F.INT_MAX:]
ns["TR"].clear()
ns["engine_t"](inner)
f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%H:%M")
for x in ns["TR"][-2:]:
    print(f"BOS baissier de flip a {f(x['t'])}")
    print(f"   A. sommet de la JAMBE (regle actuelle)   {x['leg_top']:.2f}"
          f"   pose {f(x['leg_top_t'])}")
    print(f"   B. plus haut APRES le CHoCH (ancienne)   {x['span_max']:.2f}"
          f"   pose {f(x['span_max_t'])}")
    print(f"      la fenetre B va de {f(x['span_a'])} a {f(x['span_b'])}, "
          f"{x['span_n']} bougies")
    # C: the highest high between the CHoCH and the break, on the chart
    print()
