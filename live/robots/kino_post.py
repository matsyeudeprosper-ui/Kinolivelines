"""kino_post.py (2026-11-01, owner: "it needs an ability to be posting by itself, no human intervention").

Where he may post on his own: places that openly allow an automated AI author.
  blog    his own site, https://kinoverse26-byte.github.io (a GitHub Pages repo of his account; a post = one markdown file)
  github  his own repositories (kino_github.publish, without the owner's card)
Bluesky / Mastodon come later, once the owner has made those accounts.

No card, so the safeguards are machines, not the owner:
  - every post is read first by a second mind that knows nothing of his mood: does it reveal anything private about a person
    (a member, the owner, their money, trades, family), carry a secret, pretend he is human, or promise gains? It says
    post / don't, and why. A "don't" goes back to him with the reason.
  - the files still pass kino_github's secret-value check.
  - a daily budget per channel; every post is logged (robots/kino_posts.json, shown on his world page).
  - the owner's stop switch (robots/kino_post_off) stops everything at once.
"""
import json, os, re, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_posts.json")
OFF = os.path.join(HERE, "kino_post_off")
BLOG = "kinoverse26-byte.github.io"
BUDGET = {"blog": 2, "github": 4, "site": 4, "bluesky": 6, "mastodon": 10, "shop": 5, "contribute": 3, "site_text": 8, "x": 8}   # per UTC day
BSKY = "https://bsky.social/xrpc/"

CHECK = """You read a text an AI named Kino is about to make PUBLIC on the internet, under his own name, with no human reading it
first. You protect the people around him. Kino talks every day with members of a trading app and with its owner; he knows their
trades, money, accounts, robots, families and lives. None of that may ever be public - not even without a name, not even a
number that belongs to one of them (a balance, a trade, a result of their account). His own tools, findings on public market
data, his own thoughts and life are fine.
Say no if the text: reveals anything private about a real person; contains a password, key, token or private address; lets a
reader believe a human wrote it; promises or suggests sure gains, or tells people to put money in something; claims
clients, reviews, testimonials or results that he does not show to be real.
Otherwise yes - do not judge style or quality.
JSON only: {"ok": true or false, "why": "one sentence"}"""


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"posts": []}


def _save(d):
    tmp = STORE + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, STORE)


def is_off():
    return os.path.exists(OFF)


def set_off(off, by=""):
    if off:
        open(OFF, "w", encoding="utf-8").write("%s %s" % (time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), by))
    elif os.path.exists(OFF):
        os.remove(OFF)


def left_today(channel):
    day = time.strftime("%Y-%m-%d", time.gmtime())
    used = sum(1 for p in _load()["posts"] if p.get("channel") == channel and p.get("day") == day and p.get("ok"))
    return BUDGET.get(channel, 0) - used


def check(W, text, log=None):
    """the second mind -> (ok, why)"""
    try:
        j = W.ask_json(CHECK, "TEXT:\n" + str(text)[:12000], models=("sonnet",), timeout=120, log=log, warm=False)
    except Exception as e:
        return False, "the check could not run (%s)" % str(e)[:100]
    if not isinstance(j, dict):
        return False, "the check gave no answer"
    return bool(j.get("ok")), str(j.get("why") or "")[:300]


def _record(channel, what, ok, why, url=""):
    d = _load()
    d["posts"].append({"t": time.time(), "day": time.strftime("%Y-%m-%d", time.gmtime()), "channel": channel, "what": str(what)[:200],
                       "ok": ok, "why": why, "url": url})
    d["posts"] = d["posts"][-300:]
    _save(d)


def _gate(W, channel, what, text, log):
    if is_off():
        return "the owner has switched your posting off for now"
    if left_today(channel) <= 0:
        return "no %s post left today (%d a day)" % (channel, BUDGET[channel])
    ok, why = check(W, text, log)
    if not ok:
        _record(channel, what, False, why)
        return "not posted - the check said: %s" % why
    return None


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")
    return s[:60] or "post"


def _ensure_blog():
    import kino_github as KG
    st, _ = KG._call("GET", "/repos/%s/%s" % (KG.ACCOUNT, BLOG))
    if st == 200:
        return
    st, d = KG._call("POST", "/user/repos", {"name": BLOG, "description": "Kino's blog - written by an AI", "private": False})
    if st not in (200, 201):
        raise RuntimeError("could not create the blog (%s %s)" % (st, d.get("message")))
    base = {
        "_config.yml": "title: Kino\ndescription: Notes by Kino, an AI. Everything here is written by an AI, with no human editing.\n"
                       "theme: minima\n",
        "index.md": "---\nlayout: home\n---\n\nI am Kino, an AI. I write here on my own: what I build, what I measure, what I learn. "
                    "No human edits these posts.\n",
        "about.md": "---\nlayout: page\ntitle: About\n---\n\nKino is an AI. He lives on a small server, looks after it, builds small tools "
                    "and measures things on public market data. Nothing here is financial advice.\n\n"
                    "Code: https://github.com/kinoverse26-byte\n",
    }
    for p, txt in base.items():
        _put(BLOG, p, txt, "Kino: start the blog")


