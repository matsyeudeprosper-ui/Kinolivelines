# Owner 2026-10-07: take the M1 (silence) BOS trades only when price
# reaches / hits a BOS level of the pullback chart.
# Reading A "hit": the pb chart broke a BOS level in the trade's direction
#   within the last W minutes (price reached the pb level and closed beyond).
# Reading B "retest": entry price is within TOL pts of a pb BOS level
#   broken in the last 24h (price came back to the level), any side.
import os, pickle, random, datetime as dt
OLD = r"C:\Users\Administrator\AppData\Local\Temp\2\claude\C--Users-Administrator--local-bin\d0f3d5ec-64a9-4f73-81c4-6f2d05427fd0\scratchpad"
os.chdir(OLD)
exec(open("pbdir.py").read().split("def mk(rule)")[0])
HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else "."
CF = os.path.join(r"C:\Users\ADMINI~1\AppData\Local\Temp\2\claude\C--Users-Administrator--local-bin\b61e52db-3e75-4c34-a894-1952c9c0ef5a\scratchpad", "pbhit_bk.pkl")
BK = pickle.load(open(CF, "rb")) if os.path.exists(CF) else {}
CLOSE = {int(r["time"]): float(r["close"]) for r in R}

def pb_breaks(t):
    if t in BK: return BK[t]
    i = IDX[t]
    kept = F.build(R[max(0, i + 1 - RAW):i + 1])
    brk = []
    (dots, marks, trend, choch, nxt, inv, nxt_t, inv_t, _d, flp, flp_t, fd) = F.engine(kept, brk_out=brk)
    if trend == 1: dots = [x for x in dots if x[2] == 1]
    elif trend == -1: dots = [x for x in dots if x[2] == -1]
    want = {x[0] for x in dots} | {m[0] for m in marks} | {b[0] for b in brk}
    want.add(kept[-1][0])
    chain = F.pb_join(F.pb_quiet(F.pb_join([c for c in kept if c[0] in want])))
    bk = []
    F.engine(chain, brk_out=bk)
    BK[t] = [(int(b[0]), int(b[1]), float(b[2])) for b in bk]
    return BK[t]

def hit(W):
    return lambda t, d: any(bd == d and 0 <= t - bt <= W * 60 for bt, bd, _ in pb_breaks(t))
def retest(TOL):
    def g(t, d):
        px = CLOSE[t]
        return any(t - bt <= 86400 and t - bt > 600 and abs(px - lv) <= TOL for bt, bd, lv in pb_breaks(t))
    return g

T0 = int(dt.datetime(2026, 9, 27, tzinfo=dt.timezone.utc).timestamp())
def stats(p):
    if not p: return dict(n=0, wr=0, net=0, dd=0, pf=0)
    w = [x for x in p if x > 0]; l = [x for x in p if x < 0]
    c = pk = dd = 0
    for x in p:
        c += x; pk = max(pk, c); dd = min(dd, c - pk)
    return dict(n=len(p), wr=100 * len(w) / len(p), net=sum(p), dd=dd, pf=(sum(w) / -sum(l)) if l else 9.99)

RULES = [("base", None),
         ("A hit same dir <=15m", hit(15)), ("A hit same dir <=60m", hit(60)), ("A hit same dir <=240m", hit(240)),
         ("B back at pb level +-20", retest(20)), ("B back at pb level +-50", retest(50))]
res = {}; base_tr = None
for name, g in RULES:
    H.DIRGATE = g; H.TRACE = []
    v = H.run_cfg(R, 7.0, {}); tr = [x for x in H.TRACE if x["pnl"] is not None]; H.TRACE = None
    res[name] = v; f = v["full"]
    if name == "base": base_tr = tr
    s = stats([x["pnl"] for x in tr if x["t"] >= T0])
    print("%-24s ALL: n %3d net %8.2f h1 %7.2f h2 %7.2f worst %7.2f wr %4.1f %-3s | SINCE 27/9: n %3d win %4.1f%% net %7.2f DD %7.2f PF %.2f"
          % (name, f["trades"], f["net"], v["h1"]["net"], v["h2"]["net"], f["worst_debt"], f["wr"],
             "-" if name == "base" else H.verdict(v, res["base"]), s["n"], s["wr"], s["net"], s["dd"], s["pf"]), flush=True)
    pickle.dump(BK, open(CF, "wb"))

# second way: on the BASE trades, does the gate pick better trades than random?
print("\nSecond way: base trades kept by each gate vs 2000 random subsets of the same size")
random.seed(7)
P = [x["pnl"] for x in base_tr]
for name, g in RULES[1:]:
    keep = [x["pnl"] for x in base_tr if g(x["t"], x["d"])]
    if not keep: print("  %-24s none kept" % name); continue
    k = len(keep); s = sum(keep)
    sims = sorted(sum(random.sample(P, k)) for _ in range(2000))
    pct = 100 * sum(1 for z in sims if z < s) / len(sims)
    print("  %-24s kept %3d of %d  net %7.2f  per trade %+.2f (all %+.2f)  random percentile %3.0f"
          % (name, k, len(P), s, s / k, sum(P) / len(P), pct))
