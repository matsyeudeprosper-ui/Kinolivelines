"""Per-regime paired intervals + shifted controls (ChatGPT review 11, step 3).

Runs AFTER manifest_runner.py on the same effective configs (manifest only,
live-order limits, canonical reference, requested-multiplier add rule):
  * paired exact-horizon block bootstrap (5-day nominated; 3 / 10 sensitivities;
    seed 7; 3000 resamples; degenerate counted) of CC-drawdown ratio and net diff;
  * 20 cyclic block shifts of the primary's own schedule keyed by the baseline
    opportunity id; a shift whose unkeyed opportunities exceed 10% of its
    stream is reported UNMATCHED and excluded from the beats count (both counts shown).
Rows cached per (regime, drag, effective cfg) under the same strengthened key.
"""
import sys, json, random, statistics, hashlib, time
sys.argv = ["x"]
src = open(r"C:\Projects\KinoliveLines\study\manifest_runner.py", encoding="utf-8").read().split("REGIMES = [")[0]
ns = {"__file__": r"C:\Projects\KinoliveLines\study\manifest_runner.py"}; exec(src, ns)
H, man, R, META = ns["H"], ns["man"], ns["R"], ns["META"]
run, States, reference, hook_directional, hook_keyed, effective_cfg, dd_of, REF_CANON = (
    ns["run"], ns["States"], ns["reference"], ns["hook_directional"], ns["hook_keyed"], ns["effective_cfg"], ns["dd_of"], ns["REF_CANON"])
PR = man["arms"]["baseline"]["package_regimes"]
T0 = int(R["time"][0]); T1 = int(R["time"][-1]) + 60; N_DAYS = (T1 - T0 + 86399) // 86400
SHIFTS = man["arms"]["block_shift_control"]["shifts"]; SEED = 7; REPS = 3000; BLOCKS = (5, 3, 10); UNMATCHED_FRAC = 0.10
REGIMES = [("infinity", "valere", 175.70), ("u224016179", "valere_cap3", 267.42), ("bos", "special_10", 360.37), ("reference_uncapped", "reference", 1000.0)]


def by_day(tr):
    d = {}
    for x in tr: d.setdefault((x["tc"] - T0) // 86400, []).append(x["pnl"])
    return d


def cc_bootstrap(trA, trB, block_days):
    A, B = by_day(trA), by_day(trB); r = random.Random(SEED)
    ratios, diffs, degenerate = [], [], 0
    for _ in range(REPS):
        sa, sb, got = [], [], 0
        while got < N_DAYS:
            s = r.randrange(0, N_DAYS - block_days + 1); take = min(block_days, N_DAYS - got)
            for dday in range(s, s + take):
                sa.extend(A.get(dday, [])); sb.extend(B.get(dday, []))
            got += take
        da, db = dd_of(sa), dd_of(sb)
        if db <= 0:
            degenerate += 1; continue
        ratios.append(da / db); diffs.append(sum(sa) - sum(sb))
    ratios.sort(); diffs.sort(); q = lambda xs, p: xs[int(p * (len(xs) - 1))] if xs else None
    return {"cc_ratio_ci90": [round(q(ratios, 0.05), 3), round(q(ratios, 0.95), 3)], "net_diff_ci90": [round(q(diffs, 0.05), 2), round(q(diffs, 0.95), 2)],
            "resamples": len(ratios), "degenerate": degenerate}


def _h(path): return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]
KEY = ":".join([META["sha256"][:16], _h(r"C:\Projects\KinoliveLines\live\lab\harness.py"), hashlib.sha256(src.encode()).hexdigest()[:16],
                _h(r"C:\Projects\KinoliveLines\live\lab\compte_controller.py"), _h(r"C:\Projects\KinoliveLines\live\structure_bos_bot.py"),
                hashlib.sha256(json.dumps(REF_CANON, sort_keys=True).encode()).hexdigest()[:8],
                hashlib.sha256(json.dumps({"SHIFTS": SHIFTS, "SEED": SEED, "REPS": REPS, "BLOCKS": BLOCKS, "UNMATCHED_FRAC": UNMATCHED_FRAC, "spread": 7.0}, sort_keys=True).encode()).hexdigest()[:8]])
ROWS = r"C:\Projects\KinoliveLines\study\manifest_regime_stats_rows.json"
try:
    cache = json.load(open(ROWS)); cache = cache if cache.get("key") == KEY else {"key": KEY, "rows": {}}
