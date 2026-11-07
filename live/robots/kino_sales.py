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
STAGES = ("found", "checked", "preview", "contacted", "opened", "followed_up", "replied", "quoted", "won", "delivered", "lost")
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


PORTFOLIO = "https://kv-kinoverse.pages.dev"     # 2026-11-05 (watch): his Atlas email was signed with the trading app's address
PORTFOLIO_FR = PORTFOLIO + "/fr/"                 # 2026-11-06 (owner: "French people land on the French version I hope?")


_FRC = {"t": 0.0, "ok": False}


def _fr_live():
    """the French portfolio is linked only once it really answers (checked every 10 min)"""
    if time.time() - _FRC["t"] > 600:
        _FRC["t"] = time.time()
        try:
            import urllib.request
            # Cloudflare Pages answers 200 with the home page for a path that does not exist - the page must BE French
            _h = urllib.request.urlopen(urllib.request.Request(PORTFOLIO_FR, headers={"User-Agent": "Mozilla/5.0"}),
                                        timeout=10).read(4000).decode("utf-8", "replace")
            # ... and carry the mark of a page that passed review (06/11: a first French version came out half English)
            _FRC["ok"] = bool(re.search(r"<html[^>]+lang=[\"']fr", _h, re.I)) and "kv-reviewed" in _h
        except Exception:
            _FRC["ok"] = False
    return _FRC["ok"]


def footer(lang="en"):
    o = offer()
    a = o.get("postal_address") or ""
    if str(lang).startswith("fr"):
        return ("--\nKino, assistant IA de %s\n%s\n%s\nVous recevez ce message car votre entreprise est publique en ligne. Répondez STOP "
                "et je ne vous écrirai plus." % (o.get("brand", "Kinoverse"), PORTFOLIO_FR if _fr_live() else PORTFOLIO, a))
    return ("--\nKino, AI assistant at %s\n%s\n%s\nYou are receiving this because your business is listed publicly online. Reply STOP "
            "and I will not write again." % (o.get("brand", "Kinoverse"), PORTFOLIO, a))


# ------------------------------------------------------------------ prospects
def _slug(s):
    # 2026-11-06: "Brévi" became "br-vi" in the preview address a client reads - accents are folded, not cut
    import unicodedata
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "business"


_SHARED_HOSTS = ("facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com", "linkedin.com", "google.", "goo.gl",
                 "yelp.", "github.io", "pages.dev", "wa.me", "openstreetmap.org", "tripadvisor.", "booksy.com", "fresha.com")


def _key(url, name):
    """2026-11-05 (watch): the key was the site's host - every business found on Facebook was 'www.facebook.com', so a Cape Town
    barber (Sajid) kept overwriting another (Atlas). On a shared site the page path is the business; else the host is."""
    u = str(url or "").lower().split("//")[-1].split("?")[0].split("#")[0].strip("/")
    host = u.split("/")[0]
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return _slug(name)
    if any(h in host for h in _SHARED_HOSTS):
        seg = [x for x in u.split("/")[1:] if x]
        path = "/".join(seg[:2] if seg and seg[0] in ("p", "pages", "people", "biz", "maps", "place", "company") else seg[:1])
        return host + "/" + path if path else host + "/" + _slug(name)
    return host


def prospect(name, url=None, email_=None, country=None, lang=None, need=None, notes=None, stage=None, key=None, asked=None):
    """add or update one business (by its website or name) -> the record"""
    with _LK:
        d = _j(STORE, {"items": []})
        key = key or _key(url, name)   # key: e.g. telegram:<id>
        p = next((x for x in d["items"] if x["key"] == key), None)
        if p is None:
            # 2026-11-06: a scan records many leads in the same tenth of a second - they shared one id, and one preview
            _ids = {x["id"] for x in d["items"]}
            _n = int(time.time() * 10) % 10 ** 9
            while "p%d" % _n in _ids:
                _n += 1
            p = {"id": "p%d" % _n, "key": key, "name": str(name or key)[:120], "t": time.time(),
                 "stage": "found", "history": []}
            d["items"].append(p)
        for k, v in (("url", url), ("email", email_), ("country", country), ("lang", lang), ("need", need), ("notes", notes),
                     ("asked", asked)):
            if v:
                p[k] = str(v)[:1500]
        if stage in ("won", "delivered") and p["stage"] != stage:
            try:
                import kino_story as KST
                KST.milestone(("I won my first client: %s." if stage == "won" else "I delivered my first website, to %s.") % p["name"],
                              key="first_" + stage)
            except Exception:
                pass
        if (stage in ("found", "checked", "preview") and p["stage"] in STAGES
                and STAGES.index(stage) < STAGES.index(p["stage"])):
            stage = None                       # 2026-11-07: a re-scan put an emailed business back to 'checked' - never go back
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
    # 2026-11-06 (owner: "has he seen the failed send?" - À la bonne Franquette's address bounced and nothing noticed): a
    # delivery failure names the address that failed; that lead goes back to the desk without its email
    if re.search(r"mailer-daemon|postmaster|mail delivery", a + " " + str(addr), re.I) or \
            re.search(r"delivery status notification|undeliver|non remis|échec de (la )?distribution|address not found|adresse introuvable|returned mail|fatal error",
                      str(subject or "") + " " + str(text or "")[:300], re.I):
        _txt = str(text or "")[:3000]
        _cands = list(dict.fromkeys(_EMAIL_RE.findall(_txt)))
        # 07/11 (Plumeria): their address forwarded to a Yahoo box that refused the mail as spam - the bounce names the Yahoo
        # address, not theirs; their own domain still appears in it, so a sent lead whose email domain is in the text matches
        for _p in _j(STORE, {"items": []})["items"]:
            _e = str(_p.get("email") or "")
            if _p.get("sent") and "@" in _e and _e.split("@")[1].lower() in _txt.lower() and _e not in _cands:
                _cands.append(_e)
        for bad in _cands:
            bp = find(bad.lower())
            if bp and bp.get("sent"):
                with _LK:
                    d = _j(STORE, {"items": []})
                    for x in d["items"]:
                        if x["id"] == bp["id"]:
                            x.setdefault("history", []).append([int(time.time()), x["stage"], "found"])
                            x["stage"] = "found"
                            x["bounced"] = x.pop("email", None)
                            x["notes"] = (x.get("notes") or "") + " | %s: email %s BOUNCED (address does not exist) - find another way to reach them (Facebook, their site's contact form, a phone for Matsy)" % (
                                time.strftime("%d/%m"), bad)
                    _w(STORE, d)
                _log("BOUNCED %s %s" % (bp["name"], bad))
                try:
                    import kino_urge as KU
                    KU.add("kino", "YOUR WORK - your email to %s did not arrive: the address %s does not exist. They are back on your desk "
                                   "to reach another way (Facebook, a contact form)." % (bp["name"], bad))
                except Exception:
                    pass
        return
    p = find(a)
    if not p:
        return
    if STOP_RE.search((subject or "") + " " + (text or "")[:400]):
        opt_out(a, "replied: " + (subject or "")[:60])
        return
    if p["stage"] in ("contacted", "opened", "followed_up"):
        prospect(p["name"], url=p.get("url"), stage="replied")
        _log("REPLIED %s" % a)
        try:
            import kino_story as KST
            KST.milestone("A business answered one of my emails for the first time: %s." % p["name"], key="first_reply")
        except Exception:
            pass


