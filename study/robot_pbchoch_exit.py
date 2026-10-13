"""Owner 2026-10-13: "Owl CHoCH, but exit on the PULLBACK chart's CHoCH" (the main-structure CHoCH exit cut trades
short: 1 in 4 won). Same bench as robot_choch_exit.py / the proof page ($200 base, tick engine, live gate order,
adaptive cap, sticky pullback structure, trend filter, both cost bases).

The pullback chart's state (trend, pending CHoCH) is walked CAUSALLY and STICKY at every bar where the silence
filter keeps a new candle (the pullback chain can only change then), with the same warm-up and the same view
function as the trend filter (tick_engine_pbgate_sticky). A position is closed at the first such bar where the
pullback chart turns against it - a pending CHoCH the other way, or its trend flipping - at the next quote after
that candle closes (like any signal). The stop on the protected point stays as the safety net.

Arms:
  today              the Owl as it runs
  pb_exit            no target; exit at the pullback chart's CHoCH against the trade
  pb_exit_all_bos    + unlimited catch-up (the owner's Owl CHoCH with the pullback exit)
  pekos_pb_early     target 1.0 x risk + unlimited catch-up, closed EARLY if the pullback chart turns first
    python robot_pbchoch_exit.py
Writes study/robot_pbchoch_exit.json; the per-bar pullback states are cached in study/pb_bar_states_v1.pkl.
"""
import sys, os, json, time, pickle
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import numpy as np
import tick_engine as E
from tick_engine_matrix import summarise
import tick_engine_pbgate_sticky as K
import owl_chart_feed as F
import harness as H
from robot_choch_exit import RobotArm
OUT = r"C:\Projects\KinoliveLines\study\robot_pbchoch_exit.json"
BAR_CACHE = r"C:\Projects\KinoliveLines\study\pb_bar_states_v1.pkl"
BAL = 200.0


def fast_build(rows):
    """owl_chart_feed.build() on plain tuples (time, open, high, low, close) - same arithmetic, same rounding;
    the numpy-row version costs 90 ms per 8000-bar window. Checked equal in __main__ before use."""
    kept = []
    ref_h = ref_l = None
    for t, o, h, l, c in rows:
        if ref_h is None or c > ref_h or c < ref_l:
            kept.append([t, round(o, 2), round(h, 2), round(l, 2), round(c, 2), 1 if c >= o else -1])
            ref_h, ref_l = h, l
    return kept


