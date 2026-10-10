"""Owner's OFFICIAL trend-following filter (2026-10-10 evening), replayed on the tick engine with the
pullback structure built CAUSALLY and STICKY, as the live feed holds it since the same evening:

  filter OFF   : the package as is (policy immediate | current allowance | cap on)
  trend        : the live rule (live/pb_gate.py mode "trend") - with the pullback trend AND beyond its
                 last BOS (buys above / sells below); wrong side, unknown trend or missing last BOS = pause
  trend_nopause: sensitivity only - the same rule with the permissive fallback on unknown / missing structure

The pullback state at every opportunity bar comes from a bar-by-bar walk of the whole dataset: at each bar
the feed's build -> engine runs over the 8000 bars ending there (the live window), the structure times it
finds are added to the sticky set (closed candles only, pruned to the window), and at an opportunity bar
the pullback view is built from that set - exactly owl_chart_feed.pullback_view with the sticky chain.
Gate order and state updates are the live ones (review 16 pipeline: ordinary gates first, the hook last).
    python tick_engine_pbgate_sticky.py [regime ...]        (default: infinity)
Results: study/tick_engine_pbgate_sticky.json; states cached in study/pb_state_sticky_cache.pkl
"""
import sys, os, json, time, pickle
ARGS = list(sys.argv); sys.argv = ["x"]
sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); sys.path.insert(0, r"C:\Projects\KinoliveLines\live")
import tick_engine as E
from tick_engine_matrix import PolicyArm, summarise
from tick_engine_pbgate import PbGateArm
import owl_chart_feed as F
R = E.R; WIN = F.RAW_BARS
CACHE = r"C:\Projects\KinoliveLines\study\pb_state_sticky_cache.pkl"
OUT = r"C:\Projects\KinoliveLines\study\tick_engine_pbgate_sticky.json"


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


def causal_sticky_states(opp_idx):
    """{bar index: (trend, choch, choch_lvl, last_bos)} at every opportunity bar, from a full causal walk"""
    try:
        cached = pickle.load(open(CACHE, "rb"))
        if cached.get("n_bars") == len(R) and all(i in cached["states"] for i in opp_idx): return cached["states"]
    except Exception:
        pass
    S = set(); states = {}; t0 = time.time(); want_idx = set(opp_idx)
    for i in range(min(WIN - 1, len(R) - 1), len(R)):
        kept = F.build(R[max(0, i - WIN + 1):i + 1])
        if len(kept) < 3: continue
        bk = []; dots, marks, trend, *_ = F.engine(kept, brk_out=bk)
        if trend: dots = [d for d in dots if d[2] == trend]
        S |= {t for t in ({d[0] for d in dots} | {m[0] for m in marks} | {b[0] for b in bk}) if t < kept[-1][0]}
        S = {t for t in S if t >= kept[0][0]}
        if i in want_idx:
            try: states[i] = pb_view_sticky(kept, dots, marks, bk, S)
            except Exception: states[i] = (0, 0, None, None)
        if (i - WIN + 1) % 2000 == 0: print("causal sticky walk %d / %d (%.0fs)" % (i - WIN + 1, len(R) - WIN + 1, time.time() - t0), flush=True)
    pickle.dump({"n_bars": len(R), "states": states}, open(CACHE, "wb"))
    return states


def run(uid, drag, TM, BID, ASK, END, opps, bars, S):
    cfg, rep = E.effective_cfg(E.PR[uid], E.REGIMES[uid], drag)
    arms = [PbGateArm("filter_off", cfg, bars, "none", S), PbGateArm("trend", cfg, bars, "trend", S), PbGateArm("trend_nopause", cfg, bars, "trend_nopause", S)]
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
    from pb_gate import pb_gate as _pg
    import tick_engine_pbgate as G
    # the sensitivity arm: the trend rule with the OLD permissive fallback (unknown / missing -> allowed)
    _orig = G.pb_gate
    def _gate(mode, d, px, trend, choch=0, choch_lvl=None, last_bos=None):
        if mode == "trend_nopause":
            if trend not in (1, -1): return True, "no_structure_allowed"
            if last_bos is None or px is None: return True, "no_last_bos_allowed"
            return _orig("trend", d, px, trend, choch, choch_lvl, last_bos)
        return _orig(mode, d, px, trend, choch, choch_lvl, last_bos)
    G.pb_gate = _gate
    want = ARGS[1:] or ["infinity"]
    TM, BID, ASK, n_bad, END = E.load_ticks()
    print("ticks in window", len(TM), "bars", len(R), flush=True)
    cfg0, _ = E.effective_cfg(E.PR["infinity"], E.REGIMES["infinity"], 0.0); opps0, bars0 = E.streams(cfg0)
    S_idx = causal_sticky_states([o["i"] for o in opps0])
    S = {o["t"]: S_idx.get(o["i"], (0, 0, None, None)) for o in opps0}
    n_tr = sum(1 for v in S.values() if v[0] != 0); n_last = sum(1 for v in S.values() if v[3] is not None)
    print("pb sticky states at %d opportunities: with a trend %d, with a last BOS %d" % (len(S), n_tr, n_last), flush=True)
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset": E.META["sha256"], "pb_states": {"n": len(S), "with_trend": n_tr, "with_last_bos": n_last},
           "rows": {}, "note": "causal + sticky pullback structure; arms: filter_off (package as is), trend (live rule, pauses on unknown/missing), trend_nopause (sensitivity)"}
    for uid in want:
        cfg0, _ = E.effective_cfg(E.PR[uid], E.REGIMES[uid], 0.0); opps, bars = E.streams(cfg0)
        for drag in (0.0, 0.35):
            key = "%s|%.2f" % (uid, drag); t0 = time.time()
            out, rep = run(uid, drag, TM, BID, ASK, END, opps, bars, S)
            res["rows"][key] = {"effective": rep, "arms": out}
            for name, a in out.items():
                c = a["counts"]
                print("%-10s drag %.2f %-14s | net %8.2f cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d wr %s pf %s | h1 %7.2f h2 %7.2f | refused: direction %d wrong-side %d no-trend %d no-last-bos %d | %.0fs" % (
                    uid, drag, name, a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"], a["win_rate"], a["profit_factor"], a["first_half"], a["later_half"],
                    c.get("pb_against_structure", 0), c.get("pb_paused_wrong_side", 0), c.get("pb_no_structure", 0), c.get("pb_no_last_bos", 0), time.time() - t0), flush=True)
            json.dump(res, open(OUT, "w"), indent=1)
    print("DONE", flush=True)
