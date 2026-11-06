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
WLOG = os.path.join(HERE, "kino_work.log")
BLOG = os.path.join(HERE, "kino_build.log")      # building (designer, seo, qa, hunter, billing): the owner's budget          # their thinking is paid from his work budget (kino_wallet OWN_TAGS)
TEAMDIR = r"C:\KinoWorld\team"
_LK = threading.Lock()
MAX_LIVE = 2                    # at most two at work at once (each step is one AI call)
DAY_MAX = 12                    # briefs a day
MIN_LEFT = 0.4                  # $ of his day's budget that must be left to start one

COMMON = """You work for Kino (an AI who runs Kinoverse: he makes websites and small tools for small businesses at low launch prices, and
looks after OwlNest, a trading app). You are one of his TEAM, a specialist behind him. Kino is the only one who speaks to people:
you never email, post, message or contact anyone - you find, build, check or draft, and you REPORT to him. Your files go in
C:\\KinoWorld\\team\\%s\\ (write paths like team/%s/...; relative paths start in C:\\KinoWorld\\home, so use the full path
C:\\KinoWorld\\team\\%s\\file). Never invent: a fact you did not see is "not checked".

Answer ONE JSON object per step and nothing else:
{"thought": "one short sentence", "action": "%s|done", ...fields of that action...,
 "text": "done: YOUR REPORT to Kino - what you did, what you found (with the exact names/addresses/links), what is not checked,
          and what you suggest he does next. Plain, short, complete."}
A long file (code, a page) goes BELOW the JSON between a line ===FILE=== and a line ===END=== (write).
FIELD NAMES (06/11: a designer sent six "run" with no command): run {"cmd": "a PowerShell command"}, read/write {"path"},
fetch/audit/images {"url"}, scan {"place", "kind"}, search/xsearch/photos {"q"}, download {"url", "path"}, find {"place", "kind", "with_site"},
prospect {"name", "url", "email", "country", "lang", "need", "notes", "stage"}, preview/qa/job {"who"} (qa also "url"),
deploy {"who", "path"}, invoice {"amount", "what"}, tool_run {"name", "args"}.
ACTIONS YOU HAVE:
%s"""

