"""Stage 2 (revised brief 2026-10-10): the shared-demo Compte curve as a PAUSE / RESUME gate
for new MAIN setups, on ONE declared cap-off follower configuration, as independently evolving
arms on the follower's tick clock. Development data. No live change.

Reference source (declared per run, see SOURCE):
  "demo_feed" : the dedicated demo's PACKAGE (`reference`, fixed 0.02, no account-money brakes)
                replayed by the same engine on the DEMO TERMINAL'S OWN bars and ticks
                (study/dev_bars_demo_u477508138.npz, study/ticks_u477508138/) - a labelled proxy
                for the demo's actual history (TOUCH entries are not modelled; bar-close signals)
  "std_feed"  : the same package replayed on the std feed (transfer check)
Only CLOSED reference outcomes with close time strictly earlier than the follower's MAIN signal
eligibility feed the pinned causal controller (compte_controller, compte-ctl-2); equal timestamps
are excluded (strictly earlier); an invalid / unavailable state PAUSES (conservative) and is counted.
Weak predicate (fixed): trend == -1 and choch != +1.

Follower arms (declared config: immediate entry, current recovery allowance, DAY CAP OFF - no
selection on results):
  no_pause     | global_pause (primary: pause BUY and SELL setups when the combined curve is weak)
  dir_pause    (secondary: pause a BUY only when the BUY curve is weak; a SELL only when the SELL curve is weak)
  thin_k_<phase> : outcome-independent thinning control - every k-th eligible setup paused, k from the
                 global arm's development pause rate (calibrated here, to be frozen before any fresh use)
The gate acts at MAIN signal eligibility only; open positions, their adds and an accepted pending setup
follow the unchanged corrected policy. The reference keeps trading throughout (its path never sees
the followers).
    python tick_engine_compte.py [--source demo_feed|std_feed] [regime ...]
"""
import sys, os, json, time, bisect, math
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import numpy as np
import tick_engine as E
from tick_engine_matrix import PolicyArm
from compte_controller import CompteController
SOURCE = ARGS[ARGS.index("--source") + 1] if "--source" in ARGS else "demo_feed"
FOLLOWER_POLICY = {"entry": "immediate", "allowance": "current", "cap": "off"}
WEAK = lambda st: st["trend"] == -1 and st["choch"] != 1
K_PHASES_MAX = 4


def reference_outcomes(source, drag):
    """closed outcomes of the reference package path: list of (tc_ms, pnl, d), chronological"""
    cfg, _ = E.effective_cfg(E.PR["reference_uncapped"], E.REGIMES["reference_uncapped"], drag)
    if source == "demo_feed":
        Rb = np.load(r"C:\Projects\KinoliveLines\study\dev_bars_demo_u477508138.npz")["R"]
        meta = json.load(open(r"C:\Projects\KinoliveLines\study\dev_bars_demo_u477508138.json"))
        TM, BID, ASK, nbad, END = E.load_ticks(r"C:\Projects\KinoliveLines\study\ticks_u477508138", int(E.R["time"][0]) * 1000, int(E.META["closed_bar_cutoff"]) * 1000)
        opps, bars = E.streams(cfg, Rb)
        row, _ = E.run_regime("reference_uncapped", drag, TM, BID, ASK, END, opps, bars, start_ms=int(E.R["time"][0]) * 1000)
        tr = row["baseline"]["trades_list"]
    else:
        TM, BID, ASK, nbad, END = E.load_ticks()
        opps, bars = E.streams(cfg)
        row, _ = E.run_regime("reference_uncapped", drag, TM, BID, ASK, END, opps, bars)
        tr = row["baseline"]["trades_list"]
    out = sorted(((int(x["tc"]), float(x["pnl"]), int(x["d"])) for x in tr), key=lambda z: (z[0], z[2]))
    return out, {"n": len(out), "net": round(sum(p for _, p, _ in out), 2), "feed": source}


