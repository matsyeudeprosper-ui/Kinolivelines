"""For the most recent internal dot: what span produced it, and does the
candle it landed on satisfy the rule's opposite-colour condition?"""
import inspect, sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
src = inspect.getsource(F.engine)
src = src.replace("""                nd = _snap_dot(snap, span, 1) or [m[0], m[3], 1]""",
"""                nd = _snap_dot(snap, span, 1) or [m[0], m[3], 1]
                SPANS.append((nd, span, 1))""")
src = src.replace("""                nd = _snap_dot(snap, span, -1) or [m[0], m[2], -1]""",
"""                nd = _snap_dot(snap, span, -1) or [m[0], m[2], -1]
                SPANS.append((nd, span, -1))""")
src = src.replace("def engine(kept, snap=None):", "def engine_t(kept, snap=None):", 1)
ns = {"SPANS": []}
exec(src, F.__dict__ | ns, ns)
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 3000)
mt5.shutdown()
R = [dict(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in R]
kept = F.build(R)
out = F.engine(kept)
t0 = out[7] or out[1][-1][0]
raw = [[int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]),
        float(r["close"]), 1 if r["close"] >= r["open"] else -1]
       for r in R[:-1] if int(r["time"]) > t0]
ns["SPANS"].clear()
ns["engine_t"](raw, snap=kept)
f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%H:%M")
nd, span, kind = ns["SPANS"][-1]
print(f"dernier point : {f(nd[0])}  {nd[1]:.2f}  "
      f"{'BAS' if kind == 1 else 'HAUT'}")
print(f"\nspan BRUT : {f(span[0][0])} -> {f(span[-1][0])}, "
      f"{len(span)} bougies M1")
print(f"   dont opposees ({'rouges' if kind == 1 else 'vertes'}) : "
      f"{sum(1 for x in span if x[5] == (-1 if kind == 1 else 1))}")
print(f"   creux le plus bas du span brut : "
      f"{min(x[3] for x in span):.2f}")
drawn = [k for k in kept if span[0][0] <= k[0] <= span[-1][0]]
print(f"\nbougies DESSINEES dans ce meme span : {len(drawn)}")
for k in drawn:
    col = "verte" if k[5] == 1 else "rouge"
    print(f"   {f(k[0])}  {col:<6s} O {k[1]:.2f} H {k[2]:.2f} "
          f"B {k[3]:.2f} C {k[4]:.2f}")
if drawn:
    opp = sum(1 for k in drawn if k[5] == (-1 if kind == 1 else 1))
    print(f"   dont opposees : {opp}  -> "
          + ("le span visible contient bien un repli"
             if opp else "AUCUN repli visible dans ce span"))
