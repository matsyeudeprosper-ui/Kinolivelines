"""Event-correct TICK diagnostic of the nominated delayed-recovery-MAIN candidate
(ChatGPT reviews 12-13). Per SETUP, not a path re-simulation: the setups come
from the bar-level candidate path of each manifest regime (its own debt / jar /
caps / balance, live-order limits, adverse reading); each setup is then replayed
on bid/ask ticks with exact chronology.

EXECUTION MODEL (declared, review 13): bot-triggered MARKET orders.
  signal       = the setup's bar close (bar time + 60 s)
  SIGNAL_MS    = signal-processing delay (1000 ms): nothing before close + SIGNAL_MS
  trigger      = delayed arm: first tick with ask <= mid (buy) / bid >= mid (sell)
                 immediate arm: the first tick at/after the eligibility time
  EXEC_MS      = trigger-to-execution delay (1000 ms): the order fills at the first
                 tick at/after trigger + EXEC_MS, at that tick's ask (buy) / bid (sell)
  at the fill tick, broker geometry: a stop not strictly on the correct side of the
  executable exit quote (buy: sl >= bid; sell: sl <= ask) or a target already reached
  (buy: tp <= bid; sell: tp >= ask) = order REJECTED (invalid stops), recorded; the
  same rule for BOTH arms
  before the trigger (delayed arm only): target printed on the exit side = MISSED
  WINNER; stop printed on the exit side = the trigger fires on that tick too (ask has
  crossed the midpoint) and the fill is then rejected by the geometry rule, recorded
  as reject_after_stop_print
  after the fill: the FIRST barrier in tick order on the executable exit side
COVERAGE: the incoming gap of every tick is accounted BEFORE that tick is evaluated,
  including eligibility -> first quote and fill -> next tick; a path whose largest
  incoming gap exceeds GAP_MS is UNRESOLVED (its money is excluded from the certified
  totals and shown apart as an observed-tick diagnostic).
HORIZON: ticks before the dataset's first bar are coverage context only; nothing
  after END (the closed-bar cutoff) is used; a setup still pending / open at END is
  OPEN_AT_END, kept with its mark-to-market at the last in-window quote (both arms).
QUOTES: bid <= 0, ask < bid or non-finite ticks are dropped and counted. Daily file
  hashes are verified against the manifest.
    python delayed_entry_ticks.py          (needs study/ticks/*.npz from fetch_ticks.py)
"""
import sys, json, os, bisect, time, hashlib, math
import numpy as np

SIGNAL_MS = 1000; EXEC_MS = 1000; GAP_MS = 30000; GAP_FLAG_MS = 5000


def clean_quotes(tm, bid, ask):
    ok = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask >= bid)
    return tm[ok], bid[ok], ask[ok], int((~ok).sum())


