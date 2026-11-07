"""kino_lab.py (2026-11-07, owner: "trading is his other source of income - a real project, working on it regularly, permanently,
until he finds a strategy that works, tested and everything; small tests first; positive every month").

His trading lab: every idea is a CARD before any test (what, why it could work, what kills it), then it climbs a funnel he
cannot shortcut (the bench is study/kino_lab/engine.py - the same rules for every idea):
  1 quick   the last 2 research months, 50 random-trade controls          (seconds)
  2 full    all 7 research months (Dec 2025-Jun 2026), 100 random controls: EVERY month positive, 60%+ weeks positive
  3 final   the LOCKED months (Jul 2026 - now), never shown to him; ONE try per frozen file: every month positive,
            75%+ weeks positive, beats 95% of random (Matsy 07/11 agreed: monthly positive is the bar)
  4 paper   4 weeks of live paper trading (after a final pass - Matsy is told)
  5 money   a small real pot from Matsy - only after 4
Every try is in the ledger, so he never re-tests a dead idea and we can see how many he tried (the more tries, the more one
looks good by luck - that is why the locked months exist).
Store robots/kino_lab.json; his readable copy C:\\KinoWorld\\lab\\LEDGER.md.
"""
import hashlib, json, os, re, subprocess, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_lab.json")
ENGINE = os.path.join(os.path.dirname(os.path.dirname(HERE)), "study", "kino_lab", "engine.py")
WORLD = r"C:\KinoWorld"
LAB = os.path.join(WORLD, "lab")
LEDGER_MD = os.path.join(LAB, "LEDGER.md")
_LK = threading.Lock()
NOTIFY = None                          # set by the app: a push to Matsy


