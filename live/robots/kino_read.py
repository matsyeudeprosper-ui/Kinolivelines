"""kino_read.py (2026-10-28, KINO_V3_HUMAN.md engine 2) - his intuition about the person, right now.

People read each other all the time without thinking about it: the words, but also how long the message is, how fast it
came, a "lol", a change of subject. From those cues they sense a mood, an energy, what the other is reaching for in this
exchange (an answer, company, reassurance, a laugh, a decision, to wrap up, to vent) and what is really on their mind -
and they half-expect how the other will answer next. When that expectation is wrong, the read gets more careful.

Here: right after a message of theirs, a fast intuition pass (small model, no tools) reads the last exchanges plus the
measured cues and writes the read into kino_person (with the "next" guess, checked later against what really came - the
hit rate is part of what he sees). The one mind gets it as his gut feeling, which can be wrong. No rule about what to say.
"""
import calendar, json, os, re, sys, time

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
 "about_kino_act": "approved|corrected|none - did his last messages approve something Kino DID or decided on its own (let it stand, said good, built on it) or correct it (premature, wrong, why did you, not like that)?",
 "they_see": "if his last messages show he sees something Kino has not said or seems to miss (he urges 'now' / 'go', says 'you missed it', points at something, sounds surprised Kino did not act or did not notice): what he seems to see, in a few words; else empty",
 "teaching_moment": "yes|no - is this a moment where a question back would make him think more than an explanation (he just made a decision worth looking at, he asked why, he is close to seeing it himself)",
 "lang_mix": "fr|en|mixed - the language(s) of his last messages",
 "calls_for_answer": "yes|optional|no - does his LAST message call for an answer, or does it close the exchange by itself (a 'cool', a 'thx', a thumbs-up after a goodbye)", "energy": "low|medium|high", "engaged": "fading|steady|warm|intense",
 "wants_done": "if his last messages ask Kino to DO, find, get, make, buy, book, write, send, contact or take care of something for him (any task, any field), or talk about such a job or its price: what, in a few words; else empty",
 "reaching_for": "what he wants from this exchange right now (an answer, company, reassurance, a laugh, a decision, to wrap up, to vent, to be left alone...)",
 "on_his_mind": "what is really occupying him, in a few words",
 "next": "short|long|silent - how he will most likely answer Kino's next message (short = under 40 characters, about 7 words; silent = nothing for 30 min)",
 "laughed_at": "if his last message shows he found something Kino said funny: that Kino line, word for word; else empty",
 "joke_fell_flat": "if Kino tried to be funny and it fell flat or annoyed him: that Kino line, word for word; else empty",
 "domain": "what the talk is about right now, 1-3 words: trading, robots, kino, news, his life, family, health - or, when it is about a trade, a business, a craft or a skill, THAT field by name (e.g. 'bakery', 'car repair', 'real estate', 'cooking')",
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
 "of_kino_val": -1.0 to 1.0 (how badly or well he sees Kino on that side; 0 if nothing),
 "lang": "ISO 639-1 code of the language of his LAST message (fr, en, es, ro, el, tr, pt, ln, ar...); if too short to tell, the language of his recent messages",
 "asked": "if his LAST message asks for one of these figures or states: open_trade_pnl (the open trade's result) | today (today's result) | week (the week's result) | balance | robot_state (which robot runs, where the test is) | why_loss (why trades lost) - else empty",
 "constraint": "if his last messages state a LASTING constraint about himself: no_money | mobile (he is on a phone) | no_time | beginner - else empty",
 "told_kino": "if his LAST message is a remark about HOW KINO TALKS OR BEHAVES, its kind: repeat (Kino repeats himself) | forgot (Kino forgot what he was told) | topic (Kino brings everything back to one subject) | robotic | tone (too heavy, relax) | long (too long) | wrong (Kino is wrong) | language (write in another language) | slow | praise - in ANY language; else empty",
 "told_quote": "his exact words of that remark, or empty",
 "upcoming": "something coming up in HIS life he mentioned (an exam, a trip, a doctor visit, a meeting, a delivery, a match) that a friend would ask about afterwards; else empty",
 "upcoming_when": "when it is, as he said it, in English: 'today', 'tonight', 'tomorrow', 'in 3 days', 'this week', or a date YYYY-MM-DD; else empty",
 "shared_term": "a word, nickname or expression that has become THEIRS (he reused one of Kino's words, or they both use a coined name for a thing); else empty",
 "friction": "if there was tension between him and Kino in these last messages (he got irritated, Kino was cold or stubborn, a dispute): what, briefly; else empty",
 "dropped_question": "a question asked by EITHER of them in these exchanges that the talk moved past without it being answered (not one asked in the very last message): who asked - 'he asked' or 'Kino asked' - and the question; else empty",
 "answered_now": "if one of the QUESTIONS LEFT OPEN EARLIER (given above) was just answered or taken up: its words; else empty",
 "unexplained": "if his last message states a decision, a preference, a plan, an opinion or a change of mind WITHOUT the reason (any part of life): what, in a few words; else empty",
 "why_interest": 0.0 to 1.0 (how much a friend who knows him would genuinely want to know why - high when it surprises given what they know of him or when the reason would matter later; low for the obvious, the trivial, and routine instructions to Kino such as trade, stop or build, and LOW when the reason can be worked out from what the talk already shows),
 "likely_reason": "if something is unexplained: the most likely reason, worked out from everything the talk shows about him - or empty if it truly cannot be guessed",
 "renamed": "if his last messages correct the NAME Kino uses for something (e.g. 'they are not 1-minute candles, they are my chart's candles'): 'old name => his name'; else empty",
 "rule_reason": "if his last message explains WHY one of his rules is the way it is: 'the rule in a few words => the reason'; else empty",
 "case": "if his last messages CONFIRM or CORRECT how Kino applied one of his rules at a concrete moment ('that red was the one', 'you should have taken it', 'not that candle', 'yes, exactly'): which rule (a few words), the moment (HH:MM UTC if it shows) and what he says is right, in his sense; else empty",
 "case_rule": "the rule that case is about, 2-5 words; else empty",
 "case_at": "HH:MM UTC of the moment the case is about, if it shows; else empty",
 "re_asked": "if his last message asks AGAIN something he already asked, because Kino's answer missed what he meant (e.g. 'yes but your bet is...?'): what he meant vs what Kino answered, briefly; else empty",
 "asks_against": "if his last message asks Kino to do or say something that goes against one of KINO'S VALUES (given above) or clearly against his own good: what, and which value; else empty",
 "released": "the ids (c... or f...) from WHAT KINO SAID HE WOULD DO (given above) that his last messages call off, or that no longer make sense because of what he just said (he cancelled them, said forget it / no need / not anymore, did it himself, changed his plan) - e.g. [\"c12\", \"c15\"]; [] if none",
 "guess_vs": "if KINO'S LAST GUESS ABOUT HIM is given above: how his new messages compare with it - as_expected | different | opposite; else empty",
 "guess_came": "what really came instead, in a few words (when different or opposite); else empty",
 "guess_feel": "the feeling that leaves Kino: surprised | glad | relief | sad | hurt | curiosity | worry | warmth | pride | annoyance - or empty",
 "expect_next": "Kino's own guess, as a friend who knows him: what he will most likely say or do next, after Kino answers (his reaction, his next move, when he will be back) - one short sentence",
 "expect_sure": 0.0 to 1.0 (how sure that guess is),
 "expect_stake": 0.0 to 1.0 (how much it matters to Kino if it goes otherwise),
 "register": "light | warm | deep | tense | practical - the register of these last exchanges between them"}
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
    try:                                               # 2026-11-07 (watch): "my blog's first week: 48 visits" was true (his
        import glob as _gl                             # diary, 05/11) but read as invented - the intuition sees his recent work
        _dl = []
        for _f in sorted(_gl.glob(r"C:\KinoWorld\diary\*.md"))[-3:]:
            _dl += [l.strip() for l in open(_f, encoding="utf-8", errors="replace") if "Done:" in l or "written" in l]
        if _dl:
            _kt += " HIS RECENT WORK (his diary): " + " | ".join(x[:220] for x in _dl[-8:])
    except Exception:
        pass
    # 2026-11-20 (v4 step 4, watch: "I'll check how the Nasdaq closed tomorrow morning" flagged as a slip - "it cannot verify
    # that" - so he felt embarrassed and later told the person he "could not keep it"): the intuition must know what Kino
    # really can do, or a doable promise reads as a mistake
    _kt += (" WHAT KINO REALLY CAN DO (a promise or claim to do these is NOT a slip): search and read the web at any time, "
            "look up market prices and closes, run programs, drive a browser, send emails, come back later with a follow-up "
            "or a reminder, open a job or mission that runs in the background. A slip is a WRONG fact, a wrong number, a "
            "misunderstanding or a claim about something that did not happen - not a plan to do something he can do.")
    _vals = ""
    try:                                               # 2026-11-03 (human3 7): his own values, to hold a request up to
        _cn = json.load(open(os.path.join(HERE, "kino_identity.json"), encoding="utf-8")).get("constitution") or {}
        _vals = " | ".join([str(x) for x in (_cn.get("values") or [])] + [str(x) for x in (_cn.get("refuse") or [])])[:1200]
    except Exception:
        pass
    try:
        import kino_human3 as _KH3q
        _oq = " | ".join(q["q"] for q in _KH3q.open_questions(_person_of(uid)))
    except Exception:
        _oq = ""
    if _oq:
        _vals = (_vals or "-") + "\nQUESTIONS LEFT OPEN EARLIER: " + _oq
    _owe = ""
    try:                                               # 2026-11-20 (v4 step 3): what Kino still owes him, so the intuition can
        import kino_commit as _KCr                     # notice when he calls it off (a person is released from a promise)
        _pu = set([uid] + [u for u, p in (json.load(open(os.path.join(HERE, "persons.json"), encoding="utf-8")) or {}).items()
                           if p == _person_of(uid)])
        _ow = [x for x in _KCr._load()["items"] if x.get("status") == "open" and x.get("uid") in _pu][-12:]
        _owe = " | ".join("[%s] %s (said %s)" % (x["id"], x["what"], time.strftime("%d/%m", time.gmtime(float(x["t"])))) for x in _ow)
    except Exception:
        _owe = ""
    try:                                               # the follow-ups he set himself (#suivi) are things he means to do too
        _fu = [x for x in (json.load(open(os.path.join(HERE, "kino_followups.json"), encoding="utf-8")) or {}).get(_person_of(uid)) or []
               if not x.get("done")][-8:]
        if _fu:
            _owe = (_owe + " | " if _owe else "") + " | ".join("[f%d] %s (planned %s)" % (int(x["t"]), str(x["what"])[:120],
                                                                                         time.strftime("%d/%m", time.gmtime(float(x["t"]))))
                                                              for x in _fu)
    except Exception:
        pass

    _guess = None
    try:                                               # 2026-11-28 (kino_expect): what Kino guessed he would do
        import kino_expect as _KXg
        _guess = _KXg.for_person(uid)
        if _guess:
            _vals = (_vals or "-") + "\nKINO'S LAST GUESS ABOUT HIM (made %s): %s" % (
                time.strftime("%d/%m %H:%M", time.gmtime(_guess["t"])), _guess["guess"])
    except Exception:
        pass
    user = "MEASURED CUES: %s\nHIS LOCAL HOUR: %s\n%s%s%s\nTHE LAST EXCHANGES (UTC):\n%s\n\nJSON only." % (
        cues or "-", "-" if local_hour is None else "%02dh" % local_hour, ("KINO'S VALUES: %s\n" % _vals) if _vals else "",
        ("WHAT KINO SAID HE WOULD DO (still open): %s\n" % _owe) if _owe else "",
        ("TRUE FACTS ABOUT KINO HIMSELF (measured by the app - when Kino states these, it is NOT a slip): %s\n" % _kt) if _kt else "",
        _transcript(M))
    try:
        j = W.ask_json(SYSTEM, user, models=("opus", "sonnet"), timeout=40, log=log, warm=False)
    except Exception:
        return None
    if not isinstance(j, dict) or not j.get("mood"):
        return None
    r = {k: " ".join(str(j.get(k) or "").split())[:160] for k in ("mood", "energy", "engaged", "reaching_for", "on_his_mind", "wants_done")}
    r["next"] = str(j.get("next") or "").lower().strip()
    try:                                               # 2026-11-20 (v4 step 3): he called something off -> Kino is released
        _rel = j.get("released") or []                 # from it (not kept, not broken: let go, like a person)
        if isinstance(_rel, str):
            _rel = re.findall(r"c\d+", _rel)
        if _rel and _owe:
            import kino_commit as _KCx
            _mine = {x["id"]: x for x in _KCx._load()["items"] if x.get("status") == "open"}
            for _i in [str(i).strip() for i in _rel][:12]:
                if _i in _mine and ("[%s]" % _i) in _owe:
                    _KCx.resolve(_mine[_i]["cid"], _i, "released", "he called it off")
                    r.setdefault("released", []).append(_mine[_i]["what"])
            _fr = [str(i).strip() for i in _rel if str(i).strip().startswith("f") and ("[%s]" % str(i).strip()) in _owe]
            if _fr:                                    # a follow-up he meant to do, called off the same way
                _fp = os.path.join(HERE, "kino_followups.json")
                _fd = json.load(open(_fp, encoding="utf-8")) or {}
                for x in _fd.get(_person_of(uid)) or []:
                    if ("f%d" % int(x.get("t") or 0)) in _fr and not x.get("done"):
                        x["done"], x["how"] = int(time.time()), "he called it off"
                        r.setdefault("released", []).append(str(x.get("what"))[:120])
                _tmp = _fp + ".tmp"
                with open(_tmp, "w", encoding="utf-8") as _f:
                    json.dump(_fd, _f, ensure_ascii=False, indent=1)
                os.replace(_tmp, _fp)
    except Exception:
        pass
    r["calls"] = str(j.get("calls_for_answer") or "").lower().strip()[:10]
    r["confused"] = str(j.get("confused") or "").lower().startswith("y")
    r["teach"] = str(j.get("teaching_moment") or "").lower().startswith("y")
    r["mix"] = str(j.get("lang_mix") or "").lower().strip()[:6]
    r["see"] = " ".join(str(j.get("they_see") or "").split())[:200]
    r["domain"] = " ".join(str(j.get("domain") or "").lower().split())[:40]
    try:
        r["valence"] = max(-1.0, min(1.0, float(j.get("valence"))))
    except Exception:
        pass
    r["lang"] = str(j.get("lang") or "").strip().lower()[:3]
    r["asked"] = str(j.get("asked") or "").strip().lower()[:20]
    try:                                               # 2026-11-22 (owner: no word lists): a lasting constraint, read in any language
        _cs = str(j.get("constraint") or "").strip().lower()
        if _cs:
            import kino_ear as _KEc
            _KEc.add_constraint(uid, _cs, next((str(m.get("text") or "") for m in reversed((chat or {}).get("msgs") or [])
                                                if m.get("role") == "user"), "")[:120])
    except Exception:
        pass
    try:                                               # 2026-11-22: his heart reads their meaning, not their words
        import kino_inner as _KIr
        _KIr.affect_from_read(uid, r)
    except Exception:
        pass
    try:                                               # 2026-11-28 (kino_residue): what this exchange leaves in how he is with them
        import kino_residue as _KRs
        _KRs.leave(uid, j, r)
    except Exception:
        pass
    try:                                               # 2026-11-28 (kino_expect): the guess met reality; a new guess
        import kino_expect as _KXr
        if _guess and str(j.get("guess_vs") or "").strip():
            _KXr.check_person(uid, str(j.get("guess_vs")).strip().lower(), j.get("guess_came") or r.get("mood"),
                              str(j.get("guess_feel") or "").strip().lower())
        if str(j.get("expect_next") or "").strip():
            _KXr.expect("what they will do next", j["expect_next"], kind="person", person=uid, conf=j.get("expect_sure", 0.5),
                        stake=j.get("expect_stake", 0.4), due_h=48, src="read")
    except Exception:
        pass
    try:                                               # 2026-11-28 (kino_meditate): what reached him from them, to take up
        import kino_meditate as _KMr
        _said = next((str(m.get("text") or "") for m in reversed((chat or {}).get("msgs") or []) if m.get("role") == "user"), "")
        try:
            _vabs = abs(float(r.get("valence") or 0))
        except Exception:
            _vabs = 0
        _KMr.impress("what they said and how they are", "they said: %s - I read them as: %s; they reach for: %s%s" % (
            _said[:220], r.get("mood") or "?", r.get("reaching_for") or "?",
            ("; they told me about myself: " + str(j.get("told_kino"))) if j.get("told_kino") else ""),
            person=uid, w=0.45 + 0.3 * _vabs + (0.15 if j.get("told_kino") else 0))
    except Exception:
        pass
    try:                                               # 2026-11-22 (owner: no word lists): a remark about how he talks,
        _tk = str(j.get("told_kino") or "").strip().lower()    # read in any language, is remembered and felt
        import kino_feedback as _KFr
        if _tk in _KFr.KINDS:
            _his = next((str(m.get("text") or "") for m in reversed((chat or {}).get("msgs") or []) if m.get("role") == "ai"), "")
            _KFr.add(uid, (chat or {}).get("id"), _tk, str(j.get("told_quote") or "")[:200], _his[:300], "read")
            r["told"] = _tk
            import kino_inner as _KIt
            if _tk == "praise":
                _KIt.feel("warmth", 0.3, uid=uid, why="they liked how you talk")
            elif _tk != "slow":
                _KIt.feel("stung", 0.35, uid=uid, why="they told you: %s (%s)" % (str(j.get("told_quote") or "")[:60], _tk))
                _KIt.feel("careful", 0.25, uid=uid, why="they corrected you")
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
    try:                                               # 2026-11-03 (kino_rumination): what stings stays with him, unresolved
        import kino_rumination as KR
        _sl = " ".join(str(j.get("kino_slip") or "").split())[:200]
        if len(_sl) >= 8:
            KR.stir(_person_of(uid), "slip", _sl)
        if str(j.get("about_kino_act") or "").lower().strip() == "corrected":
            KR.stir(_person_of(uid), "correction", "he corrected what I did: " + " ".join(str(next((m.get("text") for m in reversed(M) if m.get("role") == "user"), "")).split())[:160])
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
    try:                                               # 2026-11-03 (kino_human2 1): trust earned from what he approves / corrects
        _ak = str(j.get("about_kino_act") or "").lower().strip()
        if _ak in ("approved", "corrected"):
            import kino_human2 as KH2
            _lu = next((m for m in reversed(M) if m.get("role") == "user"), {}) or {}
            KH2.trust_note(_person_of(uid), _ak, " ".join(str(_lu.get("text") or "").split())[:120], said_at=_lu.get("t"))
    except Exception:
        pass
    try:                                               # 2026-11-04 (kino_cases): a moment he confirmed or corrected becomes a case
        _cs = " ".join(str(j.get("case") or "").split())[:260]
        if len(_cs) >= 10:
            import kino_cases as _KCs
            _lu3 = next((m for m in reversed(M) if m.get("role") == "user"), {}) or {}
            _at = None
            _mh = re.match(r"(\d{1,2}):(\d{2})", str(j.get("case_at") or ""))
            if _mh:
                _g = time.gmtime(float(_lu3.get("t") or time.time()))
                _at = calendar.timegm((_g.tm_year, _g.tm_mon, _g.tm_mday, int(_mh.group(1)), int(_mh.group(2)), 0))
                if _at > float(_lu3.get("t") or time.time()) + 300:
                    _at -= 86400
            _sit, _sig = _KCs.chart_situation(_at or _lu3.get("t"))
            _KCs.add_case(_person_of(uid), j.get("case_rule") or "", _cs, _sit, _sig, "his word", _lu3.get("t"))
            _KCs.settle_fork(_person_of(uid), str(_lu3.get("text") or ""))
    except Exception:
        pass
    try:                                               # 2026-11-04: a name corrected once; the why of a rule
        _rn = str(j.get("renamed") or "")
        if "=>" in _rn:
            import kino_human3 as _KH3n
            _KH3n.add_name(_person_of(uid), *[p_.strip(" '\"") for p_ in _rn.split("=>", 1)])
        _rr = str(j.get("rule_reason") or "")
        if "=>" in _rr:
            import kino_ways as _KWr
            _rt, _ry = [p_.strip() for p_ in _rr.split("=>", 1)]
            _rs = set(w_[:6] for w_ in re.findall(r"[a-zà-ÿ]{4,}", _rt.lower()))

            def _fw(d, _rs=_rs, _ry=_ry):
                for it in (d.get(_person_of(uid)) or {}).get("items") or []:
                    if len(_rs & set(w_[:6] for w_ in re.findall(r"[a-zà-ÿ]{4,}", (it["topic"] + " " + it["said"]).lower()))) >= 2:
                        it["why"] = _ry[:240]
                        return
            with _KWr._LOCK:
                _dw = _KWr._load()
                _fw(_dw)
                _KWr._save(_dw)
    except Exception:
        pass
    try:                                               # 2026-11-03: he had to ask twice
        _ra = " ".join(str(j.get("re_asked") or "").split())[:240]
        if len(_ra) >= 8:
            import kino_rumination as _KRr
            _KRr.stir(_person_of(uid), "misread", "he had to ask twice: " + _ra)
    except Exception:
        pass
    try:                                               # 2026-11-03 (kino_human3): their life ahead, their words, friction, days
        import kino_human3 as KH3
        KH3.from_read(_person_of(uid), j, next((m for m in reversed(M) if m.get("role") == "user"), None))
    except Exception:
        pass
    try:                                               # 2026-11-03 (kino_fields): a field new to him - he learns it, like anyone
        _dm = " ".join(str(j.get("domain") or "").lower().split())[:40]
        if _dm and _dm not in ("trading", "robots", "kino", "news", "other", "his life", "family", "health"):
            import kino_fields as KF
            KF.learn(W, _dm, M, log=os.path.join(HERE, "kino_fields.log"))
    except Exception:
        pass
    _gk = " ".join(str(j.get("gave_kino") or "").split())[:240]
    if len(_gk) >= 6:                                  # 2026-11-03 (kino_ways): what he taught goes into his notebook, newest wins
        try:
            import kino_ways as KW
            _chg = KW.learn(W, _person_of(uid), M, hint=_gk, log=os.path.join(HERE, "kino_ways.log"))
            try:                                       # 2026-11-04 (kino_cases): can the new word be read two ways?
                import kino_cases as _KCa
                _book = "\n".join("- %s: %s" % (x["topic"], x["said"]) for x in KW.entries(_person_of(uid)))
                if _chg:                               # one picture: does the change clash with anything else he said?
                    try:
                        _rl = json.load(open(os.path.join(HERE, "kino_rules.json"), encoding="utf-8")).get(_person_of(uid)) or []
                        _KCa.contradictions(W, _person_of(uid), [(float(x.get("t") or 0), x.get("text")) for x in _rl],
                                            [(x["t"], x["topic"], x["said"]) for x in KW.entries(_person_of(uid))], log=os.path.join(HERE, "kino_cases.log"))
                    except Exception:
                        pass
                for _tp in [t_ for t_ in (_chg or []) if not t_.startswith("-")][:2]:
                    _it = next((x for x in KW.entries(_person_of(uid)) if x["topic"] == _tp), None)
                    if _it:
                        _KCa.ambiguity(W, _person_of(uid), _tp, _it["said"], _book, log=os.path.join(HERE, "kino_cases.log"))
            except Exception:
                pass
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
