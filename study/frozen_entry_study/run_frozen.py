"""FROZEN replication runner (reviews 16 + 17): resolves EVERY dependency inside this bundle
directory, hashes the files it actually loaded against the manifest, enforces the manifest's
status, scored epochs, balances and package snapshot, certifies the quote coverage, and runs on
the scored window, on ONE clock per regime and cost basis:
  * the three-arm engine (tick_engine.run_regime): baseline / delayed = recovery-only delayed
    MAIN (the original comparator) / half_main (control);
  * the matrix cells (tick_engine_matrix.run_cells, same engine, same semantics):
    "immediate|current|cap_on" (= the baseline again, an engine-identity check) and the selected
    challenger "delay_always|all_bos|cap_on" (review 17).
Policy checks on the challenger every run: it delays OUTSIDE recovery (delayed_out_debt > 0), it
refuses no eligible recovery BOS by the debt gate (debt_gate == 0, admitted_by_allowance counted),
and it keeps the daily cap (policy cap on, cap_waived_off == 0, day_cap refusals counted).

    python run_frozen.py --manifest <entry_study_manifest.json> --ticks <dir> --bars <npz> [--out <json>]
                         [--dev-fixture START END]            (demonstration / reproduction: status DRAFT
                                                               allowed, window free, balances = development)
                         [--reproduce <tick_engine_matrix.json>] (dev-fixture only: compare every arm with the
                                                               cached development rows, tolerance 0.01)
Nothing from the working tree is importable from here: sys.path is set to this bundle first and the
loaded modules' __file__ must sit inside it, or the run aborts.
"""
import sys, os, json, hashlib, time
BUNDLE = os.path.dirname(os.path.abspath(__file__))
ARGS = list(sys.argv); sys.argv = ["x"]
CELLS = ["immediate|current|cap_on", "delay_always|all_bos|cap_on"]
CHALLENGER = "delay_always|all_bos|cap_on"
TOL = 0.01


def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


