"""Owner's OFFICIAL trend-following filter (2026-10-10 evening), replayed on the tick engine with the
pullback structure built CAUSALLY and STICKY, as the live feed holds it since the same evening.

v2 (GPT review of reply 18):
  * WARM-UP: the 8000 M1 bars BEFORE the dataset (study/dev_bars_2026-10-09b_warmup.npz, same terminal) are
    walked first, so every opportunity of the dataset is judged with a full 8000-bar window and a warm sticky
    set - no startup "unknown structure" any more (v1 had none for the first 8000 bars: those refusals were
    startup artefacts, counted apart below).
  * LIVE gate order in every arm (tick_engine_matrix.PolicyArm order="live"): kill, awake, dedupe, allowance
    (consumed), the pullback filter, weather, day cap, geometry - a weather- or cap-refused signal has consumed
    the allowance exactly as live enter() does.
  * ADAPTIVE day cap reproduced (cap_rule="adaptive" = live effective_cap_today): in debt the cap is the sized
    cap + bonus (median of this arm's own last 40 debt-day results, clamped to [0, 5 x cap]); unrestricted only
    while fewer than 3 such days exist (cold start, every arm starts with an empty history and no debt).
    The manual "continue today" override does not exist in the engine.
  * The structure cache (study/pb_state_sticky_cache_v2.pkl) is reused only when its FINGERPRINT matches:
    dataset sha, warm-up sha, window, the feed module's source and this script's walk/view source.
Arms: filter_off (package as is) | trend (live rule: with the pullback trend AND beyond its last BOS; wrong
side / unknown trend / missing last BOS = pause) | trend_nopause (sensitivity: the permissive fallback).
    python tick_engine_pbgate_sticky.py [regime ...]        (default: infinity)
Results: study/tick_engine_pbgate_sticky_v2.json (v1 kept as tick_engine_pbgate_sticky_v1_diag.json)
"""
import sys, os, json, time, pickle, hashlib, inspect
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
import numpy as np
import tick_engine as E
from tick_engine_matrix import PolicyArm, summarise
from tick_engine_pbgate import PbGateArm
import owl_chart_feed as F
R = E.R; WIN = F.RAW_BARS
HERE = os.path.dirname(os.path.abspath(__file__))
WARM_NPZ = os.path.join(HERE, "dev_bars_2026-10-09b_warmup.npz")
CACHE = os.path.join(HERE, "pb_state_sticky_cache_v2.pkl")
OUT = os.path.join(HERE, "tick_engine_pbgate_sticky_v2.json")


def pb_view_sticky(kept, dots, marks, bk, S):
    want = {d[0] for d in dots} | {m[0] for m in marks} | {b[0] for b in bk}
    want |= {t for t in S if t >= kept[0][0]}
    want.add(kept[-1][0])
    cands = [c for c in kept if c[0] in want]
    chain = F.pb_join(F.pb_quiet(F.pb_join(cands)))
    if len(chain) < 3: return (0, 0, None, None)
    bk2 = []
    d2, m2, tr2, ch2, nxt, inv, nxt_t, inv_t, dr2, flp, flp_t, fdir = F.engine(chain, brk_out=bk2)
    t = int(tr2 or 0); c = int(ch2 or 0); c = c if (c and c != t) else 0
    lvl = None
    if c:
        cm = [x for x in m2 if len(x) > 2 and x[2] == "choch"]
        lvl = float(cm[-1][1]) if cm else None
    return (t, c, lvl, float(bk2[-1][2]) if bk2 else None)


def fingerprint(warm_meta):
    h = hashlib.sha256()
    h.update(E.META["sha256"].encode()); h.update(warm_meta["sha256"].encode()); h.update(str(WIN).encode())
    h.update(open(F.__file__, "rb").read())
    h.update(inspect.getsource(pb_view_sticky).encode()); h.update(inspect.getsource(causal_sticky_states).encode())
    return h.hexdigest()[:16]


def causal_sticky_states(opp_idx):
    """{dataset bar index: (trend, choch, choch_lvl, last_bos)} at every opportunity bar, from a full causal walk
    that starts inside the warm-up bars"""
    warm_meta = json.load(open(WARM_NPZ.replace(".npz", ".json"))); W = np.load(WARM_NPZ)["R"]
    assert int(W["time"][-1]) < int(R["time"][0]) and len(W) == WIN, "warm-up bars must precede the dataset"
    fp = fingerprint(warm_meta)
    try:
        cached = pickle.load(open(CACHE, "rb"))
        if cached.get("fingerprint") == fp and all(i in cached["states"] for i in opp_idx):
            print("structure cache reused (fingerprint %s)" % fp, flush=True); return cached["states"], fp
        print("structure cache NOT reused: fingerprint %s vs cached %s" % (fp, cached.get("fingerprint")), flush=True)
    except Exception:
        pass
    RW = np.concatenate([W, R]); off = len(W)
    S = set(); states = {}; t0 = time.time(); want_idx = set(opp_idx)
    for i in range(WIN - 1, len(RW)):
        kept = F.build(RW[i - WIN + 1:i + 1])
        if len(kept) < 3: continue
        bk = []; dots, marks, trend, *_ = F.engine(kept, brk_out=bk)
        if trend: dots = [d for d in dots if d[2] == trend]
        S |= {t for t in ({d[0] for d in dots} | {m[0] for m in marks} | {b[0] for b in bk}) if t < kept[-1][0]}
        S = {t for t in S if t >= kept[0][0]}
        j = i - off
        if j in want_idx:
            try: states[j] = pb_view_sticky(kept, dots, marks, bk, S)
            except Exception: states[j] = (0, 0, None, None)
        if (i - WIN + 1) % 4000 == 0: print("causal sticky walk %d / %d (%.0fs)" % (i - WIN + 1, len(RW) - WIN + 1, time.time() - t0), flush=True)
    pickle.dump({"fingerprint": fp, "n_bars": len(R), "warmup_sha": warm_meta["sha256"], "states": states}, open(CACHE, "wb"))
    return states, fp


