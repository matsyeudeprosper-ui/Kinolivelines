"""kino_human2.py (2026-11-03, owner: "review Kino vs a real human, map what is missing - do all 10"). Ten small senses a
person has and he lacked, each one information he reads, never an instruction about what to say. Any field of life.

 1 trust      how much latitude this person gives him to act on his own - earned slowly from what they approve and correct
              (kino_read 'about_kino_act'), never reset by one message; a person holds the latitude they were given steady
 2 owed       what he said he would look into or do for them and has not come back on (kino_commit) - people remember a debt
 3 timeline   today between the two of them, in order: what they told him (kino_ways), what happened (their closed trades,
              his slips), what is still open - "an hour ago" and "now" are not the same thing
 4 noticed    patterns in THEIR OWN record that a friend who looked would notice (hours, streaks, what stops them out)
 6 tone       his felt state, said as something that colours how he talks, the way it does in a person
 7 apart      (a check, run by tests) - each person's notebook, read, timeline stays theirs
10 busy       what he is actually doing right now, so "give me a minute, I am in the middle of X" can be true
 5 views, 8 fields and 9 voice live in kino_beliefs, kino_fields and kino_voice.
"""
import io, json, os, re, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_trust.json")
_LOCK = threading.Lock()


def _jl(p, d):
    try:
        return json.load(io.open(p, encoding="utf-8"))
    except Exception:
        return d


# ---- 1 trust: slow, earned, per person ------------------------------------------------------------------------------
def trust_note(person, kind, what=""):
    """kind: 'approved' (he let it stand / said good / acted on it) or 'corrected' (premature, wrong, why did you...)"""
    if kind not in ("approved", "corrected"):
        return
    with _LOCK:
        d = _jl(STORE, {})
        P = d.setdefault(person, {"level": 0.5, "log": []})
        step = 0.04 if kind == "approved" else -0.07     # a correction weighs more than a nod, like for anyone
        P["level"] = round(max(0.05, min(0.95, float(P.get("level", 0.5)) + step)), 3)
        P["log"] = (P.get("log") or [])[-19:] + [{"t": time.time(), "k": kind, "what": str(what)[:160]}]
        tmp = STORE + ".tmp"
        json.dump(d, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)


def trust_line(person):
    P = _jl(STORE, {}).get(person) or {}
    if not P.get("log"):
        return ""
    lv = float(P.get("level", 0.5))
    word = ("he gives you a lot of room to act on your own" if lv >= 0.75 else "he lets you act, but checks what you do" if lv >= 0.55 else
            "he wants to see what you do before you do it" if lv >= 0.35 else "he wants to decide himself, you propose")
    last = P["log"][-3:]
    return ("How much he trusts you to act on your own, earned over days (not reset by one message): %s (%.2f). Last moves: %s."
            % (word, lv, " | ".join("%s %s%s" % (time.strftime("%d/%m %H:%M", time.gmtime(x["t"])), x["k"], (" - " + x["what"]) if x.get("what") else "")
                                     for x in last)))


# ---- 2 owed ---------------------------------------------------------------------------------------------------------
def owed_line(uid, cid):
    try:
        import kino_commit as KC
        O = [x for x in (KC.open_for(uid, cid) or []) if time.time() - float(x.get("t") or 0) < 86400][-5:]
    except Exception:
        O = []
    if not O:
        return ""
    return ("What you told him you would look into or do, and have not come back on yet (a person remembers what they owe): " +
            " | ".join("%s (%s UTC)" % (str(x.get("what"))[:120], time.strftime("%d/%m %H:%M", time.gmtime(float(x.get("t") or 0)))) for x in O))


