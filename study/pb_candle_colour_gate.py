# Owner 2026-10-09: the PULLBACK ("reculs") chart's last closed candle as a
# direction gate for the M1 silence-chart trades: bullish -> buys only,
# bearish -> sells only. Live settings (jar on), replay 60000 bars.
#   a) last pullback candle INCLUDING the signal bar
#   b) last pullback candle closed BEFORE the signal bar
import sys, random
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
import harness as H
sym, R = H.bars()
F = H._feed()
IDX = {int(r["time"]): i for i, r in enumerate(R)}
RAW = 8000
CACHE = {}
def pb_last_dir(i):
    if i in CACHE: return CACHE[i]
    kept = F.build(R[max(0, i + 1 - RAW):i + 1])
    brk = []
    dots, marks, trend, *_ = F.engine(kept, brk_out=brk)
    if trend: dots = [x for x in dots if x[2] == trend]
    want = {x[0] for x in dots} | {m[0] for m in marks} | {b[0] for b in brk}
    if kept: want.add(kept[-1][0])
    ch = F.pb_join(F.pb_quiet(F.pb_join([c for c in kept if c[0] in want])))
    v = 0 if not ch else (1 if ch[-1][4] >= ch[-1][1] else -1)
    CACHE[i] = v
    return v
CNT = {"n": 0, "skip": 0}
def gate(before, invert=False):
    def g(t, d):
        i = IDX.get(t)
        if i is None: return True
        col = pb_last_dir(i - 1 if before else i)
        ok = col == 0 or (col == d) != invert
        CNT["n"] += 1; CNT["skip"] += (not ok)
        return ok
    return g
LIVE = {"jar": True}
def pf(p):
    w = sum(x for x in p if x > 0); l = -sum(x for x in p if x < 0)
    return w / l if l else float("nan")
def run(g):
    H.DIRGATE = g; v = H.run_cfg(R, 7.0, LIVE); H.DIRGATE = None; return v
def row(name, v, base, extra=""):
    f = v["full"]
    print("%-44s trades %3d | win %4.1f%% | PF %.2f | net %8.2f | 1st half %8.2f | 2nd half %8.2f | worst drop %7.2f | %s %s" % (
        name, f["trades"], f["wr"], pf(f["pnls"]), f["net"], v["h1"]["net"], v["h2"]["net"], -f["worst_debt"],
        "-" if base is None else "verdict " + H.verdict(v, base), extra), flush=True)
v0 = run(None); row("normal bot (live settings)", v0, None)
for before, lab in ((False, "a) incl. signal candle"), (True, "b) candle closed before the signal")):
    CNT.update(n=0, skip=0); vg = run(gate(before)); q = CNT["skip"] / max(1, CNT["n"])
    row(lab + ": same colour = go", vg, v0, "| skips %.0f%%" % (100 * q))
    CNT.update(n=0, skip=0); vi = run(gate(before, True))
    row(lab + ": opposite colour = go", vi, v0, "| skips %.0f%%" % (100 * CNT["skip"] / max(1, CNT["n"])))
    if q > 0.02:
        nets, dds = [], []
        for sd in range(20):
            r = random.Random(sd)
            H.DIRGATE = lambda t, d, r=r: r.random() >= q
            f = H.simulate(R, 7.0, LIVE); H.DIRGATE = None
            nets.append(f["net"]); dds.append(f["worst_debt"])
        nets.sort(); dds.sort()
        print("   random skipping at %.0f%%: median net %.2f, drop %.2f | rule beats random: net %.0f%%, drop %.0f%%" % (
            100 * q, nets[10], -dds[10], 100 * sum(1 for x in nets if x < vg["full"]["net"]) / 20,
            100 * sum(1 for x in dds if x > vg["full"]["worst_debt"]) / 20), flush=True)
