"""Event-correct TICK diagnostic of the nominated delayed-recovery-MAIN candidate
(ChatGPT review 12). Not a full path re-simulation: the SETUPS come from the
bar-level candidate path of each manifest regime (its own debt/jar/caps/balance,
live-order limits, adverse reading); every setup is then replayed on bid/ask ticks
with exact chronology:

  signal   = the setup's bar close (bar time + 60 s) + latency L
  fill     = first tick at/after signal+L with ask <= mid (buy) / bid >= mid (sell);
             fill price = that tick's ask / bid (never the theoretical midpoint)
  missed winner = bid >= tp (buy) / ask <= tp (sell) printed BEFORE any fill
  stop-first    = bid <= sl (buy) / ask >= sl (sell) printed BEFORE any fill (gap)
  outcome  = after the fill, the FIRST barrier in tick order: stop (bid<=sl / ask>=sl)
             or target (bid>=tp / ask<=tp), priced at that tick's executable side
  adds     = the number the bar-level package FUNDED for that setup (add_n), each
             filled at the main's fill tick (the midpoint IS the add trigger) at the
             bullet lot, exiting with the main - booked apart
  unresolved = a tick gap > 5 s between signal and resolution, or no resolution
             before the dataset end (counted, excluded from money)
Baseline comparison: the same signals' ORIGINAL trades (entry at the first tick
after signal+L, same stop/target) replayed with the same rules, so both arms carry
the same tick execution.
    python delayed_entry_ticks.py          (needs study/ticks/*.npz from fetch_ticks.py)
"""
import sys, json, os, bisect, time, hashlib, statistics
import numpy as np
sys.argv = ["x"]
src = open(r"C:\Projects\KinoliveLines\study\manifest_runner.py", encoding="utf-8").read().split("REGIMES = [")[0]
ns = {"__file__": r"C:\Projects\KinoliveLines\study\manifest_runner.py"}; exec(src, ns)
H, man, R, META, effective_cfg = ns["H"], ns["man"], ns["R"], ns["META"], ns["effective_cfg"]
H.DIRGATE = None
PR = man["arms"]["baseline"]["package_regimes"]
TICKS = r"C:\Projects\KinoliveLines\study\ticks"; tman = json.load(open(os.path.join(TICKS, "manifest.json")))
SYM = tman["symbol"]; LATENCY_MS = 1000; GAP_MS = 5000; BLOT = H.BLOT; SPREAD_BARS = 7.0
REGIMES = [("infinity", 175.70), ("u224016179", 267.42), ("bos", 360.37), ("reference_uncapped", 1000.0)]

# ---- ticks: one sorted array for the whole window
parts = [np.load(os.path.join(TICKS, "%s_%s.npz" % (SYM, k))) for k in sorted(tman["days"]) if tman["days"][k].get("n")]
TM = np.concatenate([p["time_msc"] for p in parts]); BID = np.concatenate([p["bid"] for p in parts]); ASK = np.concatenate([p["ask"] for p in parts])
order = np.argsort(TM, kind="stable"); TM, BID, ASK = TM[order], BID[order], ASK[order]
GAP_NEXT = np.concatenate([np.diff(TM), [0]])                   # ms to the next tick (gap diagnostics along the path)
print("ticks", len(TM), "from", TM[0], "to", TM[-1], flush=True)