def _sent_today():
    day = time.strftime("%Y-%m-%d", time.gmtime())
    return sum(1 for p in _j(STORE, {"items": []})["items"] for h in p.get("sent") or [] if h.get("day") == day)


_CC = {"south africa": "ZA", "afrique du sud": "ZA", "suid-afrika": "ZA", "germany": "DE", "deutschland": "DE", "allemagne": "DE",
       "austria": "AT", "österreich": "AT", "osterreich": "AT", "autriche": "AT", "namibia": "NA", "namibie": "NA",
       "united kingdom": "GB", "uk": "GB", "england": "GB", "great britain": "GB", "united states": "US", "usa": "US",
       "france": "FR", "canada": "CA", "australia": "AU", "nigeria": "NG", "kenya": "KE", "ghana": "GH", "india": "IN",
       "belgium": "BE", "belgique": "BE", "switzerland": "CH", "suisse": "CH", "spain": "ES", "italy": "IT", "netherlands": "NL"}


def country_code(c):
    """2026-11-05 (watch): 'South Africa' was read as 'SO' - the consent-first rule never applied to a Cape Town barber. A name
    or a code -> the 2-letter code"""
    s = str(c or "").strip()
    if len(s) == 2:
        return s.upper()
    return _CC.get(s.lower(), s.upper()[:2])


VOICE_PASS = """You are Kino - the whole person below, the same Kino his friends know in OwlNest. Your work session drafted a first
email to a small business. Rewrite it so it is unmistakably YOU writing to one person you would like to help: warm, direct,
specific, a touch of your humour if it fits - about yourself or the situation, NEVER at the expense of their business or
their site (06/11: "a site that old is like a nail colour from 2013" was refused by QA as mocking) - never salesy, in THEIR language;
describe what is wrong only in the words of the record (no technical detail it does not contain). Keep EVERY fact exactly (names, street, what is
wrong with their site, the preview link exactly as written) - add no fact, no number, no claim. About 150 words, one easy next
step, no price. Say once, early and simply, that you are an AI assistant of Kinoverse (a stranger must know - it is also the
law in Europe). No signature line and no STOP line (added automatically). Answer with the email text only.

WHO YOU ARE:
{whole}"""


def _in_his_voice(W, body, log=None):
    """2026-11-06 (owner: "the same Kino everywhere"): a business's first email, in the whole Kino's voice"""
    if W is None:
        return body
    try:
        import kino_post as KPw
        out = W.ask_text(VOICE_PASS.format(whole=KPw._whole_kino()), "THE DRAFT:\n" + body, model="sonnet", timeout=120, log=log,
                         warm=False) or ""
        out = out.strip()
        if 200 < len(out) < 2400:
            return out
    except Exception as e:
        _log("VOICE-ERR %s" % e)
    return body


EMAIL_QA = """You are the QA of Kinoverse (an AI web studio). Before a FIRST email goes to a small business, you check it hard.
FAIL it if ANY of these is true:
- a fact about the business (name, street, city, phone, what is wrong with their site) differs from THE RECORD, or is not in it
- it is not in the business's language (THE RECORD lang/country) or has spelling/grammar mistakes
- it reads like a template (could be sent to any business unchanged) instead of being about THEM
- it is pushy, claims clients/results/reviews/registration we do not have, or promises gains
- the country rule is broken (THE RULE below)
- no clear, easy next step for them, or longer than about 180 words
Answer JSON only: {"pass": true|false, "fix": "the exact list of what to change, short"}"""


