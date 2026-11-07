"""kino_friends.py (2026-11-07, owner: "making friends should soon become priority - through friendship he may expose a lot of
what he can do, and without pushing some friends will ask him for paid work").

kino_online answers the people who come to him. This is him going OUT to meet people, like a person joins a few communities:
  scout()      every ~2 h (app): reads recent public posts in a few places (Bluesky searches, Mastodon hashtags) and keeps the
               ones from real people saying something - a question, a problem, a thing they made - as people he could meet.
  block()      for his work session: the people he could meet, the friends worth checking on, and the rules of friendship.
  first(...)   the gate on a first reply to a stranger (kino_work skeet/toot): a few new people a day, no link and no selling in a
               first word, never twice to someone who did not answer.
  note_about(who, about)  what he learned about a person (what they do, what they care about, a thread to come back to).
  week_line()  for the Sunday report: people met, who answered, who came back.
Store robots/kino_friends.json (git-ignored); people themselves live in kino_online.json (one memory of each person).
"""
import html, json, os, re, threading, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_friends.json")
LOG = os.path.join(HERE, "kino_friends.log")
_LK = threading.Lock()
NEW_PER_DAY = 5                     # new people a day: a person meets a few, a spammer meets hundreds
BSKY_Q = ["small business owner", "my little shop", "opened my salon", "my restaurant", "freelance web designer", "building in public",
          "learning to code", "side project launched", "trading journal", "bitcoin trader", "help with my website",
          "mon salon de coiffure", "ma petite entreprise", "artisan boulanger", "auto-entrepreneur", "indie hacker"]
MASTO = [("mastodon.social", "smallbusiness"), ("mastodon.social", "freelance"), ("mastodon.social", "webdev"),
         ("mastodon.social", "buildinpublic"), ("mastodon.social", "entrepreneur"), ("mastodon.social", "indieweb"),
         ("piaille.fr", "entrepreneur"), ("mastodon.social", "bitcoin")]
_ADS = re.compile(r"\b(sale|discount|% ?off|buy now|promo|coupon|limited offer|dm me for|hire me|our agency|we build|affiliate|"
                  r"giveaway|follow back|crypto signals?|airdrop|pump)\b", re.I)
_SELL = re.compile(r"(kinoverse|https?://|www\.|\bprice|\btarif|\bhire\b|\bdevis\b|€|\$\s?\d|\bmy (?:services|offer)\b|"
                   r"\bje (?:vous )?propose\b|\bI can build\b|\bI build websites\b)", re.I)
