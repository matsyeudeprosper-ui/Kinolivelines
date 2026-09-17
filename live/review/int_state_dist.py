"""Not a rate - a STATE. For a half-manual trader the useful question is
"is there something to trade right now", which is a state machine."""
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
from collections import Counter
st = Counter()
t_end = int(R[-1]["time"]); t_beg = int(kept[300][0])
now = t_beg + 7200
while now <= t_end:
    k = [x for x in kept if x[0] <= now]
    inner = [x for x in k if x[0] > window_start(now)][-F.INT_MAX:]
    lab = "pas de structure"
    if len(inner) >= 5:
        d_, m_, tr, ch, nx, iv, nx_t, iv_t, dr, flp, flp_t, fdir = \
            F.engine(inner)
        if tr == 0:
            lab = "pas de structure"
        else:
            ready = F.pullback_since(k, nx_t, dr)
            if ch and ch != tr:
                lab = "bascule armee"
            elif ready:
                lab = "cassure en vue"
            else:
                lab = "en cours de formation"
    st[lab] += 1
    now += 1800
tot = sum(st.values())
print(f"{tot} releves toutes les 30 min sur 13.4 jours\n")
order = ["cassure en vue", "bascule armee", "en cours de formation",
         "pas de structure"]
for k_ in order:
    if st[k_]:
        print(f"  {k_:<24s} {st[k_]:4d}  {st[k_]/tot:5.0%}")
