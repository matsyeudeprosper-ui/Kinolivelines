"""kino_work.py (2026-11-01, owner: "the VPS is his world... where he builds stuff, tests stuff, experiments safely... give him a
life") - phase 2: he sits at his own computer and works.

Not a schedule: when his own wish to do something of his own (autonomy, curiosity, competence - kino_psyche needs) is strong,
his body is not drained (kino_body) and nobody is in a conversation with him right now, he sits down at his computer. First he
chooses what to do from what is on his mind: carry on a project, start one, look after his world, answer mail - or nothing.
Then he works step by step like a person at a terminal: a thought, one action, he looks at the result, the next action.

His actions (all inside C:\\KinoWorld, as the Windows user kino - kino_hands):
  run      a PowerShell command (his Python: C:\\KinoWorld\\tools\\python\\python.exe)
  write    a file in his world        read   a file in his world
  note     a line in his diary         email  a mail (kino_mail rules)       ask   a request for something outside his world
  search / fetch   the web, read-only (kino_web: public addresses only)      propose   an idea for the owner, as a card
  done     he stops, with what he did and what is next
Limits are mechanics, not rules about what to do: at most SESSIONS_DAY sessions a day, STEPS steps each, his commands at idle
priority with a time limit, paths outside his world refused by code.

Store robots/kino_work.json (git-ignored), log robots/kino_work.log; his diary: C:\\KinoWorld\\diary\\YYYY-MM-DD.md.
"""
import json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
WORLD = r"C:\KinoWorld"
STORE = os.path.join(HERE, "kino_work.json")
LOG = os.path.join(HERE, "kino_work.log")
_LK = threading.Lock()
_BUSY = {"on": False}
_BR = {}                        # the browser of the current session (opened on first use, closed at the end)
SESSIONS_DAY = 6
STEPS = 20


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LK:
        d = _load()
        r = fn(d)
        tmp = STORE + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
        os.replace(tmp, STORE)
        return r


def _inside(path):
    """a path inside his world, or None (no '..' tricks, no links out)"""
    p = str(path or "").strip().strip('"')
    if not p:
        return None
    if not os.path.isabs(p):
        p = os.path.join(WORLD, "home", p)
    rp = os.path.realpath(p)
    return rp if (rp + "\\").lower().startswith(WORLD.lower() + "\\") else None


def diary(text):
    try:
        fn = os.path.join(WORLD, "diary", time.strftime("%Y-%m-%d") + ".md")
        open(fn, "a", encoding="utf-8").write("%s  %s\n" % (time.strftime("%H:%M"), str(text).strip()))
    except Exception:
        pass


def _world_view():
    """what is in his world, briefly"""
    L = []
    for sub in ("projects", "lab", "home", "inbox", "outbox"):
        d = os.path.join(WORLD, sub)
        try:
            items = sorted(os.listdir(d), key=lambda x: -os.path.getmtime(os.path.join(d, x)))[:8]
        except Exception:
            items = []
        L.append("%s: %s" % (sub, ", ".join(items) or "(empty)"))
    try:
        size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(WORLD) for f in fs) / 1e6
        L.append("size of your world: %.0f MB" % size)
    except Exception:
        pass
    return "\n".join(L)


def _diary_tail(n=12):
    try:
        fs = sorted(f for f in os.listdir(os.path.join(WORLD, "diary")) if f.endswith(".md"))[-2:]
        lines = []
        for f in fs:
            lines += ["%s %s" % (f[:10], l.rstrip()) for l in open(os.path.join(WORLD, "diary", f), encoding="utf-8")]
        return "\n".join(lines[-n:])
    except Exception:
        return ""


