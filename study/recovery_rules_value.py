# Owner 2026-10-09: "tell me about the strategy itself - is the way we
# recover (the rules) making us money or not". Same 42-day replay, recovery
# rules switched off one at a time.
import sys
sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab"); sys.argv = ["x"]
import harness as H
sym, R = H.bars()
V = []
for jar in (True, False):
    t = " (jar on, like live)" if jar else " (jar off)"
    V += [("all recovery rules" + t, {"jar": jar}),
          ("no entry limit in debt" + t, {"jar": jar, "n_cont": 999}),
          ("no recovery bullets" + t, {"jar": jar, "bullets": 0}),
          ("plain strategy" + t, {"jar": jar, "n_cont": 999, "bullets": 0})]
def pf(p):
    w = sum(x for x in p if x > 0); l = -sum(x for x in p if x < 0)
    return w / l if l else float("nan")
base = None
for name, cfg in V:
    v = H.run_cfg(R, 7.0, cfg); f = v["full"]
    if base is None or "all recovery" in name: base = v
    p = f["pnls"]
    print("%-46s trades %3d | win %4.1f%% | PF %.2f | net %8.2f | 1st half %8.2f | 2nd half %8.2f | worst drop %7.2f | %s" % (
        name, f["trades"], f["wr"], pf(p), f["net"], v["h1"]["net"], v["h2"]["net"], -f["worst_debt"],
        "-" if v is base else "verdict vs today " + H.verdict(v, base)), flush=True)
