"""2026-11-01 (owner: "the builder must build rules that depend on the LAST TRADE'S RESULT"): a SMALL bench check of the
robot builder's bench (robot_runner.arm_for + DslArm), on the last DAYS of the recorded ticks only.

    python robot_after_check.py <tag> [days] [robot id ...]
Writes study/robot_after_check_<tag>.json: every robot's full trade list (and counts). Run it with the old code
(tag "before") and the new code (tag "after") and compare - robots without the new fields must give the SAME trades.
The robot "owner-turn" (built here, not in robots.json) is the owner's rule: the 2-chart entry, 1R, lot 0.01; after a
stop-out the reverse trade on the next structure break, 2R. Heavy-ish (the harness streams): run it via when_free.py.
"""
import sys, os, json, time, pickle
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import robot_runner as RR
E, H, K = RR.E, RR.H, RR.K
HERE = os.path.dirname(os.path.abspath(__file__))

# the owner's rule as a robot (parts in robots.json form: piece ids + the after_loss block)
OWNER_TURN = {"entry": "p-bougie-du-haut-puis-boug", "stop": "p-stop-derriere-la-zone", "exit": "objectif-1r", "filters": [],
              "money": "simple",
              "after_loss": {"entry": "p-toute-cassure-bos-ou-cho", "stop": "point-protege", "direction": "reverse", "target": 2.0}}
# the same idea written as a TARGET FORMULA only (no after_loss): 2R after a stop-out, else 1R
TARGET_FX = {"entry": "p-bougie-du-haut-puis-boug", "stop": "p-stop-derriere-la-zone", "exit": "p-target-fx", "filters": [], "money": "simple"}
EXTRA_PIECES = [{"id": "p-target-fx", "type": "exit", "status": "tested",
                 "rule": {"target": "2 if last_hit_sl else 1", "choch": False, "time_min": None, "breakeven_at": None}}]


def run(arms, TM, BID, ASK, END, opps, bars):
    """robot_runner.run_pair's loop, keeping the arms (their trade lists)"""
    elig = [((o["t"] + 60) * 1000 + E.SIGNAL_MS, o) for o in opps]; ei = 0
    touches = sorted((t * 1000 + 60000, 1) for t, (touched, nv) in bars.items() if touched and t * 1000 + 60000 >= int(TM[0])); ti = 0
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
    return arms


def compare(a, b):
    """robots in both files: identical trade lists? + the owner's rule: every stop-out -> reverse after-loss trade at 2R"""
    A = json.load(open(os.path.join(HERE, "robot_after_check_%s.json" % a))); B = json.load(open(os.path.join(HERE, "robot_after_check_%s.json" % b)))
    ok = True
    for rid, x in A["robots"].items():
        y = B["robots"].get(rid)
        if y is None:
            continue
        same = json.dumps(x["trades"], sort_keys=True) == json.dumps(y["trades"], sort_keys=True)
        ok &= same
        print("%-28s %s: %d trades net %.2f vs %d trades net %.2f" % (rid, "IDENTICAL" if same else "DIFFERENT", x["n"], x["net"], y["n"], y["net"]))
    T = (B["robots"].get("owner-turn") or {}).get("trades") or []
    seq = 0
    for p, q in zip(T, T[1:]):
        if p.get("hit_sl") and p["pnl"] < 0 and not p.get("al"):
            r = abs(q["tp"] - q["e"]) / max(1e-9, abs(q["e"] - q["sl"]))
            good = q.get("al") and q["d"] == -p["d"] and abs(r - 2.0) < 0.02
            seq += 1 if good else 0
            if seq <= 3 or not good:
                print("  stop-out %s %s e %.2f sl %.2f pnl %.2f  ->  next %s %s e %.2f sl %.2f tp %.2f (%.2fR) after-loss=%s pnl %.2f %s" % (
                    time.strftime("%m-%d %H:%M", time.gmtime(p["tc"] / 1000)), "BUY" if p["d"] == 1 else "SELL", p["e"], p["sl"], p["pnl"],
                    time.strftime("%m-%d %H:%M", time.gmtime((q.get("fill_ms") or q["tc"]) / 1000)), "BUY" if q["d"] == 1 else "SELL",
                    q["e"], q["sl"], q["tp"], r, bool(q.get("al")), q["pnl"], "OK" if good else "<-- NOT the rule"))
            ok &= bool(good)
    print("owner-turn: %d stop-outs followed by the reverse 2R trade" % seq)
    return ok and seq > 0


