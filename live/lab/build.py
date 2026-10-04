"""Le constructeur's runner (owner 2026-10-02, phase 2 of the plan).

Takes ONE open request from lab/requests.json, lets a build session work
on it (lab/CONSTRUCTEUR.md), then runs the gates. Every gate passes -> the
build is committed, pushed, and the lab's own robot restarts on the new
code (real accounts pick it up at their next restart; a new dial changes
nothing until an idea wins its duel). Any gate fails -> every file the
session touched is put back exactly as it was, the attempt is logged on
the request, and after three failures the request is marked failed.

The agent writes code; this file decides. The gates are dumb on purpose.

    python lab/build.py            # build the oldest open requests, up to two a night
    python lab/build.py --dry      # say which request would be built
    python lab/build.py --id X     # build that request
"""
import io
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
ROOT = os.path.dirname(LIVE)
REQ = os.path.join(LAB, "requests.json")
CTX = os.path.join(LAB, "build_context.json")
LOG = os.path.join(LAB, "constructeur.log")
MISSION = os.path.join(LAB, "CONSTRUCTEUR.md")
MAX_ATTEMPTS = 3
# 2026-10-03 (owner): a request was waiting two nights behind an older
# one. Up to two builds a night, oldest first, inside a time budget; a
# failed or declined build ends the night (the next would meet the same
# closed gate, and the researcher's note is due).
MAX_PER_NIGHT = 2
BUDGET_S = 45 * 60
TURNS = 80
ALLOW = {"live/lab/harness.py", "live/lab/scrutiny.py", "live/lab/CHERCHEUR.md", "live/lab/requests.json",
         "live/owl_app_server.py", "live/structure_bos_bot.py", "live/owl_package.py", "live/owl_packages.json",
         "live/lab/twin_judge.py", "review/bot_harness_parity.py"}
NEW_OK = ("live/lab/",)
BOT_FILES = {"live/structure_bos_bot.py", "live/owl_package.py", "live/owl_packages.json"}
A = sys.argv[1:]
DRY = "--dry" in A
ONLY = A[A.index("--id") + 1] if "--id" in A and A.index("--id") + 1 < len(A) else None


def say(m):
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {m}"
    print(line, flush=True)
    try:
        io.open(LOG, "a", encoding="utf-8").write(line + "\n")
    except Exception:
        pass


def _lj(p, d):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return d


def _sj(p, obj):
    tmp = p + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, p)


def sh(cmd, timeout=900, cwd=ROOT):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return -1, str(e)


def git_changed():
    """tracked files changed, untracked files present (repo-relative, /)"""
    rc, out = sh(["git", "status", "--porcelain", "--untracked-files=all"], 120)
    mod, new = set(), set()
    for ln in out.splitlines():
        if len(ln) < 4:
            continue
        st, path = ln[:2], ln[3:].strip().replace("\\", "/")
        if st == "??":
            new.add(path)
        else:
            mod.add(path)
    return mod, new


def pick(reqs, skip=()):
    cands = [r for r in reqs if r.get("status", "open") == "open" and int(r.get("build_attempts") or 0) < MAX_ATTEMPTS
             and (ONLY is None or r.get("id") == ONLY) and r.get("id") not in skip]
    cands.sort(key=lambda r: r.get("date", ""))
    return cands[0] if cands else None


