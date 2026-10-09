# Owner 2026-10-09 (2nd ask: ONLY during recovery mode): the REFERENCE account's Compte indicator as a gate for the
# real accounts: last progression candle GREEN = take the trade, RED = skip.
# 1) simulate the reference account (every signal, fixed 0.02, no debt
#    system, no bullets) and keep each trade's CLOSE time;
# 2) at every entry of the normal bot (live settings: jar on), rebuild the
#    reference progression from the trades closed BEFORE that moment, with
#    the live silence filter, and read the colour of the last shown candle.
import sys, bisect, random
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
import harness as H
from owl_chart_feed import build
sym, R = H.bars()

REF_CFG = {"n_cont": 999, "bullets": 0, "jar": False}
H.TRACE = []; fr = H.simulate(R, 7.0, REF_CFG); ref = [x for x in H.TRACE if x.get("pnl") is not None and x.get("tc")]; H.TRACE = None
ref.sort(key=lambda x: x["tc"])
TC = [x["tc"] for x in ref]
print("reference simulated: %d trades, net %.2f" % (len(ref), fr["net"]))
_cache = {}
def last_colour(t):
    n = bisect.bisect_left(TC, t)          # trades closed strictly before t
    if n in _cache: return _cache[n]
    raw, c = [], 0.0
    for i in range(n):
        o = c; c += ref[i]["pnl"]
        raw.append({"time": i + 1, "open": o, "high": max(o, c), "low": min(o, c), "close": c})
    k = build(raw)
    col = 0 if not k else (1 if k[-1][4] >= k[-1][1] else -1)
    _cache[n] = col
    return col
CNT = {"n": 0, "skip": 0}
def gate(want):
    def g(t, d):
        col = last_colour(t); CNT["n"] += 1
        ok = col == 0 or col == want
        CNT["skip"] += (not ok)
        return ok
    return g
LIVE = {"jar": True}
def pf(p):
    w = sum(x for x in p if x > 0); l = -sum(x for x in p if x < 0)
    return w / l if l else float("nan")
def run(g):
    H.DEBTGATE = g; v = H.run_cfg(R, 7.0, LIVE); H.DEBTGATE = None; return v
def row(name, v, base, extra=""):
    f = v["full"]
    print("%-34s trades %3d | win %4.1f%% | PF %.2f | net %8.2f | 1st half %8.2f | 2nd half %8.2f | worst drop %7.2f | %s %s" % (
        name, f["trades"], f["wr"], pf(f["pnls"]), f["net"], v["h1"]["net"], v["h2"]["net"], -f["worst_debt"],
        "-" if base is None else "verdict " + H.verdict(v, base), extra), flush=True)
NOLIM = dict(LIVE, n_cont=999)
def run2(g, cfg):
    H.DEBTGATE = g; v = H.run_cfg(R, 7.0, cfg); H.DEBTGATE = None; return v
v0 = run2(None, LIVE); row("today: recovery entry limit", v0, None)
vn = run2(None, NOLIM); row("every BOS in recovery, no control", vn, v0)
CNT.update(n=0, skip=0); vg = run2(gate(1), NOLIM); q = CNT["skip"] / max(1, CNT["n"])
row("every BOS, indicator decides (green)", vg, v0, "| skips %.0f%% of recovery signals" % (100 * q))
CNT.update(n=0, skip=0); vi = run2(gate(-1), NOLIM)
row("every BOS, opposite (red = go)", vi, v0)
nets, dds = [], []
for sd in range(20):
    r = random.Random(sd)
    H.DEBTGATE = lambda t, d, r=r: r.random() >= q
    f = H.simulate(R, 7.0, NOLIM); H.DEBTGATE = None
    nets.append(f["net"]); dds.append(f["worst_debt"])
nets.sort(); dds.sort()
print("random skipping in recovery, same rate, every BOS (20 runs): median net %.2f, median worst drop %.2f | indicator beats random: net %.0f%%, drop %.0f%%" % (
    nets[10], -dds[10], 100 * sum(1 for x in nets if x < vg["full"]["net"]) / 20, 100 * sum(1 for x in dds if x > vg["full"]["worst_debt"]) / 20))
