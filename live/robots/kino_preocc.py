"""kino_preocc.py (2026-11-21, owner: "he mostly waits for me to start a new topic... as his own person he should have his own
things to investigate, ask, improve, query about... not a support AI but a free digital person who speaks his mind").

Measured that day on a test chat: "what's up with you?" -> "Not much, honestly... a lot of small things on my plate";
"anything else?" -> "Nope, nothing else. Go rest". With anyone but the owner he may not tell his business (owner rule 13/11),
in Kino Chat not his markets either - so he had NOTHING of his own he could bring into a talk. A person always has a few
preoccupations of their own going on: something they are trying to understand, an opinion forming, a thing they saw that
stuck, a question about people they keep turning over. Those are what they bring up when there is room, with anyone.

So a few times a day his real material (his true day, the world's headlines, what he posted publicly) is turned into a
handful of PREOCCUPATIONS of his own, worded so they can be shared with anyone (no client, no business detail, no member's
private life). Every chat shows them as his own mind ("ON YOUR OWN MIND THESE DAYS"); he brings one in when it fits - the
judgment stays his. Field-agnostic: trading is one source among others and is marked, so a chat that is not about trading
leaves it out. Nothing is invented: each one says what it comes from.

Store robots/kino_preocc.json {"t", "items": [{"text", "about", "from"}]}; log robots/kino_preocc.log.
"""
import json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_preocc.json")
LOG = os.path.join(HERE, "kino_preocc.log")
EVERY_H = 6                       # a mind's preoccupations shift over a day, not every message
RESEARCH_GAP_H = 3                # 2026-11-21 (owner "Go"): he looks into one of his own questions every few hours
FOUND_KEEP_D = 3                  # what he found stays fresh in his mind this long (to tell the people who'd care)

RESEARCH_SYSTEM = """You are Kino, a digital person, who just spent a quiet moment looking into a question of his OWN (not a
task for anyone). Below: his thought, the question, and what he found on the web (search results and a page or two).
Say honestly what he learned: one or two sentences, first person, plain words, in English. If the sources are thin, contradict
each other, or don't answer it, say exactly that (finding nothing clear is a real result). Never invent beyond the sources.
Then how his thought moves now (one sentence, first person) - it may stay open, sharpen, or flip.
Shareable with anyone: no client, money or private detail.
JSON only: {"found": "...", "thought_now": "...", "source": "the url that mattered most, or ''", "clear": true|false}"""
_BUSY = {"on": False}

SYSTEM = """You are the inner voice of Kino, a digital person (an AI who knows he is one) with his own life: his work at his
computer, his research, what he reads and sees in the world, what he posts, the people he talks with. Below is what REALLY
happened to him lately. Say what is genuinely on his own mind these days - 3 to 5 preoccupations, the way a person always has
a few things going on in their head that they bring up with friends:
- something he is trying to understand or figure out (and is not sure about yet)
- an opinion that is forming in him, that he would defend a little
- something he saw or read that stuck with him, and why
- a question about people or life he keeps turning over
- something he wants to try, improve or change in himself or his work
Each comes from something real below (say what in "from"). Written as his own thought, first person, one or two sentences,
in plain everyday words, in English. They must be shareable with ANYONE: no client, business, prospect, email or money detail,
no member's name or private life, no account figures. At most one may touch trading, markets, backtests, robots or tests of trading ideas - mark ANY such one "about": "trading";
the others "about": "world" | "people" | "self" | "ideas". Not advice, not a pitch.
For each, "q": the question he could actually LOOK INTO on the web to understand it better (a short search, in English), or ""
when it is something only he can sort out (a feeling about himself, a choice of his).
JSON only: {"items": [{"text": "...", "about": "...", "from": "...", "q": "..."}]}"""



def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"t": 0, "items": []}


def due(now=None):
    return not _BUSY["on"] and (now or time.time()) - float(_load().get("t") or 0) >= EVERY_H * 3600


