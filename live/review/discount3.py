"""An aligned break fires at the far end of the range by construction, so a
discount FILTER removes everything. The idea only means something as a
pullback ENTRY: after the break, wait for price to retrace into the
favourable half and enter there.

Arm A: enter at the break close (what we do today).
Arm B: enter on a retrace to the range midpoint.
Arm C: enter on a retrace one quarter of the way back (shallower).
All: stop at the internal protected level, target 0.8R, spread charged once.
A retrace that never comes = no trade."""
import bisect, inspect, sys
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
STT = [t for t, *_ in SNAP]
ST = {t: (tr, iv, nx) for t, tr, iv, nx in SNAP}
def state_at(t):
    i = bisect.bisect_right(STT, t) - 1
    return ST[STT[i]] if i >= 0 else (0, None, None)

def result(i0, d, entry, sl, tp, limit=None, wait=600):
    """If `limit` is set, wait for price to reach it first (up to `wait`
    bars); the stop must not be hit before the fill."""
    j = i0 + 1
    if limit is not None:
        hit = None
        for k in range(j, min(j + wait, len(R))):
            r = R[k]
            if d == -1 and r["high"] >= limit: hit = k; break
            if d == 1 and r["low"] <= limit: hit = k; break
            if d == -1 and r["high"] >= sl: return None
            if d == 1 and r["low"] <= sl: return None
        if hit is None: return None
        j = hit + 1
    for r in R[j:j + 6000]:
        if d == 1:
            if r["low"] <= sl: return -abs(entry - sl)
            if r["high"] >= tp: return abs(tp - entry)
        else:
            if r["high"] >= sl: return -abs(entry - sl)
            if r["low"] <= tp: return abs(tp - entry)
    return None

A, B, C = [], [], []
for j, (mt_, mdir, mprot, mdot) in enumerate(MAIN):
    seg_end = MAIN[j + 1][0] if j + 1 < len(MAIN) else R[-1]["time"]
    seg = [k for k in kept if mdot < k[0] <= seg_end]
    if len(seg) < 5: continue
    ns["BRK"].clear(); ns["SNAP"].clear(); ns["engine_b"](seg)
    for bt, d, lvl, _ in list(ns["BRK"]):
        mtr, miv, mnx = state_at(bt)
        if not mtr or miv is None or mnx is None or d != mtr: continue
        lo, hi = min(miv, mnx), max(miv, mnx)
        if hi - lo < 40: continue
        i0 = raw_i.get(bt)
        if i0 is None: continue
        px = R[i0]["close"]
        e0 = px + (SPREAD if d == 1 else -SPREAD)
        d0 = abs(e0 - lvl)
        if d0 > 10:
            p = result(i0, d, e0, lvl, e0 + d * RR * d0)
            if p is not None: A.append(p / d0)
        for frac, bucket in ((0.5, B), (0.25, C)):
            back = px + (hi - px) * frac if d == -1 else px - (px - lo) * frac
            e1 = back + (SPREAD if d == 1 else -SPREAD)
            d1 = abs(e1 - lvl)
            if d1 <= 10: continue
            if (d == -1 and e1 >= lvl) or (d == 1 and e1 <= lvl): continue
            p = result(i0, d, e1, lvl, e1 + d * RR * d1, limit=back)
            if p is not None: bucket.append(p / d1)

def stats(xs, name):
    if not xs:
        print(f"  {name:<40s} aucun"); return
    n = len(xs); w = sum(1 for r in xs if r > 0) / n; e = sum(xs) / n
    se = (sum((r - e) ** 2 for r in xs) / max(n - 1, 1)) ** .5 / n ** .5
    print(f"  {name:<40s} n {n:4d} | gagnants {w:4.0%} | "
          f"esperance {e:+.3f} R +/-{2*se:.3f} | total {sum(xs):+6.1f} R")

print(f"\n28 jours, trades internes ALIGNES\n")
stats(A, "A  entree a la cassure (actuel)")
stats(B, "B  entree sur repli a la moitie")
stats(C, "C  entree sur repli au quart")