class States:
    """causal controller states from the reference outcomes: everything with tc < t (strictly)"""
    def __init__(self, outcomes):
        self.o = outcomes; self.tc = [z[0] for z in outcomes]; self.cache = {}
    def at(self, t_ms):
        n = bisect.bisect_left(self.tc, int(t_ms))        # outcomes with tc < t_ms
        if n in self.cache: return self.cache[n]
        res = {}
        for name, flt in (("global", lambda d: True), ("buy", lambda d: d == 1), ("sell", lambda d: d == -1)):
            c = CompteController()
            for tc, p, d in self.o[:n]:
                if flt(d): c.feed(p)
            st = c.state
            # controller status: "ok" = usable; "invalid" = integrity failure (latched) -> PAUSE, conservative;
            # "no_data" / "warming" / "no_direction" = no information yet -> not weak (GO), counted apart
            res[name] = {"trend": st.get("trend", 0), "choch": st.get("choch", 0), "status": st.get("status"), "valid": st.get("status") != "invalid",
                         "informative": st.get("status") == "ok", "n": sum(1 for z in self.o[:n] if flt(z[2]))}
        res["last_close_ms"] = self.tc[n - 1] if n else None
        self.cache[n] = res; return res


class GatedArm(PolicyArm):
    def __init__(self, name, cfg, bars, mode, states, k=None, phase=0):
        super().__init__(name, cfg, dict(FOLLOWER_POLICY), bars)
        self.gmode, self.S, self.k, self.phase = mode, states, k, phase
        self.n.update({"paused": 0, "paused_invalid": 0, "eligible_for_gate": 0, "thinned": 0}); self.gate_log = []; self.elig_i = 0

    def signal(self, o, k, TM, BID, ASK):
        # the gate sits AFTER every ordinary gate and BEFORE the setup is created: evaluate on a dry pass
        if self.pos is not None or self.order is not None or self.pend is not None or self.dead: return super().signal(o, k, TM, BID, ASK)
        t_ms = int(TM[k]); self.n["eligible_for_gate"] += 1; self.elig_i += 1
        decision = "go"; st = None
        if self.gmode in ("global", "dir"):
            s = self.S.at(t_ms); st = s["global"] if self.gmode == "global" else (s["buy"] if o["d"] == 1 else s["sell"])
            if not st["valid"]: decision = "pause_invalid"
            elif st["informative"] and WEAK(st): decision = "pause"
            elif not st["informative"]: self.n["no_state"] = self.n.get("no_state", 0) + 1
            self.gate_log.append({"t": o["t"], "d": o["d"], "src_n": st["n"], "trend": st["trend"], "choch": st["choch"], "last_close_ms": s["last_close_ms"], "decision": decision})
        elif self.gmode == "thin" and self.k and (self.elig_i % self.k) == self.phase:
            decision = "thin"
        if decision == "pause": self.n["paused"] += 1; return
        if decision == "pause_invalid": self.n["paused_invalid"] += 1; return
        if decision == "thin": self.n["thinned"] += 1; return
        return super().signal(o, k, TM, BID, ASK)


