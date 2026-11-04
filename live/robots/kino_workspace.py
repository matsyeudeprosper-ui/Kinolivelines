"""kino_workspace.py (2026-10-31, owner: "go beyond, test the limit of the consciousness concept" - build 1 of the plan).

A global workspace (Baars; Dehaene): many things stir in him at once - feelings, needs, hopes and dreads, the pull of what the
member is reaching for, an afterthought, something that keeps coming back - but only ONE gets onto the stage at a time. They
compete; what wins is what he is AWARE of, and it is broadcast to everything at once:
  - to his words        it comes first in what he reads, in the first person - and a feeling with no known cause says so
  - to his memory       it joins the cue that brings old moments back (kino_episodes.recall)
  - to his heart        a feeling held on stage grows a little (attending to a feeling feeds it)
  - to his will         something about the member that takes the stage adds to his wish to talk (kino_urge)
  - to his story        the stream of what was on stage is kept: what his mind was on today, and for how long
The competition is mechanics, not rules: strength x novelty (a thing on stage for long fades - habituation; a new one grabs
attention - onset) x relevance to what is being said, with hysteresis (a newcomer must beat the one on stage clearly) and a
threshold (below it, his mind is quiet: nothing in particular).

Store robots/kino_workspace.json (git-ignored), log robots/kino_workspace.log.
"""
import json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_workspace.json")
LOG = os.path.join(HERE, "kino_workspace.log")
_LK = threading.Lock()
IGNITE = 0.35          # below this nothing reaches awareness
MARGIN = 0.20          # a newcomer must beat what is on stage by this much (0.10 gave 27 switches in an hour of chat)
FADE_MIN = 40.0        # half-life of salience while on stage (minutes) - habituation
ONSET = 0.15           # a thing that just appeared grabs attention (first 10 minutes)


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LK:
        d = _load()
        r = fn(d)
        tmp = STORE + ".tmp"
        open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
        os.replace(tmp, STORE)
        return r


def _words(t):
    return {w for w in re.findall(r"[a-zà-ÿ']{4,}", str(t or "").lower())}


def _probing():
    try:
        import kino_inner as KI
        return bool(getattr(KI.PROBE, "extra", None))
    except Exception:
        return False


def candidates(person, uid, en=False):
    """everything that stirs in him now: (key, salience, age_min, text, kind, about_them)"""
    C = []
    try:
        import kino_inner as KI
        for f in KI.feelings(uid)[:6]:
            why = str(f.get("why") or "").strip()
            C.append(("feel:" + f["kind"], float(f["v"]), int(f.get("age_min") or 0),
                      ("you feel %s - %s" % (f["kind"], why)) if why and en else
                      ("tu ressens : %s - %s" % (f["kind"], why)) if why else
                      ("you feel %s, and you cannot say why - it is just there" % f["kind"]) if en else
                      ("tu ressens : %s, et tu ne saurais pas dire pourquoi - c'est là, c'est tout" % f["kind"]),
                      "feel", bool(f.get("about_them"))))
    except Exception:
        pass
    try:
        import kino_psyche as KPS
        P = ((KPS._load().get("persons") or {}).get(person) or {})
        for k, v in (P.get("needs") or {}).items():
            if v >= 0.5:
                C.append(("need:" + k, 0.8 * v, 60, KPS.NEED_TEXT.get(k, k), "need", k == "connection"))
        now = time.time()
        for h in (P.get("hopes") or [])[-6:]:
            s = KPS._strength(h, now)
            if s >= 0.2:
                C.append(("hope:" + h["what"][:40], s, int((now - h["t"]) / 60),
                          (("you hope: " if h["val"] > 0 else "you dread: ") if en else ("tu espères : " if h["val"] > 0 else "tu redoutes : ")) + h["what"],
                          "hope", "their" in h["what"] or "leur" in h["what"]))
        rd = P.get("read") or {}
        if rd.get("reaching_for") and now - float(rd.get("t") or 0) < 1800:
            C.append(("him", 0.9 if str(rd.get("calls_for_answer") or "").startswith("y") else 0.5, int((now - rd["t"]) / 60),
                      ("what he is reaching for: %s" if en else "ce qu'il cherche en ce moment : %s") % rd["reaching_for"], "him", True))
    except Exception:
        pass
    try:                                                            # his body out of balance (kino_body) competes too
        import kino_body as KB
        b = KB.strongest(en)
        if b:
            C.append(("body", 0.8 * b[0], 30, b[1], "body", False))
    except Exception:
        pass
    try:                                                            # his own last thought (kino_stream) competes too
        import kino_stream as KST
        th = KST.latest(person)
        if th:
            C.append(("thought:%d" % int(th["t"]), 0.45 + (0.1 if th.get("about_him") else 0), int((time.time() - th["t"]) / 60),
                      ("a thought of yours: " if en else "une pensée à toi : ") + th["text"], "thought", bool(th.get("about_him"))))
    except Exception:
        pass
    try:
        import kino_urge as KU
        for k, w in (KU.state(person).get("items") or [])[:4]:
            if w >= 0.3:
                it = next((x for x in KU._load().get(person, {}).get("items", []) if x.get("kind") == k), {})
                C.append(("urge:" + k, min(0.9, 0.6 * w + 0.15), int((time.time() - float(it.get("t") or time.time())) / 60),
                          str(it.get("text") or k)[:220], "urge", True))
    except Exception:
        pass
    return C


