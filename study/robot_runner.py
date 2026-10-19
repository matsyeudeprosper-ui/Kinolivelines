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
from robot_dsl_arm import DslArm
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


def arm_for(name, parts, bars, S, pieces=None, opps=None):
    """a robot's named pieces (robots.json v2) -> the bench's settings. Filters are a list: a filter that is
    absent is switched OFF (the storm ceiling, the movement brake, the trend filter, the nervosity gate)."""
    P = pieces or {}
    eng = lambda pid: (P.get(pid) or {}).get("engine") or {}
    rule = lambda pid: (P.get(pid) or {}).get("rule")
    # pieces written in the piece language (robots.json 'rule'), run by DslArm
    dsl = {}
    for k in ("entry", "stop", "exit"):
        if parts.get(k) and rule(parts[k]) is not None:
            dsl[k] = rule(parts[k])
    ex = eng(parts.get("exit") or "objectif-08r")
    if "exit" in dsl and dsl["exit"].get("target") is not None:
        ex = {"rr": dsl["exit"]["target"]}
    pkg = parts.get("money") or "base"
    cfg_b = H.package_cfg(pkg, {"balance": BAL}); cfg_b.update({"scale_lot": 1, "scale_daily": 1})
    if ex.get("rr"):
        cfg_b["rr"] = float(ex["rr"])
    F = parts.get("filters")
    F = ["tendance-fond", "orage", "mouvement"] if F is None else list(F)
    fe = {}
    for f in F:
        if rule(f) is not None:
            dsl.setdefault("filters", []).append(rule(f))
        else:
            fe.update(eng(f))
    cfg_b["storm"] = float(fe.get("storm", 99.0))          # no storm piece: no storm ceiling
    cfg_b["movement"] = int(fe.get("movement", 0))
    cfg_b["nerv_gate"] = bool(fe.get("nerv_gate", False))
    cfg = H.cfg_strict(dict(cfg_b, drag=DRAG, limits_live=1))
    rec = eng(parts.get("recovery") or "rattrapage-limite").get("recovery", "current")
    return DslArm(name, cfg, bars, S, dsl=dsl, exit=ex.get("exit") if ex.get("exit") in ("choch", "target_choch") else "target",
                    stop="protected", allowance="all_bos" if rec == "all_bos" else "current",
                    gate="trend" if fe.get("gate") == "trend" else "none",
                    order="live", cap_rule="adaptive", cap="on", opps=opps)


def robot_opps(parts, pieces, opps, S, bars):
    """2026-10-19: a robot whose ENTRY is a formula gets its own opportunity stream - one per candle where its buy
    or sell formula turns true (from false), at that candle's close, shaped like the eyes' stream so every gate
    downstream reads it the same way: fresh (flip), awake, the bar's own pace, the background trend of the last
    real break before it. Its stop: the robot's stop piece; a 'protected point' does not exist for a formula entry,
    so the extreme of the last 20 candles stands in for it. Returns (opps, S) unchanged for any other robot."""
    P = pieces or {}
    en = (P.get(parts.get("entry")) or {}).get("rule") or {}
    if en.get("event") != "formula":
        return opps, S
    import bisect
    import numpy as np
    sys.path.insert(0, os.path.join(LIVE, "robots"))
    import robot_expr as X
    from datetime import datetime, timezone
    R = E.R; n = len(R)
    B = X.Bars.from_rates(R, X.eyes_from_opps(opps, n, S))
    times = [int(x) for x in R["time"]]
    lo = min(1440, n - 1)                           # the harness's warm-up (a day of bars)
    rt = sorted(opps, key=lambda o: o["t"]); rts = [o["t"] for o in rt]
    st = (P.get(parts.get("stop")) or {}).get("rule") or {}
    sw_lo, sw_hi = X.evaluate("lowest(low, 20)", B), X.evaluate("highest(high, 20)", B)
    out, S2 = [], dict(S)
    for d, src in ((1, en.get("buy")), (-1, en.get("sell"))):
        if not src:
            continue
        tr = X.truth(src, B)
        edge = np.flatnonzero(tr & ~np.r_[False, tr[:-1]])
        for i in edge:
            i = int(i)
            if i < lo or i >= n - 2:
                continue
            t = times[i]; cl = float(R["close"][i])
            slp = float(sw_lo[i]) if d == 1 else float(sw_hi[i])
            if st.get("kind") == "fixed":
                slp = cl - d * float(st["points"])
            if slp != slp:
                continue
            g = datetime.fromtimestamp(t, tz=timezone.utc)
            nv = (bars.get(t) or (0, 1.0))[1]
            out.append({"t": t, "i": i, "d": d, "slp": slp, "cl": cl, "flip": True, "awake": True, "nv": nv, "mv2": None,
                        "i_fire": False, "lvl": cl, "weekday": g.weekday(), "hour": g.hour, "minute": g.minute})
            j = bisect.bisect_right(rts, t) - 1
            if t not in S2:
                S2[t] = S.get(rts[j], (0, 0, None, None)) if j >= 0 else (0, 0, None, None)
    out.sort(key=lambda o: (o["t"], o["d"]))
    return out, S2