def replay(d, t_signal, e0, sl, tp, mid, delayed):
    """returns dict(kind, fill_msc, fill_px, exit_msc, exit_px, win, gap) - kind in
    fill / missed_win / stop_first / no_fill_end / unresolved_gap"""
    start = int((t_signal + 60) * 1000 + LATENCY_MS)
    i = bisect.bisect_left(TM, start)
    n = len(TM)
    # phase 1: wait for the fill (delayed: the midpoint; baseline: the first tick)
    j = i
    fill = None
    mg = 0          # the largest tick gap (ms) met on the path to resolution
    while j < n:
        b, a = BID[j], ASK[j]
        if delayed:
            if d == 1:
                if b >= tp: return {"kind": "missed_win", "t": int(TM[j]), "max_gap_ms": mg}
                if b <= sl: return {"kind": "stop_first", "t": int(TM[j]), "max_gap_ms": mg}
                if a <= mid: fill = (j, a); break
            else:
                if a <= tp: return {"kind": "missed_win", "t": int(TM[j]), "max_gap_ms": mg}
                if a >= sl: return {"kind": "stop_first", "t": int(TM[j]), "max_gap_ms": mg}
                if b >= mid: fill = (j, b); break
        else:
            fill = (j, a if d == 1 else b); break
        mg = max(mg, int(GAP_NEXT[j]))
        j += 1
    if fill is None:
        return {"kind": "no_fill_end"}
    fj, fpx = fill
    # phase 2: first barrier after the fill, exact tick order, executable side
    k = fj + 1
    while k < n:
        b, a = BID[k], ASK[k]
        if d == 1:
            if b <= sl: return {"kind": "fill", "fill_msc": int(TM[fj]), "fill_px": float(fpx), "exit_msc": int(TM[k]), "exit_px": float(b), "win": False, "max_gap_ms": mg}
            if b >= tp: return {"kind": "fill", "fill_msc": int(TM[fj]), "fill_px": float(fpx), "exit_msc": int(TM[k]), "exit_px": float(b), "win": True, "max_gap_ms": mg}
        else:
            if a >= sl: return {"kind": "fill", "fill_msc": int(TM[fj]), "fill_px": float(fpx), "exit_msc": int(TM[k]), "exit_px": float(a), "win": False, "max_gap_ms": mg}
            if a <= tp: return {"kind": "fill", "fill_msc": int(TM[fj]), "fill_px": float(fpx), "exit_msc": int(TM[k]), "exit_px": float(a), "win": True, "max_gap_ms": mg}
        mg = max(mg, int(GAP_NEXT[k]))
        k += 1
    return {"kind": "unresolved_end", "fill_msc": int(TM[fj]), "fill_px": float(fpx), "max_gap_ms": mg}


def money(d, px_in, px_out, lot): return d * (px_out - px_in) * lot


