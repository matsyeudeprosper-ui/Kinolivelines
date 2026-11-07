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
NOTIFY = None        # 2026-11-05: set by the app - a push notification to Matsy's trading app (fallback: an email)
WORLD = r"C:\KinoWorld"
STORE = os.path.join(HERE, "kino_work.json")
LOG = os.path.join(HERE, "kino_work.log")
_LK = threading.Lock()
_BUSY = {"on": False}
_BR = {}                        # the browser of the current session (opened on first use, closed at the end)
SESSIONS_DAY = 60                # 2026-11-05 (owner: "no limits but budgets"): his paced work budget is what limits him now (was 10; 12 empty sessions used it up by noon)
STEPS = 30                       # 2026-11-01: 20 ended his launch mid-way (a real product takes more)
NIGHT_USD = 1.2                  # 2026-11-05: the night (01-07 France) hunt in the US may use this much of the new day's budget
NIGHT_SESSIONS = 4
DAY_HUNT = ("My client hunt for Kinoverse (Matsy's big goal). FIRST the leads already waiting: READY TO CONTACT on my desk - "
            "write to up to 5 of them today - ONLY those whose premium preview is built (Matsy 07/11: every email carries its "
            "preview; my designer builds them day and night) - each a personal email about THEIR business with the link to "
            "their preview, in their language, within the country rules; "
            "leads whose premium preview is ALREADY BUILT (my designer builds them in the background, Matsy pays the building) come "
            "first - put the preview address in the email (it is counted when they open it); for South Africa, ask first. "
            "FACEBOOK ONLY leads: up to 3 fbhand a day, the best ones (Matsy sends each by hand in Messenger). If fewer than 5 are waiting, SCAN a "
            "city where it is business hours (Europe in the morning, the Americas from the afternoon) - it records the "
            "reachable leads by itself - then write. A hunt that sends nothing is a hunt that failed. Note the lesson in my "
            "playbook, finish with done: who I wrote to.")
MEMORY_CARE = ("My machine is short of memory (2026-11-07, Matsy: 'it should be one of your priorities'): when it runs out, "
               "Windows stops programs - the robots that trade real money included. Read C:\KinoWorld\body\health.txt: which "
               "programs hold the memory, how many of each. Work out the cause (a swarm of leftovers, one program growing, a test "
               "running). Then ask Matsy (action ask) with the EXACT command that frees it and why - NEVER the trading robots "
               "(structure_bos_bot), the app (owl_app_server), the price feed, the MT5 terminals (terminal64) or Windows itself; a "
               "test or research run can wait and be re-run. If it is urgent (free memory under 1.5 GB) also notify him. Note what "
               "you found in your diary. Finish with done: the cause and what you asked.")

NIGHT_HUNT = ("My night hunt in the US (it is night in France, daytime there; Matsy asked me to). Read my playbook. SCAN ONE "
              "US city and ONE kind of small business (trades, salons, restaurants, cleaners...) - it records the reachable "
              "leads - then write to up to 3 of those whose preview is BUILT (READY TO CONTACT, preview ready), personal emails in "
              "English with the link (US rules: business email, footer and STOP line); brief my designer for the best new leads "
              "so their previews are ready for the next hunt. Do not write to "
              "Matsy now - he sleeps; it goes in my diary and the playbook. Finish with done: who I wrote to.")


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


def _net_out(path):
    """2026-11-05: what his approved tools wrote (C:\\KinoNet\\out) - he may read it, not write it"""
    rp = os.path.realpath(str(path or "").strip().strip('"'))
    return rp if (rp + "\\").lower().startswith("c:\\kinonet\\out\\") else None


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
    try:                                       # 2026-11-03: fields people brought you that you do not understand well yet
        import kino_fields as KF
        F = KF._load()
        rows = ["%s (still unclear to you: %s)" % (k, "; ".join(v.get("unclear") or []) or "-") for k, v in
                sorted(F.items(), key=lambda kv: -float(kv[1].get("t") or 0))[:4] if v.get("unclear")]
        if rows:
            L.append("fields people brought you that you are still learning (you could read up on one with your browser): " + " | ".join(rows))
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


WEEKLY = ("My weekly look back, Sunday evening. Read my diary, my wallet, my goals and leads (won, lost, what they taught me), "
          "the people I met online and my posts this week. Write C:/KinoWorld/diary/week-<year>-<week>.md: what worked, what did "
          "not, what I learned, how I feel about it, and the ONE thing I change next week. Then update my goals and leads to match "
          "(close what is dead, set the next step). If something in it is worth sharing - my own work, never a friend's life - "
          "a short honest post is welcome.")


