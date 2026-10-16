"""Broker spread what-if (owner 2026-10-16, FOREX.com pilot): the SAME 42-day Bitcoin tick replay the proof page uses,
with the broker's spread forced to a constant around the mid price. Exness Pro quotes ~$4.5; FOREX.com quotes a fixed
$40 all day. Everything else (signals, stops, targets, money rules, $0.35/lot slippage) is unchanged.

Every robot a member may run (owner 2026-10-16: "many robots from many brokers... the verification should check
any existing robot"): stage tested/real/demo, public or the Owl itself. One replay per spread level runs ALL of them
side by side (one arm each), so a new public robot only costs its arm.
    python study/spread_whatif.py [spread $ ...]        default: native, 10, 20, 40
Writes study/spread_whatif.json and live/lab/spread_curve.json ({"robots": {id: {"name", "native", "points": {spread: net}}}}).
Heavy (loads every tick): run alone, never beside a pack build or a market test.
"""
import sys, os, json, time, pickle
SP = [float(a) for a in sys.argv[1:]] or [10.0, 20.0, 40.0]
sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import numpy as np
import robot_runner as RR
import tick_engine as E
import tick_engine_pbgate_sticky as K
import harness as H

t0 = time.time()
K.install_nopause_gate()
TM, BID, ASK, n_bad, END = E.load_ticks()
cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": RR.BAL}), drag=0.0, limits_live=1))
opps, bars = E.streams(cfg0, E.R)
cached = pickle.load(open(K.CACHE, "rb")); S_idx = cached["states"]
S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
reg = json.load(open(RR.REG, encoding="utf-8")); robots = {r["id"]: r for r in reg.get("robots") or []}
PCS = {p["id"]: p for p in reg.get("pieces") or []}
RIDS = [rid for rid, r in robots.items() if r.get("stage") in ("tested", "real", "demo") and (r.get("public") or rid == "owl")]
NAMES = {rid: (robots[rid].get("name_fr") or robots[rid].get("name") or rid) for rid in RIDS}
native = float(np.median(np.asarray(ASK, dtype=np.float64) - np.asarray(BID, dtype=np.float64)))
print("ticks %d, native median spread $%.2f, robots %s, loaded in %.0fs" % (len(TM), native, RIDS, time.time() - t0), flush=True)
out = {"native_median_spread": round(native, 2), "days": round((int(TM[-1]) - int(TM[0])) / 86400000, 1), "robots": RIDS, "runs": {}}
KEYS = ("net", "trades", "wins", "win_rate", "cc_dd", "mtm_dd", "profit_factor")
for sp in [None] + SP:
    if sp is None:
        B, A, tag = BID, ASK, "native"
    else:
        mid = (np.asarray(BID, dtype=np.float64) + np.asarray(ASK, dtype=np.float64)) / 2.0
        B, A, tag = (mid - sp / 2.0).astype(BID.dtype), (mid + sp / 2.0).astype(ASK.dtype), "%.0f" % sp
    t1 = time.time()
    arms = [RR.arm_for(rid, RR.resolve(rid, robots), bars, S, PCS) for rid in RIDS]
    r = RR.run_pair(arms, TM, B, A, END, opps, bars)
    out["runs"][tag] = {k: {kk: v[kk] for kk in KEYS} for k, v in r.items()}
    print("spread %-7s " % tag + " | ".join("%s net %+8.2f (%d trades, dd %.2f)" % (rid, r[rid]["net"], r[rid]["trades"], r[rid]["mtm_dd"]) for rid in RIDS) + "   %.0fs" % (time.time() - t1), flush=True)
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "spread_whatif.json"), "w", encoding="utf-8"), indent=1)
    # the broker book's cost curve (live/broker_book.py est_at): per robot, the native point + one point per forced spread
    curve = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "days": out["days"], "balance": RR.BAL, "native_spread": out["native_median_spread"],
             "robots": {rid: {"name": NAMES[rid], "native": out["runs"]["native"][rid]["net"],
                              "points": {k: v[rid]["net"] for k, v in out["runs"].items() if k != "native"}} for rid in RIDS}}
    json.dump(curve, open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "live", "lab", "spread_curve.json"), "w", encoding="utf-8"), indent=1)