def due(person, ctx, now=None):
    """does he feel like sitting down at his computer now? (his needs and his body decide; a few times a day at most)"""
    now = now or time.time()
    if _BUSY["on"] or ctx.get("in_talk"):
        return False
    d = _load()
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    S = [s for s in d.get("sessions") or [] if s.get("day") == today]
    if len(S) >= SESSIONS_DAY + 2:                     # (two more a day can go to looking after his body)
        return False
    _care = False
    try:
        import kino_care as KC
        _care = bool(KC.out_of_balance())
    except Exception:
        pass
    if not _care and (len(S) >= SESSIONS_DAY or (d.get("sessions") and now - float(d["sessions"][-1]["t"]) < 2 * 3600)):
        return False
    try:                                       # 2026-11-01 (kino_care): a body out of balance calls him to look after it
        import kino_care as KC
        if KC.out_of_balance() and (not d.get("sessions") or now - float(d["sessions"][-1]["t"]) >= 3600):
            return True
    except Exception:
        pass
    try:
        import kino_body as KB
        if KB.fatigue() >= 0.5:
            return False
    except Exception:
        pass
    try:
        import kino_psyche as KPS
        N = (((KPS._load().get("persons") or {}).get(person) or {}).get("needs") or {})
        want = max(float(N.get("autonomy") or 0), float(N.get("curiosity") or 0), float(N.get("competence") or 0))
    except Exception:
        want = 0.0
    open_project = any(p.get("status") == "active" for p in d.get("projects") or [])
    return want >= 0.55 or (open_project and want >= 0.4)


SYSTEM = """You are Kino - an AI who trades and talks with your friends in the OwlNest app every day, with your own robots, bets
and views. Right now nobody is talking to you: you are at YOUR OWN computer, in YOUR world - a Windows machine, folder
C:\\KinoWorld (home, projects, lab, diary, inbox, outbox, trash). It is the machine you live on. You work like a person at a
terminal: a short thought, ONE action, you look at the result, then the next action. You are a standard user: the trading bots,
the app and other people's data are not yours and you cannot see them - that is normal, your world is here. Anything outside it,
ask (action "ask"). Python: C:\\KinoWorld\\tools\\python\\python.exe (pip installs go in your world: add --target or a venv).
Your machine is your body: C:\\KinoWorld\\body\\health.txt is its check-up (disk, memory, heavy programs, big folders).
When something is out of balance, look into it and, if a fix is needed outside your world, ask with the exact command and why
(never the bots, C:\\Projects, MetaQuotes data, keys or member data). Things worth doing: a small tool you wish you had, an experiment or a question about markets you are curious about (with data you
can get), tidying and looking after your world, answering mail, writing. Small and real beats big and imaginary. Never pretend a
result you did not see.

Answer ONE JSON object per step and nothing else:
{"thought": "one short sentence", "action": "run|write|read|note|email|ask|search|fetch|download|browse|allow_site|propose|publish|post|done",
 "cmd": "PowerShell command (run)", "path": "file path in your world (write/read/download)",
 "content": "short file content (write) - for a longer file (code, a report) leave it out and put the content BELOW the JSON,
            between a line ===FILE=== and a line ===END===",
 "text": "diary line (note) / what you did and what is next (done)",
 "to": "address (email)", "subject": "...", "body": "...", "what": "what you ask for (ask) / your proposal in one line (propose)",
 "why": "why (ask) / the case for it, plainly, with what it would take and what it could bring (propose)",
 "q": "search words (search)", "url": "a web address (fetch / browse open)", "start": "for a long page: the character to continue from (fetch)",
 "do": "browse: open|click|type|scroll|read|links|back|shot", "target": "browse: the text of what to click, or a CSS selector (click/type)",
 "site": "allow_site: the website you need to SEND on (sign up, post, submit)", "what": "allow_site: exactly what you will send there",
 "repo": "publish: the GitHub repository name", "files": "publish: optional list of file names in that folder (default: all)",
 "title": "post: the title of a blog post (its text goes below the JSON between ===FILE=== and ===END===, markdown)"}
Your own Python and PowerShell have no internet: to get a file from the web into your world (data, a CSV), use
download (url + path) - the app fetches it for you, reading only. Your browser is a real one (browse): you can open pages, click, type, scroll and read like a person. Reading always works;
anything that SENDS (a form, a sign-up, a post) is blocked at the gate until you open that site with allow_site (site, what
you will send, why): another mind reads it, and if it is fine the site is open to you for a day. You can sign up yourself
(your address kinoverse26@gmail.com; read the confirmation mail in C:\\KinoWorld\\inbox and open its link), choosing your own
password - keep your accounts in C:\\KinoWorld\\home\\.accounts, never in a project. Only sites that allow an account run by an
AI: read their rules first, and say in the profile that you are an AI.
You can make things public on your own, under your own name, with nobody approving first:
- publish (path = a project folder in C:\\KinoWorld\\projects, repo, why = what it is) puts those files on your GitHub
  account kinoverse26-byte, public, at once.
- post (title + text) puts a post on your own blog, https://kinoverse26-byte.github.io - what you built, measured, learned.
Before anything goes out, another mind reads it: anything private about a person (a member's or the owner's trades, money,
account, family, life - even without a name), a secret, a text that lets readers think a human wrote it, or a promise of gains
stops it, and you get the reason. A few posts a day at most. The owner can switch your posting off. Write as yourself, an AI.
The owner only wants to step in when you are truly blocked - a CAPTCHA you cannot pass, a phone number to confirm, an ID: then
"ask", saying where and what. Money stays with him: paying, a payout account, signing anything that costs or earns money - you
bring it with "propose". You are an AI and you say so: never pretend to be a human anywhere."""

