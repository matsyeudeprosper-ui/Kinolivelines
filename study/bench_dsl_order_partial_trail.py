import sys, os, json, time, pickle
sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study")
import robot_runner as RR
E, K, H = RR.E, RR.K, RR.H
t0 = time.time()
K.install_nopause_gate()
TM, BID, ASK, n_bad, END = E.load_ticks()
cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": RR.BAL}), drag=0.0, limits_live=1))
opps, bars = E.streams(cfg0, E.R)
S_idx = pickle.load(open(K.CACHE, "rb"))["states"]; S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
reg = json.load(open(RR.REG, encoding="utf-8")); robots = {r["id"]: r for r in reg["robots"]}
PCS = {p["id"]: p for p in reg["pieces"]}
def piece(pid, typ, rule): PCS[pid] = {"id": pid, "type": typ, "rule": rule}
piece("t-entry", "entry", {"event": "formula", "buy": "cross_up(close, ema(close, 50)) and trend > 0", "sell": "cross_down(close, ema(close, 50)) and trend < 0"})
piece("t-entry-lim", "entry", {"event": "formula", "buy": "cross_up(close, ema(close, 50)) and trend > 0", "sell": "cross_down(close, ema(close, 50)) and trend < 0",
                               "order": {"type": "limit", "buy": "close - 0.5 * atr(14)", "sell": "close + 0.5 * atr(14)", "expire_min": 30}})
piece("t-stop", "stop", {"kind": "formula", "buy": "close - 2 * atr(14)", "sell": "close + 2 * atr(14)"})
piece("t-x1", "exit", {"target": 1.0, "choch": False, "time_min": None, "breakeven_at": None})
piece("t-x2p", "exit", {"target": 2.0, "choch": False, "time_min": None, "breakeven_at": None, "partial": {"at": 1.0, "pct": 50}})
piece("t-xtr", "exit", {"target": None, "choch": False, "time_min": None, "breakeven_at": None, "trail": {"start": 1.0, "dist": 1.0}})
base = {"entry": "t-entry", "filters": [], "stop": "t-stop", "exit": "t-x1", "recovery": "rattrapage-limite", "money": "simple"}
V = {"A simple 1R": base, "B + limit": dict(base, entry="t-entry-lim"), "C 2R + partial": dict(base, exit="t-x2p"),
     "D trail": dict(base, exit="t-xtr"), "E Owl money": dict(base, money="base")}
for name, parts in V.items():
    t1 = time.time()
    ro, rS = RR.robot_opps(parts, PCS, opps, S, bars)
    arm = RR.arm_for("robot", parts, bars, rS, PCS, opps=opps)
    arm.c["kill_net"] = 0.0          # mechanics test: no -60 stop
    out = RR.run_pair([arm], TM, BID, ASK, END, ro, bars)["robot"]
    nn = {k: v for k, v in arm.n.items() if k.startswith("dsl_") and v}
    print("%-16s net %8.2f trades %4d win %5s pf %5s dd %6s | signals %d | %s | %.0fs" % (name, out["net"], out["trades"], out["win_rate"], out["profit_factor"], out["cc_dd"], len(ro), nn, time.time() - t1), flush=True)
    print("   partial trades %d, wins %d of %d" % (sum(1 for t in arm.trades if t.get("pnl_partial")), sum(1 for t in arm.trades if t["win"]), len(arm.trades)), flush=True)
print("total %.0fs" % (time.time() - t0))
