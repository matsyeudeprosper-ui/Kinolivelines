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
    mid = _mut(f)
    if mid:
        threading.Thread(target=_name_it, args=(mid, what, lang), daemon=True).start()
    return mid


def wake(mid):
    """2026-11-15 (watch: 'confirmed times in about 10 minutes' - joining the promise pushed the train job to +15 min): a
    promise about a job brings it forward, never back"""
    def f(d):
        for m in d["missions"]:
            if m["id"] == mid and m["status"] in OPEN and float(m.get("next_t") or 0) > time.time():
                m["next_t"] = time.time()
    _mut(f)


def which_job(uid, cid, text):
    """2026-11-15 (owner's panel: the restaurant promise joined the Airbnb job, the Airbnb order paired with the restaurant
    jobs - word matching mixes things that share a town): which open job of this chat a promise or an order is really about
    -> its id, or None (a new thing). Decided the way a person files a note in the right folder."""
    J = [m for m in for_uid(uid) if m.get("cid") == cid and m["status"] in OPEN and not m.get("repeat_h")]
    if not J:
        return None
    try:
        import robot_warm as RW
        lines = "\n".join("%s: %s - %s" % (m["id"], m.get("title") or "", m["what"][:220]) for m in J)
        raw = RW.ask_text("Which of these open jobs is the new item about? The same subject or a continuation of it (details may differ: a restaurant list and booking that restaurant are one job) - but a different need is null even in the same town or day. "
                          "Reply ONLY JSON {\"id\": \"<job id>\" or null}.", "JOBS:\n%s\n\nNEW ITEM: %s" % (lines, str(text)[:400]),
                          model="sonnet", timeout=40)
        i = str(raw or "").find("{")
        j = json.JSONDecoder().raw_decode(raw[i:])[0] if i >= 0 else {}
        mid = j.get("id")
        return mid if any(m["id"] == mid for m in J) else None
    except Exception:
        return None


_RESTAGED = {}


def restage(mid, convo, lang="fr"):
    """2026-11-14 (owner: 'why is the card always saying options envoyées - à toi de choisir, never changing?'): after an
    exchange about the job, its card says where it really stands now - the way a person updates the to-do in their head"""
    if time.time() - _RESTAGED.get(mid, 0) < 60:
        return
    _RESTAGED[mid] = time.time()
    try:
        m = get(mid)
        if not m or m["status"] not in OPEN:
            return
        import robot_warm as RW
        raw = RW.ask_text("A job card in a chat app shows where a job stands. From the job and the latest messages, reply ONLY "
                          "JSON {\"stage\": \"2-6 words, where it stands NOW, from the client's side\"} in %s - e.g. waiting for "
                          "their choice, chosen - waiting for payment, paid - booking it, booked - confirmation sent." % (
                              "French" if lang != "en" else "English"),
                          "JOB: %s\nCURRENT STAGE: %s\nLATEST MESSAGES:\n%s" % (m["what"][:400], m.get("stage") or "-", str(convo)[-1500:]),
                          model="haiku", timeout=40)
        i = str(raw or "").find("{")
        j = json.JSONDecoder().raw_decode(raw[i:])[0] if i >= 0 else {}
        st = str(j.get("stage") or "").strip()[:60]
        if st and st != m.get("stage"):
            update(mid, stage=st)
    except Exception:
        pass


def _name_it(mid, what, lang):
    """2026-11-14 (owner: 'what's wrong with the Ta demande / En cours panel'): a new job shows what it is at once - a short
    title and first stage in the person's language - instead of 'Ta demande' until the desk first works on it"""
    try:
        m = get(mid)
        if not m or m.get("title"):
            return
        import robot_warm as RW
        raw = RW.ask_text("You name a task for its card in a chat app. Reply ONLY JSON {\"title\": \"3-7 words\", \"stage\": "
                          "\"2-5 words, what is happening now\"} in %s, friendly, no ids, no 'for <name>'." % (
                              "French" if lang != "en" else "English"), str(what)[:500], model="haiku", timeout=40)
        i = str(raw or "").find("{")
        j = json.JSONDecoder().raw_decode(raw[i:])[0] if i >= 0 else {}
        if j.get("title"):
            def f(d):
                for mm in d["missions"]:
                    if mm["id"] == mid and not mm.get("title"):
                        mm["title"] = str(j["title"])[:60]
                        if not mm.get("stage"):
                            mm["stage"] = str(j.get("stage") or "")[:60] or None
            _mut(f)
    except Exception:
        pass


def get(mid):
    return next((m for m in _load()["missions"] if m["id"] == mid), None)


def for_uid(uid):
    return [m for m in _load()["missions"] if m["uid"] == uid and (m["status"] in OPEN or time.time() - m["t"] < 14 * 86400)]


def due(now=None):
    now = now or time.time()
    return [m for m in _load()["missions"] if m["status"] in OPEN and float(m.get("next_t") or 0) <= now]