def replay(TM, BID, ASK, d, t_signal, sl, tp, mid, delayed, end_ms, signal_ms=SIGNAL_MS, exec_ms=EXEC_MS, gap_ms=GAP_MS):
    """one setup on arrays (time_msc, bid, ask). Returns a dict with kind in
    fill | missed_win | reject_invalid_stop | reject_invalid_target | reject_after_stop_print |
    open_at_end | pending_at_end | no_quote, plus max_gap_ms (largest INCOMING gap met on the
    path, eligibility -> first quote included) and resolved (max_gap_ms <= gap_ms)."""
    n = len(TM)
    elig = int((t_signal + 60) * 1000 + signal_ms)
    i = bisect.bisect_left(TM, elig)
    if i >= n or TM[i] >= end_ms:
        return {"kind": "pending_at_end" if delayed else "no_quote", "max_gap_ms": 0, "resolved": False}
    mg = int(TM[i] - elig)                       # wait from eligibility to the first available quote
    prev = int(TM[i])
    stop_printed = False
    # ---- phase 1: find the trigger tick
    trig = None
    j = i
    while j < n and TM[j] < end_ms:
        mg = max(mg, int(TM[j] - prev)); prev = int(TM[j])
        b, a = BID[j], ASK[j]
        if delayed:
            if (d == 1 and b >= tp) or (d == -1 and a <= tp):
                return {"kind": "missed_win", "t": int(TM[j]), "max_gap_ms": mg, "resolved": mg <= gap_ms}
            if (d == 1 and b <= sl) or (d == -1 and a >= sl):
                stop_printed = True
            if (d == 1 and a <= mid) or (d == -1 and b >= mid):
                trig = j; break
        else:
            trig = j; break
        j += 1
    if trig is None:
        last = max(i, min(j, n) - 1)
        return {"kind": "pending_at_end", "t": int(TM[last]), "max_gap_ms": mg, "resolved": mg <= gap_ms}
    # ---- execution: first tick at/after trigger + exec_ms
    tx = int(TM[trig]) + exec_ms
    k = bisect.bisect_left(TM, tx)
    if k >= n or TM[k] >= end_ms:
        return {"kind": "pending_at_end", "t": int(TM[trig]), "max_gap_ms": mg, "resolved": mg <= gap_ms, "note": "triggered, no in-window execution quote"}
    for q in range(trig + 1, k + 1):             # incoming gaps up to and including the execution tick
        mg = max(mg, int(TM[q] - TM[q - 1]))
    b, a = BID[k], ASK[k]
    fpx = a if d == 1 else b
    exit_q = b if d == 1 else a
    if (d == 1 and sl >= exit_q) or (d == -1 and sl <= exit_q):
        return {"kind": "reject_after_stop_print" if stop_printed else "reject_invalid_stop", "t": int(TM[k]), "fill_px": float(fpx), "exit_q": float(exit_q), "max_gap_ms": mg, "resolved": mg <= gap_ms}
    if (d == 1 and tp <= exit_q) or (d == -1 and tp >= exit_q):
        return {"kind": "reject_invalid_target", "t": int(TM[k]), "fill_px": float(fpx), "exit_q": float(exit_q), "max_gap_ms": mg, "resolved": mg <= gap_ms}
    # ---- phase 2: first barrier after the fill, exact tick order, executable exit side
    m = k + 1
    while m < n and TM[m] < end_ms:
        mg = max(mg, int(TM[m] - TM[m - 1]))
        b, a = BID[m], ASK[m]
        xq = b if d == 1 else a
        hit_sl = (d == 1 and xq <= sl) or (d == -1 and xq >= sl)
        hit_tp = (d == 1 and xq >= tp) or (d == -1 and xq <= tp)
        if hit_sl or hit_tp:
            return {"kind": "fill", "fill_msc": int(TM[k]), "fill_px": float(fpx), "exit_msc": int(TM[m]), "exit_px": float(xq), "win": bool(hit_tp and not hit_sl),
                    "max_gap_ms": mg, "resolved": mg <= gap_ms, "trigger_msc": int(TM[trig])}
        m += 1
    last = max(k, min(m, n) - 1)
    xq = BID[last] if d == 1 else ASK[last]
    return {"kind": "open_at_end", "fill_msc": int(TM[k]), "fill_px": float(fpx), "mark_msc": int(TM[last]), "mark_px": float(xq), "max_gap_ms": mg, "resolved": mg <= gap_ms, "trigger_msc": int(TM[trig])}


def money(d, px_in, px_out, lot): return d * (px_out - px_in) * lot


