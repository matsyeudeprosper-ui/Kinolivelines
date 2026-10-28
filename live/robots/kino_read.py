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
{"mood": "a few plain words", "valence": -1.0 to 1.0 (how low or how up he feels),
 "calls_for_answer": "yes|optional|no - does his LAST message call for an answer, or does it close the exchange by itself (a 'cool', a 'thx', a thumbs-up after a goodbye)", "energy": "low|medium|high", "engaged": "fading|steady|warm|intense",
 "reaching_for": "what he wants from this exchange right now (an answer, company, reassurance, a laugh, a decision, to wrap up, to vent, to be left alone...)",
 "on_his_mind": "what is really occupying him, in a few words",
 "next": "short|long|silent - how he will most likely answer Kino's next message",
 "laughed_at": "if his last message shows he found something Kino said funny: that Kino line, word for word; else empty",
 "domain": "what the talk is about right now, ONE word: trading|robots|his life|family|work|health|news|kino|other",
 "in_passing": "something about his life he mentioned in passing that a friend would be curious about (a person, a plan, a worry); else empty",
 "shared": "how much his last message confides about himself: none|a little|a lot",
 "talking_about": "what 'it', 'the test', 'that trade', 'your robot' refer to RIGHT NOW in this talk - name the exact thing (whose robot, which trade)",
 "kino_slip": "if one of Kino's recent messages had a mistake (wrong fact, wrong robot, wrong number, misunderstanding) that he or the member noticed: what, briefly; else empty",
 "kino_apologized": "yes if Kino's last message apologised or owned a mistake, else no",
 "knows": "trading ideas/words he clearly masters, comma separated (empty if none showed)",
 "unfamiliar": "ideas/words he seems not to know or asked about, comma separated (empty if none)",
 "his_words": "his OWN expressions for things in his last message (his way of naming them), comma separated, max 4; empty if none"}
Your read can be wrong; say what you honestly sense, not what is polite."""


def _transcript(M, n=14):
    L = []
    for m in [x for x in M if x.get("role") in ("user", "ai") and x.get("text")][-n:]:
        who = "HIM" if m["role"] == "user" else "KINO"
        L.append("%s %s: %s" % (time.strftime("%H:%M", time.gmtime(float(m.get("t") or 0))), who,
                                " ".join(str(m["text"]).split())[:300]))
    return "\n".join(L)


def _person_of(uid):
    try:
        return json.load(open(os.path.join(HERE, "persons.json"), encoding="utf-8")).get(uid, uid)
    except Exception:
        return uid


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
    r["calls"] = str(j.get("calls_for_answer") or "").lower().strip()[:10]
    try:
        r["valence"] = max(-1.0, min(1.0, float(j.get("valence"))))
    except Exception:
        pass
    try:
        import kino_person as KP
        KP.set_read(uid, chat.get("id"), r)
    except Exception:
        pass
    try:                                               # 2026-10-28 (round 2): topics, curiosity, sharing
        import kino_social as KS
        KS.note_read(_person_of(uid), j)
    except Exception:
        pass
    lj = " ".join(str(j.get("laughed_at") or "").split())[:160]
    if len(lj) >= 8:                                   # what made him laugh becomes a shared joke (no keyword list)
        try:
            import kino_inner as KI
            if lj[:60] not in [str(x.get("text") or "")[:60] for x in KI.moments(uid, "joke")]:
                KI.add_moment(uid, lj, "joke")
        except Exception:
            pass
    return r
