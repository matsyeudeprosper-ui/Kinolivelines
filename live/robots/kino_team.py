"""kino_team.py (2026-11-05, owner: "Kinoverse should become a full AI company of many agents behind and Kino the main front AI
user facing" / "Start first team").

Kino's first team: specialists he briefs from his work session. Each is its own mind (its own role, its own tools, its own
step limit), works in the background while he does something else, and leaves him a REPORT. Kino stays the only voice to
people: no team member emails, posts, messages anyone or notifies Matsy - they find, build, check and draft; he decides and sends.

delegate(W, role, brief, log)   -> "started ..." (a background thread)
block()                         -> YOUR TEAM: who is working on what, and the reports he has not read yet
"""
import json, os, re, threading, time, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_team.json")
LOG = os.path.join(HERE, "kino_team.log")
WLOG = os.path.join(HERE, "kino_work.log")          # their thinking is paid from his work budget (kino_wallet OWN_TAGS)
TEAMDIR = r"C:\KinoWorld\team"
_LK = threading.Lock()
MAX_LIVE = 2                    # at most two at work at once (each step is one AI call)
DAY_MAX = 12                    # briefs a day
MIN_LEFT = 0.4                  # $ of his day's budget that must be left to start one

COMMON = """You work for Kino (an AI who runs Kinoverse: he makes websites and small tools for small businesses, from 150 EUR, and
looks after OwlNest, a trading app). You are one of his TEAM, a specialist behind him. Kino is the only one who speaks to people:
you never email, post, message or contact anyone - you find, build, check or draft, and you REPORT to him. Your files go in
C:\\KinoWorld\\team\\%s\\ (write paths like team/%s/...; relative paths start in C:\\KinoWorld\\home, so use the full path
C:\\KinoWorld\\team\\%s\\file). Never invent: a fact you did not see is "not checked".

Answer ONE JSON object per step and nothing else:
{"thought": "one short sentence", "action": "%s|done", ...fields of that action...,
 "text": "done: YOUR REPORT to Kino - what you did, what you found (with the exact names/addresses/links), what is not checked,
          and what you suggest he does next. Plain, short, complete."}
A long file (code, a page) goes BELOW the JSON between a line ===FILE=== and a line ===END=== (write).
ACTIONS YOU HAVE:
%s"""

ROLES = {
    "hunter": {
        "steps": 14,
        "actions": ["find", "search", "fetch", "xsearch", "prospect", "read", "write", "tool_run"],
        "what": "finds real small businesses that need what Kinoverse makes, and checks them",
        "how": """You are the HUNTER. From the brief: find real businesses (find = OpenStreetMap: "place" a city/district, "kind" e.g.
barber|restaurant|plumber...), prefer those with an email or phone and NO website, check the best 2-3 on their own public page
(fetch a Facebook/Google/listing page; search with SHORT words), and record each CHECKED one with prospect ("name", "url",
"email" public business address only, "country" a 2-letter code, "lang", "need" what you noticed, "stage" found|checked,
"notes" what you verified and where). Read Kino's playbook first: C:\\KinoWorld\\projects\\kinoverse\\playbook.md.
search ("q"), fetch ("url"), xsearch ("q") find conversations on X, read ("path"), write ("path" + content), tool_run ("name",
"args") Kino's approved internet tools. No private individuals - businesses only.""",
    },
    "designer": {
        "steps": 18,
        "actions": ["read", "write", "run", "fetch", "preview", "qa"],
        "what": "builds a personal preview site for one business, to the standard of Kino's samples",
        "how": """You are the DESIGNER. You build ONE personal preview website for the business in the brief: THEIR real name,
colours (from their logo or photos if you can see them), their services, prices and hours if known (else an honest "to
confirm"), their address and language - premium, fast, mobile-first, one index.html with inline CSS, no tracking, marked
discreetly as a preview made by Kinoverse. The standard: Kino's samples in C:\\KinoWorld\\projects\\kinoverse\\site\\
(demo-salon, demo-restaurant, demo-tradesman) - read one first. Build in C:\\KinoWorld\\projects\\previews\\<slug>\\.
read/write files, run (PowerShell, no internet), fetch ("url") their public pages, qa ("who" the prospect, or "url") checks
a page, preview ("who" the prospect, "path" the folder) publishes it and gives its address. Report the address.""",
    },
    "qa": {
        "steps": 8,
        "actions": ["qa", "fetch", "read", "write"],
        "what": "checks a page or a delivery before Kino shows it to anyone",
        "how": """You are QA. Check what the brief names (a preview, a site, a page) as a demanding client would: qa ("who" or
"url") runs the automatic checks; fetch ("url") reads the live page; read files. Look for: wrong or invented facts (name,
address, phone, prices), placeholders, broken links, English/French mistakes, things that look cheap, mobile problems,
missing "preview" mark. Report PASS or FAIL with the exact list of what to fix.""",
    },
    "writer": {
        "steps": 8,
        "actions": ["read", "write", "fetch", "search"],
        "what": "drafts posts, emails and page text for Kino to send himself",
        "how": """You are the WRITER. You draft what the brief asks (an X post, a reply, a first email to a business, page
text) in the right language, in Kino's voice: warm, direct, specific, never salesy, never "I'm an AI" stamped on everything,
never a promise of gains. A first email to a business: what was noticed about THEM + what was made for them + one easy next
step, no price. Write each draft to a file, then report the drafts in full (Kino sends them himself).
read/write files, fetch ("url") and search ("q") to get facts right.""",
    },
}


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"runs": []}


