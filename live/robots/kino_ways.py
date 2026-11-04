"""kino_ways.py (2026-11-03, owner: "a genuine human - not if-x-do-y rules. Kino will deal with many fields in life, different
businesses, different situations"). What a person has told Kino about how THEY do things and want things done.

A friend remembers "you take your coffee black", "in my shop we never discount on Saturdays", "my stop goes on the dot" -
and he remembers the LATEST version: when you change your mind he does not keep quoting the old one. That day the owner
changed his trading rule four times in six hours; Kino kept acting on the first version, because he rebuilt the method from
raw chat lines each turn.

Here: when his intuition senses that a message taught him something (kino_read, "gave_kino"), a small pass merges it into
ONE notebook per person - a short topic and the person's own words, with when they said it. A newer word on the same
topic replaces the older one (the older is kept as history). Any field of life: a method, a preference, a boundary, how
they like to be told things. The one mind sees the notebook on every turn, and which entries changed in the last hour -
nothing tells him what to do with it; like anyone who has just been corrected, he can say it back in his own words.
"""
import io, json, os, re, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_ways.json")
_LOCK = threading.Lock()
MAX = 40

SYSTEM = """You keep Kino's notebook about ONE person: what this person has told him about how THEY do things and how they
want things done - their method for something, a preference, a boundary, a correction of how Kino works with them, how
they like to be addressed. Any field of life (trading, their shop, their family, food, work...).
NOT in the notebook: news of the day, feelings, prices, one-off events, Kino's own ideas, anything the person did not say.
You get the current notebook and the last messages. Decide what the LAST messages change:
- a new entry: a short topic (2-5 words, the person's own field, e.g. "stop placement", "sell entry", "how to address him")
  and what they said, in THEIR words, short (at most 30 words), complete enough to act on without the chat;
- an entry replaced: same topic, their newest version (it fully replaces the old one - merge only if they ADDED to it);
- an entry dropped: they said it no longer holds.
If nothing in the last messages is about how they do or want things, return empty lists.
JSON only: {"set": [{"topic": "...", "said": "...", "topic_was": "existing topic it replaces, or null"}], "drop": ["topic"]}"""


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


def entries(person):
    return list((_load().get(person) or {}).get("items") or [])


def _norm(t):
    return re.sub(r"\s+", " ", str(t or "").strip().lower())[:60]


def learn(W, person, msgs, hint="", log=None):
    """merge what the last messages taught about how this person does/wants things; returns the changed topics"""
    have = entries(person)
    book = "\n".join("- %s: %s (said %s UTC)" % (x["topic"], x["said"], time.strftime("%d/%m %H:%M", time.gmtime(x["t"]))) for x in have) or "(empty)"
    tail = []
    for m in (msgs or [])[-10:]:
        r = m.get("role")
        if r in ("user", "ai") and str(m.get("text") or "").strip():
            tail.append("%s %s: %s" % (time.strftime("%H:%M", time.gmtime(float(m.get("t") or 0))), "THEM" if r == "user" else "KINO",
                                       " ".join(str(m["text"]).split())[:500]))
    if not tail:
        return []
    j = W.ask_json(SYSTEM, "CURRENT NOTEBOOK:\n%s\n\nWHAT HIS INTUITION SENSED HE JUST TAUGHT: %s\n\nLAST MESSAGES (oldest first):\n%s\n\nJSON only."
                   % (book, hint or "-", "\n".join(tail)), models=("sonnet", "haiku"), timeout=60, log=log, warm=False)
    if not isinstance(j, dict):
        return []
    changed = []
    # stamped with WHEN they said it (the last of their messages read), not when the notebook was written
    now = max([float(m.get("t") or 0) for m in (msgs or [])[-10:] if m.get("role") == "user"] or [time.time()])

    def f(d):
        P = d.setdefault(person, {"items": []})
        items = P["items"]
        idx = {_norm(x["topic"]): x for x in items}
        for s in (j.get("set") or [])[:6]:
            tp = " ".join(str((s or {}).get("topic") or "").split())[:60]
            sd = " ".join(str((s or {}).get("said") or "").split())[:300]
            if not tp or not sd:
                continue
            old = idx.get(_norm(s.get("topic_was"))) or idx.get(_norm(tp))
            if old is not None:
                if _norm(old["said"]) == _norm(sd):
                    old["seen"] = now                  # said again: the memory is fresh again
                    continue
                old.setdefault("prev", []).append({"said": old["said"], "t": old["t"]})
                old["prev"] = old["prev"][-5:]
                old.update({"topic": tp, "said": sd, "t": now})
            else:
                x = {"topic": tp, "said": sd, "t": now}
                items.append(x)
                idx[_norm(tp)] = x
            changed.append(tp)
        for tp in (j.get("drop") or [])[:6]:
            x = idx.get(_norm(tp))
            if x is not None:
                items.remove(x)
                changed.append("-" + x["topic"])
        P["items"] = items[-MAX:]
    with _LOCK:
        d = _load()
        f(d)
        _save(d)
    return changed


def sureness(x, now=None):
    """2026-11-03 (human3 3): memory fades unless the thing is heard again - 1.0 fresh, half after 3 weeks"""
    now = now or time.time()
    return 0.5 ** ((now - float(x.get("seen") or x["t"])) / (21 * 86400.0))


def block(person, lang="fr"):
    """for the one mind: the notebook, newest first, with what changed in the last hour"""
    items = sorted(entries(person), key=lambda x: -x["t"])
    if not items:
        return ""
    now = time.time()
    en = lang == "en"
    L = []
    for x in items[:20]:
        new = now - x["t"] < 3600
        sure = sureness(x, now)
        hazy = "" if sure >= 0.6 else (", long ago and not heard since - you hold it less surely" if en else
                                      ", il y a longtemps et pas réentendu depuis - tu en es moins sûr")
        L.append("- %s: \"%s\"%s (%s %s UTC%s%s)" % (x["topic"], x["said"], (" - why: " + x["why"]) if x.get("why") else "", "said" if en else "dit le",
                                                  time.strftime("%d/%m %H:%M", time.gmtime(x["t"])),
                                                  (", CHANGED %d min ago - before it was: \"%s\"" % ((now - x["t"]) / 60, x["prev"][-1]["said"][:120])
                                                   if en else ", CHANGÉ il y a %d min - avant : \"%s\"" % ((now - x["t"]) / 60, x["prev"][-1]["said"][:120]))
                                                  if new and x.get("prev") else (" - NEW" if en else " - NOUVEAU") if new else "", hazy))
    head = ("WHAT HE TOLD YOU ABOUT HOW HE DOES AND WANTS THINGS (his notebook - his newest word on each point replaces the older one; "
            "act on THESE versions):" if en else
            "CE QU'IL T'A DIT DE SA FAÇON DE FAIRE ET DE CE QU'IL VEUT (son carnet - son dernier mot sur un point remplace l'ancien ; "
            "c'est CETTE version qui compte) :")
    return head + "\n" + "\n".join(L)


if __name__ == "__main__":
    print(block(sys.argv[1] if len(sys.argv) > 1 else "kino"))