def _load():
    try:
        d = json.load(open(STORE, encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("ideas", [])
    d.setdefault("n", 0)
    return d


def _save(d):
    json.dump(d, open(STORE + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(STORE + ".tmp", STORE)
    try:
        _ledger_md(d)
    except Exception:
        pass


def _find(d, ref):
    ref = str(ref or "").strip().lower()
    return next((x for x in d["ideas"] if x["id"].lower() == ref or x["name"].lower() == ref), None)


def idea(name, hypothesis, why, rule, kill):
    """a card before any test"""
    name, hypothesis, why, rule, kill = (str(x or "").strip() for x in (name, hypothesis, why, rule, kill))
    if len(name) < 3 or len(hypothesis) < 15 or len(rule) < 15 or len(kill) < 10:
        return "a card needs a name, the hypothesis, the exact rule and what would kill it"
    with _LK:
        d = _load()
        if _find(d, name):
            return "an idea called %s exists already - give this one its own name" % name
        d["n"] += 1
        x = {"id": "I%d" % d["n"], "name": name[:80], "t": time.time(), "hypothesis": hypothesis[:600], "why": why[:600],
             "rule": rule[:800], "kill": kill[:300], "stage": "card", "tests": []}
        d["ideas"].append(x)
        _save(d)
    return "card %s (%s) written - now write its strategy file in C:\\KinoWorld\\lab\\strategies\\ and run lab_test quick" % (x["id"], name)


def _run(path, stage):
    """the bench in its own low-priority process (the live robots first)"""
    flags = 0x00004000 if os.name == "nt" else 0          # BELOW_NORMAL_PRIORITY_CLASS
    try:
        import sys as _s
        py = _s.executable.replace("pythonw.exe", "python.exe")
        p = subprocess.run([py, "-X", "utf8", ENGINE, path, stage], capture_output=True, text=True, timeout=900,
                           creationflags=flags)
        return json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception as e:
        return {"ok": False, "stage": stage, "why": "the bench failed: %s" % str(e)[:200]}


def _fhash(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def _line(r):
    if not r.get("ok"):
        return "REFUSED - %s" % r.get("why")
    return ("%s: %s | %d trades, net %+.2f $ at 0.01 lot, win %.0f%%, PF %.2f, worst drop %.2f $ | months %s | weeks positive %d/%d | "
            "random trades as good: %d of %d (median %+.2f)" % (
                "PASSED" if r.get("pass") else "FAILED", r.get("gate"), r["trades"], r["net"], r.get("win", 0), r.get("pf", 0),
                r.get("dd", 0), " ".join("%s %+.1f" % (k[2:], v) for k, v in (r.get("months") or {}).items()),
                r.get("weeks_pos", 0), r.get("weeks", 0), r.get("random_as_good", 0), r.get("random_draws", 0), r.get("random_median") or 0))


def test(ref, path, stage="quick"):
    """quick or full, on the research months -> the verdict, written in the ledger"""
    stage = "full" if str(stage).lower().startswith("f") else "quick"
    with _LK:
        x = _find(_load(), ref)
    if not x:
        return "no idea called %s - write its card first (lab_idea)" % ref
    if not path or not os.path.exists(path):
        return "the strategy file is missing (it must be in C:\\KinoWorld\\lab\\strategies\\)"
    if stage == "full" and not any(t["stage"] == "quick" and t.get("pass") for t in x["tests"]):
        return "NOT RUN - the full test comes after a PASSED quick test (small first, Matsy's rule)"
    r = _run(path, stage)
    with _LK:
        d = _load()
        x = _find(d, ref)
        x["tests"].append({"t": time.time(), "stage": stage, "file": os.path.basename(path), "hash": _fhash(path),
                           "ok": r.get("ok"), "pass": bool(r.get("pass")), "net": r.get("net"), "trades": r.get("trades"),
                           "months": r.get("months"), "random_as_good": r.get("random_as_good"), "why": r.get("why")})
        if r.get("pass"):
            x["stage"] = {"quick": "quick passed", "full": "full passed"}[stage]
        elif x["stage"] in ("card",):
            x["stage"] = "tested"
        _save(d)
    return _line(r)


def final(ref, path):
    """the locked months, once per frozen file - the exam he cannot study for"""
    with _LK:
        x = _find(_load(), ref)
    if not x:
        return "no idea called %s" % ref
    if not any(t["stage"] == "full" and t.get("pass") for t in x["tests"]):
        return "NOT RUN - the final exam comes after a PASSED full test"
    h = _fhash(path)
    if any(t["stage"] == "final" for t in x["tests"]):
        return "NOT RUN - this idea already took its final exam; a changed version is a NEW idea (a new card), so luck is counted"
    r = _run(path, "final")
    with _LK:
        d = _load()
        x = _find(d, ref)
        x["tests"].append({"t": time.time(), "stage": "final", "file": os.path.basename(path), "hash": h, "ok": r.get("ok"),
                           "pass": bool(r.get("pass")), "net": r.get("net"), "trades": r.get("trades"), "months": r.get("months"),
                           "random_as_good": r.get("random_as_good"), "why": r.get("why")})
        x["stage"] = "FINAL PASSED - paper trading next" if r.get("pass") else "final failed"
        _save(d)
    if r.get("pass") and NOTIFY:
        try:
            NOTIFY("Kino's lab: idea %s (%s) passed its final exam on the locked months - 4 weeks of paper trading next" % (x["id"], x["name"]))
        except Exception:
            pass
    return _line(r)


def kill(ref, why):
    with _LK:
        d = _load()
        x = _find(d, ref)
        if not x:
            return "no idea called %s" % ref
        x["stage"] = "dead"
        x["dead_why"] = str(why or "")[:300]
        _save(d)
    return "%s is dead - noted, you will not test it again" % x["name"]


def board(n=12):
    d = _load()
    X = d["ideas"][-n:]
    if not X:
        return "your lab is empty - read C:\\KinoWorld\\lab\\README.md and C:\\KinoWorld\\lab\\CLOSED_IDEAS.md, then write your first card"
    L = ["%s %s [%s]%s" % (x["id"], x["name"], x["stage"], (" last: " + ("pass" if x["tests"][-1].get("pass") else "fail") +
                                                           " %s %+.1f$" % (x["tests"][-1]["stage"], x["tests"][-1].get("net") or 0))
                          if x["tests"] else "") for x in X]
    return "YOUR LAB (%d ideas so far, %d tests):\n" % (len(d["ideas"]), sum(len(x["tests"]) for x in d["ideas"])) + "\n".join(L)


def block():
    """for his mind: where the lab stands"""
    return board(8)


def _ledger_md(d):
    L = ["# My trading lab - every idea, every test (written by the app)", ""]
    for x in d["ideas"]:
        L.append("## %s %s - %s" % (x["id"], x["name"], x["stage"]))
        L.append("- hypothesis: %s" % x["hypothesis"])
        L.append("- rule: %s" % x["rule"])
        L.append("- kill: %s" % x["kill"])
        for t in x["tests"]:
            L.append("- %s %s: %s, net %s $, %s trades, months %s, random as good %s %s" % (
                time.strftime("%d/%m %H:%M", time.gmtime(t["t"])), t["stage"], "PASS" if t.get("pass") else "fail", t.get("net"),
                t.get("trades"), t.get("months"), t.get("random_as_good"), ("(" + t["why"] + ")") if t.get("why") else ""))
        if x.get("dead_why"):
            L.append("- dead: %s" % x["dead_why"])
        L.append("")
    os.makedirs(LAB, exist_ok=True)
    open(LEDGER_MD, "w", encoding="utf-8").write("\n".join(L))


def week_line(now=None):
    now = now or time.time()
    d = _load()
    T = [t for x in d["ideas"] for t in x["tests"] if now - t["t"] < 7 * 86400]
    best = max(d["ideas"], key=lambda x: ["card", "tested", "dead", "quick passed", "full passed", "final failed",
                                          "FINAL PASSED - paper trading next"].index(x["stage"]) if x["stage"] in (
        "card", "tested", "dead", "quick passed", "full passed", "final failed", "FINAL PASSED - paper trading next") else 0,
               default=None)
    return "ideas tried in all: %d, tests this week: %d (quick passed %d, full passed %d, final %d), furthest: %s" % (
        len(d["ideas"]), len(T), sum(1 for t in T if t["stage"] == "quick" and t.get("pass")),
        sum(1 for t in T if t["stage"] == "full" and t.get("pass")), sum(1 for t in T if t["stage"] == "final"),
        ("%s %s [%s]" % (best["id"], best["name"], best["stage"])) if best else "none yet")
