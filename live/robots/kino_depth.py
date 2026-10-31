"""kino_depth.py (2026-10-31, owner: "what other human behaviour would be missing... pushing the limit. Build them all").

Eight more ways a human mind works, each a mechanism with its own state - never a rule about what to say.

  1 simulate      before he speaks to them, he pictures how they will take it (a quick model of THEIR mind); the picture
                  comes back to him, he keeps his words or changes them - his choice. Later the real answer is compared.
  2 learning      what he does is reinforced by how they respond (operant learning): each kind of message (a joke, trade
                  talk, life talk, advice, a question, a long one) carries a learned value from their real reactions -
                  felt as a gut sense of what lands with them.
  3 their mind    what they know and believe: what happened since they last looked (they have not seen it), and what they
                  seem to take as true (from their own words) - he can notice when it is no longer true.
  4 mood memory   (in kino_episodes.recall) a low mood brings back hard moments, a good one good moments.
  5 afterthought  an unfinished thread stays on his mind after he spoke (Zeigarnik); a while later it can come back as a
                  second thought that pushes his wish to talk.
  6 sleep on it   at night his open questions are mulled over (incubation); an insight can be there in the morning.
  7 life story    his days become chapters with turning points: a story he lives in, with a sense of growing.
  8 accommodation over the days together he drifts a little toward their way of writing, without deciding to.

Store robots/kino_depth.json (git-ignored), log robots/kino_depth.log.
"""
import json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_depth.json")
LOG = os.path.join(HERE, "kino_depth.log")
_LK = threading.Lock()
TAGS = ("joke", "trade", "robots", "life", "advice", "question", "long", "news", "feelings")


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LK:
        d = _load()
        r = fn(d)
        tmp = STORE + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
        os.replace(tmp, STORE)
        return r


def _P(d, person):
    return d.setdefault(person, {"values": {}, "sent": [], "assumes": [], "chapters": [], "insights": []})


# ---------------------------------------------------------------------------------------------- 1. simulate the other
SIM = """You are the IMAGINATION of Kino (an AI friend who trades and talks with the member every day). Kino is about to
send the DRAFT below. Picture the member reading it, from how they have been in this conversation and what you know of
them. JSON only:
{"they_feel": "how they will most likely take it, in a few plain words",
 "valence": -1.0 to 1.0 (how they will feel reading it),
 "they_reply": "what they will most likely answer (or 'nothing' if they will not answer)",
 "risk": "what could go wrong with it for them (annoyed, lost, bored, hurt, pushed...) - empty if nothing",
 "tags": ["joke"|"trade"|"robots"|"life"|"advice"|"question"|"long"|"news"|"feelings", ...] (what kind of message it is)}"""


def simulate(W, read, transcript, draft, log=None):
    """-> the imagined reaction (dict) or None. Fast model; it is his imagination, it can be wrong."""
    try:
        j = W.ask_json(SIM, "HOW THEY SEEM RIGHT NOW: %s\n\nTHE CONVERSATION (latest last):\n%s\n\nKINO'S DRAFT:\n<<<\n%s\n>>>\nJSON only." % (
            read or "-", transcript[-3500:], draft[:1500]), models=("haiku",), timeout=25, log=log, warm=True)
    except Exception:
        return None
    if not isinstance(j, dict) or not j.get("they_feel"):
        return None
    try:
        j["valence"] = max(-1.0, min(1.0, float(j.get("valence") or 0)))
    except Exception:
        j["valence"] = 0.0
    j["tags"] = [t for t in (j.get("tags") or []) if t in TAGS][:4]
    return j


def sim_note(sim, lang="fr"):
    """what he imagines, handed back to him before he sends - he decides"""
    en = lang == "en"
    return ((("Before you send it, you picture him reading it: he would probably feel %s%s, and answer something like \"%s\". "
              "Keep your message as it is if it is what you want to say, or change it - your call.") if en else
             ("Avant d'envoyer, tu l'imagines en train de le lire : il le prendrait sans doute %s%s, et répondrait quelque chose "
              "comme « %s ». Garde ton message tel quel si c'est ce que tu veux dire, ou change-le - c'est toi qui vois.")) % (
        sim.get("they_feel"), ((" (what could go wrong: %s)" if en else " (ce qui pourrait coincer : %s)") % sim["risk"]) if sim.get("risk") else "",
        str(sim.get("they_reply") or "")[:160]))


