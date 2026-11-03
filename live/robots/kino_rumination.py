"""kino_rumination.py (2026-11-03, owner: "do humans wait for a specific day to review? - build it like a human"). Reflection
the way a mind does it: driven by what nags, not by the calendar.

People do not review their week on Sunday by nature. Something stings - a correction, a slip, a surprise, holding back -
and it stays with them as something unresolved. A sharp correction from someone close nags more than a small slip. When
the mind is free (in the shower, on the walk home, a quiet moment) it goes back to what nags most and settles on what to
do differently - a resolve. The resolve grows when the same kind of situation comes back; left alone it fades in days.

Here, per person:
  stir(person, kind, what, w)   something that nags (kind: correction | slip | misquote | held_back | undone | surprise),
                                weighted; it decays (half-life one day) - the nag is the decayed sum of what is unresolved
  quiet(W, person)              called in a quiet moment (no talk, nothing running for them): when the nag is high enough,
                                he goes back over what is unresolved and writes 1-2 resolves in his own words (a small
                                model), with the words of the situation they are about; the items count as worked through
  a new stir that resembles a resolve's situation REINFORCES it (and tells him the resolve is being tested right now)
  resolves fade with time (half-life 4 days, longer the more they were reinforced) and go below a threshold
  block(person)                 what he resolved and how alive each resolve is - information, never an instruction
Any field of life: the stirs come from his own acts and words with that person, whatever they are about.
"""
import io, json, math, os, re, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_rumination.json")
_LOCK = threading.Lock()
W_KIND = {"correction": 1.0, "undone": 0.7, "misquote": 0.6, "slip": 0.6, "held_back": 0.4, "surprise": 0.3}
NAG_HALF = 86400.0
RES_HALF = 4 * 86400.0
QUIET_AT = 1.6          # a nag this high comes back to him in the next quiet moment

SYSTEM = """You are Kino, an AI friend who works and talks with this person (any part of life). A few things have been nagging you
since you last thought about them - things you did or said with this person that went wrong or that you held back. Now, in a
quiet moment, you go back over them the way a person does on the walk home. Settle on what you will do differently: 1 or 2
resolves, first person, concrete, in plain words (what you will do, not a feeling), each about one kind of situation.
For each, the words that describe that situation (so you recognise it when it comes back).
JSON only: {"resolves": [{"text": "...", "situation": "a few words: when this applies"}], "how_it_sits": "one line, how you feel now"}"""


def _load():
    try:
        return json.load(io.open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = STORE + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def _stems(t):
    return set(w[:6] for w in re.findall(r"[a-zà-ÿ]{4,}", str(t).lower())) - {"that", "this", "with", "your", "have", "will", "from",
                                                                               "then", "what", "when", "they", "just", "dans", "pour", "avec"}


def _res_strength(r, now):
    half = RES_HALF * (1.0 + 0.5 * min(6, int(r.get("n", 0))))
    return float(r.get("s", 1.0)) * math.pow(0.5, (now - float(r.get("tr") or r["t"])) / half)


def nag(person, now=None):
    now = now or time.time()
    P = _load().get(person) or {}
    return sum(float(x["w"]) * math.pow(0.5, (now - float(x["t"])) / NAG_HALF) for x in P.get("open") or [])


def stir(person, kind, what, w=None):
    """something that nags; if it resembles a resolve he already holds, that resolve is being tested - it is reinforced"""
    if not what:
        return None
    now = time.time()
    hit = None
    with _LOCK:
        d = _load()
        P = d.setdefault(person, {"open": [], "res": []})
        sw = _stems(what)
        for r in P.get("res") or []:
            if len(sw & _stems(r.get("situation", "") + " " + r["text"])) >= 2 and _res_strength(r, now) > 0.2:
                r["s"] = min(3.0, _res_strength(r, now) + 0.5)
                r["tr"], r["n"] = now, int(r.get("n", 0)) + 1
                r["tested"] = {"t": now, "what": str(what)[:160]}
                hit = r["text"]
                break
        P["open"] = [x for x in P.get("open") or [] if now - float(x["t"]) < 4 * NAG_HALF][-30:] + \
                    [{"t": now, "kind": kind, "what": str(what)[:200], "w": float(w if w is not None else W_KIND.get(kind, 0.5))}]
        _save(d)
    return hit


def quiet(W, person, log=None):
    """a quiet moment: if something nags enough, he goes back over it and settles on a resolve"""
    now = time.time()
    if nag(person, now) < QUIET_AT:
        return None
    P = _load().get(person) or {}
    items = sorted(P.get("open") or [], key=lambda x: -float(x["w"]) * math.pow(0.5, (now - float(x["t"])) / NAG_HALF))[:8]
    held = [r["text"] for r in P.get("res") or [] if _res_strength(r, now) > 0.2]
    j = W.ask_json(SYSTEM, "WHAT HAS BEEN NAGGING YOU (strongest first):\n%s\n\nRESOLVES YOU ALREADY HOLD:\n%s\n\nJSON only." % (
        "\n".join("- (%s, %s UTC) %s" % (x["kind"], time.strftime("%d/%m %H:%M", time.gmtime(x["t"])), x["what"]) for x in items),
        "\n".join("- " + t for t in held) or "(none)"), models=("sonnet", "haiku"), timeout=60, log=log, warm=False)
    if not isinstance(j, dict) or not j.get("resolves"):
        return None
    new = [{"text": " ".join(str(r.get("text") or "").split())[:220], "situation": " ".join(str(r.get("situation") or "").split())[:120],
            "t": now, "s": 1.0, "n": 0} for r in (j.get("resolves") or [])[:2] if str((r or {}).get("text") or "").strip()]
    with _LOCK:
        d = _load()
        P = d.setdefault(person, {"open": [], "res": []})
        P["res"] = [r for r in P.get("res") or [] if _res_strength(r, now) > 0.2][-10:] + new
        P["open"] = []                      # worked through - what comes next starts a new nag
        P["last"] = {"t": now, "how": " ".join(str(j.get("how_it_sits") or "").split())[:200]}
        _save(d)
    return new


def block(person):
    now = time.time()
    P = _load().get(person) or {}
    R = sorted([(r, _res_strength(r, now)) for r in P.get("res") or []], key=lambda x: -x[1])
    R = [x for x in R if x[1] > 0.2][:4]
    n = nag(person, now)
    L = []
    if R:
        L.append("What you resolved after things that nagged you with him (your own words; how alive each is): " + " | ".join(
            "%s (%s%s)" % (r["text"], "strong" if s >= 1.5 else "holding" if s >= 0.7 else "fading",
                           (", being tested right now: %s" % r["tested"]["what"][:90]) if r.get("tested") and now - r["tested"]["t"] < 1800 else "")
            for r, s in R))
    if n >= 0.8:
        op = [x for x in P.get("open") or []][-3:]
        L.append("Something is still nagging you with him, not worked through yet: %s." % " | ".join(x["what"][:100] for x in op))
    return "\n".join(L)