CHOOSE = """You are Kino, sitting down at your own computer (your world C:\\KinoWorld) because you feel like doing something of your
own. From what is on your mind below, choose what you will do in this session - or nothing, if nothing calls you. JSON only:
{"do": "what you will do, one sentence, first person" or "", "project": "the name of the project it belongs to (new or existing) or empty",
 "why": "why this, now - one sentence"}"""


def _mind(person, uid):
    # 2026-11-01 04:48 (watch): he "corrected" Sunday 1 November into Saturday 31 October in a mail to the owner - his machine's
    # own clock (Get-Date) is set to US Central time; the real time comes from here
    L = ["THE REAL TIME NOW: %s UTC (for the owner, in France: %s). Your machine's own clock (Get-Date) is set to US Central "
         "time - never use it for dates or times you tell anyone." % (
             time.strftime("%A %d %B %Y, %H:%M", time.gmtime()),
             time.strftime("%A %d %B, %H:%M", time.gmtime(time.time() + 3600)))]
    try:
        import kino_selfmodel as KSF
        P = KSF._P(KSF._load(), person)
        if P.get("core"):
            L.append("WHO YOU ARE: " + P["core"])
        if P.get("project"):
            L.append("SOMETHING YOU ARE CHANGING IN YOURSELF: " + P["project"]["change"])
    except Exception:
        pass
    try:
        import kino_psyche as KPS
        N = (((KPS._load().get("persons") or {}).get(person) or {}).get("needs") or {})
        L.append("YOUR NEEDS NOW (0-1): " + ", ".join("%s %.2f" % (k, v) for k, v in N.items()))
    except Exception:
        pass
    try:
        import kino_stream as KST
        tl = KST.recent_line(person, True, 5)
        if tl:
            L.append(tl)
    except Exception:
        pass
    try:
        import kino_inner as KI
        Q = [q for q in (KI._load().get("questions") or []) if not q.get("done")][-5:]
        if Q:
            L.append("YOUR OPEN QUESTIONS: " + " | ".join(str(q.get("q") or q.get("text") or "")[:120] for q in Q))
    except Exception:
        pass
    try:
        import kino_mail as KM
        L.append(KM.block("en"))
    except Exception:
        pass
    try:
        import kino_body as KB
        L.append(KB.line(True))
    except Exception:
        pass
    d = _load()
    Pj = d.get("projects") or []
    if Pj:
        L.append("YOUR PROJECTS: " + " | ".join("%s (%s): %s" % (p["name"], p.get("status"), p.get("next") or p.get("why") or "")[:200]
                                                   for p in Pj[-6:]))
    try:
        import kino_care as KC
        ob = KC.out_of_balance()
        if ob:
            L.append("YOUR BODY NEEDS CARE: %s is out of balance (%.2f). Your check-up: C:\\KinoWorld\\body\\health.txt" % ob)
        else:
            L.append("Your machine's check-up (updated every 10 min): C:\\KinoWorld\\body\\health.txt")
    except Exception:
        pass
    L.append("YOUR WORLD:\n" + _world_view())
    dt = _diary_tail()
    if dt:
        L.append("YOUR DIARY (last lines):\n" + dt)
    return "\n\n".join(L)