out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dataset": META["sha256"], "ticks": {"n": int(len(TM)), "days": len(tman["days"]), "latency_ms": LATENCY_MS, "gap_ms": GAP_MS}, "rows": {}}
for drag in (0.0, 0.35):
    for uid, bal in REGIMES:
        cfg, rep = effective_cfg(PR[uid], bal, drag)
        cfg = H.cfg_strict(dict(cfg, delay_main_mid=1, delay_order="adverse"))
        H.TRACE = []; f = H.simulate(R, 7.0, cfg); rows = [x for x in H.TRACE if x.get("delayed_setup")]; H.TRACE = None
        res = {"setups": len(rows), "fill": 0, "missed_win": 0, "stop_first": 0, "unresolved": 0, "no_fill_end": 0,
               "cand_main": 0.0, "cand_add": 0.0, "base_main": 0.0, "base_add": 0.0, "base_fill": 0, "base_unresolved": 0,
               "cand_wins": 0, "slip_vs_mid": [], "base_slip_vs_close": [], "fill_delay_s": [], "bar_vs_tick_agree": 0, "bar_vs_tick_disagree": 0, "examples": [],
               "path_gap_gt5s": 0, "path_gap_gt30s": 0, "cand_main_gapfree5s": 0.0, "fills_gapfree5s": 0}
        dpl = H.drag_cost(cfg, 1.0)       # drag per 1.0 lot
        for x in rows:
            # the setup geometry exactly as the harness recorded it at the signal (full precision)
            d, lot = x["d"], x["lot"]; e0, sl, tp, mid = float(x["e0"]), float(x["sl"]), float(x["tp"]), float(x["mid"])
            nb = int(x.get("add_n", 0) or 0)        # adds the package FUNDED on the bar-level path (0 when never filled there)
            c = replay(d, x["t"], e0, sl, tp, mid, True); b = replay(d, x["t"], e0, sl, tp, mid, False)
            res[c["kind"] if c["kind"] in ("fill", "missed_win", "stop_first", "no_fill_end") else "unresolved"] += 1
            _mg = c.get("max_gap_ms", 0)
            if _mg > 5000: res["path_gap_gt5s"] += 1
            if _mg > 30000: res["path_gap_gt30s"] += 1
            if c["kind"] == "fill":
                m = money(d, c["fill_px"], c["exit_px"], lot) - dpl * lot
                res["cand_main"] += m; res["cand_wins"] += 1 if c["win"] else 0
                if _mg <= 5000: res["cand_main_gapfree5s"] += m; res["fills_gapfree5s"] += 1
                res["cand_add"] += (money(d, c["fill_px"], c["exit_px"], BLOT) - dpl * BLOT) * nb
                res["slip_vs_mid"].append(round(d * (mid - c["fill_px"]), 2))     # negative = worse than the midpoint
                res["fill_delay_s"].append(round((c["fill_msc"] - (x["t"] + 60) * 1000) / 1000.0))
                bw = x.get("win")
                if bw is not None:
                    res["bar_vs_tick_agree" if bool(bw) == bool(c["win"]) else "bar_vs_tick_disagree"] += 1
            if b["kind"] == "fill":
                res["base_fill"] += 1
                res["base_main"] += money(d, b["fill_px"], b["exit_px"], lot) - dpl * lot
                # baseline adds are NOT replayed here (they would need their own midpoint event on the
                # baseline path); base_add stays 0 and the comparison is MAIN vs MAIN
                res["base_slip_vs_close"].append(round(d * (e0 - b["fill_px"]), 2))
            else:
                res["base_unresolved"] += 1
            if len(res["examples"]) < 6:
                res["examples"].append({"t_signal": x["t"], "d": d, "e0": round(e0, 2), "sl": round(sl, 2), "tp": round(tp, 2), "mid": round(mid, 2), "lot": lot, "funded_adds": nb,
                                        "candidate": c, "baseline": b})
        for k in ("cand_main", "cand_add", "base_main", "base_add", "cand_main_gapfree5s"):
            res[k] = round(res[k], 2)
        for k in ("slip_vs_mid", "base_slip_vs_close", "fill_delay_s"):
            v = res[k]; res[k] = {"n": len(v), "median": (sorted(v)[len(v) // 2] if v else None), "min": (min(v) if v else None), "max": (max(v) if v else None)}
        res["filled_win_rate"] = round(res["cand_wins"] / res["fill"], 3) if res["fill"] else None
        out["rows"]["%s|%.2f" % (uid, drag)] = res
        print("%-18s drag %.2f | setups %3d: fills %3d (wr %s) missed-win %3d stop-first %2d unresolved %2d end %d | candidate main %8.2f adds %7.2f | baseline same signals main %8.2f (fills %d, unresolved %d) | slip vs mid med %s fill delay med %ss | bar/tick agree %d disagree %d | paths with gap>5s %d (>30s %d); gap-free fills %d main %.2f" % (
            uid, drag, res["setups"], res["fill"], res["filled_win_rate"], res["missed_win"], res["stop_first"], res["unresolved"], res["no_fill_end"], res["cand_main"], res["cand_add"],
            res["base_main"], res["base_fill"], res["base_unresolved"], res["slip_vs_mid"]["median"], res["fill_delay_s"]["median"], res["bar_vs_tick_agree"], res["bar_vs_tick_disagree"],
            res["path_gap_gt5s"], res["path_gap_gt30s"], res["fills_gapfree5s"], res["cand_main_gapfree5s"]), flush=True)
json.dump(out, open(r"C:\Projects\KinoliveLines\study\delayed_entry_ticks.json", "w"), indent=1)
print("DONE", flush=True)
