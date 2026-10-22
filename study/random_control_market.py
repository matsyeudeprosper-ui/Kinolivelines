"""random_control_market.py (2026-10-14, owner: "run that control") - does a robot's ENTRY beat chance on a market?

Preregistered before any run: the robot is replayed on the market pack exactly as in its market test (same arm,
same filters, same recovery and money, same synthetic quotes, no extra drag). Each control run replaces the robot's
opportunity stream with the SAME NUMBER of opportunities at RANDOM closed bars and in a RANDOM direction:
  * each random opportunity copies a randomly drawn REAL opportunity's stop distance (|close - stop|), its flip flag
    and its market-state fields (awake, nv, mv2), so risk per trade and the gates' pass rates match the robot's;
  * the pullback (trend) state given to a random bar is the one at the last REAL opportunity before it;
  * level = the bar's close (never reused), hour / weekday from the bar's own time.
Reported: the robot's net, the control's distribution (100 seeds), and the robot's percentile. Verdict rule (fixed):
top 5 % -> the entries beat chance here; otherwise the market result is within luck.
    python random_control_market.py USTEC [robot id] [seeds]

2026-10-18 (owner: "build it") - JOURNAL MODE, the rule used from now on:
    python random_control_market.py XAUUSD owl-sans-orage --journal [--fresh] [--uid=u1] [--nm=name]
up to 100 draws; the robot passes only if at most 5 random robots do at least as well (= the 95th percentile on 100
draws). Each draw is appended to study/luck/<robot>_<SYM>.jsonl the moment it ends, so a crash or a reboot loses at
most the draw in progress and the next start continues where it stopped (draw k always uses seed 1000+k, so 60 more
draws on top of 40 = one run of 100). The 6th random robot that does as well ends the test at once (a fail cannot be
undone by later draws). Between draws it pauses while the VPS is short of memory (live bots first). A journal is
only continued on the SAME data: the market pack's sha256 and the robot's own replay must match its first line,
otherwise it stops with "data_changed" and never mixes two periods. Progress: study/luck/<robot>_<SYM>.status.json.
The verdict file random_control_<robot>_<SYM>.json is written only when the test ends.
"""
import sys, os, json, time, pickle, random, bisect
ARGS = list(sys.argv); sys.argv = ["x"]
FLAGS = {a.split("=", 1)[0]: (a.split("=", 1)[1] if "=" in a else True) for a in ARGS if a.startswith("--")}
ARGS = [a for a in ARGS if not a.startswith("--")]
if FLAGS.get("--journal"):
    # 2026-10-19: take the journal's lock BEFORE the 10-minute replay of the robot, so a second start leaves at once
    import msvcrt as _ms
    _jd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "luck"); os.makedirs(_jd, exist_ok=True)
    _LOCK = open(os.path.join(_jd, "%s_%s.lock" % (ARGS[2] if len(ARGS) > 2 else "owl", (ARGS[1] if len(ARGS) > 1 else "USTEC").upper())), "w")
    try:
        _ms.locking(_LOCK.fileno(), _ms.LK_NBLCK, 1)
    except OSError:
        print("already running"); sys.exit(0)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import robot_runner as RR
import market_pack as MP
import tick_pack as TP          # 2026-10-16: the luck check uses the SAME data as the test it checks
import tick_engine_matrix as TMX
from datetime import datetime, timezone
E, K, H = RR.E, RR.K, RR.H

sym = (ARGS[1] if len(ARGS) > 1 else "USTEC").upper()
rid = ARGS[2] if len(ARGS) > 2 else "owl"
seeds = int(ARGS[3]) if len(ARGS) > 3 else 100
start = int(ARGS[4]) if len(ARGS) > 4 else 0       # 2026-10-14: seeds split over several processes (merge_random_control.py)
_tick = TP.tick_ready(sym)
d = TP.tdir(sym) if _tick else MP.pack_dir(sym); meta = json.load(open(os.path.join(d, "meta.json"), encoding="utf-8"))
D = MP.use(meta, d, E, K, TMX, H)
TM, BID, ASK, nb, END = TP.real_ticks(meta, d) if _tick else MP.synthetic_ticks(D, meta)
K.install_nopause_gate()
cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": RR.BAL}), drag=0.0, limits_live=1))
opps, bars = E.streams(cfg0, D)
cache = pickle.load(open(K.CACHE, "rb")); assert cache.get("bars_sha") == meta["sha256"]
S_idx = cache["states"]
S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
reg = json.load(open(RR.REG, encoding="utf-8")); robots = {r["id"]: r for r in reg.get("robots") or []}
PCS = {p["id"]: p for p in reg.get("pieces") or []}
parts = RR.resolve(rid, robots)
RR.DRAG = 0.0


