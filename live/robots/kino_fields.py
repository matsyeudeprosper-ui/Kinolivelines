"""kino_fields.py (2026-11-03, owner: "Kino will deal with many fields in life, different businesses, different situations").
Getting up to speed in a field that is new to him, the way a person does.

A person who lands in a new trade (a bakery, a garage, someone's family business) does not pretend: they ask, they note what
they learn, they notice what they still do not understand, and next time they come back knowing more. Here: when the talk
is about a field outside what he knows well (kino_read 'domain'), a small pass after the exchange notes, per FIELD (shared
across the people who taught him, without who said what): what he learned, in a line; what he still does not understand;
one good question to ask next. He reads his notes for the field being talked about - and what he does not know yet.
"""
import io, json, os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_fields.json")
_LOCK = threading.Lock()
HOME = ("trading", "robots", "kino", "news")       # what he already knows deeply - not "new fields"

SYSTEM = """You are Kino learning a field that is new to you, from a conversation. You get your notes so far on this field and the
last messages. Return what THIS exchange taught you about the field itself (how it works, its words, its habits, what
matters in it) - general knowledge, never private details about the person (no names, no money of theirs).
JSON only: {"field": "the field in 1-3 words (e.g. 'bakery', 'car repair', 'raising toddlers')",
 "learned": ["one line each, max 3, only what is new vs your notes"], "unclear": ["what you still do not understand, max 2"],
 "ask_next": "one good question to ask someone in this field next time, or ''"}"""


def _load():
    try:
        return json.load(io.open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def learn(W, domain, msgs, log=None):
    dom = " ".join(str(domain or "").lower().split())[:40]
    if not dom or dom in HOME:
        return None
    d = _load()
    F = d.get(dom) or {}
    notes = "\n".join("- " + x["text"] for x in (F.get("learned") or [])[-12:]) or "(nothing yet)"
    tail = "\n".join("%s: %s" % ("THEM" if m.get("role") == "user" else "YOU", " ".join(str(m.get("text") or "").split())[:400])
                     for m in (msgs or [])[-8:] if m.get("role") in ("user", "ai") and str(m.get("text") or "").strip())
    if not tail:
        return None
    j = W.ask_json(SYSTEM, "YOUR NOTES ON '%s':\n%s\n\nLAST MESSAGES:\n%s\n\nJSON only." % (dom, notes, tail),
                   models=("haiku", "sonnet"), timeout=60, log=log, warm=False)
    if not isinstance(j, dict):
        return None
    fld = " ".join(str(j.get("field") or dom).lower().split())[:40] or dom
    now = time.time()
    with _LOCK:
        d = _load()
        F = d.setdefault(fld, {"learned": [], "unclear": [], "ask": "", "t0": now})
        for x in (j.get("learned") or [])[:3]:
            x = " ".join(str(x).split())[:200]
            if x and not any(x[:40].lower() == y["text"][:40].lower() for y in F["learned"]):
                F["learned"].append({"t": now, "text": x})
        F["learned"] = F["learned"][-40:]
        F["unclear"] = [" ".join(str(x).split())[:160] for x in (j.get("unclear") or [])[:2] if str(x).strip()] or F.get("unclear") or []
        F["ask"] = " ".join(str(j.get("ask_next") or "").split())[:200] or F.get("ask") or ""
        F["t"] = now
        tmp = STORE + ".tmp"
        json.dump(d, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
    return fld


def block(domain):
    dom = " ".join(str(domain or "").lower().split())[:40]
    if not dom or dom in HOME:
        return ""
    d = _load()
    F = d.get(dom)
    if not F:
        return ("This talk is about %s - a field you know little about. Like anyone new to it: say what you do not know, ask, and remember." % dom)
    L = ["What you have learned so far about %s (your own notes, from people who taught you): %s." % (
        dom, " | ".join(x["text"] for x in F.get("learned", [])[-8:]))]
    if F.get("unclear"):
        L.append("Still unclear to you: " + " | ".join(F["unclear"]) + ".")
    if F.get("ask"):
        L.append("A question you wanted to ask about it: " + F["ask"])
    return " ".join(L)