def run_robot_and_parent(parts, parent_parts, PCS, TM, BID, ASK, END, opps, bars, S):
    """the robot next to its parent; a formula-entry robot runs on its own stream, the parent on the eyes'"""
    ro, rS = robot_opps(parts, PCS, opps, S, bars)
    ra = arm_for("robot", parts, bars, rS, PCS, opps=opps)
    pa = arm_for("parent", parent_parts, bars, S, PCS, opps=opps)
    if ro is opps:
        return run_pair([ra, pa], TM, BID, ASK, END, opps, bars)
    out = run_pair([ra], TM, BID, ASK, END, ro, bars)
    out.update(run_pair([pa], TM, BID, ASK, END, opps, bars))
    out["robot"]["signals"] = len(ro)
    return out


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


# ---- 2026-10-14 (owner): a robot tested on another market of the member's broker ----
# The queue is live/robots/market_tests.json: [{id, rid, sym, uid, terminal, state, at, ...}], state
# queued -> building (the market's pack, ~40 min the first time) -> testing -> done | error.
# A market test re-points the engine's module data (bars, cutoff, cache, minimum stop), so it ALWAYS runs
# in its own process (--markets), never in the process that ran a BTC test.
MQ = os.path.join(LIVE, "robots", "market_tests.json")
PUSHQ = os.path.join(LIVE, "owl_push_queue.json")


def mq_load():
    try:
        return json.load(open(MQ, encoding="utf-8"))
    except Exception:
        return []