def run(op, St):
    arm = RR.arm_for("robot", parts, bars, St, PCS)
    return RR.run_pair([arm], TM, BID, ASK, END, op, bars)["robot"]


t0 = time.time()
real = None
if not FLAGS.get("--helper"):                  # a helper only runs draws: the robot's own replay is the main's job
    real = run(opps, S)
    print("%s on %s: real net %.2f, %d trades (%.0fs)" % (rid, sym, real["net"], real["trades"], time.time() - t0), flush=True)

times = [int(x) for x in D["time"]]
real_t = [o["t"] for o in opps]; real_sorted = sorted(range(len(opps)), key=lambda k: opps[k]["t"])
rt_sorted = [opps[k]["t"] for k in real_sorted]
lo = 1440                                   # same warm-up as the harness (nervosity needs a day of bars)


def draw(sd):
    """one random-entry run, fully set by its seed: draw sd is the same run in any process, on any day"""
    rnd = random.Random(1000 + sd)
    idx = sorted(rnd.sample(range(lo, len(D) - 2), len(opps)))
    op, St = [], {}
    for i in idx:
        src = opps[rnd.randrange(len(opps))]
        t = times[i]; cl = float(D["close"][i]); dist = abs(src["cl"] - src["slp"]) or 1e-6
        dr = rnd.choice((1, -1))
        g = datetime.fromtimestamp(t, tz=timezone.utc)
        op.append({"t": t, "i": i, "d": dr, "slp": cl - dr * dist, "cl": cl, "flip": src["flip"], "awake": src["awake"],
                   "nv": src["nv"], "mv2": src["mv2"], "i_fire": False, "lvl": cl, "weekday": g.weekday(), "hour": g.hour, "minute": g.minute})
        j = bisect.bisect_right(rt_sorted, t) - 1
        St[t] = S.get(rt_sorted[j], (0, 0, None, None)) if j >= 0 else (0, 0, None, None)
    return run(op, St)