def gates(req, mod, new):
    """Each gate: (name, ok, detail). The first failure stops the list."""
    out = []
    touched = mod | new
    bad = [p for p in mod if p not in ALLOW] + [p for p in new if not p.startswith(NEW_OK)]
    out.append(("périmètre", not bad, ", ".join(bad) or "every touched file is allowed"))
    if bad:
        return out
    rc, o = sh(["python", "review/preflight.py"], 300)
    out.append(("preflight", rc == 0, o.strip().splitlines()[-1] if o.strip() else ""))
    if rc != 0:
        return out
    for p in sorted(touched):
        if p.endswith(".py"):
            rc, o = sh(["python", "-m", "py_compile", p], 120)
            out.append(("compile " + p, rc == 0, o.strip()[-200:]))
            if rc != 0:
                return out
    if touched & (BOT_FILES | {"live/lab/harness.py", "review/bot_harness_parity.py", "live/lab/twin_judge.py"}):
        rc, o = sh(["python", "review/bot_harness_parity.py"], 900)
        out.append(("parité test/robot", rc == 0, o.strip().splitlines()[-1] if o.strip() else ""))
        if rc != 0:
            return out
    if "live/lab/harness.py" in touched:
        rc, o = sh(["python", "lab/harness.py", "--json"], 600, cwd=LIVE)
        ok = rc == 0
        try:
            json.loads(o[o.index("{"):]) if ok else None
        except Exception:
            ok = False
        out.append(("le moteur tourne", ok, o.strip()[-200:] if not ok else "ok"))
        if not ok:
            return out
    # the agent must have finished the request, and proven the thing is alive
    fresh = next((r for r in _lj(REQ, {"requests": []}).get("requests", []) if r.get("id") == req.get("id")), {})
    st = fresh.get("status")
    if st == "declined":
        out.append(("déclinée", bool(fresh.get("decline_fr")), fresh.get("decline_fr", "")[:160]))
        return out
    out.append(("la demande est marquée construite", st == "built" and bool(fresh.get("key")), f"status={st} key={fresh.get('key')}"))
    if st != "built":
        return out
    t = fresh.get("test") or {}
    if t.get("flag"):
        nets = []
        for v in (t.get("a"), t.get("b")):
            rc, o = sh(["python", "lab/harness.py", "--json", t["flag"], str(v)], 600, cwd=LIVE)
            try:
                d = json.loads(o[o.index("{"):])
                v = d.get("variant") or d.get("full") or d
                v = v.get("full") if isinstance(v, dict) and isinstance(v.get("full"), dict) else v
                nets.append(v.get("net") if isinstance(v, dict) else None)
            except Exception:
                nets.append(None)
        alive = (None not in nets) and nets[0] != nets[1]
        out.append(("le réglage n’est pas du code mort", alive, f"net a={nets[0]} b={nets[1]}"))
    elif t.get("cmd"):
        rc, o = sh(t["cmd"].split(), 600, cwd=LIVE)
        out.append(("l’outil répond", rc == 0 and bool(o.strip()), o.strip()[-200:]))
    else:
        out.append(("une preuve de vie est fournie", False, "no test block on the request"))
    return out


def revert(mod, new, before_new):
    if mod:
        sh(["git", "checkout", "--"] + sorted(mod), 120)
    for p in sorted(new - before_new):
        try:
            os.remove(os.path.join(ROOT, p))
        except Exception:
            pass


def emit(kind, fr, en, members=True):
    try:
        sys.path.insert(0, LAB)
        import twin_judge as TJ
        TJ.emit(kind, fr, en, members=members)
    except Exception as e:
        say(f"emit failed: {e}")


def main():
    t0 = time.time()
    done, skip = 0, set()
    while done < MAX_PER_NIGHT and time.time() - t0 < BUDGET_S:
        rc = build_one(skip)
        if rc is None:
            break
        if rc != 0:
            return rc
        done = sum(1 for r in _lj(REQ, {"requests": []}).get("requests", []) if r.get("id") in skip and r.get("status") == "built")
        if DRY or ONLY:
            break
    return 0