def mq_set(qid, **kw):
    q = mq_load()
    for x in q:
        if x.get("id") == qid:
            x.update(kw)
    json.dump(q, open(MQ + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(MQ + ".tmp", MQ)


def push(uid, title, body):
    """same line format as owl_app_server.queue_push (the notifier also writes the inbox)"""
    try:
        try:
            q = json.load(open(PUSHQ, encoding="utf-8"))
        except Exception:
            q = []
        q.append({"uid": uid, "t": int(time.time()), "title": title, "body": body})
        json.dump(q, open(PUSHQ, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass


MLOG = os.path.join(LIVE, "robots", "market_runs.log")


def mlog(m):
    try:
        with open(MLOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(m) + chr(10))
    except Exception:
        pass


FAST_LOCK = os.path.join(LIVE, "robots", "runner_fast.lock")


def _alive(pid):
    """is this process still running? (Windows API - NEVER os.kill(pid, 0) here: on Windows it terminates it)"""
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))     # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259                                            # STILL_ACTIVE
    except Exception:
        return False


def run_markets(fast=False):
    """fast=True (2026-10-14, owner: "why one hour long"): the FAST LANE - only jobs whose market is already
    prepared (a test of under a minute), run beside a long preparation instead of waiting behind it"""
    import market_pack as MP
    import tick_pack as TP          # 2026-10-16 precision plan: a market with a verified-tick pack is tested on it
    import tick_engine_matrix as TMX
    while True:
        q = mq_load()
        if fast:
            todo = [x for x in q if x.get("state") == "queued" and (TP.tick_ready(x["sym"]) or MP.pack_ready(x["sym"]))]
        else:          # a job another runner is testing right now (alive pid) is not ours
            todo = [x for x in q if x.get("state") in ("queued", "building")
                    or (x.get("state") == "testing" and not (x.get("pid") and x.get("pid") != os.getpid() and _alive(x["pid"])))]
        if not todo:
            return
        job = todo[0]; qid, rid, sym = job["id"], job["rid"], job["sym"].upper()
        cur = next((x for x in mq_load() if x.get("id") == qid), {})
        if cur.get("state") == "testing" and cur.get("pid") and cur.get("pid") != os.getpid() and _alive(cur["pid"]):
            continue                                                         # taken meanwhile by the other lane
        try:
            open(FAST_LOCK if fast else LOCK, "w").write(str(os.getpid()))  # keep the lock fresh across long builds
            tick = TP.tick_ready(sym)
            if not tick and not MP.pack_ready(sym):
                mq_set(qid, state="building", building_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), pid=os.getpid())
                MP.build(sym, job.get("terminal") or MP.DEFAULT_TERMINAL, log=mlog)
            mq_set(qid, state="testing", pid=os.getpid())
            d = TP.tdir(sym) if tick else MP.pack_dir(sym); meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
            D = MP.use(meta, d, E, K, TMX, H)
            TM, BID, ASK, n_bad, END = TP.real_ticks(meta, d) if tick else MP.synthetic_ticks(D, meta)
            K.install_nopause_gate()
            cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": BAL}), drag=0.0, limits_live=1))
            opps, bars = E.streams(cfg0, D)
            cached = pickle.load(open(K.CACHE, "rb")); S_idx = cached["states"]
            if cached.get("bars_sha") != meta.get("sha256"):          # never read a cache against other bars
                raise RuntimeError("pack cache does not match its bars - rebuild the pack")
            S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
            reg = json.load(open(REG, encoding="utf-8")); robots = {r["id"]: r for r in reg.get("robots") or []}
            r = robots.get(rid)
            if not r:
                mq_set(qid, state="error", err="robot_gone"); continue
            parts = resolve(rid, robots); parent = r.get("parent") or "owl"
            PCS = {p["id"]: p for p in reg.get("pieces") or []}
            t0 = time.time()
            global DRAG
            DRAG = 0.0          # cost: the market's own spread is in bid/ask; BTC's measured slippage does not transfer
            out = run_robot_and_parent(parts, resolve(parent, robots), PCS, TM, BID, ASK, END, opps, bars, S)
            res = {"id": rid, "parent": parent, "parts": parts, "market": sym, "market_name": meta.get("description") or sym,
                   "server": meta.get("server"), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "balance": BAL, "drag": 0.0, "fills": "ticks" if tick else "bars", "risk_factor": meta["m"],
                   "source": ("%s %s (every broker tick, lossless)" % (meta.get("server"), meta.get("source_symbol"))) if tick else meta.get("server"),
                   "ticks": int(len(TM)),
                   "days": round((int(TM[-1]) - int(TM[0])) / 86400000, 1),
                   "window_utc": [time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[0]) / 1000)), time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[-1]) / 1000))],
                   "robot": out["robot"], "parent_result": out["parent"], "secs": round(time.time() - t0)}
            os.makedirs(RES, exist_ok=True)
            json.dump(res, open(os.path.join(RES, "%s@%s.json" % (rid, sym)), "w", encoding="utf-8"), indent=1)
            mq_set(qid, state="done", done_at=res["generated_at"], net=out["robot"]["net"], parent_net=out["parent"]["net"])
            nm = r.get("name_fr") or r.get("name") or rid
            push(job.get("uid"), "Test terminé · " + sym, "« %s » sur %s : %+.2f $ (le parent : %+.2f $), à risque égal au test Bitcoin." % (
                nm, sym, out["robot"]["net"], out["parent"]["net"]))
            mlog("%s @ %s: robot net %.2f vs parent %.2f (%d trades)" % (rid, sym, out["robot"]["net"], out["parent"]["net"], out["robot"]["trades"]))
            if out["robot"]["net"] > 0:
                random_control(rid, sym, job.get("uid"), nm)
        except BaseException as e:                           # SystemExit from a missing symbol included
            mq_set(qid, state="error", err=str(e)[:200])
            push(job.get("uid"), "Test impossible · " + sym, "Le test n’a pas pu se faire : " + str(e)[:120])
            mlog("%s @ %s: ERROR %r" % (rid, sym, e))


