"""FROZEN-replication adapter for the three-arm tick engine (review 15, item 4).

Runs the SAME engine on a SCORED window with explicit inputs, cold-flat initialisation, the
manifest's balances and package values, hash assertions on every source the manifest lists,
and per-day valid-quote coverage certification. Nothing is read from the development dataset
except for structural warm-up when the pinned bars include it.

    python tick_engine_forward.py --manifest review/entry_study_manifest.json
        --bars <npz with R> --ticks <dir with manifest.json> --scored START_EPOCH END_EPOCH
        --out <json> [--regimes infinity,...] [--drags 0,0.35] [--dev-fixture]

Initialisation convention (same for every arm): run 0, debt 0, jar 0, streak 0, no continuation
allowance, no pending, no position; balance = manifest balances; structural warm-up = bars before
START (signals before START are not traded); first incoming gap measured from START.
"""
import sys, os, json, time, hashlib
import numpy as np
ARGS = list(sys.argv); sys.argv = ["x"]
ROOT = r"C:\Projects\KinoliveLines"
sys.path.insert(0, os.path.join(ROOT, "study"))
import tick_engine as E


def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


def h(rel): return hashlib.sha256(open(os.path.join(ROOT, rel), "rb").read()).hexdigest()[:16]


def main():
    man_path = arg("--manifest", os.path.join(ROOT, "review", "entry_study_manifest.json"))
    man = json.load(open(man_path, encoding="utf-8"))
    dev_fixture = "--dev-fixture" in ARGS
    # 1. drift check: every listed source must hash as recorded (the frozen copy aborts otherwise)
    drift = {k: (v, h(k)) for k, v in man["sources"].items() if h(k) != v}
    if drift and not dev_fixture:
        raise SystemExit("SOURCE DRIFT vs manifest: %s" % drift)
    if drift:
        print("dev-fixture: source drift tolerated:", list(drift), flush=True)
    start, end = int(arg("--scored").split()[0]) if " " in (arg("--scored") or "") else int(ARGS[ARGS.index("--scored") + 1]), int(ARGS[ARGS.index("--scored") + 2])
    assert end - start == 42 * 86400 or dev_fixture, "scored window must be exactly 42 days"
    bars_npz = arg("--bars"); tdir = arg("--ticks"); out = arg("--out", os.path.join(ROOT, "study", "tick_engine_forward.json"))
    regimes = (arg("--regimes") or "infinity,u224016179,bos,reference_uncapped").split(","); drags = [float(x) for x in (arg("--drags") or "0,0.35").split(",")]
    balances = man.get("balances_at_freeze") or man["package_mapping"]["regimes"]
    # 2. bars: a pinned npz with R (structural warm-up allowed BEFORE start; nothing after end)
    Rb = np.load(bars_npz)["R"]; Rb = Rb[(Rb["time"] < end)]
    warm = int((Rb["time"] < start).sum()); print("bars %d (warm-up before start %d), ticks dir %s" % (len(Rb), warm, tdir), flush=True)
    # 3. ticks: only the scored window
    TM, BID, ASK, n_bad, END = E.load_ticks(tdir, start * 1000, end * 1000)
    print("scored ticks %d, invalid dropped %d, first %d (gap from start %.1f s), last %d" % (len(TM), n_bad, int(TM[0]) if len(TM) else -1, ((int(TM[0]) - start * 1000) / 1000.0) if len(TM) else -1, int(TM[-1]) if len(TM) else -1), flush=True)
    # 4. coverage certification per UTC day (share of 1-minute buckets with a valid tick; largest gap)
    cov = {}
    day0 = start - start % 86400
    d = day0
    while d < end:
        lo, hi = max(d, start) * 1000, min(d + 86400, end) * 1000
        sel = (TM >= lo) & (TM < hi); t = TM[sel]
        mins = int((hi - lo) // 60000) or 1
        buckets = len(np.unique((t - lo) // 60000)) if len(t) else 0
        gaps = np.diff(t) if len(t) > 1 else np.array([0])
        mg = max(int(gaps.max()) if len(t) > 1 else 0, int(t[0] - lo) if len(t) else int(hi - lo), int(hi - t[-1]) if len(t) else 0)
        share = buckets / mins
        cov[time.strftime("%Y-%m-%d", time.gmtime(d))] = {"minute_share": round(share, 4), "max_gap_s": round(mg / 1000.0, 1), "ticks": int(len(t)), "covered": bool(share >= 0.97 and mg <= 120000)}
        d += 86400
    n_cov = sum(1 for v in cov.values() if v["covered"]); print("coverage: %d / %d days covered" % (n_cov, len(cov)), flush=True)
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "manifest": man_path, "manifest_status": man.get("status"), "scored": [start, end],
           "scored_utc": [time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(start)), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(end))],
           "bars": {"file": bars_npz, "sha256": hashlib.sha256(open(bars_npz, "rb").read()).hexdigest()[:16], "n": int(len(Rb)), "warmup": warm},
           "ticks": {"dir": tdir, "n": int(len(TM)), "invalid": n_bad}, "coverage": cov, "days_covered": n_cov, "adequate_coverage": bool(n_cov >= 36) if not dev_fixture else None,
           "balances": balances, "init": "cold-flat at start; manifest balances; warm-up bars before start not traded", "dev_fixture": dev_fixture, "rows": {}}
    for uid in regimes:
        cfg0, _ = E.effective_cfg(E.PR[uid], balances[uid], 0.0)
        opps, bars = E.streams(cfg0, Rb)
        n_scored = sum(1 for o in opps if (o["t"] + 60) * 1000 + E.SIGNAL_MS >= start * 1000)
        print("%s: opportunities %d (scored %d)" % (uid, len(opps), n_scored), flush=True)
        for drag in drags:
            t0 = time.time(); row, rep = E.run_regime(uid, drag, TM, BID, ASK, END, opps, bars, start_ms=start * 1000, balance=balances[uid])
            res["rows"]["%s|%.2f" % (uid, drag)] = {"effective": rep, "arms": row}
            for name, a in row.items():
                c = a["counts"]
                print("%-18s drag %.2f %-9s | net %8.2f (+open %8.2f) cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d | setups %d missed %d | rej %d cancel %d | gap flag %d unres %d | open/pending at end %d/%d | %.0fs" % (
                    uid, drag, name, a["net"], a["net_with_open_mtm"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"], c["setups"], c["missed_win"], c["reject_geom"], c.get("cancel_stop_before_submission", 0),
                    a["gap_flagged_trades"], a["gap_unresolved_trades"], c["open_at_end"], c["pending_at_end"], time.time() - t0), flush=True)
            json.dump(res, open(out, "w"), indent=1)
    print("DONE ->", out, flush=True)


if __name__ == "__main__":
    main()