def update(mid, tell="", status=None, note="", next_h=None, title="", stage="", plan=None, step=None, cards=False):
    """his step on a mission -> a sentence for him. tell = words for the person (their chat + a push).
    title / stage (2026-11-12, owner: "the client has no estimate, it leaves him with questions"): the job card they see -
    a short name of the job and where it stands, in their language; next_t is the "next update around" time on it."""
    # plan / step (2026-11-12, owner: "a check list - what is already done and what is left"): the job's 3-6 steps in
    # their words, and how many are done
    if title or stage or plan or step is not None:
        def _ts(d):
            m = next((x for x in d["missions"] if x["id"] == mid), None)
            if m is not None:
                if title:
                    m["title"] = " ".join(str(title).split())[:60]
                if stage:
                    m["stage"] = " ".join(str(stage).split())[:110]
                if isinstance(plan, list) and plan:
                    m["plan"] = [" ".join(str(p).split())[:70] for p in plan if str(p).strip()][:6]
                if step is not None:
                    try:
                        m["step"] = max(0, min(int(step), len(m.get("plan") or [])))
                    except Exception:
                        pass
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
                if status in ("done", "stuck", "cancelled"):
                    m["closed_t"] = now
                    if status == "done" and m.get("plan"):
                        m["step"] = len(m["plan"])
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
            _cards = None
            if cards:                          # 15/11 (owner): what the desk found, shown as cards under its message
                try:
                    import kino_crawl as KCm
                    _cards = KCm.latest()
                except Exception:
                    _cards = None
            Q.append({"uid": out["uid"], "cid": out["cid"], "mid": mid, "text": str(tell)[:2000], "status": out["status"],
                      "ref": out.get("ref") or "", "t": time.time(), "replace": bool(out.get("_replace")),
                      "cards": (_cards or {}).get("items")[:6] if _cards else None, "cards_kind": (_cards or {}).get("kind"),
                      "cards_dates": (_cards or {}).get("dates")})
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
        try:                                   # 13/11 (watch): Pekos switched to French, the job kept writing English - the
            import robot_chat as RCl           # language is the one they write in NOW, not the one at the job's start
            _c = json.load(open(os.path.join(HERE, "chats", m["cid"] + ".json"), encoding="utf-8"))
            m = dict(m, lang=RCl.member_lang(_c, m.get("lang") or "fr"))
        except Exception:
            pass
        hist ="; ".join("[%s %s] %s" % (_ago(x["t"]), x["kind"], x["text"][:220]) for x in m["log"][-8:]) or "nothing done yet"
        _conv = ""
        try:                                   # 15/11 (watch): two sessions told Pekos opposite things 12 min apart ("I'll
            import kino_one as K1              # book Hippopotamus" / "confirm when you book") - each knew only its own job.
            _conv = K1.transcript((_c.get("msgs") or [])[-8:], n=8, lang=m.get("lang") or "fr")   # The conversation as it is
        except Exception:
            pass
        L.append("- %s for %s (%s%s, opened %s, status %s%s): %s\n  so far: %s%s" % (
            m["id"], m.get("name") or m["uid"], ("PAID %.0f EUR" % m["eur"]) if m.get("paid") else "free",
            (", repeats every %.0f h" % m["repeat_h"]) if m.get("repeat_h") else "", _ago(m["t"]), m["status"],
            ", writes in " + m.get("lang", "fr"), m["what"], hist,
            ("\n  THE CONVERSATION NOW (what you - chat or another job - already told them; stay consistent, never "
             "contradict it, never repeat it):\n  " + _conv.replace("\n", "\n  ")[-2500:]) if _conv else ""))
    return "\n".join(L)


def chat_line(uid):
    """for the chat prompt: what he is doing for this person"""
    M = for_uid(uid)
    if not M:
        return ""
    # 2026-11-12 (Pekos chat): "open" read as "my desk is opening the files now" four times while the job sat untouched
    # for 3.5 h. A mission nobody has worked on yet says so.
    # 2026-11-14 (watch: Matsy had accepted the Leboncoin gig, the chat side did not know and "corrected" a true message
    # three times in the night, offering Pekos to paste the ad himself): the helper tasks of each job, as they stand
    try:
        import kino_helpers as KHc
        _T = KHc._j().get("tasks") or []
    except Exception:
        _T = []

    def _hp(m):
        L = []
        for t in _T:
            if m["id"] in (t.get("mission"), t.get("for_mission")):
                who = t.get("helper") or "nobody yet"
                L.append("HELPER TASK %s %s (%s)%s" % (t["id"], t["status"], who, " - proof received" if t.get("proofs_in") else
                                                      (" - proof pending, it is being done: do not offer them to do it themselves"
                                                       if t["status"] == "accepted" else "")))
        return (" | " + "; ".join(L)) if L else ""

    # 2026-11-12: their job card shows the stage and "next update around HH:MM" - what he says matches it
    def _nx(m):
        if m["status"] not in OPEN:
            return _hp(m)
        mins = (float(m.get("next_t") or 0) - time.time()) / 60
        # 2026-11-12 (watch): "nothing is running" while a 'waiting' job sat on Pekos's card - open = still yours, still on their card
        return (" | STILL OPEN, its card shows in their chat: \"%s\", next update %s" % (m.get("stage") or "in progress",
                                                               "in about %d min" % mins if mins > 2 else "now")) + _hp(m)
    return "; ".join("%s \"%s\" - %s%s%s" % (m["id"], m["what"][:120], m["status"],
                                            (", last: " + m["log"][-1]["text"][:140]) if m["log"] else
                                            (" - JUST RECEIVED, starts within minutes (nothing found or sent yet - say what comes "
                                             "next and when, never that it is done)" if m["status"] in OPEN else ""),
                                            _nx(m)) for m in ([x for x in M if x["status"] in OPEN] + [x for x in M if x["status"] not in OPEN][-3:])[:8])