def main():
    sys.argv = ["x"]
    src = open(r"C:\Projects\KinoliveLines\study\manifest_runner.py", encoding="utf-8").read().split("REGIMES = [")[0]
    ns = {"__file__": r"C:\Projects\KinoliveLines\study\manifest_runner.py"}; exec(src, ns)
    H, man, R, META, effective_cfg = ns["H"], ns["man"], ns["R"], ns["META"], ns["effective_cfg"]
    H.DIRGATE = None
    PR = man["arms"]["baseline"]["package_regimes"]
    TICKS = r"C:\Projects\KinoliveLines\study\ticks"; tman = json.load(open(os.path.join(TICKS, "manifest.json")))
    SYM = tman["symbol"]; BLOT = H.BLOT
    END_MS = int(META["closed_bar_cutoff"]) * 1000; T0_MS = int(R["time"][0]) * 1000
    REGIMES = [("infinity", 175.70), ("u224016179", 267.42), ("bos", 360.37), ("reference_uncapped", 1000.0)]
    parts, bad_hash = [], []
    for k in sorted(tman["days"]):
        if not tman["days"][k].get("n"):
            continue
        fn = os.path.join(TICKS, "%s_%s.npz" % (SYM, k))
        h = hashlib.sha256(open(fn, "rb").read()).hexdigest()[:16]
        if h != tman["days"][k]["sha256"]:
            bad_hash.append(k); continue
        parts.append(np.load(fn))
    if bad_hash:
        raise SystemExit("tick file hash mismatch: %s" % bad_hash)
    TM = np.concatenate([p["time_msc"] for p in parts]).astype(np.int64); BID = np.concatenate([p["bid"] for p in parts]); ASK = np.concatenate([p["ask"] for p in parts])
    order = np.argsort(TM, kind="stable"); TM, BID, ASK = TM[order], BID[order], ASK[order]
    # the review-12 replay, verbatim, on the raw arrays it used (no END bound, no quote cleaning) - before/after only
    sys.path.insert(0, r"C:\Projects\KinoliveLines\study"); import delayed_entry_ticks_v1_replay as V1
    V1.TM, V1.BID, V1.ASK = TM, BID, ASK; V1.GAP_NEXT = np.concatenate([np.diff(TM), [0]])
    TM, BID, ASK, n_bad = clean_quotes(TM, BID, ASK)
    in_win = int(((TM >= T0_MS) & (TM < END_MS)).sum()); after = int((TM >= END_MS).sum())
    print("ticks %d (invalid dropped %d) | in window %d | after END (unused) %d | hashes verified %d days" % (len(TM), n_bad, in_win, after, len(parts)), flush=True)
    old = {}
    try:
        old = json.load(open(r"C:\Projects\KinoliveLines\study\delayed_entry_ticks_v1.json"))["rows"]
    except Exception:
        pass
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset": META["sha256"], "end_ms": END_MS,
           "ticks": {"n": int(len(TM)), "invalid_dropped": n_bad, "in_window": in_win, "after_end_unused": after, "signal_ms": SIGNAL_MS, "exec_ms": EXEC_MS, "gap_ms": GAP_MS, "gap_flag_ms": GAP_FLAG_MS},
           "execution_model": "bot-triggered market order; fill at the first tick >= trigger + EXEC_MS on the executable side; broker stop/target geometry checked at the fill quote for both arms", "rows": {}}
    KINDS = ("fill", "missed_win", "reject_invalid_stop", "reject_invalid_target", "reject_after_stop_print", "open_at_end", "pending_at_end", "no_quote")
    for drag in (0.0, 0.35):
        for uid, bal in REGIMES:
            cfg, rep = effective_cfg(PR[uid], bal, drag)
            cfg = H.cfg_strict(dict(cfg, delay_main_mid=1, delay_order="adverse"))
            H.TRACE = []; f = H.simulate(R, 7.0, cfg); rows = [x for x in H.TRACE if x.get("delayed_setup")]; H.TRACE = None
            dpl = H.drag_cost(cfg, 1.0)
            res = {"setups": len(rows), "cand": {k: 0 for k in KINDS}, "base": {k: 0 for k in KINDS}, "cand_wins": 0,
                   "cand_main_certified": 0.0, "cand_add_certified": 0.0, "base_main_certified": 0.0, "cand_main_observed": 0.0, "base_main_observed": 0.0,
                   "cand_unresolved_gap": 0, "base_unresolved_gap": 0, "cand_open_mtm": 0.0, "base_open_mtm": 0.0,
                   "paths_gap_gt5s": 0, "slip_vs_mid": [], "fill_delay_s": [], "bar_vs_tick_agree": 0, "bar_vs_tick_disagree": 0,
                   "changed_vs_v1": [], "examples": []}
            v1 = (old.get("%s|%.2f" % (uid, drag)) or {}).get("per_setup", {})
            per = {}
            for x in rows:
                d, lot = x["d"], x["lot"]; sl, tp, mid = float(x["sl"]), float(x["tp"]), float(x["mid"])
                nb = int(x.get("add_n", 0) or 0)
                c = replay(TM, BID, ASK, d, x["t"], sl, tp, mid, True, END_MS); b = replay(TM, BID, ASK, d, x["t"], sl, tp, mid, False, END_MS)
                res["cand"][c["kind"]] += 1; res["base"][b["kind"]] += 1
                if c.get("max_gap_ms", 0) > GAP_FLAG_MS: res["paths_gap_gt5s"] += 1
                cm = bm = None
                if c["kind"] == "fill":
                    cm = money(d, c["fill_px"], c["exit_px"], lot) - dpl * lot
                    ca = (money(d, c["fill_px"], c["exit_px"], BLOT) - dpl * BLOT) * nb
                    res["cand_main_observed"] += cm; res["cand_wins"] += 1 if c["win"] else 0
                    if c["resolved"]: res["cand_main_certified"] += cm; res["cand_add_certified"] += ca
                    else: res["cand_unresolved_gap"] += 1
                    res["slip_vs_mid"].append(round(d * (mid - c["fill_px"]), 2)); res["fill_delay_s"].append(round((c["fill_msc"] - (x["t"] + 60) * 1000) / 1000.0))
                    bw = x.get("win")
                    if bw is not None: res["bar_vs_tick_agree" if bool(bw) == bool(c["win"]) else "bar_vs_tick_disagree"] += 1
                elif c["kind"] == "open_at_end":
                    res["cand_open_mtm"] += money(d, c["fill_px"], c["mark_px"], lot)
                elif not c["resolved"]:
                    res["cand_unresolved_gap"] += 1
                if b["kind"] == "fill":
                    bm = money(d, b["fill_px"], b["exit_px"], lot) - dpl * lot
                    res["base_main_observed"] += bm
                    if b["resolved"]: res["base_main_certified"] += bm
                    else: res["base_unresolved_gap"] += 1
                elif b["kind"] == "open_at_end":
                    res["base_open_mtm"] += money(d, b["fill_px"], b["mark_px"], lot)
                elif not b["resolved"]:
                    res["base_unresolved_gap"] += 1
                key = str(x["t"])
                per[key] = {"c": c["kind"], "cw": c.get("win"), "cm": round(cm, 2) if cm is not None else None, "cg": c.get("max_gap_ms", 0), "b": b["kind"], "bw": b.get("win"), "bm": round(bm, 2) if bm is not None else None, "bg": b.get("max_gap_ms", 0)}
                # before/after: the review-12 function on the same setup
                c1 = V1.replay(d, x["t"], float(x["e0"]), sl, tp, mid, True); b1 = V1.replay(d, x["t"], float(x["e0"]), sl, tp, mid, False)
                cm1 = round(money(d, c1["fill_px"], c1["exit_px"], lot) - dpl * lot, 2) if c1["kind"] == "fill" else None
                bm1 = round(money(d, b1["fill_px"], b1["exit_px"], lot) - dpl * lot, 2) if b1["kind"] == "fill" else None
                o = {"c": c1["kind"], "cw": c1.get("win"), "cm": cm1, "cg": c1.get("max_gap_ms", 0), "b": b1["kind"], "bw": b1.get("win"), "bm": bm1, "bg": b1.get("max_gap_ms", 0)}
                per[key]["v1"] = o
                if (o["c"], o["cw"], o["cm"]) != (per[key]["c"], per[key]["cw"], per[key]["cm"]) or (o["b"], o["bw"], o["bm"]) != (per[key]["b"], per[key]["bw"], per[key]["bm"]):
                    res["changed_vs_v1"].append({"t": x["t"], "v1": o, "v2": {k: v for k, v in per[key].items() if k != "v1"}})
                if (not c["resolved"]) or (not b["resolved"]):
                    res.setdefault("newly_unresolved", []).append({"t": x["t"], "cand_gap_ms": c.get("max_gap_ms"), "base_gap_ms": b.get("max_gap_ms"), "cand": c["kind"], "base": b["kind"]})
                if len(res["examples"]) < 6:
                    res["examples"].append({"t_signal": x["t"], "d": d, "sl": round(sl, 2), "tp": round(tp, 2), "mid": round(mid, 2), "lot": lot, "funded_adds": nb, "candidate": c, "baseline": b})
            res["per_setup"] = per
            for k in ("cand_main_certified", "cand_add_certified", "base_main_certified", "cand_main_observed", "base_main_observed", "cand_open_mtm", "base_open_mtm"):
                res[k] = round(res[k], 2)
            for k in ("slip_vs_mid", "fill_delay_s"):
                v = res[k]; res[k] = {"n": len(v), "median": (sorted(v)[len(v) // 2] if v else None), "min": (min(v) if v else None), "max": (max(v) if v else None)}
            res["filled_win_rate"] = round(res["cand_wins"] / res["cand"]["fill"], 3) if res["cand"]["fill"] else None
            res["n_changed_vs_v1"] = len(res["changed_vs_v1"])
            out["rows"]["%s|%.2f" % (uid, drag)] = res
            cc, bb = res["cand"], res["base"]
            print("%-18s drag %.2f | setups %3d | cand: fill %3d (wr %s) missed %3d rej stop/target/after-print %d/%d/%d open %d pending %d | base: fill %3d rej %d/%d open %d | MAIN certified cand %8.2f (adds %6.2f) base %8.2f | observed cand %8.2f base %8.2f | unresolved(>30s) cand %d base %d | open MTM cand %.2f base %.2f | paths gap>5s %d | slip med %s delay med %ss | bar/tick %d/%d | changed vs v1 %d" % (
                uid, drag, res["setups"], cc["fill"], res["filled_win_rate"], cc["missed_win"], cc["reject_invalid_stop"], cc["reject_invalid_target"], cc["reject_after_stop_print"], cc["open_at_end"], cc["pending_at_end"],
                bb["fill"], bb["reject_invalid_stop"], bb["reject_invalid_target"], bb["open_at_end"], res["cand_main_certified"], res["cand_add_certified"], res["base_main_certified"], res["cand_main_observed"], res["base_main_observed"],
                res["cand_unresolved_gap"], res["base_unresolved_gap"], res["cand_open_mtm"], res["base_open_mtm"], res["paths_gap_gt5s"], res["slip_vs_mid"]["median"], res["fill_delay_s"]["median"], res["bar_vs_tick_agree"], res["bar_vs_tick_disagree"], res["n_changed_vs_v1"]), flush=True)
    json.dump(out, open(r"C:\Projects\KinoliveLines\study\delayed_entry_ticks.json", "w"), indent=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