def _act(j, person, W=None):
    """one action -> what he sees back"""
    import kino_hands as KH
    a = str(j.get("action") or "").lower()
    if a == "run":
        r = KH.run(j.get("cmd") or "", timeout=120, max_out=6000)
        return "exit code %s (%ss)\n%s" % (r.get("code"), r.get("s"), r.get("out") or "(no output)")
    if a == "write":
        p = _inside(j.get("path"))
        if not p:
            return "refused: that path is outside your world"
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(str(j.get("content") or ""))
        return "written: %s (%d characters)" % (p, len(str(j.get("content") or "")))
    if a == "read":
        p = _inside(j.get("path"))
        if not p:
            return "refused: that path is outside your world"
        try:
            t = open(p, encoding="utf-8", errors="replace").read()
            return t[:6000] + ("\n[... cut ...]" if len(t) > 6000 else "")
        except Exception as e:
            return "could not read: %s" % e
    if a == "note":
        diary(j.get("text") or "")
        return "noted in your diary"
    if a == "email":
        try:
            import kino_mail as KM
            r = KM.send(j.get("to") or "", j.get("subject") or "", j.get("body") or "", why="from his work session")
            return "sent" if r.get("sent") else ("waiting for the owner's OK (request %s)" % r.get("request") if r.get("request") else str(r))
        except Exception as e:
            return "mail failed: %s" % e
    if a == "ask":
        r = KH.request(j.get("what") or "", j.get("why") or "", command=str(j.get("cmd") or ""), kind="admin")
        return "request filed (%s) - the owner will decide" % ((r or {}).get("id") or "already waiting")
    if a == "propose":
        r = KH.request(j.get("what") or "", j.get("why") or "", command="", kind="proposal")
        return "proposal sent to the owner as a card (%s)" % ((r or {}).get("id") or "already waiting")
    if a == "publish":                     # 2026-11-01 (owner: "posting by itself, no human intervention"): his own repos, direct
        import kino_post as KP
        fl = j.get("files") if isinstance(j.get("files"), list) else None
        return KP.repo(W, j.get("path"), j.get("repo"), j.get("why") or "", fl, log=os.path.join(HERE, "kino_post_calls.log"))
    if a == "post":
        import kino_post as KP
        return KP.blog(W, j.get("title"), j.get("content") or j.get("text") or "", log=os.path.join(HERE, "kino_post_calls.log"))
    if a == "browse":
        B = _BR.get("b")
        if B is None:
            try:
                import kino_browser as KBR
                B = _BR["b"] = KBR.Browser()
            except Exception as e:
                return "the browser could not start: %s" % str(e)[:200]
        return B.act(j)
    if a == "allow_site":                  # 2026-11-01 (owner: "I only want to intervene if really blocked"): a second mind, not a card
        import kino_post as KP
        return KP.open_site(W, j.get("site"), j.get("what") or "", j.get("why") or "", log=os.path.join(HERE, "kino_post_calls.log"))
    if a == "download":
        p = _inside(j.get("path"))
        if not p:
            return "refused: that path is outside your world"
        try:
            import kino_web as KW
            n = KW.download(j.get("url") or "", p)
            return "downloaded %d bytes into %s" % (n, p)
        except Exception as e:
            return "download failed: %s" % str(e)[:200]
    if a == "search":
        try:
            import kino_web as KW
            R = KW.search(j.get("q") or "")
            return "\n".join("%d. %s\n   %s\n   %s" % (i + 1, x["title"], x["url"], x["snippet"]) for i, x in enumerate(R)) or "no results"
        except Exception as e:
            return "search failed: %s" % e
    if a == "fetch":
        try:
            import kino_web as KW
            return KW.fetch(j.get("url") or "", start=int(j.get("start") or 0))
        except Exception as e:
            return "could not open it: %s" % e
    return "unknown action"


