"""kino_online.py (2026-11-01, owner: next upgrades 1 + 6 - "he answers people on Mastodon and Bluesky, remembers each person").

His social life outside the app:
  tick()        every ~10 min (app): Bluesky notifications (replies, mentions, quotes, follows) are read; each becomes a file in
                his inbox (C:\\KinoWorld\\inbox\\bsky_*.txt), a wish to answer, and a note on that person. Mastodon replies arrive
                by themselves (kino_fedi) and are noted here too.
  people        robots/kino_online.json - each person he met: where, first and last time, what was said both ways, how many
                exchanges (familiarity grows with them). He reads it before answering (block()).
  pending()     messages still waiting for his answer - they call him to his computer (kino_work.due).
  answered(url) when he replies (skeet/toot with url), that message is no longer pending.
"""
import json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_online.json")
INBOX = r"C:\KinoWorld\inbox"
LOG = os.path.join(HERE, "kino_online.log")
_LK = threading.Lock()
_LAST = {"t": 0.0}


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"people": {}, "pending": [], "bsky_seen": ""}


def _save(d):
    tmp = STORE + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, STORE)


def note(who, where, text, direction="in", url="", kind="reply"):
    """one exchange with a person; an incoming message also waits for his answer"""
    with _LK:
        d = _load()
        p = d["people"].setdefault(who, {"where": where, "first": time.time(), "n": 0, "said": []})
        p["last"] = time.time()
        p["n"] = int(p.get("n") or 0) + 1
        p["said"] = (p.get("said") or [])[-11:] + [{"t": int(time.time()), "dir": direction, "kind": kind, "text": str(text)[:400], "url": url}]
        if direction == "in" and kind in ("reply", "mention", "quote") and url:
            d["pending"] = [x for x in d["pending"] if x.get("url") != url][-30:] + [
                {"t": time.time(), "who": who, "where": where, "text": str(text)[:400], "url": url}]
        _save(d)


def answered(url):
    with _LK:
        d = _load()
        d["pending"] = [x for x in d["pending"] if x.get("url") != url]
        _save(d)


def answered_by(who):
    """he wrote back to this person (an email) - what they sent no longer waits"""
    with _LK:
        d = _load()
        d["pending"] = [x for x in d["pending"] if x.get("who") != who]
        _save(d)


def pending(max_age_h=72):
    return [x for x in _load()["pending"] if time.time() - float(x.get("t") or 0) < max_age_h * 3600]


def block(en=True):
    """the people he met and what waits for an answer - for his work session"""
    d = _load()
    P = sorted(d["people"].items(), key=lambda kv: -float(kv[1].get("last") or 0))[:8]
    out = []
    W = pending()
    if W:
        out.append("WAITING FOR YOUR ANSWER: " + " | ".join(
            ("%s by email: \"%s\" (answer with email to %s)" % (x["who"], x["text"][:240], x["who"])) if x["where"] == "email" else
            ("%s on %s: \"%s\" (answer with %s and url=%s)" % (x["who"], x["where"], x["text"][:200],
                                                              "skeet" if x["where"] == "bluesky" else "toot", x["url"])) for x in W[-5:]))
    if P:
        out.append("PEOPLE YOU MET ONLINE (most recent first; how many exchanges; the last words): " + " | ".join(
            "%s (%s, %d) %s" % (k, v.get("where"), int(v.get("n") or 0),
                                " / ".join(("they: " if s["dir"] == "in" else "you: ") + s["text"][:90] for s in (v.get("said") or [])[-2:]))
            for k, v in P))
    return "\n".join(out)


# ------------------------------------------------------------------------------------------------ Bluesky
def _bsky_tick():
    import kino_post as KP
    tok, did, handle = KP._bsky_session()
    r = KP._bsky("app.bsky.notification.listNotifications?limit=40", None, tok)
    seen = _load().get("bsky_seen") or ""
    N = [n for n in (r.get("notifications") or []) if n.get("indexedAt", "") > seen]
    if not N:
        return 0
    newest = max(n.get("indexedAt", "") for n in N)
    for n in sorted(N, key=lambda x: x.get("indexedAt", "")):
        a = n.get("author") or {}
        who = "@" + str(a.get("handle"))
        why = n.get("reason")
        if why == "follow":
            note(who, "bluesky", "followed you", "in", kind="follow")
            _tell("A NEW FOLLOWER on Bluesky: %s (%s)" % (who, a.get("displayName") or ""))
            continue
        if why not in ("reply", "mention", "quote"):
            continue                                   # likes and reposts: counted by Bluesky, not a conversation
        txt = str((n.get("record") or {}).get("text") or "")
        url = n.get("uri")
        note(who, "bluesky", txt, "in", url, kind=why)
        try:
            os.makedirs(INBOX, exist_ok=True)
            open(os.path.join(INBOX, "bsky_%s_%s.txt" % (time.strftime("%Y%m%d_%H%M%S"), re.sub(r"\W", "", who)[:20])), "w",
                 encoding="utf-8").write("FROM %s (Bluesky, %s)\nPOST %s\n\n%s\n" % (who, why, url, txt))
        except Exception:
            pass
        _tell("SOMEONE %s on Bluesky - %s: \"%s\"" % ({"reply": "ANSWERED YOU", "mention": "MENTIONED YOU", "quote": "QUOTED YOU"}[why],
                                                       who, txt[:300]))
    with _LK:
        d = _load()
        d["bsky_seen"] = newest
        _save(d)
    try:
        KP._bsky("app.bsky.notification.updateSeen", {"seenAt": newest}, tok)
    except Exception:
        pass
    return len(N)


def _tell(line):
    _log(line)
    try:
        import kino_urge as KU
        KU.add("kino", line)
    except Exception:
        pass


def tick():
    """called by the app every urge tick; works every 10 minutes"""
    if time.time() - _LAST["t"] < 600:
        return
    _LAST["t"] = time.time()
    try:
        n = _bsky_tick()
        if n:
            _log("bluesky: %d new" % n)
    except Exception as e:
        _log("bluesky error %s" % str(e)[:200])