if __name__ == "__main__":
    if ARGS[1] == "compare":
        sys.exit(0 if compare(ARGS[2], ARGS[3]) else 1)
    tag = ARGS[1]; days = float(ARGS[2]) if len(ARGS) > 2 else 6.0
    ids = [a for a in ARGS[3:] if not a.startswith("--") and a not in ARGS[ARGS.index("--parts-from") + 1:ARGS.index("--parts-from") + 2]] if "--parts-from" in ARGS else ARGS[3:]
    ids = ids or ["owl", "ma-methode-2-graphiques", "ma-methode-2-graphiques-2", "hourly-pullback"]
    t00 = time.time()
    K.install_nopause_gate()
    TM, BID, ASK, n_bad, END = E.load_ticks()
    a_ms = int(END) - int(days * 86400000)
    w = TM >= a_ms; TM, BID, ASK = TM[w], BID[w], ASK[w]
    cfg0 = H.cfg_strict(dict(H.package_cfg("base", {"balance": RR.BAL}), drag=0.0, limits_live=1))
    opps, bars = E.streams(cfg0, E.R)
    cached = pickle.load(open(K.CACHE, "rb")); S_idx = cached["states"]
    S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
    reg = json.load(open(RR.REG, encoding="utf-8")); robots = {r["id"]: r for r in reg.get("robots") or []}
    PCS = {p["id"]: p for p in reg.get("pieces") or []}
    for p in EXTRA_PIECES:
        PCS.setdefault(p["id"], p)
    print("ticks %d in the last %.1f days, opportunities %d (%.0fs)" % (len(TM), days, len(opps), time.time() - t00), flush=True)
    out = {"tag": tag, "days": days, "window_utc": [time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[0]) / 1000)),
                                                   time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[-1]) / 1000))], "robots": {}}
    todo = [(rid, RR.resolve(rid, robots)) for rid in ids if rid in robots]
    if "--parts-from" in ARGS:            # the robots' parts as recorded by an earlier run (robots.json may have changed since)
        _old = json.load(open(os.path.join(HERE, "robot_after_check_%s.json" % ARGS[ARGS.index("--parts-from") + 1])))["robots"]
        todo = [(rid, _old[rid]["parts"] if rid in _old else parts) for rid, parts in todo]
    if hasattr(RR, "robot_stream") and "--no-new" not in ARGS:      # the new fields exist only in the new code
        owl = RR.resolve("owl", robots)
        todo += [("owner-turn", dict(owl, **OWNER_TURN)), ("target-fx", dict(owl, **TARGET_FX))]
    for rid, parts in todo:
        t0 = time.time()
        stream = getattr(RR, "robot_stream", None)
        ro, rS = stream(parts, PCS, opps, S, bars) if stream else RR.robot_opps(parts, PCS, opps, S, bars)
        ro = [o for o in ro if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= a_ms]
        arm = RR.arm_for(rid, parts, bars, rS, PCS, opps=opps)
        run([arm], TM, BID, ASK, END, ro, bars)
        tr = arm.trades
        out["robots"][rid] = {"parts": parts, "trades": tr, "n": len(tr), "net": round(arm.run, 2),
                              "counts": {k: v for k, v in arm.n.items() if k != "wait_s"}, "events": arm.events[:400]}
        print("%-28s trades %3d net %8.2f (%.0fs)" % (rid, len(tr), arm.run, time.time() - t0), flush=True)
    json.dump(out, open(os.path.join(HERE, "robot_after_check_%s.json" % tag), "w"), indent=1, default=str)
    print("DONE (%.0fs)" % (time.time() - t00), flush=True)
