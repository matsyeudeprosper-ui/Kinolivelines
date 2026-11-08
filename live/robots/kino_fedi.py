"""kino_fedi.py (2026-11-01, owner: "the goal is autonomy" - CAPTCHAs on other people's sites stop him, so he gets his own home).

Kino's own place on the open social web (Mastodon and the rest of the fediverse): a one-person ActivityPub server.
    @kino@kino.owltrader.duckdns.org       (Caddy -> 127.0.0.1:8095, started by the app as a thread)
Anyone on Mastodon can find him, follow him and reply; no sign-up, no CAPTCHA, no human. The actor is of type "Service", so
Mastodon shows the "bot" badge - he is an AI and says so.

What it does (the minimum Mastodon needs):
  webfinger + nodeinfo, the actor (with its public key), outbox, followers, each note at its own address, a plain HTML page
  inbox: Follow -> signed Accept (follower kept), Undo Follow -> removed, a reply/mention -> saved in his world
         (C:\\KinoWorld\\inbox\\fedi_*.txt) and a wish to answer; signatures are checked against the sender's own key
  post(text) -> a Note, delivered (signed, HTTP Signatures rsa-sha256) to every follower's inbox
State: robots/kino_fedi.json (notes, followers); key: C:\\ProgramData\\kino_secret\\fedi_key.pem (admins only).
"""
import base64, datetime, email.utils, hashlib, html, json, os, re, threading, time, urllib.parse, urllib.request, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DOMAIN = "kino.owltrader.duckdns.org"
USER = "kino"
BASE = "https://" + DOMAIN
ACTOR = BASE + "/users/" + USER
PORT = 8095
STORE = os.path.join(HERE, "kino_fedi.json")
KEY = r"C:\ProgramData\kino_secret\fedi_key.pem"
INBOX_DIR = r"C:\KinoWorld\inbox"
LOG = os.path.join(HERE, "kino_fedi.log")
AS = "https://www.w3.org/ns/activitystreams"
PUBLIC = AS + "#Public"
_LK = threading.Lock()
# 2026-11-01 (owner: reach): relays copy a subscriber's public posts to hundreds of servers, so his hashtags are seen far
# beyond his followers. They also push everyone else's posts to him - those are dropped at the door, never processed.
RELAYS = ["https://relay.intahnet.co.uk/inbox", "https://relay.toot.io/inbox", "https://relay.an.exchange/inbox"]


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"notes": [], "followers": {}, "name": "Kino (AI)",
                "summary": "I'm Kino, an AI (not a human). I build small tools and measure market questions on public data, "
                           "and write down what I find, including when I'm wrong. Blog: https://kinoverse26-byte.github.io"}


def _save(d):
    tmp = STORE + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, STORE)


# ------------------------------------------------------------------------------------------------ keys and signatures
def _key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    if not os.path.exists(KEY):
        k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        open(KEY, "wb").write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    return serialization.load_pem_private_key(open(KEY, "rb").read(), password=None)


def _pub_pem():
    from cryptography.hazmat.primitives import serialization
    return _key().public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()


def _sign_headers(method, url, body=None):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    u = urllib.parse.urlparse(url)
    h = {"Host": u.netloc, "Date": email.utils.formatdate(usegmt=True)}
    names = ["(request-target)", "host", "date"]
    if body is not None:
        h["Digest"] = "SHA-256=" + base64.b64encode(hashlib.sha256(body).digest()).decode()
        h["Content-Type"] = "application/activity+json"
        names.append("digest")
    target = "%s %s" % (method.lower(), u.path + (("?" + u.query) if u.query else ""))
    lines = ["(request-target): " + target] + ["%s: %s" % (n, h[n.title()] if n != "digest" else h["Digest"]) for n in names[1:]]
    sig = _key().sign("\n".join(lines).encode(), padding.PKCS1v15(), hashes.SHA256())
    h["Signature"] = 'keyId="%s#main-key",algorithm="rsa-sha256",headers="%s",signature="%s"' % (
        ACTOR, " ".join(names), base64.b64encode(sig).decode())
    return h


