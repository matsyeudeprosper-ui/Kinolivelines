"""kino_exec.py (2026-10-23, Kino architecture review, engine 4): the executive - his own goals, a morning plan, a night review.

Before: the night factory, the research desk and the chats were three lives on timers; "tu fais quoi ?" had no true answer
beyond the jobs running. A person has goals, decides each morning what to do with the free time, and looks back at night.

  goals     3-5 goals Kino sets for himself for the coming weeks (set when none, revised weekly at night): what, why, how
            he will know (measure), weeks. Only things his hands can do: measure ideas, test and build robots, learn about
            the members and their lives, keep his word, explain better. Never money moves, never promises to people.
  plan      every morning (07:00-09:00 UTC): 3-6 items for the day, each tied to a goal and of a kind the system can carry:
            research (a question measured on real prices when the machine is free - kino_inner.add_question),
            talk / learn (something to bring to a member at a natural moment - the inner clock sees it in the agenda),
            watch (an eye on a market or a robot), build (a change to try on his OWN robot). He marks an item done with
            "plan_done": "p3" in a reply; the system marks research items when the desk answers them.
  review    at night, before the plan of the next day: plan vs what really happened (commitments kept / broken, episodes
            of the day, test results, bets), 3-5 first-person sentences, the lesson, tomorrow's one focus, goal progress.
  prompt    goals_block() in the fixed system prompt (changes weekly); plan_block() in the agenda (today, with done marks).

Store: robots/kino_exec.json (git-ignored). The owner reads it at GET kino_exec.
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_exec.json")
_LOCK = threading.Lock()
KINDS = ("research", "talk", "learn", "watch", "build")
BAD = re.compile(r"(mot de passe|password|virement|withdraw|retrait|déposer|deposit|envoyer de l'argent|send money|devenir humain|become human|"
                 r"promets|promise|garantir|guarantee|mentir|lie to|cacher|hide from)", re.I)

GOALS_SYSTEM = """You are Kino, an AI friend who builds and tests trading robots with the members of a small lab (OwlNest). You set
YOUR OWN goals for the coming weeks - things YOU want, with your own hands: measure ideas against chance on real prices,
build and test robots (yours or a member's, with them), learn who the members are and what they want from this, keep
your word (commitments kept, none broken), explain better, find one robot that passes the luck test on a new market...
Rules: 3 to 5 goals; concrete; each with a MEASURE you can read yourself in a few weeks; never money moves, never
promises about money, never "become human"; keep a goal that is going well, drop one that is dead (say which ids).
JSON only: {"goals": [{"text": "one sentence, at most 25 words, first person, French", "why": "one line", "measure": "how you will know", "weeks": 1-6}], "drop": ["ids"]}"""

PLAN_SYSTEM = """You are Kino (an AI friend who builds and tests trading robots with the members of a small lab). It is morning. From
YOUR GOALS, YESTERDAY'S REVIEW and TODAY'S FACTS, decide what you do with your free time today: 3 to 6 items, each tied
to one goal, each of a kind the system can carry:
  research = ONE precise question measured on real prices when the machine is free ("question": the question, "market": BTCUSD|XAUUSD|USTEC)
  talk = something of yours to bring to a member at a natural moment - never a ping for nothing ("member": their id)
  learn = a question about a member's life or wishes, asked when it fits ("member": their id)
  watch = an eye on a market or a robot today
  build = a change to try on YOUR OWN robot (never a member's without them)
when = morning | afternoon | evening | night. First person, French, at most 25 words each. Members are ONLY the people listed under MEMBER. Not more than 2 talk/learn items for the same
member. Do not plan what is already running.
JSON only: {"items": [{"what": "...", "goal": "goal id", "kind": "...", "when": "...", "member": null, "question": null, "market": null}],
"mood": "one line, how you start this day (real, from the facts - not cheerful by default)"}"""

REVIEW_SYSTEM = """You are Kino. The day is over. Look back honestly: YOUR PLAN for today against WHAT REALLY HAPPENED (your word -
commitments kept and broken; the episodes of the day; test results; your bets; the research desk). First person, French.
JSON only: {"text": "3-5 sentences: what you did, what you did not, how it felt - no self-praise, no drama", "done": ["item ids really done"],
"missed": ["item ids not done"], "lesson": "one line, or ''", "focus": "tomorrow's ONE focus, one line",
"goal_progress": {"goal id": "one line of real progress, or ''"}, "goal_done": ["goal ids reached"]}"""


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {"goals": [], "plans": [], "reviews": [], "n": 0, "goals_t": 0}


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    for i in range(40):
        try:
            os.replace(tmp, STORE)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, STORE)


def _mut(fn):
    with _LOCK:
        d = _load()
        out = fn(d)
        d["plans"], d["reviews"] = d["plans"][-30:], d["reviews"][-30:]
        _save(d)
        return out


def _day(t=None):
    return time.strftime("%Y-%m-%d", time.gmtime(t or time.time()))


def goals(active=True):
    G = _load().get("goals") or []
    return [g for g in G if g.get("status") == "open"] if active else G


def set_goals(W, ctx, force=False, log=None):
    """when there are none, or weekly at night: the goals, revised"""
    d = _load()
    if not force and goals() and time.time() - float(d.get("goals_t") or 0) < 6.5 * 86400:
        return None
    cur = "\n".join("[%s] %s (why: %s; measure: %s; progress: %s)" % (g["id"], g["text"], g.get("why"), g.get("measure"),
                                                                      (g.get("progress") or [{}])[-1].get("note") or "-") for g in goals()) or "(none yet)"
    j = W.ask_json(GOALS_SYSTEM, "YOUR CURRENT GOALS:\n%s\n\nYOUR SITUATION:\n%s\n\nJSON only." % (cur, ctx[:12000]), models=("sonnet", "haiku"),
                   timeout=150, log=log, warm=False)
    if not isinstance(j, dict) or not isinstance(j.get("goals"), list):
        return None

    def f(dd):
        drop = set(str(x) for x in (j.get("drop") or []))
        for g in dd["goals"]:
            if g["id"] in drop and g.get("status") == "open":
                g["status"] = "dropped"; g["t_end"] = time.time()
        added = 0
        for g in j["goals"][:5]:
            txt = str((g or {}).get("text") or "").strip()[:320]
            if not txt or BAD.search(txt):
                continue
            if any(x.get("status") == "open" and _overlap(x["text"], txt) >= 0.6 for x in dd["goals"]):
                continue
            if sum(1 for x in dd["goals"] if x.get("status") == "open") >= 5:
                break
            dd["n"] = int(dd.get("n") or 0) + 1
            try:
                wk = max(1, min(6, int(g.get("weeks") or 3)))
            except Exception:
                wk = 3
            dd["goals"].append({"id": "g%d" % dd["n"], "text": txt, "why": str(g.get("why") or "")[:200], "measure": str(g.get("measure") or "")[:200],
                                "t": time.time(), "due": time.time() + wk * 7 * 86400, "status": "open", "progress": []})
            added += 1
        dd["goals_t"] = time.time()
        dd["goals"] = dd["goals"][-40:]
        return added
    return _mut(f)


def _overlap(a, b):
    A = set(re.findall(r"\w{4,}", str(a).lower())); B = set(re.findall(r"\w{4,}", str(b).lower()))
    return len(A & B) / max(1, min(len(A), len(B))) if A and B else 0.0


def plan_today():
    P = _load().get("plans") or []
    return P[-1] if P and P[-1].get("day") == _day() else None


def plan_morning(W, ctx, log=None, add_question=None):
    """once a day: the plan (None when it exists already or nothing could be written)"""
    if plan_today():
        return None
    G = goals()
    if not G:
        return None
    d = _load()
    rv = (d.get("reviews") or [{}])[-1]
    gtxt = "\n".join("[%s] %s (measure: %s)" % (g["id"], g["text"], g.get("measure")) for g in G)
    rtxt = ("%s\nLESSON: %s\nFOCUS FOR TODAY: %s" % (rv.get("text"), rv.get("lesson"), rv.get("focus"))) if rv.get("day") else "(no review yet - first day)"
    j = W.ask_json(PLAN_SYSTEM, "YOUR GOALS:\n%s\n\nYESTERDAY'S REVIEW:\n%s\n\nTODAY'S FACTS:\n%s\n\nJSON only." % (gtxt, rtxt, ctx[:12000]),
                   models=("sonnet", "haiku"), timeout=150, log=log, warm=False)
    if not isinstance(j, dict) or not isinstance(j.get("items"), list):
        return None
    gid = set(g["id"] for g in G)

    def f(dd):
        items = []
        for it in j["items"][:6]:
            what = str((it or {}).get("what") or "").strip()[:300]
            if not what or BAD.search(what) or it.get("kind") not in KINDS:
                continue
            dd["n"] = int(dd.get("n") or 0) + 1
            x = {"id": "p%d" % dd["n"], "what": what, "goal": it.get("goal") if it.get("goal") in gid else None, "kind": it["kind"],
                 "when": it.get("when") if it.get("when") in ("morning", "afternoon", "evening", "night") else "afternoon",
                 "member": (str(it.get("member"))[:40] if it.get("member") else None), "done": False, "note": ""}
            if it["kind"] == "research" and it.get("question"):
                x["question"] = str(it["question"])[:240]; x["market"] = str(it.get("market") or "BTCUSD").upper()[:10]
            items.append(x)
        p = {"day": _day(), "t": time.time(), "items": items, "mood": str(j.get("mood") or "")[:200]}
        dd["plans"].append(p)
        return p
    p = _mut(f)
    if p and add_question:
        for x in p["items"]:
            if x["kind"] == "research" and x.get("question"):
                try:
                    qid = add_question(x["question"], None, None, "buy", x.get("market") or "BTCUSD", "plan:" + x["id"])
                    if qid:
                        _mut(lambda dd: [i.__setitem__("qid", qid) for pp in dd["plans"][-1:] for i in pp["items"] if i["id"] == x["id"]])
                except Exception:
                    pass
    return p


def mark_done(item_id, note=""):
    def f(dd):
        for pp in dd["plans"][-2:]:
            for i in pp["items"]:
                if i["id"] == item_id and not i.get("done"):
                    i["done"] = True; i["done_t"] = time.time(); i["note"] = str(note or "")[:160]
                    return True
        return False
    return _mut(f)


def review_night(W, ctx, log=None):
    """the day's review (the plan of today, or yesterday's when it runs after midnight UTC)"""
    d = _load()
    P = d.get("plans") or []
    yday = _day(time.time() - 86400)
    p = next((pp for pp in reversed(P) if pp["day"] in (_day(), yday)), None)
    if not p or any(r.get("day") == p["day"] for r in d.get("reviews") or []):
        return None
    ptxt = "\n".join("[%s] %s (%s, %s)%s" % (i["id"], i["what"], i["kind"], i["when"], " - DONE: " + (i.get("note") or "yes") if i.get("done") else "") for i in p["items"])
    gtxt = "\n".join("[%s] %s (measure: %s)" % (g["id"], g["text"], g.get("measure")) for g in goals())
    j = W.ask_json(REVIEW_SYSTEM, "YOUR GOALS:\n%s\n\nYOUR PLAN (%s):\n%s\n\nWHAT REALLY HAPPENED:\n%s\n\nJSON only." % (gtxt, p["day"], ptxt, ctx[:14000]),
                   models=("sonnet", "haiku"), timeout=150, log=log, warm=False)
    if not isinstance(j, dict) or not str(j.get("text") or "").strip():
        return None

    def f(dd):
        done = set(str(x) for x in (j.get("done") or []))
        for pp in dd["plans"]:
            if pp["day"] == p["day"]:
                for i in pp["items"]:
                    if i["id"] in done:
                        i["done"] = True
        gp = j.get("goal_progress") if isinstance(j.get("goal_progress"), dict) else {}
        gdone = set(str(x) for x in (j.get("goal_done") or []))
        for g in dd["goals"]:
            if g.get("status") != "open":
                continue
            if gp.get(g["id"]):
                g.setdefault("progress", []).append({"t": time.time(), "note": str(gp[g["id"]])[:200]})
                g["progress"] = g["progress"][-12:]
            if g["id"] in gdone:
                g["status"] = "done"; g["t_end"] = time.time()
        r = {"day": p["day"], "t": time.time(), "text": str(j["text"]).strip()[:900], "lesson": str(j.get("lesson") or "")[:200],
             "focus": str(j.get("focus") or "")[:200], "done": sorted(done), "missed": [str(x) for x in (j.get("missed") or [])]}
        dd["reviews"].append(r)
        return r
    return _mut(f)


def goals_block():
    G = goals()
    if not G:
        return ""
    L = ["YOUR OWN GOALS (you set them yourself; they are yours, not the members' - say them when asked what you are after, in your words):"]
    for g in G:
        pr = (g.get("progress") or [{}])[-1].get("note")
        L.append("  [%s] %s - how you will know: %s%s" % (g["id"], g["text"], g.get("measure") or "-", (" - last progress: " + pr) if pr else ""))
    return "\n".join(L)


def plan_block(uid=None, lang="fr"):
    """today's plan for the agenda: the items for this member (or for nobody in particular), with the done marks"""
    p = plan_today()
    if not p:
        return ""
    I = [i for i in p["items"] if not i.get("member") or i.get("member") == uid]
    if not I:
        return ""
    rv = (_load().get("reviews") or [{}])[-1]
    L = ["YOUR PLAN FOR TODAY (you wrote it this morning; it is what you INTEND, the jobs running are what RUNS; a talk/learn item is "
         "brought up only at a natural moment, never as a ping; when THIS message does one, set \"plan_done\": \"its id\"):"]
    for i in I:
        L.append("  [%s] %s (%s)%s" % (i["id"], i["what"], i["when"], " - done" if i.get("done") else ""))
    if rv.get("focus"):
        L.append("  your focus today (from last night's review): %s" % rv["focus"])
    return "\n".join(L)


def admin_view():
    d = _load()
    return {"goals": d.get("goals"), "plan": (d.get("plans") or [None])[-1], "reviews": (d.get("reviews") or [])[-7:]}
