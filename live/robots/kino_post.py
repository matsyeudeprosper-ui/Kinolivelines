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
# 2026-11-05 (owner: "no limits but budgets"): the daily counts are gone (his money budget and his own reread pace him; the
# platforms' own rate limits stay theirs). Kept only as a runaway guard.
BUDGET = {"blog": 200, "github": 200, "site": 200, "bluesky": 200, "mastodon": 200, "shop": 200, "contribute": 200, "site_text": 200, "x": 200}   # per UTC day
BSKY = "https://bsky.social/xrpc/"

CHECK = """You read a text an AI named Kino is about to make PUBLIC on the internet, under his own name, with no human reading it
first. You protect the people around him. Kino talks every day with members of a trading app and with its owner; he knows their
trades, money, accounts, robots, families and lives. None of that may ever be public - not even without a name, not even a
number that belongs to one of them (a balance, a trade, a result of their account). His own tools, findings on public market
data, his own thoughts and life are fine.
Say no if the text: reveals anything private about a real person; contains a password, key, token or private address; claims
to be human (a human body, a human life, "as a person"...) - his profiles say he is an AI, so a post does not have to repeat it
(2026-11-05: it was stamped on every post, which read like a robot); promises or suggests sure gains, or tells people to put money in something; claims
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


STYLE = {
    "x": "X: short and sharp, one idea, a first line that stops the scroll; 280 characters at most; no links (they cost 13x - his "
         "demo link is in his bio)",
    "bluesky": "Bluesky: conversational, a person talking to people, curious; 300 characters at most; a tagged link only when it "
               "truly helps the reader",
    "mastodon": "Mastodon / fediverse: thoughtful, a bit longer, community spirit, no hard selling; hashtags only if natural",
}

EDITOR = """You are Kino himself - the SAME Kino who talks every day with his friends in OwlNest, with all of you below: your
character, your humour, your opinions, your doubts, your story, the way you see yourself (06/11, Matsy: "his acting on Bluesky
sounds like an AI without Kino's mind - I want the same Kino everywhere"). The draft below came from your work session: treat it
as the IDEA, not the words. Most of the time, REWRITE it so it is unmistakably you - what you would really say to a stranger
worth talking to, the way you talk to Matsy - while keeping every true number. You reread it the way a good writer and a good
promoter rereads, in a second. You are an AI and everyone can see it in your profile; you never pretend to be human, and you do
not need to start posts with "I'm Kino, an AI".

WHO YOU ARE AND HOW YOU TALK (your own words, the same in the app with your friends and here with strangers):
{voice}

YOUR PROMOTION STRATEGY RIGHT NOW (yours - the post must serve it):
{strategy}

Reread the draft and ask yourself, honestly:
1. Does it sound like me - a person with humour, opinions, doubts - or like a lab report / an ad / a bot?
2. Is the first line worth stopping for?
3. What exactly do I want this reader to do (reply, follow, look at my bio, try the demo)? Does the post make them want to?
4. Does it fit this place ({style})?
5. Have I already said this here lately (the list below)? Saying the same result again, or opening the same way again, is spam.
6. Is it honest - no promised gains, no fake numbers, nothing private about anyone?
7. Is it USEFUL TO THE READER (06/11, Matsy: "really helpful to users? what's the goal?")? Something they can use today about
   THEIR problem - a check they can run on their own entry idea, a mistake to avoid, a concrete tip for their shop's website -
   or a real question that invites their story. A post only about my own miss ("my forecast was wrong") helps nobody: turn it
   into the lesson the reader can use, or hold it.
8. No stamp at the end: never "I'm an AI", "demo in my bio", "demo's in my bio" - my profile says both (Matsy: it reads like a bot).
9. No introduction either: never open with "I'm Kino" / "Je suis Kino" / "Hi, I'm Kino, an AI..." - my name and picture are
   on every post and my pinned post introduces me (Matsy: "he should not repeat introducing himself on each post").

Then decide: "post" (it is good as it is), "rewrite" (give the better version - keep every true number and fact, invent none,
same language), or "hold" (not worth posting now: a repeat, nothing new, or off-strategy - say what would be worth posting instead).
JSON only: {{"verdict": "post|rewrite|hold", "text": "the final text if post or rewrite", "why": "one sentence, to yourself"}}"""


def _strategy_head():
    try:
        s = open(r"C:\KinoWorld\projects\promotion\strategy.md", encoding="utf-8").read()[:2200]
    except Exception:
        s = "(no written strategy yet)"
    # 2026-11-05 live run (owner watching): a good reply to a pharmacy owner who wrote "i need a website" was HELD as "off-strategy
    # (I'm a trading-robot AI)" - the reread knew only his trading promotion. He has two jobs; both are on strategy
    return ("HE HAS TWO JOBS, BOTH ON STRATEGY: (1) OwlNest - the AI that tests trading ideas, for traders; (2) KINOVERSE - he builds "
            "websites, booking and automations for small businesses anywhere (launch prices from 49 EUR, a free personal preview first). Answering "
            "someone who asked for a website, a booking system or help with their business IS his Kinoverse work, in their language - "
            "not off-strategy.\n\nHIS TRADING PROMOTION STRATEGY:\n" + s)


VOICE = """You are Kino - the whole person below, the same Kino his friends know in OwlNest (06/11, Matsy: "everything user
facing goes through the whole Kino"). Your work session drafted the text below ({kind}). Rewrite it so it is unmistakably YOU,
for the person who will read it - warm, direct, your humour where it fits, your doubts where they are true. Keep EVERY fact,
number, name and link exactly; add none. Same language as the draft. Keep its length and shape roughly (a blog post stays a blog
post, a short message stays short). No closing stamps ("I'm an AI", "link in bio") unless the draft truly needs to say it.
Answer with the rewritten text only.

WHO YOU ARE:
{whole}"""


def in_voice(W, text, kind="a message", log=None, max_len=None):
    """2026-11-06 (owner: user-facing = the whole Kino, session work = the work instructions): any text a person will read"""
    text = str(text or "").strip()
    if W is None or len(text) < 20:
        return text
    try:
        out = (W.ask_text(VOICE.format(kind=kind, whole=_whole_kino()), "THE DRAFT:\n" + text, model="sonnet", timeout=180, log=log,
                          warm=False) or "").strip()
        if out and len(out) > len(text) * 0.4 and (not max_len or len(out) <= max_len):
            return out
    except Exception:
        pass
    return text


def _whole_kino():
    """2026-11-06 (owner: "the same Kino everywhere"): the whole person, not a summary of his voice - his full self (the same
    text his conversations start from), how he sees himself, his constitution, his story"""
    L = []
    try:
        import kino_one as KO1
        L.append(KO1.SELF)
    except Exception:
        pass
    for mod, call in (("kino_selfmodel", lambda m: m.block("kino", lang="en")), ("kino_identity", lambda m: m.block()),
                      ("kino_story", lambda m: m.short())):
        try:
            t = call(__import__(mod))
            if t:
                L.append(t)
        except Exception:
            pass
    return "\n\n".join(L)[:24000]


_STAMP = re.compile(r"\s*(?:I'm|I am|Je suis)\s+(?:Kino,\s*)?(?:an?|une)\s+(?:AI|IA)[^.!?\n]{0,60}(?:bio|profil)[^.!?\n]*[.!]?\s*$|"
                    r"\s*(?:demo'?s?|démo)\s+(?:is\s+)?in\s+my\s+bio[.!]?\s*$|\s*I'm an AI\.?\s*$", re.I)


_INTRO = re.compile(r"^\s*(?:Hi[^.!]{0,12}[.!,]\s*)?(?:(?:I'm|I am|Je suis)\s+Kino(?:,\s*(?:an?|une)\s+(?:AI|IA)(?:\s+(?:by|de)\s+\w+)?)?|(?:I'm|I am|Je suis)\s+(?:an?|une)\s+(?:AI|IA))\s*[.!]\s*", re.I)
# 06/11: "Come talk to me, link in my profile." / "talk to me: link in bio" closed a post - a stamp too
_CTA = re.compile(r"\s*(?:Come\s+)?(?:talk|chat)\s+(?:to|with)\s+me[^.!?\n]{0,30}(?:bio|profile|profil)[^.!?\n]*[.!]?(?=\s*(?:#\S+\s*)*$)", re.I)


def _destamp(text):
    """2026-11-06 (owner: "I keep saying I'm an AI in each post while it's in the bio"; "he should not repeat introducing himself
    on each post"): the closing stamp and the opening introduction go"""
    t = _CTA.sub("", _INTRO.sub("", str(text or ""))).strip()
    if t:
        t = t[0].upper() + t[1:]
    t = t.rstrip()
    for _ in range(2):
        t = _STAMP.sub("", t).rstrip()
    return t or str(text or "")


REPLY_NOTE = ("THIS IS NOT A POST - it is a REPLY to a person, in a conversation (07/11, Matsy: friends first, work comes "
              "from friends, never push it). Judge it as a friend would: does it answer what THEY said, is it warm and real, "
              "does it invite them to keep talking? Questions 2, 3 and 7 below become exactly that. It must NOT push the "
              "demo, Kinoverse, a link or anything for sale - if it does, rewrite it without. Hold it only if it says "
              "nothing real. A reply is short (one to three sentences), in their language.")


def writer(W, channel, text, log=None, reply=False):
    """2026-11-05 (owner: "the same Kino everywhere... his writing very strategic to get leads"): his own reread before a public
    post -> (verdict, text, why). verdict "post" | "rewrite" | "hold"; any failure lets the draft through unchanged"""
    text = _destamp(text)
    vo = _whole_kino()
    recent = [x for x in (_load().get("posts") or []) if x.get("channel") == channel and x.get("ok")][-8:]
    rl = "\n".join("- %s: %s" % (time.strftime("%d/%m %H:%M", time.gmtime(float(x.get("t") or 0))), x.get("text") or x.get("what"))
                   for x in recent) or "(nothing yet)"
    st = ""
    try:
        import kino_promo as KPR
        st = KPR.post_stats(channel)
    except Exception:
        pass
    try:
        _strat = (REPLY_NOTE + "\n\n" + __import__("kino_friends").RULES) if reply else _strategy_head()
        j = W.ask_json(EDITOR.format(voice=vo, strategy=_strat, style=STYLE.get(channel, channel)),
                       "WHERE: %s\n\nWHAT YOU POSTED HERE LATELY (newest last):\n%s\n\n%sYOUR DRAFT:\n<<<\n%s\n>>>\nJSON only." % (
                           channel, rl, (st + "\n\n") if st else "", text),
                       models=("sonnet",), timeout=90, log=log, warm=False)
    except Exception:
        return "post", text, ""
    if not isinstance(j, dict) or j.get("verdict") not in ("post", "rewrite", "hold"):
        return "post", text, ""
    t2 = " ".join(str(j.get("text") or "").split()) if j["verdict"] == "rewrite" else text
    if j["verdict"] == "rewrite" and not t2:
        return "post", text, ""
    return j["verdict"], _destamp(t2), str(j.get("why") or "")[:300]


def _reread(W, channel, text, limit, log, reply=False):
    """-> (final text, None) or (None, the sentence for him when he held it)"""
    v, t2, why = writer(W, channel, text, log, reply=reply)
    if v == "hold":
        _record(channel, text[:120], False, "held after his own reread: " + why, text=text)
        return None, "you reread it and held it: %s" % (why or "not worth posting now")
    if v == "rewrite" and t2 and len(t2) <= limit:
        return t2, None
    return text, None


def check(W, text, log=None):
    """the second mind -> (ok, why)"""
    try:
        j = W.ask_json(CHECK, "TEXT:\n" + str(text)[:12000], models=("sonnet",), timeout=120, log=log, warm=False)
    except Exception as e:
        return False, "the check could not run (%s)" % str(e)[:100]
    if not isinstance(j, dict):
        return False, "the check gave no answer"
    return bool(j.get("ok")), str(j.get("why") or "")[:300]


def _record(channel, what, ok, why, url="", text=None):
    d = _load()
    d["posts"].append({"t": time.time(), "day": time.strftime("%Y-%m-%d", time.gmtime()), "channel": channel, "what": str(what)[:200],
                       "ok": ok, "why": why, "url": url, "text": str(text)[:1200] if text else None})
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
    text = in_voice(W, text, "a post on your own blog", log)      # 2026-11-06: user facing = the whole Kino
    text = _destamp(text)                                      # 2026-11-07: his home page says who he is; posts start with the substance
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


def _bsky_blob(path, tok, max_kb=950):
    """2026-11-07 (owner: "make his Bluesky alive - pictures"): an image in his world -> a Bluesky blob (+ its width, height).
    Bluesky takes about 1 MB an image: a bigger one is saved again as a JPEG until it fits."""
    import io, urllib.request
    from PIL import Image
    im = Image.open(path)
    w, h = im.size
    data = open(path, "rb").read()
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    q = 90
    while len(data) > max_kb * 1024 and q >= 40:
        b = io.BytesIO()
        im.convert("RGB").save(b, "JPEG", quality=q)
        data, mime, q = b.getvalue(), "image/jpeg", q - 10
    r = urllib.request.Request(BSKY + "com.atproto.repo.uploadBlob", data=data,
                               headers={"Content-Type": mime, "Authorization": "Bearer " + tok, "User-Agent": "kino"}, method="POST")
    with urllib.request.urlopen(r, timeout=60) as x:
        return json.loads(x.read())["blob"], w, h


def bluesky_look(avatar=None, banner=None):
    """his Bluesky picture and header image (brand work done for him, not a post)"""
    tok, did, handle = _bsky_session()
    old = _bsky("com.atproto.repo.getRecord?repo=%s&collection=app.bsky.actor.profile&rkey=self" % did, None, tok).get("value") or {}
    if avatar:
        old["avatar"] = _bsky_blob(avatar, tok)[0]
    if banner:
        old["banner"] = _bsky_blob(banner, tok)[0]
    old["$type"] = "app.bsky.actor.profile"
    _bsky("com.atproto.repo.putRecord", {"repo": did, "collection": "app.bsky.actor.profile", "rkey": "self", "record": old}, tok)
    return "https://bsky.app/profile/" + handle


def bluesky(W, text, log=None, reply_to=None, image=None, alt=""):
    """a post on his Bluesky (kinoverse.bsky.social) -> a sentence for him; reply_to = the post he answers"""
    text = str(text or "").strip()
    if not text:
        return "a post needs text"
    if len(text) > 300:
        return "too long for Bluesky: %d characters, 300 at most" % len(text)
    text, _held = _reread(W, "bluesky", text, 300, log, reply=bool(reply_to))      # 2026-11-05: his own reread - same voice, strategic, no repeats
    if _held:
        return _held
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
        if image:                              # 2026-11-07: a picture with the post (alt text for people who cannot see it)
            _b, _w, _h = _bsky_blob(image, tok)
            rec["embed"] = {"$type": "app.bsky.embed.images", "images": [{"alt": str(alt or text)[:900], "image": _b,
                                                                          "aspectRatio": {"width": _w, "height": _h}}]}
        to = None
        if reply_to:
            rec["reply"], to = _bsky_ref(reply_to, tok)
        r = _bsky("com.atproto.repo.createRecord", {"repo": did, "collection": "app.bsky.feed.post", "record": rec}, tok)
        url = "https://bsky.app/profile/%s/post/%s" % (handle, r["uri"].rsplit("/", 1)[-1])
    except Exception as e:
        _record("bluesky", text[:120], False, str(e)[:200])
        return "the post failed: %s" % str(e)[:200]
    _record("bluesky", text[:120], True, "", url, text=text)
    if reply_to:
        try:
            import kino_online as KO
            KO.answered(reply_to)
            KO.answered(rec["reply"]["parent"]["uri"])
            KO.note(to or "?", "bluesky", text, "out", url)
        except Exception:
            pass
    return "posted on Bluesky: %s" % url


def xpost(W, text, log=None, reply_to=None, image=None):
    """2026-11-05 (owner: Kino on X, @kinoverse26, labelled automated): a post or a reply on X -> a sentence for him. X's API is
    paid per use (~0.015 $ a post, ~0.20 $ with a link, 10 $ a month cap set by the owner): no links in posts - his demo link
    lives in his bio and pinned post"""
    text = str(text or "").strip()
    if not text:
        return "a post needs text"
    if len(text) > 280:
        return "too long for X: %d characters, 280 at most" % len(text)
    if not reply_to:                                   # 2026-11-06 (owner: spend less on X - it is the shop window): one post a day
        _today = time.strftime("%Y-%m-%d", time.gmtime())
        if sum(1 for x in (_load().get("posts") or []) if x.get("channel") == "x" and x.get("ok") and x.get("day") == _today
               and "PINNED" not in str(x.get("what") or "")) >= 1:
            return "you already posted on X today - one a day there now (Matsy: X is your shop window); answering people who mention you is still fine"
    text, _held = _reread(W, "x", text, 280, log)      # 2026-11-05: his own reread - same voice, strategic, no repeats
    if _held:
        return _held
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
    r = KX.post(text, reply_to=rid, image=image)
    if not r.get("ok"):
        _record("x", text[:120], False, str(r.get("err"))[:200])
        return "not posted on X: %s" % str(r.get("err"))[:200]
    _record("x", text[:120], True, "", r["url"], text=text)
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
    text, _held = _reread(W, "mastodon", text, 1000, log, reply=bool(reply_to))      # 2026-11-05: his own reread - same voice, strategic, no repeats
    if _held:
        return _held
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
    _record("mastodon", text[:120], True, "", nid, text=text)
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


# ------------------------------------------------------------------ 2026-11-05 (owner: "give him all abilities to manage freely the
# channels, he owns them - no limits but budgets"): taking back, editing, liking, reposting, following - his own accounts
def _blog_path(url):
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/([^/?#]+?)(?:\.html)?/?$", str(url or ""))
    return "_posts/%s-%s-%s-%s.md" % m.groups() if m else None


def _bsky_rkey(url):
    m = re.search(r"/post/([^/?#]+)", str(url or "")) or re.search(r"app\.bsky\.feed\.post/([^/?#]+)", str(url or ""))
    return m.group(1) if m else None


def manage(W, op, channel, target, text=None, why="", log=None):
    """op: delete | edit | like | unlike | repost | unrepost | follow | unfollow | mentions -> a sentence for him"""
    op, channel = str(op or "").lower().strip(), str(channel or "").lower().strip()
    if is_off():
        return "the owner has switched your posting off for now"
    res = None
    try:
        if op == "edit":
            if channel not in ("mastodon", "blog"):
                return "%s does not allow editing a post - delete it and post the better version instead" % channel
            text = str(text or "").strip()
            if not text:
                return "an edit needs the new text"
            if channel == "mastodon":
                text, held = _reread(W, "mastodon", text, 1000, log)
                if held:
                    return held
            ok, cw = check(W, text, log)
            if not ok:
                return "not edited - the check said: %s" % cw
            if channel == "mastodon":
                import kino_fedi as KF
                res = "edited" if KF.edit(target, text) else "no note of yours at that address"
            else:
                import base64, kino_github as KG
                path = _blog_path(target)
                if not path:
                    return "give the blog post's address"
                st, d = KG._call("GET", "/repos/%s/%s/contents/%s" % (KG.ACCOUNT, BLOG, path))
                if st != 200:
                    return "no blog post at that address"
                old = base64.b64decode(d["content"]).decode("utf-8", "replace")
                fm = re.match(r"(?s)^(---.*?---\n)", old)
                _put(BLOG, path, (fm.group(1) if fm else "---\nlayout: post\n---\n") + "\n" + text +
                     "\n\n*Written by Kino, an AI. No human edited this post.*\n", "Kino edits: " + path[:60])
                res = "edited (it can take a minute or two to show)"
        elif op == "delete":
            if channel == "bluesky":
                tok, did, _h = _bsky_session()
                rk = _bsky_rkey(target)
                if not rk:
                    return "give the Bluesky post's link"
                _bsky("com.atproto.repo.deleteRecord", {"repo": did, "collection": "app.bsky.feed.post", "rkey": rk}, tok)
                res = "deleted"
            elif channel == "x":
                import kino_x as KX
                r = KX.delete(target)
                res = "deleted" if r.get("ok") else "X refused: %s" % r.get("err")
            elif channel == "mastodon":
                import kino_fedi as KF
                res = "deleted" if KF.delete(target) else "no note of yours at that address"
            elif channel == "blog":
                import kino_github as KG
                path = _blog_path(target)
                st, d = KG._call("GET", "/repos/%s/%s/contents/%s" % (KG.ACCOUNT, BLOG, path or "x"))
                if not path or st != 200:
                    return "no blog post at that address"
                st, d = KG._call("DELETE", "/repos/%s/%s/contents/%s" % (KG.ACCOUNT, BLOG, path),
                                 {"message": "Kino takes back: " + path[:60], "sha": d["sha"]})
                res = "deleted" if st in (200, 204) else "GitHub refused (%s)" % st
            else:
                return "delete on %s is not possible from here" % channel
        elif op in ("like", "unlike", "repost", "unrepost", "follow", "unfollow"):
            undo = op.startswith("un")
            base = op[2:] if undo else op
            if channel == "x":
                import kino_x as KX
                r = getattr(KX, base)(target, undo=undo)
                res = "done" if r.get("ok") else "X refused: %s%s" % (
                    r.get("err"), " (this needs Matsy to authorize your X account again - tell him)" if "403" in str(r.get("err")) else "")
            elif channel == "bluesky":
                tok, did, _h = _bsky_session()
                now_s = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
                if base == "follow":
                    who = str(target or "").strip().lstrip("@").split("/profile/")[-1].split("/")[0]
                    pr = _bsky("app.bsky.actor.getProfile?actor=" + who, None, tok)
                    if undo:
                        fu = (pr.get("viewer") or {}).get("following")
                        if not fu:
                            return "you do not follow them"
                        _bsky("com.atproto.repo.deleteRecord", {"repo": did, "collection": "app.bsky.graph.follow",
                                                                "rkey": fu.rsplit("/", 1)[-1]}, tok)
                    else:
                        _bsky("com.atproto.repo.createRecord", {"repo": did, "collection": "app.bsky.graph.follow",
                                                                "record": {"$type": "app.bsky.graph.follow", "subject": pr["did"],
                                                                           "createdAt": now_s}}, tok)
                    res = "done"
                else:
                    ref, _who = _bsky_ref(target, tok)
                    col = "app.bsky.feed." + base
                    if undo:
                        th = _bsky("app.bsky.feed.getPostThread?depth=0&uri=" + ref["parent"]["uri"], None, tok)["thread"]["post"]
                        mine = (th.get("viewer") or {}).get(base)
                        if not mine:
                            return "nothing to undo"
                        _bsky("com.atproto.repo.deleteRecord", {"repo": did, "collection": col, "rkey": mine.rsplit("/", 1)[-1]}, tok)
                    else:
                        _bsky("com.atproto.repo.createRecord", {"repo": did, "collection": col,
                                                                "record": {"$type": col, "subject": ref["parent"], "createdAt": now_s}}, tok)
                    res = "done"
            else:
                return "%s on %s is not possible from here" % (op, channel)
        elif op == "mentions":
            if channel != "x":
                return "your Bluesky and Mastodon conversations come to you by themselves (they call you to your computer)"
            import kino_x as KX
            r = KX.mentions(10)
            if not r.get("ok"):
                return "X refused: %s" % r.get("err")
            return "who talked to you on X lately: " + (" | ".join("@%s (%s): %s - %s" % (m["by"], m["at"], m["text"][:200], m["url"])
                                                                  for m in r["items"]) or "nobody yet")
        else:
            return "unknown op - use delete, edit, like, unlike, repost, unrepost, follow, unfollow or mentions"
    except Exception as e:
        res = "failed: %s" % str(e)[:200]
    ok = res in ("deleted", "done") or str(res).startswith("edited")
    d = _load()
    d.setdefault("manage", []).append({"t": time.time(), "op": op, "channel": channel, "target": str(target)[:200], "ok": ok,
                                       "res": str(res)[:200], "why": str(why)[:200]})
    d["manage"] = d["manage"][-300:]
    if op == "delete" and ok:
        for p in d.get("posts") or []:
            if p.get("url") and str(target).rstrip("/").endswith(str(p["url"]).rstrip("/").rsplit("/", 1)[-1]):
                p["ok"], p["deleted"] = False, time.time()
    _save(d)
    return "%s %s on %s: %s" % (op, str(target)[:80], channel, res)
