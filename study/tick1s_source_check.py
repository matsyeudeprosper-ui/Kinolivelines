"""Step 4 source check: is the BROKER's tick history (idle Standard terminal) the same as what our recorder captured
live for Bitcoin? Same period, same bars/structure, only the tick source swapped; then the same robot pair.
    python study/tick1s_source_check.py"""
import sys, os, glob, pickle, json
sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import numpy as np
import robot_runner as RR
from tick1s_pack import load_day
E, K, H = RR.E, RR.K, RR.H

K.install_nopause_gate()
TM, BID, ASK, n_bad, END = E.load_ticks()
t_lo, t_hi = int(TM[0]), int(TM[-1])
parts = [load_day(f) for f in sorted(glob.glob(os.path.join(HERE, "tick1s", "BTCUSDm", "*.npz"))) if os.path.basename(f) != "bars.npz"]
bt = np.concatenate([p[0] for p in parts]); bb = np.concatenate([p[1] for p in parts]); ba = np.concatenate([p[2] for p in parts])
m = (bt >= t_lo) & (bt <= t_hi); bt, bb, ba = bt[m], bb[m], ba[m]
print("recorder ticks %d | broker ticks %d over the same window (%.1f%%)" % (len(TM), len(bt), 100.0 * len(bt) / len(TM)), flush=True)
# quote agreement: at each recorder tick, the broker's last quote at or before it
j = np.searchsorted(bt, np.asarray(TM, dtype=np.int64), side="right") - 1
ok = j >= 0
db = np.abs(bb[j[ok]] - np.asarray(BID)[ok]); da = np.abs(ba[j[ok]] - np.asarray(ASK)[ok])
print("quote agreement: bid identical on %.1f%%, within $1 on %.1f%% | ask identical on %.1f%%, within $1 on %.1f%%" % (
    100 * np.mean(db < 1e-6), 100 * np.mean(db <= 1.0), 100 * np.mean(da < 1e-6), 100 * np.mean(da <= 1.0)), flush=True)
cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": RR.BAL}), drag=0.0, limits_live=1))
opps, bars = E.streams(cfg0, E.R)
S_idx = pickle.load(open(K.CACHE, "rb"))["states"]
S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
reg = json.load(open(RR.REG, encoding="utf-8")); robots = {r["id"]: r for r in reg["robots"]}
PCS = {p["id"]: p for p in reg.get("pieces") or []}
res = {}
for tag, (tm, bi, ak) in (("recorder", (TM, BID, ASK)), ("broker", (bt, bb, ba))):
    arms = [RR.arm_for("robot", RR.resolve("pekos-owl", robots), bars, S, PCS), RR.arm_for("parent", RR.resolve("owl", robots), bars, S, PCS)]
    out = RR.run_pair(arms, tm, bi, ak, END, opps, bars); res[tag] = out
    print("%-9s Pekos owl %+.2f (%d trades)   Owl %+.2f (%d trades)" % (tag, out["robot"]["net"], out["robot"]["trades"], out["parent"]["net"], out["parent"]["trades"]), flush=True)
json.dump({t: {w: {k: res[t][w][k] for k in ("net", "trades", "cc_dd")} for w in ("robot", "parent")} for t in res},
          open(os.path.join(HERE, "tick1s_source_check.json"), "w"), indent=1)