CONTROL_SEEDS = 40
HERE = os.path.dirname(os.path.abspath(__file__))


def _free_gb():
    import ctypes
    class _MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = _MS(); m.dwLength = ctypes.sizeof(_MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 2**30


def _control_running():
    import subprocess
    try:
        o = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "@(Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -like '*random_control_market*' -or $_.CommandLine -like '*ctrl_split*') -and $_.CommandLine -notlike '*when_free*' }).Count"],
                           capture_output=True, text=True, timeout=90, creationflags=0x08000000)
        return int((o.stdout or "0").strip() or 0) > 0
    except Exception:
        return True                              # cannot tell = assume busy


def _wait_room(rid, sym, need=4.5, hours=6):
    t0 = time.time()
    while time.time() - t0 < hours * 3600:
        if _free_gb() >= need and not _control_running():
            return True
        time.sleep(120)
    return False


def random_control(rid, sym, uid, nm):
    """2026-10-15 (owner's system rule, live/owl_markets.py): a market is traded for real only when the robot's test
    made money AND its entries beat random ones. 2026-10-18 (owner: "build it"): the check is now 100 draws, at most 5
    random robots may do as well, the 6th stops it; it can take a day or two, so it is no longer run inside this lane:
    it is queued (study/luck_queue.py, one at a time, only with room, each draw saved, restarts after a reboot) and
    shown on the robot page like a check asked from there; the server sends the notice when it ends."""
    try:
        old = os.path.join(HERE, "random_control_%s_%s.json" % (rid, sym))
        if os.path.exists(old):
            os.remove(old)                       # an old verdict must never stand for a new test
        import luck_queue as LQ
        LQ.add(sym, rid, fresh=True)             # a new market test = a new luck test, never mixed with old draws
        cf = os.path.join(LIVE, "robots", "controls.json")
        try:
            q = json.load(open(cf, encoding="utf-8"))
        except Exception:
            q = []
        q.append({"rid": rid, "sym": sym, "uid": uid, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "t": time.time(),
                  "name": "luck_%s_%s" % (rid, sym), "luck": True})
        json.dump(q[-60:], open(cf + ".tmp", "w", encoding="utf-8"), indent=1)
        os.replace(cf + ".tmp", cf)
        mlog("%s @ %s: luck test queued (100 draws, journal)" % (rid, sym))
    except BaseException as e:
        mlog("%s @ %s: control ERROR %r" % (rid, sym, e))


class _NoBtc(Exception):
    pass


