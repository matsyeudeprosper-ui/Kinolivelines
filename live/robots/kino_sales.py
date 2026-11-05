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


def prospect(name, url=None, email_=None, country=None, lang=None, need=None, notes=None, stage=None):
    """add or update one business (by its website or name) -> the record"""
    with _LK:
        d = _j(STORE, {"items": []})
        key = (str(url or "").lower().split("//")[-1].strip("/").split("/")[0]) or _slug(name)
        p = next((x for x in d["items"] if x["key"] == key), None)
        if p is None:
            p = {"id": "p%d" % (int(time.time() * 10) % 10 ** 9), "key": key, "name": str(name or key)[:120], "t": time.time(),
                 "stage": "found", "history": []}
            d["items"].append(p)
        for k, v in (("url", url), ("email", email_), ("country", country), ("lang", lang), ("need", need), ("notes", notes)):
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
        ok, why = KP.check(W, "SALES EMAIL to a business (%s, %s)\nSubject: %s\n\n%s\n\nThis is a first contact from an AI assistant of "
                              "Kinoverse to a business at its public professional address. Also say no if it claims results, clients or "
                              "a registration it does not have, or pressures the reader." % (p["name"], p.get("url") or "", subject, full), log=log)
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
    L.append("THE OFFER AND YOUR RULES (Matsy's): " + json.dumps({k: o.get(k) for k in ("services", "rules", "registration")}, ensure_ascii=False)[:2500])
    return "\n".join(L)
