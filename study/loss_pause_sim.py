# Owner 2026-10-08: the loss-pause rule INSIDE the bot simulation, so virtual
# trades book nothing (money, debt, reserve, streak, recovery adds) and the
# debt-driven behaviour reacts as it would live.
import sys, random
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
import harness as H
sym, R = H.bars()
def run(lp):
    H.LOSSPAUSE = lp; H.TRACE = []
    f = H.simulate(R, 7.0, {}); tr = H.TRACE; H.TRACE = None
    v = H.run_cfg(R, 7.0, {}); H.LOSSPAUSE = False
    return f, v, tr
f0, v0, tr0 = run(False)
print("check off == before: net", f0["net"], "trades", f0["trades"])
f1, v1, tr1 = run(True)
real = [x for x in tr1 if x["pnl"] is not None and not x.get("virt")]
virt = [x for x in tr1 if x["pnl"] is not None and x.get("virt")]
print("sanity: real pnl sum %.2f vs net %.2f" % (sum(x["pnl"] for x in real), f1["net"]))
def row(name, v, f, extra=""):
    print("%-26s net %8.2f | 1st half %8.2f 2nd half %8.2f | worst drop %7.2f | real %3d virtual %3d %s" % (
        name, v["full"]["net"], v["h1"]["net"], v["h2"]["net"], -v["full"]["worst_debt"], f["trades"] - f.get("virtual", 0), f.get("virtual", 0), extra))
row("normal bot", v0, f0)
row("loss-pause (simulated)", v1, f1, "verdict " + H.verdict(v1, v0))
print("virtual trades: %d, would-be net %.2f, win %.0f%%" % (len(virt), sum(x["pnl"] for x in virt), 100 * sum(1 for x in virt if x["pnl"] > 0) / max(1, len(virt))))
q = f1["virtual"] / max(1, f1["trades"])
nets, dds = [], []
for s in range(40):
    rnd = random.Random(s)
    vr = run(lambda win, r=rnd: r.random() < q)[1]
    nets.append(vr["full"]["net"]); dds.append(vr["full"]["worst_debt"])
nets.sort(); dds.sort()
pn = 100 * sum(1 for x in nets if x < v1["full"]["net"]) / len(nets)
pd = 100 * sum(1 for x in dds if x > v1["full"]["worst_debt"]) / len(dds)
print("random pauses at the same rate (%.0f%%), 40 runs: net median %.2f, worst drop median %.2f" % (100 * q, nets[20], -dds[20]))
print("loss-pause beats random on net in %.0f%% of runs, on worst drop in %.0f%%" % (pn, pd))
