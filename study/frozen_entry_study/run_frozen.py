"""FROZEN replication runner (review 16): resolves EVERY dependency inside this bundle directory,
hashes the files it actually loaded against the manifest, enforces the manifest's status, scored
epochs, balances and package snapshot, and runs the three-arm engine on the scored window.

    python run_frozen.py --manifest <entry_study_manifest.json> --ticks <dir> --bars <npz> [--out <json>]
                         [--dev-fixture START END]   (demonstration only: status DRAFT allowed, window free)

Nothing from the working tree is importable from here: sys.path is set to this bundle first and the
loaded modules' __file__ must sit inside it, or the run aborts.
"""
import sys, os, json, hashlib, time
BUNDLE = os.path.dirname(os.path.abspath(__file__))
ARGS = list(sys.argv); sys.argv = ["x"]


def arg(name, default=None):
    return ARGS[ARGS.index(name) + 1] if name in ARGS else default


def h(path): return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


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
    extra = sorted(f for f in os.listdir(BUNDLE) if f not in want and not f.startswith("__") and f not in ("run_frozen.py", "owl_nest_users.json"))
    if bad: raise SystemExit("BUNDLE DRIFT vs manifest: %s" % bad)
    # 3. import only from the bundle. The bot module reads account files at import; the bundle holds
    #    NO real credentials - harmless placeholders are created if absent (never hashed, gitignored)
    for fn, body in (("owl_secrets.json", '{"mt5_password": "placeholder-not-a-credential"}'), ("owl_nest_users.json", "[]")):
        p = os.path.join(BUNDLE, fn)
        if not os.path.exists(p): open(p, "w", encoding="utf-8").write(body)
    sys.path.insert(0, BUNDLE)
    for m in list(sys.modules):
        if m in ("tick_engine", "tick_engine_forward", "manifest_runner", "dev_dataset", "harness", "structure_bos_bot", "owl_package", "compte_controller"):
            del sys.modules[m]
    import tick_engine as E
    import harness, structure_bos_bot, owl_package, compte_controller, dev_dataset
    loaded = {"tick_engine": E.__file__, "harness": harness.__file__, "structure_bos_bot": structure_bos_bot.__file__, "owl_package": owl_package.__file__,
              "compte_controller": compte_controller.__file__, "dev_dataset": dev_dataset.__file__}
    outside = {k: v for k, v in loaded.items() if os.path.dirname(os.path.abspath(v)).lower() != BUNDLE.lower()}
    if outside: raise SystemExit("module loaded OUTSIDE the bundle: %s" % outside)
    loaded_hashes = {k: h(v) for k, v in loaded.items()}
    # 4. scored window and balances: from the manifest when FROZEN; free only for the fixture
    if fixture:
        start, end = int(ARGS[ARGS.index("--dev-fixture") + 1]), int(ARGS[ARGS.index("--dev-fixture") + 2])
        balances = man["package_mapping"]["regimes"]
    else:
        start, end = int(man["scored_start"]), int(man["scored_end"]); balances = man["balances_at_freeze"]
        assert end - start == 42 * 86400, "scored window must be 42 days"
        assert balances, "balances_at_freeze missing"
    tdir, bars_npz = arg("--ticks"), arg("--bars"); out = arg("--out", os.path.join(BUNDLE, "frozen_result.json"))
    import numpy as np
    Rb = np.load(bars_npz)["R"]; Rb = Rb[Rb["time"] < end]; warm = int((Rb["time"] < start).sum())
    TM, BID, ASK, n_bad, END = E.load_ticks(tdir, start * 1000, end * 1000)
    res = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "bundle": BUNDLE, "manifest": man_path, "manifest_status": man.get("status"), "fixture": fixture,
           "loaded_modules": loaded, "loaded_hashes": loaded_hashes, "bundle_extra_files": extra, "scored": [start, end],
           "scored_utc": [time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(start)), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(end))],
           "bars": {"file": bars_npz, "sha256": h(bars_npz), "n": int(len(Rb)), "warmup": warm}, "ticks": {"dir": tdir, "n": int(len(TM)), "invalid": n_bad},
           "balances": balances, "package_snapshot": h(os.path.join(BUNDLE, "compte_frozen_manifest.json")), "rows": {}}
    print("bundle OK (%d files hashed), modules inside bundle, scored %s -> %s, ticks %d, bars %d (warm-up %d)" % (len(want), res["scored_utc"][0], res["scored_utc"][1], len(TM), len(Rb), warm), flush=True)
    regimes = (arg("--regimes") or "infinity,u224016179,bos,reference_uncapped").split(","); drags = [float(x) for x in (arg("--drags") or "0,0.35").split(",")]
    for uid in regimes:
        cfg0, _ = E.effective_cfg(E.PR[uid], balances[uid], 0.0); opps, bars = E.streams(cfg0, Rb)
        for drag in drags:
            row, rep = E.run_regime(uid, drag, TM, BID, ASK, END, opps, bars, start_ms=start * 1000, balance=balances[uid])
            res["rows"]["%s|%.2f" % (uid, drag)] = {"effective": rep, "arms": row}
            for name, a in row.items():
                print("%-18s drag %.2f %-9s | net %8.2f cc_dd %7.2f mtm_dd %7.2f | trades %3d wins %3d" % (uid, drag, name, a["net"], a["cc_dd"], a["mtm_dd"], a["trades"], a["wins"]), flush=True)
            json.dump(res, open(out, "w"), indent=1)
    print("DONE ->", out, flush=True)


if __name__ == "__main__":
    main()
