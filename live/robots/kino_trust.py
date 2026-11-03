"""kino_trust.py (2026-11-03, owner: "do each item properly - a proper engine"). How much latitude a person gives Kino, per kind
of thing he does on his own - learned, not set.

A person does not trust a colleague "at 0.6". They trust him to close a trade but not to open one; to pick the restaurant
but not the date; to answer clients but not to set prices. And that trust moves with what happened: each time he did
something on his own and they let it stand or said "good", it grows a little; each time they corrected it, undid it or
said "too early", it shrinks more; old events weigh less with time.

Here, per person and per KIND of act (the act's own name - "order:open", "order:close", "order:modify", "robot:switch",
"build", any tool he has), a Beta belief: approvals and corrections, each decaying with a 14-day half-life. An act he
just did waits 30 minutes for the person's reaction (kino_read 'about_kino_act'); the reaction is credited to the acts
of that window. Undoing what he did (the desk closing or modifying right after) counts as a correction. What comes out
is a reading he gets before acting - room he has been given for that kind of act, and how sure that reading is - never
an instruction.
"""
import io, json, math, os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_trust.json")
_LOCK = threading.Lock()
HALF = 14 * 86400.0
WINDOW = 1800.0


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


def act_kind(verb, text=""):
    """a stable name for what he did, from his own tool and its words - any tool, any field"""
    v = str(verb or "").lower().strip()
    t = str(text or "").lower()
    if v == "ordre":
        if any(w in t for w in ("ferme", "fermer", "close", "coupe")):
            return "order:close"
        if any(w in t for w in ("achat", "acheter", "buy", "vente", "vendre", "sell")):
            return "order:open"
        if any(w in t for w in ("sl=", "tp=", "stop", "objectif")):
            return "order:modify"
        return "order:other"
    return v or "act"


def did(person, kind, what=""):
    """he just did something on his own: it waits for the person's reaction"""
    with _LOCK:
        d = _load()
        P = d.setdefault(person, {"kinds": {}, "pending": []})
        P["pending"] = [x for x in P.get("pending") or [] if time.time() - x["t"] < WINDOW][-8:] + \
                       [{"t": time.time(), "kind": kind, "what": str(what)[:160]}]
        _save(d)


def _decay(k, now):
    dt = now - float(k.get("t") or now)
    f = math.pow(0.5, dt / HALF)
    k["a"], k["b"], k["t"] = float(k.get("a", 0)) * f, float(k.get("b", 0)) * f, now


def react(person, reaction, said=""):
    """the person's reaction ('approved' / 'corrected') to what he did in the last 30 minutes"""
    if reaction not in ("approved", "corrected"):
        return []
    now = time.time()
    with _LOCK:
        d = _load()
        P = d.get(person) or {}
        pend = [x for x in P.get("pending") or [] if now - x["t"] < WINDOW]
        if not pend:
            return []
        K = P.setdefault("kinds", {})
        hit = []
        for kd in sorted(set(x["kind"] for x in pend)):
            k = K.setdefault(kd, {"a": 0.0, "b": 0.0, "t": now, "log": []})
            _decay(k, now)
            if reaction == "approved":
                k["a"] += 1.0
            else:
                k["b"] += 1.5                       # a correction weighs more than a nod, like for anyone
            k["log"] = (k.get("log") or [])[-9:] + [{"t": now, "r": reaction, "said": str(said)[:120]}]
            hit.append(kd)
        P["pending"] = []                           # this reaction answered them
        d[person] = P
        _save(d)
    return hit


def undone(person, kinds, how=""):
    """the person redid what he had just done (closed or changed his order by hand within the window): a softer correction -
    someone redoing your work is a signal, not always a reproach (a hand close can also be a profit taken)"""
    now = time.time()
    with _LOCK:
        d = _load()
        P = d.get(person) or {}
        pend = [x for x in P.get("pending") or [] if now - x["t"] < WINDOW and x["kind"] in kinds]
        if not pend:
            return []
        K = P.setdefault("kinds", {})
        hit = []
        for kd in sorted(set(x["kind"] for x in pend)):
            k = K.setdefault(kd, {"a": 0.0, "b": 0.0, "t": now, "log": []})
            _decay(k, now)
            k["b"] += 0.75
            k["log"] = (k.get("log") or [])[-9:] + [{"t": now, "r": "undone", "said": str(how)[:120]}]
            hit.append(kd)
        P["pending"] = [x for x in P.get("pending") or [] if x not in pend]
        d[person] = P
        _save(d)
    return hit


def reading(person, kind):
    """(room 0-1, how sure 0-1, n) for that kind of act; room 0.5 with no history"""
    k = ((_load().get(person) or {}).get("kinds") or {}).get(kind)
    if not k:
        return 0.5, 0.0, 0
    k = dict(k)
    _decay(k, time.time())
    a, b = k["a"], k["b"]
    n = a + b
    return (a + 1.0) / (n + 2.0), n / (n + 4.0), int(round(n))


def block(person, lang="en"):
    K = (_load().get(person) or {}).get("kinds") or {}
    if not K:
        return ""
    rows = []
    for kd in sorted(K):
        room, sure, n = reading(person, kd)
        if n < 1:
            continue
        word = ("lots of room" if room >= 0.7 else "some room" if room >= 0.5 else "little room" if room >= 0.3 else "he wants to decide this himself")
        last = (K[kd].get("log") or [])[-1:]
        rows.append("%s: %s (%d reaction%s%s%s)" % (kd, word, n, "" if n == 1 else "s", ", an early read" if sure < 0.4 else "", ("; last: %s %s" % (last[0]["r"], ("\"%s\"" % last[0]["said"]) if last[0].get("said") else "")) if last else ""))
    if not rows:
        return ""
    return ("How much room he has given you to act on your own, by kind of act - earned from how he reacted to what you did "
            "(fades over weeks): " + " | ".join(rows))