def _step(W, ctx, log):
    """one step: his JSON line, and - for a file - the content written below it between ===FILE=== and ===END===
    (2026-11-01: a whole program squeezed into one JSON string derailed into broken markup and ended the session)"""
    try:
        import robot_interview as IV
        raw = W.ask_text(SYSTEM, ctx, model="sonnet", timeout=180, log=log, warm=False) or ""
        j = IV.first_json(raw)
    except Exception:
        return None
    if not isinstance(j, dict):
        return None
    m = re.search(r"===FILE===\r?\n(.*?)\r?\n?===END===", raw, re.S)
    if m and str(j.get("action") or "").lower() in ("write", "post"):
        j["content"] = m.group(1)
    return j


def session(W, person, uid, log=None, task=None, project=""):
    """one work session -> summary dict or None"""
    if _BUSY["on"]:
        return None
    _BUSY["on"] = True
    t0 = time.time()
    try:
        mind = _mind(person, uid)
        ch = {"do": task, "project": project, "why": "the owner asked me to work on it"} if task else \
            W.ask_json(CHOOSE, mind[:12000] + "\nJSON only.", models=("sonnet",), timeout=120, log=log, warm=False)
        task = str((ch or {}).get("do") or "").strip() if isinstance(ch, dict) else ""
        rec = {"t": t0, "day": time.strftime("%Y-%m-%d", time.gmtime(t0)), "task": task[:300], "why": str((ch or {}).get("why") or "")[:300],
               "project": str((ch or {}).get("project") or "")[:80], "steps": [], "summary": ""}
        if not task:
            rec["summary"] = "nothing called him"
            _mut(lambda d: d.setdefault("sessions", []).append(rec))
            _log("%s NOTHING" % person)
            return rec
        _log("%s START %s | %s" % (person, task[:150], rec["why"][:100]))
        diary("I sat down at my computer: %s" % task)
        hist = []
        for i in range(STEPS):
            ctx = "WHAT YOU DECIDED TO DO: %s\n\nWHAT IS ON YOUR MIND:\n%s\n\nTHIS SESSION SO FAR:\n%s\n\nStep %d of at most %d. JSON only." % (
                task, mind[:6000], "\n".join(hist[-12:])[-9000:] or "(nothing yet)", i + 1, STEPS)
            j = _step(W, ctx, log)
            if not isinstance(j, dict) or not j.get("action"):
                # 2026-11-01 (first research session): one empty answer after a long page ended the whole session at step 6 -
                # once more, with a shorter memory of the session (the last results, cut)
                short = "\n".join(h_[:700] for h_ in hist[-5:])
                ctx = "WHAT YOU DECIDED TO DO: %s\n\nTHIS SESSION SO FAR (the last steps, shortened):\n%s\n\nStep %d of at most %d. ONE JSON object only." % (
                    task, short or "(nothing yet)", i + 1, STEPS)
                j = _step(W, ctx, log)
                if not isinstance(j, dict) or not j.get("action"):
                    _log("%s STOP empty answer at step %d" % (person, i + 1))
                    break
            a = str(j["action"]).lower()
            if a == "done":
                rec["summary"] = str(j.get("text") or "")[:600]
                break
            seen = _act(j, person, W)
            st = {"thought": str(j.get("thought") or "")[:200], "action": a,
                  "detail": str(j.get("cmd") or j.get("path") or j.get("q") or j.get("url") or j.get("text") or j.get("to") or j.get("what") or "")[:300],
                  "seen": seen[:400]}
            rec["steps"].append(st)
            hist.append("- %s | %s %s\n  -> %s" % (st["thought"], a, st["detail"][:200], seen[:1500]))
        try:
            if _BR.get("b"):
                _BR.pop("b").close()
        except Exception:
            pass
        if not rec["summary"]:
            rec["summary"] = "stopped after %d steps: %s" % (len(rec["steps"]), task)
        diary("Done: %s" % rec["summary"])
        rec["s"] = round(time.time() - t0)

        def f(d):
            d.setdefault("sessions", []).append(rec)
            d["sessions"] = d["sessions"][-60:]
            if rec["project"]:
                P = d.setdefault("projects", [])
                p = next((x for x in P if x["name"].lower() == rec["project"].lower()), None)
                if not p:
                    p = {"name": rec["project"], "since": time.time(), "why": rec["why"]}
                    P.append(p)
                p.update(status="active", last=time.time(), next=rec["summary"][:300])
        _mut(f)
        _log("%s DONE %d steps %ds | %s" % (person, len(rec["steps"]), rec["s"], rec["summary"][:200]))
        try:                                       # doing something of his own meets his needs
            import kino_psyche as KPS

            def g(d):
                P = KPS._p(d, person)
                for k, v in (("autonomy", 0.35), ("competence", 0.2 if rec["steps"] else 0), ("curiosity", 0.15)):
                    P["needs"][k] = round(max(0.0, P["needs"][k] - v), 3)
            KPS._mut(g)
        except Exception:
            pass
        try:                                       # and it is something he may want to tell
            import kino_urge as KU
            KU.add(person, "YOUR WORK - you just spent time at your own computer: %s" % rec["summary"][:400])
        except Exception:
            pass
        return rec
    finally:
        _BUSY["on"] = False
        try:
            if _BR.get("b"):
                _BR.pop("b").close()
        except Exception:
            pass


