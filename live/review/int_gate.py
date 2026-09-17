"""The main structure's gate is "at least one flip in 2 h". What is the
equivalent for the INTERNAL structure? Record activity features at each
aligned internal break and test them as gates."""
import bisect, inspect, sys, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
SPREAD, RR = 7.0, 0.8
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 60000)
mt5.shutdown()
R = [dict(time=int(r[0]), open=float(r[1]), high=float(r[2]),
          low=float(r[3]), close=float(r[4])) for r in R]
kept = F.build(R)
raw_i = {r["time"]: i for i, r in enumerate(R)}
kt = [k[0] for k in kept]
src = inspect.getsource(F.engine)
src = src.replace("        lo_i, lo_v = i, l\n    # 2026-09-15",
                  "        lo_i, lo_v = i, l\n"
                  "        SNAP.append((t, trend,\n"
                  "                     (prot_lo[1] if (trend==1 and prot_lo)\n"
                  "                      else (prot_hi[1] if (trend==-1 and prot_hi)\n"
                  "                            else None)),\n"
                  "                     (hi_v if trend==1 else\n"
                  "                      (lo_v if trend==-1 else None))))\n"
                  "    # 2026-09-15")
src = src.replace("                    prot_lo = nd",
                  "                    prot_lo = nd; BRK.append((t, 1, nd[1], nd[0]))")
src = src.replace("                    prot_hi = nd",
                  "                    prot_hi = nd; BRK.append((t, -1, nd[1], nd[0]))")
src = src.replace("def engine(kept, snap=None):", "def engine_b(kept, snap=None):", 1)
ns = {"BRK": [], "SNAP": []}
exec(src, F.__dict__ | ns, ns)
ns["BRK"].clear(); ns["SNAP"].clear(); ns["engine_b"](kept)
MAIN, SNAP = list(ns["BRK"]), list(ns["SNAP"])
STT = [t for t, *_ in SNAP]; ST = {t: (a, b, c) for t, a, b, c in SNAP}
def state_at(t):
    i = bisect.bisect_right(STT, t) - 1
    return ST[STT[i]] if i >= 0 else (0, None, None)
def walk(i0, d, entry, sl, tp):
    for r in R[i0 + 1:i0 + 6000]:
        if d == 1:
            if r["low"] <= sl: return -abs(entry - sl)
            if r["high"] >= tp: return abs(tp - entry)
        else:
            if r["high"] >= sl: return -abs(entry - sl)
            if r["low"] <= tp: return abs(tp - entry)
    return None
T = []
for j, (mt_, mdir, mprot, mdot) in enumerate(MAIN):
    seg_end = MAIN[j + 1][0] if j + 1 < len(MAIN) else R[-1]["time"]
    seg = [k for k in kept if mdot < k[0] <= seg_end]
    if len(seg) < 5: continue
    ns["BRK"].clear(); ns["SNAP"].clear(); ns["engine_b"](seg)
    brks = list(ns["BRK"]); mks = None
    _d, mks, *_ = F.engine(seg)
    for bt, d, lvl, _ in brks:
        mtr, miv, mnx = state_at(bt)
        if not mtr or d != mtr: continue
        i0 = raw_i.get(bt)
        if i0 is None: continue
        e = R[i0]["close"] + (SPREAD if d == 1 else -SPREAD)
        dist = abs(e - lvl)
        if dist <= 10: continue
        p = walk(i0, d, e, lvl, e + d * RR * dist)
        if p is None: continue
        b1 = sum(1 for x in brks if bt - 3600 <= x[0] < bt)
        b2 = sum(1 for x in brks if bt - 7200 <= x[0] < bt)
        b4 = sum(1 for x in brks if bt - 14400 <= x[0] < bt)
        fl = sum(1 for m in mks
                 if m[2] == "bos" and bt - 7200 <= m[0] < bt)
        ev = sum(1 for m in mks if bt - 7200 <= m[0] < bt)
        age = (bt - mdot) / 3600.0
        # chart candles in the last 2 h = how "awake" the filtered chart is
        lo_i2 = bisect.bisect_left(kt, bt - 7200)
        hi_i2 = bisect.bisect_left(kt, bt)
        cc = hi_i2 - lo_i2
        T.append(dict(t=bt, r=p / dist, d=d, dist=dist, b1=b1, b2=b2,
                      b4=b4, fl=fl, ev=ev, age=age, cc=cc,
                      h=dt.datetime.utcfromtimestamp(bt).hour))