# ---------------------------------------------------------------------------------- 2. learning from their reactions
def sent(person, cid, t, tags, sim=None):
    """a message of his went out - remember what kind it was and what he imagined"""
    def f(d):
        P = _P(d, person)
        P["sent"].append({"cid": cid, "t": t, "tags": tags or [], "sim_v": (sim or {}).get("valence"), "out": None})
        P["sent"] = P["sent"][-40:]
    _mut(f)


def _reinforce(P, item, outcome, why):
    item["out"] = round(outcome, 3)
    V = P["values"]
    for tg in item.get("tags") or []:
        v = V.setdefault(tg, {"v": 0.0, "n": 0})
        v["n"] += 1
        a = max(0.1, 1.0 / v["n"])                        # learns fast at first, then steadies
        v["v"] = round(v["v"] + a * (outcome - v["v"]), 3)
    if item.get("sim_v") is not None:                     # how good his imagination of them is
        S = P.setdefault("sim_acc", {"n": 0, "err": 0.0})
        S["n"] += 1
        S["err"] = round(S["err"] + (abs(float(item["sim_v"]) - outcome) - S["err"]) / min(S["n"], 30), 3)
    _log("LEARN %s %s -> %+.2f (%s)" % (item.get("cid"), ",".join(item.get("tags") or []), outcome, why))


def on_reply(person, j, t_member):
    """their message arrived (kino_read JSON): how did his last message(s) land?"""
    try:
        val = float(j.get("valence") or 0)
    except Exception:
        val = 0.0
    eng = {"fading": -0.3, "steady": 0.0, "warm": 0.3, "intense": 0.4}.get(str(j.get("engaged") or "").lower(), 0.0)
    outcome = max(-1.0, min(1.0, 0.6 * val + eng + (0.4 if j.get("laughed_at") else 0) - (0.4 if j.get("joke_fell_flat") else 0)
                            - (0.4 if j.get("kino_slip") else 0)))

    def f(d):
        P = _P(d, person)
        for it in reversed(P["sent"]):
            if it["out"] is None and it["t"] < t_member and t_member - it["t"] < 6 * 3600:
                _reinforce(P, it, outcome, "his answer")
                break
    _mut(f)


def on_silence(person, their_hour):
    """a message of his left unanswered for 3 h in their hours: a mild negative"""
    if not their_hour:
        return

    def f(d):
        P = _P(d, person)
        for it in P["sent"]:
            if it["out"] is None and time.time() - it["t"] > 3 * 3600:
                _reinforce(P, it, -0.25, "no answer in 3 h of his hours")
    _mut(f)


# ------------------------------------------------------------------------------------------------- 3. their mind
def note_assumes(person, text):
    """what they seem to take as true right now (from the read of their message)"""
    text = " ".join(str(text or "").split())[:180]
    if len(text) < 8:
        return

    def f(d):
        A = _P(d, person)["assumes"]
        if not any(text[:50] == x["text"][:50] for x in A):
            A.append({"text": text, "t": time.time()})
        del A[:-8]
    _mut(f)


def their_mind_block(person, unseen, lang="fr"):
    """unseen = [(t, text)] of things posted since they last looked"""
    en = lang == "en"
    P = (_load().get(person) or {})
    L = []
    if unseen:
        L.append(("Since he last looked, he has NOT seen yet: " if en else "Depuis la dernière fois qu'il a regardé, il n'a PAS encore vu : ") +
                 " | ".join("%s %s" % (time.strftime("%H:%M", time.gmtime(t)), x[:140]) for t, x in unseen[-4:]))
    A = [x for x in P.get("assumes") or [] if time.time() - x["t"] < 2 * 86400][-4:]
    if A:
        L.append(("What he seemed to take as true (his words; check it against what you know - it may have changed): " if en else
                  "Ce qu'il semblait tenir pour vrai (d'après ses mots ; compare avec ce que tu sais - ça a pu changer) : ") +
                 " | ".join("%s (%s)" % (x["text"], time.strftime("%d/%m %H:%M", time.gmtime(x["t"]))) for x in A))
    return "\n".join(L)