def bar_states(limit=None):
    """{bar time: (pb trend, pending pb choch)} at every bar that adds a kept candle - causal + sticky walk"""
    warm_meta = json.load(open(K.WARM_NPZ.replace(".npz", ".json"))); W = np.load(K.WARM_NPZ)["R"]
    fp = K.fingerprint(warm_meta)
    try:
        c = pickle.load(open(BAR_CACHE, "rb"))
        if c.get("fingerprint") == fp and not limit:
            print("bar states reused (%d)" % len(c["states"]), flush=True); return c["states"]
    except Exception:
        pass
    R = E.R; WIN = K.WIN
    RW = np.concatenate([W, R]); off = len(W)
    TU = [(int(r["time"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])) for r in RW]
    for j in (WIN - 1, WIN + 777, len(RW) // 2, len(RW) - 1):        # the fast filter must equal the feed's, exactly
        assert fast_build(TU[j - WIN + 1:j + 1]) == F.build(RW[j - WIN + 1:j + 1]), "fast_build differs at %d" % j
    S = set(); out = {}; t0 = time.time(); last_kept = None
    end = len(RW) if not limit else min(len(RW), off + limit)
    for i in range(WIN - 1, end):
        kept = fast_build(TU[i - WIN + 1:i + 1])
        if len(kept) < 3: continue
        bk = []; dots, marks, trend, *_ = F.engine(kept, brk_out=bk)
        if trend: dots = [d for d in dots if d[2] == trend]
        S |= {t for t in ({d[0] for d in dots} | {m[0] for m in marks} | {b[0] for b in bk}) if t < kept[-1][0]}
        S = {t for t in S if t >= kept[0][0]}
        if i >= off and kept[-1][0] != last_kept:
            try:
                st = K.pb_view_sticky(kept, dots, marks, bk, S)
                out[TU[i][0]] = (int(st[0]), int(st[1]))
            except Exception:
                pass
        last_kept = kept[-1][0]
        if (i - WIN + 1) % 4000 == 0: print("bar walk %d / %d, states %d (%.0fs)" % (i - WIN + 1, end - WIN + 1, len(out), time.time() - t0), flush=True)
    if not limit:
        pickle.dump({"fingerprint": fp, "states": out}, open(BAR_CACHE, "wb"))
    return out


class PbExitArm(RobotArm):
    """exit part 'pb_choch' (no target) or 'target_pb' (target kept, early exit): close when the pullback chart
    turns against the open trade"""
    def __init__(self, name, cfg, bars, S, pbexit="none", **kw):
        super().__init__(name, cfg, bars, S, exit="choch" if pbexit == "pb_choch" else "target", **kw)
        self.pbexit = pbexit; self.n.update({"pb_exits": 0, "pb_exit_wins": 0})

    def signal(self, o, k, TM, BID, ASK):
        # the main-structure CHoCH exit of RobotArm must NOT fire here: only the pullback chart closes
        mode, self.exit_mode = self.exit_mode, "target"
        try:
            super().signal(o, k, TM, BID, ASK)
        finally:
            self.exit_mode = mode

    def pb_event(self, st, k, TM, BID, ASK):
        p = self.pos
        if p is None or self.pbexit == "none": return
        tr, ch = st; d = p["d"]
        if tr == -d or ch == -d:
            xq = BID[k] if d == 1 else ASK[k]
            prof = d * (xq - p["e"]) * p["lot"] + sum(d * (xq - ad["e"]) * ad["lot"] * ad["n"] for ad in p["adds"])
            self.n["pb_exits"] += 1; self.n["pb_exit_wins"] += 1 if prof > 0 else 0
            self.close(p, xq, int(TM[k]), prof > 0)


def run(cfg, cfg_pekos, TM, BID, ASK, END, opps, bars, S, PBS):
    kw = dict(order="live", cap_rule="adaptive", cap="on")
    arms = [PbExitArm("today", cfg, bars, S, **kw),
            PbExitArm("pb_exit", cfg, bars, S, pbexit="pb_choch", **kw),
            PbExitArm("pb_exit_all_bos", cfg, bars, S, pbexit="pb_choch", allowance="all_bos", **kw),
            PbExitArm("pekos_pb_early", cfg_pekos, bars, S, pbexit="target_pb", allowance="all_bos", **kw)]
    elig = [((o["t"] + 60) * 1000 + E.SIGNAL_MS, o) for o in opps]; ei = 0
    pbe = sorted(((t + 60) * 1000 + E.SIGNAL_MS, st) for t, st in PBS.items()); pi = 0
    touches = sorted((t * 1000 + 60000, 1) for t, (touched, nv) in bars.items() if touched); ti = 0
    prev = int(TM[0])
    for kk in range(len(TM)):
        t_ms = int(TM[kk]); gap_in = t_ms - prev; prev = t_ms
        for arm in arms: arm.roll(t_ms)
        while ti < len(touches) and touches[ti][0] <= t_ms:
            ti += 1
            for arm in arms:
                if arm.last_flip_t is not None and arm.cont_left < int(arm.c["n_cont"]): arm.cont_left = min(int(arm.c["n_cont"]), arm.cont_left + 1)
        while pi < len(pbe) and pbe[pi][0] <= t_ms:
            st = pbe[pi][1]; pi += 1
            for arm in arms: arm.pb_event(st, kk, TM, BID, ASK)
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
        pn = [t["pnl"] for t in a["trades_list"]]
        hold = sorted((t["tc"] - (t.get("fill_ms") or t["tc"])) / 60000.0 for t in a["trades_list"])
        out[arm.name] = {k: a[k] for k in ("net", "cc_dd", "mtm_dd", "trades", "wins", "win_rate", "profit_factor", "first_half", "later_half")}
        out[arm.name].update({"curve": sorted(curve.items()), "best": max(pn) if pn else None, "worst": min(pn) if pn else None,
                              "hold_median_min": round(hold[len(hold) // 2], 1) if hold else None,
                              "counts": {k: v for k, v in a["counts"].items() if k in ("pb_exits", "pb_exit_wins", "admitted_by_allowance", "kills", "fills")}})
    return out


if __name__ == "__main__":
    t00 = time.time()
    if len(ARGS) > 1 and ARGS[1] == "probe":
        bar_states(limit=2000); print("probe done (%.0fs for 2000 bars)" % (time.time() - t00)); sys.exit()
    PBS = bar_states()
    _sv = [v for _, v in sorted(PBS.items())]
    flips = sum(1 for x, y in zip(_sv, _sv[1:]) if x[0] != y[0])
    print("pullback states at %d bars, trend changes %d (%.0fs)" % (len(PBS), flips, time.time() - t00), flush=True)
    K.install_nopause_gate()
    TM, BID, ASK, n_bad, END = E.load_ticks()
    cfg_b = H.package_cfg("base", {"balance": BAL}); cfg_b.update({"scale_lot": 1, "scale_daily": 1}); cfg0 = H.cfg_strict(dict(cfg_b, drag=0.0, limits_live=1))
    opps, bars = E.streams(cfg0, E.R)
    cached = pickle.load(open(K.CACHE, "rb")); S_idx = cached["states"]
    S = {o["t"]: S_idx[o["i"]] for o in opps if o["i"] in S_idx}
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "balance": BAL, "days": round((int(TM[-1]) - int(TM[0])) / 86400000, 1), "rows": {}}
    for drag in (0.35, 0.0):
        cfg = H.cfg_strict(dict(cfg_b, drag=drag, limits_live=1)); cfg_p = H.cfg_strict(dict(cfg_b, drag=drag, limits_live=1, rr=1.0)); t0 = time.time()
        res["rows"]["%.2f" % drag] = run(cfg, cfg_p, TM, BID, ASK, END, opps, bars, S, PBS)
        for nm, a in res["rows"]["%.2f" % drag].items():
            print("drag %.2f %-16s net %8.2f cc_dd %7.2f trades %3d wr %s pf %s h1 %7.2f h2 %7.2f hold %s | %s (%.0fs)" % (
                drag, nm, a["net"], a["cc_dd"], a["trades"], a["win_rate"], a["profit_factor"], a["first_half"], a["later_half"], a["hold_median_min"], a["counts"], time.time() - t0), flush=True)
        json.dump(res, open(OUT, "w"), indent=1)
    print("DONE ->", OUT, "(%.0fs)" % (time.time() - t00), flush=True)