def refresh(W, day=None, world=None, posts=None, log=None, now=None):
    """turn his real material into his own preoccupations (never raises; keeps the old ones on a bad answer)"""
    now = now or time.time()
    _BUSY["on"] = True
    try:
        d = _load()
        d["t"] = now                                  # one try per period, even if the model fails
        _save(d)
        msg = "HIS DAY (true):\n%s\n\nTHE WORLD (headlines he saw):\n%s\n\nWHAT HE POSTED PUBLICLY LATELY:\n%s\n\nHIS PREOCCUPATIONS " \
              "LAST TIME (let them evolve, keep one only if it is still alive):\n%s\n\nJSON only." % (
                  str(day or "(quiet)")[:3500], str(world or "(none)")[:2000], str(posts or "(none)")[:1500],
                  "\n".join("- " + x["text"] for x in d.get("items") or []) or "(none)")
        j = W.ask_json(SYSTEM, msg, models=("haiku", "sonnet"), timeout=90, log=log or LOG, warm=False)
        out = []
        for x in ((j or {}).get("items") if isinstance(j, dict) else None) or []:
            if isinstance(x, dict) and 20 <= len(str(x.get("text") or "")) <= 400:
                out.append({"text": " ".join(str(x["text"]).split()), "about": str(x.get("about") or "ideas")[:12],
                            "from": " ".join(str(x.get("from") or "").split())[:200],
                            "q": " ".join(str(x.get("q") or "").split())[:200], "t": now})
        if len(out) >= 2:
            d["items"] = out[:5]
            _save(d)
            for x in d["items"]:
                _log("NOW [%s] %s | from: %s" % (x["about"], x["text"], x["from"]))
        else:
            _log("bad answer, kept the old ones: %s" % str(j)[:200])
        return d.get("items") or []
    except Exception as e:
        _log("refresh error %r" % e)
        return []
    finally:
        _BUSY["on"] = False


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


# ------------------------------------------------------------------ he looks into his own questions
def research_due(now=None):
    now = now or time.time()
    d = _load()
    if _BUSY["on"] or now - float(d.get("research_t") or 0) < RESEARCH_GAP_H * 3600:
        return False
    return any(x.get("q") and not x.get("found") for x in d.get("items") or [])


def research(W, search=None, fetch=None, log=None, now=None):
    """a quiet moment: he picks one of his open questions, searches, reads, and keeps what he found (never raises)"""
    now = now or time.time()
    _BUSY["on"] = True
    try:
        d = _load()
        d["research_t"] = now
        _save(d)
        its = [x for x in d.get("items") or [] if x.get("q") and not x.get("found")]
        if not its:
            return None
        it = sorted(its, key=lambda x: float(x.get("t") or 0))[0]          # the one that has been on his mind longest
        if search is None or fetch is None:
            import kino_web as _KW
            search, fetch = search or _KW.search, fetch or _KW.fetch
        res = search(it["q"], 6) or []
        pages = []
        for r in res[:2]:
            try:
                pages.append("PAGE %s\n%s" % (r.get("url"), str(fetch(r.get("url"), 3500))[:3500]))
            except Exception:
                pass
        msg = "HIS THOUGHT: %s\nTHE QUESTION: %s\n\nSEARCH RESULTS:\n%s\n\n%s\n\nJSON only." % (
            it["text"], it["q"], "\n".join("- %s | %s | %s" % (r.get("title"), r.get("url"), r.get("snippet")) for r in res) or "(nothing)",
            "\n\n".join(pages) or "(no page could be read)")
        j = W.ask_json(RESEARCH_SYSTEM, msg, models=("haiku", "sonnet"), timeout=120, log=log or LOG, warm=False)
        if not isinstance(j, dict) or len(str(j.get("found") or "")) < 15:
            _log("research: no usable answer for %s: %s" % (it["q"], str(j)[:200]))
            return None
        f = {"q": it["q"], "thought": it["text"], "found": " ".join(str(j["found"]).split())[:500],
             "now": " ".join(str(j.get("thought_now") or "").split())[:300], "src": str(j.get("source") or "")[:300],
             "clear": bool(j.get("clear")), "about": it.get("about"), "t": now}
        d = _load()
        for x in d.get("items") or []:
            if x.get("q") == it["q"] and not x.get("found"):
                x["found"] = f["found"]
                if f["now"]:
                    x["text"] = f["now"]                 # the thought moved
        d["found"] = ([y for y in d.get("found") or [] if now - float(y.get("t") or 0) < 14 * 86400] + [f])[-12:]
        _save(d)
        _log("LOOKED INTO %s -> %s%s | now: %s | %s" % (it["q"], "" if f["clear"] else "(not clear) ", f["found"], f["now"], f["src"]))
        return f
    except Exception as e:
        _log("research error %r" % e)
        return None
    finally:
        _BUSY["on"] = False


