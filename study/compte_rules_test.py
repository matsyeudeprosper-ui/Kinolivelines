# Owner 2026-10-08: the Compte indicator as a BOT rule, on the replay.
# The progression chart is rebuilt from the bot's own simulated trades (all
# trades, real + virtual, at full size) with the SAME filter + engine + cold
# start windows as the live worker. Rules:
#   #1 half lot while the results are in a downtrend
#   #5 trade virtually while the results are in a downtrend
# each also in an "until CHoCH up" form, against random halvings / pauses at
# the same rate.
import sys, random
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
import harness as H
from owl_chart_feed import build, engine
sym, R = H.bars()

def state(P):
    raw, cum, t = [], 0.0, 0
    for p in P:
        o = cum; cum += p; t += 1
        raw.append({"time": t, "open": o, "high": max(o, cum), "low": min(o, cum), "close": cum})
    k = build(raw)
    if len(k) < 3:
        return 0, 0
    for w in (len(k), 120, 80, 50, 30, 20):
        out = engine(k[-w:], brk_out=[])
        if out[2]:
            return out[2], out[3]
    return 0, 0

CNT = {"n": 0, "hit": 0}
def rule(kind, until_choch):
    def f(P):
        tr, ch = state(P)
        on = tr == -1 and not (until_choch and ch == 1)
        CNT["n"] += 1; CNT["hit"] += on
        if not on: return 1.0, False
        return (0.5, False) if kind == "half" else (1.0, True)
    return f
def rnd(kind, q, seed):
    r = random.Random(seed)
    def f(P):
        on = r.random() < q
        if not on: return 1.0, False
        return (0.5, False) if kind == "half" else (1.0, True)
    return f

def run(hook):
    H.EQHOOK = hook
    v = H.run_cfg(R, 7.0, {})
    f = H.simulate(R, 7.0, {})
    H.EQHOOK = None
    return v, f
v0, f0 = run(None)
def row(name, v, f, extra=""):
    print("%-34s net %8.2f | 1st half %8.2f 2nd half %8.2f | worst drop %7.2f | trades real %3d virtual %3d %s" % (
        name, v["full"]["net"], v["h1"]["net"], v["h2"]["net"], -v["full"]["worst_debt"],
        f["trades"] - f.get("virtual", 0), f.get("virtual", 0), extra), flush=True)
row("normal bot", v0, f0)
res = {}
for name, kind, uc in (("#1 half lot in downtrend", "half", False), ("#1b half lot until CHoCH up", "half", True),
                       ("#5 virtual in downtrend", "virt", False), ("#5b virtual until CHoCH up", "virt", True)):
    CNT.update(n=0, hit=0)
    v, f = run(rule(kind, uc))
    q = CNT["hit"] / max(1, CNT["n"])
    res[name] = (v, f, q, kind)
    row(name, v, f, "| on %.0f%% of entries | verdict %s" % (100 * q, H.verdict(v, v0)))
print("\nRandom controls (same rate, 20 seeds, full period):", flush=True)
for name, (v, f, q, kind) in res.items():
    nets, dds = [], []
    for sd in range(20):
        H.EQHOOK = rnd(kind, q, sd); g = H.simulate(R, 7.0, {}); H.EQHOOK = None
        nets.append(g["net"]); dds.append(g["worst_debt"])
    nets.sort(); dds.sort()
    pn = 100 * sum(1 for x in nets if x < v["full"]["net"]) / 20
    pd = 100 * sum(1 for x in dds if x > v["full"]["worst_debt"]) / 20
    print("  %-34s random median net %8.2f drop %7.2f | rule beats random: net %3.0f%%  drop %3.0f%%" % (
        name, nets[10], -dds[10], pn, pd), flush=True)
