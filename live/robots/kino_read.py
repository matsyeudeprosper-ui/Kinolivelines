"""kino_read.py (2026-10-28, KINO_V3_HUMAN.md engine 2) - his intuition about the person, right now.

People read each other all the time without thinking about it: the words, but also how long the message is, how fast it
came, a "lol", a change of subject. From those cues they sense a mood, an energy, what the other is reaching for in this
exchange (an answer, company, reassurance, a laugh, a decision, to wrap up, to vent) and what is really on their mind -
and they half-expect how the other will answer next. When that expectation is wrong, the read gets more careful.

Here: right after a message of theirs, a fast intuition pass (small model, no tools) reads the last exchanges plus the
measured cues and writes the read into kino_person (with the "next" guess, checked later against what really came - the
hit rate is part of what he sees). The one mind gets it as his gut feeling, which can be wrong. No rule about what to say.
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SYSTEM = """You are the intuition of Kino, a friend who trades and talks with this person every day. You do not answer him.
You sense him, the way a close friend does from how he writes - not only what he says: the length, the speed, a "lol",
a dry "ok", a change of subject, the hour for him.
Read him RIGHT NOW. JSON only:
{"mood": "a few plain words", "energy": "low|medium|high", "engaged": "fading|steady|warm|intense",
 "reaching_for": "what he wants from this exchange right now (an answer, company, reassurance, a laugh, a decision, to wrap up, to vent, to be left alone...)",
 "on_his_mind": "what is really occupying him, in a few words",
 "next": "short|long|silent - how he will most likely answer Kino's next message"}
Your read can be wrong; say what you honestly sense, not what is polite."""


def _transcript(M, n=14):
    L = []
    for m in [x for x in M if x.get("role") in ("user", "ai") and x.get("text")][-n:]:
        who = "HIM" if m["role"] == "user" else "KINO"
        L.append("%s %s: %s" % (time.strftime("%H:%M", time.gmtime(float(m.get("t") or 0))), who,
                                " ".join(str(m["text"]).split())[:300]))
    return "\n".join(L)


def read(W, uid, chat, cues="", local_hour=None, log=None):
    """one intuition pass -> the read (dict) or None; stored in kino_person"""
    M = chat.get("msgs") or []
    if not any(m.get("role") == "user" for m in M[-3:]):
        return None
    user = "MEASURED CUES: %s\nHIS LOCAL HOUR: %s\n\nTHE LAST EXCHANGES (UTC):\n%s\n\nJSON only." % (
        cues or "-", "-" if local_hour is None else "%02dh" % local_hour, _transcript(M))
    try:
        j = W.ask_json(SYSTEM, user, models=("haiku", "sonnet"), timeout=40, log=log, warm=False)
    except Exception:
        return None
    if not isinstance(j, dict) or not j.get("mood"):
        return None
    r = {k: " ".join(str(j.get(k) or "").split())[:160] for k in ("mood", "energy", "engaged", "reaching_for", "on_his_mind")}
    r["next"] = str(j.get("next") or "").lower().strip()
    try:
        import kino_person as KP
        KP.set_read(uid, chat.get("id"), r)
    except Exception:
        pass
    return r
