"""The proof page's "$200 reference test" rebuilt with TODAY's verified rules (GPT 2026-10-11): the generic
`base` package at $200 on the development 42 days, on the tick engine with the live gate order, the adaptive
cap rule (the base package has no daily cap), the causal + sticky pullback structure (warm-up walk, cache v2)
and Mike's trend / last-BOS filter with the missing-structure pause - both cost bases. A no-filter twin on the
same conventions is kept beside it so the page can say what the filter changed.
Separate from Valère's replay (different account, balance, quotes, period).
    python proof_current_rules.py
Writes live/lab/proof_current.json (read by the app's proof page).
"""
import sys, os, json, time, pickle
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live\lab")
import tick_engine as E
from tick_engine_matrix import summarise
from tick_engine_pbgate import PbGateArm
import tick_engine_pbgate_sticky as K
import harness as H
OUT = r"C:\Projects\KinoliveLines\live\lab\proof_current.json"; BAL = 200.0


def run(cfg, drag, TM, BID, ASK, END, opps, bars, S):
    kw = dict(order="live", cap_rule="adaptive", allowance="current", cap="on")
    arms = [PbGateArm("today", cfg, bars, "trend", S, **kw), PbGateArm("no_filter", cfg, bars, "none", S, **kw)]
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
        # daily cumulative curve for the page (date, cumulative net)
        cur = 0.0; curve = {};
        for t in a["trades_list"]:
            cur += t["pnl"]; curve[time.strftime("%Y-%m-%d", time.gmtime(t["tc"] / 1000))] = round(cur, 2)
        pn = [t["pnl"] for t in a["trades_list"]]; streak = mx = 0
        for p in pn:
            streak = streak + 1 if p <= 0 else 0; mx = max(mx, streak)
        out[arm.name] = {k: a[k] for k in ("net", "net_with_open_mtm", "cc_dd", "mtm_dd", "trades", "wins", "win_rate", "profit_factor", "first_half", "later_half", "missed_winners")}
        out[arm.name].update({"curve": sorted(curve.items()), "pnls": [round(p, 2) for p in pn], "max_loss_streak": mx, "refusals": {k: v for k, v in a["counts"].items() if k.startswith("pb_")}})
    return out


if __name__ == "__main__":
    K.install_nopause_gate()
    TM, BID, ASK, n_bad, END = E.load_ticks()
    # GPT 2026-10-11: the live base package scales lot and cap with the balance at each day roll - the test must too
    cfg_b = H.package_cfg("base", {"balance": BAL}); cfg_b.update({"scale_lot": 1, "scale_daily": 1}); cfg0 = H.cfg_strict(dict(cfg_b, drag=0.0, limits_live=1))
    opps, bars = E.streams(cfg0, E.R)
    cached = pickle.load(open(K.CACHE, "rb")); S_idx = cached["states"]
    assert all(o["i"] in S_idx for o in opps), "the saved sticky structure does not cover every opportunity - rerun tick_engine_pbgate_sticky.py"
    S = {o["t"]: S_idx[o["i"]] for o in opps}
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "balance": BAL, "package": "base", "days": round((int(TM[-1]) - int(TM[0])) / 86400000, 1),
           "window_utc": [time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[0]) / 1000)), time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(TM[-1]) / 1000))],
           "engine": "tick engine (bid/ask ticks of the std account), live gate order, adaptive cap rule, daily balance scaling of lot and cap, causal + sticky pullback structure with 8000-bar warm-up (fingerprint %s)" % cached.get("fingerprint"),
           "rules": "today's rules: trend / last-BOS filter with the missing-structure pause, current recovery restriction, package brakes; 'no_filter' = the same without the filter", "rows": {}}
    for drag in (0.0, 0.35):
        cfg = H.cfg_strict(dict(cfg_b, drag=drag, limits_live=1)); t0 = time.time()
        res["rows"]["%.2f" % drag] = run(cfg, drag, TM, BID, ASK, END, opps, bars, S)
        for n, a in res["rows"]["%.2f" % drag].items():
            print("drag %.2f %-10s net %8.2f cc_dd %7.2f mtm_dd %7.2f trades %3d wr %s pf %s h1 %7.2f h2 %7.2f (%.0fs)" % (drag, n, a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["win_rate"], a["profit_factor"], a["first_half"], a["later_half"], time.time() - t0), flush=True)
        json.dump(res, open(OUT, "w"), indent=1)
    print("DONE ->", OUT, flush=True)
