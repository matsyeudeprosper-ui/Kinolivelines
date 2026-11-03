"""kino_asks.py (2026-11-03, owner list 7 item 3: "learning what you usually want in a situation"). People who know each other
answer the question before it is asked: "trade's open - you'll want my bet: two in three it comes back to the entry".

Here, per person: each question they ask is noted with its KIND (a few words, from a vocabulary that grows with them: "your
bet on the trade", "why that stop", "are you still on auto") and the SITUATION it came in (a trade open / no trade open).
Over time that is a table - in this situation, this person asks these things, this often. He reads the line for the
situation they are in now; whether to offer the answer first is his to feel. Any field: the kinds are their own words.
Kinds come from his intuition read after each message (kino_read 'his_question_kind'); seed() reads the past chat once.
"""
import io, json, os, re, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_asks.json")
_LOCK = threading.Lock()
MIN_N = 3


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


def _norm(k):
    return " ".join(str(k or "").lower().split())[:50]


def kinds(person):
    return sorted({x["k"] for x in (_load().get(person) or {}).get("asks") or []})


def note(person, kind, situation, t=None):
    k = _norm(kind)
    if len(k) < 3:
        return
    with _LOCK:
        d = _load()
        P = d.setdefault(person, {"asks": []})
        P["asks"] = (P["asks"] + [{"t": float(t or time.time()), "k": k, "s": situation}])[-600:]
        _save(d)


def table(person, situation, days=21, before=None):
    now = float(before or time.time())
    A = [x for x in (_load().get(person) or {}).get("asks") or [] if x["s"] == situation and now - 86400 * days <= x["t"] < now]
    C = {}
    for x in A:
        C[x["k"]] = C.get(x["k"], 0) + 1
    return len(A), sorted(C.items(), key=lambda kv: -kv[1])


def line(person, situation):
    n, C = table(person, situation)
    top = [(k, c) for k, c in C if c >= MIN_N and c >= 0.15 * n]
    if n < 6 or not top:
        return ""
    return ("What he usually asks when %s (from %d of his questions in this situation, last 3 weeks): %s."
            % (situation, n, "; ".join("\"%s\" %d times" % kc for kc in top[:4])))


SEED = """Below is part of a chat between a person (HIM) and Kino, with system lines (SYS) showing orders and trades. List EVERY
question HE asks (a real question to Kino, not rhetorical). For each: its KIND in 2-5 plain words, reusing a kind from the
KNOWN KINDS list whenever it is the same thing (so the same question always gets the same kind), and the SITUATION at that
moment: "a trade is open" if a position of his was open then (opened and not yet closed), else "no trade is open".
JSON only: {"asks": [{"at": "HH:MM as shown", "kind": "...", "situation": "a trade is open|no trade is open"}]}"""


def seed(W, person, msgs, log=None, chunk=70):
    """once: his past questions, read in chunks by a small model"""
    M = [m for m in msgs if m.get("role") in ("user", "ai", "sys") and str(m.get("text") or "").strip()]
    out = []
    for i in range(0, len(M), chunk):
        part = M[i:i + chunk]
        if not any(m["role"] == "user" and "?" in str(m["text"]) for m in part):
            continue
        tx = "\n".join("%s %s: %s" % (time.strftime("%d/%m %H:%M", time.gmtime(float(m.get("t") or 0))),
                                      {"user": "HIM", "ai": "KINO", "sys": "SYS"}[m["role"]], " ".join(str(m["text"]).split())[:260]) for m in part)
        j = W.ask_json(SEED, "KNOWN KINDS: %s\n\nCHAT:\n%s\n\nJSON only." % (", ".join(kinds(person)) or "(none yet)", tx),
                       models=("haiku", "sonnet"), timeout=90, log=log, warm=False)
        for a in (j or {}).get("asks") or [] if isinstance(j, dict) else []:
            hh = str(a.get("at") or "")
            m = next((x for x in part if x["role"] == "user" and time.strftime("%d/%m %H:%M", time.gmtime(float(x.get("t") or 0))).endswith(hh[-5:])), None)
            s = "a trade is open" if "open" in str(a.get("situation") or "") and "no trade" not in str(a.get("situation") or "") else "no trade is open"
            if m is not None:
                note(person, a.get("kind"), s, m.get("t"))
                out.append((m.get("t"), _norm(a.get("kind")), s))
    return out