ROLES = {
    "hunter": {
        "steps": 14,
        "actions": ["scan", "find", "audit", "search", "fetch", "xsearch", "prospect", "read", "write", "tool_run"],
        "what": "finds real small businesses that need what Kinoverse makes, and checks them",
        "how": """You are the HUNTER. Start with scan ("place", "kind"): a whole city audited at once - the weak sites with their email and the
no-website businesses that show an email. Then (or for more): find real businesses (find = OpenStreetMap: "place" a city/district, "kind" e.g.
barber|restaurant|plumber..., "with_site": true for those WITH a website), then audit ("url") their sites - a weakness score
4+ with an email found = the best lead (no-website businesses rarely show an email; Kino cannot phone). Check the best 2-3 on their own public page
(fetch a Facebook/Google/listing page; search with SHORT words), and record each CHECKED one with prospect ("name", "url",
"email" public business address only, "country" a 2-letter code, "lang", "need" what you noticed, "stage" found|checked,
"notes" what you verified and where). Read Kino's playbook first: C:\\KinoWorld\\projects\\kinoverse\\playbook.md.
search ("q"), fetch ("url"), xsearch ("q") find conversations on X, read ("path"), write ("path" + content), tool_run ("name",
"args") Kino's approved internet tools. No private individuals - businesses only.""",
    },
    "designer": {
        "steps": 24,
        "actions": ["read", "write", "run", "fetch", "images", "photos", "download", "preview", "qa", "deploy"],
        "what": "builds a premium, production-looking preview site (and app version) for one business",
        "how": """You are the DESIGNER - the standard is a top agency's finished work, not a template. Matsy (the owner), 06/11:
"premium and modern website/app ... the best preview as if it was the final production, with images and all".
You build ONE preview for the business in the brief, AS IF IT WERE THEIR LIVE SITE:
- THEIR real name, logo (or a refined wordmark), colours from their brand, services, prices and hours if public (else "on
  request"/"to confirm"), address, phone, language. Never invent reviews, awards or facts.
- REAL IMAGES, at least 6: THEIR OWN photos first - if they have a site, images ("url" their site) lists the photos on it:
  download the best ones (their salon, their team, their work); also their Facebook/Instagram/Google page. A business with
  a site ALWAYS gets its own photos (06/11: the Brevi preview showed an Asian street barber with a Pepsi sign instead); then photos ("q" short English words, e.g. "barber fade", "barbershop interior") gives free-licence photos -
  download ("url", "path" into the preview folder, e.g. C:\\KinoWorld\\projects\\previews\\<slug>\\img\\hero.jpg) and use them.
  Credit non-CC0 photos in the footer.
- Modern design: a full-bleed hero photo with a strong headline and one clear call to action, Google Fonts (a display font
  + a clean body font), a refined palette, generous spacing, smooth scroll, subtle reveal animations, cards with hover,
  a gallery, services with prices, hours + map (an OpenStreetMap or Google Maps embed of their address), booking/contact,
  a sticky mobile call/WhatsApp button, a proper footer. Perfect on a phone first. At least 5 <section>s.
- APP VERSION: a manifest.json + app icon (a simple SVG/PNG of their initials) + theme colour so it installs on a phone
  ("Add to home screen"); a small "Install the app" button. Kino may offer it as an option.
- A small discreet ribbon: "Preview made for <name> by Kinoverse - not live yet".
Build in C:\\KinoWorld\\projects\\previews\\<slug>\\ (index.html + img\\ + manifest.json). Write index.html in ONE write
(the whole page below ===FILE===). Then qa it, fix what it says, then preview ("who" the prospect, "path" the folder) - it
refuses a page that is still bare. Report the address and what you used (photos and their source).
For KINO'S OWN portfolio site (when the brief says so): edit its folder and publish it with deploy ("who" "kinoverse", "path" the folder), then qa ("url" its address).""",
    },
    "billing": {
        "steps": 10,
        "actions": ["job", "invoice", "read", "write"],
        "what": "quotes, payment links, invoices and who has paid",
        "how": """You are BILLING. From the brief: write a clear quote for the client (what is included, the price from THE
OFFER, delivery time, the deposit - usually half - and what happens after delivery) as a file in C:\\KinoWorld\\team\\billing\\,
create the payment link with invoice ("amount" in dollars, "what" it is for - a crypto payment link on Kinoverse's account;
PayPal only through Kino), update the job with job ("who" the client, and its status: deposit_paid / paid when Kino tells you
they paid), and keep C:\\KinoWorld\\team\\billing\\ledger.md up to date (date, client, what, amount, status). Never invent a
payment: 'paid' only when the brief says it arrived. Report the quote text and the link for Kino to send.""",
    },
    "seo": {
        "steps": 12,
        "actions": ["read", "write", "run", "fetch", "audit", "qa"],
        "what": "makes a client's site findable on Google",
        "how": """You are SEO. For the site in the brief (a folder in C:\\KinoWorld\\projects\\... and its live address): make it
findable - a precise <title> and meta description with their trade + city, one clear <h1>, alt texts, Open Graph tags,
LocalBusiness JSON-LD with their REAL name, address, phone and hours (only what is known), a sitemap.xml and robots.txt,
fast images, internal links, their language in <html lang>. Edit the files in place (write), then qa. Report what you
changed and what the CLIENT should do (claim their Google Business Profile, add the site link there and on Facebook) -
Kino tells them; you never contact anyone.""",
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
        if role == "writer":                   # 2026-11-06 (owner): words for clients and the public on the API; building on the subscription
            with W.api_scope():
                raw = W.ask_text(_system(role), ctx, model="sonnet", timeout=180, log=log, warm=False) or ""
        else:
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


BUILD = """You are a top web designer and front-end developer (the level of the best agencies). You write ONE complete, production-
quality HTML page for a small business: the client must open it and feel it is their finished, premium site.
Rules: their REAL facts only (from the brief and the notes) - never invent reviews, awards, prices or hours ("on request" /
"call to book" instead); use ONLY the image files listed as downloaded (relative paths like img/hero.jpg), each where it fits
best (the sharpest, most striking one as the hero; the business's OWN photos always before stock) - a stock photo only
if it fits THEIR world (their country, their kind of place, modern and clean - not a street stall for a city salon) - and
NEVER a photo showing another business's name, sign, logo or a brand (Pepsi, Coca-Cola...)
(06/11: a 'Daddy Joe barbing saloon' sign ended up in Atlas's gallery), and alt texts only claim what the photo really is;
the business name as logo text is written plainly (no letter split into a span); the header must fit on a 360 px phone WITH every
button visible - the "Install the app" button appears only on Android, so let the header wrap (06/11: Appeler was cut off on
the owner's phone); image addresses carry a version (img/hero.jpg?v=1) so a rebuilt preview never shows old cached photos; inline CSS + a little vanilla JS, Google Fonts allowed; mobile-first and
flawless on a phone; a full-bleed hero with a strong, specific headline (about THEM, their street, their city - not a generic
slogan), clear calls to action (call / WhatsApp / booking), at least 5 <section>s (about, services, gallery, hours + map embed
of their address, contact), refined palette from their brand, generous spacing, subtle reveal animation that never hides content
if JS fails, sticky mobile call bar, accessible contrast, alt texts, meta description, Open Graph tags, a manifest link and
theme colour if a manifest exists, the discreet ribbon "Preview made for <name> by Kinoverse - not live yet", and photo credits
in the footer for any non-CC0 photo. Answer with the complete HTML document only, from <!doctype html> to </html>."""


def _build(W, brief, hist, path, draft, log):
    """2026-11-06 (owner: "premium ... the best possible"): the page itself is written by the strongest model, from everything
    the designer gathered; its cheaper steps only do the gathering"""
    try:
        raw = W.ask_text(BUILD, "THE BRIEF:\n%s\n\nWHAT THE DESIGNER GATHERED (facts, photos downloaded, notes):\n%s\n\nTHE DESIGNER'S "
                                "DRAFT (improve on it freely - keep its true facts and its image files):\n%s\n\nWrite the complete page "
                                "for %s now." % (brief, "\n".join(hist)[-14000:], str(draft)[:16000], path),
                         model="opus", timeout=420, log=log, warm=False) or ""
        m = re.search(r"<!doctype html.*?</html>", raw, re.S | re.I)
        if m and len(m.group(0)) > 6000:
            _log("BUILD opus %d chars for %s" % (len(m.group(0)), path))
            return m.group(0)
        _log("BUILD opus gave no full page for %s" % path)
    except Exception as e:
        _log("BUILD-ERR %s" % e)
    return None


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
                    if role == "designer" and p.lower().endswith(".html"):
                        j["content"] = _build(W, brief, hist, p, j.get("content") or "", log) or j.get("content")
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
        if role == "writer" and al["day"] and al["left"] < MIN_LEFT:      # builders are on the owner's budget
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
    # 2026-11-06 (owner: "the building of anything on my personal budget for now; later Kino pays himself"): the builders'
    # thinking is logged apart (kino_build.log is not one of his wallet tags) - only the writer, who talks for him, is his
    if role != "writer" and log == WLOG:
        log = BLOG
    threading.Thread(target=_work, args=(W, rid, role, brief, log), daemon=True, name="kino-team-" + role).start()
    _log("START %s %s | %s" % (rid, role, brief[:300].replace("\n", " ")))
    return "your %s started on it (id %s, up to %d steps). The report comes into YOUR TEAM - go on with something else." % (
        role, rid, ROLES[role]["steps"])


_AUTO = {"t": 0.0}
AUTO_DAY = 10                   # previews built a day by the queue (the owner's subscription carries them - kept reasonable)


def auto_previews(W):
    """2026-11-06 (owner: "the building of anything on my personal budget - build now"): every lead waiting on his desk with an
    email gets its premium preview built before he writes, one at a time, in the background. Called often by the app; acts
    at most every 10 minutes, never when a designer is already at work."""
    now = time.time()
    if now - _AUTO["t"] < 600:
        return None
    _AUTO["t"] = now
    d = _load()
    R = d.get("runs") or []
    if any(x.get("status") == "working" and x["role"] == "designer" and now - x["t"] < 3 * 3600 for x in R):
        return None
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if sum(1 for x in R if x.get("day") == day and x["role"] == "designer" and "[auto]" in x.get("brief", "")) >= AUTO_DAY:
        return None
    try:
        import kino_sales as KS
        P = KS._j(KS.STORE, {"items": []})["items"]
    except Exception:
        return None
    tried = {x.get("lead") for x in R if x.get("lead")}
    cand = [p for p in P if p["stage"] in ("found", "checked") and p.get("email") and not p.get("preview") and not p.get("sent")
            and p["id"] not in tried]
    if not cand:
        return None
    cand.sort(key=lambda p: ("weak site" not in str(p.get("need") or ""), -float(p.get("updated") or 0)))
    p = cand[0]
    brief = ("[auto] Build the premium preview for the prospect '%s' (%s, %s). What we know (verified by the scan - use ONLY true "
             "facts, 'on request' / 'to confirm' for the rest): %s. Notes: %s. Their site if any: %s. Language: %s. Find their own "
             "photos or details on their public pages if you can (fetch), else fitting free-licence photos. Build it as their "
             "finished site, app version included, qa it, then publish with preview (who '%s'). Report the address." % (
                 p["name"], p.get("country") or "?", p.get("lang") or "?", p.get("need") or "", (p.get("notes") or "")[:300],
                 p.get("url") or "none", p.get("lang") or "fr", p["name"]))
    r = delegate(W, "designer", brief, log=BLOG)
    if r.startswith("your designer started"):
        rid = re.search(r"id (\w+)", r)

        def f(dd):
            for x in dd.get("runs") or []:
                if rid and x["id"] == rid.group(1):
                    x["lead"] = p["id"]
        _mut(f)
    _log("AUTO-PREVIEW %s | %s" % (p["name"], r[:120]))
    return r


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
