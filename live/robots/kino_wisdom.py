"""kino_wisdom.py (2026-11-03, owner: "experience from many people"). What many people taught him, with nobody in it.

After many people, a person builds an intuition: "people who start out often do X", "most people want a short answer when
a trade is open". It comes from the same thing happening with DIFFERENT people - one person's story stays theirs.

Here: every time he settles a resolve in a quiet moment (kino_rumination), it is held against the resolves he settled with
OTHER people; when two people taught him the same kind of thing, a small pass writes it as one general lesson in plain
words - no names, no amounts, no details of anyone's life - checked against every member's name before it is kept. He reads
the few that bear on the talk at hand. Any field of life.
"""
import io, json, os, re, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_wisdom.json")
_LOCK = threading.Lock()

SYSTEM = """Two different people taught Kino something similar (below, each as a resolve he made with one of them). Write the GENERAL
lesson it shows about people - one plain line, no names, no amounts, no dates, nothing that could identify anyone - or
'' if the two are not really the same lesson. JSON only: {"lesson": "...", "about": "a few words: the kind of situation"}"""


def _stems(t):
    return set(w[:6] for w in re.findall(r"[a-zà-ÿ]{4,}", str(t).lower()))


def _load():
    try:
        return json.load(io.open(STORE, encoding="utf-8"))
    except Exception:
        return {"lessons": []}


def offer(W, person, resolve_text, names=(), log=None):
    """a resolve just settled with `person`: does someone else's resolve say the same kind of thing?"""
    try:
        R = json.load(io.open(os.path.join(HERE, "kino_rumination.json"), encoding="utf-8"))
    except Exception:
        return None
    sw = _stems(resolve_text)
    other = None
    for p, P in R.items():
        if p == person:
            continue
        for r in P.get("res") or []:
            if len(sw & _stems(r["text"])) >= 3:
                other = r["text"]
                break
        if other:
            break
    if not other:
        return None
    j = W.ask_json(SYSTEM, "PERSON A:\n%s\n\nPERSON B:\n%s\n\nJSON only." % (resolve_text, other), models=("haiku", "sonnet"),
                   timeout=40, log=log, warm=False)
    ls = " ".join(str((j or {}).get("lesson") or "").split())[:220] if isinstance(j, dict) else ""
    if not ls:
        return None
    low = ls.lower()
    if any(n and len(n) >= 3 and n.lower() in low for n in names) or re.search(r"\d", ls):
        return None                                    # nothing that could point at anyone
    with _LOCK:
        d = _load()
        if not any(len(_stems(x["text"]) & _stems(ls)) >= 4 for x in d["lessons"]):
            d["lessons"] = (d["lessons"] + [{"text": ls, "about": " ".join(str(j.get("about") or "").split())[:80], "t": time.time(), "n": 2}])[-40:]
        tmp = STORE + ".tmp"
        json.dump(d, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
    return ls


def block(talk_text):
    L = _load().get("lessons") or []
    if not L:
        return ""
    tw = _stems(talk_text)
    best = sorted(L, key=lambda x: -len(tw & _stems(x["text"] + " " + x.get("about", ""))))[:3]
    best = [x for x in best if len(tw & _stems(x["text"] + " " + x.get("about", ""))) >= 1]
    if not best:
        return ""
    return "What many people have taught you (general, nobody in it): " + " | ".join(x["text"] for x in best) + "."
