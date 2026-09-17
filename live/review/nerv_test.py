"""Is nervosity a decision input or decoration? Tested on aligned internal
trades under BOTH window anchors, which is now the standard after the gate
retraction. Spread cannot be tested: no historical spread is stored."""
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
rng = [r["high"] - r["low"] for r in R]
def nerv(i):
    a = rng[max(0, i - 60):i]
    b = rng[max(0, i - 1440):i]
    if len(a) < 20 or len(b) < 200: return None
    a = sorted(a); b = sorted(b)
    m1 = a[len(a) // 2]; m2 = b[len(b) // 2]
    return m1 / m2 if m2 > 0 else None
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
ns["SNAP"].clear(); ns["PD"].clear(); ns["engine_b"](kept)
MAIN = list(ns["PD"]); SNAP = list(ns["SNAP"])
STT = [t for t, _ in SNAP]; ST = dict(SNAP)
def trend_at(t):
    i = bisect.bisect_right(STT, t) - 1
    return ST[STT[i]] if i >= 0 else 0
def walk(i0, d, e, sl, tp):
    for r in R[i0 + 1:i0 + 6000]:
        if d == 1:
            if r["low"] <= sl: return -abs(e - sl)
            if r["high"] >= tp: return abs(tp - e)
        else:
            if r["high"] >= sl: return -abs(e - sl)
            if r["low"] <= tp: return abs(tp - e)
    return None
def run(anchor):
    T = []
    for j, (bt_, dt_, dir_, lvl_) in enumerate(MAIN):
        start = dt_ if anchor == "dot" else bt_
        seg_end = MAIN[j + 1][0] if j + 1 < len(MAIN) else R[-1]["time"]
        seg = [k for k in kept if start < k[0] <= seg_end]
        if len(seg) < 5: continue
        ns["PD"].clear(); IB = []
        ns["engine_b"](seg, brk_out=IB)
        for (ibt, idt, idir, ilvl) in list(ns["PD"]):
            if idir != trend_at(ibt) or not trend_at(ibt): continue
            i0 = raw_i.get(ibt)
            if i0 is None: continue
            nv = nerv(i0)
            if nv is None: continue
            e = R[i0]["close"] + (SPREAD if idir == 1 else -SPREAD)
            dist = abs(e - ilvl)
            if dist <= 10: continue
            p = walk(i0, idir, e, ilvl, e + idir * RR * dist)
            if p is None: continue
            T.append(dict(t=ibt, r=p / dist, nv=nv))
    T.sort(key=lambda x: x["t"])
    return T
def cell(xs):
    if len(xs) < 12: return f"n {len(xs):3d}   --"
    n = len(xs); e = sum(x["r"] for x in xs) / n
    w = sum(1 for x in xs if x["r"] > 0) / n
    return f"n {n:3d}  {w:3.0%}  {e:+.3f}"
A, B = run("dot"), run("brk")
print(f"\n{len(A)} / {len(B)} trades selon l'ancre\n")
print(f"  {'nervosite':<22s} | {'ancre POINT':<18s} | ancre CASSURE")
for lo, hi, nm in ((0, .8, "calme (<0.8x)"), (.8, 1.0, "0.8-1.0x"),
                   (1.0, 1.2, "1.0-1.2x"), (1.2, 99, "agite (>1.2x)")):
    print(f"  {nm:<22s} | {cell([x for x in A if lo<=x['nv']<hi]):<18s} | "
          f"{cell([x for x in B if lo<=x['nv']<hi])}")
print()
print(f"  {'garde si agite >1.2x':<22s} | {cell([x for x in A if x['nv']>1.2]):<18s} | "
      f"{cell([x for x in B if x['nv']>1.2])}")
print(f"  {'garde si calme <1.0x':<22s} | {cell([x for x in A if x['nv']<1.0]):<18s} | "
      f"{cell([x for x in B if x['nv']<1.0])}")
print(f"  {'tous (reference)':<22s} | {cell(A):<18s} | {cell(B)}")
