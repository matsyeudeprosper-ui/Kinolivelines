"""Audit every published internal dot against the owner's full rule:
between a previous high and a new high, separated by >=1 opposite candle,
sitting on the span's extreme - all judged on the DRAWN candles."""
import inspect, sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
src = inspect.getsource(F.engine)
for k in ("1", "-1"):
    src = src.replace(f"                nd = _vis or [m[0], m[{'3' if k=='1' else '2'}], {k}]",
                      f"                nd = _vis or [m[0], m[{'3' if k=='1' else '2'}], {k}]\n"
                      f"                SP.append((nd, span, {k}, vis))")
src = src.replace("def engine(kept, snap=None):", "def engine_t(kept, snap=None):", 1)
ns = {"SP": []}
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
ns["SP"].clear()
dots = ns["engine_t"](raw, snap=kept)[0]
f = lambda t: dt.datetime.utcfromtimestamp(t).strftime("%H:%M")
shown = [x for x in ns["SP"] if x[3]]
hidden = [x for x in ns["SP"] if not x[3]]
print(f"{len(ns['SP'])} cassures confirmees -> {len(shown)} points dessines, "
      f"{len(hidden)} supprimes\n")
bad = 0
for nd, span, kind, vis in shown:
    cand = [k for k in kept if span[0][0] <= k[0] <= span[-1][0]]
    opp = sum(1 for k in cand if k[5] == -kind)
    ext = (min(k[3] for k in cand) if kind == 1
           else max(k[2] for k in cand))
    ok = opp >= 1 and abs(ext - nd[1]) < 0.01 and len(cand) >= 1
    if not ok:
        bad += 1
        print(f"  ECHEC {f(nd[0])} {nd[1]:.2f}: {len(cand)} bougies "
              f"visibles, {opp} opposee(s), extreme {ext:.2f}")
print(f"points dessines respectant la regle complete : "
      f"{len(shown) - bad}/{len(shown)}")
for nd, span, kind, vis in shown[-4:]:
    cand = [k for k in kept if span[0][0] <= k[0] <= span[-1][0]]
    opp = sum(1 for k in cand if k[5] == -kind)
    print(f"   {f(nd[0])} {nd[1]:9.2f} {'BAS' if kind==1 else 'HAUT'}  "
          f"span visible {len(cand)} bougies dont {opp} opposee(s)")
