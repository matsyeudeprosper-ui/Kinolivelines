"""Le critique's runner (owner 2026-10-02, phase 3 of the plan).

Every night after the researcher, each idea that scored "better on both
halves" and has no fresh critique gets one: a short review session
(lab/CRITIQUE.md) that tries to break it, and writes passe / doute /
bloque to lab/critiques.json. lab_researcher.py reads that before it
starts a twin: bloque = no twin, doute = twin with the doubt on its card.

    python lab/critic.py            # review tonight's candidates (3 at most)
    python lab/critic.py --dry      # list them, review nothing
    python lab/critic.py --id X     # review that idea now
"""
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

LAB = os.path.dirname(os.path.abspath(__file__))
LIVE = os.path.dirname(LAB)
CRIT = os.path.join(LAB, "critiques.json")
CTX = os.path.join(LAB, "critic_context.json")
LOG = os.path.join(LAB, "critique.log")
MISSION = os.path.join(LAB, "CRITIQUE.md")
FRESH_DAYS = 7
MAX_PER_NIGHT = 3
TURNS = 40
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


def _list(doc):
    """the file as a list, whether it was written as a list or as {"critiques": [...]}"""
    return doc if isinstance(doc, list) else (doc or {}).get("critiques", [])


def latest(critiques, vid):
    mine = sorted((c for c in critiques if c.get("id") == vid), key=lambda c: c.get("date", ""))
    return mine[-1] if mine else None


def candidates(auto, critiques, today):
    out = []
    for v in auto.get("variants") or []:
        vid = v.get("id")
        if not vid or v.get("verdict") != "A":
            continue
        if ONLY and vid != ONLY:
            continue
        c = latest(critiques, vid)
        if c and not ONLY:
            try:
                age = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(c.get("date", today), "%Y-%m-%d")).days
            except Exception:
                age = 0
            if age < FRESH_DAYS:
                continue
        out.append(v)
    out.sort(key=lambda v: -abs(float(v.get("diff_net") or 0)))
    return out[:MAX_PER_NIGHT] if not ONLY else out[:1]


def context(v, auto):
    vid = v.get("id")
    hist = []
    try:
        for ln in io.open(os.path.join(LAB, "auto_history.jsonl"), encoding="utf-8"):
            try:
                r = json.loads(ln)
                if r.get("id") == vid:
                    hist.append(r)
            except Exception:
                pass
    except Exception:
        pass
    props = [p for p in _lj(os.path.join(LAB, "proposals.json"), {"proposals": []}).get("proposals", []) if p.get("id") == vid]
    reg = _lj(os.path.join(LAB, "registry.json"), [])
    items = reg if isinstance(reg, list) else reg.get("items", reg.get("registry", []))
    same_family = [{"id": it.get("id"), "title_fr": it.get("title_fr"), "status": it.get("status"), "verdict": it.get("verdict"), "nums_fr": it.get("nums_fr")}
                   for it in items if it.get("family") == v.get("family")]
    arch = _lj(os.path.join(LAB, "archive.json"), {})
    twins = [t for t in _lj(os.path.join(LAB, "twins.json"), {"twins": []}).get("twins", []) if t.get("id") == vid]
    return {"now": datetime.now(timezone.utc).isoformat(timespec="seconds"), "idea": v,
            "base": auto.get("base"), "engine": auto.get("engine"), "days": auto.get("days"),
            "history": hist[-12:], "proposal": props[-1] if props else None,
            "registry_same_family": same_family, "archived": vid in (arch if isinstance(arch, dict) else {}),
            "twins": twins, "dial_flags": "python lab/harness.py --help"}


def review(v, auto):
    vid = v.get("id")
    _sj(CTX, context(v, auto))
    claude = os.path.join(os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.exe")
    mission = io.open(MISSION, encoding="utf-8").read() + f"\n\nCritique `{vid}`. Read lab/critic_context.json first. Begin."
    try:
        r = subprocess.run([claude, "-p", mission, "--output-format", "text", "--max-turns", str(TURNS),
                            "--allowedTools", "Bash(python *)", "Read", "Write", "Edit", "Glob", "Grep"],
                           cwd=LIVE, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500)
        io.open(os.path.join(LAB, f"critique_{vid}.log"), "w", encoding="utf-8").write((r.stdout or "") + (r.stderr or ""))
    except Exception as e:
        say(f"{vid}: session failed: {e}")


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    auto = _lj(os.path.join(LAB, "auto.json"), {})
    doc = _lj(CRIT, {"critiques": []})
    cands = candidates(auto, _list(doc), today)
    say("to review: " + (", ".join(v.get("id") for v in cands) or "nothing") + (" [dry]" if DRY else ""))
    if DRY:
        return 0
    for v in cands:
        vid = v.get("id")
        review(v, auto)
        doc = _lj(CRIT, {"critiques": []})
        c = latest(_list(doc), vid)
        ok = c and c.get("date") == today and c.get("verdict") in ("passe", "doute", "bloque") and (c.get("fr") or c.get("en"))
        if not ok:
            # a review that left no readable verdict must not block the lab,
            # and must not pass unseen either
            if isinstance(doc, list):
                doc = {"critiques": doc}
            doc.setdefault("critiques", []).append({"id": vid, "date": today, "verdict": "doute",
                                                    "fr": "Le critique n’a pas rendu d’avis lisible cette nuit ; l’idée avance avec ce doute.",
                                                    "en": "The critic left no readable verdict tonight; the idea moves on with that doubt.",
                                                    "checks": ["no verdict written"]})
            _sj(CRIT, doc)
            c = doc["critiques"][-1]
        say(f"{vid}: {c.get('verdict')} - {(c.get('fr') or '')[:100]}")
        if c.get("verdict") == "bloque":
            try:
                sys.path.insert(0, LAB)
                import twin_judge as TJ
                TJ.emit("critic_blocked", ("\U0001f6d1 Le labo : le critique dit non",
                                           f"« {v.get('title_fr') or vid} » : {(c.get('fr') or '')[:170]}"),
                        ("\U0001f6d1 The lab: the critic says no",
                         f"“{v.get('title_en') or vid}”: {(c.get('en') or c.get('fr') or '')[:170]}"), members=True)
            except Exception as e:
                say(f"emit failed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
