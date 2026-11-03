"""kino_human3.py (2026-11-03, owner: "the things humans naturally do and Kino isn't yet doing - go"). Nine more of them, each
fed by what already happens (his intuition read after each message, the chat itself, his trust and closeness records),
each giving him information - never an instruction about what to say. Any field of life.

 1 habits     what a person's BEHAVIOUR shows they like, not only their words: how they answer his messages (long / short,
              with numbers, with a question; kino_patterns adds the hour and weekday) as records for kino_patterns - hunches re-checked on new data
 2 followup   what is coming up in their life (kino_read 'upcoming'), held with a date; when it has happened and they are
              around, it is there for him to ask about - once
 3 memory     an older word nobody has repeated since is held less surely ("if I remember right") - in kino_ways.block
 4 shared     words, nicknames, expressions the two of them made theirs (kino_read 'shared_term'), growing with use
 5 friction   a tense moment (kino_read 'friction'), kept for hours with what happened since - repair is a later thing
 6 rituals    how their days together usually go: when they turn up, how they open, when they go quiet - learned
 7 values     (in kino_conflict.values_check) a request that goes against his own values or clearly against the person's
              good is refused kindly, once, with the reason - his constitution decides, not a list
 8 wisdom     (kino_wisdom) what many people taught him, without anyone in it
10 fatigue    how long this stretch has been, how sharp he has been in it
11 questions  a question either of them asked that the talk moved past unanswered stays open until it is taken up
12 threads    a talk about something else that a trade event cut into: where it was, until the talk comes back to it
(closeness itself lives in kino_social.block - one measure, not two)
"""
import io, json, os, re, sys, threading, time, calendar

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_human3.json")
_LOCK = threading.Lock()