def run_gated(uid, drag, TM, BID, ASK, END, opps, bars, S, k):
    cfg, rep = E.effective_cfg(E.PR[uid], E.REGIMES[uid], drag)
    arms = [GatedArm("no_pause", cfg, bars, "none", S), GatedArm("global_pause", cfg, bars, "global", S), GatedArm("dir_pause", cfg, bars, "dir", S)]
    if k and k >= 2:
        for ph in range(min(k, K_PHASES_MAX)): arms.append(GatedArm("thin_k%d_p%d" % (k, ph), cfg, bars, "thin", S, k, ph))
    elig = [((o["t"] + 60) * 1000 + E.SIGNAL_MS, o) for o in opps]; ei = 0
    touches = sorted((t * 1000 + 60000, 1) for t, (touched, nv) in bars.items() if touched); ti = 0
    n = len(TM); prev = int(TM[0])
    for kk in range(n):
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
    out = {}; T1 = int(TM[-1]); TMID = (int(TM[0]) + T1) // 2
    for arm in arms:
        mtm_open = arm.finish(TM, BID, ASK, END); tr = arm.trades
        out[arm.name] = {"net": round(arm.run, 2), "net_with_open_mtm": round(arm.run + mtm_open, 2), "cc_dd": round(E.dd_of(arm.pnls), 2), "mtm_dd": round(arm.mtm_dd, 2),
                         "trades": len(tr), "wins": arm.wins, "pnl_main": round(sum(x["pnl_main"] for x in tr), 2), "pnl_add": round(sum(x["pnl_add"] for x in tr), 2),
                         "risk_main": round(sum(x["risk"] for x in tr), 2), "first_half": round(sum(x["pnl"] for x in tr if x["tc"] < TMID), 2), "later_half": round(sum(x["pnl"] for x in tr if x["tc"] >= TMID), 2),
                         "counts": {kk2: v for kk2, v in arm.n.items() if kk2 != "wait_s"}, "gate_log": arm.gate_log[:600], "trades_list": tr}
    return out, rep


if __name__ == "__main__":
    want = [a for a in ARGS[1:] if not a.startswith("--") and a not in ("demo_feed", "std_feed")] or ["infinity", "u224016179", "bos"]
    outp = r"C:\Projects\KinoliveLines\study\tick_engine_compte_%s.json" % SOURCE
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": SOURCE, "follower_policy": FOLLOWER_POLICY, "weak_predicate": "trend == -1 and choch != +1", "rows": {}, "reference": {}}
    try: res["rows"] = json.load(open(outp))["rows"]
    except Exception: pass
    TM, BID, ASK, n_bad, END = E.load_ticks()
    print("follower ticks (std feed) %d" % len(TM), flush=True)
    for drag in (0.0, 0.35):
        outcomes, rinfo = reference_outcomes(SOURCE, drag); res["reference"]["%.2f" % drag] = rinfo
        print("reference (%s) drag %.2f: %d closed outcomes net %.2f" % (SOURCE, drag, rinfo["n"], rinfo["net"]), flush=True)
        S = States(outcomes)
        for uid in want:
            key = "%s|%.2f" % (uid, drag)
            if key in res["rows"]: print(key, "(cached)", flush=True); continue
            cfg0, _ = E.effective_cfg(E.PR[uid], E.REGIMES[uid], 0.0); opps, bars = E.streams(cfg0)
            # calibrate the thinning rate from the GLOBAL arm's development pause share (dry pass: state only)
            t0 = time.time(); pre, _ = run_gated(uid, drag, TM, BID, ASK, END, opps, bars, S, None)
            g = pre["global_pause"]["counts"]; rate = (g["paused"] + g["paused_invalid"]) / max(1, g["eligible_for_gate"]); k = int(round(1.0 / rate)) if rate > 0 else None
            out, rep = run_gated(uid, drag, TM, BID, ASK, END, opps, bars, S, k) if (k and k >= 2) else (pre, _)
            res["rows"][key] = {"effective": rep, "thin_k": k, "global_pause_rate": round(rate, 4), "arms": out}
            for name, a in out.items():
                c = a["counts"]
                print("%-18s drag %.2f %-14s | net %8.2f cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d main %8.2f adds %6.2f risk %6.0f | h1 %7.2f h2 %7.2f | eligible %3d paused %3d invalid %3d thinned %3d | %.0fs" % (
                    uid, drag, name, a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"], a["pnl_main"], a["pnl_add"], a["risk_main"], a["first_half"], a["later_half"], c["eligible_for_gate"], c["paused"], c["paused_invalid"], c["thinned"], time.time() - t0), flush=True)
            json.dump(res, open(outp, "w"), indent=1)
    print("DONE", flush=True)