def h(path): return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def coverage(TM, start, end, np):
    """per UTC day: share of 1-minute buckets with a valid tick and the largest gap (prereg: covered when
    share >= 0.97 and gap <= 120 s; adequate when >= 36 of the 42 days are covered)"""
    cov = {}; d = start - start % 86400
    while d < end:
        lo, hi = max(d, start) * 1000, min(d + 86400, end) * 1000
        sel = (TM >= lo) & (TM < hi); t = TM[sel]
        mins = int((hi - lo) // 60000) or 1
        buckets = len(np.unique((t - lo) // 60000)) if len(t) else 0
        gaps = np.diff(t) if len(t) > 1 else np.array([0])
        mg = max(int(gaps.max()) if len(t) > 1 else 0, int(t[0] - lo) if len(t) else int(hi - lo), int(hi - t[-1]) if len(t) else 0)
        share = buckets / mins
        cov[time.strftime("%Y-%m-%d", time.gmtime(d))] = {"minute_share": round(share, 4), "max_gap_s": round(mg / 1000.0, 1), "ticks": int(len(t)),
                                                          "covered": bool(share >= 0.97 and mg <= 120000)}
        d += 86400
    return cov


def policy_checks(row, cfg_day_cap):
    c = row["counts"]; p = row["policy"]
    return {"delays_outside_recovery": c.get("delayed_out_debt", 0) > 0, "delayed_out_debt": c.get("delayed_out_debt", 0), "delayed_in_debt": c.get("delayed_in_debt", 0),
            "no_debt_gate_refusal": c.get("debt_gate", 0) == 0, "admitted_by_allowance": c.get("admitted_by_allowance", 0),
            "cap_retained": (p.get("cap") == "on" and c.get("cap_waived_off", 0) == 0), "day_cap_refusals": c.get("day_cap", 0), "package_day_cap": cfg_day_cap,
            "all_pass": (c.get("delayed_out_debt", 0) > 0 and c.get("debt_gate", 0) == 0 and p.get("cap") == "on" and c.get("cap_waived_off", 0) == 0)}


def main():
    man_path = arg("--manifest"); man = json.load(open(man_path, encoding="utf-8"))
    fixture = "--dev-fixture" in ARGS
    # 1. manifest status
    if man.get("status") != "FROZEN" and not fixture:
        raise SystemExit("manifest status is %r - a scored run needs FROZEN" % man.get("status"))
    # 2. the bundle on disk must hash exactly as the manifest recorded it (every file, incl. data pins)
    want = man["frozen_copy"]["files"]; bad = {}
    for fn, hv in want.items():
        p = os.path.join(BUNDLE, fn)
        if not os.path.exists(p) or h(p) != hv: bad[fn] = (hv, h(p) if os.path.exists(p) else None)
    extra = sorted(f for f in os.listdir(BUNDLE) if f not in want and not f.startswith("__") and f not in ("run_frozen.py", "owl_nest_users.json", "owl_secrets.json")
                   and not f.startswith("frozen_result") and not f.startswith("frozen_fixture"))
    if bad: raise SystemExit("BUNDLE DRIFT vs manifest: %s" % bad)
    # 3. import only from the bundle. The bot module reads account files at import; the bundle holds
    #    NO real credentials - harmless placeholders are created if absent (never hashed, gitignored)
    for fn, body in (("owl_secrets.json", '{"mt5_password": "placeholder-not-a-credential"}'), ("owl_nest_users.json", "[]")):
        p = os.path.join(BUNDLE, fn)
        if not os.path.exists(p): open(p, "w", encoding="utf-8").write(body)
    sys.path.insert(0, BUNDLE)
    for m in list(sys.modules):
        if m in ("tick_engine", "tick_engine_matrix", "tick_engine_forward", "manifest_runner", "dev_dataset", "harness", "structure_bos_bot", "owl_package", "compte_controller", "pb_gate"):
            del sys.modules[m]
    import tick_engine as E
    import tick_engine_matrix as M
    import harness, structure_bos_bot, owl_package, compte_controller, dev_dataset
    loaded = {"tick_engine": E.__file__, "tick_engine_matrix": M.__file__, "harness": harness.__file__, "structure_bos_bot": structure_bos_bot.__file__,
              "owl_package": owl_package.__file__, "compte_controller": compte_controller.__file__, "dev_dataset": dev_dataset.__file__}
    outside = {k: v for k, v in loaded.items() if os.path.dirname(os.path.abspath(v)).lower() != BUNDLE.lower()}
    if outside: raise SystemExit("module loaded OUTSIDE the bundle: %s" % outside)
    assert M.E is E, "the matrix module must use the bundle's engine"
    loaded_hashes = {k: h(v) for k, v in loaded.items()}
    # 4. scored window and balances: from the manifest when FROZEN; free only for the fixture
    if fixture:
        start, end = int(ARGS[ARGS.index("--dev-fixture") + 1]), int(ARGS[ARGS.index("--dev-fixture") + 2])
        balances = man["package_mapping"]["regimes"]
    else:
        start, end = int(man["scored_start"]), int(man["scored_end"]); balances = man["balances_at_freeze"]
        assert end - start == 42 * 86400, "scored window must be 42 days"
        assert balances, "balances_at_freeze missing"
        import calendar
        assert man.get("frozen_at") and start >= calendar.timegm(time.strptime(man["frozen_at"], "%Y-%m-%dT%H:%M:%SZ")), "scored_start must follow frozen_at (no backdating)"
    tdir, bars_npz = arg("--ticks"), arg("--bars"); out = arg("--out", os.path.join(BUNDLE, "frozen_result.json"))
    import numpy as np
    Rb = np.load(bars_npz)["R"]; Rb = Rb[Rb["time"] < end]; warm = int((Rb["time"] < start).sum())
    TM, BID, ASK, n_bad, END = E.load_ticks(tdir, start * 1000, end * 1000)
    if not len(TM): raise SystemExit("no ticks in the scored window yet")
    cov = coverage(TM, start, end, np); n_cov = sum(1 for v in cov.values() if v["covered"])
    rule = man.get("coverage_rule", {"minute_share_min": 0.97, "max_gap_s": 120, "days_covered_min": 36})
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "bundle": BUNDLE, "manifest": man_path, "manifest_status": man.get("status"), "fixture": fixture,
           "loaded_modules": loaded, "loaded_hashes": loaded_hashes, "bundle_extra_files": extra, "scored": [start, end],
           "scored_utc": [time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(start)), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(end))],
           "bars": {"file": bars_npz, "sha256": h(bars_npz), "n": int(len(Rb)), "warmup": warm}, "ticks": {"dir": tdir, "n": int(len(TM)), "invalid": n_bad,
           "first_gap_s": round((int(TM[0]) - start * 1000) / 1000.0, 1)},
           "coverage": cov, "days_covered": n_cov, "coverage_rule": rule, "adequate_coverage": (bool(n_cov >= int(rule.get("days_covered_min", 36))) if not fixture else None),
           "balances": balances, "package_snapshot": h(os.path.join(BUNDLE, "compte_frozen_manifest.json")),
           "baseline_note": "the baseline is the EARLIER package snapshot (compte_frozen_manifest.json pinned in this bundle), NOT today's live configuration",
           "cells": CELLS, "challenger": CHALLENGER, "rows": {}, "checks": {}}
    print("bundle OK (%d files hashed), modules inside bundle, scored %s -> %s, ticks %d, bars %d (warm-up %d), coverage %d/%d days" % (
        len(want), res["scored_utc"][0], res["scored_utc"][1], len(TM), len(Rb), warm, n_cov, len(cov)), flush=True)
    regimes = (arg("--regimes") or "infinity,u224016179,bos,reference_uncapped").split(","); drags = [float(x) for x in (arg("--drags") or "0,0.35").split(",")]
    repro = json.load(open(arg("--reproduce")))["rows"] if (fixture and arg("--reproduce")) else None
    all_ok = True
    for uid in regimes:
        cfg0, _ = E.effective_cfg(E.PR[uid], balances[uid], 0.0); opps, bars = E.streams(cfg0, Rb)
        for drag in drags:
            key = "%s|%.2f" % (uid, drag); t0 = time.time()
            row, rep = E.run_regime(uid, drag, TM, BID, ASK, END, opps, bars, start_ms=start * 1000, balance=balances[uid])
            cells, _, dup = M.run_cells(uid, drag, TM, BID, ASK, END, opps, bars, CELLS, start_ms=start * 1000, balance=balances[uid])
            chk = {"engine_identity": (cells[CELLS[0]]["net"] == row["baseline"]["net"] and cells[CELLS[0]]["trades"] == row["baseline"]["trades"]),
                   "challenger_policy": policy_checks(cells[CHALLENGER], ("none (package has no cap)" if dup.get("no_cap") else "package cap")), "duplicates": dup}
            if repro is not None:
                dev = repro.get(key, {}).get("arms", {}); cmp = {}
                pairs = [("baseline", "immediate|current|cap_on", row["baseline"]), ("delayed", "delay_debt|current|cap_on", row["delayed"]), ("half_main", "half_main", row["half_main"]),
                         ("cell:" + CELLS[0], CELLS[0], cells[CELLS[0]]), ("cell:" + CHALLENGER, CHALLENGER, cells[CHALLENGER])]
                for name, dkey, r in pairs:
                    d = dev.get(dkey)
                    if not d: cmp[name] = "no development row"; continue
                    diffs = {f: (r[f], d[f]) for f in ("net", "cc_dd", "mtm_dd", "trades", "wins") if abs(float(r[f]) - float(d[f])) > TOL}
                    cmp[name] = "match" if not diffs else diffs
                chk["reproduction"] = cmp; chk["reproduced"] = all(v == "match" for v in cmp.values())
                all_ok = all_ok and chk["reproduced"]
            all_ok = all_ok and chk["engine_identity"] and chk["challenger_policy"]["all_pass"]
            res["rows"][key] = {"effective": rep, "arms": row, "cells": cells}; res["checks"][key] = chk
            for name, a in list(row.items()) + [("cell:" + k, v) for k, v in cells.items()]:
                print("%-18s drag %.2f %-32s | net %8.2f cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d wr %s pf %s missed %s | %.0fs" % (
                    uid, drag, name, a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"], a.get("win_rate"), a.get("profit_factor"),
                    a.get("missed_winners", a.get("counts", {}).get("missed_win")), time.time() - t0), flush=True)
            print("   checks: identity %s | challenger policy %s (delayed out/in debt %d/%d, debt_gate refusals %d, admitted %d, cap on + day_cap refusals %d)%s" % (
                chk["engine_identity"], chk["challenger_policy"]["all_pass"], chk["challenger_policy"]["delayed_out_debt"], chk["challenger_policy"]["delayed_in_debt"],
                cells[CHALLENGER]["counts"].get("debt_gate", 0), chk["challenger_policy"]["admitted_by_allowance"], chk["challenger_policy"]["day_cap_refusals"],
                (" | reproduction " + str(chk.get("reproduction"))) if repro is not None else ""), flush=True)
            json.dump(res, open(out, "w"), indent=1)
    res["all_checks_pass"] = all_ok
    json.dump(res, open(out, "w"), indent=1)
    print("DONE ->", out, "| all checks pass:", all_ok, flush=True)


if __name__ == "__main__":
    main()
