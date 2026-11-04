"""kino_cases.py (2026-11-04, owner list 9: "learning from examples, asking when a rule can mean two things, practising on his
mistakes"). People learn a rule from the cases it was applied to, not only from its wording: "first red candle" meant one thing
to Kino and another to the owner for hours, until the owner pointed at a candle - "that one".

  cases      per person, moments where the person CONFIRMED or CORRECTED how one of their rules applied, with what the
             situation was then (his word - the strongest), and his own worked cases from practice (his hindsight - weaker,
             and a word of the person always beats it). When the same kind of situation comes back, the closest cases are
             there for him to read - the way a person thinks "last time it looked like this, he said...".
  ambiguity  when a person gives or changes an instruction, a small pass asks whether it can honestly be read two ways that
             lead to different actions; if so the two readings wait for him to ask the person - once.
  practice   a miss from the session's hindsight review (kino_entries) becomes a worked case: the situation, what the rule
             called for, what he did.
Any field: a situation is whatever text describes the moment; for charts a signature (the colours after the top close) helps
find the closest case.
"""
import io, json, os, re, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_cases.json")
_LOCK = threading.Lock()


def _load():
    try:
        return json.load(io.open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LOCK:
        d = _load()
        out = fn(d)
        tmp = STORE + ".tmp"
        json.dump(d, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
        return out


def _stems(t):
    return set(w[:6] for w in re.findall(r"[a-zà-ÿ0-9]{4,}", str(t).lower()))


def add_case(person, rule, verdict, situation="", sig="", source="his word", t=None):
    rule = " ".join(str(rule or "").split())[:60]
    verdict = " ".join(str(verdict or "").split())[:260]
    if len(verdict) < 8:
        return

    def f(d):
        P = d.setdefault(person, {})
        C = P.setdefault("cases", [])
        if any(len(_stems(c["verdict"]) & _stems(verdict)) >= max(3, 0.7 * len(_stems(verdict))) for c in C[-30:]):
            return
        C.append({"t": float(t or time.time()), "rule": rule, "verdict": verdict, "situation": " ".join(str(situation).split())[:500],
                  "sig": sig, "source": source})
        P["cases"] = C[-80:]
    _mut(f)


def settled_line(person):
    x = (_load().get(person) or {}).get("settled")
    if not x or time.time() - x["t"] > 7 * 86400:
        return ""
    return ("How his older and newer instructions fit together, as you understand it (the newer one counts; if a moment falls exactly "
            "between the two, ask him): " + " | ".join(x["lines"]) + ".")


def cases_block(person, sig="", topic_text=""):
    C = (_load().get(person) or {}).get("cases") or []
    _st = settled_line(person)
    if not C:
        return _st
    tw = _stems(topic_text)

    def score(c):
        s = 0.0
        if sig and c.get("sig"):
            s += 3.0 if c["sig"] == sig else (1.5 if c["sig"].split(":")[0] == sig.split(":")[0] and c["sig"][:6] == sig[:6] else 0)
        s += 0.2 * len(tw & _stems(c["rule"] + " " + c["verdict"]))
        s += 1.0 if c["source"] == "his word" else 0
        return s + float(c["t"]) / 1e10
    best = sorted(C, key=score, reverse=True)[:4]
    return (_st + "\n" if _st else "") + ("Past cases of his rules (how they were applied in a real moment - %s; when one looks like now, it shows what he means):\n%s"
            % ("his word beats your own practice cases", "\n".join(
                "- [%s, %s UTC%s] %s%s" % (c["source"], time.strftime("%d/%m %H:%M", time.gmtime(c["t"])), (", " + c["sig"]) if c.get("sig") else "",
                                          c["verdict"], (" - situation: " + c["situation"][:200]) if c.get("situation") else "") for c in best)))


# ---- ambiguity ---------------------------------------------------------------------------------------------------------
AMBIG = """A person just gave or changed an instruction (below, with the rest of their notebook for context). Can THIS instruction
honestly be read in two different ways that would lead to DIFFERENT actions in a real situation (e.g. "the first red candle" =
"the first candle, if it is red" vs "the first candle that is red")? Only a real fork counts, not a nitpick; if their own words or
notebook already settle it, there is no fork.
JSON only: {"fork": true|false, "a": "reading A in a few words", "b": "reading B in a few words", "ask": "one short plain question to them"}"""


def ambiguity(W, person, topic, said, book="", log=None):
    j = W.ask_json(AMBIG, "THE INSTRUCTION (%s): %s\n\nTHEIR NOTEBOOK:\n%s\n\nJSON only." % (topic, said, book or "-"),
                   models=("haiku", "sonnet"), timeout=40, log=log, warm=False)
    if not (isinstance(j, dict) and j.get("fork") is True and str(j.get("ask") or "").strip()):
        return None
    q = {"t": time.time(), "topic": " ".join(str(topic).split())[:60], "a": str(j.get("a") or "")[:160], "b": str(j.get("b") or "")[:160],
         "ask": " ".join(str(j["ask"]).split())[:240], "asked": False}

    def f(d):
        P = d.setdefault(person, {})
        P["forks"] = [x for x in P.get("forks") or [] if x["topic"] != q["topic"]][-5:] + [q]
    _mut(f)
    return q


def forks_line(person, ai_texts):
    """an open fork until he has asked it (his own words carry the question) or it is a day old"""
    now = time.time()
    said = _stems(" ".join(ai_texts[-4:]))

    def f(d):
        for x in (d.get(person) or {}).get("forks") or []:
            if not x["asked"] and len(_stems(x["ask"]) & said) >= max(2, 0.4 * len(_stems(x["ask"]))):
                x["asked"] = True
    _mut(f)
    F = [x for x in (_load().get(person) or {}).get("forks") or [] if not x["asked"] and now - x["t"] < 3 * 86400]
    if not F:
        return ""
    return ("Something he told you can be read two ways, or two of his instructions do not fit together, and you have not asked him "
            "yet: %s. A person who will act on it asks once, plainly, at a calm moment."
            % " | ".join("%s - (a) %s / (b) %s - e.g. \"%s\"" % (x["topic"], x["a"], x["b"], x["ask"]) for x in F[-2:]))


def settle_fork(person, answer_text):
    """his answer to a fork question: the fork closes (the answer becomes a case through the read)"""
    aw = _stems(answer_text)

    def f(d):
        for x in (d.get(person) or {}).get("forks") or []:
            if x["asked"] and len(aw & _stems(x["topic"] + " " + x["a"] + " " + x["b"])) >= 2:
                x["settled"] = True
                x["asked"] = True
    _mut(f)


# ---- chart signature: the colours after the top close (for the closest case) -----------------------------------------
def chart_sig(top_colour, lower_colours):
    return "%s:%s" % ("bull" if str(top_colour).startswith("bull") else "bear", ",".join("R" if c.upper().startswith("R") else "G" for c in lower_colours[:3]))


def chart_situation(at_t=None, chart_path=None):
    """the top-chart period around a moment, as text + signature (None when there is no chart)"""
    try:
        import kino_entries as KE
        j = json.load(io.open(chart_path or os.path.join(HERE, "..", "owl_chart_btc.json"), encoding="utf-8"))
        tops = KE.real_tops(j)
        at_t = float(at_t or time.time())
        prev = [x for x in tops if float(x[0]) + 60 <= at_t]
        if not prev:
            return "", ""
        a = prev[-1]
        t1 = float(a[0]) + 60
        col = "bullish" if float(a[4]) >= float(a[1]) else "bearish"
        low = [x for x in (j.get("candles") or []) if x and len(x) > 4 and float(x[0]) >= t1 and float(x[0]) <= at_t + 60][:4]
        cl = ["RED" if float(x[4]) < float(x[1]) else "green" for x in low]
        txt = "top candle closed %s at %s UTC; lower candles after it: %s" % (col, time.strftime("%H:%M", time.gmtime(t1)),
                                                                              ", ".join("%s %s" % (time.strftime("%H:%M", time.gmtime(float(x[0]))), c) for x, c in zip(low, cl)) or "none yet")
        return txt, chart_sig(col, cl)
    except Exception:
        return "", ""


def situation_of(top, lower):
    """a finished period (kino_entries.periods) as text + signature"""
    col = top[2]
    cl = [c for _, c, _ in lower[:4]]
    txt = "top candle closed %s at %s UTC; lower candles after it: %s" % (col, time.strftime("%H:%M", time.gmtime(float(top[1]))),
                                                                          ", ".join("%s %s" % (time.strftime("%H:%M", time.gmtime(t)), c) for t, c, _ in lower[:4]) or "none")
    return txt, chart_sig(col, cl)



# ---- 2026-11-04 (owner list 13 item 1): one picture of their method - where two of their instructions disagree ----------
CONTRA = """Below is everything a person told Kino about how they want things done: an older rules list and a newer notebook (with
dates). Hold it as ONE picture. Where do two of their instructions really DISAGREE - they would lead to different actions in
the same situation (e.g. "flip on a close beyond the stop" vs "flip when a candle closes entirely beyond the stop")? Only real
clashes: name ONE concrete situation and the DIFFERENT action each instruction gives in it. Two instructions about different
things (when the stop moves vs which ladder step comes next; what a card shows vs where the stop goes) do NOT clash - they fit
together. Not wording either. If the newer one clearly replaces the older one on purpose, put it in "settled" instead. Usually
there are none or one.
JSON only: {"clashes": [{"topic": "a few words", "situation": "the one concrete situation", "a": "instruction A (with its date)
-> the action it gives", "b": "instruction B (with its date) -> the different action", "ask": "one short plain question to them"}],
"settled": ["older X is replaced by newer Y", ...]}"""


def contradictions(W, person, rules, book, log=None):
    """rules: [(t, text)]; book: [(t, topic, said)] -> the open clashes become forks he asks about, once"""
    txt = "OLDER RULES LIST:\n%s\n\nNOTEBOOK:\n%s" % (
        "\n".join("- (%s) %s" % (time.strftime("%d/%m %H:%M", time.gmtime(t)), x) for t, x in rules) or "-",
        "\n".join("- (%s) %s: %s" % (time.strftime("%d/%m %H:%M", time.gmtime(t)), tp, x) for t, tp, x in book) or "-")
    j = W.ask_json(CONTRA, txt + "\n\nJSON only.", models=("sonnet", "haiku"), timeout=90, log=log, warm=False)
    if not isinstance(j, dict):
        return []
    new = []
    for c in (j.get("clashes") or [])[:3]:
        if not str((c or {}).get("ask") or "").strip():
            continue
        q = {"t": time.time(), "topic": "rules disagree: " + " ".join(str(c.get("topic") or "").split())[:50],
             "a": str(c.get("a") or "")[:200], "b": str(c.get("b") or "")[:200], "ask": " ".join(str(c["ask"]).split())[:240], "asked": False}
        new.append(q)

    st = [" ".join(str(x).split())[:260] for x in (j.get("settled") or [])[:4] if str(x).strip()]

    def f(d):
        P = d.setdefault(person, {})
        if st:                                         # how the older and newer words fit, as he understands it
            P["settled"] = {"t": time.time(), "lines": st}
        F = P.get("forks") or []
        for q in new:
            if not any(len(_stems(x["a"] + x["b"]) & _stems(q["a"] + q["b"])) >= 4 for x in F if not x.get("settled")):
                F.append(q)
        P["forks"] = F[-8:]
    _mut(f)
    return new