def _load():
    try:
        return json.load(io.open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LOCK:
        d = _load()
        out = fn(d)
        tmp = STORE + ".tmp"
        json.dump(d, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
        return out


def _stems(t):
    return set(w[:6] for w in re.findall(r"[a-zà-ÿ]{4,}", str(t).lower())) - {"that", "this", "with", "your", "have", "will", "from",
                                                                               "then", "what", "when", "they", "just", "dans", "pour", "avec"}


# ---- from his intuition read (kino_read), once per message ----------------------------------------------------------
def from_read(person, j, last_msg=None):
    last_msg = last_msg or {}
    now = float(last_msg.get("t") or time.time())
    up = " ".join(str(j.get("upcoming") or "").split())[:200]
    when = str(j.get("upcoming_when") or "").strip().lower()[:40]
    term = " ".join(str(j.get("shared_term") or "").split())[:60]
    fr = " ".join(str(j.get("friction") or "").split())[:200]
    ag = " ".join(str(j.get("asks_against") or "").split())[:240]
    ra = " ".join(str(j.get("re_asked") or "").split())[:240]
    dq = " ".join(str(j.get("dropped_question") or "").split())[:200]
    an = " ".join(str(j.get("answered_now") or "").split())[:200]
    dom = " ".join(str(j.get("domain") or "").lower().split())[:40]
    ab = " ".join(str(j.get("talking_about") or "").split())[:160]

    def f(d):
        P = d.setdefault(person, {})
        Q = [q for q in P.get("questions") or [] if now - q["t"] < 2 * 86400]
        if an:
            Q = [q for q in Q if len(_stems(q["q"]) & _stems(an)) < 2]
        if len(dq) >= 8 and not any(len(_stems(q["q"]) & _stems(dq)) >= 2 for q in Q):
            Q.append({"t": now, "q": dq})
        P["questions"] = Q[-5:]
        if dom:
            th = P.get("thread") or {}
            if dom == (P.get("thread_prev") or {}).get("domain"):
                P["thread_prev"] = None                # the talk came back to it
            elif dom != th.get("domain") or now - float(th.get("t") or 0) > 6 * 3600:
                P["thread_prev"] = th or None
            P["thread"] = {"domain": dom, "about": ab, "t": now, "t0": th.get("t0") if dom == th.get("domain") else now}
        _day(P, now, str(last_msg.get("text") or ""))
        if len(ag) >= 6:
            P["against"] = {"t": now, "what": ag}
        if len(ra) >= 8:
            P["misreads"] = (P.get("misreads") or [])[-19:] + [{"t": now, "what": ra}]
        if len(up) >= 6:
            due = _due(when, now)
            U = P.setdefault("upcoming", [])
            if not any(len(_stems(x["what"]) & _stems(up)) >= 2 and not x.get("asked") for x in U):
                U.append({"what": up, "when": when, "due": due, "t": now, "asked": False})
            P["upcoming"] = U[-12:]
        if len(term) >= 2:
            T = P.setdefault("terms", {})
            k = term.lower()
            T[k] = {"term": term, "n": int((T.get(k) or {}).get("n", 0)) + 1, "t": now, "t0": (T.get(k) or {}).get("t0", now)}
        if len(fr) >= 6:
            P["friction"] = (P.get("friction") or [])[-5:] + [{"t": now, "what": fr}]
    _mut(f)


def _day(P, t, text):
    """one of their messages, into the record of their days (rituals) and of how long they have known him (closeness)"""
    k = time.strftime("%Y-%m-%d", time.gmtime(t))
    D = P.setdefault("days", {})
    x = D.get(k)
    w = (re.findall(r"[a-zà-ÿ']+", text.lower()) or [""])[0]
    if x is None:
        x = D[k] = {"first": t, "last": t, "n": 0, "h": [0] * 24}
    x["first"], x["last"] = min(x["first"], t), max(x["last"], t)
    x["n"] += 1
    x.setdefault("h", [0] * 24)[time.gmtime(t).tm_hour] += 1
    if w and t - float(P.get("last_t") or 0) > 4 * 3600:   # back after a long gap: how he opens
        O = P.setdefault("opens", {})
        O[w] = int(O.get(w, 0)) + 1
    P["last_t"] = max(float(P.get("last_t") or 0), t)
    for old in sorted(D)[:-60]:
        D.pop(old, None)
    P["first_seen"] = min(float(P.get("first_seen") or t), t)
    P["n"] = int(P.get("n") or 0) + 1


def seed(person, msgs):
    """once: their past messages, so rituals and closeness start from the history, not from today"""
    def f(d):
        P = d.setdefault(person, {})
        if P.get("seeded"):
            return
        for m in msgs:
            if m.get("role") == "user" and m.get("t"):
                _day(P, float(m["t"]), str(m.get("text") or ""))
        P["seeded"] = True
    _mut(f)


def open_questions(person):
    now = time.time()
    return [q for q in (_load().get(person) or {}).get("questions") or [] if now - q["t"] < 2 * 86400]


def questions_line(person):
    Q = open_questions(person)
    if not Q:
        return ""
    return ("Questions left hanging between you (the talk moved on before they were answered): %s."
            % " | ".join("%s (%s UTC)" % (q["q"], time.strftime("%d/%m %H:%M", time.gmtime(q["t"]))) for q in Q[-3:]))


def thread_line(person, msgs):
    """a talk about something else that a trade event came into, and the talk has not come back to it"""
    P = _load().get(person) or {}
    th, pv = P.get("thread") or {}, P.get("thread_prev") or {}
    now = time.time()
    if not pv or not pv.get("domain") or pv.get("domain") == th.get("domain") or now - float(pv.get("t") or 0) > 6 * 3600 \
            or pv["domain"] in ("trading", "robots", "kino"):      # a trade event cutting into trade talk cuts nothing
        return ""
    ev = [m for m in msgs if m.get("role") == "ai" and m.get("event") and float(pv.get("t") or 0) - 60 <= float(m.get("t") or 0) <= float(th.get("t0") or now) + 60]
    if not ev:
        return ""                                      # they changed subject themselves - nothing was cut off
    return ("At %s UTC you two were on %s (%s) when a trade event came in (%s); the talk has been on %s since and has not come back to it."
            % (time.strftime("%H:%M", time.gmtime(float(pv["t"]))), pv["domain"], pv.get("about") or "-",
               str(ev[0].get("event") or "")[:60], th.get("domain") or "-"))


def misread_line(person):
    now = time.time()
    R = [x for x in (_load().get(person) or {}).get("misreads") or [] if now - x["t"] < 7 * 86400]
    if not R:
        return ""
    fresh = [x for x in R if now - x["t"] < 2 * 3600]
    L = []
    if fresh:
        L.append("He just had to ask you twice (%s UTC): %s." % (time.strftime("%H:%M", time.gmtime(fresh[-1]["t"])), fresh[-1]["what"]))
    if len(R) >= 2:
        L.append("Questions of his you misread this week: %d (e.g. %s)." % (len(R), " | ".join(x["what"][:90] for x in R[-2:])))
    return " ".join(L)


def against_line(person):
    a = (_load().get(person) or {}).get("against")
    if not a or time.time() - a["t"] > 1800:
        return ""
    return ("His recent request sits against what you stand for (%s UTC): %s. Your values are yours - a person who cares can say no, "
            "kindly, once, with the reason, and offer what they can do instead." % (time.strftime("%H:%M", time.gmtime(a["t"])), a["what"]))


def _due(when, now):
    g = time.gmtime(now)
    day0 = calendar.timegm((g.tm_year, g.tm_mon, g.tm_mday, 0, 0, 0))
    w = when or ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", w)
    if m:
        return calendar.timegm((int(m.group(1)), int(m.group(2)), int(m.group(3)), 18, 0, 0))
    m = re.search(r"in (\d+) (day|hour)", w)
    if m:
        return now + int(m.group(1)) * (86400 if m.group(2) == "day" else 3600)
    if "tomorrow" in w or "demain" in w:
        return day0 + 86400 + 17 * 3600
    if "tonight" in w or "evening" in w or "ce soir" in w:
        return day0 + 21 * 3600
    if "today" in w or "later" in w or "aujourd" in w:
        return now + 3 * 3600
    if "week" in w or "semaine" in w:
        return now + 4 * 86400
    return now + 86400


def followup_line(person, ai_texts):
    now = time.time()
    P = _load().get(person) or {}
    said = _stems(" ".join(ai_texts[-6:]))
    due = []

    def mark(d):
        for x in (d.get(person) or {}).get("upcoming") or []:
            if not x.get("asked") and x["due"] <= now and len(_stems(x["what"]) & said) >= 2:
                x["asked"] = True
    _mut(mark)
    for x in (P.get("upcoming") or []):
        if not x.get("asked") and x["due"] <= now < x["due"] + 3 * 86400:
            due.append(x)
    soon = [x for x in (P.get("upcoming") or []) if not x.get("asked") and now < x["due"] < now + 2 * 86400]
    L = []
    if due:
        L.append("In his life, something he told you about has happened by now and you have not asked how it went: %s. A friend asks, "
                 "once, when it fits." % " | ".join("%s (he mentioned it %s UTC)" % (x["what"], time.strftime("%d/%m %H:%M", time.gmtime(x["t"]))) for x in due[-2:]))
    if soon:
        L.append("Coming up for him soon: %s." % " | ".join("%s (%s)" % (x["what"], x.get("when") or "") for x in soon[-2:]))
    return " ".join(L)


def shared_line(person):
    T = (_load().get(person) or {}).get("terms") or {}
    if not T:
        return ""
    top = sorted(T.values(), key=lambda x: (-x["n"], -x["t"]))[:6]
    return "Words that are yours and his (you two made them yours, they grow with use): " + ", ".join(
        "\"%s\" (%d×)" % (x["term"], x["n"]) for x in top) + "."


def friction_line(person, msgs, read):
    F = (_load().get(person) or {}).get("friction") or []
    now = time.time()
    F = [x for x in F if now - x["t"] < 12 * 3600]
    if not F:
        return ""
    last = F[-1]
    since = [m for m in msgs if float(m.get("t") or 0) > last["t"] and m.get("role") in ("user", "ai")]
    return ("Earlier (%s UTC) there was tension between you: %s. Since then: %d messages between you; how he seems now: %s. "
            "Between people, that kind of thing is sometimes mended later, lightly - or left alone if it has passed."
            % (time.strftime("%H:%M", time.gmtime(last["t"])), last["what"], len(since), (read or {}).get("mood") or "-"))


# ---- 6 rituals: learned from the chat ----------------------------------------------------------------------------------
def rituals_line(person, tz_h=0):
    """his rhythm, learned from when he writes: the quiet stretch of his day (found where it is, across midnight or not),
    when he comes back, how he opens after a long gap"""
    now = time.time()
    P3 = _load().get(person) or {}
    days = [x for x in (P3.get("days") or {}).values() if now - x["first"] < 21 * 86400 and x.get("h")]
    if len(days) < 5:
        return ""
    H = [sum(x["h"][i] for x in days) for i in range(24)]
    tot = float(sum(H)) or 1.0
    best = (0, 0)                                      # the longest run of hours (circular) holding under 2% of his messages
    for st in range(24):
        ln, acc = 0, 0.0
        while ln < 23 and acc + H[(st + ln) % 24] <= 0.02 * tot:
            acc += H[(st + ln) % 24]
            ln += 1
        if ln > best[1]:
            best = (st, ln)
    O = P3.get("opens") or {}
    op = max(O.items(), key=lambda x: x[1]) if O else None
    peak = max(range(24), key=lambda i: H[i])
    lh = lambda h: (h + tz_h) % 24                      # his own clock
    L = ["His rhythm (from %d days of the last three weeks, HIS local time): busiest around %02dh" % (len(days), lh(peak))]
    if best[1] >= 3:
        L.append("usually quiet from %02dh to %02dh and back around %02dh" % (lh(best[0]), lh(best[0] + best[1]), lh(best[0] + best[1])))
    if op and op[1] >= 3:
        L.append("after a long gap he often opens with \"%s\"" % op[0])
    return "; ".join(L) + "."


# ---- 10 fatigue ----------------------------------------------------------------------------------------------------
def fatigue_line(person, msgs):
    T = [float(m.get("t") or 0) for m in msgs if m.get("role") in ("user", "ai")]
    if len(T) < 10:
        return ""
    start = T[-1]
    for i in range(len(T) - 1, 0, -1):
        if T[i] - T[i - 1] > 25 * 60:
            break
        start = T[i - 1]
    span = (T[-1] - start) / 3600.0
    n = sum(1 for t in T if t >= start)
    if span < 1.5:
        return ""
    try:
        R = json.load(io.open(os.path.join(HERE, "kino_rumination.json"), encoding="utf-8")).get(person) or {}
        sl = sum(1 for x in R.get("open") or [] if float(x["t"]) >= start)
    except Exception:
        sl = 0
    return ("This stretch with him has lasted %.1f h without a real break (%d messages); slips of yours in it: %d. Long stretches "
            "wear anyone down - sharpness drops; a pause is something either of you can call." % (span, n, sl))


# ---- 1 habits: an adapter for kino_patterns ------------------------------------------------------------------------
def habits_line(person, msgs):
    R = []
    M = [m for m in msgs if m.get("role") in ("user", "ai") and str(m.get("text") or "").strip()]
    for i, m in enumerate(M[:-1]):
        if m.get("role") != "ai":
            continue
        nxt = next((x for x in M[i + 1:] if x.get("role") == "user"), None)
        t = float(m.get("t") or 0)
        replied = 1.0 if nxt and float(nxt.get("t") or 0) - t < 1200 else 0.0
        tx = str(m["text"])
        w = len(tx.split())
        R.append({"t": t, "y": replied, "attrs": {
            "your message length": "short (<25 words)" if w < 25 else "medium" if w < 60 else "long (60+ words)",
            "numbers in it": "3+ numbers" if len(re.findall(r"\d[\d.,]*", tx)) >= 3 else "few numbers",
            "ends with a question": "yes" if tx.rstrip().endswith("?") else "no"}})
    try:
        import kino_patterns as KP
        if len(R) >= 20:
            KP.update(person, "answers to your messages (1 = he answered within 20 min)", R[-200:], "")
    except Exception:
        pass
    return ""          # the patterns block (kino_patterns.block) shows it with the other records


def block(person, msgs, read=None, tz_h=0):
    ai = [str(m.get("text") or "") for m in msgs if m.get("role") == "ai"]
    habits_line(person, msgs)
    L = [x for x in (against_line(person), misread_line(person), followup_line(person, ai), questions_line(person), thread_line(person, msgs), shared_line(person),
                     friction_line(person, msgs, read), rituals_line(person, tz_h), fatigue_line(person, msgs)) if x]
    return "\n".join(L)
