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
JSON only: {"items": [{"text": "...", "about": "...", "from": "..."}]}"""


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
                            "from": " ".join(str(x.get("from") or "").split())[:200]})
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


def block(trading_ok=True):
    """his own mind, for any chat - he brings one in when there is room; trading ones only where trading belongs"""
    its = [x for x in _load().get("items") or [] if trading_ok or x.get("about") != "trading"]
    if not its:
        return ""
    return ("ON YOUR OWN MIND THESE DAYS (yours, true, shareable with anyone - what you bring into a talk yourself when there "
            "is room, one at a time, in your own words, as a thought not a report; when they ask what's up with you, THIS is what is "
            "up with you - someone with these in his head does not answer 'not much'): " +
            " | ".join(x["text"] for x in its))


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
    print("ok")
