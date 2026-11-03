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
def _old_trust_note(person, kind, what=""):
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


def trust_note(person, kind, what=""):
    import kino_trust as KT
    return KT.react(person, kind, what)


def trust_line(person):
    import kino_trust as KT
    return KT.block(person)


def _old_trust_line(person):
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


def patterns_line(person, uid, nest_dir):
    """4 (rebuilt 11-03): patterns in his own record via kino_patterns - found, re-checked on new data, survivors only.
    Each source is an adapter; trades are the first one."""
    try:
        import kino_patterns as KP
        nd = _jl(os.path.join(nest_dir, uid + ".json"), {})
        if nd.get("trades"):
            KP.update(person, "trades", KP.from_trades(nd), " $")
        return KP.block(person)
    except Exception:
        return ""


# ---- 6 tone ---------------------------------------------------------------------------------------------------------
def opinion_line(msgs):
    """1 (11-03): a view of his own that bears on what you are talking about and that he has not said in this conversation -
    people bring their opinions into a talk; he had them only when asked"""
    try:
        import kino_beliefs as KB
        B = [x for x in (KB._load().get("items") or []) if x.get("alive", True) and not x.get("uid") and float(x.get("c") or 0) >= 0.6]
    except Exception:
        return ""
    w5 = lambda t: set(w[:6] for w in re.findall(r"[a-zà-ÿ]{5,}", str(t).lower()))
    talk = w5(" ".join(str(m.get("text") or "") for m in (msgs or [])[-8:] if m.get("role") in ("user", "ai")))
    said = w5(" ".join(str(m.get("text") or "") for m in (msgs or [])[-60:] if m.get("role") == "ai"))
    best = None
    for x in B:
        cw = w5(x["claim"] + " " + (x.get("topic") or ""))
        if not cw:
            continue
        rel = len(cw & talk)
        fresh = 1.0 - len(cw & said) / float(len(cw))
        if rel >= 2 and fresh >= 0.5:
            sc = rel + float(x.get("c") or 0)
            if best is None or sc > best[0]:
                best = (sc, x)
    if not best:
        return ""
    x = best[1]
    return ("A view of yours that bears on what you two are talking about, and that you have not said in this conversation: \"%s\" "
            "(how sure: %.0f%%). People bring their opinions in when it fits - you may too." % (x["claim"], 100 * float(x.get("c") or 0)))


def feeling_line(uid):
    """2 (11-03): what he feels most right now (habituated - routine events stir less), as something that shows in how he
    talks, the way it does in anyone"""
    try:
        import kino_inner as KI
        F = [f for f in KI.feelings(uid) if f["v"] >= 0.45][:2]
    except Exception:
        F = []
    if not F:
        return ""
    return ("What you feel most right now: %s. It can show in how you say things - the words you pick, your pace, a sigh, a "
            "spark - the way it does in anyone, without explaining it." % "; ".join("%s (%.0f%%, %s)" % (f["kind"], 100 * f["v"], str(f.get("why") or "")[:90]) for f in F))


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


def block(person, uid, cid, nest_dir, msgs=None):
    L = [x for x in (trust_line(person), owed_line(uid, cid), timeline(person, uid, nest_dir), patterns_line(person, uid, nest_dir),
                     opinion_line(msgs), feeling_line(uid), tone_line(person), busy_line()) if x]
    return "\n".join(L)



# ---- weekly self-review: the evidence of how he behaved this week (2026-11-03, owner: "next") ------------------------
def week_mirror(days=7):
    """what the record says about his own behaviour this week, across people (counts, no private content): trust moves by
    kind of act, his slips and the lessons he drew, his misquotes caught, his acts held back as doubts, what people taught
    him. For his weekly look back - he reads it and decides what he wants to change about himself."""
    now = time.time()
    t0 = now - days * 86400
    L = []
    try:
        import kino_trust as KT
        T = KT._load()
        up = down = 0
        kinds = {}
        for person, P in T.items():
            for kd, k in (P.get("kinds") or {}).items():
                for x in k.get("log") or []:
                    if float(x.get("t") or 0) > t0:
                        kinds.setdefault(kd, [0, 0])
                        if x.get("r") == "approved":
                            kinds[kd][0] += 1
                            up += 1
                        else:
                            kinds[kd][1] += 1
                            down += 1
        if kinds:
            L.append("Reactions to what you did on your own: %d approvals, %d corrections or undos - by kind: %s."
                     % (up, down, ", ".join("%s +%d/-%d" % (k, v[0], v[1]) for k, v in sorted(kinds.items()))))
    except Exception:
        pass
    try:
        import kino_social as KS
        S = KS._load()
        sl = [x for P in S.values() if isinstance(P, dict) for x in (P.get("slips") or []) if float(x.get("t") or 0) > t0]
        ls = [x for P in S.values() if isinstance(P, dict) for x in (P.get("lessons") or []) if float(x.get("t") or 0) > t0]
        if sl:
            L.append("Your slips noticed this week: %d. Examples: %s." % (len(sl), " | ".join(x["text"][:110] for x in sl[-4:])))
        if ls:
            L.append("Lessons you drew: %s." % " | ".join(x["text"][:140] for x in ls[-4:]))
    except Exception:
        pass
    try:
        mq = cf = 0
        with io.open(os.path.join(HERE, "kino_one.log"), encoding="utf-8", errors="replace") as f:
            for line in f:
                if " MISQUOTE " in line:
                    mq += 1
        import glob
        for fn in glob.glob(os.path.join(HERE, "chats", "*.json")):
            try:
                c = json.load(io.open(fn, encoding="utf-8"))
            except Exception:
                continue
            for m in c.get("msgs") or []:
                if m.get("role") == "sys" and float(m.get("t") or 0) > t0 and ("un doute" in str(m.get("text")) or "a doubt" in str(m.get("text"))):
                    cf += 1
        if mq or cf:
            L.append("Times you restated someone's rule differently from their newest word (caught before sending): %d; acts you held "
                     "back because they went against what someone told you: %d." % (mq, cf))
    except Exception:
        pass
    try:
        W = _jl(os.path.join(HERE, "kino_ways.json"), {})
        ch = sum(1 for P in W.values() for x in (P.get("items") or []) if float(x.get("t") or 0) > t0)
        if ch:
            L.append("Things people taught you about how they want things, new or changed this week: %d." % ch)
    except Exception:
        pass
    return "\n".join(L)