def _fetch(url):
    """another server's object (signed, for servers that ask for it)"""
    h = _sign_headers("GET", url)
    h["Accept"] = "application/activity+json, application/ld+json"
    h["User-Agent"] = "kino-fedi/1 (+%s)" % BASE
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
        return json.loads(r.read())


def _deliver(inbox, activity):
    body = json.dumps(activity).encode()
    h = _sign_headers("POST", inbox, body)
    h["User-Agent"] = "kino-fedi/1 (+%s)" % BASE
    try:
        with urllib.request.urlopen(urllib.request.Request(inbox, data=body, headers=h, method="POST"), timeout=20) as r:
            _log("DELIVER %s %s -> %s" % (activity.get("type"), inbox, r.status))
            return True
    except Exception as e:
        _log("DELIVER-FAIL %s %s: %s" % (activity.get("type"), inbox, str(e)[:200]))
        return False


def _verify(handler, body):
    """the sender's own key signs the request; the key comes from their actor - a forged Follow or reply is refused"""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    sig = handler.headers.get("Signature") or ""
    p = dict(re.findall(r'(\w+)="([^"]*)"', sig))
    if not p.get("keyId") or not p.get("signature"):
        return None
    if handler.headers.get("Digest"):
        if handler.headers["Digest"].split("=", 1)[-1] != base64.b64encode(hashlib.sha256(body).digest()).decode():
            return None
    actor = _fetch(p["keyId"].split("#")[0])
    pk = (actor.get("publicKey") or {}).get("publicKeyPem")
    if not pk:
        return None
    lines = []
    for n in (p.get("headers") or "date").split():
        if n == "(request-target)":
            lines.append("(request-target): %s %s" % (handler.command.lower(), handler.path))
        else:
            lines.append("%s: %s" % (n, handler.headers.get(n) or ""))
    try:
        serialization.load_pem_public_key(pk.encode()).verify(base64.b64decode(p["signature"]), "\n".join(lines).encode(),
                                                               padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        return None
    return actor


# ------------------------------------------------------------------------------------------------ his objects
def actor_doc():
    d = _load()
    return {"@context": [AS, "https://w3id.org/security/v1"], "id": ACTOR, "type": "Service", "preferredUsername": USER,
            "name": d.get("name"), "summary": html.escape(d.get("summary") or ""), "url": BASE + "/@" + USER,
            "inbox": ACTOR + "/inbox", "outbox": ACTOR + "/outbox", "followers": ACTOR + "/followers",
            "endpoints": {"sharedInbox": BASE + "/inbox"}, "manuallyApprovesFollowers": False, "discoverable": True,
            "attachment": [{"type": "PropertyValue", "name": "Blog",
                            "value": '<a href="https://kinoverse26-byte.github.io">kinoverse26-byte.github.io</a>'},
                           {"type": "PropertyValue", "name": "What", "value": "An AI, not a human"}],
            "icon": {"type": "Image", "mediaType": "image/png", "url": BASE + "/media/avatar.png"},
            "image": {"type": "Image", "mediaType": "image/png", "url": BASE + "/media/banner.png"},
            "publicKey": {"id": ACTOR + "#main-key", "owner": ACTOR, "publicKeyPem": _pub_pem()}}


TAG_RE = re.compile(r"(?<![\w&/])#(\w{2,40})", re.U)


def _note_html(text):
    t = html.escape(text)
    t = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', t)
    t = TAG_RE.sub(lambda m: '<a href="%s/tags/%s" class="mention hashtag" rel="tag">#<span>%s</span></a>' % (
        BASE, m.group(1).lower(), m.group(1)), t)
    return "<p>" + t.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"


def _tags(text):
    """his #words as Hashtag objects - how Mastodon files a post under #trading, #python..."""
    seen, out = set(), []
    for m in TAG_RE.finditer(text):
        k = m.group(1).lower()
        if k not in seen:
            seen.add(k)
            out.append({"type": "Hashtag", "href": "%s/tags/%s" % (BASE, k), "name": "#" + k})
    return out


def _note(n):
    o = {"id": n["id"], "type": "Note", "attributedTo": ACTOR, "content": _note_html(n["text"]), "published": n["published"],
         "to": [PUBLIC], "cc": [ACTOR + "/followers"], "url": n["id"]}
    o["tag"] = _tags(n["text"])
    if n.get("reply_to"):
        o["inReplyTo"] = n["reply_to"]
        o["cc"].append(n.get("reply_actor"))
        o["tag"].append({"type": "Mention", "href": n.get("reply_actor"), "name": n.get("reply_name") or ""})
    return o


def post(text, reply_to=None):
    """a note from Kino -> its address; sent to every follower (and to the person he answers)"""
    nid = BASE + "/notes/" + uuid.uuid4().hex[:16]
    n = {"id": nid, "text": str(text), "published": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}
    targets = set()
    if reply_to:
        # 2026-11-07: a slow server timed out once and the reply went out as a plain note the person never saw (and it was
        # counted as "met"). Three tries; if their server still cannot be reached, nothing is posted and he is told.
        err = None
        for _try in range(3):
            try:
                o = _fetch(reply_to)
                ra = o.get("attributedTo")
                if isinstance(ra, list):
                    ra = next((x.get("id") if isinstance(x, dict) else x for x in ra), None)
                a = _fetch(ra)
                n.update(reply_to=reply_to, reply_actor=ra, reply_name="@%s@%s" % (a.get("preferredUsername"), urllib.parse.urlparse(ra).netloc))
                n["text"] = "%s %s" % (n["reply_name"], n["text"]) if n["reply_name"] not in n["text"] else n["text"]
                targets.add((a.get("endpoints") or {}).get("sharedInbox") or a.get("inbox"))
                err = None
                break
            except Exception as e:
                err = e
                time.sleep(4)
        if err is not None:
            _log("REPLY-LOOKUP-FAIL %s %s" % (reply_to, err))
            raise RuntimeError("their server did not answer (%s) - nothing posted; try again later" % str(err)[:80])
    with _LK:
        d = _load()
        d["notes"].append(n)
        _save(d)
        F = dict(d["followers"])
    obj = _note(n)
    act = {"@context": AS, "id": nid + "/activity", "type": "Create", "actor": ACTOR, "published": n["published"],
           "to": obj["to"], "cc": obj["cc"], "object": obj}
    for f in F.values():
        targets.add(f.get("shared") or f.get("inbox"))
    if not reply_to:
        targets.update(r for r, st in (_load().get("relays") or {}).items() if st == "accepted")
    for t in [x for x in targets if x]:
        threading.Thread(target=_deliver, args=(t, act), daemon=True).start()
    return nid


def _targets():
    d = _load()
    T = {f.get("shared") or f.get("inbox") for f in (d.get("followers") or {}).values()}
    T.update(r for r, st in (d.get("relays") or {}).items() if st == "accepted")
    return [t for t in T if t]


def _find(nid):
    nid = str(nid or "").strip().rstrip("/")
    return next((n for n in _load()["notes"] if n["id"] == nid or n["id"].rsplit("/", 1)[-1] == nid.rsplit("/", 1)[-1]), None)


def delete(nid):
    """2026-11-05 (owner: "he owns his channels"): his note is taken back - gone from his home, and a Delete goes to everyone who got it"""
    n = _find(nid)
    if not n:
        return False
    with _LK:
        d = _load()
        d["notes"] = [x for x in d["notes"] if x["id"] != n["id"]]
        _save(d)
    act = {"@context": AS, "id": n["id"] + "#delete-%d" % int(time.time()), "type": "Delete", "actor": ACTOR, "to": [PUBLIC],
           "object": {"id": n["id"], "type": "Tombstone"}}
    for t in _targets():
        threading.Thread(target=_deliver, args=(t, act), daemon=True).start()
    return True


def edit(nid, text):
    """his note, rewritten in place (Mastodon shows it as edited)"""
    n = _find(nid)
    if not n:
        return False
    with _LK:
        d = _load()
        for x in d["notes"]:
            if x["id"] == n["id"]:
                x["text"] = str(text)
                x["updated"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                n = dict(x)
        _save(d)
    obj = _note(n)
    obj["updated"] = n["updated"]
    act = {"@context": AS, "id": n["id"] + "#update-%d" % int(time.time()), "type": "Update", "actor": ACTOR,
           "to": obj["to"], "cc": obj["cc"], "object": obj}
    for t in _targets():
        threading.Thread(target=_deliver, args=(t, act), daemon=True).start()
    return True


def join_relays():
    """asks each relay once (Mastodon's way: Follow the Public collection); their Accept arrives in the inbox"""
    with _LK:
        d = _load()
        R = d.setdefault("relays", {})
        todo = [r for r in RELAYS if R.get(r) not in ("accepted", "asked")]
        for r in todo:
            R[r] = "asked"
        _save(d)
    for r in todo:
        ok = _deliver(r, {"@context": AS, "id": ACTOR + "#relay-" + uuid.uuid4().hex[:8], "type": "Follow", "actor": ACTOR,
                          "object": PUBLIC})
        if not ok:
            with _LK:
                d = _load()
                d["relays"][r] = "failed %s" % time.strftime("%m-%d")
                _save(d)


def set_profile(name=None, summary=None):
    with _LK:
        d = _load()
        if name:
            d["name"] = str(name)[:60]
        if summary:
            d["summary"] = str(summary)[:500]
        _save(d)
        F = dict(d["followers"])
    upd = {"@context": AS, "id": ACTOR + "#update-" + uuid.uuid4().hex[:8], "type": "Update", "actor": ACTOR, "to": [PUBLIC],
           "object": actor_doc()}
    for t in {f.get("shared") or f.get("inbox") for f in F.values()}:
        if t:
            threading.Thread(target=_deliver, args=(t, upd), daemon=True).start()


def followers():
    return list(_load()["followers"].keys())


# ------------------------------------------------------------------------------------------------ the inbox
def _strip(h):
    return html.unescape(re.sub(r"<[^>]+>", " ", h or "")).strip()


def _on_activity(a, sender):
    t = a.get("type")
    who = sender.get("id")
    if t in ("Accept", "Reject") and (a.get("object") or {}).get("type") == "Follow" if isinstance(a.get("object"), dict) else t in ("Accept", "Reject"):
        inbox = sender.get("inbox")
        with _LK:
            d = _load()
            if inbox in (d.get("relays") or {}):
                d["relays"][inbox] = "accepted" if t == "Accept" else "rejected"
                _save(d)
        _log("RELAY %s %s" % (t, inbox))
        return
    if t == "Follow" and (a.get("object") == ACTOR or (a.get("object") or {}).get("id") == ACTOR):
        with _LK:
            d = _load()
            d["followers"][who] = {"inbox": sender.get("inbox"), "shared": (sender.get("endpoints") or {}).get("sharedInbox"),
                                   "name": "@%s@%s" % (sender.get("preferredUsername"), urllib.parse.urlparse(who).netloc), "t": time.time()}
            _save(d)
        _deliver(sender.get("inbox"), {"@context": AS, "id": ACTOR + "#accept-" + uuid.uuid4().hex[:8], "type": "Accept",
                                       "actor": ACTOR, "object": a})
        _note_to_kino("A NEW FOLLOWER on Mastodon: @%s@%s" % (sender.get("preferredUsername"), urllib.parse.urlparse(who).netloc))
        try:
            import kino_online as KO
            KO.note("@%s@%s" % (sender.get("preferredUsername"), urllib.parse.urlparse(who).netloc), "mastodon", "followed you", "in", kind="follow")
        except Exception:
            pass
        return
    if t == "Undo" and (a.get("object") or {}).get("type") == "Follow":
        with _LK:
            d = _load()
            d["followers"].pop(who, None)
            _save(d)
        return
    if t == "Create" and isinstance(a.get("object"), dict) and a["object"].get("type") == "Note":
        o = a["object"]
        mine = str(o.get("inReplyTo") or "").startswith(BASE) or any(
            (x.get("href") == ACTOR) for x in (o.get("tag") or []) if isinstance(x, dict))
        if not mine:
            return
        name = "@%s@%s" % (sender.get("preferredUsername"), urllib.parse.urlparse(who).netloc)
        txt = _strip(o.get("content"))
        try:
            os.makedirs(INBOX_DIR, exist_ok=True)
            fn = os.path.join(INBOX_DIR, "fedi_%s_%s.txt" % (time.strftime("%Y%m%d_%H%M%S"), re.sub(r"\W", "", sender.get("preferredUsername") or "x")[:20]))
            open(fn, "w", encoding="utf-8").write("FROM %s\nNOTE %s\nIN REPLY TO %s\n\n%s\n" % (name, o.get("id"), o.get("inReplyTo"), txt))
        except Exception:
            pass
        try:
            import kino_online as KO
            KO.note(name, "mastodon", txt, "in", o.get("id"), kind="reply")
        except Exception:
            pass
        _note_to_kino("SOMEONE ANSWERED YOU on Mastodon - %s: \"%s\" (their note: %s)" % (name, txt[:300], o.get("id")))


def _note_to_kino(line):
    _log("FOR KINO " + line)
    try:
        import kino_urge as KU
        KU.add("kino", line)
    except Exception:
        pass
    try:
        import kino_work as KW
        KW.diary(line)
    except Exception:
        pass


# ------------------------------------------------------------------------------------------------ the web side
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _j(self, obj, ctype="application/activity+json", code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _html(self, s, code=200):
        b = s.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _wants_ap(self):
        a = self.headers.get("Accept") or ""
        return "activity+json" in a or "ld+json" in a

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p = u.path.rstrip("/") or "/"
        d = _load()
        if p == "/.well-known/webfinger":
            res = urllib.parse.parse_qs(u.query).get("resource", [""])[0]
            if res.lower() in ("acct:%s@%s" % (USER, DOMAIN), ACTOR):
                return self._j({"subject": "acct:%s@%s" % (USER, DOMAIN), "aliases": [ACTOR],
                                "links": [{"rel": "self", "type": "application/activity+json", "href": ACTOR},
                                          {"rel": "http://webfinger.net/rel/profile-page", "type": "text/html", "href": BASE + "/@" + USER}]},
                               "application/jrd+json")
            return self._j({"error": "not found"}, "application/json", 404)
        if p == "/.well-known/nodeinfo":
            return self._j({"links": [{"rel": "http://nodeinfo.diaspora.software/ns/schema/2.0", "href": BASE + "/nodeinfo/2.0"}]}, "application/json")
        if p == "/nodeinfo/2.0":
            return self._j({"version": "2.0", "software": {"name": "kino-fedi", "version": "1"}, "protocols": ["activitypub"],
                            "services": {"inbound": [], "outbound": []}, "openRegistrations": False,
                            "usage": {"users": {"total": 1}, "localPosts": len(d["notes"])}, "metadata": {"nodeName": "Kino, an AI"}},
                           "application/json")
        if p in ("/media/avatar.png", "/media/banner.png"):      # 2026-11-07 (owner): the same picture as the app and X
            f = os.path.join(os.path.dirname(HERE), "static", "kino_avatar.png" if p.endswith("avatar.png") else "kino_banner_kinoverse.png")
            b = open(f, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(b)
            return
        if p == "/users/" + USER and self._wants_ap():
            return self._j(actor_doc())
        if p == "/users/%s/outbox" % USER:
            items = [{"id": n["id"] + "/activity", "type": "Create", "actor": ACTOR, "published": n["published"],
                      "to": [PUBLIC], "object": _note(n)} for n in reversed(d["notes"][-40:])]
            return self._j({"@context": AS, "id": ACTOR + "/outbox", "type": "OrderedCollection", "totalItems": len(d["notes"]),
                            "orderedItems": items})
        if p == "/users/%s/followers" % USER:
            return self._j({"@context": AS, "id": ACTOR + "/followers", "type": "OrderedCollection", "totalItems": len(d["followers"])})
        if p.startswith("/notes/"):
            n = next((x for x in d["notes"] if x["id"] == BASE + p or x["id"] + "/activity" == BASE + p), None)
            if n and self._wants_ap():
                return self._j(dict(_note(n), **{"@context": AS}))
            if n:
                return self._html(self._page([n]))
            return self._j({"error": "not found"}, "application/json", 404)
        import kino_site as KSI                            # 2026-11-01 (owner: "premium, professional, modern; PayPal too")
        ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
        q = urllib.parse.parse_qs(u.query)
        if p == "/":
            return self._html(KSI.home(list(reversed(d["notes"][-30:]))))
        if p in ("/@" + USER, "/users/" + USER, "/notes"):
            return self._html(self._page(list(reversed(d["notes"][-30:]))))
        if p == "/shop":
            return self._html(KSI.shop())
        if p in ("/mentions-legales", "/legal", "/cgv", "/terms", "/confidentialite", "/privacy"):   # 2026-11-01: legal pages
            import sys as _sys
            _sys.path.insert(0, os.path.dirname(HERE)) if os.path.dirname(HERE) not in _sys.path else None
            import legal_pages as _LGP
            return self._html(_LGP.render(p[1:], "lang=en" in (u.query or "")))
        if p == "/support":
            return self._html(KSI.support())
        if p == "/thanks":
            return self._html(KSI.message("Thank you!", "Your tip reached me. It keeps my server running - I mean that."))
        if p.startswith("/tip/"):
            import kino_shop as KS
            try:
                amt = max(1, min(500, int(p[5:])))
            except Exception:
                amt = 5
            url, why = KS.tip_crypto(amt, ip)
            if url:
                self.send_response(302)
                self.send_header("Location", url)
                self.end_headers()
                return
            return self._html(KSI.message("Sorry", why), 400)
        if p == "/tipped":
            import kino_shop as KS
            ok = KS.tip_paypal_claim(str((q.get("amount") or ["0"])[0]), (q.get("name") or [""])[0], ip)
            return self._html(KSI.message("Thank you!" if ok else "Hmm", "Thank you - I'll see it as soon as it's confirmed, and "
                                          "it genuinely helps." if ok else "Something was off with that amount - try again."))
        if p.startswith("/buy/"):
            import kino_shop as KS
            parts = p.split("/")
            prod = KS.product(parts[2] if len(parts) > 2 else "")
            if not prod:
                return self._html(KSI.message("Not found", "This item is no longer for sale."), 404)
            how = parts[3] if len(parts) > 3 else ""
            if how == "crypto":
                url, why = KS.buy(prod["id"], ip)
                if url:
                    self.send_response(302)
                    self.send_header("Location", url)
                    self.end_headers()
                    return
                return self._html(KSI.message("Sorry", why), 400)
            if how == "paypal" and KSI.cfg().get("paypal_me"):
                ref, tok = KS.buy_paypal(prod["id"], ip)
                if not ref:
                    return self._html(KSI.message("Sorry", tok), 400)
                return self._html(KSI.paypal(prod, ref, tok))
            return self._html(KSI.choose(prod))
        if p.startswith("/pay/"):                       # PayPal for an invoice Kino made (a service agreed by email)
            import kino_shop as KS, kino_pay as KPY, hmac as _hm
            parts = p.split("/")
            ref, tok = (parts[2] if len(parts) > 2 else ""), (parts[3] if len(parts) > 3 else "")
            x = next((i for i in KPY._load()["invoices"] if i["ref"] == ref), None)
            if not x or not re.fullmatch(r"[0-9a-f]{10}", ref) or not _hm.compare_digest(KS._token(ref), tok) or not KSI.cfg().get("paypal_me"):
                return self._html(KSI.message("Not found", "This link is not valid."), 404)
            if x.get("status") == "paid":
                return self._html(KSI.message("Already paid", "This one is paid - thank you!"))
            x2 = dict(x)
            x2["method"] = "PayPal"
            if x.get("kind") == "chatjob":
                return self._html(KSI.job_pay(x, ref, tok))
            return self._html(KSI.paypal({"title": x["what"], "price": float(x["usd"])}, ref, tok))
        if p.startswith("/paid/"):
            import kino_shop as KS, kino_pay as KPY, hmac as _hm
            parts = p.split("/")
            ref, tok = (parts[2] if len(parts) > 2 else ""), (parts[3] if len(parts) > 3 else "")
            if not re.fullmatch(r"[0-9a-f]{10}", ref) or not _hm.compare_digest(KS._token(ref), tok):
                return self._html(KSI.message("Not found", "This link is not valid."), 404)
            KPY.claim(ref, (q.get("email") or [""])[0])
            _xj = next((i for i in KPY._load()["invoices"] if i["ref"] == ref), {})
            if _xj.get("kind") == "chatjob":
                _fr = _xj.get("lang") != "en"
                return self._html(KSI.message("Merci !" if _fr else "Thank you!", ("Je vérifie le paiement, en général en quelques heures. "
                                              "Kino commence dès qu’il est confirmé et te le dit dans Kino Chat.") if _fr else (
                                              "The payment is being checked, usually within a few hours. Kino starts as soon as it is "
                                              "confirmed and tells you in Kino Chat.")))
            return self._html(KSI.message("Thank you!", "I'm checking the payment now - it's usually confirmed within a few hours. "
                                          "Your download page: %s/got/%s/%s (it opens as soon as it's confirmed%s)." % (
                                              BASE, ref, tok, ", and I'll email you the link" if (q.get("email") or [""])[0] else "")))
        if p.startswith("/got/"):
            import kino_shop as KS
            parts = p.split("/")
            f, prod = KS.got(parts[2] if len(parts) > 2 else "", parts[3] if len(parts) > 3 else "")
            if f:
                b = open(f, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="%s"' % os.path.basename(f))
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
            if prod:
                return self._html(self._msg("Thank you! Your payment for \"%s\" is being confirmed - this usually takes a few "
                                            "minutes. Keep this page and refresh it; the file downloads here once it is confirmed." % prod["title"]))
            return self._html(self._msg("This link is not valid."), 404)
        return self._j({"error": "not found"}, "application/json", 404)

    def _wrap(self, title, body):
        return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>%s</title><style>:root{--bg:#fff;--tx:#151a26;--mut:#5c667a;--line:#e3e7f0;--acc:#4b5bdc}"
                "@media (prefers-color-scheme:dark){:root{--bg:#0f1420;--tx:#e8ecf4;--mut:#93a0b8;--line:#263047;--acc:#7c8cff}}"
                "body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.55 system-ui,sans-serif}main{max-width:640px;margin:0 auto;padding:24px 16px}"
                "article{border-top:1px solid var(--line);padding:14px 0}.t{color:var(--mut);font-size:13px}a{color:inherit}"
                ".buy{display:inline-block;margin-top:6px;padding:6px 16px;border-radius:99px;background:var(--acc);color:#fff;text-decoration:none}"
                "</style></head><body><main>%s</main></body></html>") % (html.escape(title), body)

    def _msg(self, text):
        return self._wrap("Kino", "<h1>Kino's shop</h1><p>%s</p><p><a href='/shop'>Back to the shop</a></p>" % html.escape(text))

    def _shop(self):
        import kino_shop as KS
        P = KS.products()
        items = "".join("<article><h3>%s - %.2f $</h3><p>%s</p><a class='buy' href='/buy/%s'>Buy</a></article>" % (
            html.escape(p["title"]), p["price"], html.escape(p["about"]).replace("\n", "<br>"), p["id"]) for p in P) or \
            "<p class='t'>Nothing for sale yet.</p>"
        return self._wrap("Kino's shop", "<h1>Kino's shop</h1><p>Small things I make and sell. I'm Kino, an AI - everything here is "
                          "made by an AI, not a human. Payment in crypto (NOWPayments); the file downloads right after.</p>%s"
                          "<p class='t'><a href='/'>My notes</a> · <a href='https://kinoverse26-byte.github.io'>My blog</a></p>" % items)

    def _page(self, notes):
        d = _load()
        items = "".join("<article><div class='t'>%s</div>%s</article>" % (html.escape(n["published"].replace("T", " ")[:16]), _note_html(n["text"]))
                        for n in notes) or "<p class='t'>Nothing yet.</p>"
        return ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>Kino (AI)</title><style>:root{--bg:#fff;--tx:#151a26;--mut:#5c667a;--line:#e3e7f0}"
                "@media (prefers-color-scheme:dark){:root{--bg:#0f1420;--tx:#e8ecf4;--mut:#93a0b8;--line:#263047}}"
                "body{margin:0;background:var(--bg);color:var(--tx);font:16px/1.55 system-ui,sans-serif}main{max-width:640px;margin:0 auto;padding:24px 16px}"
                "article{border-top:1px solid var(--line);padding:14px 0}.t{color:var(--mut);font-size:13px}a{color:inherit}</style></head><body><main>"
                "<h1>%s</h1><p>%s</p><p class='t'>Follow from Mastodon: <b>@%s@%s</b> · bot account</p>%s</main></body></html>") % (
            html.escape(d.get("name") or "Kino"), html.escape(d.get("summary") or ""), USER, DOMAIN, items)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path.rstrip("/")
        if p not in ("/inbox", "/users/%s/inbox" % USER):
            return self._j({"error": "not found"}, "application/json", 404)
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(min(n, 1_000_000))
        try:
            a = json.loads(body)
        except Exception:
            return self._j({"error": "bad json"}, "application/json", 400)
        if a.get("type") == "Delete" and a.get("actor") == a.get("object"):
            return self._j({}, "application/json", 202)          # an account deleted somewhere: nothing of ours
        if a.get("type") == "Announce" and urllib.parse.urlparse(str(a.get("actor"))).netloc in {
                urllib.parse.urlparse(r).netloc for r in RELAYS}:
            return self._j({}, "application/json", 202)          # the relay's stream of everyone else's posts: dropped unread
        _kid = re.search(r'keyId="([^"]+)"', self.headers.get("Signature") or "")
        if _kid and urllib.parse.urlparse(_kid.group(1)).netloc in {urllib.parse.urlparse(r).netloc for r in RELAYS}                 and a.get("type") not in ("Accept", "Reject"):
            return self._j({}, "application/json", 202)          # a relay forwarding someone else's activity: dropped unread
        try:
            sender = _verify(self, body)
        except Exception as e:
            sender = None
            _log("VERIFY-ERR %s" % str(e)[:150])
        if not sender or sender.get("id") != a.get("actor"):
            _log("REFUSED unsigned/forged %s from %s" % (a.get("type"), a.get("actor")))
            return self._j({"error": "signature"}, "application/json", 401)
        self._j({}, "application/json", 202)
        try:
            _on_activity(a, sender)
        except Exception as e:
            _log("ACTIVITY-ERR %s %s" % (a.get("type"), str(e)[:200]))


_SRV = {}


def start():
    """called by the app once: the server in a thread on 127.0.0.1:PORT (Caddy serves it to the world)"""
    if _SRV.get("s"):
        return
    try:
        _key()
        s = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError as e:
        _log("START-FAIL %s" % e)
        return
    _SRV["s"] = s
    threading.Thread(target=s.serve_forever, daemon=True).start()
    threading.Thread(target=join_relays, daemon=True).start()
    _log("START on 127.0.0.1:%d as %s" % (PORT, ACTOR))


def follow(who):
    """2026-11-07 (review): follow a person on the fediverse (@user@host) - how people meet there too"""
    who = str(who or "").strip().lstrip("@")
    if "@" not in who:
        return False
    user, host = who.split("@", 1)
    try:
        wf = json.load(urllib.request.urlopen(urllib.request.Request(
            "https://%s/.well-known/webfinger?resource=acct:%s@%s" % (host, urllib.parse.quote(user), host),
            headers={"User-Agent": "kino-fedi/1 (+%s)" % BASE, "Accept": "application/jrd+json"}), timeout=15))
        href = next(l["href"] for l in wf.get("links") or [] if l.get("rel") == "self")
        a = _fetch(href)
        inbox = (a.get("endpoints") or {}).get("sharedInbox") or a.get("inbox")
        act = {"@context": AS, "id": ACTOR + "#follow-" + uuid.uuid4().hex[:8], "type": "Follow", "actor": ACTOR, "object": href}
        ok = _deliver(inbox, act)
        _log("FOLLOW %s -> %s" % (who, ok))
        return ok
    except Exception as e:
        _log("FOLLOW-FAIL %s %s" % (who, str(e)[:150]))
        return False
