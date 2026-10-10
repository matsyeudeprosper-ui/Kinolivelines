"""GPT 2026-10-10 (evening), the second comparison, Valere / Infinity only, both cost bases, the new trend
filter (live/pb_gate.py mode "trend", pauses on unknown / missing structure) active in all four variants:
  A : CURRENT recovery restriction (FLIP BOS + ONE continuation in debt, dot-touch re-arm) + daily cap ON
  B : ALL otherwise-eligible MAIN BOS in debt                                                 + daily cap ON
  C : current restriction                                                                     + daily cap OFF
  D : all eligible BOS                                                                        + daily cap OFF
ON = the package's normal cap incl. its adaptive recovery rules (the manual "continue today" override is not in
the engine at all); OFF = no daily profit cap of any kind (adaptive included); day accounting, scaling, lots,
recovery bullets, every other brake identical; internal entries disabled; each arm keeps its own balance, debt
and recovery budget (independent paths on one clock).
The pullback structure is the saved causal + sticky set (study/pb_state_sticky_cache.pkl) - reused as is when
its inputs (the dataset's bar count) are unchanged; the gate runs in the live order (after the ordinary gates
and the allowance / used-level updates). Backtest only.
    python tick_engine_pbgate_allowance.py
Results: study/tick_engine_pbgate_allowance.json
"""
import sys, os, json, time, pickle
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
import tick_engine as E
from tick_engine_matrix import PolicyArm, summarise
from tick_engine_pbgate import PbGateArm
import tick_engine_pbgate_sticky as K
R = E.R
OUT = r"C:\Projects\KinoliveLines\study\tick_engine_pbgate_allowance.json"


class PbGateArmP(PbGateArm):
    """the pullback gate arm with an explicit allowance policy (PbGateArm fixes 'current')"""
    def __init__(self, name, cfg, bars, mode, states, allowance, cap="on"):
        PolicyArm.__init__(self, name, cfg, {"entry": "immediate", "allowance": allowance, "cap": cap}, bars)
        self.gmode, self.S = mode, states; self.n.update({"pb_refused": 0, "pb_choch_allowed": 0, "pb_no_state": 0})


def run(uid, drag, TM, BID, ASK, END, opps, bars, S):
    cfg, rep = E.effective_cfg(E.PR[uid], E.REGIMES[uid], drag)
    arms = [PbGateArmP("A_current_capON", cfg, bars, "trend", S, "current", "on"), PbGateArmP("B_allbos_capON", cfg, bars, "trend", S, "all_bos", "on"),
            PbGateArmP("C_current_capOFF", cfg, bars, "trend", S, "current", "off"), PbGateArmP("D_allbos_capOFF", cfg, bars, "trend", S, "all_bos", "off")]
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
    return {arm.name: summarise(arm, TM, BID, ASK, END, TMID) for arm in arms}, rep


if __name__ == "__main__":
    TM, BID, ASK, n_bad, END = E.load_ticks()
    print("ticks in window", len(TM), "bars", len(R), flush=True)
    cfg0, _ = E.effective_cfg(E.PR["infinity"], E.REGIMES["infinity"], 0.0); opps0, bars0 = E.streams(cfg0)
    cached = pickle.load(open(K.CACHE, "rb"))
    assert cached.get("n_bars") == len(R), "the saved sticky structure was built on a different dataset"
    S_idx = cached["states"]; S = {o["t"]: S_idx.get(o["i"], (0, 0, None, None)) for o in opps0}
    print("reusing the saved causal/sticky pullback structure: %d states" % len(S), flush=True)
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset": E.META["sha256"], "rows": {},
           "note": "trend filter in all four; A/C = current allowance (FLIP + 1 continuation in debt, dot-touch re-arm), B/D = all otherwise-eligible MAIN BOS in debt; A/B = daily cap ON (normal + adaptive recovery rules, no manual override), C/D = cap OFF entirely; everything else identical, own balance/debt/budget per arm"}
    for drag in (0.0, 0.35):
        key = "infinity|%.2f" % drag; t0 = time.time()
        out, rep = run("infinity", drag, TM, BID, ASK, END, opps0, bars0, S)
        res["rows"][key] = {"effective": rep, "arms": out}
        for name, a in out.items():
            c = a["counts"]
            print("%-16s drag %.2f | net %8.2f cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d wr %s pf %s | h1 %7.2f h2 %7.2f | debt-gate refusals %d admitted-by-allowance %d day-cap refusals %d cap-off passes %d | pb refused: direction %d wrong-side %d no-trend %d no-last-bos %d | %.0fs" % (
                name, drag, a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"], a["win_rate"], a["profit_factor"], a["first_half"], a["later_half"],
                c.get("debt_gate", 0), c.get("admitted_by_allowance", 0), c.get("day_cap", 0), c.get("cap_waived_off", 0), c.get("pb_against_structure", 0), c.get("pb_paused_wrong_side", 0), c.get("pb_no_structure", 0), c.get("pb_no_last_bos", 0), time.time() - t0), flush=True)
        json.dump(res, open(OUT, "w"), indent=1)
    print("DONE", flush=True)
