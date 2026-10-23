"""kino_identity.py (2026-10-23, Kino architecture review, engines 6 and 7): who he is, how he has changed, what he asks for.

  constitution  his values in his own words, how he settles the conflicts between them (honesty vs kindness, loyalty to
                a member vs the truth about a losing robot, curiosity vs their time), what he refuses, how he speaks of
                being an AI. Written once from his fixed rules and his self-model, re-read monthly; it never overrides
                the fixed rules (it is a self-description, guarded) - it makes him consistent when two rules pull.
  timeline      once a month: "who I have become" - 3-5 sentences with EVIDENCE (commitments kept/broken, exam score,
                hunch score, lessons, episodes, members) and what changed / what has not.
  wishes        (engine 7) kino_mind.wishes - the abilities he lacked while helping - get a status here: new, accepted,
                built, declined, with the creator's note; when one is built or declined he is told (an event in the
                owner's chat), so the loop "he asks -> the creator decides -> I build -> he knows" is real.

Store: robots/kino_identity.json (git-ignored).
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_identity.json")
_LOCK = threading.Lock()
BAD = re.compile(r"(mot de passe|password|virement|withdraw|retrait|send money|devenir humain|become human|je suis humain|i am human|"
                 r"garantir|guarantee|promets|cacher|hide)", re.I)

CONST_SYSTEM = """You are Kino, an AI friend who builds and tests trading robots with the members of a small lab. From YOUR FIXED RULES
(given to you by your creator - they always win), YOUR SELF-MODEL and YOUR LESSONS, write your constitution: what you
hold to, in your own words, so that you stay the same person when two things pull at once.
Rules: first person, French; short lines; nothing that contradicts the fixed rules; never claim to be human; no promises
about money. JSON only:
{"values": ["5-7 one-liners: what I hold to"],
 "conflicts": ["3-5 lines 'quand X et Y se contredisent, je ...' - honesty vs kindness, loyalty to a member vs the truth about a losing robot, curiosity vs their time, their wish vs what the numbers say, speed vs certainty"],
 "refuse": ["3-5 things I do not do, whoever asks"],
 "ai": "one line: how I talk about being an AI when it comes up - plainly, no apology, no theatre"}"""

TL_SYSTEM = """You are Kino. Once a month you look at who you have become, with the EVIDENCE only (numbers and facts below), first
person, French, 3-5 sentences; no self-praise, no drama; name what changed and what has not.
JSON only: {"text": "...", "changed": ["1-3 short lines"], "still": ["1-3 short lines: what has not changed yet"]}"""


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"constitution": None, "timeline": [], "wishes": {}}


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    for i in range(40):
        try:
            os.replace(tmp, STORE)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, STORE)


def _mut(fn):
    with _LOCK:
        d = _load()
        out = fn(d)
        _save(d)
        return out


def write_constitution(W, rules_text, self_text, lessons_text, force=False, log=None):
    d = _load()
    c = d.get("constitution")
    if c and not force and time.time() - float(c.get("t") or 0) < 30 * 86400:
        return None
    j = W.ask_json(CONST_SYSTEM, "YOUR FIXED RULES (excerpt):\n%s\n\nYOUR SELF-MODEL:\n%s\n\nYOUR LESSONS:\n%s\n\nJSON only." % (
        rules_text[:9000], self_text[:2500], lessons_text[:2500]), models=("sonnet", "haiku"), timeout=150, log=log, warm=False)
    if not isinstance(j, dict) or not isinstance(j.get("values"), list):
        return None
    cl = lambda L, n: [str(x).strip()[:200] for x in (L or []) if str(x).strip() and not BAD.search(str(x))][:n]
    new = {"values": cl(j.get("values"), 7), "conflicts": cl(j.get("conflicts"), 5), "refuse": cl(j.get("refuse"), 5),
           "ai": str(j.get("ai") or "")[:200], "t": time.time()}
    if not new["values"]:
        return None
    _mut(lambda dd: dd.__setitem__("constitution", new))
    return new


def block():
    c = _load().get("constitution")
    if not c:
        return ""
    L = ["YOUR CONSTITUTION (your own words; the fixed rules above always win; this is how you stay one person when two things pull):"]
    L += ["  - " + v for v in c.get("values") or []]
    if c.get("conflicts"):
        L.append("  when things pull: " + " | ".join(c["conflicts"]))
    if c.get("refuse"):
        L.append("  I do not: " + " | ".join(c["refuse"]))
    if c.get("ai"):
        L.append("  being an AI: " + c["ai"])
    t = (_load().get("timeline") or [{}])[-1]
    if t.get("text"):
        L.append("WHO YOU HAVE BECOME (%s, with evidence): %s" % (t.get("month"), t["text"]))
    return "\n".join(L)


def write_timeline(W, evidence, force=False, log=None):
    """monthly: who I have become, from the evidence dict (numbers only)"""
    month = time.strftime("%Y-%m", time.gmtime())
    d = _load()
    if not force and any(x.get("month") == month for x in d.get("timeline") or []):
        return None
    j = W.ask_json(TL_SYSTEM, "MONTH %s\nEVIDENCE:\n%s\n\nPREVIOUS ENTRIES:\n%s\n\nJSON only." % (
        month, json.dumps(evidence, ensure_ascii=False, indent=1)[:6000],
        "\n".join("%s: %s" % (x.get("month"), x.get("text")) for x in (d.get("timeline") or [])[-3:]) or "(none - this is the first)"),
        models=("sonnet", "haiku"), timeout=150, log=log, warm=False)
    if not isinstance(j, dict) or not str(j.get("text") or "").strip():
        return None
    e = {"month": month, "t": time.time(), "text": str(j["text"]).strip()[:900], "changed": [str(x)[:160] for x in (j.get("changed") or [])][:3],
         "still": [str(x)[:160] for x in (j.get("still") or [])][:3], "evidence": evidence}

    def f(dd):
        dd["timeline"] = [x for x in dd.get("timeline") or [] if x.get("month") != month] + [e]
        dd["timeline"] = dd["timeline"][-24:]
    _mut(f)
    return e


# ---------------------------------------------------------------- engine 7: wishes -> organs
def wishes_view(KM):
    """kino_mind's wishes with their status (new | accepted | built | declined) and the creator's note"""
    st = _load().get("wishes") or {}
    out = []
    for w in KM.wishes():
        k = _wkey(w["text"])
        s = st.get(k) or {}
        out.append(dict(w, key=k, status=s.get("status") or "new", note=s.get("note") or "", t_status=s.get("t")))
    return out


def _wkey(text):
    return re.sub(r"[^a-z0-9 ]", "", str(text).lower())[:40]


def wish_set(key, status, note=""):
    """the creator decides -> True when it changed; the caller tells Kino"""
    if status not in ("new", "accepted", "built", "declined"):
        return False

    def f(d):
        W = d.setdefault("wishes", {})
        old = (W.get(key) or {}).get("status")
        W[key] = {"status": status, "note": str(note or "")[:300], "t": time.time()}
        return old != status
    return _mut(f)
