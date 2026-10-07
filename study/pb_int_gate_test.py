# Owner 2026-10-07: with internal structure on the pullback chart, when price
# closes beyond (or just touches) a pullback-chart BOS / CHoCH level, accept the
# M1 silence-chart trades going the same way as that breakout.
# The pb chart (+ its internal structure, stateful pin like live) is rebuilt
# every STEP minutes from closed bars only; the levels in force at that moment
# are then watched on the next STEP M1 bars. Causal: levels known before the
# bars that hit them.
import sys, os, time, pickle, random, datetime as dt
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
import harness as H
sym, R = H.bars(); F = H._feed()
HERE = r"C:\Users\ADMINI~1\AppData\Local\Temp\2\claude\C--Users-Administrator--local-bin\b61e52db-3e75-4c34-a894-1952c9c0ef5a\scratchpad"
EV = os.path.join(HERE, "pbint_events.pkl")
RAW, STEP = 8000, 2
T = [int(r["time"]) for r in R]
HI = [float(r["high"]) for r in R]; LO = [float(r["low"]) for r in R]; CL = [float(r["close"]) for r in R]

if os.path.exists(EV):
    events = pickle.load(open(EV, "rb"))
else:
    F._PB_PIN.update({"t0": None, "start": None})
    events = []                      # (t, dir, kind 'main'/'int', how 'touch'/'close', level)
    t0 = time.time()
    for g in range(RAW, len(R) - 1, STEP):
        kept = F.build(R[g - RAW + 1:g + 1]); bk = []
        dots, marks, trend, *_ = F.engine(kept, brk_out=bk)
        if trend: dots = [d for d in dots if d[2] == trend]
        try:
            pb = F.pullback_view(kept, dots, marks, bk)
        except Exception:
            pb = None
        if not pb: continue
        px = CL[g]
        lv = [(pb.get(k), "main") for k in ("next_bos", "invalid", "flip_bos")] + \
             [(pb.get(k), "int") for k in ("int_bos", "int_inv", "int_flip_bos")]
        lv = [(float(v), kd) for v, kd in lv if v]
        done = set()
        for j in range(g + 1, min(g + 1 + STEP, len(R))):
            for v, kd in lv:
                d = 1 if v > px else -1
                if (v, "touch") not in done and ((d == 1 and HI[j] >= v) or (d == -1 and LO[j] <= v)):
                    events.append((T[j], d, kd, "touch", v)); done.add((v, "touch"))
                if (v, "close") not in done and ((d == 1 and CL[j] > v) or (d == -1 and CL[j] < v)):
                    events.append((T[j], d, kd, "close", v)); done.add((v, "close"))
        if (g // STEP) % 2000 == 0:
            print("  built to", dt.datetime.utcfromtimestamp(T[g]), "events", len(events), "%.0fs" % (time.time() - t0), flush=True)
    pickle.dump(events, open(EV, "wb"))
print("events", len(events))

def timeline(kinds, how):
    return sorted((t, d) for t, d, kd, hw, _ in events if kd in kinds and hw == how)
import bisect
def gate(kinds, how, W=None):
    tl = timeline(kinds, how); ts = [x[0] for x in tl]
    def g(t, d):
        i = bisect.bisect_right(ts, t) - 1
        if i < 0: return False
        if W is None: return tl[i][1] == d          # last event's direction, until an opposite one
        k = i                                        # any same-direction event in the last W min
        while k >= 0 and t - tl[k][0] <= W * 60:
            if tl[k][1] == d: return True
            k -= 1
        return False
    return g

T27 = int(dt.datetime(2026, 9, 27, tzinfo=dt.timezone.utc).timestamp())
def stats(p):
    if not p: return dict(n=0, wr=0, net=0, dd=0, pf=0)
    w = [x for x in p if x > 0]; l = [x for x in p if x < 0]
    c = pk = dd = 0
    for x in p: c += x; pk = max(pk, c); dd = min(dd, c - pk)
    return dict(n=len(p), wr=100 * len(w) / len(p), net=sum(p), dd=dd, pf=(sum(w) / -sum(l)) if l else 9.99)
M, MI = ("main",), ("main", "int")
RULES = [("base", None),
         ("close main, until opposite", gate(M, "close")), ("close main+int, until opposite", gate(MI, "close")),
         ("touch main, until opposite", gate(M, "touch")), ("touch main+int, until opposite", gate(MI, "touch")),
         ("close main+int, <=60m", gate(MI, "close", 60)), ("touch main+int, <=60m", gate(MI, "touch", 60))]
res = {}
for name, g in RULES:
    H.DIRGATE = g; H.TRACE = []
    H.simulate(R, 7.0, {}); tr = [x for x in H.TRACE if x["pnl"] is not None]; H.TRACE = None
    H.DIRGATE = g
    v = H.run_cfg(R, 7.0, {}); H.DIRGATE = None
    res[name] = v; f = v["full"]
    if name == "base": base_tr = tr
    s = stats([x["pnl"] for x in tr if x["t"] >= T27])
    print("%-32s ALL: n %3d net %8.2f h1 %7.2f h2 %7.2f worst %7.2f wr %4.1f %-3s | SINCE 27/9: n %3d win %4.1f%% net %7.2f DD %7.2f PF %.2f"
          % (name, f["trades"], f["net"], v["h1"]["net"], v["h2"]["net"], f["worst_debt"], f["wr"],
             "-" if name == "base" else H.verdict(v, res["base"]), s["n"], s["wr"], s["net"], s["dd"], s["pf"]), flush=True)

print("\nSecond way: base trades kept by each gate vs 2000 random subsets of the same size")
random.seed(7); P = [x["pnl"] for x in base_tr]
for name, g in RULES[1:]:
    keep = [x["pnl"] for x in base_tr if g(x["t"], x["d"])]
    if not keep: print("  %-32s none kept" % name); continue
    k = len(keep); s = sum(keep)
    sims = [sum(random.sample(P, k)) for _ in range(2000)]
    pct = 100 * sum(1 for z in sims if z < s) / len(sims)
    print("  %-32s kept %3d of %d  net %7.2f  per trade %+.2f (all %+.2f)  random percentile %3.0f"
          % (name, k, len(P), s, s / k, sum(P) / len(P), pct))
from collections import Counter
c = Counter((kd, hw) for _, _, kd, hw, _ in events)
print("event counts", dict(c))