def summary(nets, trs, pfs):
    nets_s = sorted(nets)
    pct = 100.0 * sum(1 for x in nets if x < real["net"]) / len(nets)
    q = lambda p: nets_s[min(len(nets_s) - 1, int(p * len(nets_s)))]
    return {"symbol": sym, "robot": rid, "seeds": len(nets), "real": {k: real[k] for k in ("net", "trades", "win_rate", "profit_factor", "cc_dd", "first_half", "later_half")},
            "control": {"median": q(0.5), "p05": q(0.05), "p25": q(0.25), "p75": q(0.75), "p95": q(0.95), "mean": sum(nets) / len(nets),
                        "share_positive": sum(1 for x in nets if x > 0) / len(nets), "median_trades": sorted(trs)[len(trs) // 2] if trs else None,
                        "median_pf": sorted(pfs)[len(pfs) // 2] if pfs else None},
            "percentile": pct, "verdict": "beats chance" if pct >= 95 else "within luck", "nets": nets,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def pack_building():
    """a market pack is being built (study/markets/_building.json, under 5 h old and its process alive)"""
    f = os.path.join(HERE, "markets", "_building.json")
    try:
        b = json.load(open(f))
    except Exception:
        return False
    if time.time() - float(b.get("t") or 0) > 5 * 3600:
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(b.get("pid") or 0))
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259                             # STILL_ACTIVE
    except Exception:
        return True


MAXN, ALLOW, ROOM_GB = 100, 5, 1.2         # pause line measured WITH our own ~1.3 GB held; when_free kills at 0.9
JDIR = os.path.join(HERE, "luck")
# 2026-10-22 (owner, after the VPS went to 18 GB / 8 cores: "yes" to 3 draws at once + "leave enough memory for
# research"): the main process starts up to 2 HELPERS that run draws beside it. A helper starts only with >= 6.5 GB
# free and no research job running, and leaves (giving its ~1.3 GB back) as soon as free memory drops under 5 GB or
# research starts - research needs 4.5 GB (when_free) and may now run beside a luck test. Draw k is still seed
# 1000+k, so who runs it changes nothing; each seed is claimed once (a file in <base>.claims), rows are appended
# under a lock and read back deduplicated by seed.
WORKERS, HELPER_START_GB, RESEARCH_GB = 3, 6.5, 5.0
BASE = os.path.join(JDIR, "%s_%s" % (rid, sym))
JP, CDIR = BASE + ".jsonl", BASE + ".claims"


def jrows():
    rows, seen = [], set()
    try:
        for x in open(JP, encoding="utf-8"):
            try:
                r = json.loads(x)
            except Exception:
                continue                                      # a line cut by a crash: that draw runs again
            if r.get("kind") == "draw" and r.get("sd") not in seen:
                seen.add(r.get("sd")); rows.append(r)
    except OSError:
        pass
    return rows


def jappend(row):
    import msvcrt
    with open(JP + ".wlock", "w") as lk:                       # main and helpers append one row at a time
        while True:
            try:
                msvcrt.locking(lk.fileno(), msvcrt.LK_NBLCK, 1); break
            except OSError:
                time.sleep(0.2)
        try:
            with open(JP, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n"); f.flush(); os.fsync(f.fileno())
        finally:
            lk.seek(0); msvcrt.locking(lk.fileno(), msvcrt.LK_UNLCK, 1)


def over(rows, rn):
    b = sum(1 for r in rows if r["net"] >= rn)
    return len(rows) >= MAXN or b > ALLOW or (len(rows) >= 10 and b >= 3) or (len(rows) >= 20 and b >= 4)   # 10-21 item 2


def claim_next(rows):
    """the lowest seed nobody has run or claimed; None when the claimed ones already reach the 100"""
    os.makedirs(CDIR, exist_ok=True)
    done = {r["sd"] for r in rows}
    flying = [f for f in os.listdir(CDIR) if f.isdigit() and int(f) not in done]
    if len(done) + len(flying) >= MAXN:
        return None
    sd = 0
    while True:
        if sd not in done:
            try:
                os.close(os.open(os.path.join(CDIR, str(sd)), os.O_CREAT | os.O_EXCL | os.O_WRONLY)); return sd
            except FileExistsError:
                pass
        sd += 1


def run_draw(sd):
    t1 = time.time()
    r = draw(sd)
    row = {"kind": "draw", "sd": sd, "net": round(r["net"], 2), "trades": r["trades"], "pf": r["profit_factor"],
           "sec": round(time.time() - t1), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    jappend(row)
    return row


def pid_alive(pid):
    import ctypes
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    code = ctypes.c_ulong(); ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code)); ctypes.windll.kernel32.CloseHandle(h)
    return code.value == 259


def research_running():
    from when_free import heavy_running
    return heavy_running(ignore_luck=True)


def helper():
    """a helper: claim, draw, append - until the test is over, the main is gone, memory is short or research starts"""
    from when_free import free_gb
    main_pid = int(FLAGS["--helper"]); n = 0
    rn = None
    try:
        rn = float(json.loads(open(JP, encoding="utf-8").readline())["real"])
    except Exception:
        print("helper: no journal head"); return 0
    while pid_alive(main_pid):
        rows = jrows()
        if over(rows, rn):
            break
        f = free_gb()
        if f < RESEARCH_GB:
            print("helper: %.1f GB free - leaving the room to research and the bots" % f, flush=True); break
        busy = research_running()
        if busy:
            print("helper: research running - stepping aside (%s)" % busy[0], flush=True); break
        sd = claim_next(rows)
        if sd is None:
            break
        row = run_draw(sd); n += 1
        print("  helper draw %d: %.2f" % (row["sd"], row["net"]), flush=True)
    print("helper %d out after %d draws" % (os.getpid(), n), flush=True)
    return 0


HELPERS = []


def helpers_alive():
    HELPERS[:] = [p for p in HELPERS if p.poll() is None]
    return len(HELPERS)


def maybe_helpers():
    """start helpers up to WORKERS-1 while there is clear room and no research job"""
    import subprocess
    from when_free import free_gb
    if helpers_alive() >= WORKERS - 1 or free_gb() < HELPER_START_GB or pack_building() or research_running():
        return
    cmd = [sys.executable, "-u", os.path.abspath(__file__), sym, rid, "--helper=%d" % os.getpid()]
    log = open(BASE + ".log", "a", encoding="utf-8")
    flags = 0x00000008 | 0x08000000 | 0x00000200 | 0x00004000         # detached, no window, own group, below normal
    p = subprocess.Popen(cmd, cwd=HERE, stdout=log, stderr=subprocess.STDOUT, creationflags=flags, close_fds=True)
    HELPERS.append(p)
    print("  helper started (pid %d, %.1f GB free)" % (p.pid, free_gb()), flush=True)


def journal():
    import msvcrt
    from when_free import free_gb
    os.makedirs(JDIR, exist_ok=True)
    base = os.path.join(JDIR, "%s_%s" % (rid, sym))
    jp, sp = base + ".jsonl", base + ".status.json"
    if "_LOCK" not in globals():                              # (the lock is taken at start in journal mode)
        lk = open(base + ".lock", "w")
        try:
            msvcrt.locking(lk.fileno(), msvcrt.LK_NBLCK, 1)   # one process per journal; the OS frees it if we die
        except OSError:
            print("already running"); return 0
    rn = round(real["net"], 2)
    now = lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    head = {"kind": "head", "real": rn, "trades": real["trades"], "sha": meta.get("sha256"), "opps": len(opps), "bars": len(D),
            "max": MAXN, "allow": ALLOW, "at": now()}
    st = {"rid": rid, "sym": sym, "real": rn, "max": MAXN, "allow": ALLOW, "started": now()}

    def status(state, rows, **kw):
        own = [r["sec"] for r in rows if r.get("sec")]
        beats = sum(1 for r in rows if r["net"] >= rn)
        st.update(kw, state=state, n=len(rows), beats=beats, updated=now(),
                  sec_per_draw=round(sum(own) / len(own)) if own else None,
                  best=max((r["net"] for r in rows), default=None))
        if st["sec_per_draw"] and state in ("running", "paused"):
            st["eta_h"] = round((MAXN - len(rows)) * st["sec_per_draw"] / 3600 / max(1, st.get("workers") or 1), 1)     # worst case: no early stop
        with open(sp + ".tmp", "w", encoding="utf-8") as f:
            json.dump(st, f, indent=1)
        for k in range(20):                                   # 2026-10-22: a reader holding the file (the app) made the
            try:                                              # replace fail with WinError 5 and killed the test at draw 37
                os.replace(sp + ".tmp", sp); break
            except PermissionError:
                time.sleep(0.25)

    if FLAGS.get("--fresh"):
        for f in (jp, sp):
            if os.path.exists(f):
                os.remove(f)
    rows = []
    if os.path.exists(jp):
        L = []
        for x in open(jp, encoding="utf-8"):
            try:
                L.append(json.loads(x))
            except Exception:
                pass                                          # a line cut by a crash: that draw runs again
        h = L[0] if L and L[0].get("kind") == "head" else {}
        if h.get("sha") != head["sha"] or abs(float(h.get("real", 1e9)) - rn) > 0.005 or h.get("opps") != len(opps):
            status("data_changed", [], was=h, now=head)
            print("journal is for other data: %s -> %s" % (h, head)); return 3
        rows = [x for x in L[1:] if x.get("kind") == "draw"]
    else:
        # continue an earlier one-shot run on the same data (it used seeds 0..n-1, start 0)
        try:
            old = json.load(open(os.path.join(HERE, "random_control_%s_%s.json" % (rid, sym)), encoding="utf-8"))
            if abs(float(old["real"]["net"]) - rn) <= 0.005 and old.get("nets") and len(old["nets"]) == int(old["seeds"]):
                rows = [{"kind": "draw", "sd": k, "net": x, "imported": old.get("generated_at")} for k, x in enumerate(old["nets"])]
                head["imported"] = {"n": len(rows), "from": old.get("generated_at")}
        except Exception:
            pass
    with open(jp + ".tmp", "w", encoding="utf-8") as f:       # rewrite clean (drops a cut last line)
        for x in [head] + rows:
            f.write(json.dumps(x) + "\n")
    os.replace(jp + ".tmp", jp)
    import shutil
    shutil.rmtree(CDIR, ignore_errors=True)                  # claims of a dead run: their seeds are simply free again
    beats = lambda: sum(1 for r in rows if r["net"] >= rn)
    hopeless = lambda: (len(rows) >= 10 and beats() >= 3) or (len(rows) >= 20 and beats() >= 4)    # 2026-10-21 owner list item 2
    while True:
        rows = jrows()
        if over(rows, rn):
            break
        while pack_building():                               # 2026-10-21: a member waits for a market pack - step aside
            status("paused", rows, why="market pack", workers=1 + helpers_alive()); time.sleep(60)
        while free_gb() < ROOM_GB:                            # live bots first: wait for memory between draws
            status("paused", rows, why="memory", workers=1 + helpers_alive()); time.sleep(120)
        maybe_helpers()
        status("running", rows, why=None, workers=1 + helpers_alive())
        sd = claim_next(rows)
        if sd is None:                                        # the last seeds are with the helpers: wait for them
            if not helpers_alive():
                shutil.rmtree(CDIR, ignore_errors=True)       # a helper died holding a claim: free its seed
            time.sleep(30); continue
        row = run_draw(sd)
        rows = jrows()
        print("  draw %d: %.2f (%d as good as the robot, %d draws)" % (row["sd"], row["net"], beats(), len(rows)), flush=True)
    for p in HELPERS:                                         # the verdict is in: draws still running would not count
        try:
            p.kill()
        except Exception:
            pass
    rows = jrows()
    if len(rows) > MAXN:
        rows = sorted(rows, key=lambda r: r["sd"])[:MAXN]
    passed = beats() <= ALLOW and not hopeless()
    res = summary([r["net"] for r in rows], [r["trades"] for r in rows if r.get("trades")], [r["pf"] or 0 for r in rows if "pf" in r])
    res.update(verdict="beats chance" if passed else "within luck", rule="%d draws, at most %d as good" % (MAXN, ALLOW),
               beats=beats(), stopped_early=len(rows) < MAXN)
    json.dump(res, open(os.path.join(HERE, "random_control_%s_%s.json" % (rid, sym)), "w"), indent=1)
    status("pass" if passed else "fail", rows)
    uid = FLAGS.get("--uid")
    if uid and uid is not True:
        nm = FLAGS.get("--nm") if FLAGS.get("--nm") not in (None, True) else rid
        if passed:
            RR.push(uid, "Nouveau marché autorisé · " + sym, "« %s » bat le hasard sur %s : %d tirages au hasard, %d seulement font aussi bien. "
                    "Les comptes qui font tourner ce robot tradent maintenant aussi ce marché." % (nm, sym, len(rows), beats()))
        else:
            RR.push(uid, "Contrôle terminé · " + sym, "« %s » sur %s : %d tirages au hasard font aussi bien (après %d tirages) : "
                    "dans la chance, ce marché reste en test." % (nm, sym, beats(), len(rows)))
    print(json.dumps({k: v for k, v in res.items() if k != "nets"}, indent=1))
    return 0


if FLAGS.get("--helper"):
    sys.exit(helper())
if FLAGS.get("--journal"):
    sys.exit(journal())

nets, pfs, trs = [], [], []
for sd in range(start, start + seeds):
    r = draw(sd)
    nets.append(r["net"]); pfs.append(r["profit_factor"] or 0); trs.append(r["trades"])
    if (sd - start + 1) % 5 == 0:
        print("  %d/%d seeds (%.0fs)" % (sd - start + 1, seeds, time.time() - t0), flush=True)

out = summary(nets, trs, pfs)
out["seeds"] = seeds
json.dump(out, open(os.path.join(HERE, "random_control_%s_%s%s.json" % (rid, sym, "_part%d" % start if len(ARGS) > 4 else "")), "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "nets"}, indent=1))