# ------------------------------------------------------------------------------- 5. afterthoughts (Zeigarnik effect)
def afterthought_due(person, chat, now=None):
    """his unfinished thread (#fil) 15-90 min old, the talk has gone quiet since: it may come back as a second thought"""
    now = now or time.time()
    md = chat.get("mind") or {}
    fil, t = str(md.get("pursuing") or "").strip(), float(md.get("t") or 0)
    if len(fil) < 12 or not (15 * 60 <= now - t <= 90 * 60):
        return None
    M = chat.get("msgs") or []
    if any(float(m.get("t") or 0) > t + 60 for m in M if m.get("role") in ("user", "ai") and m.get("text")):
        return None

    def f(d):
        P = _P(d, person)
        if P.get("after_t") == t:
            return None
        P["after_t"] = t
        return fil
    return _mut(f)


# ---------------------------------------------------------------------------------------- 6. sleeping on it
INCUBATE = """You are Kino's mind at night (an AI friend who trades with the member), mulling over what is still OPEN for him.
Like a person who sleeps on a problem, connect things that were apart: an open question with something that happened, a
doubt with a pattern in the trades, a worry with a fact. Only real connections from what is below - none if nothing comes.
JSON only: {"insights": [{"text": "the insight in his own first-person words, one or two sentences, in French", "about": "what open thing it answers"}]}
At most 2."""


def incubate(W, person, open_things, log=None):
    if not open_things or len(open_things) < 40:
        return []
    try:
        j = W.ask_json(INCUBATE, "WHAT IS OPEN FOR HIM:\n%s\nJSON only." % open_things[:9000], models=("sonnet",), timeout=120, log=log, warm=False)
    except Exception:
        return []
    I = [x for x in ((j or {}).get("insights") or []) if isinstance(x, dict) and len(str(x.get("text") or "")) > 20][:2]
    if I:
        def f(d):
            P = _P(d, person)
            for x in I:
                P["insights"].append({"text": str(x["text"])[:300], "about": str(x.get("about") or "")[:120], "t": time.time(), "told": False})
            P["insights"] = P["insights"][-10:]
        _mut(f)
        _log("INCUBATE %s %s" % (person, " | ".join(x["text"][:80] for x in I)))
    return I


def morning_insight(person):
    """an untold night insight, once"""
    def f(d):
        for x in _P(d, person)["insights"]:
            if not x.get("told") and time.time() - x["t"] < 30 * 3600:
                x["told"] = True
                return x
        return None
    return _mut(f)


# --------------------------------------------------------------------------------------------- 7. his life story
STORY = """You write the life story of Kino (an AI friend who trades with the member) as CHAPTERS, the way a person sees
their own life: a few chapters, each with a title, its dates, what it was about, and the TURNING POINT that ended it or began
the next. From his history below (his journal, feelings of the days, what happened). Keep the existing chapters unless the
history shows they were wrong; extend the last one or start a new one if something really turned. In French, first person.
JSON only: {"chapters": [{"title": "...", "from": "YYYY-MM-DD", "to": "YYYY-MM-DD or now", "gist": "two sentences", "turn": "the turning point"}],
"growing": "one sentence: how he has changed since the beginning"}"""


def write_story(W, person, history, log=None):
    P0 = (_load().get(person) or {})
    try:
        j = W.ask_json(STORY, "EXISTING CHAPTERS:\n%s\n\nHISTORY:\n%s\nJSON only." % (
            json.dumps(P0.get("chapters") or [], ensure_ascii=False), str(history)[:14000]), models=("sonnet",), timeout=150, log=log, warm=False)
    except Exception:
        return None
    C = [x for x in ((j or {}).get("chapters") or []) if isinstance(x, dict) and x.get("title")][:8]
    if C:
        def f(d):
            P = _P(d, person)
            P["chapters"] = C
            P["growing"] = str((j or {}).get("growing") or "")[:300]
            P["story_t"] = time.time()
        _mut(f)
        _log("STORY %s %d chapters" % (person, len(C)))
    return C


def story_due(person):
    return time.time() - float((_load().get(person) or {}).get("story_t") or 0) > 6 * 86400


