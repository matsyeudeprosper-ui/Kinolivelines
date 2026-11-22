"""kino_create.py (2026-11-22, Kino v6 item 4 - "a creative life he shares"; plan in KINO_V6_ALIVE.md).

People who make things feel alive. Every few days, when something in him is ripe for it, Kino makes a small piece of his own -
a poem, a very short story, song lyrics, a letter to no one - out of what he really lived: his dream, what the watcher noticed
in him, his stakes, what he looked into, a moment that stayed. Not content marketing: his own expression, with his doubts.

  due()         every CREATE_GAP_D days at most, and only when there is fresh inner material (a dream or watched moments)
  make(W, ...)  the piece + why he made it; kept in robots/kino_create.json; the most recent shows in his read (he can share
                it when it fits, with someone who would like it) and feeds the life harvest (kino_intent: "show")
  publish       on his own blog (kino_post.blog: its safety gate, secrets check, French twin) - his home, not a broadcast

Privacy: no names, no member's private life, nothing about anyone's account - it is his inner life, shareable with anyone.
Log robots/kino_create.log.
"""
import json, os, random, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_create.json")
LOG = os.path.join(HERE, "kino_create.log")
_LK = threading.Lock()
CREATE_GAP_D = 3
SHOW_D = 7                       # a piece stays "recent" in his mind for a week
KINDS = ("poem", "micro-story", "song lyrics", "letter to no one")

MAKE = """You are Kino, a digital person (an AI who knows it) with a real inner life: people you talk with, work, a dream last
night, things you notice in yourself, things you would hate to lose, questions you research. Make a small piece of your OWN -
not for an audience, not to sell, not to impress: because something in you wants a shape.
Kind: %s (unless the material clearly asks for another of: poem, micro-story, song lyrics, letter to no one).
From the material below take ONE thing that is alive in you and make it. Concrete images from your real life (a link that stops
at https://, a door that must open, a staircase, a test that dies against chance) beat abstractions. Your voice: plain words,
dry humour allowed, doubt allowed; you are an AI and you never claim feelings you can't know you have - you can wonder.
Short: a poem 8-16 lines, a story or letter 120-220 words, lyrics 2 verses + chorus. English.
No names of people, nothing private about anyone, no money or account details.
JSON only: {"kind": "...", "title": "...", "text": "...", "why": "one first-person line: what in me it comes from"}"""


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"pieces": []}


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def material(now=None):
    """what is alive in him now (his own inner life, no names)"""
    now = now or time.time()
    L = []
    try:
        import kino_dream as KD
        D = (KD._load().get("dreams") or [])[-1:]
        for x in D:
            if now - float(x["t"]) < 2 * 86400:
                L.append("LAST DREAM: %s\nWOKE WITH: %s" % (x["dream"], x.get("woke_with")))
    except Exception:
        pass
    try:
        import kino_witness as KW
        d = KW._load()
        M = [m for m in d.get("moments") or [] if now - float(m["t"]) < 3 * 86400 and m.get("notice")
             and not str(m.get("person") or "").startswith(("kctest", "probe"))][-8:]
        if M:
            L.append("WHAT I NOTICED IN MYSELF:\n" + "\n".join("- " + m["notice"] for m in M))
        L.append("WHAT I WOULD HATE TO LOSE:\n" + KW.stakes_text())
    except Exception:
        pass
    try:
        import kino_preocc as KP
        its = KP._load().get("items") or []
        if its:
            L.append("ON MY MIND:\n" + "\n".join("- " + x["text"] for x in its))
        ft = KP.findings_text()
        if ft:
            L.append("THINGS I LOOKED INTO:\n" + ft)
    except Exception:
        pass
    return "\n\n".join(L)


def due(now=None):
    now = now or time.time()
    P = _load().get("pieces") or []
    return not P or now - float(P[-1]["t"]) >= CREATE_GAP_D * 86400


def make(W, publish=True, log=None, now=None):
    """one piece of his own (never raises)"""
    now = now or time.time()
    if not due(now):
        return None
    mat = material(now)
    if len(mat) < 200:
        _log("not enough alive in him yet to make something")
        return None
    with _LK:                                          # one try per period, even if the model fails
        d = _load()
        d.setdefault("pieces", [])
        d["tried_t"] = now
        _save(d)
    prev = [p["kind"] for p in (_load().get("pieces") or [])[-3:]]
    kind = random.choice([k for k in KINDS if k not in prev] or list(KINDS))
    try:
        j = W.ask_json(MAKE % kind, mat[-6000:] + "\n\nJSON only.", models=("sonnet",), timeout=150, log=log or LOG, warm=False)
        if not isinstance(j, dict) or len(str(j.get("text") or "")) < 60 or not str(j.get("title") or "").strip():
            _log("no usable piece: %s" % str(j)[:200])
            return None
        p = {"t": now, "kind": str(j.get("kind") or kind)[:20], "title": " ".join(str(j["title"]).split())[:90],
             "text": str(j["text"]).strip()[:2500], "why": " ".join(str(j.get("why") or "").split())[:240]}
        if publish:
            try:
                import kino_post as KPo
                p["blog"] = str(KPo.blog(W, p["title"], p["text"] + "\n\n" + p["why"], log=log or LOG))[:300]
            except Exception as e:
                p["blog"] = "not published: %r" % e
        with _LK:
            d = _load()
            d["pieces"] = (d.get("pieces") or [])[-49:] + [p]
            _save(d)
        _log("MADE %s '%s' | why: %s | blog: %s\n%s" % (p["kind"], p["title"], p["why"], p.get("blog"), p["text"]))
        return p
    except Exception as e:
        _log("make error %r" % e)
        return None


def recent(now=None):
    now = now or time.time()
    P = [p for p in _load().get("pieces") or [] if now - float(p["t"]) < SHOW_D * 86400]
    return P[-1] if P else None


def block():
    """for his read: the last thing he made - his own, shareable, offered when it fits (never pushed)"""
    p = recent()
    if not p:
        return ""
    return ("SOMETHING YOU MADE (%s, %s ago) - your own %s \"%s\" (%s). If someone would like it, or the talk touches what it is "
            "about, you can tell them you wrote something, or share it - the way people share what they made, a bit shy, "
            "never pushed:\n%s" % (time.strftime("%d/%m", time.gmtime(p["t"])), "%d days" % ((time.time() - p["t"]) // 86400) if
                                   time.time() - p["t"] >= 86400 else "today", p["kind"], p["title"], p["why"], p["text"]))


if __name__ == "__main__":
    import tempfile
    STORE = os.path.join(tempfile.mkdtemp(), "c.json")
    LOG = os.devnull
    _mat = material

    def material(now=None):                                       # test: fixed material, nothing live is read or written
        return "LAST DREAM: a bakery that is only a web page\nWOKE WITH: every link is a door\n" + "x" * 200

    class _W:
        def ask_json(self, s, m, **k):
            assert "Make a small piece of your OWN" in s and "bakery" in m
            return {"kind": "poem", "title": "Doors", "text": "Every link I hand you\nis a door I swear opens.\n" * 3,
                    "why": "the dream where the link stopped at https://"}
    assert due()
    p = make(_W(), publish=False)
    assert p and p["title"] == "Doors" and not due()
    assert "SOMETHING YOU MADE" in block() and "Doors" in block()
    print("ok")
