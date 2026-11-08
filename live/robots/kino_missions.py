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


def create(uid, cid, what, name="", lang="fr", ref="", eur=0.0, paid=False, repeat_h=None):
    what = " ".join(str(what or "").split())[:600]
    if not what or not uid or not cid:
        return None

    def f(d):
        M = d["missions"]
        if ref and any(m.get("ref") == ref for m in M):
            return next(m["id"] for m in M if m.get("ref") == ref)
        if sum(1 for m in M if m["uid"] == uid and m["status"] in OPEN) >= MAX_OPEN_PER_PERSON:
            return None
        mid = "m" + os.urandom(4).hex()
        M.append({"id": mid, "uid": uid, "cid": cid, "name": str(name)[:60], "lang": lang, "what": what, "ref": ref,
                  "eur": float(eur or 0), "paid": bool(paid), "status": "open", "t": time.time(), "next_t": time.time(),
                  "repeat_h": float(repeat_h) if repeat_h else None, "log": []})
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


def update(mid, tell="", status=None, note="", next_h=None):
    """his step on a mission -> a sentence for him. tell = words for the person (their chat + a push)"""
    out = {}

    def f(d):
        m = next((x for x in d["missions"] if x["id"] == mid), None)
        if m is None:
            return
        now = time.time()
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
            Q.append({"uid": out["uid"], "cid": out["cid"], "mid": mid, "text": str(tell)[:2000], "status": out["status"],
                      "ref": out.get("ref") or "", "t": time.time()})
            json.dump(Q, open(OUTBOX, "w", encoding="utf-8"), ensure_ascii=False)
    return "mission %s: %s%s" % (mid, out["status"], " - %s has your message in their chat" % (out.get("name") or "they") if tell else "")


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
    return "; ".join("%s \"%s\" - %s%s" % (m["id"], m["what"][:120], m["status"],
                                          (", last: " + m["log"][-1]["text"][:140]) if m["log"] else "") for m in M[-6:])
