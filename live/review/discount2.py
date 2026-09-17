"""Same idea, correct range. The main range is the protected level (the
diamond) to the level the next break must take out - and BOTH move on every
trigger, not only when a dot is created. Record them at every candle."""
import inspect, sys
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
# snapshot the main state at the END of every candle
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
ns["BRK"].clear(); ns["SNAP"].clear()
ns["engine_b"](kept)
MAIN, SNAP = list(ns["BRK"]), list(ns["SNAP"])
print(f"{len(SNAP)} instantanes de la structure principale, "
      f"{len(MAIN)} cassures")
ST = {t: (tr, iv, nx) for t, tr, iv, nx in SNAP}
STT = [t for t, *_ in SNAP]
import bisect
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

trades = []
for j, (mt_, mdir, mprot, mdot) in enumerate(MAIN):
    seg_end = MAIN[j + 1][0] if j + 1 < len(MAIN) else R[-1]["time"]
    seg = [k for k in kept if mdot < k[0] <= seg_end]
    if len(seg) < 5: continue
    ns["BRK"].clear(); ns["SNAP"].clear()
    ns["engine_b"](seg)
    for bt, d, lvl, _ in list(ns["BRK"]):
        mtr, miv, mnx = state_at(bt)
        if not mtr or miv is None or mnx is None: continue
        if d != mtr: continue
        lo, hi = min(miv, mnx), max(miv, mnx)
        if hi - lo < 40: continue
        i0 = raw_i.get(bt)
        if i0 is None: continue
        entry = R[i0]["close"] + (SPREAD if d == 1 else -SPREAD)
        dist = abs(entry - lvl)
        if dist <= 10: continue
        p = walk(i0, d, entry, lvl, entry + d * RR * dist)
        if p is None: continue
        pos = (entry - lo) / (hi - lo)
        fav = (pos > 0.5) if mtr == -1 else (pos < 0.5)
        trades.append(dict(t=bt, r=p / dist, fav=fav, pos=pos,
                           width=hi - lo))

def stats(xs, name):
    if not xs:
        print(f"  {name:<32s} aucun"); return
    n = len(xs); rs = [x["r"] for x in xs]
    w = sum(1 for r in rs if r > 0) / n; e = sum(rs) / n
    se = (sum((r - e) ** 2 for r in rs) / max(n - 1, 1)) ** .5 / n ** .5
    print(f"  {name:<32s} n {n:4d} | gagnants {w:4.0%} | "
          f"esperance {e:+.3f} R +/-{2*se:.3f} | total {sum(rs):+6.1f} R")

trades.sort(key=lambda x: x["t"])
ins = [x for x in trades if 0 <= x["pos"] <= 1]
print(f"\n{len(trades)} trades alignes, dont {len(ins)} "
      f"dans la fourchette ({len(ins)/max(len(trades),1):.0%}), "
      f"largeur mediane {sorted(x['width'] for x in trades)[len(trades)//2]:.0f} pts\n")
stats(trades, "tous les alignes")
stats([x for x in trades if x["fav"]], "moitie FAVORABLE (l'idee)")
stats([x for x in trades if not x["fav"]], "moitie opposee (temoin)")
h = len(trades) // 2
print("\n  par moitie de l'echantillon")
stats([x for x in trades[:h] if x["fav"]], "  favorable, 1re")
stats([x for x in trades[h:] if x["fav"]], "  favorable, 2e")
stats([x for x in trades[:h] if not x["fav"]], "  opposee, 1re")
stats([x for x in trades[h:] if not x["fav"]], "  opposee, 2e")
