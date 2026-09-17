"""Symmetric test: BOTH structures, BOTH event types, THREE windows, on the
same 223 aligned internal trades. Then combinations."""
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
src = inspect.getsource(F.engine)
src = src.replace("        lo_i, lo_v = i, l\n    # 2026-09-15",
                  "        lo_i, lo_v = i, l\n"
                  "        SNAP.append((t, trend))\n    # 2026-09-15")
src = src.replace("def engine(kept, snap=None, brk_out=None):",
                  "def engine_b(kept, snap=None, brk_out=None):", 1)
ns = {"SNAP": []}
exec(src, F.__dict__ | ns, ns)
MB = []                                  # main BREAK times
ns["SNAP"].clear()
mdots, mmarks, *_ = ns["engine_b"](kept, brk_out=MB)
MF = [m[0] for m in mmarks if m[2] == "bos"]      # main FLIP times
SNAP = list(ns["SNAP"])
STT = [t for t, _ in SNAP]; ST = dict(SNAP)
def trend_at(t):
    i = bisect.bisect_right(STT, t) - 1
    return ST[STT[i]] if i >= 0 else 0
MBT = sorted(b[0] for b in MB)
def count(arr, t, w):
    return bisect.bisect_left(arr, t) - bisect.bisect_left(arr, t - w)
def walk(i0, d, entry, sl, tp):
    for r in R[i0 + 1:i0 + 6000]:
        if d == 1:
            if r["low"] <= sl: return -abs(entry - sl)
            if r["high"] >= tp: return abs(tp - entry)
        else:
            if r["high"] >= sl: return -abs(entry - sl)
            if r["low"] <= tp: return abs(tp - entry)
    return None
# segments from main breaks
MBfull = sorted(MB)
T = []
for j, (mt_, mdir) in enumerate(MBfull):
    seg_end = MBfull[j + 1][0] if j + 1 < len(MBfull) else R[-1]["time"]
    seg = [k for k in kept if mt_ < k[0] <= seg_end]
    if len(seg) < 5: continue
    IB = []
    idots, imarks, *_ = ns["engine_b"](seg, brk_out=IB)
    IBT = sorted(b[0] for b in IB)
    IFT = sorted(m[0] for m in imarks if m[2] == "bos")
    for bt, d in IB:
        mtr = trend_at(bt)
        if not mtr or d != mtr: continue
        i0 = raw_i.get(bt)
        if i0 is None: continue
        # the protected level at that break
        lvl = None
        for dd in idots:
            if dd[0] <= bt: lvl = dd[1]
        if lvl is None: continue
        e = R[i0]["close"] + (SPREAD if d == 1 else -SPREAD)
        dist = abs(e - lvl)
        if dist <= 10: continue
        p = walk(i0, d, e, lvl, e + d * RR * dist)
        if p is None: continue
        rec = dict(t=bt, r=p / dist, d=d, dist=dist)
        for w, nm in ((3600, "1h"), (7200, "2h"), (14400, "4h")):
            rec["ib" + nm] = count(IBT, bt, w)
            rec["if" + nm] = count(IFT, bt, w)
            rec["mb" + nm] = count(MBT, bt, w)
            rec["mf" + nm] = count(sorted(MF), bt, w)
        T.append(rec)
T.sort(key=lambda x: x["t"])
def line(xs, name):
    if len(xs) < 10:
        print(f"  {name:<36s} n {len(xs):4d}  (trop peu)"); return None
    n = len(xs); rs = [x["r"] for x in xs]
    w = sum(1 for r in rs if r > 0) / n; e = sum(rs) / n
    h = n // 2
    e1 = sum(x["r"] for x in xs[:h]) / h
    e2 = sum(x["r"] for x in xs[h:]) / (n - h)
    print(f"  {name:<36s} n {n:4d} | gagn {w:4.0%} | esp {e:+.3f} | "
          f"moities {e1:+.2f}/{e2:+.2f} "
          f"{'accord' if (e1>0)==(e2>0) else '  -'}")
    return e
print(f"{len(T)} trades alignes, 42 jours\n")
line(T, "REFERENCE")
print("\n  PORTES SIMPLES (garde si >= 1 evenement)")
for st, sn in (("i", "interne"), ("m", "principale")):
    for ev, en in (("b", "cassures"), ("f", "flips")):
        for w in ("1h", "2h", "4h"):
            k = st + ev + w
            line([x for x in T if x[k] >= 1], f"  {sn} {en} {w}")