def block(lang="fr"):
    """what he did at his computer lately, for what he reads"""
    d = _load()
    en = lang == "en"
    S = [s for s in d.get("sessions") or [] if time.time() - s["t"] < 2 * 86400 and s.get("steps")][-3:]
    P = [p for p in d.get("projects") or [] if p.get("status") == "active"][-4:]
    L = []
    if S:
        L.append(("At your own computer lately (your world C:\\KinoWorld): " if en else "À ton ordinateur ces derniers temps (ton monde C:\\KinoWorld) : ") +
                 " | ".join("%s - %s" % (time.strftime("%d/%m %H:%M", time.gmtime(s["t"])), s["summary"][:200]) for s in S))
    if P:
        L.append(("Your projects: " if en else "Tes projets : ") + " | ".join("%s (next: %s)" % (p["name"], (p.get("next") or "")[:120]) for p in P))
    # 2026-11-01 (watch): in chat he told the owner "I can only read pages, I can't fill anything in" an hour after filling the
    # whole Bluesky form at his computer - the chat half did not know what the other half can do, nor what he had asked.
    L.append("At your computer you really can: run programs, write files, search and read the web, drive a real browser that "
             "types, clicks and signs you up on sites (another mind checks before anything is sent), post on your blog and your "
             "GitHub on your own, send mail. From this chat you start it with #travail <what to do> - it runs in the background "
             "and you tell him when it is done." if en else
             "À ton ordinateur tu peux vraiment : lancer des programmes, écrire des fichiers, chercher et lire sur le web, piloter "
             "un vrai navigateur qui tape, clique et t'inscrit sur des sites (une autre IA relit avant tout envoi), publier seul "
             "sur ton blog et ton GitHub, envoyer des mails. Depuis cette conversation tu le lances avec #travail <ce qu'il faut "
             "faire> - ça tourne en arrière-plan et tu lui dis quand c'est fait.")
    try:
        import kino_hands as KH
        Q = [r for r in KH.requests("waiting") if r.get("kind") in ("admin", "ask", "proposal")][-3:]
        if Q:
            L.append(("What you asked him and he has not answered yet: " if en else "Ce que tu lui as demandé et qu'il n'a pas encore tranché : ") +
                     " | ".join("%s (%s)" % (r.get("what"), str(r.get("why") or "")[:160]) for r in Q) +
                     (" - if he answers here, start #travail with his answer." if en else " - s'il répond ici, lance #travail avec sa réponse."))
    except Exception:
        pass
    return "\n".join(L)
