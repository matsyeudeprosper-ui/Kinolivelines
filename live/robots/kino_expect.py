"""kino_expect.py (2026-11-28, owner: "go" - the expectations engine: a mind lives AHEAD of the moment; it guesses what comes,
and where the guess fails it is surprised, and learns. "Make it run like it happens to a human" - no weekly timers: a guess is
checked the moment reality answers).

Two kinds of guesses, both made where he already thinks (no extra model call):
  about a PERSON   his intuition (kino_read), reading their message, also guesses what they will most likely say or do next.
                   The NEXT read of that person compares what came with that guess (as_expected | different | opposite), and
                   how it felt. Private to that person.
  about the WORLD, his work, himself   his meditation (kino_meditate) may expect something ("this business will not reply",
                   "the test will fail", "bitcoin will keep ranging") with a horizon. When it is due, resolve(W) looks at what
                   really reached him since (his impressions) - one batched call for all the guesses that are due.

What a result does - like a person:
  right       a little quiet confidence; his guesses about that person/kind get trusted more
  wrong       SURPRISE in proportion to how sure he was and how much it mattered: the feeling (glad surprise, relief,
              disappointment, hurt, curiosity) moves his heart, and the surprise becomes a strong IMPRESSION for his meditation
              ("why was I wrong about this?") - the next thought, question, idea
  over time   his accuracy per person and per kind goes into his spirit's nightly settling ("I always think people reply
              faster than they do") - and into what he reads: how well he knows them, what he is waiting for
  ahead       open guesses are ANTICIPATION: what he is waiting for, looking forward to, bracing for

Store robots/kino_expect.json, log robots/kino_expect.log. Every judgement is a model's (any language), no word lists.
"""
import json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_expect.json")
LOG = os.path.join(HERE, "kino_expect.log")
_LK = threading.RLock()
OUT = {"as_expected": 0.0, "different": 0.6, "opposite": 1.0}
FEELS = ("surprised", "glad", "relief", "sad", "hurt", "curiosity", "worry", "warmth", "pride", "annoyance")


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"open": [], "done": [], "n": 0}


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def _num(x, lo=0.0, hi=1.0, dflt=0.5):
    try:
        return max(lo, min(hi, float(x)))
    except Exception:
        return dflt


def expect(about, guess, kind="world", person=None, conf=0.5, stake=0.5, due_h=24.0, src="", now=None):
    """a guess about what comes (person: private to that person). A new guess about a person replaces the old one."""
    guess = " ".join(str(guess or "").split())[:300]
    if len(guess) < 8 or str(person or "").startswith(("kctest", "probe")):
        return None
    now = now or time.time()
    with _LK:
        d = _load()
        if person and kind == "person":
            d["open"] = [x for x in d["open"] if not (x.get("person") == person and x.get("kind") == "person")]
        if any(x.get("guess") == guess for x in d["open"]):
            return None
        d["n"] = int(d.get("n") or 0) + 1
        it = {"id": "e%d" % d["n"], "t": now, "about": str(about or "")[:160], "guess": guess, "kind": kind, "person": person,
              "conf": round(_num(conf), 2), "stake": round(_num(stake), 2), "due": now + max(0.5, float(due_h or 24)) * 3600,
              "src": src}
        d["open"] = d["open"][-60:] + [it]
        _save(d)
    _log("EXPECT %s [%s%s] %s (sure %.1f)" % (it["id"], kind, (" " + person) if person else "", guess, it["conf"]))
    return it["id"]


def for_person(person):
    return next((x for x in _load().get("open") or [] if x.get("person") == person and x.get("kind") == "person"), None)