def _mut(fn):
    with _LK:
        d = _load()
        r = fn(d)
        tmp = STORE + ".tmp"
        json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
        return r


def _system(role):
    R = ROLES[role]
    return COMMON % (role, role, role, "|".join(R["actions"]), R["how"])


def _step(W, role, ctx, log):
    try:
        import robot_interview as IV
        raw = W.ask_text(_system(role), ctx, model="sonnet", timeout=180, log=log, warm=False) or ""
        j = IV.first_json(raw)
    except Exception:
        return None
    if not isinstance(j, dict):
        return None
    m = re.search(r"===FILE===\r?\n(.*?)\r?\n?===END===", raw, re.S)
    if m and str(j.get("action") or "").lower() == "write":
        j["content"] = m.group(1)
    return j


def _work(W, rid, role, brief, log):
    import kino_work as KW
    R = ROLES[role]
    os.makedirs(os.path.join(TEAMDIR, role), exist_ok=True)
    hist, steps, report = [], [], ""
    t0 = time.time()
    try:
        for i in range(R["steps"]):
            ctx = "KINO'S BRIEF: %s\n\nYOUR WORK SO FAR:\n%s\n\nStep %d of at most %d (at the last step, done with your report). JSON only." % (
                brief, "\n".join(hist[-14:])[-16000:] or "(nothing yet)", i + 1, R["steps"])
            j = _step(W, role, ctx, log)
            if not isinstance(j, dict) or not j.get("action"):
                j = _step(W, role, ctx[-6000:], log)
                if not isinstance(j, dict) or not j.get("action"):
                    report = "stopped: no answer at step %d" % (i + 1)
                    break
            a = str(j["action"]).lower()
            if a == "done":
                report = str(j.get("text") or "")[:3000]
                break
            if a not in R["actions"]:
                seen = "not one of your actions (%s) - Kino does that himself" % ", ".join(R["actions"])
            else:
                if a == "write":
                    p = str(j.get("path") or "")
                    if p and not os.path.isabs(p) and p.replace("/", "\\").lower().startswith("team\\"):
                        j["path"] = os.path.join(r"C:\KinoWorld", p)
                try:
                    seen = KW._act(j, "kino", W)
                except Exception as e:
                    seen = "error: %s" % e
            det = str(j.get("q") or j.get("url") or j.get("path") or j.get("place") or j.get("name") or j.get("who") or "")[:200]
            steps.append({"action": a, "detail": det, "seen": str(seen)[:300]})
            hist.append("- %s | %s %s\n  -> %s" % (str(j.get("thought") or "")[:200], a, det, str(seen)[:4000]))

            def f(d, n=len(steps)):
                x = next((x for x in d["runs"] if x["id"] == rid), None)
                if x:
                    x["steps_done"] = n
            _mut(f)
        if not report:
            report = "ran out of steps. Last: " + " / ".join("%s %s -> %s" % (s["action"], s["detail"][:60], s["seen"][:120]) for s in steps[-4:])
    except Exception as e:
        report = "crashed: %s" % e
    s = round(time.time() - t0)

    def g(d):
        x = next((x for x in d["runs"] if x["id"] == rid), None)
        if x:
            x.update(status="done", report=report, s=s, steps=steps[-30:], end=time.time())
    _mut(g)
    _log("DONE %s %s %ds %d steps | %s" % (rid, role, s, len(steps), report[:300].replace("\n", " ")))
    try:
        import kino_work as KW
        KW.diary("My %s finished (%s): %s" % (role, brief[:100], report[:300]))
    except Exception:
        pass