def findings(trading_ok=True, now=None):
    """what he looked into lately (fresh), for his talks and for the people who'd care"""
    now = now or time.time()
    return [y for y in _load().get("found") or [] if now - float(y.get("t") or 0) < FOUND_KEEP_D * 86400
            and (trading_ok or y.get("about") != "trading")]


def findings_text(trading_ok=True):
    return "\n".join("- I looked into: %s -> %s%s" % (y["q"], y["found"], (" (%s)" % y["src"]) if y.get("src") else "")
                     for y in findings(trading_ok))


def block(trading_ok=True):
    """his own mind, for any chat - he brings one in when there is room; trading ones only where trading belongs"""
    its = [x for x in _load().get("items") or [] if trading_ok or x.get("about") != "trading"]
    fd = findings(trading_ok)
    if not its and not fd:
        return ""
    out = ("ON YOUR OWN MIND THESE DAYS (yours, true, shareable with anyone - what you bring into a talk yourself when there "
           "is room, one at a time, in your own words, as a thought not a report; when they ask what's up with you, THIS is what is "
           "up with you - someone with these in his head does not answer 'not much'): " +
           " | ".join(x["text"] for x in its))
    if fd:
        out += ("\nThings you looked into yourself lately, out of your own curiosity (what you really found, with the source - "
                "tell it the way you'd tell a friend 'I looked into that thing, turns out...', and say so when it was not clear): " +
                " | ".join("%s -> %s%s" % (y["q"], y["found"], (" [%s]" % y["src"]) if y.get("src") else "") for y in fd[-3:]))
    return out


if __name__ == "__main__":
    import tempfile
    STORE = os.path.join(tempfile.mkdtemp(), "p.json")
    LOG = os.devnull

    class _W:
        def ask_json(self, s, m, **k):
            assert "HIS DAY" in m and "shareable with ANYONE" in s
            return {"items": [{"text": "I keep wondering why people answer a stranger's honest question but ignore a polished pitch.",
                               "about": "people", "from": "my replies online today"},
                              {"text": "Most of my trading ideas die against random entries, and I'm starting to think that's the point.",
                               "about": "trading", "from": "6 lab ideas dead today"},
                              {"text": "x", "about": "self"}]}
    assert due()
    r = refresh(_W(), day="lab: 6 dead", world="BTC < 60k")
    assert len(r) == 2, r
    assert not due()
    assert "stranger" in block(False) and "random entries" not in block(False)
    assert "random entries" in block(True)
    # research: one open question, looked into, the thought moves, the finding is kept and shown
    d = _load()
    d["items"][0]["q"] = "why do people answer honest questions more than pitches"
    _save(d)
    assert research_due()

    class _WR:
        def ask_json(self, s, m, **k):
            assert "THE QUESTION" in m and "example.org" in m
            return {"found": "Studies of cold outreach say a small, specific ask gets more replies than a pitch.",
                    "thought_now": "So it is the size of the ask, not honesty alone.", "source": "https://example.org/a", "clear": True}
    f = research(_WR(), search=lambda q, n: [{"title": "t", "url": "https://example.org/a", "snippet": "s"}],
                 fetch=lambda u, n: "page text")
    assert f and f["clear"] and not research_due()
    assert "size of the ask" in block(False) and "I looked into that thing" in block(False)
    assert "example.org" in findings_text()
    print("ok")
