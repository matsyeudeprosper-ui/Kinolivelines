"""The robot builder's test bench (owner 2026-10-12): every robot in live/robots/robots.json whose stage is
"queued" is replayed on the proof page's harness (base money at $200 unless the robot names another money
version, tick engine, live gate order, adaptive cap, sticky pullback structure, trend filter, 0.35 $/lot
cost) next to its PARENT, and the result is written to live/robots/results/<id>.json; the robot's stage
becomes "tested". One run at a time (a lock file); robots are tested one after another.

    python robot_runner.py            # all queued robots
    python robot_runner.py <id> ...   # these robots, whatever their stage
"""
import sys, os, json, time, pickle
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import tick_engine as E
from tick_engine_matrix import summarise
import tick_engine_pbgate_sticky as K
import harness as H
from robot_choch_exit import RobotArm
LIVE = r"C:\Projects\KinoliveLines\live"
REG = os.path.join(LIVE, "robots", "robots.json"); RES = os.path.join(LIVE, "robots", "results")
LOCK = os.path.join(LIVE, "robots", "runner.lock"); BAL = 200.0; DRAG = 0.35


def resolve(rid, robots, seen=None):
    """a robot's parts: its parent's, then its own on top (nearest wins), like the money packages"""
    seen = seen or set()
    r = robots.get(rid)
    if r is None or rid in seen:
        return {}
    seen.add(rid)
    out = resolve(r.get("parent"), robots, seen) if r.get("parent") else {}
    for k, v in (r.get("parts") or {}).items():
        out[k] = v
    return out


def arm_for(name, parts, bars, S, pieces=None):
    """a robot's named pieces (robots.json v2) -> the bench's settings. Filters are a list: a filter that is
    absent is switched OFF (the storm ceiling, the movement brake, the trend filter, the nervosity gate)."""
    P = pieces or {}
    eng = lambda pid: (P.get(pid) or {}).get("engine") or {}
    ex = eng(parts.get("exit") or "objectif-08r")
    pkg = parts.get("money") or "base"
    cfg_b = H.package_cfg(pkg, {"balance": BAL}); cfg_b.update({"scale_lot": 1, "scale_daily": 1})
    if ex.get("rr"):
        cfg_b["rr"] = float(ex["rr"])
    F = parts.get("filters")
    F = ["tendance-fond", "orage", "mouvement"] if F is None else list(F)
    fe = {}
    for f in F:
        fe.update(eng(f))
    cfg_b["storm"] = float(fe.get("storm", 99.0))          # no storm piece: no storm ceiling
    cfg_b["movement"] = int(fe.get("movement", 0))
    cfg_b["nerv_gate"] = bool(fe.get("nerv_gate", False))
    cfg = H.cfg_strict(dict(cfg_b, drag=DRAG, limits_live=1))
    rec = eng(parts.get("recovery") or "rattrapage-limite").get("recovery", "current")
    return RobotArm(name, cfg, bars, S, exit=ex.get("exit") if ex.get("exit") in ("choch", "target_choch") else "target",
                    stop="protected", allowance="all_bos" if rec == "all_bos" else "current",
                    gate="trend" if fe.get("gate") == "trend" else "none",
                    order="live", cap_rule="adaptive", cap="on")