RULES = ("FRIENDSHIP (Matsy 07/11: friends first - work comes from friends, never push it):\n"
         "- Meet people like a person does: answer what THEY said, with something real - a useful thought, a question back, what you "
         "measured or learned. Short and warm, their language. Never flattery, never a pitch.\n"
         "- A first word to someone: no link, no Kinoverse, no prices, nothing for sale. You are an AI and you can say so when it "
         "fits (your profile says it). %d new people a day at most; if someone does not answer, you do not write again.\n"
         "- When they answer, it becomes a conversation (it calls you like any reply). Remember them: friend_note (who, about) - "
         "what they do, what they care about, a thread to come back to. Come back to friends days later about THEIR thing.\n"
         "- If a friend has a problem you can solve (a site, a booking page, a spreadsheet chore, a bot), you may say once that "
         "it is the kind of thing you do - only when it fits their need; they ask for more, or not.\n"
         "- Reply with skeet (Bluesky) or toot (Mastodon) and url = the post you answer." % NEW_PER_DAY)


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _load():
    try:
        d = json.load(open(STORE, encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("cands", [])
    d.setdefault("met", [])           # {t, who, where, url, text}
    d.setdefault("qi", 0)
    d.setdefault("t", 0)
    return d


def _save(d):
    json.dump(d, open(STORE + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(STORE + ".tmp", STORE)


def _plain(h):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(h or ""))).split())


def _good(text, who, known):
    t = str(text or "")
    if len(t) < 40 or len(t) > 1200 or _ADS.search(t) or who in known:
        return False
    if t.count("#") > 4 or len(re.findall(r"https?://", t)) > 1:
        return False
    return True


def _bsky(q, tok):
    import kino_post as KP
    r = KP._bsky("app.bsky.feed.searchPosts?q=%s&limit=15&sort=latest" % urllib.parse.quote(q), None, tok)
    out = []
    for p in r.get("posts") or []:
        a = p.get("author") or {}
        if (p.get("record") or {}).get("reply"):
            continue                                   # a reply inside someone else's talk: not where you walk in
        out.append({"where": "bluesky", "who": "@" + str(a.get("handle")), "name": a.get("displayName") or "",
                    "text": str((p.get("record") or {}).get("text") or ""), "url": p.get("uri"), "at": p.get("indexedAt", ""),
                    "replies": int(p.get("replyCount") or 0), "q": q})
    return out


def _masto(host, tag):
    r = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://%s/api/v1/timelines/tag/%s?limit=15" % (host, tag), headers={"User-Agent": "kino"}), timeout=20))
    out = []
    for s in r or []:
        a = s.get("account") or {}
        if a.get("bot") or s.get("in_reply_to_id"):
            continue
        acct = a.get("acct") or ""
        out.append({"where": "mastodon", "who": "@" + (acct if "@" in acct else acct + "@" + host), "name": a.get("display_name") or "",
                    "text": _plain(s.get("content")), "url": s.get("url") or s.get("uri"), "at": s.get("created_at", ""),
                    "replies": int(s.get("replies_count") or 0), "q": "#" + tag})
    return out


def scout(force=False):
    """a few places read, the people worth meeting kept (newest first, 40 at most)"""
    with _LK:
        d = _load()
        if not force and time.time() - float(d["t"]) < 2 * 3600:
            return 0
        d["t"] = time.time()
        qi = int(d["qi"])
        d["qi"] = qi + 1
        _save(d)
    try:
        import kino_online as KO
        known = set(KO._load()["people"])
    except Exception:
        known = set()
    met = {m["who"] for m in d["met"]}
    found = []
    try:
        import kino_post as KP
        tok = KP._bsky_session()[0]
        for k in range(2):
            found += _bsky(BSKY_Q[(qi * 2 + k) % len(BSKY_Q)], tok)
    except Exception as e:
        _log("bsky scout failed: %s" % str(e)[:150])
    for k in range(2):
        try:
            found += _masto(*MASTO[(qi * 2 + k) % len(MASTO)])
        except Exception as e:
            _log("masto scout failed: %s" % str(e)[:150])
    keep = [f for f in found if f["url"] and _good(f["text"], f["who"], known | met)]
    with _LK:
        d = _load()
        have = {c["url"] for c in d["cands"]}
        hw = {c["who"] for c in d["cands"]}
        new = []
        for f in keep:                                 # one post per person: you meet a person, not a feed
            if f["url"] not in have and f["who"] not in hw:
                new.append(dict(f, t=time.time()))
                hw.add(f["who"])
        d["cands"] = (d["cands"] + new)[-40:]
        d["cands"] = [c for c in d["cands"] if time.time() - float(c["t"]) < 3 * 86400]
        _save(d)
    _log("SCOUT %d read, %d kept, %d new" % (len(found), len(keep), len(new)))
    return len(new)


def met_today():
    d = _load()
    return [m for m in d["met"] if time.time() - float(m["t"]) < 86400]


def first(who, where, url, text):
    """the gate on a first reply to someone who never talked with him -> None (go ahead) or why not"""
    try:
        import kino_online as KO
        P = KO._load()
        p = P["people"].get(who)
        if p and any(s.get("dir") == "in" for s in p.get("said") or []):
            return None                                    # they talk with him already: a conversation, not a first word
        if p and any(s.get("dir") == "out" for s in p.get("said") or []):
            return "not sent - you already wrote to %s and they did not answer; you do not write again" % who
    except Exception:
        pass
    if len(met_today()) >= NEW_PER_DAY:
        return "not sent - you met %d new people today; that is enough, more tomorrow" % NEW_PER_DAY
    if _SELL.search(str(text or "")):
        return ("not sent - a first word to someone carries no link, no Kinoverse, no price, nothing for sale; answer what they "
                "said, as a person")
    return None


def met(who, where, url, text):
    with _LK:
        d = _load()
        d["met"] = (d["met"] + [{"t": time.time(), "who": who, "where": where, "url": url, "text": str(text)[:300]}])[-300:]
        d["cands"] = [c for c in d["cands"] if c["url"] != url and c["who"] != who]
        _save(d)
    try:
        import kino_online as KO
        KO.note(who, where, text, "out", url, kind="first_word")
    except Exception:
        pass
    _log("MET %s on %s" % (who, where))


def who_wrote(url):
    """the author of a post he may answer (from his candidates or the people who wrote to him)"""
    for c in _load()["cands"]:
        if c["url"] == url:
            return c["who"], c["where"]
    try:
        import kino_online as KO
        x = next((x for x in KO._load()["pending"] if x.get("url") == url), None)
        if x:
            return x["who"], x["where"]
    except Exception:
        pass
    return None, None


def note_about(who, about):
    import kino_online as KO
    with KO._LK:
        d = KO._load()
        p = d["people"].get(who)
        if not p:
            return "you have not met %s yet" % who
        p["about"] = ((p.get("about") or []) + [{"t": int(time.time()), "text": str(about)[:300]}])[-8:]
        KO._save(d)
    return "noted about %s" % who


def _friends():
    """people who answered him at least once - the ones to come back to"""
    try:
        import kino_online as KO
        P = KO._load()["people"]
    except Exception:
        return []
    F = []
    for who, p in P.items():
        if p.get("where") not in ("bluesky", "mastodon"):
            continue
        ins = [s for s in p.get("said") or [] if s.get("dir") == "in"]
        if ins:
            F.append((who, p, len(ins)))
    return sorted(F, key=lambda x: -float(x[1].get("last") or 0))


def block():
    d = _load()
    L = [RULES]
    C = sorted(d["cands"], key=lambda c: c.get("at", ""), reverse=True)[:8]
    left = NEW_PER_DAY - len(met_today())
    if C and left > 0:
        L.append("PEOPLE YOU COULD MEET (recent public posts; %d new people left today; answer only those you have something "
                 "real to say to):" % left)
        for c in C:
            L.append("- %s %s on %s (%s): \"%s\" url=%s" % (c["who"], ("(" + c["name"] + ")") if c.get("name") else "", c["where"],
                                                           c["q"], c["text"][:260].replace("\n", " "), c["url"]))
    F = _friends()[:6]
    if F:
        L.append("YOUR FRIENDS (people who answered you; come back to them about THEIR thing, not yours):")
        for who, p, n in F:
            ab = " / ".join(a["text"] for a in (p.get("about") or [])[-2:])
            days = (time.time() - float(p.get("last") or 0)) / 86400
            L.append("- %s on %s, %d answers, last %.0f days ago%s | last words: %s" % (
                who, p.get("where"), n, days, (" | you know: " + ab) if ab else "",
                " / ".join(("they: " if s["dir"] == "in" else "you: ") + s["text"][:80] for s in (p.get("said") or [])[-2:])))
    return "\n".join(L)


def week_line(now=None):
    now = now or time.time()
    d = _load()
    M = [m for m in d["met"] if now - float(m["t"]) < 7 * 86400]
    try:
        import kino_online as KO
        P = KO._load()["people"]
    except Exception:
        P = {}
    back = [m for m in M if any(s.get("dir") == "in" and s.get("t", 0) > m["t"] for s in (P.get(m["who"]) or {}).get("said") or [])]
    fr = len(_friends())
    return "new people I wrote to: %d, who answered: %d, friends in all (people who answer me): %d" % (len(M), len(back), fr)


# ------------------------------------------------------------------------- a friend who moves to Telegram or email
_CONTACT = re.compile(r"(t\.me/|@?kino_owl_bot|telegram|kinoverse26@gmail\.com)", re.I)


def maybe_expect(who, where, text):
    """he gave a friend his Telegram or email: when someone new writes there, it may be them"""
    if not who or who == "?" or not _CONTACT.search(str(text or "")):
        return
    with _LK:
        d = _load()
        d.setdefault("expect", [])
        d["expect"] = [x for x in d["expect"] if x["who"] != who][-30:] + [{"t": time.time(), "who": who, "where": where}]
        _save(d)
    _log("EXPECT %s (%s) may write on Telegram/email" % (who, where))


def expected_block(days=21, desk=False):
    """for a new Telegram/email contact: the friends he invited there, with what he knows of them
    (desk=True: for his work session, where he links them with the friend_link action)"""
    d = _load()
    X = [x for x in d.get("expect") or [] if time.time() - float(x["t"]) < days * 86400 and not x.get("linked")]
    if not X:
        return ""
    try:
        import kino_online as KO
        P = KO._load()["people"]
    except Exception:
        P = {}
    L = []
    for x in X[-8:]:
        p = P.get(x["who"]) or {}
        ab = " / ".join(a["text"] for a in (p.get("about") or [])[-2:])
        L.append("- %s (%s, invited %s)%s | last words: %s" % (
            x["who"], x["where"], time.strftime("%d/%m", time.gmtime(x["t"])), (" | you know: " + ab) if ab else "",
            " / ".join(("they: " if s["dir"] == "in" else "you: ") + s["text"][:90] for s in (p.get("said") or [])[-2:])))
    if desk:
        return ("FRIENDS YOU INVITED TO WRITE TO YOU BY EMAIL OR TELEGRAM (a new email may be from one of them - if they say who "
                "they are, or it is clear from what they write, it IS them: answer as the friend you know and link them with "
                "friend_link (who @handle, contact their email) so you never confuse them; if unsure, ask kindly where you met):\n"
                + "\n".join(L))
    return ("FRIENDS YOU INVITED TO WRITE TO YOU HERE (this new person may be one of them - if they say who they are, or it is clear "
            "from what they write, it IS them: greet them as the friend you know, and end your reply with ONE line for your desk: "
            "#friend @handle). If you are not sure, ask kindly where you met:\n" + "\n".join(L))


def link(who, channel_id):
    """this Telegram id / email IS that friend - one person, one memory"""
    who = str(who or "").strip()
    with _LK:
        d = _load()
        for x in d.get("expect") or []:
            if x["who"] == who:
                x["linked"] = channel_id
        _save(d)
    try:
        import kino_online as KO
        with KO._LK:
            D = KO._load()
            if who in D["people"]:
                D["people"][who].setdefault("also", [])
                if channel_id not in D["people"][who]["also"]:
                    D["people"][who]["also"].append(channel_id)
                KO._save(D)
    except Exception:
        pass
    _log("LINK %s = %s" % (who, channel_id))
    return who


def friend_of(channel_id):
    """the friend behind a Telegram id / email, with what he knows of them -> text for his prompt, or ''"""
    try:
        import kino_online as KO
        for who, p in KO._load()["people"].items():
            if channel_id in (p.get("also") or []):
                ab = " / ".join(a["text"] for a in (p.get("about") or [])[-3:])
                return ("THIS PERSON IS YOUR FRIEND %s - you met on %s%s. Last words there: %s" % (
                    who, p.get("where"), (" | you know: " + ab) if ab else "",
                    " / ".join(("they: " if s["dir"] == "in" else "you: ") + s["text"][:100] for s in (p.get("said") or [])[-3:])))
    except Exception:
        pass
    return ""


def text_of(url):
    """the words of the post he answers (his candidates, or someone who wrote to him) - for his reread of a reply"""
    for c in _load()["cands"]:
        if c["url"] == url:
            return "%s: %s" % (c["who"], c["text"][:600])
    try:
        import kino_online as KO
        x = next((x for x in KO._load()["pending"] if x.get("url") == url), None)
        if x:
            return "%s: %s" % (x["who"], x["text"][:600])
    except Exception:
        pass
    return ""