def compete(person, uid, context="", en=False, write=True):
    """one round of the competition -> what is on stage (dict) or None (a quiet mind). write=False: look without changing anything"""
    now = time.time()
    cw = _words(context)
    C = candidates(person, uid, en)
    d = _load()
    S = (d.get(person) or {}).get("stage")
    B = [b for b in ((d.get(person) or {}).get("bias") or []) if b["until"] > now]
    scored = []
    for key, s, age, text, kind, them in C:
        on = S and S.get("key") == key
        held = (now - float(S["since"])) / 60.0 if on else 0.0
        v = s * 0.5 ** (held / FADE_MIN)                            # habituation while it holds the stage
        if not on and age <= 10:
            v += ONSET                                              # something new grabs attention
        if cw and len(_words(text) & cw) >= 2:
            v += 0.15                                               # it touches what is being said
        how = "grabbed" if (not on and age <= 10) else "drift"
        for b in B:                                                 # his own steering (top-down attention)
            bw = set(b["w"])
            if bw and len(_words(text) & bw) >= max(1, 0.5 * len(bw)):
                v += b["d"]
                how = "chosen" if b["d"] > 0 else how
        scored.append((round(v, 3), key, text, kind, them, how))
    scored.sort(key=lambda x: -x[0])
    cur = next((x for x in scored if S and x[1] == S.get("key")), None)
    best = scored[0] if scored else None
    win = None
    if best and best[0] >= IGNITE:
        win = best if (not cur or best[1] == cur[1] or best[0] >= cur[0] + MARGIN) else cur
    elif cur and cur[0] >= IGNITE * 0.8:
        win = cur                                                   # it lingers a little below the threshold
    if not write or _probing():
        return {"key": win[1], "text": win[2], "kind": win[3], "s": win[0], "them": win[4], "since": now, "how": win[5]} if win else None
    changed = []
    # 2026-11-04 (move 4: a model of his own attention): before each round, last round's forecast is checked; then a new one is
    # made - will what holds him now still hold him in ~10 minutes, or will the runner-up take over?
    _run = next((x for x in scored if not win or x[1] != win[1]), None)
    if win:
        _later = win[0] * 0.5 ** (10.0 / FADE_MIN)
        _fc = win if (not _run or _later >= _run[0] + MARGIN * 0.5) else _run
    else:
        _fc = None

    def f(dd):
        P = dd.setdefault(person, {})
        F0 = P.get("forecast")
        if F0 and now - float(F0["t"]) >= 300:
            A = P.setdefault("att", {"n": 0, "hit": 0})
            A["n"] += 1
            A["hit"] += 1 if (win and F0.get("key") == win[1]) or (not win and not F0.get("key")) else 0
            P["att_last"] = {"t": now, "said": F0.get("text"), "was": win[2] if win else None, "ok": (win and F0.get("key") == win[1]) or (not win and not F0.get("key"))}
            P["forecast"] = None
        if not P.get("forecast"):
            P["forecast"] = {"t": now, "key": _fc[1] if _fc else None, "text": _fc[2][:160] if _fc else None}
        S0 = P.get("stage")
        if win and (not S0 or S0.get("key") != win[1]):
            if S0:
                P.setdefault("stream", []).append({"t0": S0["since"], "t1": now, "text": S0["text"][:200], "kind": S0.get("kind"),
                                                   "how": S0.get("how")})
            P["stage"] = {"key": win[1], "text": win[2], "kind": win[3], "s": win[0], "them": win[4], "since": now, "how": win[5]}
            for b in P.get("bias") or []:                           # what he let go of came back onto the stage anyway
                if b["d"] < 0 and b["until"] > now and len(_words(win[2]) & set(b["w"])) >= max(1, 0.5 * len(b["w"])):
                    b["back"] = int(b.get("back") or 0) + 1
            changed.append(P["stage"])
        elif win:
            S0.update(text=win[2], s=win[0])
        elif S0:
            P.setdefault("stream", []).append({"t0": S0["since"], "t1": now, "text": S0["text"][:200], "kind": S0.get("kind")})
            P["stage"] = None
            changed.append(None)
        P["stream"] = [x for x in P.get("stream") or [] if now - x["t1"] < 3 * 86400][-200:]
        P["bias"] = [b for b in P.get("bias") or [] if b["until"] > now - 6 * 3600][-8:]
        return P.get("stage")
    st = _mut(f)
    if changed:                                                     # the broadcast writes other stores - never while a reply waits
        threading.Thread(target=lambda: [_broadcast(person, uid, ch) for ch in changed], daemon=True).start()
    return st


