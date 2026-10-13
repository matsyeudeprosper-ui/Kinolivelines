"""Owner 2026-10-12, first robot of the robot builder: "inherit everything from the main bot, change the
EXIT to: exit only when a CHoCH happens; money: no limit on the number of BOS during recovery".

Same harness as the proof page's "$200 reference test" (study/proof_current_rules.py): the `base`
package at $200, tick engine, live gate order, adaptive cap, daily balance scaling, causal + sticky
pullback structure, the trend / last-BOS filter - both cost bases. Arms (one tick clock, independent paths):

  today          the Owl as it runs today (target 0.8 x risk, stop at the protected point, recovery = flip + 1)
  exit_choch     EXIT part only: no target; the trade closes at the candle close that confirms a CHoCH against
                 it (a main-structure flip the other way), at the next quote, like any signal; the stop at the
                 protected point stays as the safety net; after the exit the reversal is judged like any entry
  money_all_bos  MONEY part only: during recovery every BOS is allowed (the 'all_bos' allowance)
  owner_robot    both: the owner's robot
  owner_no_stop  the owner's robot with NO stop at all (exit strictly at the CHoCH) - informational

    python robot_choch_exit.py
Writes study/robot_choch_exit.json.
"""
import sys, os, json, time, pickle
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import tick_engine as E
from tick_engine_matrix import summarise
from tick_engine_pbgate import PbGateArm
import tick_engine_pbgate_sticky as K
import harness as H
OUT = r"C:\Projects\KinoliveLines\study\robot_choch_exit.json"; BAL = 200.0
FAR = 1e7


class RobotArm(PbGateArm):
    """a PbGateArm whose EXIT part can be swapped: exit='target' (today) or 'choch'; stop='protected' or 'none'"""
    def __init__(self, name, cfg, bars, S, exit="target", stop="protected", allowance="current", gate="trend", **kw):
        super().__init__(name, cfg, bars, gate, S, allowance=allowance, **kw)
        self.exit_mode, self.stop_mode = exit, stop
        self.n.update({"choch_exits": 0, "choch_exit_wins": 0, "stop_exits": 0})

    def size_at_fill(self, setup, fill_px, frozen):
        pos = super().size_at_fill(setup, fill_px, frozen)
        if pos is not None:
            d = pos["d"]
            if self.exit_mode == "choch": pos["tp"] = pos["e"] + d * FAR          # no target
            if self.stop_mode == "none": pos["sl"] = pos["e"] - d * FAR           # no stop (sizing kept the protected-point risk)
        return pos

    def signal(self, o, k, TM, BID, ASK):
        p = self.pos
        if p is not None and self.exit_mode in ("choch", "target_choch") and o["flip"] and o["d"] == -p["d"]:
            d = p["d"]; xq = BID[k] if d == 1 else ASK[k]
            prof = d * (xq - p["e"]) * p["lot"] + sum(d * (xq - ad["e"]) * ad["lot"] * ad["n"] for ad in p["adds"])
            self.n["choch_exits"] += 1; self.n["choch_exit_wins"] += 1 if prof > 0 else 0
            self.close(p, xq, int(TM[k]), prof > 0)
        super().signal(o, k, TM, BID, ASK)       # the reversal is then judged like any other entry


def run(cfg, TM, BID, ASK, END, opps, bars, S):
    kw = dict(order="live", cap_rule="adaptive", cap="on")
    arms = [RobotArm("today", cfg, bars, S, **kw),
            RobotArm("exit_choch", cfg, bars, S, exit="choch", **kw),
            RobotArm("money_all_bos", cfg, bars, S, allowance="all_bos", **kw),
            RobotArm("owner_robot", cfg, bars, S, exit="choch", allowance="all_bos", **kw),
            RobotArm("owner_no_stop", cfg, bars, S, exit="choch", stop="none", allowance="all_bos", **kw)]
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
    T1 = int(TM[-1]); TMID = (int(TM[0]) + T1) // 2
    out = {}
    for arm in arms:
        a = summarise(arm, TM, BID, ASK, END, TMID)
        cur = 0.0; curve = {}
        for t in a["trades_list"]:
            cur += t["pnl"]; curve[time.strftime("%Y-%m-%d", time.gmtime(t["tc"] / 1000))] = round(cur, 2)
        pn = [t["pnl"] for t in a["trades_list"]]; streak = mx = 0
        for p in pn:
            streak = streak + 1 if p <= 0 else 0; mx = max(mx, streak)
        hold = sorted((t["tc"] - (t.get("fill_ms") or t["tc"])) / 60000.0 for t in a["trades_list"])
        out[arm.name] = {k: a[k] for k in ("net", "net_with_open_mtm", "cc_dd", "mtm_dd", "trades", "wins", "win_rate", "profit_factor", "first_half", "later_half")}
        out[arm.name].update({"curve": sorted(curve.items()), "pnls": [round(p, 2) for p in pn], "max_loss_streak": mx,
                              "best": max(pn) if pn else None, "worst": min(pn) if pn else None,
                              "hold_median_min": round(hold[len(hold) // 2], 1) if hold else None,
                              "counts": {k: v for k, v in a["counts"].items() if k in ("choch_exits", "choch_exit_wins", "admitted_by_allowance", "debt_gate", "kills", "fills")}})
    return out


if __name__ == "__main__":
    t00 = time.time()
    K.install_nopause_gate()
    TM, BID, ASK, n_bad, END = E.load_ticks()
    cfg_b = H.package_cfg("base", {"balance": BAL}); cfg_b.update({"scale_lot": 1, "scale_daily": 1}); cfg0 = H.cfg_strict(dict(cfg_b, drag=0.0, limits_live=1))
    opps, bars = E.streams(cfg0, E.R)
    cached = pickle.load(open(K.CACHE, "rb")); S_idx = cached["states"]
    assert all(o["i"] in S_idx for o in opps), "the saved sticky structure does not cover every opportunity"
    S = {o["t"]: S_idx[o["i"]] for o in opps}
    print("ticks %d, opportunities %d, flips %d (%.0fs)" % (len(TM), len(opps), sum(1 for o in opps if o["flip"]), time.time() - t00), flush=True)
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "balance": BAL, "package": "base",
           "days": round((int(TM[-1]) - int(TM[0])) / 86400000, 1),
           "window_utc": [time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[0]) / 1000)), time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[-1]) / 1000))],
           "engine": "tick engine, live gate order, adaptive cap, daily scaling, sticky pullback structure, trend / last-BOS filter (same as proof_current_rules.py)",
           "rows": {}}
    for drag in (0.35, 0.0):
        cfg = H.cfg_strict(dict(cfg_b, drag=drag, limits_live=1)); t0 = time.time()
        res["rows"]["%.2f" % drag] = run(cfg, TM, BID, ASK, END, opps, bars, S)
        for nm, a in res["rows"]["%.2f" % drag].items():
            print("drag %.2f %-14s net %8.2f cc_dd %7.2f mtm_dd %7.2f trades %3d wr %s pf %s h1 %7.2f h2 %7.2f hold %s | %s (%.0fs)" % (
                drag, nm, a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["win_rate"], a["profit_factor"], a["first_half"], a["later_half"], a["hold_median_min"], a["counts"], time.time() - t0), flush=True)
        json.dump(res, open(OUT, "w"), indent=1)
    print("DONE ->", OUT, "(%.0fs)" % (time.time() - t00), flush=True)
