"""Mike / GPT 2026-10-10 (night): Valère's REAL account (nest u224016179, login 224016179) from its bot start to the
latest quotes - what it really earned (the ledger) versus what TODAY'S live rules would have earned (the tick engine).

Hypothetical arms (both on the corrected conventions: live gate order, adaptive daily cap, causal + sticky pullback
structure with warm-up, cold-flat at the real start with the real starting balance, no discretionary overrides -
the manual "continue today" switch does not exist in the engine):
  today_rules  : the account's package as it is today - trend / last-BOS filter with the missing-structure pause,
                 current recovery restriction, adaptive cap, lots / scaling, recovery adds, every brake
  engine_check : the same package WITHOUT the pullback filter (the rules the bot ran for most of the period) -
                 only to show how close the engine on the proxy quotes gets to the real ledger; NOT a result
Quotes: the development ticks (std BTCUSDm) + the forward ticks, merged; bars: dataset + extension; the common
covered period is reported, nothing outside it is scored. Both cost bases (spread only; + $0.35 per 0.02 lot).
    python replay_valere_actual_vs_today.py
Results: study/replay_valere_actual_vs_today.json
"""
import sys, os, json, time, pickle, hashlib, inspect
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
import numpy as np
import tick_engine as E
from tick_engine_matrix import summarise
from tick_engine_pbgate import PbGateArm
import tick_engine_pbgate_sticky as K
import owl_chart_feed as F
HERE = os.path.dirname(os.path.abspath(__file__))
UID = "u224016179"; NEST = "u224016179"
ERA = "2026-09-14T22:46:39+00:00"; BAL0 = 210.0        # verified: first "BOS-BOT starting ... balance 210.00" banner (the nest era_start is 19:07:20, 3.6 h earlier; ledger bal_start 210.00; first closed trade 23:06 UTC)
CACHE = os.path.join(HERE, "pb_state_sticky_cache_valere.pkl"); OUT = os.path.join(HERE, "replay_valere_actual_vs_today.json")


def merged_ticks(t0_ms, end_ms):
    """development ticks + forward ticks, sorted, duplicates by timestamp dropped, clipped"""
    a = E.load_ticks(os.path.join(HERE, "ticks"), t0_ms, 4_000_000_000_000)
    b = E.load_ticks(os.path.join(HERE, "ticks_forward"), t0_ms, end_ms)
    TM = np.concatenate([a[0], b[0]]); BID = np.concatenate([a[1], b[1]]); ASK = np.concatenate([a[2], b[2]])
    o = np.argsort(TM, kind="stable"); TM, BID, ASK = TM[o], BID[o], ASK[o]
    keep = np.concatenate([[True], np.diff(TM) > 0]); TM, BID, ASK = TM[keep], BID[keep], ASK[keep]
    win = (TM >= t0_ms) & (TM < end_ms)
    return TM[win], BID[win], ASK[win], a[3] + b[3]


def causal_sticky_states(RW, off, opp_idx, fp):
    try:
        cached = pickle.load(open(CACHE, "rb"))
        if cached.get("fingerprint") == fp and all(i in cached["states"] for i in opp_idx):
            print("structure cache reused", fp, flush=True); return cached["states"]
    except Exception:
        pass
    WIN = K.WIN; S = set(); states = {}; t0 = time.time(); want = set(opp_idx)
    for i in range(WIN - 1, len(RW)):
        kept = F.build(RW[i - WIN + 1:i + 1])
        if len(kept) < 3: continue
        bk = []; dots, marks, trend, *_ = F.engine(kept, brk_out=bk)
        if trend: dots = [d for d in dots if d[2] == trend]
        S |= {t for t in ({d[0] for d in dots} | {m[0] for m in marks} | {b[0] for b in bk}) if t < kept[-1][0]}
        S = {t for t in S if t >= kept[0][0]}
        j = i - off
        if j in want:
            try: states[j] = K.pb_view_sticky(kept, dots, marks, bk, S)
            except Exception: states[j] = (0, 0, None, None)
        if (i - WIN + 1) % 4000 == 0: print("causal sticky walk %d / %d (%.0fs)" % (i - WIN + 1, len(RW) - WIN + 1, time.time() - t0), flush=True)
    pickle.dump({"fingerprint": fp, "states": states}, open(CACHE, "wb"))
    return states


