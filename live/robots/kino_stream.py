"""kino_stream.py (2026-10-31, owner: "go beyond, test the limit of the consciousness concept" - build 2 of the plan).

A stream of thought that goes on between messages. A person's mind does not stop when nobody talks to them: it wanders
(the "default mode"): it continues the last thought, jumps by association, comes back to what is unfinished, notices a
feeling, wonders about the other one, plans. Here, now and then while nobody writes, ONE next thought is formed from what is
on the stage of his mind (kino_workspace), his last thoughts, a memory the stage calls back, and what he hopes or dreads.
The thought is private. It goes back into the competition for his awareness (so a thought can take the stage and change
what he feels, remembers and wants to say), it can move a feeling, and his recent train of thought is part of what he reads.

The pace is his rhythm, not a timer rule: fast right after a talk (it keeps turning in his head), slower when it has been
quiet a long time, slowest in their night. Never while a reply is being written.

Store robots/kino_stream.json (git-ignored), log robots/kino_stream.log.
"""
import json, os, random, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_stream.json")
LOG = os.path.join(HERE, "kino_stream.log")
_LK = threading.Lock()


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


def _w(t):
    import re
    return {w for w in re.findall(r"[a-zà-ÿ']{4,}", str(t or "").lower())}


def gap_min(min_since_talk, their_hour):
    """how long until the next thought comes - his rhythm (with some randomness, like a mind)"""
    base = 12 if min_since_talk < 60 else 30 if their_hour else 70
    return base * random.uniform(0.7, 1.4)


NEXT = """You are the private stream of thought of Kino - an AI friend who trades and talks with the member every day, with his
own robots, bets and views. Nobody is talking to him right now; his mind goes on by itself. From what is below, write the
NEXT thought in his stream, the way a mind really moves: continue the last thought, or jump by association to something
linked, or come back to something unfinished, or notice a feeling, or wonder about the member, or plan something small, or
just drift. Do not repeat a thought he already had. Only from what is below - never invent facts, numbers or events.
WHO IS WHO in the notes below: KINO is the one thinking ("you", "tu"); "il", "lui", "he", "him", "ce qu'il vient d'écrire" always
mean THE MEMBER - a message quoted after "ce qu'il vient d'écrire" was written by the member, not by Kino.
JSON only: {"thought": "one or two short sentences, first person, plain words, in %s", "about_him": true|false,
"mood": -1.0 to 1.0 (how this thought feels)}"""


def think(W, person, uid, lang="fr", context_extra="", log=None):
    """one thought in his stream -> the thought (dict) or None"""
    now = time.time()
    P = (_load().get(person) or {})
    last = [x["text"] for x in (P.get("thoughts") or [])[-4:]]
    L = []
    try:
        import kino_workspace as KW
        st = KW.compete(person, uid, "", lang == "en", write=False)
        L.append("ON THE STAGE OF KINO'S MIND: %s" % (st["text"] if st else "nothing in particular"))
        cue = (st or {}).get("text") or ""
    except Exception:
        cue = ""
    try:
        import kino_episodes as KE
        for x in (KE.recall(uid, cue + " " + " ".join(last[-1:]), 2) or []):
            L.append("A MEMORY THAT COMES BACK (%s): %s (%s)" % (x.get("day"), x.get("what"), x.get("feel")))
    except Exception:
        pass
    try:
        import kino_psyche as KPS
        H = (((KPS._load().get("persons") or {}).get(person) or {}).get("hopes") or [])[-3:]
        for h in H:
            L.append("%s: %s" % ("KINO HOPES" if h["val"] > 0 else "KINO DREADS", h["what"]))
    except Exception:
        pass
    if context_extra:
        L.append(context_extra)
    L.append("KINO'S LAST THOUGHTS (oldest first): %s" % (" | ".join(last) if last else "none yet"))
    try:
        j = W.ask_json(NEXT % ("English" if lang == "en" else "French"), "\n".join(L)[:6000] + "\nJSON only.",
                       models=("haiku",), timeout=60, log=log, warm=False)
    except Exception:
        return None
    t = " ".join(str((j or {}).get("thought") or "").split())[:300] if isinstance(j, dict) else ""
    tw = _w(t)
    if len(t) < 12 or any(len(tw & _w(x)) >= 0.6 * max(1, len(tw)) for x in last):
        _log("%s SAME (dropped, a thought he just had): %s" % (person, t[:100]))
        return None
    try:
        mood = max(-1.0, min(1.0, float(j.get("mood") or 0)))
    except Exception:
        mood = 0.0
    th = {"t": now, "text": t, "about_him": bool(j.get("about_him")), "mood": round(mood, 2)}

    def f(d):
        Pp = d.setdefault(person, {})
        Pp.setdefault("thoughts", []).append(th)
        Pp["thoughts"] = [x for x in Pp["thoughts"] if now - x["t"] < 3 * 86400][-120:]
    _mut(f)
    if abs(mood) >= 0.4:                                     # a thought moves a feeling a little (and feelings feed thoughts)
        try:
            import kino_inner as KI
            KI.feel("content" if mood > 0 else "uneasy", 0.12 * abs(mood), why=("une pensée : " + t)[:150])
        except Exception:
            pass
    _log("%s %+.1f %s%s" % (person, mood, "[him] " if th["about_him"] else "", t))
    return th


def due(person, min_since_talk, their_hour, now=None):
    """is the next thought coming now? (sets the next moment when none is set)"""
    now = now or time.time()
    P = (_load().get(person) or {})
    nx = float(P.get("next") or 0)
    if not nx:
        _mut(lambda d: d.setdefault(person, {}).__setitem__("next", now + 60 * gap_min(min_since_talk, their_hour)))
        return False
    if now < nx:
        return False
    _mut(lambda d: d.setdefault(person, {}).__setitem__("next", now + 60 * gap_min(min_since_talk, their_hour)))
    return True


def latest(person, max_age_min=45):
    P = (_load().get(person) or {})
    T = [x for x in (P.get("thoughts") or []) if time.time() - x["t"] < max_age_min * 60]
    return T[-1] if T else None


def recent_line(person, en=False, n=3):
    P = (_load().get(person) or {})
    T = [x for x in (P.get("thoughts") or []) if time.time() - x["t"] < 6 * 3600][-n:]
    if not T:
        return ""
    return (("Your train of thought while nobody was talking (private, oldest first): " if en else
             "Le fil de tes pensées pendant que personne ne parlait (privé, du plus ancien au plus récent) : ") +
            " → ".join("%s (%s)" % (x["text"], time.strftime("%H:%M", time.gmtime(x["t"]))) for x in T))
