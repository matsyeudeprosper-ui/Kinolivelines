"""Owner's urgent live change of 2026-10-10, backtested on the three-arm tick engine:
the PULLBACK-DIRECTION gate (structure_bos_bot.PB_DIR_GATE + pb_state_now):
  pb_gate_choch : an entry against the pullback chart's trend is refused UNLESS the
                  pullback chart has a pending CHoCH in the entry's direction and the
                  signal quote is beyond the CHoCH price (the live rule)
  pb_gate_strict: refused whenever against the pullback chart's trend (attribution)
  baseline      : the account's package as is
The pullback state is computed CAUSALLY at each opportunity's bar exactly as the bot
does it (feed build -> engine -> pullback_view over the last 8000 closed M1 bars, the
signal bar included, since the bot reads closed bars at the close). Every regime of the
manifest, both cost bases, one tick clock, independent paths.
    python tick_engine_pbgate.py [regime ...]
"""
import sys, os, json, time, pickle
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
import tick_engine as E
from tick_engine_matrix import PolicyArm
import owl_chart_feed as F
from pb_gate import pb_gate
R = E.R
CACHE = r"C:\Projects\KinoliveLines\study\pb_state_cache_v2.pkl"   # v2: states carry the last BOS price too


def pb_state_at(i):
    """(trend, pending choch dir, choch price, last BOS price) of the pullback chart built from bars [i-7999 .. i]"""
    g0 = max(0, i - 7999); kept = F.build(R[g0:i + 1]); bk = []
    if len(kept) < 3: return (0, 0, None, None)
    dots, marks, trend, *_ = F.engine(kept, brk_out=bk)
    if trend: dots = [d for d in dots if d[2] == trend]
    try:
        pb = F.pullback_view(kept, dots, marks, bk) or {}
    except Exception:
        return (0, 0, None, None)
    t = int(pb.get("trend") or 0); c = int(pb.get("choch") or 0); c = c if (c and c != t) else 0
    lvl = None
    if c:
        cm = [x for x in (pb.get("marks") or []) if len(x) > 2 and x[2] == "choch"]
        lvl = float(cm[-1][1]) if cm else None
    bks = pb.get("breaks") or []
    return (t, c, lvl, float(bks[-1][2]) if bks else None)


class PbGateArm(PolicyArm):
    def __init__(self, name, cfg, bars, mode, states):
        super().__init__(name, cfg, {"entry": "immediate", "allowance": "current", "cap": "on"}, bars)
        self.gmode, self.S = mode, states; self.n.update({"pb_refused": 0, "pb_choch_allowed": 0, "pb_no_state": 0})

    def gate_hook(self, o, k, TM, BID, ASK, setup, debt_now):
        """review 16: like the live enter(), the pullback gate runs AFTER the ordinary gates and the
        continuation allowance / used-level updates, immediately before the order"""
        if self.gmode == "none": return True
        st = self.S.get(o["t"])
        if st is None: self.n["pb_no_state"] += 1; return True
        tr, ch, lvl, last = (tuple(st) + (None,))[:4]
        ok, why = pb_gate(self.gmode, o["d"], setup["e0"], tr, ch, lvl, last)   # the live bot's own decision function
        if not ok: self.n["pb_refused"] += 1; self.n["pb_" + why] = self.n.get("pb_" + why, 0) + 1; return False
        if why == "choch_exception": self.n["pb_choch_allowed"] += 1
        return True


def run_gate(uid, drag, TM, BID, ASK, END, opps, bars, S):
    cfg, rep = E.effective_cfg(E.PR[uid], E.REGIMES[uid], drag)
    arms = [PbGateArm("baseline", cfg, bars, "none", S), PbGateArm("pb_gate_choch", cfg, bars, "choch", S), PbGateArm("pb_gate_strict", cfg, bars, "strict", S),
            PbGateArm("pb_gate_trend", cfg, bars, "trend", S)]   # owner 2026-10-10 evening: the official rule
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
        out[arm.name] = {"net": round(arm.run, 2), "cc_dd": round(E.dd_of(arm.pnls), 2), "mtm_dd": round(arm.mtm_dd, 2), "trades": len(tr), "wins": arm.wins,
                         "pnl_main": round(sum(x["pnl_main"] for x in tr), 2), "pnl_add": round(sum(x["pnl_add"] for x in tr), 2), "risk_main": round(sum(x["risk"] for x in tr), 2),
                         "first_half": round(sum(x["pnl"] for x in tr if x["tc"] < TMID), 2), "later_half": round(sum(x["pnl"] for x in tr if x["tc"] >= TMID), 2),
                         "counts": {k2: v for k2, v in arm.n.items() if k2 != "wait_s"}, "trades_list": tr}
    return out, rep


if __name__ == "__main__":
    want = ARGS[1:] or ["infinity", "u224016179", "bos", "reference_uncapped"]
    TM, BID, ASK, n_bad, END = E.load_ticks()
    print("ticks in window", len(TM), flush=True)
    cfg0, _ = E.effective_cfg(E.PR["infinity"], E.REGIMES["infinity"], 0.0); opps0, bars0 = E.streams(cfg0)
    try: S = pickle.load(open(CACHE, "rb"))
    except Exception: S = {}
    t0 = time.time(); todo = [o for o in opps0 if o["t"] not in S]
    for j, o in enumerate(todo):
        S[o["t"]] = pb_state_at(o["i"])
        if j % 100 == 0: print("pb state %d / %d (%.0fs)" % (j, len(todo), time.time() - t0), flush=True)
    pickle.dump(S, open(CACHE, "wb"))
    tr_c = sum(1 for v in S.values() if v[0] != 0); ch_c = sum(1 for v in S.values() if v[1] != 0)
    print("pb states at %d opportunities: with a trend %d, with a pending CHoCH %d" % (len(S), tr_c, ch_c), flush=True)
    outp = r"C:\Projects\KinoliveLines\study\tick_engine_pbgate.json"
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset": E.META["sha256"], "rows": {}, "pb_states": {"n": len(S), "with_trend": tr_c, "with_choch": ch_c}}
    try: res["rows"] = json.load(open(outp))["rows"]
    except Exception: pass
    for uid in want:
        cfg0, _ = E.effective_cfg(E.PR[uid], E.REGIMES[uid], 0.0); opps, bars = E.streams(cfg0)
        for drag in (0.0, 0.35):
            key = "%s|%.2f" % (uid, drag)
            if key in res["rows"]: print(key, "(cached)", flush=True); continue
            t0 = time.time(); out, rep = run_gate(uid, drag, TM, BID, ASK, END, opps, bars, S)
            res["rows"][key] = {"effective": rep, "arms": out}
            for name, a in out.items():
                c = a["counts"]
                print("%-18s drag %.2f %-15s | net %8.2f cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d main %8.2f adds %6.2f risk %6.0f | h1 %7.2f h2 %7.2f | pb refused %3d choch-allowed %3d no-state %d | %.0fs" % (
                    uid, drag, name, a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"], a["pnl_main"], a["pnl_add"], a["risk_main"], a["first_half"], a["later_half"], c["pb_refused"], c["pb_choch_allowed"], c["pb_no_state"], time.time() - t0), flush=True)
            json.dump(res, open(outp, "w"), indent=1)
    print("DONE", flush=True)