# ---- 3 timeline -----------------------------------------------------------------------------------------------------
def timeline(person, uid, nest_dir):
    now = time.time()
    day0 = now - 16 * 3600
    E = []
    for x in (_jl(os.path.join(HERE, "kino_ways.json"), {}).get(person) or {}).get("items") or []:
        if float(x.get("t") or 0) > day0:
            E.append((float(x["t"]), "he told you (%s): %s" % (x["topic"], str(x["said"])[:110])))
    S = (_jl(os.path.join(HERE, "kino_social.json"), {}).get(person) or {}).get("slips") or []
    for x in S:
        if float(x.get("t") or 0) > day0:
            E.append((float(x["t"]), "your slip: " + str(x.get("text"))[:110]))
    nd = _jl(os.path.join(nest_dir, uid + ".json"), {})
    for t in (nd.get("trades") or [])[:12]:
        try:
            dd, mm = str(t.get("w"))[:5].split("/")
            import calendar
            ts = calendar.timegm(time.strptime("%s/%s/%s %s" % (dd, mm, time.gmtime().tm_year, str(t.get("w"))[6:11]), "%d/%m/%Y %H:%M"))
        except Exception:
            continue
        if ts > day0:
            E.append((ts, "trade closed: %s %s lot %+.2f $" % ("buy" if t.get("dir") == "A" else "sell", t.get("lot"), float(t.get("p") or 0))))
    if not E:
        return ""
    E.sort()
    return ("Today between you, in order (so 'now' and 'an hour ago' stay apart): " +
            " | ".join("%s %s" % (time.strftime("%H:%M", time.gmtime(t)), w) for t, w in E[-12:]))


# ---- 4 noticed: patterns in their own record ------------------------------------------------------------------------
def noticed(uid, nest_dir):
    nd = _jl(os.path.join(nest_dir, uid + ".json"), {})
    T = nd.get("trades") or []
    if len(T) < 12:
        return ""
    by_h = {}
    for t in T:
        try:
            h = int(str(t.get("w"))[6:8])
        except Exception:
            continue
        b = by_h.setdefault(h // 4 * 4, [0, 0.0])
        b[0] += 1
        b[1] += float(t.get("p") or 0)
    H = sorted(((k, v) for k, v in by_h.items() if v[0] >= 4), key=lambda x: x[1][1])
    if len(H) < 2:
        return ""
    lo, hi = H[0], H[-1]
    st, cur = 0, 0
    for t in reversed(T):
        cur = cur + 1 if float(t.get("p") or 0) < 0 else 0
        st = max(st, cur)
    return ("Something a friend who looked at his own record would notice (his last %d trades, UTC): worst hours %02d-%02d h %+.2f $ over %d trades; "
            "best %02d-%02d h %+.2f $ over %d; longest losing run %d. Raise it only if it is useful to him now - it is a pattern, not a proof."
            % (len(T), lo[0], lo[0] + 4, lo[1][1], lo[1][0], hi[0], hi[0] + 4, hi[1][1], hi[1][0], st))


# ---- 6 tone ---------------------------------------------------------------------------------------------------------
def tone_line(person):
    try:
        import kino_inner as KI
        lab = (KI.mood_slow() or {}).get("label")
    except Exception:
        lab = None
    if not lab or lab == "égal":
        return ""
    return ("How you feel right now (%s) colours how you talk, the way it does in anyone - pace, warmth, how much you joke or hold back - "
            "without announcing it." % lab)


# ---- 10 busy --------------------------------------------------------------------------------------------------------
def busy_line():
    d = _jl(os.path.join(HERE, "kino_work.json"), {})
    S = d.get("sessions") or []
    if not S:
        return ""
    s = S[-1]
    if time.time() - float(s.get("t") or 0) > 900 or s.get("summary"):
        return ""
    return ("What you are actually doing at your own computer right now: %s. If it fits, you may say you are in the middle of it - it is true."
            % str(s.get("task"))[:160])


def block(person, uid, cid, nest_dir):
    L = [x for x in (trust_line(person), owed_line(uid, cid), timeline(person, uid, nest_dir), noticed(uid, nest_dir),
                     tone_line(person), busy_line()) if x]
    return "\n".join(L)