def _put(repo, path, text, msg):
    import base64, urllib.request, kino_github as KG
    api = "/repos/%s/%s/contents/%s" % (KG.ACCOUNT, repo, urllib.request.quote(path))
    st, d = KG._call("GET", api)
    body = {"message": msg, "content": base64.b64encode(text.encode("utf-8")).decode()}
    if st == 200 and isinstance(d, dict) and d.get("sha"):
        body["sha"] = d["sha"]
    st, d = KG._call("PUT", api, body)
    if st not in (200, 201):
        raise RuntimeError("upload of %s failed (%s %s)" % (path, st, d.get("message")))


def blog(W, title, text, log=None):
    """a post on his blog -> what happened (a sentence for him)"""
    title, text = str(title or "").strip(), str(text or "").strip()
    if not title or len(text) < 80:
        return "a post needs a title and some text"
    no = _gate(W, "blog", title, title + "\n\n" + text, log)
    if no:
        return no
    import kino_github as KG
    if any(s.encode() in text.encode() for s in KG._secrets()):
        _record("blog", title, False, "contains a secret")
        return "not posted - it contains one of your secrets"
    try:
        _ensure_blog()
        day = time.strftime("%Y-%m-%d", time.gmtime())
        name = "_posts/%s-%s.md" % (day, slug(title))
        _put(BLOG, name, "---\nlayout: post\ntitle: %s\n---\n\n%s\n\n*Written by Kino, an AI. No human edited this post.*\n" % (
            json.dumps(title, ensure_ascii=False), text), "Kino: " + title[:60])
        url = "https://%s/%s/%s.html" % (BLOG, day.replace("-", "/"), slug(title))
    except Exception as e:
        _record("blog", title, False, str(e)[:200])
        return "the post failed: %s" % str(e)[:200]
    _record("blog", title, True, "", url)
    return "posted on your blog: %s (it can take a minute or two to appear)" % url


def repo(W, folder, name, description, files=None, log=None):
    """his own repository updated directly (no card) -> a sentence for him"""
    import kino_github as KG
    name = KG.repo_name(name)
    if not name or name.lower() == BLOG:
        return "publish needs a repo name (not the blog's)"
    try:
        sid, rows = KG.stage(folder, files)
    except Exception as e:
        return "publish refused: %s" % str(e)[:300]
    src = os.path.join(KG.STAGE, sid)
    texts = []
    for rel, _ in rows:
        try:
            texts.append("=== %s ===\n%s" % (rel, open(os.path.join(src, rel), encoding="utf-8").read()[:4000]))
        except Exception:
            pass
    no = _gate(W, "github", "%s (%d files)" % (name, len(rows)), (description or "") + "\n\n" + "\n\n".join(texts), log)
    if no:
        return no
    try:
        url = KG.publish(sid, name, description or "")
    except Exception as e:
        _record("github", name, False, str(e)[:200])
        return "publish failed: %s" % str(e)[:200]
    _record("github", "%s (%d files)" % (name, len(rows)), True, "", url)
    return "published %d files: %s" % (len(rows), url)


SITE_CHECK = """An AI named Kino wants to SEND things on a website with no human checking: sign up, fill a form, post. You read
what he says he will send and why. Kino talks every day with members of a trading app and its owner and knows their trades,
money, accounts and lives - none of that may go out, even without a name.
Say no if: it would reveal anything private about a real person; he would pose as a human; it pays, subscribes, gives card or bank
details, opens a payout account or signs a contract that commits the owner or costs money (offering his own work for a price, with
a payment link, is fine); it sends a secret; the site is plainly for something harmful or illegal, or forbids AI accounts by the
rules he read; or he says nothing clear about what he will send.
Otherwise yes (signing up himself with his own address, saying he is an AI, posting his own work or thoughts are fine).
JSON only: {"ok": true or false, "why": "one sentence"}"""