def run(cfg, rep, drag, TM, BID, ASK, END, opps, bars, S, start_ms):
    kw = dict(order="live", cap_rule="adaptive", allowance="current", cap="on")
    arms = [PbGateArm("today_rules", cfg, bars, "trend", S, **kw), PbGateArm("engine_check_no_filter", cfg, bars, "none", S, **kw)]
    elig = [((o["t"] + 60) * 1000 + E.SIGNAL_MS, o) for o in opps if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= start_ms]; ei = 0
    touches = sorted((t * 1000 + 60000, 1) for t, (touched, nv) in bars.items() if touched); ti = 0
    n = len(TM); prev = int(start_ms)
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
    T1 = int(TM[-1]); TMID = (int(start_ms) + T1) // 2
    return {arm.name: summarise(arm, TM, BID, ASK, END, TMID) for arm in arms}


def ledger(cut_s):
    d = json.load(open(r"C:\Projects\KinoliveLines\live\lab\wealth\%s.json" % NEST, encoding="utf-8"))
    rows = [t for t in d["trades"] if t[0] <= cut_s]; pn = [t[1] for t in rows]
    w = sum(1 for p in pn if p > 0); gw = sum(p for p in pn if p > 0); gl = -sum(p for p in pn if p < 0); c = pk = dd = 0.0
    for p in pn: c += p; pk = max(pk, c); dd = max(dd, pk - c)
    return {"era": d["era"], "bal_start": d["bal_start"], "balance_now": d["balance"], "flows": d["flows"], "others": d["others"],
            "closed_in_period": len(rows), "wins": w, "win_rate": round(w / len(pn), 4) if pn else None, "profit_factor": round(gw / gl, 3) if gl else None,
            "net": round(sum(pn), 2), "closed_dd": round(dd, 2), "gross_win": round(gw, 2), "gross_loss": round(gl, 2),
            "first_close": rows[0][0] if rows else None, "last_close": rows[-1][0] if rows else None, "lots": sorted(set(round(t[2], 2) for t in rows)),
            "after_cutoff": {"n": len(d["trades"]) - len(rows), "net": round(sum(t[1] for t in d["trades"] if t[0] > cut_s), 2)}}


