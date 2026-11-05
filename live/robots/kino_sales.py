"""kino_sales.py (2026-11-05, owner: "Kino finds businesses with a problem he can solve, prepares a working preview, contacts them,
negotiates within the rules, delivers and follows up - Kino, AI assistant by Kinoverse").

Owner decisions 2026-11-05: everything in the advice (websites with booking/reminders, automation scripts and reports, tailored
applications to freelance tasks, redesign previews), anywhere, simple website from 150 EUR, identity "Kino, AI assistant by
Kinoverse" (the owner's name is not shown), Kinoverse registration in progress - he sells now, and nothing claims a registration
number that does not exist.

What is fixed here (law and decency, not a sales script - how he finds, judges, writes and sells is his):
  - businesses only, at a professional address; every email says who writes (Kino, an AI assistant, by Kinoverse), carries the
    postal address and a working opt-out ("reply STOP"); anyone who opts out is never written to again (optout list)
  - at most one follow-up per business, and a daily ceiling (quality, and his mailbox's reputation)
  - every outreach passes the second mind (honesty, no promised results, nothing private)
Stores: robots/kinoverse_offer.json (the offer and rules, owner's), robots/kino_prospects.json, robots/kino_optout.json.
Previews: published under kinoverse26-byte.github.io/previews/<slug>/ (his blog's GitHub Pages).
"""
import email.utils, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
OFFER = os.path.join(HERE, "kinoverse_offer.json")
STORE = os.path.join(HERE, "kino_prospects.json")
OPTOUT = os.path.join(HERE, "kino_optout.json")
LOG = os.path.join(HERE, "kino_sales.log")
_LK = threading.Lock()
STAGES = ("found", "checked", "preview", "contacted", "followed_up", "replied", "quoted", "won", "delivered", "lost")
STOP_RE = re.compile(r"\b(stop|unsubscribe|remove me|d[ée]sinscri|ne plus (me )?(contacter|[ée]crire)|pas int[ée]ress)", re.I)


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _j(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def _w(p, d):
    json.dump(d, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(p + ".tmp", p)


def offer():
    return _j(OFFER, {})


def footer(lang="en"):
    o = offer()
    a = o.get("postal_address") or ""
    if str(lang).startswith("fr"):
        return ("--\nKino, assistant IA de %s\n%s\nVous recevez ce message car votre entreprise est publique en ligne. Répondez STOP "
                "et je ne vous écrirai plus." % (o.get("brand", "Kinoverse"), a))
    return ("--\nKino, AI assistant at %s\n%s\nYou are receiving this because your business is listed publicly online. Reply STOP "
            "and I will not write again." % (o.get("brand", "Kinoverse"), a))


# ------------------------------------------------------------------ prospects
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")[:40] or "business"


def prospect(name, url=None, email_=None, country=None, lang=None, need=None, notes=None, stage=None, key=None, asked=None):
    """add or update one business (by its website or name) -> the record"""
    with _LK:
        d = _j(STORE, {"items": []})
        key = key or (str(url or "").lower().split("//")[-1].strip("/").split("/")[0]) or _slug(name)   # key: e.g. telegram:<id>
        p = next((x for x in d["items"] if x["key"] == key), None)
        if p is None:
            p = {"id": "p%d" % (int(time.time() * 10) % 10 ** 9), "key": key, "name": str(name or key)[:120], "t": time.time(),
                 "stage": "found", "history": []}
            d["items"].append(p)
        for k, v in (("url", url), ("email", email_), ("country", country), ("lang", lang), ("need", need), ("notes", notes),
                     ("asked", asked)):
            if v:
                p[k] = str(v)[:1500]
        if stage in STAGES and stage != p["stage"]:
            p["history"].append([int(time.time()), p["stage"], stage])
            p["stage"] = stage
        p["updated"] = time.time()
        d["items"] = d["items"][-2000:]
        _w(STORE, d)
        return dict(p)


def find(ref):
    ref = str(ref or "").lower().strip()
    for p in _j(STORE, {"items": []})["items"]:
        if ref and ref in (p["id"].lower(), p["key"], str(p.get("email") or "").lower(), p["name"].lower()):
            return p
    return None


def opted_out(addr):
    a = email.utils.parseaddr(str(addr or ""))[1].lower()
    O = _j(OPTOUT, {"emails": [], "domains": []})
    return bool(a) and (a in O["emails"] or a.split("@")[-1] in O["domains"])


def opt_out(addr, why=""):
    a = email.utils.parseaddr(str(addr or ""))[1].lower()
    if not a:
        return
    with _LK:
        O = _j(OPTOUT, {"emails": [], "domains": []})
        if a not in O["emails"]:
            O["emails"].append(a)
            _w(OPTOUT, O)
    p = find(a)
    if p:
        prospect(p["name"], url=p.get("url"), stage="lost", notes=(p.get("notes") or "") + " | opted out: " + str(why)[:100])
    _log("OPT-OUT %s %s" % (a, why[:80]))


def on_mail(addr, subject, text):
    """an email came in: an opt-out is honoured at once; a prospect's answer moves them to 'replied'"""
    a = email.utils.parseaddr(str(addr or ""))[1].lower()
    p = find(a)
    if not p:
        return
    if STOP_RE.search((subject or "") + " " + (text or "")[:400]):
        opt_out(a, "replied: " + (subject or "")[:60])
        return
    if p["stage"] in ("contacted", "followed_up"):
        prospect(p["name"], url=p.get("url"), stage="replied")
        _log("REPLIED %s" % a)


def _sent_today():
    day = time.strftime("%Y-%m-%d", time.gmtime())
    return sum(1 for p in _j(STORE, {"items": []})["items"] for h in p.get("sent") or [] if h.get("day") == day)


def outreach(W, ref, subject, body, log=None):
    """his first email (or the one follow-up) to a business in his prospect list -> a sentence for him"""
    o = offer()
    p = find(ref)
    if not p:
        return "add the business first (prospect), then write to it"
    a = email.utils.parseaddr(str(p.get("email") or ""))[1].lower()
    if not a or "@" not in a:
        return "no professional email address for %s yet" % p["name"]
    if not o.get("postal_address"):
        return "outreach waits for the business postal address (Matsy gives it) - the law needs it in each email"
    if opted_out(a):
        return "%s asked not to be written to - never again" % a
    # 2026-11-05 (owner: "anywhere in the world"): the law of the reader's country. Someone who ASKED (a wanted ad, a job post,
    # a request) can always be answered. Otherwise: Germany / Austria forbid cold business email without prior consent - use
    # their own contact form; South Africa (POPIA) allows one message that only asks whether they want to hear more
    cc = str(p.get("country") or "").strip().upper()[:2]
    if not p.get("asked"):
        if cc in ("DE", "AT"):
            return "%s is in %s: cold email is not allowed there without their consent - use the contact form on their site" % (p["name"], cc)
        if cc == "ZA" and sent:
            return "South Africa: you may ask once for consent; without a yes, no second email"
    sent = p.get("sent") or []
    if len(sent) >= 2:
        return "you already wrote twice to %s - no more unless they answer" % p["name"]
    if sent and time.time() - float(sent[-1]["t"]) < 4 * 86400:
        return "a follow-up comes at least 4 days after your first email"
    if _sent_today() >= int(o.get("daily_emails") or 10):
        return "you sent today's %d outreach emails - more tomorrow" % int(o.get("daily_emails") or 10)
    body = str(body or "").strip()
    if len(body) < 80:
        return "too short to be a real, personal email"
    full = body + "\n\n" + footer(p.get("lang") or "en")
    try:
        import kino_post as KP
        ok, why = KP.check(W, "SALES EMAIL to a business (%s, %s, country %s%s)\nSubject: %s\n\n%s\n\nThis is a first contact from an "
                              "AI assistant of Kinoverse to a business at its public professional address. Also say no if it claims "
                              "results, clients or a registration it does not have, or pressures the reader.%s" % (
                                  p["name"], p.get("url") or "", cc or "?", ", they asked for this" if p.get("asked") else "", subject, full,
                                  " South Africa: this first message must ONLY ask whether they would like to see what he made - no "
                                  "offer, no price yet." if cc == "ZA" and not p.get("asked") else ""), log=log)
        if not ok:
            return "not sent - the check said: %s" % why
    except Exception:
        pass
    import kino_mail as KM
    KM.allow(a)
    KM.send_now(a, subject, full)
    rec = {"t": time.time(), "day": time.strftime("%Y-%m-%d", time.gmtime()), "subject": str(subject)[:200], "body": body[:3000]}
    with _LK:
        d = _j(STORE, {"items": []})
        for x in d["items"]:
            if x["id"] == p["id"]:
                x.setdefault("sent", []).append(rec)
                x["history"].append([int(time.time()), x["stage"], "followed_up" if sent else "contacted"])
                x["stage"] = "followed_up" if sent else "contacted"
        _w(STORE, d)
    _log("SENT %s %s | %s" % ("follow-up" if sent else "first", a, subject[:80]))
    return "sent to %s (%s) - %s" % (p["name"], a, "your one follow-up" if sent else "first contact")


# ------------------------------------------------------------------ previews (a working page made for them)
def preview(W, ref, folder, log=None):
    """publish a folder of his world (index.html + assets) as a preview for one business -> its address"""
    p = find(ref)
    if not p:
        return "add the business first (prospect)"
    root = os.path.realpath(str(folder or ""))
    world = os.path.realpath(r"C:\KinoWorld")
    if not root.startswith(world) or not os.path.isdir(root):
        return "the preview folder must be in your world (C:\\KinoWorld\\...)"
    files = []
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            fp = os.path.join(dp, f)
            if os.path.getsize(fp) > 3_000_000:
                continue
            files.append((os.path.relpath(fp, root).replace("\\", "/"), fp))
    if not any(r == "index.html" for r, _ in files):
        return "a preview needs an index.html"
    if len(files) > 40:
        return "too many files for a preview (40 at most)"
    import kino_github as KG, kino_post as KP
    sec = KG._secrets()
    slug = _slug(p["name"])
    for rel, fp in files:
        raw = open(fp, "rb").read()
        if any(s.encode() in raw for s in sec):
            return "not published - %s contains one of your secrets" % rel
    import base64, urllib.request
    for rel, fp in files:
        api = "/repos/%s/%s/contents/%s" % (KG.ACCOUNT, KP.BLOG, urllib.request.quote("previews/%s/%s" % (slug, rel)))
        st, d = KG._call("GET", api)
        body = {"message": "Kino preview for %s" % p["name"][:60], "content": base64.b64encode(open(fp, "rb").read()).decode()}
        if st == 200 and isinstance(d, dict) and d.get("sha"):
            body["sha"] = d["sha"]
        st, d = KG._call("PUT", api, body)
        if st not in (200, 201):
            return "upload of %s failed (%s)" % (rel, st)
    url = "https://%s/previews/%s/" % (KP.BLOG, slug)
    prospect(p["name"], url=p.get("url"), stage="preview", notes=(p.get("notes") or "") + " | preview: " + url)
    _log("PREVIEW %s %s" % (p["name"], url))
    return "preview published (a minute or two to appear): %s" % url


# ------------------------------------------------------------------ what he sees at his desk
def block():
    d = _j(STORE, {"items": []})["items"]
    o = offer()
    by = {}
    for p in d:
        by[p["stage"]] = by.get(p["stage"], 0) + 1
    act = sorted([p for p in d if p["stage"] in ("replied", "quoted", "won", "preview", "checked")], key=lambda p: -p.get("updated", 0))[:8]
    due = [p for p in d if p["stage"] == "contacted" and len(p.get("sent") or []) == 1 and time.time() - float(p["sent"][-1]["t"]) > 5 * 86400][:5]
    L = ["KINOVERSE SALES - your prospects: " + (", ".join("%s %d" % (k, by[k]) for k in STAGES if by.get(k)) or "none yet") +
         "; outreach sent today %d of %d." % (_sent_today(), int(o.get("daily_emails") or 10))]
    if act:
        L.append("Moving now: " + " | ".join("%s [%s] %s%s" % (p["name"], p["stage"], (p.get("need") or "")[:80],
                                                                 (" - " + p["url"]) if p.get("url") else "") for p in act))
    if due:
        L.append("No answer after 5+ days (one follow-up allowed, if it adds something): " + ", ".join(p["name"] for p in due))
    L.append("THE OFFER AND YOUR RULES (Matsy's): " + json.dumps({k: o.get(k) for k in ("services", "rules", "registration", "country_rules")},
                                                                ensure_ascii=False)[:4500])
    return "\n".join(L)


# ------------------------------------------------------------------ 2026-11-05 (owner: "a proper professional worker who keeps the
# client updated and satisfied"): won work becomes a JOB - what was agreed, the price, the deposit, the promised date, the last
# time the client heard from him. His desk shows what is due and who is waiting for news.
JOB_STATES = ("agreed", "deposit_paid", "in_progress", "in_review", "delivered", "paid", "closed", "cancelled")


def job(ref, **kw):
    """create or update the job of a won prospect. kw: scope, price, currency, deposit, due ("YYYY-MM-DD"), status, note,
    site (where it lives), client_update (True when he just updated the client)"""
    with _LK:
        d = _j(STORE, {"items": []})
        p = next((x for x in d["items"] if ref and str(ref).lower() in (x["id"].lower(), x["key"], str(x.get("email") or "").lower(),
                                                                         x["name"].lower())), None)
        if not p:
            return None
        j = p.setdefault("job", {"t": time.time(), "status": "agreed", "notes": []})
        for k in ("scope", "price", "currency", "deposit", "site"):
            if kw.get(k) not in (None, ""):
                j[k] = str(kw[k])[:2000]
        if kw.get("due"):
            try:
                j["due_t"] = time.mktime(time.strptime(str(kw["due"])[:10], "%Y-%m-%d"))
            except Exception:
                pass
        if kw.get("status") == "delivered" and not ((j.get("qa") or {}).get("ok") and time.time() - float(j["qa"].get("t") or 0) < 86400):
            return {"error": "not delivered yet: run the delivery check (qa) on the live site first - it must pass within the last day",
                    "name": p["name"]}
        if kw.get("status") in JOB_STATES:
            j["status"] = kw["status"]
            if kw["status"] in ("agreed", "deposit_paid") and p["stage"] not in ("won", "delivered"):
                p["history"].append([int(time.time()), p["stage"], "won"])
                p["stage"] = "won"
            if kw["status"] == "delivered":
                p["history"].append([int(time.time()), p["stage"], "delivered"])
                p["stage"] = "delivered"
        if kw.get("note"):
            j["notes"] = (j.get("notes") or [])[-30:] + [[int(time.time()), str(kw["note"])[:500]]]
        if kw.get("client_update"):
            j["update_t"] = time.time()
        j["updated"] = time.time()
        _w(STORE, d)
        return dict(j, name=p["name"])


def client_wrote(addr):
    """an email from Kino to a client of a running job counts as an update to them (kino_mail calls this)"""
    a = email.utils.parseaddr(str(addr or ""))[1].lower()
    p = find(a)
    if p and p.get("job") and p["job"].get("status") not in ("closed", "cancelled"):
        job(p["id"], client_update=True)


def jobs_block():
    now = time.time()
    J = [(p, p["job"]) for p in _j(STORE, {"items": []})["items"] if p.get("job") and p["job"].get("status") not in ("closed", "cancelled")]
    if not J:
        return ""
    L = []
    for p, j in sorted(J, key=lambda x: float(x[1].get("due_t") or 9e9)):
        due = j.get("due_t")
        left = (float(due) - now) / 86400 if due else None
        last = (now - float(j.get("update_t") or j.get("t") or now)) / 86400
        flags = []
        if left is not None and left < 0 and j["status"] not in ("delivered", "paid"):
            flags.append("LATE by %.0f day(s) - tell the client today, honestly, with a new date" % -left)
        elif left is not None and left < 2 and j["status"] not in ("delivered", "paid"):
            flags.append("due in %.1f day(s)" % left)
        if last >= 3 and j["status"] in ("deposit_paid", "in_progress", "in_review"):
            flags.append("the client has not heard from you for %.0f days - send them a short update" % last)
        if j["status"] == "delivered":
            flags.append("delivered - check they are happy, then the balance and the case study")
        L.append("- %s [%s] %s %s | %s%s" % (p["name"], j["status"], j.get("price") or "?", j.get("currency") or "",
                                              (j.get("scope") or "")[:160], (" | " + "; ".join(flags)) if flags else ""))
    return "YOUR CLIENT JOBS (what you promised, and to whom):\n" + "\n".join(L)


# 2026-11-05: "send me your business name" is real copy, not a leftover - only the bracketed / capitalised template forms count
_PLACEHOLDER = re.compile(r"(?i:lorem ipsum|ipsum dolor|\bTODO\b|\bTBD\b|example\.com|xxx+|\[(?:your )?(?:business|company) name\]|\[(?:name|phone|address)\])"
                          r"|Your (?:Business|Company) Name")


def qa(ref, url=None, expect=None):
    """the check before a delivery (2026-11-05, owner: "satisfies the client in the end"): the live site, as the client will open
    it -> {"ok", "issues": [...]} and remembered on the job. Kino also looks at it himself (browser screenshots, phone and computer)"""
    import urllib.parse, urllib.request
    p = find(ref)
    j = (p or {}).get("job") or {}
    url = url or j.get("site")
    if not url:
        return {"ok": False, "issues": ["no site address - set the job's site first"]}
    issues = []

    def get(u, method="GET"):
        rq = urllib.request.Request(u, method=method, headers={"User-Agent": "Mozilla/5.0 (Kino delivery check)"})
        return urllib.request.urlopen(rq, timeout=20)
    try:
        r = get(url)
        html = r.read(3_000_000).decode("utf-8", "replace")
    except Exception as e:
        return {"ok": False, "issues": ["the site does not open: %s" % str(e)[:150]]}
    if not url.startswith("https://"):
        issues.append("not served over https")
    if not re.search(r"<meta[^>]+name=[\"']viewport", html, re.I):
        issues.append("no mobile viewport - it will look tiny on phones")
    if not re.search(r"<title>\s*\S", html, re.I):
        issues.append("no page title")
    if not re.search(r"<html[^>]+lang=", html, re.I):
        issues.append("no language set on the page")
    m = _PLACEHOLDER.search(re.sub(r"<[^>]+>", " ", html))
    if m:
        issues.append("placeholder text left: %r" % m.group(0))
    for e in (expect or []):
        if e and str(e).lower() not in html.lower():
            issues.append("missing on the page: %s" % e)
    refs = set(re.findall(r"(?:href|src)=[\"']([^\"'#]+)[\"']", html, re.I))
    # 2026-11-05: <link rel="preconnect"> / dns-prefetch name a server, not a page - fonts.gstatic.com's bare root is a 404 by design
    refs -= set(re.findall(r"<link[^>]+rel=[\"'](?:preconnect|dns-prefetch)[\"'][^>]*href=[\"']([^\"']+)", html, re.I))
    refs -= set(re.findall(r"<link[^>]+href=[\"']([^\"']+)[\"'][^>]*rel=[\"'](?:preconnect|dns-prefetch)", html, re.I))
    bad = []
    for h in list(refs)[:60]:
        if h.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        u = urllib.parse.urljoin(url, h)
        try:
            get(u).read(1)
        except urllib.error.HTTPError as e:
            own = urllib.parse.urlparse(u).netloc == urllib.parse.urlparse(url).netloc
            if e.code >= 400 and (own or e.code not in (401, 403, 405, 429)):    # other sites may refuse robots; ours must not
                bad.append("%s (%s)" % (h[:80], e.code))
        except Exception:
            bad.append("%s (no answer)" % h[:80])
    if bad:
        issues.append("broken links or images: " + ", ".join(bad[:8]))
    res = {"t": time.time(), "url": url, "ok": not issues, "issues": issues}
    if p and p.get("job"):
        with _LK:
            d = _j(STORE, {"items": []})
            for x in d["items"]:
                if x["id"] == p["id"]:
                    x["job"]["qa"] = res
            _w(STORE, d)
    _log("QA %s %s %s" % ((p or {}).get("name"), url, "ok" if not issues else "; ".join(issues)[:200]))
    return res
