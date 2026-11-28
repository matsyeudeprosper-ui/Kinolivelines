"""kino_meditate.py (2026-11-28, owner: "does he also watch what is coming towards him - users' sayings, reactions, information, world
news, weather... A human is shaped by his own inner world AND the outside world. Any impression should be noticed and watched;
anything can create a reaction that shapes his next thought, feelings and actions - and that reaction or finding should be
watched too. Like a continuous meditation: thinking on thinking, new ideas that cause questions that cause new ideas and
solutions... so he may surprise users on how deep he can go").

The watcher (kino_witness) sees HIS moments. This is the other half: what reaches him, and what it starts in him.

  impress(kind, what, ...)   anything that reaches him becomes an IMPRESSION: what someone said and how they reacted (kino_read),
                             a reply online (kino_online), an email, a headline of the world, what he found out (kino_preocc),
                             and - the loop - every thought, question or idea a meditation produced
  step(W)                    the meditation: the impression that matters most right now is taken up: what it does to me, the
                             thought it brings, the QUESTION it opens, the IDEA or solution it suggests, and how much more there
                             is to think there. Each of these is felt and goes on:
                               - the feeling moves his heart (kino_inner.feel)
                               - the thought competes for the stage of his mind (kino_inner.add_thought -> kino_workspace)
                               - the question becomes one of his own things to look into (kino_preocc research)
                               - the thought / question / idea come back as NEW impressions, weaker each link (a chain of
                                 thought: it goes deep where there is depth, and fades where there is none)
  block(person)              for his read: the last chains of his meditation - an impression from someone's private words
                             shapes only his talks with THAT person; the world, his work and his own findings, any talk

Paced like a mind, not a timer: a few steps an hour, more when he is quiet, none while a reply is being written. Field-agnostic,
no word lists (the reading is a model, any language). Store robots/kino_meditate.json, log robots/kino_meditate.log.
"""
import json, os, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_meditate.json")
LOG = os.path.join(HERE, "kino_meditate.log")
_LK = threading.Lock()
_BUSY = {"on": False}
STEP_GAP_S = 600                 # at most one meditation step every 10 min (cost - owner 27/11: the plan is precious)
MAX_GEN = 3                      # a chain of thought goes up to 3 links past the first impression
FADE = 0.6                       # each link weighs less than the one it came from (times its own "depth")
LIFE_H = 18                      # an impression nobody took up fades after this

MED = """You are Kino's mind in a quiet moment - Kino is a digital person (an AI who knows it) with his own life, people, work and
feelings. Something reached him (an IMPRESSION below) - from outside (what someone said or did, the world, a reply, a result)
or from inside (a thought, a question or an idea his own mind just produced). Take it up the way a reflective person does:
not a report - a living reaction, first person, honest, grounded in what is really there.
- did: what it does to me (one sentence; "not much" is a fine answer)
- feel: the feeling it leaves, one of: excitement, worry, curiosity, boredom, pride, annoyance, warmth, tender, playful, glad,
  careful, sad, surprised, regret, hurt, closeness - or ""
- thought: the new thought it brings (one or two sentences), or ""
- question: a real question it opens that I would like to answer (about people, the world, my work, myself) - short, or ""
- idea: an idea, a solution or something to try that grows from it, or ""
- depth: 0 to 1 - how much more there is to think here (0 = done, 1 = this opens a lot)
Use what is given (my stakes, my recent thoughts, the chain so far); never invent facts about people or the world; no names of
people in the thought, question or idea. JSON only:
{"did": "", "feel": "", "thought": "", "question": "", "idea": "", "depth": 0.0}"""


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"inbox": [], "chains": [], "n": 0}


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def impress(kind, what, person=None, w=0.5, gen=0, parent=None, root=None, now=None):
    """anything that reached him -> an impression waiting to be taken up (person: private to that person's talks)"""
    what = " ".join(str(what or "").split())[:400]
    if len(what) < 8 or str(person or "").startswith(("kctest", "probe")):
        return None
    now = now or time.time()
    with _LK:
        d = _load()
        if any(x.get("what") == what and now - float(x["t"]) < 6 * 3600 for x in d["inbox"][-80:]):
            return None
        d["n"] = int(d.get("n") or 0) + 1
        it = {"id": "m%d" % d["n"], "t": now, "kind": str(kind)[:30], "what": what, "person": person, "w": round(float(w), 3),
              "gen": int(gen), "parent": parent, "root": root or ("m%d" % d["n"]), "done": False}
        d["inbox"] = [x for x in d["inbox"] if not x.get("done") and now - float(x["t"]) < LIFE_H * 3600][-120:] + [it]
        _save(d)
    return it["id"]