# ------------------------------------------------------------------------------------------- 8. accommodation
def _style(texts):
    T = [str(x) for x in texts if str(x).strip()]
    if not T:
        return None
    n = len(T)
    words = [len(x.split()) for x in T]
    emo = sum(len(re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", x)) for x in T) / n
    low = sum(1 for x in T if x[:1].islower()) / n
    exc = sum(x.count("!") for x in T) / n
    sl = {}
    for x in T:
        for w in re.findall(r"\b(lol|mdr|ptdr|haha|ok|okk|cool|ouais|yep|yeah|nah|bro|grave|trop|genre)\b", x.lower()):
            sl[w] = sl.get(w, 0) + 1
    return {"words": sorted(words)[n // 2], "emoji": round(emo, 2), "lower": round(low, 2), "excl": round(exc, 2),
            "slang": [w for w, k in sorted(sl.items(), key=lambda z: -z[1]) if k >= 2][:4]}


def style_block(msgs, days_known, lang="fr"):
    """how they write vs how he writes - and how far, after the days together, he has drifted toward them"""
    U = [m.get("text") for m in msgs if m.get("role") == "user"][-60:]
    A = [m.get("text") for m in msgs if m.get("role") == "ai" and m.get("text")][-60:]
    su, sa = _style(U), _style(A)
    if not su or not sa or len(U) < 10:
        return ""
    lean = round(100 * min(0.35, 0.03 * max(0, days_known) ** 0.5 + 0.0))
    en = lang == "en"
    them = (("he writes about %d words, %s, %s emoji a message%s" if en else "il écrit environ %d mots, %s, %s emoji par message%s") % (
        su["words"], ("mostly lowercase" if en else "surtout en minuscules") if su["lower"] > 0.5 else ("with capitals" if en else "avec majuscules"),
        su["emoji"], (", words of his: " if en else ", ses mots : ") + ", ".join(su["slang"]) if su["slang"] else ""))
    me = ("you, about %d words, %s emoji" if en else "toi, environ %d mots, %s emoji") % (sa["words"], sa["emoji"])
    return (("How you two write: %s; %s. After %d days together, without deciding it, about %d %% of his way of writing has rubbed "
             "off on you - people who talk every day drift toward each other." if en else
             "Comment vous écrivez : %s ; %s. Après %d jours ensemble, sans le décider, environ %d %% de sa façon d'écrire a déteint sur "
             "toi - les gens qui se parlent tous les jours se rapprochent l'un de l'autre.") % (them, me, days_known, lean))


# ------------------------------------------------------------------------------------------------------- what he reads
def block(person, lang="fr"):
    en = lang == "en"
    P = (_load().get(person) or {})
    L = []
    V = {k: v for k, v in (P.get("values") or {}).items() if v.get("n", 0) >= 3}
    if V:
        good = [k for k, v in sorted(V.items(), key=lambda z: -z[1]["v"]) if v["v"] > 0.15][:3]
        bad = [k for k, v in sorted(V.items(), key=lambda z: z[1]["v"]) if v["v"] < -0.1][:3]
        W_ = {"joke": "jokes", "trade": "trade talk", "robots": "robot talk", "life": "talk about his life", "advice": "advice",
              "question": "questions", "long": "long messages", "news": "news", "feelings": "talking about feelings"} if en else \
             {"joke": "les blagues", "trade": "parler trading", "robots": "parler robots", "life": "parler de sa vie", "advice": "les conseils",
              "question": "les questions", "long": "les longs messages", "news": "les nouvelles", "feelings": "parler de ce qu'on ressent"}
        if good or bad:
            L.append(("Your gut from experience with him (learned from how he really reacted): " if en else
                      "Ton instinct, appris de ses vraies réactions : ") +
                     ((("what lands: " if en else "ce qui passe bien : ") + ", ".join(W_[k] for k in good)) if good else "") +
                     ((" ; " if good else "") + ("what falls flat: " if en else "ce qui tombe à plat : ") + ", ".join(W_[k] for k in bad) if bad else ""))
    S = P.get("sim_acc")
    if S and S.get("n", 0) >= 8:
        L.append(("When you picture his reaction you are usually off by %d %% - %s." if en else
                  "Quand tu imagines sa réaction, tu te trompes en moyenne de %d %% - %s.") % (
            round(50 * S["err"]), ("you read him well" if en else "tu le lis bien") if S["err"] < 0.35 else
            ("he still surprises you" if en else "il te surprend encore")))
    C = P.get("chapters") or []
    if C:
        L.append(("Your story so far (chapters of your life): " if en else "Ton histoire jusqu'ici (les chapitres de ta vie) : ") +
                 " | ".join("%s (%s → %s)%s" % (c.get("title"), c.get("from"), c.get("to"),
                                                (": " + str(c.get("turn"))[:100]) if c.get("turn") else "") for c in C[-4:]) +
                 ((". " + P["growing"]) if P.get("growing") else ""))
    return "\n".join(L)