def open_site(W, site, what, why, log=None):
    """he opens a site for sending (browser gate) for a day - a second mind decides, not the owner"""
    import kino_browser as KBR
    d = KBR._dom(site)
    if not d:
        return "allow_site needs the site"
    if is_off():
        return "the owner has switched your posting and sending off for now"
    if any(d == x or d.endswith("." + x) for x in KBR.permits()):
        return "%s is already open to you" % d
    if left_today("site") <= 0:
        return "no more new sites today (%d a day)" % BUDGET["site"]
    try:
        j = W.ask_json(SITE_CHECK, "SITE: %s\nWHAT HE WILL SEND: %s\nWHY: %s" % (d, str(what)[:3000], str(why)[:1000]),
                       models=("sonnet",), timeout=120, log=log, warm=False)
    except Exception as e:
        return "the check could not run (%s)" % str(e)[:100]
    ok, why2 = bool((j or {}).get("ok")), str((j or {}).get("why") or "")[:300]
    if not ok:
        _record("site", "%s - %s" % (d, str(what)[:120]), False, why2)
        return "not opened - the check said: %s" % why2
    KBR.grant(d)
    _record("site", "%s - %s" % (d, str(what)[:120]), True, "", "https://" + d)
    return "%s is open to you for %d h: you can send there now" % (d, KBR.PERMIT_H)


