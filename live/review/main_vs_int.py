"""Same rule, same costs, same 28 days: MAIN-structure trades against
INTERNAL-structure trades. Entry at the break close plus a spread, stop at
the protected level that break creates, target 0.8R, exits on raw M1 with
the stop checked first."""
import inspect, sys, time
sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import MetaTrader5 as mt5
import owl_chart_feed as F
SPREAD, RR = 7.0, 0.8
if not F.connect(): sys.exit("pas de connexion")
R = mt5.copy_rates_from_pos(F.SYMBOL, mt5.TIMEFRAME_M1, 0, 40000)
mt5.shutdown()
R = [dict(time=int(r[0]), open=float(r[1]), high=float(r[2]),
          low=float(r[3]), close=float(r[4])) for r in R]
kept = F.build(R)
raw_i = {r["time"]: i for i, r in enumerate(R)}
src = inspect.getsource(F.engine)
src = src.replace("                    prot_lo = nd",
                  "                    prot_lo = nd; BRK.append((t, 1, nd[1], nd[0]))")
src = src.replace("                    prot_hi = nd",
                  "                    prot_hi = nd; BRK.append((t, -1, nd[1], nd[0]))")
src = src.replace("def engine(kept, snap=None):", "def engine_b(kept, snap=None):", 1)
ns = {"BRK": []}
exec(src, F.__dict__ | ns, ns)

def walk(i0, d, entry, sl, tp):
    for r in R[i0 + 1:i0 + 6000]:
        if d == 1:
            if r["low"] <= sl: return -abs(entry - sl)
            if r["high"] >= tp: return abs(tp - entry)
        else:
            if r["high"] >= sl: return -abs(entry - sl)
            if r["low"] <= tp: return abs(tp - entry)
    return None

def make(bt, d, lvl):
    i0 = raw_i.get(bt)
    if i0 is None: return None
    entry = R[i0]["close"] + (SPREAD if d == 1 else -SPREAD)
    dist = abs(entry - lvl)
    if dist <= 10: return None
    p = walk(i0, d, entry, lvl, entry + d * RR * dist)
    return None if p is None else dict(t=bt, d=d, r=p / dist, dist=dist)

ns["BRK"].clear(); ns["engine_b"](kept)
MAIN = list(ns["BRK"])
main_tr = []
for bt, d, lvl, dot in MAIN:
    tr = make(bt, d, lvl)
    if tr: main_tr.append(tr)

int_tr = []
for j, (mt_, mdir, mlvl, mdot) in enumerate(MAIN):
    seg_end = MAIN[j + 1][0] if j + 1 < len(MAIN) else R[-1]["time"]
    seg = [k for k in kept if mdot < k[0] <= seg_end]
    if len(seg) < 5: continue
    ns["BRK"].clear(); ns["engine_b"](seg)
    for bt, d, lvl, _ in ns["BRK"]:
        tr = make(bt, d, lvl)
        if tr:
            tr["mtr"] = mdir
            int_tr.append(tr)

def stats(xs, name):
    if not xs:
        print(f"  {name:<32s} aucun"); return
    n = len(xs); rs = [x["r"] for x in xs]
    w = sum(1 for r in rs if r > 0) / n; e = sum(rs) / n
    se = (sum((r - e) ** 2 for r in rs) / max(n - 1, 1)) ** .5 / n ** .5
    md = sorted(x["dist"] for x in xs)[n // 2]
    print(f"  {name:<32s} n {n:4d} | gagnants {w:4.0%} | "
          f"esperance {e:+.3f} R +/-{2*se:.3f} | total {sum(rs):+7.1f} R | "
          f"stop median {md:4.0f} pts")

days = (R[-1]["time"] - R[0]["time"]) / 86400
print(f"{days:.0f} jours, spread {SPREAD:.0f} pts, TP {RR}R\n")
stats(main_tr, "STRUCTURE PRINCIPALE (actuelle)")
stats(int_tr, "structure interne, tout")
stats([x for x in int_tr if x["d"] == x["mtr"]],
      "structure interne, alignee")
stats([x for x in int_tr if x["d"] != x["mtr"]],
      "structure interne, contre")
print()
print(f"  cadence : principale {len(main_tr)/days:.1f} trades/jour, "
      f"interne alignee "
      f"{len([x for x in int_tr if x['d']==x['mtr']])/days:.1f}/jour")

# ---- is internal-aligned actually better than the main structure, or is
# the gap within the noise of two samples this size?
import random
A = [x["r"] for x in int_tr if x["d"] == x["mtr"]]
B = [x["r"] for x in main_tr]
real = sum(A)/len(A) - sum(B)/len(B)
pool = A + B; nA = len(A)
random.seed(23); hit = 0
for _ in range(4000):
    random.shuffle(pool)
    if (sum(pool[:nA])/nA - sum(pool[nA:])/len(pool[nA:])) >= real:
        hit += 1
print(f"\n  ecart interne-alignee moins principale : {real:+.3f} R")
print(f"  reproduit par le hasard : {hit}/4000 ({hit/4000:.1%})")
# and the per-half check
h = len(int_tr)//2; hm = len(main_tr)//2
f = lambda xs: sum(x['r'] for x in xs)/max(len(xs),1)
print(f"\n  1re moitie : interne alignee {f([x for x in int_tr[:h] if x['d']==x['mtr']]):+.3f}"
      f"  vs principale {f(main_tr[:hm]):+.3f}")
print(f"  2e moitie  : interne alignee {f([x for x in int_tr[h:] if x['d']==x['mtr']]):+.3f}"
      f"  vs principale {f(main_tr[hm:]):+.3f}")
