"""Frozen reference snapshot (ChatGPT review 3): exact hashes of the runner,
engine, gates and the control account's package values, written to
live/lab/reference_snapshot_<uid>.json. Research config only - the owner's
production settings are not touched. Run again to verify: it reports DRIFT
when any hash or value differs from the stored snapshot."""
import hashlib, json, os, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.join(HERE, "..", "live")
sys.path.insert(0, LIVE)
import owl_package as P   # noqa: E402

UID = sys.argv[1] if len(sys.argv) > 1 else "infinity"
FILES = ["structure_bos_bot.py", "owl_chart_feed.py", "owl_package.py", "bos_paper_variant.py",
         "bos_reference_ledger.py", "reference_ledger_lib.py", "lab/compte_controller.py"]


def sha(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
    except FileNotFoundError:
        return None


def main():
    git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=LIVE, capture_output=True, text=True).stdout.strip()
    u = next(x for x in json.load(open(os.path.join(LIVE, "owl_nest_users.json"), encoding="utf-8")) if x.get("id") == UID)
    pkg = P.for_account(UID)
    # research config = the control's STRATEGY dials with the money-dependent
    # restrictions removed (debt gate, caps, kill line, recovery, scaling)
    research = {"rr": pkg["rr"], "k_streak": pkg["k_streak"], "nervosity": pkg.get("nervosity", True),
                "movement": pkg.get("movement", True), "internal_entries": pkg.get("internal_entries", False),
                "touch_entries": False, "lot": 0.02, "n_cont": "unlimited", "bullets": 0, "jar": False,
                "day_cap": None, "kill_net": None, "scale_with_balance": False, "debt_gate": False}
    snap = {"uid": UID, "login": u.get("login"), "server": u.get("mt5_server"), "symbol": u.get("symbol"),
            "terminal": u.get("terminal"), "git": git, "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "hashes": {f: sha(os.path.join(LIVE, f)) for f in FILES},
            "package": {"name": pkg["package"], "values": {k: pkg[k] for k in sorted(pkg) if k != "package"}},
            "research_config": research}
    out = os.path.join(LIVE, "lab", f"reference_snapshot_{UID}.json")
    if os.path.exists(out):
        old = json.load(open(out, encoding="utf-8"))
        drift = [k for k in ("hashes", "package", "research_config", "login", "server", "symbol")
                 if old.get(k) != snap[k]]
        print(("DRIFT in " + ", ".join(drift)) if drift else "NO DRIFT vs snapshot of " + old["frozen_at"])
        if "--refreeze" not in sys.argv:
            return
    json.dump(snap, open(out, "w", encoding="utf-8"), indent=1)
    print("frozen", out, "git", git, "package", pkg["package"])


if __name__ == "__main__":
    main()
