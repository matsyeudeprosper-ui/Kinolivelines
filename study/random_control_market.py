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


MAXN, ALLOW, ROOM_GB = 100, 5, 1.2         # pause line measured WITH our own ~1.3 GB held; when_free kills at 0.9
JDIR = os.path.join(HERE, "luck")


def journal():
    import msvcrt
    from when_free import free_gb
    os.makedirs(JDIR, exist_ok=True)
    base = os.path.join(JDIR, "%s_%s" % (rid, sym))
    jp, sp = base + ".jsonl", base + ".status.json"
    lk = open(base + ".lock", "w")
    try:
        msvcrt.locking(lk.fileno(), msvcrt.LK_NBLCK, 1)       # one process per journal; the OS frees it if we die
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
            st["eta_h"] = round((MAXN - len(rows)) * st["sec_per_draw"] / 3600, 1)     # worst case: no early stop
        json.dump(st, open(sp + ".tmp", "w", encoding="utf-8"), indent=1)
        os.replace(sp + ".tmp", sp)

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
    done = {r["sd"] for r in rows}
    out = open(jp, "a", encoding="utf-8")
    sd = 0
    beats = lambda: sum(1 for r in rows if r["net"] >= rn)
    while len(rows) < MAXN and beats() <= ALLOW:
        if sd in done:
            sd += 1; continue
        while free_gb() < ROOM_GB:                            # live bots first: wait for memory between draws
            status("paused", rows, why="memory"); time.sleep(120)
        status("running", rows, why=None)
        t1 = time.time()
        r = draw(sd)
        row = {"kind": "draw", "sd": sd, "net": round(r["net"], 2), "trades": r["trades"], "pf": r["profit_factor"],
               "sec": round(time.time() - t1), "at": now()}
        out.write(json.dumps(row) + "\n"); out.flush(); os.fsync(out.fileno())
        rows.append(row); done.add(sd); sd += 1
        print("  draw %d: %.2f (%d as good as the robot, %d draws)" % (row["sd"], row["net"], beats(), len(rows)), flush=True)
    passed = beats() <= ALLOW
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