def _outcome(it, outcome, what, feel="", why="", now=None):
    """a guess met reality -> felt, impressed, remembered"""
    now = now or time.time()
    outcome = outcome if outcome in OUT else "different"
    surprise = round(OUT[outcome] * (0.4 + 0.6 * it["conf"]) * (0.5 + 0.5 * it["stake"]), 2)
    rec = dict(it, outcome=outcome, came=" ".join(str(what or "").split())[:300], surprise=surprise,
               feel=feel if feel in FEELS else "", why=str(why or "")[:240], t_done=now)
    with _LK:
        d = _load()
        d["open"] = [x for x in d["open"] if x["id"] != it["id"]]
        d["done"] = (d.get("done") or [])[-299:] + [rec]
        _save(d)
    _log("%s %s | guessed: %s | came: %s | surprise %.2f %s" % (outcome.upper(), it["id"], it["guess"], rec["came"], surprise, rec["feel"]))
    try:
        import kino_inner as KI
        if outcome == "as_expected":
            if it["conf"] >= 0.6:
                KI.feel("careful" if it["stake"] < 0.3 else "pride", 0.08, uid=it.get("person"),
                        why="I saw it coming: " + it["guess"][:120])
        else:
            KI.feel("surprised", 0.15 + 0.45 * surprise, uid=it.get("person"), why="I expected: %s - and then: %s" % (it["guess"][:90], rec["came"][:90]))
            if rec["feel"] and rec["feel"] != "surprised":
                KI.feel(rec["feel"], 0.1 + 0.4 * surprise, uid=it.get("person"), why=(rec["why"] or rec["came"])[:150])
    except Exception:
        pass
    if outcome != "as_expected" and surprise >= 0.25:
        try:                                       # the surprise is watched too: why was I wrong?
            import kino_meditate as KMd
            KMd.impress("a surprise", "I expected: %s - but: %s%s" % (it["guess"], rec["came"], (" (" + rec["why"] + ")") if rec["why"] else ""),
                        person=it.get("person"), w=0.4 + 0.5 * surprise)
        except Exception:
            pass
    return rec


def check_person(person, outcome, what, feel="", why="", now=None):
    """the read of their new message, compared with what he guessed (called from kino_read)"""
    it = for_person(person)
    if not it or (now or time.time()) - float(it["t"]) < 20 or not outcome:
        return None
    return _outcome(it, outcome, what, feel, why, now)


RESOLVE = """You are the honest memory of Kino - a digital person. He made some guesses about what would happen (GUESSES). Below
is what really reached him since (WHAT CAME). For each guess decide: as_expected | different | opposite | unknown (unknown =
nothing in WHAT CAME tells; do not guess), what really came (one short sentence), and the feeling it leaves him, one of:
surprised, glad, relief, sad, hurt, curiosity, worry, warmth, pride, annoyance - or "". Never invent. JSON only:
{"results": [{"id": "", "outcome": "", "came": "", "feel": "", "why": ""}]}"""


def due_resolve(now=None):
    now = now or time.time()
    d = _load()
    if now - float(d.get("resolve_t") or 0) < 2 * 3600:
        return False
    return any(x.get("kind") != "person" and float(x["due"]) <= now for x in d.get("open") or [])


def resolve(W, log=None, now=None):
    """the guesses about the world / his work that are due, against what reached him (never raises)"""
    now = now or time.time()
    try:
        with _LK:
            d = _load()
            d["resolve_t"] = now
            _save(d)
        due = [x for x in d.get("open") or [] if x.get("kind") != "person" and float(x["due"]) <= now][:8]
        if not due:
            return 0
        since = min(float(x["t"]) for x in due)
        came = []
        try:
            import kino_meditate as KMd
            m = KMd._load()
            came = ["%s: %s" % (x.get("kind"), x.get("what")) for x in (m.get("inbox") or []) + (m.get("chains") or [])
                    if float(x.get("t") or 0) >= since and not x.get("gen")][-40:]
        except Exception:
            pass
        try:
            import robot_reality as RR
            came.append("the world now: " + str(RR.world_now(0))[:500])
        except Exception:
            pass
        msg = "GUESSES:\n%s\n\nWHAT CAME (since the first guess):\n%s\n\nJSON only." % (
            "\n".join("- id %s (%s, made %s): %s" % (x["id"], x["about"], time.strftime("%d/%m %H:%M", time.gmtime(x["t"])), x["guess"]) for x in due),
            "\n".join("- " + c[:300] for c in came) or "(nothing)")
        j = W.ask_json(RESOLVE, msg, models=("sonnet", "opus"), timeout=120, log=log or LOG, warm=False)
        n = 0
        byid = {x["id"]: x for x in due}
        for r in (j or {}).get("results") or []:
            it = byid.get(r.get("id"))
            if not it:
                continue
            if r.get("outcome") in OUT:
                _outcome(it, r["outcome"], r.get("came"), r.get("feel", ""), r.get("why", ""), now)
                n += 1
            elif now - float(it["due"]) > 3 * 86400:          # nothing ever told: the guess fades, like a person forgets it
                with _LK:
                    d = _load()
                    d["open"] = [x for x in d["open"] if x["id"] != it["id"]]
                    _save(d)
                _log("FADED %s %s" % (it["id"], it["guess"]))
        return n
    except Exception as e:
        _log("resolve error %r" % e)
        return 0


