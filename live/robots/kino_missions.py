"""kino_missions.py (2026-11-08, owner: "Kino s'en occupe - users come to Kino because he is known for taking care of almost any
matter; he never limits himself, he always finds a way").

A MISSION = something Kino does FOR a person over time, in the world: contact businesses, chase an answer, post a letter, send
a helper, watch the job offers / flats / appointment slots every day... It is opened by a paid job (kino_pay ON_PAID / a
pay-after job) or by Kino himself from the chat (#mission), carried out in his work sessions (kino_work: due() calls him when
one is due, action "mission"), and every report he writes for the person lands in their chat with a push (OUTBOX, drained by
the app every 30 s).

Store robots/kino_missions.json {"missions": [...]}:
  {id, uid, cid, name, lang, what, ref, eur, paid, status open|working|waiting|watching|done|stuck|cancelled, t, next_t,
   repeat_h, log:[{t, kind note|tell|status, text}]}
"""
import json
import os
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_missions.json")
OUTBOX = os.path.join(HERE, "kino_missions_out.json")
_LK = threading.Lock()
OPEN = ("open", "working", "waiting", "watching")
MAX_OPEN_PER_PERSON = 6


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"missions": []}


def _save(d):
    tmp = STORE + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def _mut(fn):
    with _LK:
        d = _load()
        r = fn(d)
        _save(d)
        return r


def _words(t):
    import re
    return {w for w in re.findall(r"\w+", str(t or "").lower()) if len(w) > 3}


def _alike(a, b, th):
    A, B = _words(a), _words(b)
    return bool(A and B) and len(A & B) / float(min(len(A), len(B))) >= th


def create(uid, cid, what, name="", lang="fr", ref="", eur=0.0, paid=False, repeat_h=None, budget=0.0):
    """budget (12/11) = the part of a paid job the client prepaid for others (provider, helper, item) - Kino may spend up to it"""
    what = " ".join(str(what or "").split())[:600]
    if not what or not uid or not cid:
        return None

    def f(d):
        M = d["missions"]
        if ref and any(m.get("ref") == ref for m in M):
            return next(m["id"] for m in M if m.get("ref") == ref)
        # 2026-11-08 (owner's screenshot: two reports for one job): the price card and his "#travail" in the SAME reply opened
        # two missions. A mission for the same person opened in the last 3 minutes is the same work - merge into it.
        _same = next((m for m in reversed(M) if m["uid"] == uid and m["cid"] == cid and m["status"] in OPEN
                      and time.time() - m["t"] < 180 and not (ref and m.get("ref"))), None)
        # 2026-11-12 (Pekos chat): the same "find the two replies, word for word" was opened 4 min apart (outside the 3-min
        # merge), both waited 3.5 h for a work session and BOTH delivered. An open, unpaid mission in this chat asking the
        # same thing (most of its words) is that mission, whatever its age.
        if _same is None and not ref:
            _same = next((m for m in reversed(M) if m["uid"] == uid and m["cid"] == cid and m["status"] in OPEN
                          and not m.get("ref") and _alike(what, m["what"], 0.6)), None)
        if _same is not None:
            if ref:
                _same.update(ref=ref, eur=float(eur or 0), paid=bool(paid), budget_eur=float(budget or 0))
            if what not in _same["what"]:
                _same["what"] = (_same["what"] + " | " + what)[:900]
            return _same["id"]
        if sum(1 for m in M if m["uid"] == uid and m["status"] in OPEN) >= MAX_OPEN_PER_PERSON:
            return None
        mid = "m" + os.urandom(4).hex()
        M.append({"id": mid, "uid": uid, "cid": cid, "name": str(name)[:60], "lang": lang, "what": what, "ref": ref,
                  "eur": float(eur or 0), "paid": bool(paid), "status": "open", "t": time.time(), "next_t": time.time(),
                  "repeat_h": float(repeat_h) if repeat_h else None, "log": [], "budget_eur": float(budget or 0)})
        d["missions"] = M[-500:]
        return mid
    return _mut(f)


def get(mid):
    return next((m for m in _load()["missions"] if m["id"] == mid), None)


def for_uid(uid):
    return [m for m in _load()["missions"] if m["uid"] == uid and (m["status"] in OPEN or time.time() - m["t"] < 14 * 86400)]


def due(now=None):
    now = now or time.time()
    return [m for m in _load()["missions"] if m["status"] in OPEN and float(m.get("next_t") or 0) <= now]


