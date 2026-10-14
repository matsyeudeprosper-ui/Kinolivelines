"""calibrate_bar_fills.py (2026-10-14): how much does the market-pack path (1-minute candles replayed as 4 quotes,
adverse extreme first) cost versus real ticks? Replay a robot on BITCOIN through the pack path, on the SAME bars,
warm-up and pullback cache as the tick bench, and compare with its tick result. k = 1 and BTC's own minimum stop,
so the ONLY difference is the fills. If the candle path is much worse, every other market's result is biased low.
    python calibrate_bar_fills.py [robot id, default owl]
"""
import sys, os, json, time, pickle, shutil
ARGS = list(sys.argv); sys.argv = ["x"]
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import numpy as np
import robot_runner as RR
import market_pack as MP
import tick_engine_matrix as TMX
E, K, H = RR.E, RR.K, RR.H

rid = ARGS[1] if len(ARGS) > 1 else "owl"
reg = json.load(open(RR.REG, encoding="utf-8")); robots = {r["id"]: r for r in reg.get("robots") or []}
PCS = {p["id"]: p for p in reg.get("pieces") or []}
parts = RR.resolve(rid, robots)
K.install_nopause_gate()
D = E.R
meta = {"sha256": E.META["sha256"], "closed_bar_cutoff": E.META["closed_bar_cutoff"], "symbol": "BTC-calibration",
        "point": 0.01, "k": 1.0, "spread_med_points": float(np.median(D["spread"][D["spread"] > 0])), "s_min_dist": float(E.S_MIN_DIST)}
cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": RR.BAL}), drag=0.0, limits_live=1))
opps, bars = E.streams(cfg0, D)
cached = pickle.load(open(K.CACHE, "rb")); S_idx = cached["states"]
S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
out = {}
for mode in ("ticks", "bars"):
    if mode == "ticks":
        TM, BID, ASK, nb, END = E.load_ticks()
    else:
        TM, BID, ASK, nb, END = MP.synthetic_ticks(D, meta)
    for drag in (0.35, 0.0):
        RR.DRAG = drag
        arms = [RR.arm_for("robot", parts, bars, S, PCS)]
        o = RR.run_pair(arms, TM, BID, ASK, END, opps, bars)["robot"]
        out["%s_drag%s" % (mode, drag)] = {k: o[k] for k in ("net", "trades", "win_rate", "profit_factor", "cc_dd", "first_half", "later_half")}
        print(mode, "drag", drag, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out["%s_drag%s" % (mode, drag)].items()}, flush=True)
json.dump(out, open(os.path.join(HERE, "calibrate_bar_fills_%s.json" % rid), "w"), indent=1)