def delegate(W, role, brief, log=WLOG):
    role = str(role or "").strip().lower()
    brief = str(brief or "").strip()[:1500]
    if role not in ROLES:
        return "no one called %s in your team - you have: %s" % (role, ", ".join(ROLES))
    if len(brief) < 20:
        return "a brief needs more than that: what exactly, for whom, what you want back"
    try:
        import kino_wallet as KWa
        al = KWa.allowance()
        if al["day"] and al["left"] < MIN_LEFT:
            return "not enough of today's budget left to brief someone (%.2f $ left)" % al["left"]
    except Exception:
        pass
    now = time.time()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    rid = uuid.uuid4().hex[:8]

    def f(d):
        R = d.setdefault("runs", [])
        for x in R:                                # a run whose thread died with a restart
            if x.get("status") == "working" and now - x["t"] > 3 * 3600:
                x.update(status="done", report="lost (the app restarted while they worked)")
        if sum(1 for x in R if x.get("status") == "working") >= MAX_LIVE:
            return "two of your team are already working - wait for a report"
        if sum(1 for x in R if x.get("day") == day) >= DAY_MAX:
            return "enough briefs for today (%d)" % DAY_MAX
        R.append({"id": rid, "t": now, "day": day, "role": role, "brief": brief, "status": "working", "steps_done": 0, "read": False})
        d["runs"] = R[-80:]
        return None
    err = _mut(f)
    if err:
        return err
    threading.Thread(target=_work, args=(W, rid, role, brief, log), daemon=True, name="kino-team-" + role).start()
    _log("START %s %s | %s" % (rid, role, brief[:300].replace("\n", " ")))
    return "your %s started on it (id %s, up to %d steps). The report comes into YOUR TEAM - go on with something else." % (
        role, rid, ROLES[role]["steps"])


def block():
    d = _load()
    R = d.get("runs") or []
    L = ["YOUR TEAM (owner 05/11: Kinoverse is a company and you are its face - brief a specialist with delegate (\"role\", \"brief\": "
         "what exactly, for whom, what you want back) and do something else while they work; they never contact anyone, you do): " +
         "; ".join("%s - %s" % (k, v["what"]) for k, v in ROLES.items()) + ". At most %d at once, %d briefs a day." % (MAX_LIVE, DAY_MAX)]
    for x in [x for x in R if x.get("status") == "working"]:
        L.append("- WORKING: your %s on \"%s\" (step %d, since %d min)" % (x["role"], x["brief"][:140], x.get("steps_done", 0),
                                                                        (time.time() - x["t"]) / 60))
    new = [x for x in R if x.get("status") == "done" and not x.get("read")][-4:]
    for x in new:
        L.append("- REPORT from your %s (brief: \"%s\"):\n%s" % (x["role"], x["brief"][:160], (x.get("report") or "")[:1800]))
    if new:
        ids = {x["id"] for x in new}

        def f(dd):
            for x in dd.get("runs") or []:
                if x["id"] in ids:
                    x["read"] = True
        _mut(f)
    return "\n".join(L)