T.sort(key=lambda x: x["t"])
def stats(xs, name):
    if len(xs) < 10:
        print(f"  {name:<34s} n {len(xs):4d}  (trop peu)"); return
    n = len(xs); rs = [x["r"] for x in xs]
    w = sum(1 for r in rs if r > 0) / n; e = sum(rs) / n
    se = (sum((r - e) ** 2 for r in rs) / (n - 1)) ** .5 / n ** .5
    h = n // 2
    e1 = sum(x["r"] for x in xs[:h]) / h
    e2 = sum(x["r"] for x in xs[h:]) / (n - h)
    print(f"  {name:<34s} n {n:4d} | gagn {w:4.0%} | esp {e:+.3f} "
          f"+/-{2*se:.3f} | moities {e1:+.2f}/{e2:+.2f} "
          f"{'accord' if (e1>0)==(e2>0) else '  -'}")
print(f"{len(T)} trades alignes, 42 jours\n")
stats(T, "REFERENCE")
print("\n  cassures internes dans les 2 h precedentes")
for lo, hi, nm in ((0,1,"aucune"),(1,2,"1"),(2,4,"2-3"),(4,99,"4 et +")):
    stats([x for x in T if lo <= x["b2"] < hi], f"  {nm}")
print("\n  cassures internes dans l heure precedente")
for lo, hi, nm in ((0,1,"aucune"),(1,2,"1"),(2,99,"2 et +")):
    stats([x for x in T if lo <= x["b1"] < hi], f"  {nm}")
print("\n  flips internes dans les 2 h")
for lo, hi, nm in ((0,1,"aucun"),(1,99,"au moins 1")):
    stats([x for x in T if lo <= x["fl"] < hi], f"  {nm}")
print("\n  bougies du chart dans les 2 h (marche eveille)")
cs = sorted(x["cc"] for x in T)
q1,q2,q3 = [cs[int(len(cs)*p)] for p in (.25,.5,.75)]
for lo, hi, nm in ((0,q1,"le plus calme"),(q1,q2,"2e quart"),
                   (q2,q3,"3e quart"),(q3,9999,"le plus anime")):
    stats([x for x in T if lo <= x["cc"] < hi], f"  {nm} ({lo}-{hi})")
print("\n  age de la structure interne")
for lo, hi, nm in ((0,1,"< 1 h"),(1,3,"1-3 h"),(3,8,"3-8 h"),(8,999,"> 8 h")):
    stats([x for x in T if lo <= x["age"] < hi], f"  {nm}")

import random
print("\n" + "=" * 64)
print("  LA PORTE : au moins une cassure interne recemment")
for w, nm in ((3600, "1 h"), (7200, "2 h"), (14400, "4 h")):
    key = {3600: "b1", 7200: "b2", 14400: "b4"}[w]
    stats([x for x in T if x[key] >= 1], f"  au moins 1 cassure dans {nm}")
    stats([x for x in T if x[key] == 0], f"  aucune dans {nm} (rejetes)")
print("\n  cumul avec Londres 07-12 UTC")
stats([x for x in T if x["b1"] >= 1 and 7 <= x["h"] < 12],
      "  porte 1 h + Londres")
stats([x for x in T if 7 <= x["h"] < 12], "  Londres seul")
print("\n" + "=" * 64)
print("  temoin direction aleatoire sur la porte 1 h")
sel = [x for x in T if x["b1"] >= 1]
real = sum(x["r"] for x in sel) / len(sel)
sims = []
for sd in range(12):
    random.seed(400 + sd); out = []
    for x in sel:
        i0 = raw_i.get(x["t"])
        if i0 is None: continue
        d = random.choice((1, -1))
        e = R[i0]["close"] + (SPREAD if d == 1 else -SPREAD)
        p = walk(i0, d, e, e - d * x["dist"], e + d * RR * x["dist"])
        if p is not None: out.append(p / x["dist"])
    if len(out) > 20: sims.append(sum(out) / len(out))
sims.sort()
beat = sum(1 for g in sims if g >= real)
print(f"     reel {real:+.3f} | hasard median {sims[len(sims)//2]:+.3f} "
      f"(min {sims[0]:+.3f} max {sims[-1]:+.3f}) | {beat}/{len(sims)} l atteignent")
print("     -> " + ("vient de la derive" if beat >= 2 else "survit au temoin"))
# permutation against the same pool
rs = [x["r"] for x in T]; k = len(sel); random.seed(7); hit = 0
for _ in range(4000):
    random.shuffle(rs)
    if sum(rs[:k]) / k >= real: hit += 1
print(f"     permutation dans le meme jeu : {hit/4000:.1%}")
