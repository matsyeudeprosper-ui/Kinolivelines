"""spread_audit_owl20.py [robot=owl] [spread=20] - audit of a good result (2026-10-16): Owl at a forced $20 spread made
+56.66 with 5 fewer trades than at its native cost (+51.10). Which trades disappear, which change, and why?
Replays the proof window twice (native ticks, forced spread) with ONE arm each and diffs the trade lists by close
time. Writes study/spread_audit_<robot>_<spread>.json and prints the differences. Heavy: run alone.
"""
import sys, os, json, time, pickle
rid = sys.argv[1] if len(sys.argv) > 1 else "owl"; SP = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import numpy as np
import robot_runner as RR
import tick_engine as E
import tick_engine_pbgate_sticky as K
import harness as H
from tick_engine_matrix import summarise

K.install_nopause_gate()
TM, BID, ASK, n_bad, END = E.load_ticks()
cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": RR.BAL}), drag=0.0, limits_live=1))
opps, bars = E.streams(cfg0, E.R)
cached = pickle.load(open(K.CACHE, "rb")); S_idx = cached["states"]
S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
reg = json.load(open(RR.REG, encoding="utf-8")); robots = {r["id"]: r for r in reg.get("robots") or []}
PCS = {p["id"]: p for p in reg.get("pieces") or []}
TMID = (int(TM[0]) + int(TM[-1])) // 2


def run(B, A, tag):
    t0 = time.time()
    arm = RR.arm_for(rid, RR.resolve(rid, robots), bars, S, PCS)
    RR.run_pair([arm], TM, B, A, END, opps, bars)
    a = summarise(arm, TM, B, A, END, TMID)
    print("%s: net %.2f, %d trades (%.0fs)" % (tag, a["net"], a["trades"], time.time() - t0), flush=True)
    return a


nat = run(BID, ASK, "native")
mid = (np.asarray(BID, dtype=np.float64) + np.asarray(ASK, dtype=np.float64)) / 2.0
forced = run((mid - SP / 2.0).astype(BID.dtype), (mid + SP / 2.0).astype(ASK.dtype), "spread %.0f" % SP)
key = lambda t: int(t.get("fill_ms") or t["tc"]) // 60000       # entry minute (fill), else close minute
N = {key(t): t for t in nat["trades_list"]}; F = {key(t): t for t in forced["trades_list"]}
only_n = [N[k] for k in sorted(set(N) - set(F))]; only_f = [F[k] for k in sorted(set(F) - set(N))]
both = [(N[k], F[k]) for k in sorted(set(N) & set(F))]
print("\nfirst trade keys:", sorted((nat["trades_list"] or [{}])[0].keys()))
print("\nonly at native cost (%d): net %.2f" % (len(only_n), sum(t["pnl"] for t in only_n)))
for t in only_n:
    print("  %s pnl %+7.2f" % (time.strftime("%m-%d %H:%M", time.gmtime(key(t) * 60)), t["pnl"]))
print("only at $%.0f (%d): net %.2f" % (SP, len(only_f), sum(t["pnl"] for t in only_f)))
for t in only_f:
    print("  %s pnl %+7.2f" % (time.strftime("%m-%d %H:%M", time.gmtime(key(t) * 60)), t["pnl"]))
d = [(a, b) for a, b in both if abs(a["pnl"] - b["pnl"]) > 0.005]
print("shared trades %d, of which %d changed: native %.2f -> forced %.2f" % (len(both), len(d), sum(a["pnl"] for a, b in both), sum(b["pnl"] for a, b in both)))
for a, b in sorted(d, key=lambda ab: -abs(ab[0]["pnl"] - ab[1]["pnl"]))[:15]:
    print("  %s %+7.2f -> %+7.2f" % (time.strftime("%m-%d %H:%M", time.gmtime(key(a) * 60)), a["pnl"], b["pnl"]))
out = {"robot": rid, "spread": SP, "native_net": nat["net"], "forced_net": forced["net"], "native_trades": nat["trades"], "forced_trades": forced["trades"],
       "only_native": [{"t": key(t) * 60, "pnl": t["pnl"]} for t in only_n], "only_forced": [{"t": key(t) * 60, "pnl": t["pnl"]} for t in only_f],
       "shared": len(both), "shared_changed": [{"t": key(a) * 60, "native": a["pnl"], "forced": b["pnl"]} for a, b in d]}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "spread_audit_%s_%.0f.json" % (rid, SP)), "w"), indent=1)