def build_one(skip):
    """One request, oldest first. None = nothing left to build."""
    doc = _lj(REQ, {"requests": []})
    req = pick(doc.get("requests", []), skip)
    if not req:
        say("nothing to build" + (" [dry]" if DRY else ""))
        return None
    skip.add(req.get("id"))
    rid = req.get("id")
    attempt = int(req.get("build_attempts") or 0) + 1
    say(f"request {rid} attempt {attempt}" + (" [dry]" if DRY else ""))
    if DRY:
        return 0
    mod0, new0 = git_changed()
    dirty = [p for p in mod0 if p in ALLOW and p != "live/lab/requests.json"]   # the runner's own state may be unsaved
    if dirty:
        say(f"build files already modified, not building: {dirty}")
        return 1
    _sj(CTX, {"request": req, "attempt": attempt, "previous_failure": req.get("build_error"),
              "allowed_files": sorted(ALLOW), "now": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    claude = os.path.join(os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.exe")
    mission = io.open(MISSION, encoding="utf-8").read() + f"\n\nBuild request `{rid}` (attempt {attempt}). Read lab/build_context.json first. Begin."
    # 2026-10-04 (owner): the model falls back by itself when the usual one is out (claude_run)
    sys.path.insert(0, LAB)
    from claude_run import run as _crun
    rc, out, _model = _crun(mission, turns=TURNS, cwd=LIVE, timeout=3000, who="le constructeur")
    if _model:
        say(f"model fallback: {_model}")
    io.open(os.path.join(LAB, f"build_{rid}_{attempt}.log"), "w", encoding="utf-8").write(out)
    say(f"session rc={rc} out={len(out)}")
    mod, new = git_changed()
    mod = {p for p in mod if p not in mod0}            # only what the session changed
    new = {p for p in new if p not in new0 and not (p.endswith(".log") or p.endswith("_context.json") or "/build_" in p)}   # the runner's own scratch is never part of a build
    results = gates(req, mod, new)
    for name, ok, detail in results:
        say(("  ok   " if ok else "  FAIL ") + name + (" - " + detail if detail else ""))
    failed = [r for r in results if not r[1]]
    fresh_doc = _lj(REQ, {"requests": []})
    fresh = next((r for r in fresh_doc.get("requests", []) if r.get("id") == rid), None)
    declined = bool(fresh) and fresh.get("status") == "declined" and not failed
    if failed:
        why = failed[0][0] + (" : " + failed[0][2] if failed[0][2] else "")
        revert(mod, new, new0)
        doc = _lj(REQ, {"requests": []})
        for r in doc.get("requests", []):
            if r.get("id") == rid:
                r["build_attempts"] = attempt
                r["build_error"] = why[:300]
                if attempt >= MAX_ATTEMPTS:
                    r["status"] = "failed"
        _sj(REQ, doc)
        sh(["git", "add", "live/lab/requests.json"], 60)
        sh(["git", "commit", "-q", "-m", f"constructeur: {rid} attempt {attempt} failed - {why[:60]}" + chr(10) + chr(10) + "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"], 60)
        sh(["git", "push", "-q"], 180)
        say(f"reverted; {why}")
        if attempt >= MAX_ATTEMPTS:
            emit("build_failed", ("\U0001f6e0 Le labo : le constructeur n’y arrive pas",
                                  f"« {req.get('title_fr') or rid} » : trois essais, toujours une porte fermée ({why[:120]}). Il faut une main humaine."),
                 ("\U0001f6e0 The lab: the builder cannot do it",
                  f"“{req.get('title_en') or rid}”: three attempts, still a closed gate ({why[:120]}). A human hand is needed."), members=False)
        return 1
    if declined:
        revert(mod - {"live/lab/requests.json"}, new, new0)
        sh(["git", "add", "live/lab/requests.json"], 60)
        sh(["git", "commit", "-q", "-m", f"constructeur: {rid} declined\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"], 60)
        sh(["git", "push", "-q"], 180)
        say("declined: " + (fresh.get("decline_fr") or "")[:160])
        emit("build_declined", ("\U0001f6e0 Le labo : le constructeur dit non",
                                f"« {req.get('title_fr') or rid} » : {(fresh.get('decline_fr') or '')[:170]}"),
             ("\U0001f6e0 The lab: the builder says no",
              f"“{req.get('title_en') or rid}”: {(fresh.get('decline_en') or '')[:170]}"), members=False)
        return 0
    # every gate passed: keep it
    if "live/owl_app_server.py" in mod:
        rc, o = sh(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "restart.ps1"), "-What", "app"], 300)
        say("app restarted" if rc == 0 else "app restart: " + o.strip()[-160:])
        rc2, o2 = sh(["node", "review/ui_smoke.mjs", os.path.join(os.environ.get("TEMP", "."), "smk_build")], 900)
        if rc2 != 0:
            revert(mod, new, new0)
            sh(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(ROOT, "restart.ps1"), "-What", "app"], 300)
            doc = _lj(REQ, {"requests": []})
            for r in doc.get("requests", []):
                if r.get("id") == rid:
                    r["build_attempts"] = attempt
                    r["build_error"] = "ui_smoke: " + o2.strip()[-200:]
            _sj(REQ, doc)
            say("ui_smoke failed; reverted and restarted on the old code")
            return 1
    files = sorted(mod | new)
    sh(["git", "add"] + files, 120)
    sh(["git", "commit", "-q", "-m", f"constructeur: {rid} - {req.get('title_en') or ''}\n\nBuilt by the lab's builder on request of the chercheur; every gate passed.\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"], 120)
    rc, o = sh(["git", "rev-parse", "--short", "HEAD"], 60)
    commit = o.strip()
    sh(["git", "push", "-q"], 180)
    doc = _lj(REQ, {"requests": []})
    for r in doc.get("requests", []):
        if r.get("id") == rid:
            r["built_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            r["built_commit"] = commit
            r.pop("build_error", None)
    _sj(REQ, doc)
    sh(["git", "add", "live/lab/requests.json"], 60)
    sh(["git", "commit", "-q", "-m", f"constructeur: {rid} built ({commit})\n\nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"], 60)
    sh(["git", "push", "-q"], 180)
    if mod & BOT_FILES:
        try:
            sys.path.insert(0, LAB)
            import twin_judge as TJ
            TJ._restart_labo()
            say("lab robot restarted on the new code")
        except Exception as e:
            say(f"labo restart failed: {e}")
    note_fr = (fresh or {}).get("built_note_fr") or f"Le chercheur peut maintenant tester « {req.get('title_fr') or rid} ». Rien ne change dans le robot tant qu’une idée n’a pas gagné son duel."
    note_en = (fresh or {}).get("built_note_en") or f"The chercheur can now test “{req.get('title_en') or rid}”. Nothing changes in the robot until an idea wins its duel."
    emit("build_done", ("\U0001f528 Le labo : le constructeur a livré", note_fr[:200]),
         ("\U0001f528 The lab: the builder delivered", note_en[:200]), members=True)
    say(f"built {rid} -> {commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
