"""Broker spread what-if (owner 2026-10-16, FOREX.com pilot): the SAME 42-day Bitcoin tick replay the proof page uses,
with the broker's spread forced to a constant around the mid price. Exness Pro quotes ~$4.5; FOREX.com quotes a fixed
$40 all day. Everything else (signals, stops, targets, money rules, $0.35/lot slippage) is unchanged.
    python study/spread_whatif.py [spread $ ...]        default: native, 10, 20, 40
Writes study/spread_whatif.json. Heavy (loads every tick): run alone, never beside a pack build or a market test.
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
native = float(np.median(np.asarray(ASK, dtype=np.float64) - np.asarray(BID, dtype=np.float64)))
print("ticks %d, native median spread $%.2f, loaded in %.0fs" % (len(TM), native, time.time() - t0), flush=True)
out = {"native_median_spread": round(native, 2), "days": round((int(TM[-1]) - int(TM[0])) / 86400000, 1), "runs": {}}
for sp in [None] + SP:
    if sp is None:
        B, A, tag = BID, ASK, "native"
    else:
        mid = (np.asarray(BID, dtype=np.float64) + np.asarray(ASK, dtype=np.float64)) / 2.0
        B, A, tag = (mid - sp / 2.0).astype(BID.dtype), (mid + sp / 2.0).astype(ASK.dtype), "%.0f" % sp
    t1 = time.time()
    arms = [RR.arm_for("owl", RR.resolve("owl", robots), bars, S, PCS), RR.arm_for("pekos-owl", RR.resolve("pekos-owl", robots), bars, S, PCS)]
    r = RR.run_pair(arms, TM, B, A, END, opps, bars)
    out["runs"][tag] = {k: {kk: v[kk] for kk in ("net", "trades", "wins", "win_rate", "cc_dd", "mtm_dd", "profit_factor")} for k, v in r.items()}
    print("spread %-7s owl net %+8.2f (%d trades, dd %.2f) | pekos-owl net %+8.2f (%d trades, dd %.2f)   %.0fs" % (
        tag, r["owl"]["net"], r["owl"]["trades"], r["owl"]["mtm_dd"], r["pekos-owl"]["net"], r["pekos-owl"]["trades"], r["pekos-owl"]["mtm_dd"], time.time() - t1), flush=True)
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "spread_whatif.json"), "w", encoding="utf-8"), indent=1)