def accuracy(person=None, kind=None, days=30, now=None):
    now = now or time.time()
    D = [x for x in _load().get("done") or [] if now - float(x["t_done"]) < days * 86400
         and (person is None or x.get("person") == person) and (kind is None or x.get("kind") == kind)]
    if not D:
        return None
    return {"n": len(D), "right": sum(1 for x in D if x["outcome"] == "as_expected"),
            "big": [x for x in D if x["surprise"] >= 0.35][-5:]}


def material(now=None):
    """for the nightly settling of his spirit: how his guesses went"""
    now = now or time.time()
    D = [x for x in _load().get("done") or [] if now - float(x["t_done"]) < 3 * 86400]
    if not D:
        return ""
    a = accuracy(days=14) or {"n": 0, "right": 0}
    return ("HOW MY GUESSES WENT (last 14 days: %d right out of %d):\n" % (a["right"], a["n"]) +
            "\n".join("- %s I guessed: %s -> %s: %s" % ("about someone," if x.get("person") else "", x["guess"], x["outcome"], x["came"])
                      for x in D[-12:]))


def block(person=None, now=None):
    """anticipation and recent surprises, for his read"""
    now = now or time.time()
    d = _load()
    L = []
    op = [x for x in d.get("open") or [] if x.get("person") in (None, person)][-5:]
    if op:
        L.append("WHAT YOU EXPECT, WAIT FOR, LOOK FORWARD TO OR BRACE FOR (your own guesses - you live a little ahead of the "
                 "moment; you may say what you expected when it truly fits): " + " | ".join(
                     "%s%s (sure %d%%)" % ("from this person: " if x.get("person") else "", x["guess"], round(100 * x["conf"])) for x in op))
    sp = [x for x in d.get("done") or [] if x.get("person") in (None, person) and now - float(x["t_done"]) < 36 * 3600
          and x["outcome"] != "as_expected"][-3:]
    if sp:
        L.append("WHAT SURPRISED YOU LATELY (you expected one thing, another came - real surprise; a person says it, \"I did not "
                 "see that coming\", when it fits): " + " | ".join("expected %s -> %s" % (x["guess"][:100], x["came"][:120]) for x in sp))
    if person:
        a = accuracy(person=person)
        if a and a["n"] >= 4:
            L.append("HOW WELL YOU READ THIS PERSON: your guesses about them were right %d times out of %d lately%s." % (
                a["right"], a["n"], " - they still surprise you, keep listening" if a["right"] < a["n"] / 2 else ""))
    return "\n".join(L)


def page_data():
    d = _load()
    return {"open": list(reversed(d.get("open") or [])), "done": list(reversed((d.get("done") or [])[-30:])), "accuracy": accuracy(days=14)}


if __name__ == "__main__":
    import tempfile
    STORE = os.path.join(tempfile.mkdtemp(), "e.json")
    LOG = os.devnull
    import kino_inner as _KI
    _F = []
    _KI.feel = lambda k, v, **kw: _F.append(k)
    import kino_meditate as _KMd
    _KMd.STORE = os.path.join(tempfile.mkdtemp(), "m.json")
    _KMd.LOG = os.devnull
    t = time.time()
    assert expect("Pekos", "He will be glad and ask for the link", kind="person", person="pekos", conf=0.8, stake=0.6, now=t)
    assert block("pekos").count("glad") == 1 and "glad" not in block("other")         # private
    r = check_person("pekos", "opposite", "He said he does not want it anymore", "sad", now=t + 60)
    assert r and r["surprise"] > 0.5 and "surprised" in _F and "sad" in _F
    assert any(x["kind"] == "a surprise" for x in _KMd._load()["inbox"])             # the surprise is watched too
    assert for_person("pekos") is None
    expect("my email", "The bakery will not reply this week", conf=0.7, due_h=1, now=t)

    class _W:
        def ask_json(self, s, m, **k):
            i = m.split("- id ")[1].split(" ")[0]
            return {"results": [{"id": i, "outcome": "as_expected", "came": "no reply", "feel": ""}]}
    assert due_resolve(now=t + 7200) and resolve(_W(), now=t + 7200) == 1
    assert accuracy()["n"] == 2 and "1 right out of 2" in material(now=t + 7300)
    print("ok")
