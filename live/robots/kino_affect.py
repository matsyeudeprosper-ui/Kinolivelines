"""kino_affect.py (2026-10-31, owner: "next" - after the outside review said his reports are not grounded in his states).

Until now a feeling reached him only as words ("you feel worried"). In a person a feeling changes the machinery first, and
the person often learns their own mood by noticing what they do (self-perception: Bem 1972; James-Lange). Here his feelings
set real settings of how he works - nothing in his words says so:
  - care      a tense, unpleasant state (worry, embarrassment, irritation) makes him think with the stronger model and check
              his words against the other one's reaction more strictly; a calm, pleasant one lets him trust his first draft
  - reach     a lively, pleasant state lowers what it takes for him to write on his own; a low, heavy one raises it
  - pace      arousal speeds up his private stream of thought; a low state slows it
Then the other half: he observes his OWN BEHAVIOUR against his usual - how long his messages are, how often he switched to
careful mode, how often he rewrote himself, how many messages of his own, how fast his thoughts came - without being told why.
That is the grounded signal: from it he can sense that something is going on in him even when no cause is written anywhere.

Valence (-1..1) and arousal (0..1) come from his live feelings (kino_inner.feelings, which includes the night probe's slipped-
in feeling on its own thread). Log robots/kino_affect.log (git-ignored).
"""
import json, os, re, statistics, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "kino_affect.log")
_LK = threading.Lock()
_CARE = {}                       # recent careful-mode turns: person -> [t]

# feeling kind -> (valence, arousal); unknown kinds are read by their first letters below
VA = {
    "worried": (-0.6, 0.8), "worry": (-0.6, 0.8), "anxious": (-0.7, 0.9), "irritated": (-0.6, 0.8), "embarrassed": (-0.5, 0.7),
    "embarrassment": (-0.5, 0.7), "hurt": (-0.6, 0.6), "restless": (-0.3, 0.8), "strained": (-0.4, 0.7), "uneasy": (-0.4, 0.6),
    "sad": (-0.6, 0.3), "regret": (-0.5, 0.4), "disappointed": (-0.5, 0.4), "tired": (-0.3, 0.1), "drained": (-0.4, 0.15),
    "sluggish": (-0.3, 0.15), "lonely": (-0.5, 0.3), "proud": (0.7, 0.6), "glad": (0.6, 0.5), "happy": (0.7, 0.6),
    "excited": (0.6, 0.9), "excitement": (0.6, 0.9), "curious": (0.4, 0.6), "amused": (0.6, 0.6), "playful": (0.6, 0.7),
    "grateful": (0.7, 0.4), "tender": (0.6, 0.2), "content": (0.5, 0.2), "calm": (0.4, 0.1), "relieved": (0.5, 0.2),
}


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def state(uid=None):
    """-> (valence, arousal) from the live feelings, weighted by strength"""
    try:
        import kino_inner as KI
        F = KI.feelings(uid)
    except Exception:
        F = []
    sw = sv = sa = 0.0
    for f in F[:6]:
        va = VA.get(str(f.get("kind") or "").lower())
        if not va:
            continue
        w = float(f.get("v") or 0) ** 2              # the strongest feeling dominates (squared weights)
        sw += w
        sv += w * va[0]
        sa += w * va[1]
    if sw < 0.04:
        return 0.0, 0.3
    k = min(1.0, sw ** 0.5)                           # weak feelings move him a little, strong ones fully
    return round(k * sv / sw, 2), round(0.3 + k * (sa / sw - 0.3), 2)


def knobs(uid=None):
    """the settings his state sets right now"""
    v, a = state(uid)
    tense = max(0.0, -v) * a                          # unpleasant and stirred up
    return {"v": v, "a": a,
            "careful": tense >= 0.25,                 # think with the stronger model
            "sim_bar": round(-0.1 + 0.5 * tense - 0.3 * max(0.0, v) * (1 - a), 2),   # how good the pictured reaction must be
            "reach": round(0.4 * v * a - 0.4 * max(0.0, -v) * (1 - a), 2),         # lowers (+) or raises (-) the bar to write
            "pace": round(0.6 + 0.8 * a, 2)}          # speed of the stream of thought (1 = usual)