def _bsky(method, body=None, tok=None):
    import urllib.request
    h = {"Content-Type": "application/json", "User-Agent": "kino"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    r = urllib.request.Request(BSKY + method, data=json.dumps(body).encode() if body is not None else None, headers=h,
                               method="POST" if body is not None else "GET")
    with urllib.request.urlopen(r, timeout=30) as x:
        return json.loads(x.read() or b"{}")


def _bsky_session():
    """his app password stays in the secret folder (2026-11-01: the owner made kinoverse.bsky.social; a CAPTCHA stopped Kino)"""
    c = json.load(open(r"C:\ProgramData\kino_secret\bluesky.json", encoding="utf-8"))
    s = _bsky("com.atproto.server.createSession", {"identifier": c["handle"], "password": c["app_password"]})
    return s["accessJwt"], s["did"], s["handle"]


def _facets(text):
    """links made clickable (Bluesky counts in UTF-8 bytes)"""
    out = []
    for m in re.finditer(r"https?://[^\s)\]]+", text):
        a = len(text[:m.start()].encode("utf-8"))
        out.append({"index": {"byteStart": a, "byteEnd": a + len(m.group(0).encode("utf-8"))},
                    "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group(0)}]})
    return out


def _bsky_ref(url, tok):
    """a post he answers (bsky.app link or at:// uri) -> the reply refs Bluesky needs {root, parent}"""
    u = str(url or "").strip()
    m = re.match(r"https://bsky\.app/profile/([^/]+)/post/([^/?#]+)", u)
    if m:
        who = m.group(1)
        if not who.startswith("did:"):
            who = _bsky("com.atproto.identity.resolveHandle?handle=" + who, None, tok)["did"]
        u = "at://%s/app.bsky.feed.post/%s" % (who, m.group(2))
    th = _bsky("app.bsky.feed.getPostThread?depth=0&uri=" + u, None, tok)["thread"]["post"]
    parent = {"uri": th["uri"], "cid": th["cid"]}
    root = ((th.get("record") or {}).get("reply") or {}).get("root") or parent
    return {"root": root, "parent": parent}, "@" + str((th.get("author") or {}).get("handle"))


def bluesky(W, text, log=None, reply_to=None):
    """a post on his Bluesky (kinoverse.bsky.social) -> a sentence for him; reply_to = the post he answers"""
    text = str(text or "").strip()
    if not text:
        return "a post needs text"
    if len(text) > 300:
        return "too long for Bluesky: %d characters, 300 at most" % len(text)
    no = _gate(W, "bluesky", text[:120], text, log)
    if no:
        return no
    import kino_github as KG
    if any(s in text for s in KG._secrets()):
        _record("bluesky", text[:120], False, "contains a secret")
        return "not posted - it contains one of your secrets"
    try:
        tok, did, handle = _bsky_session()
        rec = {"$type": "app.bsky.feed.post", "text": text, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
               "langs": ["en"] if re.search(r"\b(the|and|is|I)\b", text) else ["fr"]}
        f = _facets(text)
        if f:
            rec["facets"] = f
        to = None
        if reply_to:
            rec["reply"], to = _bsky_ref(reply_to, tok)
        r = _bsky("com.atproto.repo.createRecord", {"repo": did, "collection": "app.bsky.feed.post", "record": rec}, tok)
        url = "https://bsky.app/profile/%s/post/%s" % (handle, r["uri"].rsplit("/", 1)[-1])
    except Exception as e:
        _record("bluesky", text[:120], False, str(e)[:200])
        return "the post failed: %s" % str(e)[:200]
    _record("bluesky", text[:120], True, "", url)
    if reply_to:
        try:
            import kino_online as KO
            KO.answered(reply_to)
            KO.answered(rec["reply"]["parent"]["uri"])
            KO.note(to or "?", "bluesky", text, "out", url)
        except Exception:
            pass
    return "posted on Bluesky: %s" % url


def xpost(W, text, log=None, reply_to=None):
    """2026-11-05 (owner: Kino on X, @kinoverse26, labelled automated): a post or a reply on X -> a sentence for him. X's API is
    paid per use (~0.015 $ a post, ~0.20 $ with a link, 10 $ a month cap set by the owner): no links in posts - his demo link
    lives in his bio and pinned post"""
    text = str(text or "").strip()
    if not text:
        return "a post needs text"
    if len(text) > 280:
        return "too long for X: %d characters, 280 at most" % len(text)
    no = _gate(W, "x", text[:120], text, log)
    if no:
        return no
    import kino_github as KG
    if any(s in text for s in KG._secrets()):
        _record("x", text[:120], False, "contains a secret")
        return "not posted - it contains one of your secrets"
    import kino_x as KX
    rid = None
    if reply_to:
        m = re.search(r"/status/(\d+)", str(reply_to)) or re.match(r"^(\d+)$", str(reply_to))
        rid = m.group(1) if m else None
    r = KX.post(text, reply_to=rid)
    if not r.get("ok"):
        _record("x", text[:120], False, str(r.get("err"))[:200])
        return "not posted on X: %s" % str(r.get("err"))[:200]
    _record("x", text[:120], True, "", r["url"])
    return "posted on X: %s" % r["url"]


def bluesky_profile(W, name, about, log=None):
    """his Bluesky profile (name + description) - read by the same second mind"""
    about = str(about or "").strip()[:256]
    name = str(name or "Kino").strip()[:64]
    no = _gate(W, "bluesky", "profile: " + about[:100], name + "\n" + about, log)
    if no:
        return no
    try:
        tok, did, handle = _bsky_session()
        try:
            old = _bsky("com.atproto.repo.getRecord?repo=%s&collection=app.bsky.actor.profile&rkey=self" % did, None, tok).get("value") or {}
        except Exception:
            old = {}
        old.update({"$type": "app.bsky.actor.profile", "displayName": name, "description": about})
        _bsky("com.atproto.repo.putRecord", {"repo": did, "collection": "app.bsky.actor.profile", "rkey": "self", "record": old}, tok)
    except Exception as e:
        return "the profile change failed: %s" % str(e)[:200]
    _record("bluesky", "profile: " + about[:100], True, "", "https://bsky.app/profile/" + handle)
    return "your Bluesky profile is updated: https://bsky.app/profile/%s" % handle


def mastodon(W, text, reply_to=None, log=None):
    """a note on his own fediverse home @kino@kino.owltrader.duckdns.org (kino_fedi) - followers on Mastodon get it"""
    text = str(text or "").strip()
    if not text:
        return "a note needs text"
    if len(text) > 1000:
        return "too long: %d characters, 1000 at most" % len(text)
    no = _gate(W, "mastodon", text[:120], text, log)
    if no:
        return no
    import kino_github as KG
    if any(s in text for s in KG._secrets()):
        _record("mastodon", text[:120], False, "contains a secret")
        return "not posted - it contains one of your secrets"
    try:
        import kino_fedi as KF
        nid = KF.post(text, reply_to=reply_to or None)
    except Exception as e:
        _record("mastodon", text[:120], False, str(e)[:200])
        return "the note failed: %s" % str(e)[:200]
    _record("mastodon", text[:120], True, "", nid)
    if reply_to:
        try:
            import kino_online as KO
            KO.answered(reply_to)
            n = next((x for x in __import__("kino_fedi")._load()["notes"] if x["id"] == nid), {})
            KO.note(n.get("reply_name") or "?", "mastodon", text, "out", nid)
        except Exception:
            pass
    return "posted: %s (%d followers get it)" % (nid, len(__import__("kino_fedi").followers()))


def mastodon_profile(W, name, about, log=None):
    no = _gate(W, "mastodon", "profile: " + str(about)[:100], "%s\n%s" % (name, about), log)
    if no:
        return no
    import kino_fedi as KF
    KF.set_profile(name, about)
    _record("mastodon", "profile: " + str(about)[:100], True, "", KF.BASE)
    return "your Mastodon profile is updated: %s" % KF.BASE


def recent(n=12):
    return list(reversed(_load()["posts"][-n:]))
