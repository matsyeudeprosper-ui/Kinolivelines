"""kino_conflict.py (2026-11-03, owner: "a proper engine, not a fixed sentence"). Before he acts on his own, the act is held
up against what the person told him about how they want things (kino_ways) - the way a person pauses with their hand on
the door: "wait - didn't he say not to?".

It is a check of THIS act against THOSE words, not a rule list: a small model reads the act he is about to do and the
person's notebook and answers whether the act goes against one of their instructions, and which. A conflict does not
forbid anything: the act goes to the person as a question (a card to confirm) with the reason in one line, instead of
being done silently. No conflict: the act goes ahead as before. Any act, any field.
"""
import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SYSTEM = """You check ONE act Kino is about to do on his own, for a person, against what that person told him about how they want
things done (their notebook). Does the act go AGAINST one of their instructions - a different level, a different moment,
a different size, something they said not to do, or something they said to do differently? Only a real contradiction
counts; an act their words do not cover is NOT a conflict; an act that follows their newest word is NOT a conflict even
if an older word said otherwise.
JSON only: {"conflict": true|false, "with": "the topic of their instruction it contradicts, or ''",
 "why": "one plain line, to the person, saying what differs (e.g. 'you said the stop goes on the dot at 77185, this one is at 77000')"}"""


def check(W, person, act_text, situation="", log=None):
    """-> None (no conflict / nothing to check) or {"with", "why"}"""
    try:
        import kino_ways as KW
        items = KW.entries(person)
    except Exception:
        items = []
    vals = ""
    try:                                               # 2026-11-03 (human3 7): his own values count too
        _cn = __import__("json").load(open(os.path.join(HERE, "kino_identity.json"), encoding="utf-8")).get("constitution") or {}
        vals = "\n".join("- " + str(v) for v in list(_cn.get("values") or []) + list(_cn.get("refuse") or []))
    except Exception:
        pass
    if not items and not vals:
        return None
    book = "\n".join("- %s: %s (said %s UTC)" % (x["topic"], x["said"], time.strftime("%d/%m %H:%M", time.gmtime(x["t"])))
                     for x in sorted(items, key=lambda x: x["t"]))
    if vals:
        book = (book or "(empty)") + "\n\nKINO'S OWN VALUES (an act against these is a conflict too - with = 'my values'; a standing permission the person gave in their notebook IS their OK):\n" + vals
    j = W.ask_json(SYSTEM, "THEIR NOTEBOOK (oldest first; the newest word on a topic is the one that holds):\n%s\n\n"
                           "THE SITUATION NOW (facts): %s\n\nTHE ACT HE IS ABOUT TO DO: %s\n\nJSON only." % (book, str(situation)[:1500], act_text),
                   models=("haiku", "sonnet"), timeout=30, log=log, warm=False)
    if isinstance(j, dict) and j.get("conflict") is True and str(j.get("why") or "").strip():
        return {"with": str(j.get("with") or "")[:80], "why": " ".join(str(j["why"]).split())[:240]}
    return None


QUOTE = """Kino is about to send a message to a person. Does the message RESTATE one of that person's own instructions (from their
notebook) in a way that differs from their NEWEST word - a condition they dropped, a word they changed (e.g. "fully" when they
said a close is enough), a level, a timeframe? Paraphrase is fine if the meaning is the same; a message that does not restate
their instructions is fine; putting today's actual number on their rule (the level it gives right now) is fine. JSON only: {"misquote": true|false, "which": "topic", "theirs": "their newest wording, short",
"why": "one line: what the message says differently"}"""


def _stems(t):
    import re
    return set(w[:6] for w in re.findall(r"[a-zà-ÿ]{4,}", str(t).lower())) - {"that", "this", "with", "your", "have", "will", "from", "then", "what", "when", "they", "just", "dans", "pour", "avec", "mais", "plus", "tout"}


def misquote(W, person, say, log=None):
    """-> None, or {"which", "theirs", "why"} when his message restates their instruction differently from their newest word.
    Only messages that share several words with a notebook entry are checked (cheap gate, then a small model)."""
    try:
        import kino_ways as KW
        items = KW.entries(person)
    except Exception:
        items = []
    if not items or not str(say or "").strip():
        return None
    sw = _stems(say)
    near = [x for x in items if len(sw & _stems(x["topic"] + " " + x["said"])) >= 2]
    if not near:
        return None
    book = "\n".join("- %s: %s" % (x["topic"], x["said"]) for x in sorted(near, key=lambda x: x["t"]))
    j = W.ask_json(QUOTE, "THEIR NOTEBOOK (newest word per topic):\n%s\n\nKINO'S MESSAGE:\n%s\n\nJSON only." % (book, str(say)[:1500]),
                   models=("haiku", "sonnet"), timeout=25, log=log, warm=False)
    if isinstance(j, dict) and j.get("misquote") is True and str(j.get("why") or "").strip():
        return {"which": str(j.get("which") or "")[:80], "theirs": str(j.get("theirs") or "")[:240], "why": " ".join(str(j["why"]).split())[:240]}
    return None
