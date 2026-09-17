"""Is the internal gate result an artifact of how the internal window is
anchored? Same trades, same gate, two anchors:
  A) window starts at the main PROTECTED DOT's timestamp (what the live feed
     uses, and what INTERNAL_GATE.md measured)
  B) window starts at the main BREAK's timestamp
"""
import bisect, inspect, sys
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
src = inspect.getsource(F.engine)
src = src.replace("        lo_i, lo_v = i, l\n    # 2026-09-15",
                  "        lo_i, lo_v = i, l\n"
                  "        SNAP.append((t, trend))\n    # 2026-09-15")
src = src.replace("                    prot_lo = nd",
                  "                    prot_lo = nd; PD.append((t, nd[0], 1, nd[1]))")
src = src.replace("                    prot_hi = nd",
                  "                    prot_hi = nd; PD.append((t, nd[0], -1, nd[1]))")
src = src.replace("def engine(kept, snap=None, brk_out=None):",
                  "def engine_b(kept, snap=None, brk_out=None):", 1)
ns = {"SNAP": [], "PD": []}
exec(src, F.__dict__ | ns, ns)
ns["SNAP"].clear(); ns["PD"].clear()
ns["engine_b"](kept)
MAIN = list(ns["PD"])                   # (break_t, dot_t, dir, level)
SNAP = list(ns["SNAP"]); STT = [t for t, _ in SNAP]; ST = dict(SNAP)
def trend_at(t):
    i = bisect.bisect_right(STT, t) - 1
    return ST[STT[i]] if i >= 0 else 0
def walk(i0, d, entry, sl, tp):
    for r in R[i0 + 1:i0 + 6000]:
        if d == 1:
            if r["low"] <= sl: return -abs(entry - sl)
            if r["high"] >= tp: return abs(tp - entry)
        else:
            if r["high"] >= sl: return -abs(entry - sl)
            if r["low"] <= tp: return abs(tp - entry)
    return None
def run(anchor):
    T = []
    for j, (bt_, dt_, dir_, lvl_) in enumerate(MAIN):
        start = dt_ if anchor == "dot" else bt_
        seg_end = MAIN[j + 1][0] if j + 1 < len(MAIN) else R[-1]["time"]
        seg = [k for k in kept if start < k[0] <= seg_end]
        if len(seg) < 5: continue
        ns["PD"].clear()
        IB = []
        ns["engine_b"](seg, brk_out=IB)
        pds = list(ns["PD"])
        IBT = sorted(b[0] for b in IB)
        for k_, (ibt, idt, idir, ilvl) in enumerate(pds):
            mtr = trend_at(ibt)
            if not mtr or idir != mtr: continue
            i0 = raw_i.get(ibt)
            if i0 is None: continue
            e = R[i0]["close"] + (SPREAD if idir == 1 else -SPREAD)
            dist = abs(e - ilvl)
            if dist <= 10: continue
            p = walk(i0, idir, e, ilvl, e + idir * RR * dist)
            if p is None: continue
            nb = bisect.bisect_left(IBT, ibt) - bisect.bisect_left(IBT, ibt - 3600)
            T.append(dict(t=ibt, r=p / dist, nb=nb))
    T.sort(key=lambda x: x["t"])
    return T
def line(xs, name):
    if len(xs) < 10:
        print(f"  {name:<30s} n {len(xs):4d} (trop peu)"); return
    n = len(xs); rs = [x["r"] for x in xs]
    w = sum(1 for r in rs if r > 0) / n; e = sum(rs) / n
    h = n // 2
    e1 = sum(x["r"] for x in xs[:h]) / h; e2 = sum(x["r"] for x in xs[h:]) / (n - h)
    print(f"  {name:<30s} n {n:4d} | gagn {w:4.0%} | esp {e:+.3f} | "
          f"moities {e1:+.2f}/{e2:+.2f} "
          f"{'accord' if (e1>0)==(e2>0) else '  -'}")
for anc, nm in (("dot", "A) ancre sur le POINT protege"),
                ("brk", "B) ancre sur la CASSURE")):
    T = run(anc)
    print(f"\n{nm} : {len(T)} trades")
    line(T, "  reference")
    line([x for x in T if x["nb"] >= 1], "  porte : >=1 cassure en 1 h")
    line([x for x in T if x["nb"] == 0], "  rejetes")

# ---- combinations, judged under BOTH anchors. Only what holds in both is
# worth anything, after the anchor swing above.
print("\n" + "=" * 66)
print("  COMBINAISONS, exigees sous LES DEUX ancres")
MBT = sorted(b[0] for b in MAIN)
def run2(anchor):
    T = []
    for j, (bt_, dt_, dir_, lvl_) in enumerate(MAIN):
        start = dt_ if anchor == "dot" else bt_
        seg_end = MAIN[j + 1][0] if j + 1 < len(MAIN) else R[-1]["time"]
        seg = [k for k in kept if start < k[0] <= seg_end]
        if len(seg) < 5: continue
        ns["PD"].clear(); IB = []
        ns["engine_b"](seg, brk_out=IB)
        pds = list(ns["PD"]); IBT = sorted(b[0] for b in IB)
        for (ibt, idt, idir, ilvl) in pds:
            mtr = trend_at(ibt)
            if not mtr or idir != mtr: continue
            i0 = raw_i.get(ibt)
            if i0 is None: continue
            e = R[i0]["close"] + (SPREAD if idir == 1 else -SPREAD)
            dist = abs(e - ilvl)
            if dist <= 10: continue
            p = walk(i0, idir, e, ilvl, e + idir * RR * dist)
            if p is None: continue
            nb = bisect.bisect_left(IBT, ibt) - bisect.bisect_left(IBT, ibt-3600)
            mb = bisect.bisect_left(MBT, ibt) - bisect.bisect_left(MBT, ibt-7200)
            T.append(dict(t=ibt, r=p / dist, nb=nb, mb=mb))
    T.sort(key=lambda x: x["t"])
    return T
A, B = run2("dot"), run2("brk")
def cell(xs):
    if len(xs) < 10: return f"n {len(xs):3d}  --"
    n = len(xs); e = sum(x["r"] for x in xs) / n
    w = sum(1 for x in xs if x["r"] > 0) / n
    return f"n {n:3d}  {w:3.0%}  {e:+.3f}"
combos = [
    ("interne>=1 ET principale>=1", lambda x: x["nb"] >= 1 and x["mb"] >= 1),
    ("interne>=1 SEUL",             lambda x: x["nb"] >= 1 and x["mb"] == 0),
    ("principale>=1 SEUL",          lambda x: x["nb"] == 0 and x["mb"] >= 1),
    ("aucune des deux",             lambda x: x["nb"] == 0 and x["mb"] == 0),
    ("au moins l'une des deux",     lambda x: x["nb"] >= 1 or x["mb"] >= 1),
]
print(f"  {'combinaison':<30s} | {'ancre POINT':<20s} | ancre CASSURE")
for nm, fn in combos:
    print(f"  {nm:<30s} | {cell([x for x in A if fn(x)]):<20s} | "
          f"{cell([x for x in B if fn(x)])}")
