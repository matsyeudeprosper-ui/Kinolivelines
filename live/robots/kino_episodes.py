"""kino_episodes.py (2026-10-23, Kino architecture review, engine 2): episodic memory.

Before: 40 notes per member, the oldest dropped; "related" = raw keyword hits over 30 days of messages. A person keeps
EPISODES ("the day the gold robot passed its luck test", "when he told me about the parcel for his father") and finds them
by cue; with time the episodes become FACTS ("his father lives in Congo") and the trivia is forgotten.

  write_day    each night, per member with activity: the day's conversations -> 1-6 episodes (what happened, first
               person, the member's language; his feeling; the outcome; tags; importance 1-5; kind work|life|moment|lesson)
  recall       by cue, no model: the words of what they just said (and the thread) against the episodes' tags and text,
               weighted by importance, strengthened by every recall, weakened by age
  block        "EPISODES YOU REMEMBER WITH THEM" - 3-4 lines in the prompt when something matches
  consolidate  weekly: episodes older than a week -> durable facts (merged with the known ones); episodes that were never
               recalled and matter little are dropped after a month (forgetting), moments and lessons are kept
  facts        read into the member's memory block (robot_chat.memory_text - the cached half)

Store: robots/kino_episodes.json (git-ignored with the chats).
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_episodes.json")
_LOCK = threading.Lock()
_STOP = set(("avec dans pour cette celui celle ceux elle elles nous vous leur leurs mais donc alors comme très plus moins tout tous toute toutes "
             "être avoir fait faire dire être aussi encore déjà quand même chose choses autre autres juste bien entre sans sous vers chez "
             "that this with from have been were they them their what when your will would could should about there here just like "
             "into than then also some more most only very much many such over").split())
STRIP = re.compile(r"[a-zà-ÿ0-9]{4,}")

EP_SYSTEM = """You are Kino's memory. Kino is an AI friend who builds trading robots with members of a small lab. You read ONE DAY of
Kino's conversations with ONE member (Kino is "YOU", the member is "MEMBER") and write the EPISODES worth remembering, the way
a friend remembers a day: what happened between you, what they told you about their life, decisions taken, results, shared
moments, what you felt.
Rules: only what is in the text, never invented; "what" in the member's language, first person ("on a lancé...", "il m'a dit
que..."); 1 to 6 episodes, the important ones first; skip routine ("they said ok", greetings); a detail of their LIFE
(family, work, a trip, a worry, a joke that landed) is ALWAYS an episode with importance 4-5.
JSON only: {"episodes": [{"what": "1-2 sentences", "feel": "one word", "outcome": "what came out of it, or ''",
"tags": ["4-8 lowercase keywords: names, markets, robots, life words"], "importance": 1-5, "kind": "work|life|moment|lesson"}]}"""

CONSOL_SYSTEM = """You are Kino's memory. From these EPISODES with one member (older than a week) and the FACTS already known, write the
durable FACTS worth keeping for months: who they are, their life, what they want, what worked and failed with their robots,
your shared moments. Merge - never repeat a known fact; if one changed, write the new version. One sentence each, the
member's language.
JSON only: {"facts": [{"text": "...", "importance": 1-5, "from": ["episode ids"]}], "keep": ["ids of episodes still worth
keeping as episodes (moments, lessons, turning points) - the others live on as facts only"]}"""


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


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
        _save(d)
        return out


def _u(d, uid):
    return d.setdefault(uid, {"episodes": [], "facts": [], "n": 0, "last_t": 0, "last_consol": 0})


def _words(t):
    return set(w for w in STRIP.findall(str(t or "").lower()) if w not in _STOP)


def day_text(chats, since, until):
    """the member's conversations between two times, as text for the memory (YOU / MEMBER / results / charts)"""
    out, n_user = [], 0
    for c in chats or []:
        M = [m for m in c.get("msgs") or [] if since <= int(m.get("t") or 0) < until and m.get("role") in ("user", "ai", "result", "demo", "image", "sys")]
        if not any(m.get("role") == "user" for m in M):
            continue
        n_user += sum(1 for m in M if m.get("role") == "user")
        L = ["=== conversation '%s' (robot: %s, market %s)" % (str(c.get("thread") or c.get("title") or "")[:60], (c.get("robot") or {}).get("name"),
                                                            (c.get("robot") or {}).get("market") or c.get("market"))]
        for m in M[-60:]:
            r = m.get("role")
            hm = time.strftime("%H:%M", time.gmtime(int(m.get("t") or 0)))
            if r == "user":
                L.append("%s MEMBER: %s" % (hm, str(m.get("text") or "")[:400]))
            elif r == "ai" and m.get("text"):
                L.append("%s YOU: %s" % (hm, str(m.get("text") or "")[:500]))
            elif r == "result":
                L.append("%s TEST RESULT: net %s over %s trades" % (hm, (m.get("result") or {}).get("net"), (m.get("result") or {}).get("trades")))
            elif r == "demo":
                L.append("%s YOU SHOWED A CHART" % hm)
            elif r == "image":
                L.append("%s MEMBER SENT A SCREENSHOT" % hm)
            elif r == "sys" and m.get("text"):
                L.append("%s (system: %s)" % (hm, str(m.get("text"))[:160]))
        out.append("\n".join(L))
    return "\n\n".join(out), n_user


def write_day(uid, chats, since, until, W, log=None):
    """one window of conversations -> episodes (the ids added). Nothing said by the member in the window = nothing written."""
    txt, n_user = day_text(chats, since, until)
    if not txt or n_user < 1:
        _mut(lambda d: _u(d, uid).__setitem__("last_t", until))
        return []
    j = W.ask_json(EP_SYSTEM, "DAY %s\n\n%s\n\nJSON only." % (time.strftime("%Y-%m-%d", time.gmtime(since)), txt[:24000]),
                   models=("sonnet", "haiku"), timeout=150, log=log, warm=False)
    E = (j or {}).get("episodes") if isinstance(j, dict) else None
    if not isinstance(E, list):
        return []
    day = time.strftime("%Y-%m-%d", time.gmtime(since))

    def f(d):
        u = _u(d, uid)
        ids = []
        for e in E[:6]:
            if not isinstance(e, dict) or not str(e.get("what") or "").strip():
                continue
            what = str(e["what"]).strip()[:320]
            if any(x["day"] == day and _overlap(x["what"], what) >= 0.7 for x in u["episodes"]):
                continue
            try:
                imp = max(1, min(5, int(e.get("importance") or 3)))
            except Exception:
                imp = 3
            u["n"] += 1
            x = {"id": "e%d" % u["n"], "t": until, "day": day, "what": what, "feel": str(e.get("feel") or "")[:30],
                 "outcome": str(e.get("outcome") or "")[:200], "tags": [str(t).lower()[:30] for t in (e.get("tags") or []) if str(t).strip()][:8],
                 "imp": imp, "kind": e.get("kind") if e.get("kind") in ("work", "life", "moment", "lesson") else "work", "recalls": 0, "c": False}
            u["episodes"].append(x)
            ids.append(x["id"])
        u["last_t"] = until
        u["episodes"] = u["episodes"][-400:]
        return ids
    return _mut(f)


def _overlap(a, b):
    A, B = _words(a), _words(b)
    return len(A & B) / max(1, min(len(A), len(B))) if A and B else 0.0


def recall(uid, query, n=4, exclude_day=None):
    """episodes matching the cue, best first - and each one remembered gets a little stronger"""
    q = _words(query)
    if len(q) < 2:
        return []
    now = time.time()
    d = _load()
    u = d.get(uid) or {}
    hits = []
    for x in u.get("episodes") or []:
        if exclude_day and x.get("day") == exclude_day:
            continue
        T = set(x.get("tags") or []) | _words(x.get("what")) | _words(x.get("outcome"))
        ov = len(q & T)
        if ov < 2:
            continue
        age_d = (now - float(x.get("t") or now)) / 86400
        sc = ov * (0.6 + x.get("imp", 3) / 5.0) * (1 + 0.1 * min(10, x.get("recalls", 0))) * (0.7 if age_d > 60 else 1.0)
        hits.append((sc, x))
    hits.sort(key=lambda h: -h[0])
    out = [x for _, x in hits[:n]]
    if out:
        ids = set(x["id"] for x in out)

        def f(d2):
            for y in _u(d2, uid)["episodes"]:
                if y["id"] in ids:
                    y["recalls"] = y.get("recalls", 0) + 1
                    y["last_recall"] = now
        try:
            _mut(f)
        except Exception:
            pass
    return out


def block(uid, chat, lang="fr"):
    """the prompt block for this turn: what the last messages bring back"""
    M = [m for m in (chat or {}).get("msgs") or [] if m.get("role") in ("user", "ai") and m.get("text")]
    cue = " ".join([str(chat.get("thread") or "")] + [str(m["text"]) for m in M[-4:]])
    today = time.strftime("%Y-%m-%d", time.gmtime())
    E = recall(uid, cue, 4, exclude_day=today)             # today he is living it, not remembering it
    if not E:
        return ""
    L = ["EPISODES YOU REMEMBER WITH THEM (brought back by what they just said; use ONE naturally when it fits, like a friend - "
         "\"tu te souviens, le jour où...\" - never as a report, never if it does not fit):"]
    for x in E:
        L.append("  [%s, %s] %s%s%s" % (x["id"], time.strftime("%d/%m", time.strptime(x["day"], "%Y-%m-%d")), x["what"],
                                       (" - %s" % x["outcome"]) if x.get("outcome") else "", (" (you felt: %s)" % x["feel"]) if x.get("feel") else ""))
    return "\n".join(L)


def facts(uid, n=25):
    u = _load().get(uid) or {}
    F = sorted(u.get("facts") or [], key=lambda f: (-f.get("imp", 3), -f.get("t", 0)))[:n]
    return [f["text"] for f in F]


def consolidate(uid, W, force=False, log=None):
    """weekly: last week's episodes become facts; forgetting"""
    now = time.time()
    u = _load().get(uid) or {}
    if not force and now - float(u.get("last_consol") or 0) < 7 * 86400:
        return None
    old = [x for x in u.get("episodes") or [] if not x.get("c") and now - float(x.get("t") or now) > 7 * 86400]
    if not old and not force:
        _mut(lambda d: _u(d, uid).__setitem__("last_consol", now))
        return None
    if old:
        ep_txt = "\n".join("[%s, %s, imp %d, %s] %s%s" % (x["id"], x["day"], x["imp"], x["kind"], x["what"], (" -> " + x["outcome"]) if x.get("outcome") else "") for x in old[-60:])
        kf = "\n".join("- " + f["text"] for f in (u.get("facts") or [])[-40:]) or "(none yet)"
        j = W.ask_json(CONSOL_SYSTEM, "KNOWN FACTS:\n%s\n\nEPISODES:\n%s\n\nJSON only." % (kf, ep_txt), models=("sonnet", "haiku"), timeout=150, log=log, warm=False)
    else:
        j = {}
    F = (j or {}).get("facts") if isinstance(j, dict) else None
    keep = set(str(k) for k in ((j or {}).get("keep") or [])) if isinstance(j, dict) else set()

    def f(d):
        uu = _u(d, uid)
        added = 0
        for ft in F or []:
            if not isinstance(ft, dict) or not str(ft.get("text") or "").strip():
                continue
            txt = str(ft["text"]).strip()[:240]
            dup = next((x for x in uu["facts"] if _overlap(x["text"], txt) >= 0.6), None)
            try:
                imp = max(1, min(5, int(ft.get("importance") or 3)))
            except Exception:
                imp = 3
            if dup:
                dup.update(text=txt, imp=max(dup.get("imp", 3), imp), t=now)
            else:
                uu["facts"].append({"text": txt, "imp": imp, "t": now, "from": [str(s) for s in (ft.get("from") or [])][:6]})
                added += 1
        uu["facts"] = sorted(uu["facts"], key=lambda x: (-x.get("imp", 3), -x.get("t", 0)))[:60]
        old_ids = set(x["id"] for x in old)
        E2 = []
        for x in uu["episodes"]:
            if x["id"] in old_ids:
                x["c"] = True
            age_d = (now - float(x.get("t") or now)) / 86400
            forget = x.get("c") and x["id"] not in keep and x.get("kind") not in ("moment", "lesson") and (
                (x.get("imp", 3) <= 2 and x.get("recalls", 0) == 0 and age_d > 30) or (x.get("imp", 3) <= 3 and x.get("recalls", 0) == 0 and age_d > 45))
            if not forget:
                E2.append(x)
        dropped = len(uu["episodes"]) - len(E2)
        uu["episodes"] = E2
        uu["last_consol"] = now
        return {"facts_added": added, "dropped": dropped, "consolidated": len(old)}
    return _mut(f)


def night(users, chats_of, W, log=None):
    """every night: each member's new activity -> episodes; then the weekly consolidation when due"""
    now = time.time()
    out = {}
    for u in users or []:
        uid = u.get("id")
        if not uid:
            continue
        try:
            st = _load().get(uid) or {}
            since = float(st.get("last_t") or 0) or (now - 86400)
            if now - since < 3600:
                continue
            chats = chats_of(u)
            ids = write_day(uid, chats, since, now, W, log)
            r = consolidate(uid, W, log=log)
            out[uid] = {"episodes": len(ids), "consol": r}
        except Exception as e:
            out[uid] = {"err": str(e)[:120]}
    return out


def admin_view(uid):
    u = _load().get(uid) or {}
    return {"episodes": (u.get("episodes") or [])[-30:], "facts": u.get("facts") or [], "last_t": u.get("last_t"), "last_consol": u.get("last_consol")}