if __name__ == "__main__":
    if "--markets" in ARGS:                                  # child process: the parent holds the lock
        run_markets(); sys.exit(0)
    if "--fast" in ARGS:                                     # the fast lane: its own lock, prepared markets only
        if os.path.exists(FAST_LOCK) and time.time() - os.path.getmtime(FAST_LOCK) < 1800:
            print("fast lane already running"); sys.exit(0)
        open(FAST_LOCK, "w").write(str(os.getpid()))
        try:
            run_markets(fast=True)
        finally:
            try: os.remove(FAST_LOCK)
            except Exception: pass
        sys.exit(0)
    if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 3 * 3600:
        print("another run is in progress"); sys.exit(0)
    open(LOCK, "w").write(str(os.getpid()))
    RUN_T0 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        reg = json.load(open(REG, encoding="utf-8")); robots = {r["id"]: r for r in reg.get("robots") or []}
        todo = ARGS[1:] or [r["id"] for r in reg.get("robots") or [] if r.get("stage") == "queued" or r.get("retest")]   # 2026-10-18: re-tests keep their stage
        if not todo:
            print("nothing queued"); raise _NoBtc()
        os.makedirs(RES, exist_ok=True)
        K.install_nopause_gate()
        TM, BID, ASK, n_bad, END = E.load_ticks()
        cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": BAL}), drag=0.0, limits_live=1))
        opps, bars = E.streams(cfg0, E.R)
        cached = pickle.load(open(K.CACHE, "rb")); S_idx = cached["states"]
        S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
        done = set()
        while todo:
          rid = todo.pop(0)
          if rid in done:
            continue
          done.add(rid)
          if not todo and not ARGS[1:]:
            # robots queued while this run was going: test them too before stopping
            _r2 = json.load(open(REG, encoding="utf-8"))
            todo += [x["id"] for x in _r2.get("robots") or [] if (x.get("stage") == "queued" or x.get("retest")) and x["id"] not in done]
            robots = {x["id"]: x for x in _r2.get("robots") or []}; reg = _r2
          if True:
            r = robots.get(rid)
            if not r:
                continue
            t0 = time.time()
            parts = resolve(rid, robots); parent = r.get("parent") or "owl"
            PCS = {p["id"]: p for p in json.load(open(REG, encoding="utf-8")).get("pieces") or []}   # fresh: pieces made meanwhile
            missing = [v for k, v in parts.items() if k != "money" and k != "filters" and (PCS.get(v) or {}).get("status") in ("pending", "to_build", None)]
            if missing:
                print(rid, "skipped: pieces not testable yet", missing, flush=True); continue
            out = run_robot_and_parent(parts, resolve(parent, robots), PCS, TM, BID, ASK, END, opps, bars, S)
            res = {"id": rid, "parent": parent, "parts": parts, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "balance": BAL, "drag": DRAG, "days": round((int(TM[-1]) - int(TM[0])) / 86400000, 1),
                   "window_utc": [time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[0]) / 1000)), time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[-1]) / 1000))],
                   "robot": out["robot"], "parent_result": out["parent"], "secs": round(time.time() - t0)}
            json.dump(res, open(os.path.join(RES, rid + ".json"), "w", encoding="utf-8"), indent=1)
            reg = json.load(open(REG, encoding="utf-8"))           # re-read: the app may have added robots meanwhile
            for x in reg.get("robots") or []:
                if x["id"] == rid and x.get("stage") in ("queued", "testing", None):
                    x["stage"] = "tested"; x["tested_at"] = res["generated_at"]
                if x["id"] == rid and x.get("retest"):
                    x.pop("retest", None); x["tested_at"] = res["generated_at"]
            used = set(v for k, v in parts.items() if k not in ("filters", "money")) | set(parts.get("filters") or [])
            for pc in reg.get("pieces") or []:          # a new rule piece becomes "tested" once a robot using it was tested
                if pc.get("id") in used and pc.get("status") == "new":
                    pc["status"] = "tested"
            json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(rid, "robot net %.2f vs parent %.2f (%ds)" % (out["robot"]["net"], out["parent"]["net"], res["secs"]), flush=True)
    except _NoBtc:
        pass
    finally:
        # 2026-10-14: then the other markets, in their OWN process (they re-point the engine's data), under
        # this run's lock so a market build and a BTC test never run at the same time
        try:
            if any(x.get("state") in ("queued", "building", "testing") for x in mq_load()):
                import subprocess
                subprocess.run([sys.executable, os.path.abspath(__file__), "--markets"], cwd=os.path.dirname(os.path.abspath(__file__)))
        except Exception as e:
            print("markets:", e, flush=True)
        try: os.remove(LOCK)
        except Exception: pass
        # anything queued meanwhile (a robot queued during a long market build) gets its own run
        try:
            _rq = json.load(open(REG, encoding="utf-8"))
            # only what was queued AFTER this run started: a robot that stays queued (a piece not testable
            # yet) must not make the runner respawn itself forever
            if any((x.get("stage") == "queued" or x.get("retest")) and (x.get("queued_at") or "") > RUN_T0 for x in _rq.get("robots") or [])                     or any(x.get("state") == "queued" and (x.get("at") or "") > RUN_T0 for x in mq_load()):
                import subprocess
                subprocess.Popen([sys.executable, os.path.abspath(__file__)], cwd=os.path.dirname(os.path.abspath(__file__)), creationflags=0x08000000)
        except Exception:
            pass