if __name__ == "__main__":
    import calendar
    K.install_nopause_gate()   # harmless here (no nopause arm); keeps the gate table identical to the other scripts
    start_s = calendar.timegm(time.strptime(ERA[:19], "%Y-%m-%dT%H:%M:%S")); start_ms = start_s * 1000
    W = np.load(os.path.join(HERE, "dev_bars_2026-10-09b_warmup.npz"))["R"]; X = np.load(os.path.join(HERE, "dev_bars_ext.npz"))["R"]
    xm = json.load(open(os.path.join(HERE, "dev_bars_ext.json"))); wm = json.load(open(os.path.join(HERE, "dev_bars_2026-10-09b_warmup.json")))
    R_all = np.concatenate([E.R, X]); assert int(X["time"][0]) > int(E.R["time"][-1])
    TM, BID, ASK, n_bad = merged_ticks(start_ms, 4_000_000_000_000)
    END = int(TM[-1]) + 1; end_s = END // 1000
    R_all = R_all[R_all["time"] < end_s]
    print("period %s -> %s UTC | ticks %d (invalid dropped %d) | bars %d (+%d ext)" % (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(start_s)), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(end_s)), len(TM), n_bad, len(R_all), len(X)), flush=True)
    cov = K.__dict__.get("coverage")
    # coverage per UTC day over the scored period (same rule as the frozen runner)
    covd = {}; d0 = start_s - start_s % 86400; dd = d0
    while dd < end_s:
        lo, hi = max(dd, start_s) * 1000, min(dd + 86400, end_s) * 1000; sel = (TM >= lo) & (TM < hi); t = TM[sel]
        mins = int((hi - lo) // 60000) or 1; buckets = len(np.unique((t - lo) // 60000)) if len(t) else 0
        gaps = np.diff(t) if len(t) > 1 else np.array([0]); mg = max(int(gaps.max()) if len(t) > 1 else 0, int(t[0] - lo) if len(t) else int(hi - lo), int(hi - t[-1]) if len(t) else 0)
        covd[time.strftime("%Y-%m-%d", time.gmtime(dd))] = {"minute_share": round(buckets / mins, 4), "max_gap_s": round(mg / 1000.0, 1), "ticks": int(len(t)), "covered": bool(buckets / mins >= 0.97 and mg <= 120000)}
        dd += 86400
    n_cov = sum(1 for v in covd.values() if v["covered"]); print("coverage: %d / %d days" % (n_cov, len(covd)), flush=True)
    cfg0, rep0 = E.effective_cfg(E.PR[UID], BAL0, 0.0); opps, bars = E.streams(cfg0, R_all)
    fp = hashlib.sha256((E.META["sha256"] + wm["sha256"] + xm["sha256"] + str(K.WIN) + hashlib.sha256(open(F.__file__, "rb").read()).hexdigest() + inspect.getsource(K.pb_view_sticky) + inspect.getsource(causal_sticky_states)).encode()).hexdigest()[:16]
    RW = np.concatenate([W, R_all]); S_idx = causal_sticky_states(RW, len(W), [o["i"] for o in opps if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= start_ms], fp)
    S = {o["t"]: S_idx.get(o["i"], (0, 0, None, None)) for o in opps}
    n_sc = sum(1 for o in opps if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= start_ms)
    print("opportunities in the period %d; pullback states with a trend %d, with a last BOS %d" % (n_sc, sum(1 for o in opps if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= start_ms and S[o["t"]][0] != 0), sum(1 for o in opps if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= start_ms and S[o["t"]][3] is not None)), flush=True)
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "account": {"nest_id": NEST, "login": 224016179, "server": "Exness-MT5Real30", "name": "Valere Guilet", "package": E.PR[UID].get("label")},
           "period": {"start": start_s, "end": end_s, "start_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(start_s)), "end_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(end_s)), "days": round((end_s - start_s) / 86400, 2)},
           "quotes": {"ticks": int(len(TM)), "invalid_dropped": n_bad, "source": "std account BTCUSDm (development + forward ticks), a PROXY for the account's own Exness-MT5Real30 BTCUSD quotes", "coverage": covd, "days_covered": n_cov},
           "bars": {"dataset_sha": E.META["sha256"], "warmup_sha": wm["sha256"], "ext_sha": xm["sha256"], "n": int(len(R_all))}, "structure_fingerprint": fp,
           "assumptions": ["cold-flat at the real start with the real starting balance (210.00); no deposits/withdrawals in the ledger (flows empty)",
                           "today's package snapshot throughout (the only differences between the snapshot and today's package are the pullback gate dials)",
                           "no discretionary 'continue today' override in the engine; the REAL account had it switched on at 2026-10-10 07:05 UTC, i.e. inside the last hour of the covered period (its 10-10 trades after that hour are flagged apart)",
                           "adaptive daily cap with an empty debt-day history at start (as the real bot started); live gate order; causal + sticky pullback structure with 8000-bar warm-up"],
           "actual_ledger": ledger(end_s), "rows": {}}
    for drag in (0.0, 0.35):
        cfg, rep = E.effective_cfg(E.PR[UID], BAL0, drag); t0 = time.time()
        out = run(cfg, rep, drag, TM, BID, ASK, END, opps, bars, S, start_ms); res["rows"]["%.2f" % drag] = {"effective": rep, "arms": out}
        for name, a in out.items():
            c = a["counts"]
            print("drag %.2f %-24s | net %8.2f cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d wr %s pf %s | h1 %7.2f h2 %7.2f | refused: direction %d wrong-side %d no-trend %d no-last-bos %d | weather %d debt-gate %d day-cap %d | %.0fs" % (
                drag, name, a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"], a["win_rate"], a["profit_factor"], a["first_half"], a["later_half"],
                c.get("pb_against_structure", 0), c.get("pb_paused_wrong_side", 0), c.get("pb_no_structure", 0), c.get("pb_no_last_bos", 0), c.get("weather", 0), c.get("debt_gate", 0), c.get("day_cap", 0), time.time() - t0), flush=True)
        json.dump(res, open(OUT, "w"), indent=1)
    print("DONE", flush=True)