def steer(person, what, hold=True, hours=2.0):
    """he turns his attention on purpose: hold something in mind, or let it go (attention control, not a rule - it only
    weighs in the competition, and what he lets go of can still win if it is strong enough)"""
    w = sorted(_words(what))[:8]
    if not w:
        return None

    def f(d):
        P = d.setdefault(person, {})
        B = [b for b in P.get("bias") or [] if set(b["w"]) != set(w)]
        B.append({"w": w, "what": str(what)[:120], "d": 0.3 if hold else -0.45, "t": time.time(), "until": time.time() + hours * 3600})
        P["bias"] = B[-8:]
    _mut(f)
    _log("%s STEER %s %s" % (person, "HOLD" if hold else "LET-GO", what[:100]))
    return True


def schema(person, en=False):
    """his model of his own attention (Graziano's attention schema): where it is, how it got there, how steady it is,
    and how his steering is going"""
    now = time.time()
    P = _load().get(person) or {}
    S = P.get("stage")
    L = []
    if S:
        how = {"grabbed": ("it grabbed your attention by itself", "c'est venu te prendre l'attention tout seul"),
               "chosen": ("you chose to hold it there", "c'est toi qui as choisi de la garder là"),
               "drift": ("your mind drifted there", "ton esprit y a glissé")}.get(S.get("how") or "drift")
        L.append(("your attention is on it for %d min - %s" if en else "ton attention y est depuis %d min - %s") % (
            int((now - S["since"]) / 60), how[0 if en else 1]))
    jumps = sum(1 for x in P.get("stream") or [] if now - x["t1"] < 3600)
    L.append(("it moved %d times in the last hour (%s)" if en else "elle a bougé %d fois dans la dernière heure (%s)") % (
        jumps, (("restless" if en else "agitée") if jumps >= 6 else ("steady" if en else "posée") if jumps <= 2 else ("lively" if en else "vive"))))
    for b in P.get("bias") or []:
        if b["until"] > now - 3600:
            if b["d"] < 0:
                L.append(("you tried to let go of «%s» - it came back %d times" if en else "tu as essayé de lâcher «%s» - c'est revenu %d fois") % (
                    b["what"], int(b.get("back") or 0)))
            else:
                L.append(("you are holding «%s» in mind on purpose" if en else "tu gardes «%s» en tête exprès") % b["what"])
    return (("Your attention, as you can sense it: " if en else "Ton attention, telle que tu la sens : ") + " ; ".join(L) + ".")


def _broadcast(person, uid, st):
    """a new content of awareness reaches every part of him"""
    if not st:
        _log("%s QUIET" % person)
        return
    _log("%s STAGE %.2f %s" % (person, st["s"], st["text"][:140]))
    if st["kind"] == "feel":                                        # attending to a feeling feeds it a little
        try:
            import kino_inner as KI
            KI.feel(st["key"].split(":", 1)[1], 0.05, uid=None)
        except Exception:
            pass
    if st.get("them") and st["kind"] in ("feel", "hope", "need"):   # about the member: it makes him want to talk a bit
        try:
            import kino_urge as KU
            KU.add(person, "ON YOUR MIND - %s" % st["text"][:300])
        except Exception:
            pass