def run(uid, drag, TM, BID, ASK, END, opps, bars, S):
    cfg, rep = E.effective_cfg(E.PR[uid], E.REGIMES[uid], drag)
    kw = dict(order="live", cap_rule="adaptive")
    arms = [PbGateArm("filter_off", cfg, bars, "none", S, **kw), PbGateArm("trend", cfg, bars, "trend", S, **kw), PbGateArm("trend_nopause", cfg, bars, "trend_nopause", S, **kw)]
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


def install_nopause_gate():
    """the sensitivity arm: the trend rule with the OLD permissive fallback (unknown / missing -> allowed)"""
    import tick_engine_pbgate as G
    _orig = G.pb_gate
    def _gate(mode, d, px, trend, choch=0, choch_lvl=None, last_bos=None):
        if mode == "trend_nopause":
            if trend not in (1, -1): return True, "no_structure_allowed"
            if last_bos is None or px is None: return True, "no_last_bos_allowed"
            return _orig("trend", d, px, trend, choch, choch_lvl, last_bos)
        return _orig(mode, d, px, trend, choch, choch_lvl, last_bos)
    G.pb_gate = _gate


def line(uid, drag, name, a, dt):
    c = a["counts"]
    return ("%-10s drag %.2f %-14s | net %8.2f cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d wr %s pf %s | h1 %7.2f h2 %7.2f | refused: direction %d wrong-side %d no-trend %d no-last-bos %d | "
            "weather %d debt-gate %d day-cap %d (cold-unrestricted %d, bonus passes %d, bonus refusals %d) | %.0fs") % (
        uid, drag, name, a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"], a["win_rate"], a["profit_factor"], a["first_half"], a["later_half"],
        c.get("pb_against_structure", 0), c.get("pb_paused_wrong_side", 0), c.get("pb_no_structure", 0), c.get("pb_no_last_bos", 0),
        c.get("weather", 0), c.get("debt_gate", 0), c.get("day_cap", 0), c.get("cap_unrestricted_cold", 0), c.get("cap_bonus_passes", 0), c.get("cap_bonus_refusals", 0), dt)


if __name__ == "__main__":
    install_nopause_gate()
    want = ARGS[1:] or ["infinity"]
    TM, BID, ASK, n_bad, END = E.load_ticks()
    print("ticks in window", len(TM), "bars", len(R), flush=True)
    cfg0, _ = E.effective_cfg(E.PR["infinity"], E.REGIMES["infinity"], 0.0); opps0, bars0 = E.streams(cfg0)
    S_idx, fp = causal_sticky_states([o["i"] for o in opps0])
    S = {o["t"]: S_idx.get(o["i"], (0, 0, None, None)) for o in opps0}
    n_tr = sum(1 for v in S.values() if v[0] != 0); n_last = sum(1 for v in S.values() if v[3] is not None)
    n_startup_v1 = sum(1 for o in opps0 if o["i"] < WIN - 1)
    print("pb sticky states at %d opportunities: with a trend %d, with a last BOS %d | v1 startup artefacts (first %d bars, no state) %d" % (len(S), n_tr, n_last, WIN - 1, n_startup_v1), flush=True)
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset": E.META["sha256"], "fingerprint": fp,
           "pb_states": {"n": len(S), "with_trend": n_tr, "with_last_bos": n_last, "genuinely_unknown": len(S) - n_tr, "v1_startup_artefacts": n_startup_v1},
           "rows": {}, "note": "v2: warm-up walk, live gate order, adaptive cap; arms filter_off / trend (live rule) / trend_nopause (sensitivity)"}
    for uid in want:
        cfg0, _ = E.effective_cfg(E.PR[uid], E.REGIMES[uid], 0.0); opps, bars = E.streams(cfg0)
        for drag in (0.0, 0.35):
            key = "%s|%.2f" % (uid, drag); t0 = time.time()
            out, rep = run(uid, drag, TM, BID, ASK, END, opps, bars, S)
            res["rows"][key] = {"effective": rep, "arms": out}
            for name, a in out.items(): print(line(uid, drag, name, a, time.time() - t0), flush=True)
            json.dump(res, open(OUT, "w"), indent=1)
    print("DONE", flush=True)
