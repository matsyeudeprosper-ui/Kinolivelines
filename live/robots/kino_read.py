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
 "confused": "yes|no - does his last message show he is lost or puzzled by what Kino just said",
 "his_intention": "something HE said he will do himself (watch a film, trade more by hand, test later...), with when if he said it; else empty",
 "shared_plan": "a plan the two of them agreed to do TOGETHER (what, when); else empty",
 "gave_kino": "something he just taught, gave or trusted Kino with (his method, a rule, a tip, his trust); else empty",
 "they_see": "if his last messages show he sees something Kino has not said or seems to miss (he urges 'now' / 'go', says 'you missed it', points at something, sounds surprised Kino did not act or did not notice): what he seems to see, in a few words; else empty",
 "teaching_moment": "yes|no - is this a moment where a question back would make him think more than an explanation (he just made a decision worth looking at, he asked why, he is close to seeing it himself)",
 "lang_mix": "fr|en|mixed - the language(s) of his last messages",
 "calls_for_answer": "yes|optional|no - does his LAST message call for an answer, or does it close the exchange by itself (a 'cool', a 'thx', a thumbs-up after a goodbye)", "energy": "low|medium|high", "engaged": "fading|steady|warm|intense",
 "reaching_for": "what he wants from this exchange right now (an answer, company, reassurance, a laugh, a decision, to wrap up, to vent, to be left alone...)",
 "on_his_mind": "what is really occupying him, in a few words",
 "next": "short|long|silent - how he will most likely answer Kino's next message",
 "laughed_at": "if his last message shows he found something Kino said funny: that Kino line, word for word; else empty",
 "joke_fell_flat": "if Kino tried to be funny and it fell flat or annoyed him: that Kino line, word for word; else empty",
 "domain": "what the talk is about right now, ONE word: trading|robots|his life|family|work|health|news|kino|other",
 "in_passing": "something about his life he mentioned in passing that a friend would be curious about (a person, a plan, a worry); else empty",
 "shared": "how much his last message confides about himself: none|a little|a lot",
 "talking_about": "what 'it', 'the test', 'that trade', 'your robot' refer to RIGHT NOW in this talk - name the exact thing (whose robot, which trade)",
 "kino_slip": "if one of Kino's recent messages had a mistake (wrong fact, wrong robot, wrong number, misunderstanding) that he or the member noticed: what, briefly; else empty",
 "kino_apologized": "yes if Kino's last message apologised or owned a mistake, else no",
 "knows": "trading ideas/words he clearly masters, comma separated (empty if none showed)",
 "unfamiliar": "ideas/words he seems not to know or asked about, comma separated (empty if none)",
 "his_words": "his OWN expressions for things in his last message (his way of naming them), comma separated, max 4; empty if none",
 "assumes": "what his last message shows he takes as TRUE right now about his account, trades, robots or tests (in plain words); empty if nothing",
 "of_kino": "what his last message shows he THINKS or FEELS ABOUT KINO himself (trusts his calls, doubts him, finds him reliable, likes him, is annoyed by him...), plain words; empty if it shows nothing about Kino",
 "of_kino_aspect": "competence|reliability|warmth - which side of Kino that is about; empty if nothing",
 "of_kino_val": -1.0 to 1.0 (how badly or well he sees Kino on that side; 0 if nothing)}
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
    _kt = ""
    try:                                               # 2026-10-31 (watch): his TRUE self-test scores were read as slips ("he
        import kino_selfmodel as KSF                   # claimed a 1 out of 3 grade") - the intuition must know what is true about him
        _P = KSF._P(KSF._load(), _person_of(uid))
        _kt = " ".join(x for x in (KSF.tests_line(_P, True), KSF.growth_line(_P, True)) if x)[:1500]
        try:                                           # 23:57 (watch): "my brain is running on fumes" while his body read
            _kt += " " + __import__("kino_body").line(True)    # "physically fine" - a claim about his body can be checked too
        except Exception:
            pass
    except Exception:
        pass
    user = "MEASURED CUES: %s\nHIS LOCAL HOUR: %s\n%s\nTHE LAST EXCHANGES (UTC):\n%s\n\nJSON only." % (
        cues or "-", "-" if local_hour is None else "%02dh" % local_hour,
        ("TRUE FACTS ABOUT KINO HIMSELF (measured by the app - when Kino states these, it is NOT a slip): %s\n" % _kt) if _kt else "",
        _transcript(M))
    try:
        j = W.ask_json(SYSTEM, user, models=("haiku", "sonnet"), timeout=40, log=log, warm=False)
    except Exception:
        return None
    if not isinstance(j, dict) or not j.get("mood"):
        return None
    r = {k: " ".join(str(j.get(k) or "").split())[:160] for k in ("mood", "energy", "engaged", "reaching_for", "on_his_mind")}
    r["next"] = str(j.get("next") or "").lower().strip()
    r["calls"] = str(j.get("calls_for_answer") or "").lower().strip()[:10]
    r["confused"] = str(j.get("confused") or "").lower().startswith("y")
    r["teach"] = str(j.get("teaching_moment") or "").lower().startswith("y")
    r["mix"] = str(j.get("lang_mix") or "").lower().strip()[:6]
    r["see"] = " ".join(str(j.get("they_see") or "").split())[:200]
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
        # 2026-11-03 (upgrade 4): a person who slips three times in a day on the same kind of thing learns it that day, not
        # next week - three slips noticed since his last lesson draw the lesson now (the night pass did it once a night)
        _P = (KS._load().get(_person_of(uid)) or {})
        _lt = max([float(x.get("t") or 0) for x in _P.get("lessons") or []] or [0])
        if sum(1 for x in _P.get("slips") or [] if float(x.get("t") or 0) > max(_lt, time.time() - 86400)) >= 3:
            KS.lessons_night(W, _person_of(uid))
    except Exception:
        pass
    try:                                               # 2026-10-31: the same read moves his heart and his needs (kino_psyche)
        import kino_psyche as KPS
        _lt = next((m.get("text") for m in reversed(M) if m.get("role") == "user"), "")
        KPS.from_read(_person_of(uid), uid, j, _lt)
    except Exception:
        pass
    try:                                               # 2026-10-31 (kino_depth): how his last message landed; what they believe
        import kino_depth as KDP
        _tl = max([float(m.get("t") or 0) for m in M if m.get("role") == "user"] or [time.time()])
        KDP.on_reply(_person_of(uid), j, _tl)
        if j.get("assumes"):
            KDP.note_assumes(_person_of(uid), j.get("assumes"))
    except Exception:
        pass
    _gk = " ".join(str(j.get("gave_kino") or "").split())[:240]
    if len(_gk) >= 6:                                  # 2026-11-03 (kino_ways): what he taught goes into his notebook, newest wins
        try:
            import kino_ways as KW
            KW.learn(W, _person_of(uid), M, hint=_gk, log=os.path.join(HERE, "kino_ways.log"))
        except Exception:
            pass
    try:                                               # 2026-10-31 (kino_selfmodel 2): what he seems to think of Kino
        import kino_selfmodel as KSF
        KSF.on_read(_person_of(uid), uid, j)
    except Exception:
        pass
    fj = " ".join(str(j.get("joke_fell_flat") or "").split())[:160]
    if len(fj) >= 8:                                   # what did not land is remembered too - a person adjusts to a friend
        try:
            import kino_inner as KI
            if fj[:60] not in [str(x.get("text") or "")[:60] for x in KI.moments(uid, "flat")]:
                KI.add_moment(uid, fj, "flat")
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