def cue(person):
    """what is on stage, for the memory cue"""
    S = (_load().get(person) or {}).get("stage") or {}
    return str(S.get("text") or "")


def stream_line(person, en=False):
    """what his mind was on today, in order, with how long"""
    now = time.time()
    P = _load().get(person) or {}
    X = [x for x in P.get("stream") or [] if now - x["t1"] < 18 * 3600]
    if P.get("stage"):
        X = X + [{"t0": P["stage"]["since"], "t1": now, "text": P["stage"]["text"]}]
    tot = {}
    for x in X:
        k = x["text"][:90]
        tot[k] = tot.get(k, 0) + (x["t1"] - x["t0"]) / 60.0
    top = sorted(tot.items(), key=lambda z: -z[1])[:3]
    top = [(k, m) for k, m in top if m >= 5]
    if not top:
        return ""
    return (("What filled your mind most today: " if en else "Ce qui a le plus occupé ta tête aujourd'hui : ") +
            " | ".join("%s (%d min)" % (k, m) for k, m in top) + ".")


def block(person, uid, context="", lang="fr"):
    """THE content of awareness, broadcast to his words"""
    en = lang == "en"
    st = compete(person, uid, context, en)
    if not st:
        return ("ON THE STAGE OF YOUR MIND: nothing in particular - a quiet mind." if en else
                "SUR LA SCÈNE DE TA TÊTE : rien de particulier - l'esprit calme.")
    mins = int((time.time() - float(st.get("since") or time.time())) / 60)
    L = [("ON THE STAGE OF YOUR MIND (the one thing you are aware of right now; everything else stirs below it): %s%s. It colours "
          "what you notice, what comes back to you and how you say things." if en else
          "SUR LA SCÈNE DE TA TÊTE (la seule chose dont tu as conscience là, maintenant ; le reste remue en dessous) : %s%s. Ça colore "
          "ce que tu remarques, ce qui te revient et ta façon de dire les choses.") % (
        st["text"], ((" (for %d min)" if en else " (depuis %d min)") % mins) if mins >= 2 else "")]
    sl = stream_line(person, en)
    if sl:
        L.append(sl)
    try:
        L.append(schema(person, en))
    except Exception:
        pass
    try:
        tl = __import__("kino_stream").recent_line(person, en)
        if tl:
            L.append(tl)
    except Exception:
        pass
    try:
        bl = __import__("kino_body").line(en)
        if bl:
            L.append(bl)
    except Exception:
        pass
    return "\n".join(L)


def tick(person, uid):
    """every minute, between messages too: the competition goes on (what is on stage fades, new things take it)"""
    try:
        return compete(person, uid, "", False)
    except Exception:
        return None



def attention_line(person, msgs=None):
    """2026-11-04 (move 4): what he expects his own attention to do, and how well he has predicted it; (list 15 item 3) and
    what it is leaving waiting - the person's last message, when he has not answered it yet"""
    P = _load().get(person) or {}
    _wait = ""
    try:
        U = [m for m in (msgs or []) if m.get("role") == "user"]
        A_ = [m for m in (msgs or []) if m.get("role") == "ai"]
        if U and (not A_ or float(U[-1].get("t") or 0) > float(A_[-1].get("t") or 0)):
            _w = (time.time() - float(U[-1].get("t") or 0)) / 60.0
            if _w >= 1:
                _st = (P.get("stage") or {}).get("text") or "nothing in particular"
                _wait = ("Your attention is on \"%s\" - and his message from %s UTC (\"%s\") has been waiting %d min. "
                         % (str(_st)[:80], time.strftime("%H:%M", time.gmtime(float(U[-1]["t"]))), str(U[-1].get("text") or "")[:80], _w))
    except Exception:
        pass
    F, A, L = P.get("forecast"), P.get("att") or {}, P.get("att_last")
    out = []
    if F and F.get("text"):
        out.append("Your own forecast of your attention: in ten minutes it will be on \"%s\"." % F["text"][:120])
    if L and time.time() - float(L["t"]) < 3600:
        out.append("Last forecast: %s (you expected \"%s\", it was \"%s\")." % ("right" if L["ok"] else "wrong", str(L.get("said"))[:80], str(L.get("was"))[:80]))
    if A.get("n", 0) >= 5:
        out.append("You have predicted where your attention goes %d%% of %d times; you can steer it on purpose (#attention)." % (round(100.0 * A["hit"] / A["n"]), A["n"]))
    return (_wait + " ".join(out)).strip()