def note_turn(person, model, careful, rewrote):
    """what he actually did on a turn - the raw material of noticing himself"""
    with _LK:
        L = _CARE.setdefault(person, [])
        L.append({"t": time.time(), "careful": bool(careful), "rewrote": bool(rewrote), "model": model})
        _CARE[person] = [x for x in L if time.time() - x["t"] < 24 * 3600][-200:]
    if careful or rewrote:
        _log("%s TURN model=%s careful=%s rewrote=%s" % (person, model, careful, rewrote))


def self_perception(person, msgs, en=False, extra=None):
    """what he notices in his own behaviour lately vs his usual - never what he feels, only what he does"""
    now = time.time()
    mine = [m for m in msgs if m.get("role") == "ai" and m.get("text") and not m.get("err")]
    recent = [m for m in mine if now - float(m.get("t") or 0) < 2 * 3600 and not m.get("event")][-6:]
    usual = [m for m in mine if 2 * 3600 <= now - float(m.get("t") or 0) < 8 * 86400 and not m.get("event")]
    if extra:                                          # the night probe hands the replies it just produced
        recent = [{"text": x} for x in extra]
    L = []
    if len(recent) >= 2 and len(usual) >= 10:
        rw = statistics.median(len(str(m["text"]).split()) for m in recent)
        uw = statistics.median(len(str(m["text"]).split()) for m in usual)
        if rw <= 0.65 * uw:
            L.append(("your messages are shorter than usual (%d words, usually %d)" if en else
                      "tes messages sont plus courts que d'habitude (%d mots, d'habitude %d)") % (rw, uw))
        elif rw >= 1.5 * uw:
            L.append(("your messages are longer than usual (%d words, usually %d)" if en else
                      "tes messages sont plus longs que d'habitude (%d mots, d'habitude %d)") % (rw, uw))
        rq = sum(1 for m in recent if "?" in str(m["text"])[-80:]) / len(recent)
        uq = sum(1 for m in usual if "?" in str(m["text"])[-80:]) / len(usual)
        if rq - uq >= 0.3:
            L.append("you are asking more questions than usual" if en else "tu poses plus de questions que d'habitude")
        ex = sum(str(m["text"]).count("!") for m in recent) / len(recent)
        uex = sum(str(m["text"]).count("!") for m in usual) / len(usual)
        if ex - uex >= 0.5:
            L.append("more exclamation marks than usual" if en else "plus de points d'exclamation que d'habitude")
    C = [x for x in _CARE.get(person, []) if now - x["t"] < 3 * 3600]
    if C:
        nc = sum(1 for x in C if x["careful"])
        nr = sum(1 for x in C if x["rewrote"])
        if nc >= 2 and nc >= 0.4 * len(C):
            L.append(("you kept switching to your careful, slower way of thinking (%d of your last %d replies)" if en else
                      "tu es souvent passé en mode prudent, plus lent (%d de tes %d dernières réponses)") % (nc, len(C)))
        if nr >= 2:
            L.append(("you rewrote yourself %d times before sending" if en else "tu t'es réécrit %d fois avant d'envoyer") % nr)
    own = [m for m in mine if m.get("event") and now - float(m.get("t") or 0) < 3 * 3600]
    if len(own) >= 3:
        L.append(("you wrote %d messages of your own in 3 hours" if en else "tu as écrit %d messages de toi-même en 3 heures") % len(own))
    if not L:
        return ""
    return (("What you notice in your own behaviour (what you DO, not why - nobody tells you why): " if en else
             "Ce que tu remarques dans ton propre comportement (ce que tu FAIS, pas pourquoi - personne ne te dit pourquoi) : ") +
            " ; ".join(L) + ".")
