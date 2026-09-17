"""The full rule set, one filter at a time, under BOTH window anchors.
Aligned -> activity gate -> nervosity veto. Trades, win rate, expectancy,
total R and trades per day."""
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
DAYS = (R[-1]["time"] - R[0]["time"]) / 86400
kept = F.build(R)
raw_i = {r["time"]: i for i, r in enumerate(R)}
rng = [r["high"] - r["low"] for r in R]
def nerv(i):
    a = sorted(rng[max(0, i-60):i]); b = sorted(rng[max(0, i-1440):i])
    if len(a) < 20 or len(b) < 200: return None
    m2 = b[len(b)//2]
    return (a[len(a)//2] / m2) if m2 > 0 else None
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
    for r in R[i0+1:i0+6000]:
        if d == 1:
            if r["low"] <= sl: return -abs(e-sl)
            if r["high"] >= tp: return abs(tp-e)
        else:
            if r["high"] >= sl: return -abs(e-sl)
            if r["low"] <= tp: return abs(tp-e)
    return None
def run(anchor):
    T = []
    for j, (bt_, dt_, dir_, lvl_) in enumerate(MAIN):
        start = dt_ if anchor == "dot" else bt_
        seg_end = MAIN[j+1][0] if j+1 < len(MAIN) else R[-1]["time"]
        seg = [k for k in kept if start < k[0] <= seg_end]
        if len(seg) < 5: continue
        ns["PD"].clear(); IB = []
        ns["engine_b"](seg, brk_out=IB)
        IBT = sorted(b[0] for b in IB)
        for (ibt, idt, idir, ilvl) in list(ns["PD"]):
            mtr = trend_at(ibt)
            i0 = raw_i.get(ibt)
            if i0 is None: continue
            nv = nerv(i0)
            e = R[i0]["close"] + (SPREAD if idir == 1 else -SPREAD)
            dist = abs(e - ilvl)
            if dist <= 10: continue
            p = walk(i0, idir, e, ilvl, e + idir*RR*dist)
            if p is None: continue
            nb = bisect.bisect_left(IBT, ibt) - bisect.bisect_left(IBT, ibt-3600)
            T.append(dict(t=ibt, r=p/dist, al=(mtr != 0 and idir == mtr),
                          nb=nb, nv=nv))
    T.sort(key=lambda x: x["t"])
    return T
def row(xs, name):
    if not xs:
        print(f"  {name:<34s} aucun"); return
    n = len(xs); rs = [x["r"] for x in xs]
    w = sum(1 for r in rs if r > 0)/n; e = sum(rs)/n
    print(f"  {name:<34s} n {n:4d} | {n/DAYS:4.1f}/j | gagn {w:4.0%} | "
          f"esp {e:+.3f} | total {sum(rs):+7.1f} R")
for anc, nm in (("dot", "ANCRE = point protege (le flux en direct)"),
                ("brk", "ANCRE = cassure (le controle)")):
    T = run(anc)
    print(f"\n{nm} — {DAYS:.0f} jours")
    row(T, "0. toutes les cassures internes")
    a1 = [x for x in T if x["al"]]
    row(a1, "1. + sens de la grande tendance")
    a2 = [x for x in a1 if x["nb"] >= 1]
    row(a2, "2. + au moins 1 mouvement en 1 h")
    a3 = [x for x in a2 if x["nv"] is not None and x["nv"] <= 1.0]
    row(a3, "3. + nervosite <= 1.0x  (REGLE FINALE)")