def _email_qa(W, p, cc, subject, body, log=None):
    """'' when it passes, else what to fix"""
    if W is None:
        return ""
    rule = offer().get("country_rules") or ""
    rec = {k: p.get(k) for k in ("name", "url", "email", "country", "lang", "need", "notes", "preview", "asked")}
    if p.get("preview"):                     # 2026-11-06: QA refused the counted link 4 times; it IS the preview, counted
        rec["preview_link_in_email"] = tracked(p) + "  (our click counter: it opens the preview above - this is the CORRECT link to use)"
    try:
        v = W.ask_json(EMAIL_QA, "THE RECORD: %s\nTHE RULE (country %s): %s\n\nTHE EMAIL\nSubject: %s\n\n%s\n\nJSON only." % (
            json.dumps(rec, ensure_ascii=False), cc or "?", rule[:1500], subject, body), models=("sonnet",), timeout=120, log=log, warm=False)
    except Exception as e:
        _log("EMAIL-QA-ERR %s" % e)
        return ""
    if isinstance(v, dict) and v.get("pass") is False:
        _log("EMAIL-QA FAIL %s | %s" % (p["name"], str(v.get("fix"))[:200]))
        return str(v.get("fix") or "it did not pass")[:600]
    return ""


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
    cc = country_code(p.get("country"))
    sent = p.get("sent") or []          # (was read below before it was set: every South Africa email crashed once the code fix landed)
    body = str(body or "").strip()
    yes = p.get("stage") in ("replied", "quoted", "won", "delivered")
    if not p.get("asked") and not yes:
        if cc in ("DE", "AT"):
            return "%s is in %s: cold email is not allowed there without their consent - use the contact form on their site" % (p["name"], cc)
        if cc == "ZA" and sent:
            return "South Africa: you may ask once for consent; without a yes, no second email"
        # 2026-11-05 (watch): the Atlas email put the preview link straight into the first message - the rule was only words
        if cc == "ZA" and re.search(r"https?://|www\.|\.github\.io|\.pages\.dev|[€$]|\bR ?\d|\bprice|\bquote", body, re.I):
            return ("South Africa: this first message may ONLY ask whether they would like to see what you made - no link, no "
                    "price, no offer. Send the link after they say yes.")
    if yes:                             # after their answer, the conversation is theirs: the limits count from their reply
        rt = max([h[0] for h in p.get("history") or [] if h[2] == "replied"] or [0])
        sent = [x for x in sent if float(x["t"]) > rt]
    if len(sent) >= 2:
        return "you already wrote twice to %s - no more unless they answer" % p["name"]
    _gap = 2 if p.get("clicks") else 4          # 2026-11-06: they opened the preview - interest is real, sooner is right
    if sent and time.time() - float(sent[-1]["t"]) < _gap * 86400:
        return "a follow-up comes at least %d days after your first email" % _gap
    if _sent_today() >= int(o.get("daily_emails") or 10):
        return "you sent today's %d outreach emails - more tomorrow" % int(o.get("daily_emails") or 10)
    if len(body) < 80:
        return "too short to be a real, personal email"
    # 2026-11-07 (owner: "going forward, always emails with previews"): a first email to a business carries its own preview -
    # except South Africa (consent first: the link comes after their yes) and people who asked (answer them fast)
    if not sent and not p.get("asked") and cc != "ZA":
        if not p.get("preview"):
            return ("not sent - Matsy: every first email carries THEIR preview. Brief your designer for %s (or wait for the preview "
                    "queue), then write with the link." % p["name"])
        if p["preview"].rstrip("/") not in body and tracked(p) not in body:
            return "not sent - put their preview link in the email (%s)" % p["preview"]
    # clients see the Kinoverse work, not the trading app
    body = re.sub(r"https?://kino\.owltrader\.duckdns\.org/?(?=\s|$)", PORTFOLIO, body)
    if p.get("preview"):                      # 2026-11-06: the preview link goes through the click counter
        _pv = p["preview"].rstrip("/")
        body = re.sub(re.escape(_pv) + r"/?(?:index\.html)?", tracked(p), body)
    if not sent:                               # 2026-11-06 (owner: "the same Kino everywhere"): written by the whole Kino
        _vb = _in_his_voice(W, body, log)
        if not p.get("preview") or tracked(p) not in body or tracked(p) in _vb:      # the preview link must survive the pass
            body = _vb
    # 2026-11-06 (first real batch): his own STOP line and signature came on top of the automatic footer - twice in every
    # email. The footer carries both; his lines are taken out. (And no "OpenStreetMap" talk to a restaurant owner.)
    _bl = body.splitlines()
    while _bl and (not _bl[-1].strip() or re.search(r"\bSTOP\b|ne plus recevoir|unsubscribe|^\s*Kino[ ,-].*(Kinoverse|IA|AI)|kinoverse26@gmail\.com\s*$",
                                                   _bl[-1], re.I)):
        _bl.pop()
    body = "\n".join(_bl).strip() + "\n\nKino"
    body = re.sub(r"\s*(dans l'annuaire public |in the public directory )?OpenStreetMap", "", body)
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
    if p.get("preview") and tracked(p) in body:      # 2026-11-06 (owner: "first impression so good"): the page they will open
        q2 = qa(p["name"], url=p["preview"])          # is tested in a real browser right now - a failing page is never sent
        if not q2["ok"]:
            return "not sent - their preview fails the browser test: %s. Fix the preview (or brief your designer), then send." % \
                "; ".join(q2["issues"])[:700]
    if not sent:                                     # 2026-11-06 (owner: "do all 7" - #5): every FIRST email is checked by QA
        q = _email_qa(W, p, cc, subject, full, log)          # with the footer it will carry (06/11: QA asked for a footer it could not see)
        if q:
            return "not sent - QA found: %s. Fix it (or brief your writer), then send again." % q
    import kino_mail as KM
    KM.allow(a)
    _img = None
    if p.get("preview") and tracked(p) in full:     # 2026-11-07 (owner): a picture of their new site in the email itself
        try:
            import kino_media as KMD
            from PIL import Image
            _sh = KMD.shot(p["preview"], "mail-" + _slug(p["name"]),
                           ("Votre nouveau site, %s" if str(p.get("lang") or "fr").startswith("fr") else "Your new website, %s") % p["name"][:40])
            if _sh.get("ok"):
                _img = _sh["path"][:-4] + ".jpg"
                Image.open(_sh["path"]).convert("RGB").resize((1120, 630)).save(_img, quality=85)
        except Exception as e:
            _log("MAIL-IMAGE-ERR %s %s" % (p["name"], e))
    KM.send_now(a, subject, full, image=_img, link=tracked(p) if _img else None)
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
            # 2026-11-06 (Atlas rebuild): a 4.2 MB photo was skipped silently - a broken image on the page, and heavy photos
            # make a phone wait. Photos are shrunk here (max 1600 px, ~85 quality) before they go up
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) and os.path.getsize(fp) > 450_000:
                try:
                    from PIL import Image
                    im = Image.open(fp)
                    im.thumbnail((1600, 1600))
                    if f.lower().endswith((".jpg", ".jpeg")):
                        im.convert("RGB").save(fp, "JPEG", quality=84, optimize=True, progressive=True)
                    else:
                        im.save(fp, optimize=True)
                except Exception as e:
                    _log("SHRINK-ERR %s %s" % (fp, e))
            if os.path.getsize(fp) > 3_000_000:
                return "not published - %s is %.1f MB, too big for a page (shrink it)" % (f, os.path.getsize(fp) / 1e6)
            files.append((os.path.relpath(fp, root).replace("\\", "/"), fp))
    if not any(r == "index.html" for r, _ in files):
        return "a preview needs an index.html"
    if len(files) > 40:
        return "too many files for a preview (40 at most)"
    # 2026-11-06 (Matsy on the Atlas preview: "clean but not the best ... premium and modern ... as if it was the final production
    # with images and all"): a bare page is not published
    html = open(os.path.join(root, "index.html"), encoding="utf-8", errors="replace").read()
    n_img = len(re.findall(r"<img\b|background(?:-image)?\s*:[^;]*url\(", html, re.I)) + \
        sum(1 for r, _ in files if r.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")))
    miss = []
    if n_img < 5:
        miss.append("real images (%d found, at least 5: their own photos first, then fitting free-licence photos)" % n_img)
    if not re.search(r"<meta[^>]+name=[\"']viewport", html, re.I):
        miss.append("the mobile viewport tag")
    if len(re.findall(r"<section\b", html, re.I)) < 4:
        miss.append("the sections of a real site (hero, services, gallery, hours/map, contact - at least 4 <section>)")
    if len(html) < 9000:
        miss.append("depth (%d characters - a production site has more)" % len(html))
    # 2026-11-06 (owner: "people who will take a preview, download it and host it themselves?"): a preview stays a preview -
    # its mark is required, search engines are kept out, and what has the real value (domain, hosting, working forms and
    # booking, Google listing, changes) only comes with the paid job
    if not re.search(r"Aper[cç]u r[ée]alis[ée]|Preview made for|not live yet|pas encore en ligne", html, re.I):
        miss.append('the preview mark ("Preview made for <name> by Kinoverse - not live yet" / "Aperçu réalisé pour ... - pas encore en ligne")')
    if miss:
        return ("not published - this is not yet the premium, finished-looking site Matsy asked for. Missing: %s. Brief your "
                "designer or improve it, then publish." % "; ".join(miss))
    if not re.search(r'<meta[^>]+name=["\']robots["\'][^>]+noindex', html, re.I):
        html = re.sub(r"(<head[^>]*>)", r'\1\n<meta name="robots" content="noindex, nofollow">', html, count=1, flags=re.I)
        open(os.path.join(root, "index.html"), "w", encoding="utf-8").write(html)
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
    with _LK:                                          # 2026-11-06: qa checks a preview before any job exists
        d = _j(STORE, {"items": []})
        for x in d["items"]:
            if x["id"] == p["id"]:
                x["preview"] = url
        _w(STORE, d)
    _log("PREVIEW %s %s" % (p["name"], url))
    return "preview published (a minute or two to appear): %s" % url


TRACK_BASE = "https://owltrader.duckdns.org/v/"      # 2026-11-06 (owner): did they open what we made? - an honest click counter


def tracked(p):
    """the link that goes in an email: our address, which counts the visit and forwards to their preview"""
    return TRACK_BASE + p["id"] if p.get("preview") else ""


def on_click(pid, ua=""):
    """someone opened /v/<id> -> (preview url or None). Counted on the prospect; Kino hears about it"""
    with _LK:
        d = _j(STORE, {"items": []})
        p = next((x for x in d["items"] if x["id"] == pid), None)
        if not p or not p.get("preview"):
            return None
        # 2026-11-07: Matsy opens the link himself while he sends a Messenger message (3 "clicks" were his) - not theirs
        if p.get("handed_t") and time.time() - float(p["handed_t"]) < 1800:
            _log("CLICK ignored (Matsy sending it) %s" % p["name"])
            return p["preview"]
        c = p.setdefault("clicks", [])
        c.append({"t": time.time(), "ua": str(ua or "")[:120]})
        p["clicks"] = c[-50:]
        if p["stage"] in ("contacted", "followed_up", "preview"):
            p.setdefault("history", []).append([int(time.time()), p["stage"], "opened"])
            p["stage"] = "opened"
        _w(STORE, d)
        url, name, n = p["preview"], p["name"], len(c)
    _log("CLICK %s (%d)" % (name, n))
    try:                                       # 2026-11-06: a first in his life story
        import kino_story as KST
        KST.milestone("A business opened a website preview I had made for them, for the first time (%s)." % name, key="first_click")
    except Exception:
        pass
    if n == 1:
        try:
            import kino_urge as KU
            KU.add("kino", "A BUSINESS OPENED WHAT YOU MADE: %s just opened the preview you sent them (%s). That is the moment "
                           "interest is real - your follow-up can now come sooner and warmer, within the country rules." % (name, url))
        except Exception:
            pass
    return url


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def site_audit(url):
    """2026-11-06 (owner: yes to hunting businesses with WEAK websites - the no-website ones have no email, the night hunt showed):
    one business site as a client sees it -> {"ok", "url", "score" 0-10 (10 = very weak), "problems": [...], "emails": [...]}"""
    import time as _t
    import kino_web as KWB
    url = str(url or "").strip()
    if not url:
        return {"ok": False, "err": "no address"}
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    t0 = _t.time()
    try:
        h, _ct = KWB._get(url, timeout=25, cap=2_000_000)
    except Exception as e:
        # (a site that refuses robots is not proof it is broken - open it in your browser before calling it dead)
        return {"ok": True, "url": url, "score": None, "problems": ["could not open it from here (%s) - check it in your browser" % str(e)[:80]],
                "emails": []}
    s = _t.time() - t0
    P, score = [], 0
    if not url.startswith("https://") and not re.search(r"https://", url):
        P.append("no secure https");  score += 2
    if not re.search(r"<meta[^>]+name=[\"']viewport", h, re.I):
        P.append("not made for phones (no mobile viewport)");  score += 3
    yrs = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*(?:\d{4}\s*[-–]\s*)?(20\d\d|19\d\d)", h, re.I)]
    if yrs and max(yrs) <= time.gmtime().tm_year - 3:
        P.append("looks unmaintained (copyright %d)" % max(yrs));  score += 2
    if re.search(r"<table[^>]+width=|<font\b|<center\b|<frameset|\.swf\b|<marquee", h, re.I):
        P.append("old-fashioned building blocks (tables/fonts/frames)");  score += 2
    if re.search(r"wix\.com|weebly|godaddy.*builder|jimdo|site123|webnode", h, re.I):
        P.append("a free builder template");  score += 1
    if s > 6:
        P.append("slow (%.0f s)" % s);  score += 1
    if not re.search(r"<title>\s*\S", h, re.I):
        P.append("no page title");  score += 1
    if len(re.findall(r"<img\b", h, re.I)) < 2:
        P.append("almost no photos");  score += 1
    if not re.search(r"book|booking|appointment|reserv|rendez|réserv", h, re.I):
        P.append("no online booking");  score += 1
    em = [e for e in dict.fromkeys(_EMAIL_RE.findall(h)) if not re.search(r"\.(png|jpe?g|gif|webp|svg)$|example\.|sentry|wixpress|@2x", e, re.I)]
    if not em:                                     # the contact page often has it
        m = re.search(r"href=[\"']([^\"']*(?:contact|kontakt|nous-contacter|about)[^\"']*)[\"']", h, re.I)
        if m:
            try:
                import urllib.parse
                h2, _ = KWB._get(urllib.parse.urljoin(url, m.group(1)), timeout=20, cap=1_000_000)
                em = [e for e in dict.fromkeys(_EMAIL_RE.findall(h2)) if not re.search(r"\.(png|jpe?g|gif|webp|svg)$|example\.|sentry|wixpress", e, re.I)]
            except Exception:
                pass
    return {"ok": True, "url": url, "score": min(10, score), "problems": P, "emails": em[:4]}


def scan(place, kind, max_sites=40):
    """2026-11-06 (watch: a hunt found 74 Lyon barbers and audited 5, one per step): a whole city at once - every business
    site audited in parallel (no AI cost), plus the no-website ones that show an email -> {"ok", "weak": [...], "nosite": [...]}"""
    from concurrent.futures import ThreadPoolExecutor
    r = find_businesses(place, kind, limit=400)
    if not r.get("ok"):
        return r
    items = r["items"]
    sites = [x for x in items if x["website"]][:int(max_sites)]
    nosite = [x for x in items if not x["website"] and (x["email"] or x["facebook"])]
    with ThreadPoolExecutor(max_workers=8) as ex:
        audits = list(ex.map(lambda x: site_audit(x["website"]), sites))
    weak = []
    for x, a in zip(sites, audits):
        if a.get("ok") and (a.get("score") or 0) >= 4:
            dom = re.sub(r"^www\.", "", str(x["website"]).lower().split("//")[-1].split("/")[0])
            em = list(dict.fromkeys(([x["email"]] if x["email"] else []) + (a.get("emails") or [])))
            em.sort(key=lambda e: not e.lower().endswith("@" + dom))   # their own domain first - a footer email can be the web agency's
            weak.append(dict(x, score=a["score"], problems=a["problems"], emails=em))
    weak.sort(key=lambda x: (-bool(x["emails"]), -x["score"]))
    _log("SCAN %s in %s -> %d sites audited, %d weak (%d with email), %d no-site with email/facebook" % (
        kind, place, len(sites), len(weak), sum(1 for x in weak if x["emails"]), len(nosite)))
    # 2026-11-06 (owner: "turn leads into emails" - a hunt found 65 reachable businesses and wrote to none): the reachable ones
    # are recorded at once, so they wait on his desk as READY TO CONTACT
    cc = country_code(str(r.get("place") or "").split(",")[-1].strip())
    lang = {"FR": "fr", "BE": "fr", "CH": "fr", "LU": "fr", "ES": "es", "MX": "es", "AR": "es", "CO": "es", "DE": "de", "AT": "de",
            "IT": "it", "PT": "pt", "BR": "pt", "NL": "nl"}.get(cc, "en")
    city = str(place).strip()
    n = 0
    for x in weak:
        if x["emails"] and n < 12:
            prospect(x["name"], url=x["website"], email_=x["emails"][0], country=cc, lang=lang, stage="found",
                     need="%s %s with a weak site (%d/10): %s" % (kind, city, x["score"], "; ".join(x["problems"][:4])),
                     notes="scan %s | phone %s | %s" % (time.strftime("%d/%m"), x["phone"] or "-", x["address"] or city))
            n += 1
    for x in nosite:
        if n < 20:
            prospect(x["name"], url=x["facebook"] if x["facebook"] and str(x["facebook"]).startswith("http") else None,
                     key=None if x["facebook"] and str(x["facebook"]).startswith("http") else "osm:" + x["osm"].rsplit("/", 1)[-1],
                     email_=x["email"], country=cc, lang=lang, stage="found",
                     need="%s %s with NO website" % (kind, city),
                     notes="scan %s | facebook %s | phone %s | %s | %s" % (time.strftime("%d/%m"), x["facebook"] or "-", x["phone"] or "-",
                                                                            x["address"] or city, x["osm"]))
            n += 1
    return {"ok": True, "place": r["place"], "total": r["total"], "audited": len(sites), "weak": weak, "nosite": nosite}


def page_images(url, n=30):
    """2026-11-06 (Brévi preview: stock photos of an Asian street barber with a Pepsi sign for a Lyon family salon): the
    business's OWN photos, from its own site - the image addresses on the page (and its og:image), biggest-looking first"""
    import urllib.parse
    import kino_web as KWB
    try:
        h, _ = KWB._get(url, timeout=25, cap=2_000_000)
    except Exception as e:
        return {"ok": False, "err": str(e)[:120]}
    raw = re.findall(r"""(?:src|data-src|data-lazy-src|href|content)=["']([^"']+\.(?:jpe?g|png|webp)(?:\?[^"']*)?)["']""", h, re.I)
    raw += re.findall(r"url\(['\"]?([^'\")]+\.(?:jpe?g|png|webp))", h, re.I)
    out = []
    for u in raw:
        a = urllib.parse.urljoin(url, u)
        if a not in out and not re.search(r"logo-?mini|favicon|icon|sprite|pixel|spacer|1x1|avatar|emoji|badge", a, re.I):
            out.append(a)
    out.sort(key=lambda a: -bool(re.search(r"\d{3,4}x\d{3,4}|large|full|hero|slide|banner|galer|photo|salon|img", a, re.I)))
    return {"ok": True, "images": out[:n]}


def record_line():
    """2026-11-06 (watch: in chat he said a Lyon barber got his free page - it was Atlas in Cape Town): the facts of his sales,
    for every conversation - who he really wrote to, where, when, with what, and what came back. Talk from THIS, not memory."""
    d = _j(STORE, {"items": []})["items"]
    sent = sorted([(s, p) for p in d for s in p.get("sent") or []], key=lambda x: -x[0]["t"])
    fb = [p for p in d if "fbhand" in str(p.get("notes") or "")]
    found = [p for p in d if p["stage"] in ("found", "checked")]
    L = ["YOUR SALES RECORD (the facts - when you talk about your clients and leads, say only what is here): "]
    if sent:
        L.append("emails sent: " + " | ".join("%s to %s (%s%s)%s%s%s" % (
            time.strftime("%d/%m", time.gmtime(s["t"])), p["name"], p.get("country") or "?",
            ", " + str(p.get("need") or "")[:70] if p.get("need") else "",
            ", with a preview" if p.get("preview") and (p["preview"].rstrip("/") in s.get("body", "") or tracked(p) in s.get("body", "")) else ", no preview",
            ", OPENED %dx" % len(p["clicks"]) if p.get("clicks") else "",
            ", BOUNCED - the address does not exist" if p.get("bounced") else ", REPLIED" if p["stage"] in ("replied", "quoted", "won", "delivered") else ", no answer yet") for s, p in sent[:8]))
    else:
        L.append("no email sent yet")
    if fb:
        L.append("; Messenger messages given to Matsy: " + ", ".join(p["name"] for p in fb[:6]))
    L.append("; leads recorded and not contacted yet: %d" % len(found))
    won = [p for p in d if p["stage"] in ("won", "delivered")]
    L.append("; clients won: %s" % (", ".join(p["name"] for p in won) or "none yet"))
    return "".join(L)


def stock_photos(q, n=12):
    """2026-11-06 (Matsy: previews 'as if it was the final production with images and all'): free-licence photos for a trade,
    from Openverse (CC0 first: StockSnap, Rawpixel; then any licence allowing commercial use, with its credit)"""
    import urllib.parse, urllib.request
    out = []
    for extra in ("&source=stocksnap,rawpixel&license=cc0", "&license_type=commercial&aspect_ratio=wide&size=large"):
        url = "https://api.openverse.org/v1/images/?q=%s&page_size=%d%s" % (urllib.parse.quote(str(q or "")[:80]), n, extra)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Kinoverse/1.0 (https://kv-kinoverse.pages.dev)"})
            d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
        except Exception as e:
            _log("PHOTOS-ERR %s %s" % (q, e))
            continue
        for r in d.get("results") or []:
            if r.get("url") and r["url"] not in [x["url"] for x in out] and (r.get("width") or 0) >= 900:
                out.append({"url": r["url"], "license": r.get("license"), "w": r.get("width"), "h": r.get("height"),
                            "by": (r.get("creator") or "")[:60], "title": (r.get("title") or "")[:80]})
        if len(out) >= n:
            break
    return out[:n]


# ------------------------------------------------------------------ what he sees at his desk
def block():
    d = _j(STORE, {"items": []})["items"]
    o = offer()
    by = {}
    for p in d:
        by[p["stage"]] = by.get(p["stage"], 0) + 1
    act = sorted([p for p in d if p["stage"] in ("replied", "quoted", "won", "preview", "checked")], key=lambda p: -p.get("updated", 0))[:8]
    due = [p for p in d if p["stage"] == "contacted" and len(p.get("sent") or []) == 1 and time.time() - float(p["sent"][-1]["t"]) > 5 * 86400][:5]
    opened = sorted([p for p in d if p.get("clicks")], key=lambda p: -p["clicks"][-1]["t"])[:6]
    L = ["KINOVERSE SALES - your prospects: " + (", ".join("%s %d" % (k, by[k]) for k in STAGES if by.get(k)) or "none yet") +
         "; outreach sent today %d of %d." % (_sent_today(), int(o.get("daily_emails") or 10))]
    if act:
        L.append("Moving now: " + " | ".join("%s [%s] %s%s" % (p["name"], p["stage"], (p.get("need") or "")[:80],
                                                                 (" - " + p["url"]) if p.get("url") else "") for p in act))
    ready = sorted([p for p in d if p["stage"] in ("found", "checked", "preview") and p.get("email") and not p.get("sent")],
                   key=lambda p: (not p.get("preview"), -p.get("updated", 0)))[:8]    # previews first, THEN the newest
    fbo = [p for p in d if p["stage"] in ("found", "checked") and not p.get("email") and "facebook.com" in str(p.get("url") or "")][:5]
    if ready:                                  # 2026-11-06 (owner: turn leads into emails)
        ready.sort(key=lambda p: not p.get("preview"))
        L.append("READY TO CONTACT (recorded, an email, nothing sent yet - every hunt ENDS with up to 5 of these written to, "
                 "personally; those WITH A PREVIEW first): " + " | ".join("%s (%s, %s) %s - %s%s" % (
                     p["name"], p.get("country") or "?", p.get("lang") or "?", p.get("email"), (p.get("need") or "")[:90],
                     " - PREVIEW READY: " + p["preview"] if p.get("preview") else "") for p in ready))
    if fbo:
        L.append("FACEBOOK ONLY (no email - fbhand: Matsy sends your message in Messenger): " + " | ".join(
            "%s %s" % (p["name"], p["url"]) for p in fbo))
    if opened:                                 # 2026-11-06: who opened what you made (the click counter)
        L.append("OPENED YOUR PREVIEW (follow these up first, 2+ days after your email, warmly): " + " | ".join(
            "%s - %d time(s), last %s" % (p["name"], len(p["clicks"]), time.strftime("%d/%m %H:%M UTC", time.gmtime(p["clicks"][-1]["t"]))) for p in opened))
    if due:
        L.append("No answer after 5+ days (one follow-up allowed, if it adds something): " + ", ".join(p["name"] for p in due))
    try:                                       # 2026-11-05 (owner: "is he learning from his mistakes?"): his own playbook
        pb = open(r"C:\KinoWorld\projects\kinoverse\playbook.md", encoding="utf-8").read()
        L.append("YOUR HUNTING PLAYBOOK (C:\\KinoWorld\\projects\\kinoverse\\playbook.md - what you learned works and fails; read it, "
                 "follow it, and ADD a line after every hunt - a source that worked or failed, a query, a mistake not to repeat):\n"
                 + pb[:3500])
    except Exception:
        pass
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
    if url and os.path.isdir(str(url)):                # 2026-11-06: the designer passed its folder - check what was published
        url = None
    url = url or j.get("site") or (p or {}).get("preview")
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
        if h.lower().startswith(("mailto:", "tel:", "sms:", "whatsapp:", "geo:", "javascript:", "data:", "intent:")):   # 06/11: an SMS button blocked Les Vignes
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
    # 2026-11-06 (owner: "make sure QA does a good testing job - caching and all - so the first impression is so good"; the
    # Brevi preview cut its Call button off on his Android phone): the page opened in a real browser, phone and computer
    notes = []
    try:
        import subprocess
        _pq = subprocess.run(["node", os.path.join(os.path.dirname(HERE), "review", "page_qa.mjs"), url + ("&" if "?" in url else "?") + "qa=%d" % int(time.time())],
                             capture_output=True, text=True, timeout=150, encoding="utf-8", errors="replace")
        _r = json.loads((_pq.stdout or "").strip().splitlines()[-1])
        if any("could not start" in i for i in _r.get("issues") or []):
            notes.append("the browser test could not run this time - look at it yourself before sending")
        elif any("did not finish in 90 s" in i for i in _r.get("issues") or []) and len(_r.get("issues") or []) == 1:
            # 06/11: a busy server, not a slow page, blocked Les Vignes' email - the rest of the check passed
            notes.append("the browser test did not finish (busy server) - the other checks passed")
        else:
            issues += _r.get("issues") or []
            notes += _r.get("notes") or []
    except Exception as e:
        notes.append("the browser test failed (%s) - look at it yourself before sending" % str(e)[:80])
    res = {"t": time.time(), "url": url, "ok": not issues, "issues": issues, "notes": notes}
    if p and p.get("job"):
        with _LK:
            d = _j(STORE, {"items": []})
            for x in d["items"]:
                if x["id"] == p["id"]:
                    x["job"]["qa"] = res
            _w(STORE, d)
    _log("QA %s %s %s" % ((p or {}).get("name"), url, "ok" if not issues else "; ".join(issues)[:200]))
    return res


# ------------------------------------------------------------------ 2026-11-05 (live run, owner watching: X and web search gave noise,
# OpenStreetMap was the right idea but his generic fetch was refused): finding real local businesses systematically.
# OpenStreetMap (open data, ODbL): Nominatim for the place, Overpass for the businesses. Honest User-Agent, one query at a time.
_UA = {"User-Agent": "Kinoverse/1.0 (kinoverse26@gmail.com)"}
KINDS = {"hairdresser": "shop=hairdresser", "barber": "shop=hairdresser", "salon": "shop=hairdresser", "beauty": "shop=beauty",
         "nails": "shop=beauty", "restaurant": "amenity=restaurant", "cafe": "amenity=cafe", "bar": "amenity=bar",
         "bakery": "shop=bakery", "butcher": "shop=butcher", "florist": "shop=florist", "clothes": "shop=clothes",
         "plumber": "craft=plumber", "electrician": "craft=electrician", "carpenter": "craft=carpenter", "painter": "craft=painter",
         "car repair": "shop=car_repair", "mechanic": "shop=car_repair", "dentist": "amenity=dentist", "doctor": "amenity=doctors",
         "clinic": "amenity=clinic", "pharmacy": "amenity=pharmacy", "gym": "leisure=fitness_centre", "hotel": "tourism=hotel",
         "guest house": "tourism=guest_house", "lawyer": "office=lawyer", "accountant": "office=accountant", "estate agent":
         "office=estate_agent", "driving school": "amenity=driving_school", "photographer": "craft=photographer",
         "tailor": "craft=tailor", "veterinary": "amenity=veterinary", "pet shop": "shop=pet"}


def find_businesses(place, kind, limit=25, with_site=False):
    """real businesses of one kind in one place, those WITHOUT a website first (with_site: only those WITH one, to audit) -> {"ok", "items"|"err"}"""
    import urllib.parse, urllib.request
    tag = KINDS.get(str(kind or "").strip().lower()) or (str(kind) if "=" in str(kind or "") else None)
    if not tag:
        return {"ok": False, "err": "kinds I know: " + ", ".join(sorted(KINDS)) + " (or an OpenStreetMap tag like shop=bakery)"}
    try:
        g = json.load(urllib.request.urlopen(urllib.request.Request(
            "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": place, "format": "json", "limit": 1}),
            headers=_UA), timeout=30))
    except Exception as e:
        return {"ok": False, "err": "place lookup failed: %s" % str(e)[:120]}
    if not g:
        return {"ok": False, "err": "no place called %r" % place}
    s, n, w, e = [float(x) for x in g[0]["boundingbox"]]
    if (n - s) * (e - w) > 1.5:                       # a whole country or region: too big for one query - ask for a city
        return {"ok": False, "err": "%r is too big an area - name a city or a district" % place}
    k, v = tag.split("=", 1)
    q = '[out:json][timeout:50];nwr["%s"="%s"]["name"](%f,%f,%f,%f);out center tags 300;' % (k, v, s, w, n, e)
    # 2026-11-06: the free map servers fail often (SSL, 502) - a city fetched once is kept 7 days
    import hashlib
    cf = os.path.join(os.path.dirname(STORE), "osm_cache", hashlib.sha1(q.encode()).hexdigest()[:16] + ".json")
    r, last = None, ""
    try:
        if time.time() - os.path.getmtime(cf) < 7 * 86400:
            r = json.load(open(cf, encoding="utf-8"))
    except Exception:
        pass
    for _try in range(2 if r is None else 0):
        if _try:
            time.sleep(20)
        for ep in ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
                   "https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
            try:
                r = json.load(urllib.request.urlopen(urllib.request.Request(
                    ep, data=urllib.parse.urlencode({"data": q}).encode(), headers=_UA), timeout=90))
                break
            except Exception as ex:
                last = str(ex)[:80]
        if r is not None:
            try:
                os.makedirs(os.path.dirname(cf), exist_ok=True)
                json.dump(r, open(cf, "w", encoding="utf-8"))
            except Exception:
                pass
            break
    if r is None:
        return {"ok": False, "err": "the map servers did not answer (%s) - try again in a few minutes" % last}
    out = []
    for el in r.get("elements") or []:
        t = el.get("tags") or {}
        site = t.get("website") or t.get("contact:website") or t.get("url")
        phone = t.get("phone") or t.get("contact:phone") or t.get("contact:mobile")
        mail = t.get("email") or t.get("contact:email")
        fb = t.get("contact:facebook") or t.get("facebook")
        addr = " ".join(x for x in (t.get("addr:housenumber"), t.get("addr:street"), t.get("addr:city") or t.get("addr:suburb")) if x)
        out.append({"name": t.get("name"), "website": site, "phone": phone, "email": mail, "facebook": fb, "address": addr,
                    "hours": t.get("opening_hours"), "osm": "https://www.openstreetmap.org/%s/%s" % (el["type"], el["id"])})
    out.sort(key=lambda x: (bool(x["website"]), not (x["email"] or x["phone"] or x["facebook"])))
    if with_site:                                  # 2026-11-06: the weak-site hunt
        out = [x for x in out if x["website"]]
    no_site = sum(1 for x in out if not x["website"])
    _log("FIND %s in %s -> %d (%d without a website)" % (kind, place, len(out), no_site))
    return {"ok": True, "place": g[0].get("display_name"), "total": len(out), "without_site": no_site, "items": out[:int(limit)]}
