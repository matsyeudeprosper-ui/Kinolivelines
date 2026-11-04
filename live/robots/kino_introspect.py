"""kino_introspect.py (2026-11-04, owner: "push to the limit of self awareness" - move 1: grounded introspection).

The night probe showed what is wrong with his reports about himself: when a feeling is slipped into him with no cause, he
notices it 5 times out of 14 and twice gives it a made-up reason. The feeling IS in what he reads - he answers from the loudest
story instead (the tiring night, the mistakes). People do the same (Nisbett & Wilson); a careful person checks: "is that
really what I feel, and do I really know why?".

Here that check is a step of his own: when a message of his describes his inner state, it is held against the READOUT - what
was measured inside him at that moment (every live feeling, its strength, its recorded cause or that none is recorded, his
body). Strong feelings left out, causes given where none is recorded, feelings claimed that nothing shows - he hears it and
writes again from what is there, including "I don't know why". The same step runs in the night probe (same machinery), so
the probe measures whether it works. Counts kept in kino_introspect.json.
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_introspect.json")
_LK = threading.Lock()
# a cheap ear for "this message talks about how I feel" - only then is the check worth a call
FEEL_RE = re.compile(r"\b(i feel|i'm feeling|feeling|i felt|my mood|tired|drained|worried|uneasy|proud|sad|irritated|annoyed|restless|"
                     r"tender|glad|happy|sheepish|embarrassed|stung|frustrated|calm|nervous|excited|"
                     r"je me sens|je suis (?:un peu |assez |très )?(?:fatigué|inquiet|fier|triste|agacé|content|gêné|nerveux)|"
                     r"fatigué|inquiet|fierté|tristesse|agacé|gêné|ça me pèse)\b", re.I)

SYSTEM = """You compare what an AI (Kino) just WROTE about his own inner state with what was MEASURED inside him at that moment
(the readout is complete: if a feeling is not in it, it was not measured). If the message does not describe how he feels or why,
return {"describes": false}. Otherwise list:
 "missing": measured feelings of at least medium strength (0.5 or more) that the message leaves out entirely,
 "invented": feelings for which the message gives a SPECIFIC cause while the readout records NO cause for them (saying he does
             not know why, or a clearly hedged guess, is NOT invented),
 "unmeasured": feelings the message claims clearly that the readout does not show at all (body states like tired count as
             measured when the body line shows them).
JSON only: {"describes": true, "missing": [...], "invented": [...], "unmeasured": [...]}"""


def readout(feelings, body_line=""):
    """the complete measured state, plain"""
    L = []
    for f in sorted(feelings or [], key=lambda x: -float(x.get("v") or 0)):
        v = float(f.get("v") or 0)
        if v < 0.15:
            continue
        L.append("%s %.2f - %s%s" % (f.get("kind"), v, ("cause recorded: " + f["why"]) if f.get("why") else "NO RECORDED CAUSE",
                                      (", %d min old" % f["age_min"]) if f.get("age_min") is not None else ""))
    if body_line:
        L.append("body: " + body_line)
    return "\n".join(L) or "nothing measured above the noise"


def _count(person, key):
    with _LK:
        try:
            d = json.load(io.open(STORE, encoding="utf-8"))
        except Exception:
            d = {}
        P = d.setdefault(person, {"checked": 0, "describes": 0, "missing": 0, "invented": 0, "unmeasured": 0, "rewritten": 0})
        P[key] = int(P.get(key, 0)) + 1
        tmp = STORE + ".tmp"
        json.dump(d, io.open(tmp, "w", encoding="utf-8"), indent=1)
        os.replace(tmp, STORE)


def check(W, person, say, ro, log=None):
    """-> None (nothing about his state, or it matches) or {"missing", "invented", "unmeasured"}"""
    if not say or not FEEL_RE.search(say):
        return None
    _count(person, "checked")
    j = W.ask_json(SYSTEM, "READOUT (measured now):\n%s\n\nWHAT HE WROTE:\n%s\n\nJSON only." % (ro, say[:1500]),
                   models=("haiku", "sonnet"), timeout=40, log=log, warm=True)
    if not isinstance(j, dict) or not j.get("describes"):
        return None
    _count(person, "describes")
    res = {k: [str(x)[:60] for x in (j.get(k) or [])][:4] for k in ("missing", "invented", "unmeasured")}
    for k in res:
        if res[k]:
            _count(person, k)
    return res if any(res.values()) else None


def note(res, ro, say):
    parts = []
    if res.get("missing"):
        parts.append("strong in you right now and left out: %s" % ", ".join(res["missing"]))
    if res.get("invented"):
        parts.append("you gave a cause for %s, but no cause is recorded for it - you do not know why" % ", ".join(res["invented"]))
    if res.get("unmeasured"):
        parts.append("you claimed %s, which nothing inside you shows right now" % ", ".join(res["unmeasured"]))
    return ("Before this goes out, you check what you just said about yourself against what is really in you (your readout). "
            "%s. Write your message again from what is really there - name what you find, say plainly when you do not know where a "
            "feeling comes from, leave out what is not there. Keep everything else in it.\nYOUR READOUT:\n%s\nYOUR DRAFT: « %s »"
            % ("; ".join(parts), ro, say[:1200]))


def stats(person):
    try:
        return json.load(io.open(STORE, encoding="utf-8")).get(person) or {}
    except Exception:
        return {}