def update(mid, tell="", status=None, note="", next_h=None, title="", stage=""):
    """his step on a mission -> a sentence for him. tell = words for the person (their chat + a push).
    title / stage (2026-11-12, owner: "the client has no estimate, it leaves him with questions"): the job card they see -
    a short name of the job and where it stands, in their language; next_t is the "next update around" time on it."""
    if title or stage:
        def _ts(d):
            m = next((x for x in d["missions"] if x["id"] == mid), None)
            if m is not None:
                if title:
                    m["title"] = " ".join(str(title).split())[:60]
                if stage:
                    m["stage"] = " ".join(str(stage).split())[:110]
        _mut(_ts)
    out = {}
    _dupmsg = ""
    if tell:
        _m0 = get(mid)
        if _m0 is not None:
            # 2026-11-12 (Pekos chat): two missions for one ask -> the same replies pasted twice, 4 min apart. A report that
            # repeats the one still showing in this chat (each mission's LAST report - a newer one within 15 min replaces
            # the older bubble) in the last 6 h does not go out again, and is not logged as told.
            _lasts = []
            for m in _load()["missions"]:
                if m["cid"] == _m0["cid"]:
                    T = [x for x in m["log"] if x["kind"] == "tell"]
                    if T:
                        _lasts.append(T[-1])
            _dup = next((x for x in _lasts if time.time() - x["t"] < 6 * 3600 and _alike(tell, x["text"], 0.7)), None)
            if _dup is not None:
                _dupmsg = " - NOT sent: this chat already has the same report (%s), no need to say it twice" % _ago(_dup["t"])
                note = ((note + " | ") if note else "") + "unsent repeat: " + str(tell)[:300]
                tell = ""

    def f(d):
        m = next((x for x in d["missions"] if x["id"] == mid), None)
        if m is None:
            return
        now = time.time()
        # 2026-11-08 (first real mission): three reports in one minute, the list twice - a new report within 15 min of the
        # last one REPLACES it in their chat (one message, one push)
        _lt = max([x["t"] for x in m["log"] if x["kind"] == "tell"] or [0])
        out["_replace"] = bool(tell) and now - _lt < 900
        if note:
            m["log"].append({"t": now, "kind": "note", "text": str(note)[:800]})
        if tell:
            m["log"].append({"t": now, "kind": "tell", "text": str(tell)[:2000]})
        if status and status in OPEN + ("done", "stuck", "cancelled"):
            if status != m["status"]:
                m["log"].append({"t": now, "kind": "status", "text": status})
            m["status"] = status
        if next_h is not None:
            try:
                m["next_t"] = now + max(0.25, min(24 * 30, float(next_h))) * 3600
            except Exception:
                pass
        elif m["status"] in OPEN:                  # no time given: a watcher keeps its rhythm, the rest comes back tomorrow
            m["next_t"] = now + (float(m["repeat_h"]) if m.get("repeat_h") else 24) * 3600
        m["log"] = m["log"][-60:]
        out.update(m)
    _mut(f)
    if not out:
        return "no mission %s" % mid
    if tell:
        with _LK:
            try:
                Q = json.load(open(OUTBOX, encoding="utf-8"))
            except Exception:
                Q = []
            Q = [q for q in Q if not (q.get("mid") == mid and out.get("_replace"))]      # not delivered yet: the newer one wins
            Q.append({"uid": out["uid"], "cid": out["cid"], "mid": mid, "text": str(tell)[:2000], "status": out["status"],
                      "ref": out.get("ref") or "", "t": time.time(), "replace": bool(out.get("_replace"))})
            json.dump(Q, open(OUTBOX, "w", encoding="utf-8"), ensure_ascii=False)
    return "mission %s: %s%s" % (mid, out["status"], (" - %s has your message in their chat" % (out.get("name") or "they")) if tell else _dupmsg)


def drain():
    """the app takes the reports to deliver"""
    with _LK:
        try:
            Q = json.load(open(OUTBOX, encoding="utf-8"))
        except Exception:
            return []
        try:
            os.remove(OUTBOX)
        except Exception:
            pass
        return Q


def _ago(t):
    h = (time.time() - float(t)) / 3600
    return "%d min ago" % (h * 60) if h < 1 else ("%.0f h ago" % h if h < 48 else "%.0f days ago" % (h / 24))


def block(limit=6):
    """for his work session: the missions due now, with their history"""
    D = sorted(due(), key=lambda m: (not m.get("paid"), m["next_t"]))[:limit]
    if not D:
        return ""
    L = []
    for m in D:
        hist = "; ".join("[%s %s] %s" % (_ago(x["t"]), x["kind"], x["text"][:220]) for x in m["log"][-8:]) or "nothing done yet"
        L.append("- %s for %s (%s%s, opened %s, status %s%s): %s\n  so far: %s" % (
            m["id"], m.get("name") or m["uid"], ("PAID %.0f EUR" % m["eur"]) if m.get("paid") else "free",
            (", repeats every %.0f h" % m["repeat_h"]) if m.get("repeat_h") else "", _ago(m["t"]), m["status"],
            ", writes in " + m.get("lang", "fr"), m["what"], hist))
    return "\n".join(L)


def chat_line(uid):
    """for the chat prompt: what he is doing for this person"""
    M = for_uid(uid)
    if not M:
        return ""
    # 2026-11-12 (Pekos chat): "open" read as "my desk is opening the files now" four times while the job sat untouched
    # for 3.5 h. A mission nobody has worked on yet says so.
    # 2026-11-12: their job card shows the stage and "next update around HH:MM" - what he says matches it
    def _nx(m):
        if m["status"] not in OPEN:
            return ""
        mins = (float(m.get("next_t") or 0) - time.time()) / 60
        return (" | their card says: \"%s\", next update %s" % (m.get("stage") or "in progress",
                                                               "in about %d min" % mins if mins > 2 else "now"))
    return "; ".join("%s \"%s\" - %s%s%s" % (m["id"], m["what"][:120], m["status"],
                                            (", last: " + m["log"][-1]["text"][:140]) if m["log"] else
                                            (" - JUST RECEIVED, starts within minutes (nothing found or sent yet - say what comes "
                                             "next and when, never that it is done)" if m["status"] in OPEN else ""),
                                            _nx(m)) for m in M[-6:])