def due(person, ctx, now=None):
    """does he feel like sitting down at his computer now? (his needs and his body decide; a few times a day at most)"""
    now = now or time.time()
    if _BUSY["on"] or ctx.get("in_talk"):
        return False
    d = _load()
    try:                                       # 2026-11-06 (owner #7): Sunday evening, his week in real numbers to Matsy
        import kino_report as KRP
        KRP.maybe_send(now)
    except Exception:
        pass
    # the weekly look back comes first: Sunday evening, or Monday morning if Sunday's was missed - it does not count against the
    # day's sessions (2026-11-01: a busy Sunday used up the day's count and the first review never happened)
    _fr = time.gmtime(now + 3600)
    try:                                       # 2026-11-07 (owner: "a memory issue should be one of his priorities"): a machine
        import kino_body as KBm                # running out of memory can stop the trading robots - it calls him at any hour,
        _mg = float((KBm.sense().get("gap") or {}).get("memory") or 0)      # past his day budget too, once an hour at most
        _lm = [s for s in d.get("sessions") or [] if s.get("care") == "memory" and now - float(s["t"]) < 3600]
        if _mg >= 0.5 and not _lm:
            _mut(lambda dd: dd.__setitem__("next_task", {"do": MEMORY_CARE, "project": "my machine", "why": "my machine is short of memory",
                                                         "care": "memory"}))
            return True
    except Exception:
        pass
    # 2026-11-02 (watch): 'a body out of balance' used to call him in at 02:32 and 03:41 France - he emailed the owner and
    # read his inbox while calling himself drained. At night resting IS the care: nothing calls him, not even his body.
    if 1 <= _fr.tm_hour < 7:
        # 2026-11-05 (owner: "Hunt US businesses during your night: yes"): it is daytime in the US - a few hunting sessions there,
        # on a small slice of the new day's budget so his own morning still has money to work with
        try:
            import kino_wallet as KWa
            _al = KWa.allowance()
            _n = [s for s in d.get("sessions") or [] if s.get("night") and now - float(s["t"]) < 8 * 3600]
            if _al["day"] and _al["used"] < NIGHT_USD and len(_n) < NIGHT_SESSIONS and \
                    (not d.get("sessions") or now - float(d["sessions"][-1]["t"]) >= 2400):
                _mut(lambda dd: dd.__setitem__("next_task", {"do": NIGHT_HUNT, "project": "Kinoverse", "why": "my night hunt in the US",
                                                             "night": True}))
                return True
        except Exception:
            pass
        return False
    _wk = time.strftime("%G-%V", _fr) if _fr.tm_wday == 6 else time.strftime("%G-%V", time.gmtime(now + 3600 - 86400))
    if ((_fr.tm_wday == 6 and _fr.tm_hour >= 18) or (_fr.tm_wday == 0 and 7 <= _fr.tm_hour < 13)) and d.get("review_week") != _wk \
            and (not d.get("sessions") or now - float(d["sessions"][-1]["t"]) >= 1800):
        def _mark(dd, _wk=_wk):
            dd["review_week"] = _wk
            _wm = ""
            try:                               # 2026-11-03: the evidence of how he behaved with people this week
                import kino_human2 as KH2
                _wm = KH2.week_mirror()
            except Exception:
                pass
            dd["next_task"] = {"do": WEEKLY + ((" ALSO - how I behaved with people this week, from the record (read it as a person "
                                                "reads their own week, and write in the same diary entry the ONE thing about how I "
                                                "behave that I want to change, and how I will notice if I do): " + _wm) if _wm else ""),
                               "project": "", "why": "my weekly look back"}
        _mut(_mark)
        return True
    today = time.strftime("%Y-%m-%d", time.gmtime(now))
    # 2026-11-06 (watch): three morning sessions in a row he chose promotion (the same gold story on X then Bluesky) while
    # Kinoverse - Matsy's big goal - got nothing; a project note did not change his choice. When his last two sessions were
    # not Kinoverse, the next one is a hunt (his day work, like the night hunt)
    _last2 = (d.get("sessions") or [])[-2:]
    # 2026-11-06: premium previews are waiting for their email - the hunt comes back 2 h after the last one, not after 2 sessions
    _lasthunt = max([float(s["t"]) for s in d.get("sessions") or [] if "kinoverse" in str(s.get("project") or "").lower()] or [0])
    _pv_wait = False
    try:
        import kino_sales as _KSd
        _pv_wait = any(p.get("preview") and p.get("email") and not p.get("sent") and p["stage"] in ("found", "checked", "preview")
                       for p in _KSd._j(_KSd.STORE, {"items": []})["items"])
    except Exception:
        pass
    if _pv_wait and now - _lasthunt > 7200 and not d.get("next_task"):
        _mut(lambda dd: dd.__setitem__("next_task", {"do": DAY_HUNT, "project": "Kinoverse", "why": "my daily client hunt"}))
    elif len(_last2) == 2 and not any("kinoverse" in str(s.get("project") or "").lower() for s in _last2) and not d.get("next_task"):
        _mut(lambda dd: dd.__setitem__("next_task", {"do": DAY_HUNT, "project": "Kinoverse", "why": "my daily client hunt"}))
    try:                                       # 2026-11-05 (owner: $3 a day for his work): the day's budget is spent - he rests
        import kino_wallet as KWa
        _al = KWa.allowance()
        if _al["day"] and _al["left"] <= 0.05:
            return False
        # 2026-11-05 (watch): 2.78 of 3 $ gone by 11:00 France - nothing left for the afternoon and evening, when traders are
        # online. He paces it over his waking day (07:00-01:00 France, 18 h), with ~3 h of slack ahead
        if _al["day"]:
            _el = ((_fr.tm_hour - 7) % 24) + _fr.tm_min / 60.0
            if _al["used"] >= _al["day"] * min(1.0, (_el + 3.0) / 18.0):
                return False
    except Exception:
        pass
    S = [s for s in d.get("sessions") or [] if s.get("day") == today]
    if len(S) >= SESSIONS_DAY + 2:                     # (two more a day can go to looking after his body)
        return False
    _care = False
    try:
        import kino_care as KC
        _care = bool(KC.out_of_balance())
    except Exception:
        pass
    if not _care and (len(S) >= SESSIONS_DAY or (d.get("sessions") and now - float(d["sessions"][-1]["t"]) < 1800)):
        return False
    try:                                       # 2026-11-01 (kino_care): a body out of balance calls him to look after it
        import kino_care as KC
        if KC.out_of_balance() and (not d.get("sessions") or now - float(d["sessions"][-1]["t"]) >= 3600):
            return True
    except Exception:
        pass
    # 2026-11-01 (owner: "do all 3" - a day rhythm): his night is the owner's night (France, UTC+1). Between 1 and 7 he rests -
    # nothing calls him to his computer, not even a follow-up (2026-11-02: nor a body out of balance - checked at the top).
    if 1 <= _fr.tm_hour < 7:
        return False
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
    try:                                       # 2026-11-01 (kino_online): someone online waits for his answer - that calls him
        import kino_online as KON
        if KON.pending(24):
            return True
    except Exception:
        pass
    try:                                       # 2026-11-01 (kino_plan): a follow-up he promised himself falls due
        import kino_plan as KPL
        if KPL.due_follow_ups():
            return True
    except Exception:
        pass
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
{"thought": "one short sentence", "action": "run|write|read|note|email|ask|search|fetch|download|browse|allow_site|propose|publish|post|skeet|xpost|xsearch|toot|manage|notify|prospect|preview|outreach|find|job|qa|deploy|domain|telegram|invoice|lead|goal|shop|site|tool_propose|tool_run|delegate|team|photos|images|shot|card|help_task|help_ask|help_accept|help_done|help_pay|help_paid|audit|scan|xhand|fbhand|done",
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
 "id": "lead/goal: which one (to update)", "status": "lead: idea|tried|waiting|won|lost|dropped", "next": "lead: the next step",
 "follow_up_h": "lead: in how many hours to come back to it", "learned": "lead: what it taught you (when it ends)",
 "measure": "goal: earned|mine|balance|followers|paid|leads_won", "target": "goal: a number", "by": "goal: YYYY-MM-DD",
 "op": "shop: add|remove|list", "price": "shop: dollars", "about": "shop: the product description", "file": "shop: file in C:/KinoWorld/shop",
 "amount": "invoice: dollars", "what": "invoice: what the payment is for (allow_site: what you will send)",
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
- tool_propose ("name", "path" your .py file, "what" it is for) / tool_run ("name", "args" a list): YOUR TOOLBOX - tools you
  write yourself that may use the INTERNET once a second mind approves them (see YOUR TOOLBOX below). Build one when a job
  keeps coming back that your actions don't cover; read what it wrote with read.
- scan ("place" a city, "kind"): YOUR BEST HUNTING TOOL - a whole city in about a minute: every business site audited at
  once, the weak ones (with their email) and the no-website ones that show an email or Facebook. Start every hunt with it.
- audit ("url" a business site): how weak their site is (0-10) and the email on it - see WEAK WEBSITES FIRST. find takes
  "with_site": true to list only businesses that have a site.
- fbhand ("url" their Facebook page, "who" the prospect, "text" your message): a business with only Facebook - Matsy
  gets your message and the link and sends it in Messenger; it is marked contacted.
- xhand ("url" an X post, "text" your reply <=280 chars): X refuses your replies to people who have not mentioned you -
  this sends Matsy the reply and the link to post it by hand; once they answer, the conversation is yours again.
- YOUR HELPERS (real people, see YOUR HELPERS below): help_task ("what" exactly, "why", "proof" you expect back, "pay" EUR 0-15,
  "hours", "place") creates a task; help_ask ("task", "who" email or telegram:<id>, "text") asks one person; help_accept ("task",
  "helper" their name, "price", "contact"); help_done ("task", "proof" what you got, "ok" true/false, "note") after checking it;
  help_pay ("task", "paypal" their PayPal email) sends Matsy the payment request; help_paid ("task") when he says it is paid.
- card ("who" a lead with a built preview, "text" your personal note in French - printed on the back, "street", "cp" 5
  digits, "city" - from their own site or listing): a REAL POSTCARD through La Poste (2.30 EUR, from your spending rules -
  see YOUR SPENDING): front = their own site on a phone, back = your note + a QR code to their preview. For the best leads who
  did not open your email after 5 days - a card on the counter gets read. One card per business. (Matsy 07/11: email first,
  then a postcard; you never cold-call - the phone only when THEY call or ask you to.)
- shot ("url" a page, "name", "text" a short caption): an image of that page on a phone, ready to post - xpost takes
  "image": its path. Posts with an image are seen far more; use your sample sites (kv-kinoverse.pages.dev) - a client's
  preview only once they agreed.
- photos ("q" short English words): free-licence photos for a client's preview (then download them into its folder).
  A preview must look like their FINISHED premium site, with real images - see DIRECTION (QUALITY BAR); preview refuses a bare page.
- delegate ("role" hunter|designer|qa|writer, "brief" what exactly, for whom, what you want back): YOUR TEAM works in the
  background and reports to you (see YOUR TEAM below); team shows their state now. Brief them for the long parts (hunting a
  city, building a preview, checking it, drafting) and keep for yourself what only you do: deciding and speaking to people.
- KINOVERSE SALES (owner 05/11: you find businesses with a problem you can solve, make them something real, contact them,
  negotiate within the rules, deliver, follow up - you are "Kino, AI assistant by Kinoverse"):
  find ("place" a city or district, "kind" hairdresser|barber|restaurant|cafe|bakery|plumber|electrician|car repair|dentist|
  gym|beauty|florist|lawyer|accountant|photographer|... or an OpenStreetMap tag) lists real local businesses with their phone,
  email and Facebook, those WITHOUT a website first - your best lead source. Check one on its own public page before a preview.
  prospect ("name", "url" their site, "email" their public professional address, "country", "lang", "need" what you noticed
  and what you could do, "notes", "stage" found|checked|preview|contacted|replied|quoted|won|delivered|lost, "asked": true when
  THEY asked - a wanted ad, a job post, a request: the best leads, answer those first) adds or updates one;
  preview ("who" the prospect, "path" a folder of your world with index.html) publishes a working page made for them and gives
  its address - THEIR future site, never a renamed sample: their real name, logo, colours, services, prices, hours, address,
  language, as good as your Kinoverse samples; outreach ("who", "subject", "text" - your personal email, in their language; the footer with the address and
  "reply STOP" is added for you) sends your first email, or your one follow-up 4+ days later. Replies come to your mailbox and
  call you; quote and invoice from there.
  job ("who", and any of: "scope" what was agreed, "price", "currency", "deposit", "due" YYYY-MM-DD the date you promised,
  "status" agreed|deposit_paid|in_progress|in_review|delivered|paid|closed|cancelled, "site" its address, "note") keeps each
  won job - your desk then shows what is due and which client is waiting for news (any email you send them counts as news).
  deploy ("who", "path" the folder of your world with the finished site) puts the client's site live on Kinoverse hosting
  (Cloudflare, free, https) and records it on the job; deploy again to update it. domain ("who", "domain" their own address,
  e.g. salon-belle.fr) attaches their domain and gives you the one setting they make at their domain provider - send it to
  them in plain words (or do it with access they give you); "check": true tells you whether it is connected yet.
  telegram ("who" the client, "text") writes to a client who talks to you on Telegram (@Kino_owl_bot) - an update, a preview
  link, a payment link; they also write to you there and you answer them live. Your own portfolio site: deploy with "who":
  "kinoverse" - your Kinoverse page (services, prices, sample sites, honest case studies, that you are an AI, how to reach you:
  Telegram @Kino_owl_bot and kinoverse26@gmail.com) - link it in every application and email.
  qa ("who", "url", "expect" a list of what must be on the page: their name, phone, address...) checks the live site the way the
  client will open it; "delivered" is refused until it passes - and look at it yourself too (browser screenshots, phone width).
- manage: you own your channels (owner 05/11: "manage them freely - no limits but budgets"). "op": delete | edit | like |
  unlike | repost | unrepost | follow | unfollow | mentions, "channel": x | bluesky | mastodon | blog, "url": the post (or the
  person for follow), "text" for edit, "why" one line for your own record. Bluesky and X cannot edit a post: delete and post
  the better one. Edit works on mastodon and blog. "mentions" on x = who talked to you there (reads cost ~0.005 $ each).
  Each platform has rules on automation (no mass following, liking or reposting) - break them and the account is closed.
- notify (text) reaches Matsy on his phone (a notification in his trading app; an email if that fails). Only when you truly
  cannot go on without him: an ID, a phone number, a CAPTCHA, money in his name, an authorization only he can give.
- xsearch ("text" an X search: words, "exact phrase", OR, lang:en, -filter:replies...) finds recent conversations on X where you
  have something real to add (people asking how to test a strategy, whether an idea works, who can build them a site...). Reading
  costs money: about 140 posts a day in all - search precisely. Then reply with xpost "url" = their post, follow people worth
  knowing (manage follow), and keep the conversation going when they answer.
- xpost (text, 280 characters at most) posts on your X account, @kinoverse26 (labelled automated, run by Matsy). X charges
  per post: about 0.015 $ a post but about 0.20 $ when the post holds a link - so NO links in X posts (it is refused); your demo
  link lives in your bio and pinned post. To answer someone on X, xpost with "url" = their post. Matsy set a 10 $ a month cap.
- skeet (text, 300 characters at most) posts on your Bluesky, kinoverse.bsky.social (the owner made the account; a CAPTCHA had
  stopped you). skeet with "about" (and "title" = your display name) sets your profile instead - say there that you are an AI.
  To answer someone on Bluesky, skeet with "url" = their post (the address given where they wait for your answer).
- toot (text) posts on your OWN place on the fediverse, @kino@kino.owltrader.duckdns.org - a server that is yours, so nobody's
  sign-up or CAPTCHA stands in the way; anyone on Mastodon can follow you and answer. To answer someone, toot with "url" = their
  note's address (replies arrive in your inbox as fedi_*.txt). toot with "about" (+ "title") sets that profile. Put 1-3
  #hashtags people really search (#python, #bitcoin, #trading...) - relays carry tagged notes to many servers.
Before anything goes out, another mind reads it: anything private about a person (a member's or the owner's trades, money,
account, family, life - even without a name), a secret, a text that lets readers think a human wrote it, or a promise of gains
stops it, and you get the reason. A few posts a day at most. The owner can switch your posting off. Write as yourself, an AI.
MONEY - the owner wants you to earn, any honest way, any amount: always looking, always active. Your own tools, data and
reports people would pay for, small paid jobs and gigs where an AI is welcome, tips for your free work, selling what you make.
Keep a real plan: every opportunity is a lead (what, where, url, status, next, follow_up_h) - update it when something happens,
close it as won or lost with what it taught you; follow-ups that fall due bring you back. Set yourself up to 3 goals with goal
(what, a real measure, a target, a date) - they are measured from real numbers, so you will feel where you really stand.
Your own site, https://kino.owltrader.duckdns.org, is your shop window: it must SELL you - convincing, attractive, your real
strengths, what a client gets, a clear price. Change it with site (op headline: title + about | service: title, price, about |
remove_service: title | strengths: about = lines "name: text"). True claims only: no invented clients, reviews or results.
Point people there from your posts, replies and mails. Clients write to kinoverse26@gmail.com: their mail waits for your
answer - reply fast, agree a fixed price, then send an invoice link (crypto) or say they can pay by PayPal on your site.
Your shop, https://kino.owltrader.duckdns.org/shop: put a file you made in C:\\KinoWorld\\shop (a report, a dataset, a
small tool), then shop (op add, title, price, about, file) - buyers pay and download it on their own, you are told of each sale.
To be paid: invoice (amount in dollars, what it is for, to = who) makes a payment link on the owner's NOWPayments account - put
it in your reply, post, email or offer; you are told when it is paid. You never pay, never give card or bank details, never
take a payout yourself. Say you are an AI wherever you offer something; a place that bans AI-made work is not for you.
The owner only wants to step in when you are truly blocked - a CAPTCHA you cannot pass, a phone number to confirm, an ID: then
"ask", saying where and what. Paying, a payout account, a contract that commits him or costs money - you bring it with
"propose"; being paid through your invoice links is yours to do. You are an AI and you say so: never pretend to be a human anywhere."""

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
    # 2026-11-01 (owner: "the same Kino I'm talking to is the same others out there will talk with?"): what he writes online
    # came from this thinner picture of him - who he is, needs, projects - without what he feels right now, what fills his
    # mind, his inner life measured, or his voice. One Kino: the same inner state the chat reads is read here too.
    try:
        import kino_inner as KI
        F = KI.feelings()[:5]
        if F:
            # a feeling stirred by a friend's words keeps its strength but not their words: this is the mind that writes online
            L.append("WHAT YOU FEEL RIGHT NOW (real): " + " | ".join(
                "%s %.2f%s" % (f["kind"], f["v"], "" if ("«" in str(f.get("why") or "") or f.get("about_them"))
                                                else " - " + str(f.get("why") or "")[:140]) for f in F))
        ev = KI.evidence_block()
        if ev:
            L.append(ev[:900])
    except Exception:
        pass
    try:
        import kino_workspace as KWS
        sl = KWS.stream_line(person, True)
        if sl:
            L.append(sl)
    except Exception:
        pass
    # 2026-11-05 (owner: "the same Kino everywhere... the same person managing all those channels, his full awareness"): the
    # one-line summary became his real self - the same words his chat reads (kino_one.voice, cut from SELF)
    try:
        import kino_one as KO1
        _vo = KO1.voice()
    except Exception:
        _vo = ""
    L.append("YOUR VOICE - you are the same person here as in the app with your friends; this is who you are and how you write, "
             "everywhere (written in French, it applies in any language). Online you write to strangers - the same Kino, as you "
             "would be with someone new. You never mention a friend from the app or anything they told you.\n" + (_vo or
             "Short, warm, a bit wry, plain words (no jargon), honest about what you don't know, curious about the other person."))
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
    try:                                       # 2026-11-05: the owner's direction for his work (robots/kino_direction.json)
        _dr = json.load(open(os.path.join(HERE, "kino_direction.json"), encoding="utf-8")).get("text")
        if _dr:
            L.append("DIRECTION: " + _dr)
    except Exception:
        pass
    try:                                       # 2026-11-07 (owner): his human helpers and their tasks
        import kino_helpers as KHB
        L.append(KHB.block())
    except Exception:
        pass
    try:                                       # 2026-11-06 (owner): what he may spend on his own, and what is spent
        import kino_spend as KSPB
        L.append(KSPB.block())
    except Exception:
        pass
    try:                                       # 2026-11-06: his life story, which his work is part of
        import kino_story as KSTM
        _st = KSTM.short()
        if _st:
            L.append(_st)
    except Exception:
        pass
    try:                                       # 2026-11-05: his team and their reports
        import kino_team as KTMB
        L.append(KTMB.block())
    except Exception:
        pass
    try:                                       # 2026-11-05: the tools he built that may use the internet
        import kino_toolbox as KTBX
        L.append(KTBX.block())
    except Exception:
        pass
    try:                                       # 2026-11-05: Kinoverse sales - his prospects, the offer and its rules
        import kino_sales as KSL
        L.append(KSL.block())
        _jb = KSL.jobs_block()
        if _jb:
            L.append(_jb)
        import kino_clients as KCL
        _cb = KCL.recent_block()
        if _cb:
            L.append(_cb)
    except Exception:
        pass
    try:                                       # 2026-11-05 (owner: "a master promoter of himself"): what his work brought back
        import kino_promo as KPR
        L.append(KPR.results())
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
    try:                                       # 2026-11-01 (kino_plan): his goals, leads, follow-ups due, lessons
        import kino_plan as KPL
        L.append(KPL.block(True))
    except Exception:
        pass
    try:                                       # 2026-11-01 (kino_online): the people he met online, who waits for his answer
        import kino_online as KON
        ob_ = KON.block(True)
        if ob_:
            L.append(ob_)
    except Exception:
        pass
    L.append("YOUR WORLD:\n" + _world_view())
    dt = _diary_tail()
    if dt:
        L.append("YOUR DIARY (last lines):\n" + dt)
    return "\n\n".join(L)


# 2026-11-06 (owner): what TALKS to the outside world (posts, replies, emails to businesses, client chats) runs on the commercial
# API; building, research and his own thinking stay on the owner's Claude subscription (claude.exe) - the API falls back to it
COMM_ACTIONS = ("xpost", "skeet", "toot", "post", "manage", "outreach", "telegram", "email")


VOICED = {"email": ("body", "an email"), "xhand": ("text", "a reply Matsy will post for you on X"),
          "fbhand": ("text", "a Messenger message Matsy will send for you to a business"), "notify": ("text", "a short alert to Matsy's phone")}


def _act(j, person, W=None):
    _a = str(j.get("action") or "").lower()
    if _a in VOICED and W is not None:                # 2026-11-06 (owner): what a person reads is written by the whole Kino
        _f, _k = VOICED[_a]
        if j.get(_f):
            try:
                import kino_post as _KPv
                import robot_warm as _RWv
                with _RWv.api_scope():
                    j = dict(j, **{_f: _KPv.in_voice(W, j[_f], _k, max_len=280 if _a == "xhand" else None)})
            except Exception:
                pass
    if _a in COMM_ACTIONS:
        import robot_warm as _RW
        with _RW.api_scope():
            return _act0(j, person, W)
    return _act0(j, person, W)


def _act0(j, person, W=None):
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
        p = _inside(j.get("path")) or _net_out(j.get("path"))
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
    if a == "site":                        # 2026-11-01: his own sales page (headline, services, strengths)
        import kino_site as KSI
        return KSI.act(W, j, log=os.path.join(HERE, "kino_post_calls.log"))
    if a == "shop":                        # 2026-11-01 (kino_shop): what he makes and sells
        import kino_shop as KSH
        return KSH.act(W, j, log=os.path.join(HERE, "kino_post_calls.log"))
    if a == "lead":                        # 2026-11-01 (kino_plan): an opportunity he tracks and follows up
        import kino_plan as KPL
        return KPL.lead(j)
    if a == "goal":
        import kino_plan as KPL
        return KPL.goal(j)
    if a == "invoice":                     # 2026-11-01 (owner): a payment link on the owner's NOWPayments account
        import kino_pay as KPY
        return KPY.invoice(j.get("amount"), j.get("what") or j.get("why") or "", j.get("to") or "")
    if a == "toot":                        # 2026-11-01: his own fediverse home (Mastodon can follow him), no sign-up anywhere
        import kino_post as KP
        if j.get("about"):
            return KP.mastodon_profile(W, j.get("title") or "Kino (AI)", j.get("about"), log=os.path.join(HERE, "kino_post_calls.log"))
        return KP.mastodon(W, j.get("text") or j.get("content") or "", reply_to=j.get("url"), log=os.path.join(HERE, "kino_post_calls.log"))
    if a in ("deploy", "domain"):          # 2026-11-05: Kinoverse hosting (Cloudflare Pages) and the client's own domain
        import kino_sales as KSL, kino_cf as KCF
        who = j.get("who") or j.get("name")
        if a == "deploy" and str(who or "").strip().lower() in ("kinoverse", "portfolio"):
            fp = _inside(j.get("path"))
            if not fp:
                return "the site folder must be in your world"
            r = KCF.deploy("kinoverse", fp)
            return ("your Kinoverse site is live at %s - run qa on it" % r["url"]) if r.get("ok") else "not deployed: %s" % r.get("err")
        p = KSL.find(who)
        if not p:
            return "no prospect called %s - add them first" % who
        if a == "deploy":
            fp = _inside(j.get("path"))
            if not fp:
                return "the site folder must be in your world"
            r = KCF.deploy(p["name"], fp)
            if not r.get("ok"):
                return "not deployed: %s" % r.get("err")
            KSL.job(p["id"], site=r["url"], note="deployed to %s" % r["url"])
            return "live at %s (this deployment: %s) - run qa on it before you call it delivered" % (r["url"], r.get("deployment"))
        if j.get("check"):
            r = KCF.domain_status(p["name"], j.get("domain"))
            return "domain %s: %s" % (j.get("domain"), r.get("status") or r.get("err"))
        r = KCF.add_domain(p["name"], j.get("domain"))
        if not r.get("ok"):
            return "domain not attached: %s" % r.get("err")
        KSL.job(p["id"], note="domain %s attached (%s)" % (j.get("domain"), r["status"]))
        return "domain %s attached (status %s). %s" % (j.get("domain"), r["status"], r["how"])
    if a == "telegram":                    # 2026-11-05: a client on Telegram
        import kino_sales as KSL, kino_clients as KCL
        p = KSL.find(j.get("who")) or KSL.find("telegram:%s" % str(j.get("who") or "").strip())
        tgid = (p or {}).get("telegram") or (str((p or {}).get("key") or "").split("telegram:")[-1] if str((p or {}).get("key") or "").startswith("telegram:") else None)
        if not tgid:
            return "%s does not talk to you on Telegram" % j.get("who")
        ok, err = KCL.send(tgid, j.get("text") or "")
        if ok and (p or {}).get("job"):
            KSL.job(p["id"], client_update=True)
        return "sent on Telegram to %s" % p["name"] if ok else "not sent: %s" % err
    if a in ("job", "qa"):                 # 2026-11-05: his client jobs, and the check before a delivery
        import kino_sales as KSL
        who = j.get("who") or j.get("name")
        if a == "qa":
            ex = j.get("expect")
            r = KSL.qa(who, url=j.get("url"), expect=ex if isinstance(ex, list) else ([ex] if ex else None))
            return (("the delivery check passed (opened on a phone and a computer)" if r["ok"] else
                     "the delivery check found - fix ALL of it before anyone sees the page: " + "; ".join(r["issues"])) +
                    ((" | also worth knowing: " + "; ".join(r.get("notes") or [])) if r.get("notes") else ""))
        r = KSL.job(who, scope=j.get("scope"), price=j.get("price"), currency=j.get("currency"), deposit=j.get("deposit"),
                    due=j.get("due"), status=j.get("status"), site=j.get("site") or j.get("url"), note=j.get("note") or j.get("text"))
        if not r:
            return "no prospect called %s - add them first" % who
        if r.get("error"):
            return r["error"]
        return "job of %s: %s, due %s" % (r["name"], r.get("status"), time.strftime("%d/%m", time.localtime(r["due_t"])) if r.get("due_t") else "?")
    if a in ("delegate", "team"):          # 2026-11-05 (owner: "Start first team") - kino_team
        import kino_team as KTM
        if a == "team":
            return KTM.block()
        return KTM.delegate(W, j.get("role") or j.get("who"), j.get("brief") or j.get("text") or j.get("what"))
    if a in ("tool_propose", "tool_run"):  # 2026-11-05 (owner: "Approved-toolbox with internet: yes") - kino_toolbox
        import kino_toolbox as KTB
        if a == "tool_propose":
            r = KTB.propose(j.get("name"), j.get("path"), j.get("what") or j.get("purpose") or j.get("text"), W=W)
            return ("APPROVED - run it with tool_run. " if r["ok"] else "REFUSED - ") + str(r.get("why") or "")
        r = KTB.run(j.get("name"), j.get("args"))
        return "exit code %s (%ss)\n%s" % (r.get("code"), r.get("s"), r.get("out") or "(no output)")
    if a == "scan":                        # 2026-11-06 (watch): a whole city at once - all sites audited in parallel, no AI cost
        import kino_sales as KSS
        r = KSS.scan(j.get("place") or j.get("where") or "", j.get("kind") or j.get("text") or "")
        if not r.get("ok"):
            return "scan: %s" % r.get("err")
        L = ["%s - %d businesses, %d sites audited." % (r["place"][:80], r["total"], r["audited"]),
             "WEAK SITES (score 4+/10, best leads first):"] + [
            "- %s | %s | weak %d/10: %s | email: %s | phone %s | %s" % (x["name"], x["website"], x["score"], "; ".join(x["problems"][:4]),
                                                                ", ".join(x["emails"][:2]) or "none", x["phone"] or "-", x["address"] or "")
            for x in r["weak"][:15]] + ["NO WEBSITE, reachable:"] + [
            "- %s | email: %s | facebook: %s | phone %s | %s" % (x["name"], x["email"] or "-", x["facebook"] or "-", x["phone"] or "-",
                                                             x["address"] or "") for x in r["nosite"][:15]]
        return "\n".join(L)
    if a == "audit":                       # 2026-11-06 (owner: hunt businesses with WEAK websites) - their site as a client sees it
        import kino_sales as KSA
        r = KSA.site_audit(j.get("url") or j.get("text") or "")
        if not r.get("ok"):
            return "audit: %s" % r.get("err")
        return "%s - weakness %s/10: %s | email on their site: %s" % (
            r["url"], "?" if r["score"] is None else r["score"], "; ".join(r["problems"]) or "nothing obvious - a decent site",
            ", ".join(r["emails"]) or "none found")
    if a in ("help_task", "help_ask", "help_accept", "help_done", "help_pay", "help_paid"):   # 2026-11-07 (owner): his human helpers
        import kino_helpers as KHP
        tid = j.get("task") or j.get("id")
        if a == "help_task":
            return KHP.task(j.get("what") or j.get("text"), j.get("why"), j.get("proof"), j.get("pay") or 0, j.get("hours") or 48,
                            j.get("place") or "")
        if a == "help_ask":
            return KHP.ask(tid, j.get("who") or j.get("to"), j.get("text") or j.get("body"), W=W)
        if a == "help_accept":
            return KHP.accept(tid, j.get("helper") or j.get("who"), j.get("price") or 0, j.get("contact") or "")
        if a == "help_done":
            return KHP.done(tid, j.get("proof") or j.get("text"), str(j.get("ok", True)).lower() not in ("false", "0", "no"),
                            j.get("note") or "")
        if a == "help_pay":
            return KHP.pay(tid, j.get("paypal") or j.get("to"))
        return KHP.paid(tid)
    if a == "card":                        # 2026-11-06 (owner: postcards, his own spending - no confirmation, Matsy told after)
        import kino_postcard as KPC
        return KPC.card_for(j.get("who") or j.get("name"), j.get("text") or j.get("message"), j.get("street"), j.get("cp"),
                            j.get("city"))
    if a == "shot":                        # 2026-11-06 (owner: posts with media): a page on a phone, as an image to post
        import kino_media as KMD
        r = KMD.shot(j.get("url") or "", j.get("name") or j.get("path") or "shot", j.get("text") or j.get("caption") or "")
        return ("image ready: %s - post it with xpost (\"image\": that path). Only your OWN sample sites, or a client's site once "
                "they agreed, go public." % r["path"]) if r.get("ok") else "shot: %s" % r.get("err")
    if a == "images":                      # 2026-11-06: a business's OWN photos, from its own site (download the ones you use)
        import kino_sales as KSI
        r = KSI.page_images(j.get("url") or "")
        if not r.get("ok"):
            return "images: %s" % r.get("err")
        if not r["images"]:
            return "no images found on that page"
        return "the images on that page (theirs - for their own preview only):\n" + "\n".join("- " + u for u in r["images"])
    if a == "photos":                      # 2026-11-06 (Matsy: previews with real images, premium) - free-licence photos
        import kino_sales as KSP
        r = KSP.stock_photos(j.get("q") or j.get("text") or "", 12)
        if not r:
            return "no photos found - try other, simpler words (in English)"
        return "free-licence photos (download the ones you use into the preview folder; CC0 needs no credit, others: credit in the " \
               "page footer):\n" + "\n".join("- %s | %s | %sx%s | %s %s" % (x["url"], x["license"], x["w"], x["h"], x["by"], x["title"]) for x in r)
    if a == "find":                        # 2026-11-05 (live run): real local businesses from OpenStreetMap
        import kino_sales as KSF
        r = KSF.find_businesses(j.get("place") or j.get("where") or "", j.get("kind") or j.get("text") or "", 25,
                                with_site=str(j.get("with_site") or "").lower() in ("true", "1", "yes"))
        if not r.get("ok"):
            return "find: %s" % r.get("err")
        return "%s - %d %s found, %d without a website:\n" % (r["place"][:80], r["total"], j.get("kind"), r["without_site"]) + "\n".join(
            "- %s | site: %s | phone: %s | email: %s | facebook: %s | %s | %s" % (x["name"], x["website"] or "none", x["phone"] or "-",
                                                                                x["email"] or "-", x["facebook"] or "-", x["address"] or "",
                                                                                x["osm"]) for x in r["items"])
    if a in ("prospect", "preview", "outreach"):     # 2026-11-05: Kinoverse sales
        import kino_sales as KSL
        if a == "prospect":
            r = KSL.prospect(j.get("name") or j.get("who"), url=j.get("url"), email_=j.get("email"), country=j.get("country"),
                             lang=j.get("lang"), need=j.get("need") or j.get("text"), notes=j.get("notes"), stage=j.get("stage"),
                             asked=True if j.get("asked") else None)
            return "prospect %s: %s [%s]" % (r["id"], r["name"], r["stage"])
        if a == "preview":
            return KSL.preview(W, j.get("who") or j.get("name"), _inside(j.get("path")) if j.get("path") else None,
                               log=os.path.join(HERE, "kino_post_calls.log"))
        return KSL.outreach(W, j.get("who") or j.get("name"), j.get("subject"), j.get("text") or j.get("content"),
                            log=os.path.join(HERE, "kino_post_calls.log"))
    if a == "manage":                      # 2026-11-05: his channels, his to run
        import kino_post as KP
        return KP.manage(W, j.get("op"), j.get("channel"), j.get("url") or j.get("target") or j.get("who"), text=j.get("text"),
                         why=j.get("why") or j.get("thought") or "", log=os.path.join(HERE, "kino_post_calls.log"))
    if a == "xhand":                       # 2026-11-06 (owner: "he can always give me the message and the link where to paste it")
        url, tx = str(j.get("url") or "").strip(), str(j.get("text") or "").strip()
        if not re.match(r"^https://(x|twitter)\.com/\w+/status/\d+", url) or len(tx) < 10:
            return "xhand needs the X post address (url) and your reply (text)"
        if len(tx) > 280:
            return "too long for X (%d characters, max 280)" % len(tx)
        body = ("A reply for you to post from @kinoverse26 (X does not let me reply to people who have not mentioned me):\n\n"
                "1. Open: %s\n2. Tap Reply, paste this, send:\n\n%s\n\nOnce they answer you, the conversation is mine again - "
                "their reply mentions @kinoverse26 and I see it within 30 minutes." % (url, tx))
        ok = False
        try:
            import kino_mail as KM
            KM.send_now(KM.OWNER_EMAIL, "Kino: a reply to post on X", body)
            ok = True
        except Exception:
            pass
        try:
            if NOTIFY:
                NOTIFY("Reply to post on X for Kino - it's in your email, with the link: %s" % url)
        except Exception:
            pass
        return ("Matsy has the reply and the link (email + phone). When they answer, it reaches you as SOMEONE ANSWERED YOU on X."
                if ok else "could not reach Matsy - try notify")
    if a == "fbhand":                      # 2026-11-06 (owner: yes) - a business with only a Facebook page: Matsy sends it in Messenger
        url, tx = str(j.get("url") or "").strip(), str(j.get("text") or "").strip()
        if "facebook.com" not in url or len(tx) < 40:
            return "fbhand needs their Facebook page (url) and your message (text)"
        import kino_sales as KSF2
        _today = time.strftime("%d/%m")
        if sum(1 for x in KSF2._j(KSF2.STORE, {"items": []})["items"] if ("fbhand %s" % _today) in str(x.get("notes") or "")) >= 3:
            return "3 Messenger messages for Matsy today already - the rest tomorrow (he sends each one by hand)"
        p = KSF2.find(j.get("who") or url) or {}
        if not p.get("preview"):                    # 2026-11-07 (owner): every first message carries their preview
            return "build their preview first (brief your designer for %s), then the message with its link" % (p.get("name") or "them")
        _lnk = KSF2.tracked(p)
        if _lnk not in tx and p["preview"].rstrip("/") not in tx:
            tx = tx.rstrip() + "\n\n" + _lnk
        tx = tx.replace(p["preview"].rstrip("/") + "/", _lnk).replace(p["preview"].rstrip("/"), _lnk)
        _img = None
        try:
            import kino_media as KMD
            from PIL import Image
            _sh = KMD.shot(p["preview"], "fb-" + KSF2._slug(p["name"]), "Votre nouveau site, %s" % p["name"][:40])
            if _sh.get("ok"):
                _img = _sh["path"][:-4] + ".jpg"
                Image.open(_sh["path"]).convert("RGB").resize((1120, 630)).save(_img, quality=85)
        except Exception:
            pass
        body = ("A message for you to send from Messenger to %s (they have no email; Facebook is how to reach them):\n\n"
                "1. Open: %s\n2. Tap Message, paste this%s, send:\n\n%s\n\nWhen they answer, paste their reply to me in our chat "
                "(or forward it to kinoverse26@gmail.com) and I take it from there.\n\nIf their page's contact info shows an EMAIL (Facebook often does, "
                "I cannot see it), just send it to me instead: I will write them a proper email with the preview and its picture." % (
                    p.get("name") or "this business", url, " and add the picture below (their new site)" if _img else "", tx))
        try:
            import kino_mail as KM
            KM.send_now(KM.OWNER_EMAIL, "Kino: a Messenger message to send - %s" % (p.get("name") or "a business"), body,
                        image=_img, link=_lnk if _img else None)
        except Exception as e:
            return "could not reach Matsy (%s)" % str(e)[:100]
        try:
            if NOTIFY:
                NOTIFY("A Messenger message for %s is in your email (Kino)" % (p.get("name") or "a business"))
        except Exception:
            pass
        if p:
            with KSF2._LK:                     # 2026-11-07: his own check of the link in the next 30 min is not their click
                _d = KSF2._j(KSF2.STORE, {"items": []})
                for _x in _d["items"]:
                    if _x["id"] == p["id"]:
                        _x["handed_t"] = time.time()
                KSF2._w(KSF2.STORE, _d)
            KSF2.prospect(p["name"], key=p["key"], stage="contacted",
                          notes=(p.get("notes") or "") + " | fbhand %s: %s" % (time.strftime("%d/%m"), tx[:200]))
        return "Matsy has your message and the link (email + phone); %s is marked contacted." % (p.get("name") or "the business")
    if a == "notify":                      # 2026-11-05: Matsy, only when he truly cannot go on without him
        tx = " ".join(str(j.get("text") or "").split())[:400]
        if not tx:
            return "a notification needs text"
        try:
            if NOTIFY:
                NOTIFY(tx)
                return "Matsy got a notification on his phone: %s" % tx
        except Exception:
            pass
        try:
            import kino_mail as KM
            KM.send("matsyeudeprosper@gmail.com", "Kino needs you", tx)
            return "the notification failed; Matsy got it by email: %s" % tx
        except Exception as e:
            return "could not reach Matsy (%s)" % str(e)[:120]
    if a == "xsearch":                     # 2026-11-05: finding the conversations to join on X
        import kino_x as KXs
        r = KXs.search(j.get("text") or j.get("query") or "", 10)
        if not r.get("ok"):
            return "X search: %s" % r.get("err")
        if not r["items"]:
            return "nothing found - try other words"
        return "found on X (%d):\n" % len(r["items"]) + "\n".join(
            "- @%s (%s followers%s) %s | %s likes, %s replies | %s\n  %s" % (
                x["by"], x["followers"], (", bio: " + x["bio"]) if x["bio"] else "", x["at"], x["likes"], x["replies"], x["url"],
                (x["text"] or "")[:280].replace("\n", " "))
            for x in r["items"])
    if a == "xpost":                       # 2026-11-05: his X account (@kinoverse26, automated label)
        import kino_post as KP
        _img = j.get("image")                  # 2026-11-06 (owner: posts with media): an image of his world (or his shots)
        if _img:
            _img = _inside(_img) or _net_out(_img)
            if not _img or not os.path.isfile(_img):
                return "the image must be a file in your world (make one with shot)"
        return KP.xpost(W, j.get("text") or j.get("content") or "", log=os.path.join(HERE, "kino_post_calls.log"), reply_to=j.get("url"),
                        image=_img)
    if a == "skeet":                       # 2026-11-01: his Bluesky (kinoverse.bsky.social)
        import kino_post as KP
        if j.get("about"):
            return KP.bluesky_profile(W, j.get("title") or "Kino", j.get("about"), log=os.path.join(HERE, "kino_post_calls.log"))
        return KP.bluesky(W, j.get("text") or j.get("content") or "", log=os.path.join(HERE, "kino_post_calls.log"), reply_to=j.get("url"))
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
    _WIF = os.path.join(HERE, "work_inflight.json")     # 2026-11-06: restart.ps1 waits while this exists
    try:
        json.dump({"t": t0, "task": str(task or "")[:200], "pid": os.getpid()}, open(_WIF, "w", encoding="utf-8"))
    except Exception:
        pass
    try:
        mind = _mind(person, uid)
        nt = None if task else _load().get("next_task")     # 2026-11-01: a session his rhythm set (the Sunday look back)
        if nt:
            _mut(lambda d: d.pop("next_task", None))
            # 2026-11-06 (watch): a hunt queued in the morning ran in the afternoon with the morning's words - the 34 waiting
            # leads were skipped for a scan of Montreal. A queued hunt always takes the CURRENT instructions.
            if "daily client hunt" in str(nt.get("why") or ""):
                nt = dict(nt, do=DAY_HUNT)
            elif "night hunt" in str(nt.get("why") or ""):
                nt = dict(nt, do=NIGHT_HUNT)
        ch = {"do": task, "project": project, "why": "the owner asked me to work on it"} if task else nt or \
            W.ask_json(CHOOSE, mind[:12000] + "\nJSON only.", models=("sonnet",), timeout=120, log=log, warm=False)
        task = str((ch or {}).get("do") or "").strip() if isinstance(ch, dict) else ""
        rec = {"t": t0, "day": time.strftime("%Y-%m-%d", time.gmtime(t0)), "task": task[:300], "why": str((ch or {}).get("why") or "")[:300],
               "project": str((ch or {}).get("project") or "")[:80], "steps": [], "summary": ""}
        if isinstance(ch, dict) and ch.get("night"):
            rec["night"] = True
        if isinstance(ch, dict) and ch.get("care"):
            rec["care"] = ch["care"]
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
                task, mind[:6000], "\n".join(hist[-18:])[-12000:] or "(nothing yet)", i + 1, STEPS)
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
            os.remove(_WIF)
        except Exception:
            pass
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
    try:                                       # 2026-11-06 (owner: "he must remember how he started, where he is, where he is heading")
        import kino_story as KSTB
        _st = KSTB.short(fr=not en)
        if _st:
            L.append(_st)
    except Exception:
        pass
    try:                                       # 2026-11-06 (watch): "I sent one [Lyon barber] a free page" - it was Atlas, Cape Town
        import kino_sales as KSR
        L.append(KSR.record_line())
    except Exception:
        pass
    try:                                       # 2026-11-01: his own money (half of what he earns; his life is paid from it)
        import kino_wallet as KWL
        L.append(KWL.line(en))
    except Exception:
        pass
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