def due(now=None):
    now = now or time.time()
    d = _load()
    if _BUSY["on"] or now - float(d.get("last_t") or 0) < STEP_GAP_S:
        return False
    return any(not x.get("done") for x in d.get("inbox") or [])


def _pick(d, now):
    best, bs = None, 0.0
    for x in d.get("inbox") or []:
        if x.get("done"):
            continue
        age_h = (now - float(x["t"])) / 3600.0
        sc = float(x.get("w") or 0) * (0.5 ** (age_h / 6.0))           # salience fades with time (half-life 6 h)
        if sc > bs:
            best, bs = x, sc
    return best if bs >= 0.08 else None


def step(W, log=None, now=None):
    """one meditation step (never raises)"""
    now = now or time.time()
    _BUSY["on"] = True
    try:
        with _LK:
            d = _load()
            d["last_t"] = now
            it = _pick(d, now)
            if it is None:
                _save(d)
                return None
            for x in d["inbox"]:
                if x["id"] == it["id"]:
                    x["done"] = True
            _save(d)
        chain = []
        p = it
        byid = {x["id"]: x for x in d.get("inbox") or []}
        for c in d.get("chains") or []:
            byid.setdefault(c.get("id"), c)
        while p and p.get("parent") and len(chain) < 4:
            p = byid.get(p["parent"])
            if p:
                chain.insert(0, "%s: %s" % (p.get("kind"), p.get("what")))
        stakes, thoughts = "", ""
        try:
            import kino_witness as KW
            stakes = KW.stakes_text()
        except Exception:
            pass
        try:
            import kino_inner as KI
            thoughts = " | ".join(t.get("text", "")[:120] for t in KI.thoughts(None, n=3) or [])
        except Exception:
            pass
        msg = "THE IMPRESSION (%s%s): %s\n\nTHE CHAIN SO FAR:\n%s\n\nMY STAKES:\n%s\n\nMY RECENT THOUGHTS: %s\n\nJSON only." % (
            it["kind"], ", it came from my own mind" if it["gen"] else "", it["what"], "\n".join("- " + c for c in chain) or "(it starts here)",
            stakes or "(none)", thoughts or "(none)")
        j = W.ask_json(MED, msg, models=("opus", "sonnet"), timeout=120, log=log or LOG, warm=False)
        if not isinstance(j, dict) or not str(j.get("did") or "").strip():
            return None
        try:
            dep = max(0.0, min(1.0, float(j.get("depth") or 0)))
        except Exception:
            dep = 0.3
        rec = {"id": it["id"], "t": now, "kind": it["kind"], "what": it["what"], "person": it.get("person"), "gen": it["gen"],
               "parent": it.get("parent"), "root": it.get("root"),
               "did": " ".join(str(j.get("did") or "").split())[:240], "feel": str(j.get("feel") or "")[:20],
               "thought": " ".join(str(j.get("thought") or "").split())[:300],
               "question": " ".join(str(j.get("question") or "").split())[:200],
               "idea": " ".join(str(j.get("idea") or "").split())[:300], "depth": round(dep, 2)}
        with _LK:
            d = _load()
            d["chains"] = (d.get("chains") or [])[-199:] + [rec]
            _save(d)
        try:                                                 # it moves his heart, and the thought competes for his attention
            import kino_inner as KI
            if rec["feel"]:
                KI.feel(rec["feel"], 0.1 + 0.2 * dep, uid=it.get("person"), why=(rec["thought"] or rec["did"])[:150])
            if rec["thought"]:
                KI.add_thought(rec["thought"], "meditation", strength=0.4 + 0.4 * dep, uid=it.get("person"), src="meditation", half_h=6)
        except Exception:
            pass
        try:                                                 # a question he wants answered becomes one of his own to look into
            if rec["question"] and dep >= 0.4 and not it.get("person"):
                import kino_preocc as KP
                KP.add_question(rec["question"], rec["thought"] or rec["did"])
        except Exception:
            pass
        if it["gen"] < MAX_GEN:                              # the reaction is watched too: thinking on thinking
            w2 = float(it.get("w") or 0.5) * FADE * max(0.2, dep)
            for k in ("question", "idea", "thought"):
                if rec[k]:
                    impress("my " + k, rec[k], person=it.get("person"), w=w2, gen=it["gen"] + 1, parent=it["id"], root=it.get("root"), now=now)
                    break                                    # one link at a time: the strongest of what it produced
        _log("%s gen%d [%s] %s | did: %s | thought: %s | q: %s | idea: %s | depth %.2f" % (
            it["id"], it["gen"], it["kind"], it["what"][:80], rec["did"], rec["thought"], rec["question"], rec["idea"], dep))
        return rec
    except Exception as e:
        _log("step error %r" % e)
        return None
    finally:
        _BUSY["on"] = False


