"""Keeps the "Rentabilite" numbers current (owner 2026-10-11: "auto rerun the backtest each time something new
is introduced in the bot, by the lab or by me").

  python proof_autorun.py --check     every 30 min: if the robot's RULES changed (fingerprint of the bot code, the
                                      packages, the gate, the engine), rerun the $200 backtest of today's rules
                                      (proof_current_rules.py, ~6 min) and stamp it with the new fingerprint
  python proof_autorun.py --nightly   once a night: fetch Valere's newest ticks and bars (read-only), replay his
                                      account with the engine (replay_valere_real.py) and publish the
                                      backtest-vs-real comparison (live/lab/fidelity.json); then --check

What it can and cannot follow, said plainly on the page: package dials (owl_packages.json) flow into the backtest
automatically; a NEW rule written into the bot's code must also be modelled in the engine - until then the page
shows the backtest as built before the latest rule change.
Log: study/proof_autorun.log. Runs sequentially (never two heavy jobs at once - disk/pagefile incident).
"""
import os, sys, json, time, hashlib, subprocess
ROOT = r"C:\Projects\KinoliveLines"; PY = sys.executable
LOG = os.path.join(ROOT, "study", "proof_autorun.log")
CUR = os.path.join(ROOT, "live", "lab", "proof_current.json")
FID = os.path.join(ROOT, "live", "lab", "fidelity.json")
LOCK = os.path.join(ROOT, "study", "proof_autorun.lock")
RULE_FILES = ["live/structure_bos_bot.py", "live/owl_packages.json", "live/owl_package.py", "live/pb_gate.py"]
ENGINE_FILES = ["study/tick_engine.py", "study/tick_engine_matrix.py", "study/tick_engine_pbgate.py", "study/proof_current_rules.py", "live/lab/harness.py"]


def log(m):
    open(LOG, "a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")


def fp(files):
    h = hashlib.sha256()
    for f in files:
        try: h.update(open(os.path.join(ROOT, f), "rb").read())
        except Exception: h.update(f.encode())
    return h.hexdigest()[:16]


def run(args, timeout=5400):
    t0 = time.time(); r = subprocess.run([PY] + args, cwd=os.path.join(ROOT, "study"), capture_output=True, text=True, timeout=timeout)
    log("ran %s rc=%s in %.0fs%s" % (" ".join(args), r.returncode, time.time() - t0, ("" if r.returncode == 0 else " | " + (r.stderr or r.stdout)[-300:].replace("\n", " "))))
    return r.returncode == 0


def check(force=False):
    rules, engine = fp(RULE_FILES), fp(ENGINE_FILES)
    try: cur = json.load(open(CUR, encoding="utf-8"))
    except Exception: cur = {}
    if not force and cur.get("rules_fp") == rules and cur.get("engine_fp") == engine:
        return False
    log("rules %s (was %s), engine %s (was %s) -> rerun the backtest" % (rules, cur.get("rules_fp"), engine, cur.get("engine_fp")))
    if not run(["proof_current_rules.py"], 1800): return False
    cur = json.load(open(CUR, encoding="utf-8"))
    cur.update({"rules_fp": rules, "engine_fp": engine, "rebuilt_at": int(time.time()), "rebuilt_reason": "rules changed" if not force else "nightly"})
    json.dump(cur, open(CUR, "w", encoding="utf-8"), indent=1)
    return True


def fidelity():
    """the backtest of Valere's account (actual rules, his own quotes) against his real broker ledger"""
    r = json.load(open(os.path.join(ROOT, "study", "replay_valere_real.json"), encoding="utf-8"))
    G = r["actual_ledger"]["groups"]; a = r["rows"]["0.00"]["arms"]["actual_rules"]; m = r["rows"]["0.00"]["match_vs_ledger"]["actual_rules"]

    def st(P, bal0):
        n = len(P); W = [p for p in P if p > 0]; gw = sum(W); gl = -sum(p for p in P if p <= 0); c = pk = 0.0; dd = 0.0; eq_pk = bal0; ddp = 0.0
        for p in P:
            c += p; pk = max(pk, c); dd = max(dd, pk - c); eq = bal0 + c; eq_pk = max(eq_pk, eq); ddp = max(ddp, (eq_pk - eq) / eq_pk * 100)
        return {"n": n, "wr": round(100 * len(W) / n, 1) if n else None, "pf": round(gw / gl, 2) if gl else None, "net": round(gw - gl, 2), "dd": round(dd, 2), "dd_pct": round(ddp, 1)}
    # pairs within one second
    used = set(); within1 = 0
    for t in a["trades_list"]:
        best = None; bd = 601
        for i, g in enumerate(G):
            if i in used or g["d"] != t["d"]: continue
            d = abs(g["tc"] - t["tc"] / 1000)
            if d < bd: bd, best = d, i
        if best is not None: used.add(best); within1 += bd <= 1
    out = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "period_utc": [r["period"]["start_utc"], r["period"]["end_utc"]],
           "quotes": "the account's own broker quotes (bid/ask ticks)", "days_covered": r["quotes"]["days_covered"], "days": len(r["quotes"]["coverage"]),
           "real": st([g["pnl"] for g in G], 210.0), "backtest": st([t["pnl"] for t in a["trades_list"]], 210.0),
           "matched": m["paired"], "matched_1s": within1, "real_n": len(G), "backtest_n": len(a["trades_list"]),
           "engine_only": m["engine_only"], "engine_only_pnl": m["engine_only_pnl"], "real_only": m["real_only"], "real_only_pnl": m["real_only_pnl"],
           "paired_pnl_backtest": m["paired_pnl_engine"], "paired_pnl_real": m["paired_pnl_real"],
           "with_filter": st([t["pnl"] for t in r["rows"]["0.00"]["arms"]["actual_rules_filter"]["trades_list"]], 210.0)}
    json.dump(out, open(FID, "w", encoding="utf-8"), indent=1)
    log("fidelity published: real %s vs backtest %s, matched %d/%d (%d within 1 s)" % (out["real"]["net"], out["backtest"]["net"], out["matched"], out["real_n"], within1))


def nightly():
    run(["fetch_ticks.py", "--forward", "--uid", "u224016179"], 3600)
    run(["fetch_bars_uid.py", "--uid", "u224016179", "--from", "2026-09-08T00:00:00"], 600)
    if run(["replay_valere_real.py"], 7200):
        try: fidelity()
        except Exception as e: log("fidelity failed: %r" % (e,))
    check()


if __name__ == "__main__":
    if os.path.exists(LOCK) and time.time() - os.path.getmtime(LOCK) < 4 * 3600:
        sys.exit(0)                     # a run is in progress
    open(LOCK, "w").write(str(os.getpid()))
    try:
        if "--nightly" in sys.argv: nightly()
        elif "--fidelity" in sys.argv: fidelity()
        else: check("--force" in sys.argv)
    finally:
        try: os.remove(LOCK)
        except Exception: pass
