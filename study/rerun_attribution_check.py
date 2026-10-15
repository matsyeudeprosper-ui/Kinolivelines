"""Attribution check for the 2026-10-15 re-run: rerun the Bitcoin pair (Pekos owl vs Owl) with the OLD add risk
(full stop distance) patched in memory. If it reproduces the old results (+66.27 / +57.39), the whole change
in the new results is the add fix and nothing else.   python study/rerun_attribution_check.py"""
import sys, os, math, pickle, json
sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import robot_runner as RR
E, K, H = RR.E, RR.K, RR.H


def old_try_adds(self, k, TM, BID, ASK):
    p = self.pos; p["add_done"] = True
    c = self.c; debt = self.debt(); self.n["adds_triggered"] += 1
    if not (debt > 0.5 and self.streak < self.K and self.NB > 0): return
    nv = self.bars.get(int(TM[k]) // 60000 * 60, (False, p["nv"]))[1]
    if c["jar"]:
        r001 = p["dist"] * E.BLOT; gain001 = self.rr * r001                    # the OLD (full distance) arithmetic
        by_budget = int((self.chest * E.JAR_STAKE) // r001) if r001 > 0 else 0
        by_debt = int(math.ceil(debt / gain001)) if gain001 > 0 else 0
        nb = 0 if nv > 1.0 else max(0, min(self.NB, by_budget, by_debt))
    else:
        nb = self.NB
    if nb:
        self.order = {"kind": "bullet", "due": int(TM[k]) + E.EXEC_MS, "setup": {"d": p["d"]}, "n": nb}


E.Arm.try_adds = old_try_adds
K.install_nopause_gate()
TM, BID, ASK, n_bad, END = E.load_ticks()
cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": RR.BAL}), drag=0.0, limits_live=1))
opps, bars = E.streams(cfg0, E.R)
S_idx = pickle.load(open(K.CACHE, "rb"))["states"]
S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
reg = json.load(open(RR.REG, encoding="utf-8")); robots = {r["id"]: r for r in reg["robots"]}
PCS = {p["id"]: p for p in reg.get("pieces") or []}
arms = [RR.arm_for("robot", RR.resolve("pekos-owl", robots), bars, S, PCS), RR.arm_for("parent", RR.resolve("owl", robots), bars, S, PCS)]
out = RR.run_pair(arms, TM, BID, ASK, END, opps, bars)
print("OLD add risk: Pekos owl %+.2f (%d trades)  Owl %+.2f (%d trades)   [published before: +66.27 (80) / +57.39 (82)]"
      % (out["robot"]["net"], out["robot"]["trades"], out["parent"]["net"], out["parent"]["trades"]))
