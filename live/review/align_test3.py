"""Does the MAIN trend predict INTERNAL trade outcomes?
One engine run per main segment, so it finishes. Entry at the break close
plus spread, stop at the protected level it creates, target 0.8R, exits
walked on raw M1 with the stop checked first."""
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

ns["BRK"].clear(); ns["engine_b"](kept)
MAIN = list(ns["BRK"])                       # (t, dir, level, dot_time)
print(f"structure principale : {len(MAIN)} cassures sur "
      f"{(R[-1]['time']-R[0]['time'])/86400:.0f} jours")

def exit_trade(i0, d, entry, sl, tp):
    for r in R[i0 + 1:i0 + 6000]:
        if d == 1:
            if r["low"] <= sl: return -abs(entry - sl)
            if r["high"] >= tp: return abs(tp - entry)
        else:
            if r["high"] >= sl: return -abs(entry - sl)
            if r["low"] <= tp: return abs(tp - entry)
    return None

trades = []
t0 = time.time()
for j, (mt_, mdir, mlvl, mdot) in enumerate(MAIN):
    seg_end = MAIN[j + 1][0] if j + 1 < len(MAIN) else R[-1]["time"]
    seg = [k for k in kept if mdot < k[0] <= seg_end]
    if len(seg) < 5:
        continue
    ns["BRK"].clear()
    ns["engine_b"](seg)
    for bt, d, lvl, _dt in ns["BRK"]:
        i0 = raw_i.get(bt)
        if i0 is None: continue
        entry = R[i0]["close"] + (SPREAD if d == 1 else -SPREAD)
        dist = abs(entry - lvl)
        if dist <= 10: continue
        tp = entry + d * RR * dist
        pnl = exit_trade(i0, d, entry, lvl, tp)
        if pnl is not None:
            trades.append(dict(t=bt, d=d, mtr=mdir, r=pnl / dist))
print(f"simulation en {time.time()-t0:.0f}s\n")

def stats(xs, name):
    if not xs:
        print(f"  {name:<26s} aucun"); return
    n = len(xs); w = sum(1 for x in xs if x > 0) / n; e = sum(xs) / n
    se = (sum((x - e) ** 2 for x in xs) / max(n - 1, 1)) ** .5 / n ** .5
    print(f"  {name:<26s} n {n:5d}  gagnants {w:4.0%}  "
          f"esperance {e:+.3f} R  +/-{2*se:.3f}")

trades.sort(key=lambda x: x["t"])
h = len(trades) // 2
print(f"{len(trades)} trades internes simules\n")
stats([x["r"] for x in trades], "TOUS")
print()
stats([x["r"] for x in trades if x["d"] == x["mtr"]], "ALIGNES sur la principale")
stats([x["r"] for x in trades if x["d"] != x["mtr"]], "CONTRE la principale")
print("\n  premiere moitie")
stats([x["r"] for x in trades[:h] if x["d"]==x["mtr"]], "  alignes")
stats([x["r"] for x in trades[:h] if x["d"]!=x["mtr"]], "  contre")
print("  seconde moitie")
stats([x["r"] for x in trades[h:] if x["d"]==x["mtr"]], "  alignes")
stats([x["r"] for x in trades[h:] if x["d"]!=x["mtr"]], "  contre")

# ---- control: is the split bigger than chance? Shuffle the ALIGNED label
# 2000 times and see how often a gap this large appears by luck.
import random
lab = [1 if x["d"] == x["mtr"] else 0 for x in trades]
val = [x["r"] for x in trades]
def gap(lb):
    a = [v for v, l in zip(val, lb) if l]
    c = [v for v, l in zip(val, lb) if not l]
    if not a or not c: return 0.0
    return sum(a)/len(a) - sum(c)/len(c)
real = gap(lab)
random.seed(17)
worse = 0
for _ in range(2000):
    random.shuffle(lab)
    if gap(lab) >= real:
        worse += 1
print(f"\n  ecart reel aligne - contre : {real:+.3f} R")
print(f"  melanges au hasard faisant aussi bien : {worse}/2000 "
      f"({worse/2000:.1%})")
print("  -> " + ("le hasard reproduit cet ecart trop souvent"
                 if worse/2000 > 0.05 else
                 "le hasard ne reproduit cet ecart que rarement"))