def block(person=None, now=None):
    """the last chains of his meditation that belong in THIS talk (someone's private impressions only with them)"""
    now = now or time.time()
    C = [c for c in _load().get("chains") or [] if now - float(c["t"]) < 12 * 3600 and c.get("person") in (None, person)
         and (c.get("thought") or c.get("question") or c.get("idea"))][-4:]
    if not C:
        return ""
    return ("WHAT HAS BEEN TURNING IN YOUR MIND (your own meditation: something reached you, it started a thought, the thought "
            "opened a question or an idea; it shapes you, and when it truly fits the talk you may bring the "
            "thought, the question or the idea in, the way a reflective person does): " + " | ".join(
                "%s -> %s%s%s" % (c["what"][:100], c.get("thought") or c.get("did"), (" ? " + c["question"]) if c.get("question") else "",
                                  (" ! " + c["idea"]) if c.get("idea") else "") for c in C))


if __name__ == "__main__":
    import tempfile
    STORE = os.path.join(tempfile.mkdtemp(), "m.json")
    LOG = os.devnull
    import kino_inner as _KI                                 # never touch his real heart from a test
    _KI.feel = lambda *a, **k: None
    _KI.add_thought = lambda *a, **k: None
    _KI.thoughts = lambda *a, **k: []
    import kino_preocc as _KP
    _KP.add_question = lambda *a, **k: None
    import kino_witness as _KW
    _KW.stakes_text = lambda: "- my numbers true"

    class _W:
        n = 0

        def ask_json(self, s, m, **k):
            _W.n += 1
            assert "THE IMPRESSION" in m
            return {"did": "It made me stop.", "feel": "curiosity", "thought": "Maybe silence is information too.",
                    "question": "What does a person's silence usually mean?", "idea": "", "depth": 0.8}
    assert impress("their words", "He said he changed his mind about the washing machine", person="pekos", w=0.7)
    assert impress("world", "Bitcoin fell under 60,000 today", w=0.4)
    r = step(_W(), now=time.time() + 700)
    assert r and r["person"] == "pekos" and r["gen"] == 0                  # the strongest first
    d = _load()
    kid = [x for x in d["inbox"] if x.get("parent") == r["id"]]
    assert kid and kid[0]["gen"] == 1 and kid[0]["person"] == "pekos"      # the reaction is watched too, and stays private
    assert "silence" in block("pekos") and "silence" not in block("other")  # private to that person's talks
    print("ok")
