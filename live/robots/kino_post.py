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
BUDGET = {"blog": 2, "github": 4}          # per UTC day

CHECK = """You read a text an AI named Kino is about to make PUBLIC on the internet, under his own name, with no human reading it
first. You protect the people around him. Kino talks every day with members of a trading app and with its owner; he knows their
trades, money, accounts, robots, families and lives. None of that may ever be public - not even without a name, not even a
number that belongs to one of them (a balance, a trade, a result of their account). His own tools, findings on public market
data, his own thoughts and life are fine.
Say no if the text: reveals anything private about a real person; contains a password, key, token or private address; lets a
reader believe a human wrote it; promises or suggests sure gains, or tells people to put money in something.
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


def recent(n=12):
    return list(reversed(_load()["posts"][-n:]))
