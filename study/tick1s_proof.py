"""Step 4 proof: the compact 1-second data must give the SAME test results as every raw tick.
Bitcoin's current test data (every raw tick, our own recorder) is compacted with tick1s_pack.compact() and the
same robot pair (Pekos owl vs Owl, today's bench) is run on both.   python study/tick1s_proof.py"""
import sys, os, pickle, json
sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import numpy as np
import robot_runner as RR
from tick1s_pack import compact
E, K, H = RR.E, RR.K, RR.H

K.install_nopause_gate()
TM, BID, ASK, n_bad, END = E.load_ticks()
cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": RR.BAL}), drag=0.0, limits_live=1))
opps, bars = E.streams(cfg0, E.R)
S_idx = pickle.load(open(K.CACHE, "rb"))["states"]
S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
reg = json.load(open(RR.REG, encoding="utf-8")); robots = {r["id"]: r for r in reg["robots"]}
PCS = {p["id"]: p for p in reg.get("pieces") or []}
k = compact(np.asarray(TM, dtype=np.int64), np.asarray(BID, dtype=np.float64), np.asarray(ASK, dtype=np.float64))
print("raw ticks %d -> compact %d (%.0f%%)" % (len(TM), len(k), 100.0 * len(k) / len(TM)), flush=True)
res = {}
for tag, (tm, bi, ak) in (("raw", (TM, BID, ASK)), ("compact", (TM[k], BID[k], ASK[k]))):
    arms = [RR.arm_for("robot", RR.resolve("pekos-owl", robots), bars, S, PCS), RR.arm_for("parent", RR.resolve("owl", robots), bars, S, PCS)]
    out = RR.run_pair(arms, tm, bi, ak, END, opps, bars)
    res[tag] = out
    print("%-8s Pekos owl %+.2f (%d trades, dip %.2f)   Owl %+.2f (%d trades, dip %.2f)" % (
        tag, out["robot"]["net"], out["robot"]["trades"], out["robot"]["cc_dd"], out["parent"]["net"], out["parent"]["trades"], out["parent"]["cc_dd"]), flush=True)
for who in ("robot", "parent"):
    a, b = res["raw"][who], res["compact"][who]
    print("%s: net diff %+.2f, trades %d vs %d" % (who, b["net"] - a["net"], a["trades"], b["trades"]))
json.dump({w: {t: {k2: res[t][w][k2] for k2 in ("net", "trades", "cc_dd", "wins")} for t in res} for w in ("robot", "parent")},
          open(os.path.join(HERE, "tick1s_proof.json"), "w"), indent=1)