except Exception:
    cache = {"key": KEY, "rows": {}}
out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key": KEY, "n_days": N_DAYS, "rows": {}}
print("days", N_DAYS, "key", KEY, flush=True)
for drag in (0.0, 0.35):
    basis = "B" if drag else "A"; S = None
    for uid, pname, bal in REGIMES:
        cfg, rep = effective_cfg(PR[uid], bal, drag)
        ck = "%s|%.2f|%s" % (uid, drag, hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:12])
        if ck in cache["rows"]:
            row = cache["rows"][ck]; out["rows"][ck] = row
            print("%-18s drag %.2f %s (cached) ratio %s CI90 %s | shifts beats dd %s" % (uid, drag, basis, row["ratio"], row["boot"]["5"]["cc_ratio_ci90"], row["shifts"]["beats_dd_matched"]), flush=True)
            continue
        if S is None:
            S = States(reference(drag))
        fb, trb = run(cfg); fp, trp = run(cfg, hook_directional(S), True)
        ddb, ddp = dd_of([x["pnl"] for x in trb]), dd_of([x["pnl"] for x in trp])
        boot = {str(b): cc_bootstrap(trp, trb, b) for b in BLOCKS}
        base_ids = [x["t"] for x in trb]; sched = {x["t"]: x["req_mult"] for x in trp}
        sh = []
        for s_ in SHIFTS:
            seq = [sched.get(t, 1.0) for t in base_ids]; off = s_ % len(seq); seq = seq[off:] + seq[:off]
            mult = dict(zip(base_ids, seq)); miss = [0]; fc, tc_ = run(cfg, hook_keyed(mult, miss), True)
            sh.append({"shift": s_, "net": fc["net"], "dd_cc": round(dd_of([x["pnl"] for x in tc_]), 2), "n": len(tc_), "unkeyed": miss[0],
                       "unmatched": miss[0] > UNMATCHED_FRAC * max(1, len(tc_))})
        matched_sh = [x for x in sh if not x["unmatched"]]
        row = {"regime": uid, "package": pname, "drag": drag, "basis": basis, "balance_used": bal,
               "baseline": {"net": fb["net"], "dd_cc": round(ddb, 2), "n": len(trb)}, "primary": {"net": fp["net"], "dd_cc": round(ddp, 2), "n": len(trp)},
               "ratio": round(ddp / ddb, 3) if ddb else None, "boot": boot,
               "shifts": {"rows": sh, "n_matched": len(matched_sh), "n_unmatched": len(sh) - len(matched_sh),
                          "beats_net_all": sum(1 for x in sh if x["net"] < fp["net"]), "beats_dd_all": sum(1 for x in sh if x["dd_cc"] > ddp),
                          "beats_net_matched": sum(1 for x in matched_sh if x["net"] < fp["net"]), "beats_dd_matched": sum(1 for x in matched_sh if x["dd_cc"] > ddp),
                          "net_median": sorted(x["net"] for x in sh)[len(sh) // 2], "dd_median": sorted(x["dd_cc"] for x in sh)[len(sh) // 2],
                          "unkeyed_max": max(x["unkeyed"] for x in sh)}}
        cache["rows"][ck] = row; json.dump(cache, open(ROWS, "w"), indent=1); out["rows"][ck] = row
        b5 = boot["5"]
        print("%-18s drag %.2f %s | base %7.2f/%6.2f primary %7.2f/%6.2f ratio %s | CI90 ratio %s (b3 %s b10 %s) net diff %s degen %d | shifts: beats net %d/%d dd %d/%d matched (%d unmatched; all %d/20 %d/20) unkeyed max %d" % (
            uid, drag, basis, fb["net"], ddb, fp["net"], ddp, row["ratio"], b5["cc_ratio_ci90"], boot["3"]["cc_ratio_ci90"], boot["10"]["cc_ratio_ci90"], b5["net_diff_ci90"], b5["degenerate"],
            row["shifts"]["beats_net_matched"], len(matched_sh), row["shifts"]["beats_dd_matched"], len(matched_sh), row["shifts"]["n_unmatched"],
            row["shifts"]["beats_net_all"], row["shifts"]["beats_dd_all"], row["shifts"]["unkeyed_max"]), flush=True)
H.DIRGATE = None
json.dump(out, open(r"C:\Projects\KinoliveLines\study\manifest_regime_stats.json", "w"), indent=1)
print("DONE", flush=True)