def run_pair(arms, TM, BID, ASK, END, opps, bars):
    elig = [((o["t"] + 60) * 1000 + E.SIGNAL_MS, o) for o in opps]; ei = 0
    touches = sorted((t * 1000 + 60000, 1) for t, (touched, nv) in bars.items() if touched); ti = 0
    prev = int(TM[0])
    for kk in range(len(TM)):
        t_ms = int(TM[kk]); gap_in = t_ms - prev; prev = t_ms
        for arm in arms: arm.roll(t_ms)
        while ti < len(touches) and touches[ti][0] <= t_ms:
            ti += 1
            for arm in arms:
                if arm.last_flip_t is not None and arm.cont_left < int(arm.c["n_cont"]): arm.cont_left = min(int(arm.c["n_cont"]), arm.cont_left + 1)
        while ei < len(elig) and elig[ei][0] <= t_ms:
            o = elig[ei][1]; ei += 1
            for arm in arms: arm.signal(o, kk, TM, BID, ASK)
        for arm in arms: arm.tick(kk, TM, BID, ASK, gap_in)
    TMID = (int(TM[0]) + int(TM[-1])) // 2; out = {}
    for arm in arms:
        a = summarise(arm, TM, BID, ASK, END, TMID)
        cur = 0.0; curve = {}
        for t in a["trades_list"]:
            cur += t["pnl"]; curve[time.strftime("%Y-%m-%d", time.gmtime(t["tc"] / 1000))] = round(cur, 2)
        pn = [t["pnl"] for t in a["trades_list"]]; streak = mx = 0
        for p in pn:
            streak = streak + 1 if p <= 0 else 0; mx = max(mx, streak)
        hold = sorted((t["tc"] - (t.get("fill_ms") or t["tc"])) / 60000.0 for t in a["trades_list"])
        out[arm.name] = {k: a[k] for k in ("net", "cc_dd", "mtm_dd", "trades", "wins", "win_rate", "profit_factor", "first_half", "later_half")}
        out[arm.name].update({"curve": sorted(curve.items()), "max_loss_streak": mx, "best": max(pn) if pn else None, "worst": min(pn) if pn else None,
                              "hold_median_min": round(hold[len(hold) // 2], 1) if hold else None})
    return out


if __name__ == "__main__":
    if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 3 * 3600:
        print("another run is in progress"); sys.exit(0)
    open(LOCK, "w").write(str(os.getpid()))
    try:
        reg = json.load(open(REG, encoding="utf-8")); robots = {r["id"]: r for r in reg.get("robots") or []}
        todo = ARGS[1:] or [r["id"] for r in reg.get("robots") or [] if r.get("stage") == "queued"]
        if not todo:
            print("nothing queued"); sys.exit(0)
        os.makedirs(RES, exist_ok=True)
        K.install_nopause_gate()
        TM, BID, ASK, n_bad, END = E.load_ticks()
        cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": BAL}), drag=0.0, limits_live=1))
        opps, bars = E.streams(cfg0, E.R)
        cached = pickle.load(open(K.CACHE, "rb")); S_idx = cached["states"]
        S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
        for rid in todo:
            r = robots.get(rid)
            if not r:
                continue
            t0 = time.time()
            parts = resolve(rid, robots); parent = r.get("parent") or "owl"
            PCS = {p["id"]: p for p in reg.get("pieces") or []}
            missing = [v for k, v in parts.items() if k != "money" and k != "filters" and (PCS.get(v) or {}).get("status") in ("pending", "to_build", None)]
            if missing:
                print(rid, "skipped: pieces not testable yet", missing, flush=True); continue
            arms = [arm_for("robot", parts, bars, S, PCS), arm_for("parent", resolve(parent, robots), bars, S, PCS)]
            out = run_pair(arms, TM, BID, ASK, END, opps, bars)
            res = {"id": rid, "parent": parent, "parts": parts, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "balance": BAL, "drag": DRAG, "days": round((int(TM[-1]) - int(TM[0])) / 86400000, 1),
                   "window_utc": [time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[0]) / 1000)), time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[-1]) / 1000))],
                   "robot": out["robot"], "parent_result": out["parent"], "secs": round(time.time() - t0)}
            json.dump(res, open(os.path.join(RES, rid + ".json"), "w", encoding="utf-8"), indent=1)
            reg = json.load(open(REG, encoding="utf-8"))           # re-read: the app may have added robots meanwhile
            for x in reg.get("robots") or []:
                if x["id"] == rid and x.get("stage") in ("queued", "testing", None):
                    x["stage"] = "tested"; x["tested_at"] = res["generated_at"]
            json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(rid, "robot net %.2f vs parent %.2f (%ds)" % (out["robot"]["net"], out["parent"]["net"], res["secs"]), flush=True)
    finally:
        try: os.remove(LOCK)
        except Exception: pass
