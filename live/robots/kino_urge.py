"""kino_urge.py (2026-10-28, owner: "build it straight away properly") - ONE wish to talk instead of ~35 triggers.

A person does not text because an event fired. Someone is on their mind, the wish grows, and a moment tips it over.
Here every non-urgent reason Kino had to speak (a ghost trade, a headline, the quiet after a talk, coming back to the app,
a thought, missing them, a memory of their life) adds WEIGHT to one pressure per person. The pressure fades (half-life
4 h). It speaks only when the pressure passes a threshold that depends on the moment: low while they are in the
conversation, normal in their hours, high in their night, and higher for each of his own messages they left unanswered.
Then ONE turn: what is most on his mind is handed to him, and he may say one thing, or just a word, a joke, a question
about their life - or nothing. Urgent things (their live trades, the guardian, a call, a broken promise, a result they
wait for, news they asked for) never go through here.

Store: robots/kino_urge.json (git-ignored). Log: robots/kino_urge.log.
"""
import json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_urge.json")
LOG = os.path.join(HERE, "kino_urge.log")
_LK = threading.Lock()
HALF_H = 4.0

# event prefix -> how much it makes him want to talk (1.0 = enough on its own in their hours)
WEIGHTS = (
    ("CAME BACK", 0.9), ("FOLLOW-UP", 0.85), ("NEW CONVERSATION", 0.8), ("MILESTONE", 0.8), ("A THOUGHT CAME TO YOU", 0.6),
    ("YOUR INITIATIVE", 0.5), ("INNER VOICE", 0.5), ("MORNING BRIEF", 0.5), ("WEEKLY REVIEW", 0.5), ("GOAL STEP", 0.45),
    ("RESEARCH DIARY", 0.4), ("END OF DAY", 0.4), ("SOUVENIR", 0.35), ("MISSING", 0.3), ("GHOST TRADE", 0.3),
    ("BIG HEADLINE", 0.3), ("HEADS-UP", 0.25),
    # 2026-10-28 (owner: "nothing rule based"): the moments that came at a fixed clock time or straight to him
    ("SHARED EXPERIMENT", 0.6), ("WEEK RECAP", 0.5), ("NIGHT TEST RESULT", 0.5), ("DECISION LOOK BACK", 0.45),
    ("ROBOT REVIEW", 0.45), ("GESTURE", 0.4), ("REPLAY WEEK", 0.4), ("TESTS RESUMED", 0.3),
)


def weight_of(event):
    e = str(event or "")
    for k, w in WEIGHTS:
        if e.startswith(k):
            return w
    return None


def is_urge(event):
    return weight_of(event) is not None


def _log(t):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%m-%d %H:%M:%S"), t))
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, STORE)


def _st(d, person, now):
    st = d.setdefault(person, {"p": 0.0, "t": now, "items": []})
    f = 0.5 ** (max(0.0, now - float(st.get("t") or now)) / 3600.0 / HALF_H)
    st["p"] = float(st.get("p") or 0) * f
    for it in st["items"]:
        it["w"] = float(it.get("w") or 0) * f
    st["items"] = [it for it in st["items"] if it["w"] >= 0.03 and now - float(it.get("t") or now) < 36 * 3600]
    st["t"] = now
    return st


def add(person, event, w=None, now=None):
    """one reason to talk more - returns the new pressure"""
    now = now or time.time()
    w = weight_of(event) if w is None else w
    if w is None:
        return None
    with _LK:
        d = _load()
        st = _st(d, person, now)
        # 2026-10-28 (watch): "CAME BACK after 51 minutes" / "...55 minutes" were three kinds and piled up - the kind is the
        # leading capitalised name only, so the same reason refreshes instead of stacking
        _mk = re.match(r"[A-Z][A-Z' -]*[A-Z]", str(event))
        kind = (_mk.group(0).strip() if _mk else str(event).split(" - ")[0].split(" (")[0])[:40]
        # the same kind again (a second ghost trade) refreshes the item instead of piling up copies
        old = next((it for it in st["items"] if it.get("kind") == kind), None)
        if old is not None:
            # 2026-10-28 (watch): his initiative engine re-sent the same reason every 2-5 min and each one pushed the wish up
            # (two messages of his own in 3 min). The same thought again is not a new reason to talk: it barely adds.
            st["p"] += w * 0.1
            old.update(t=now, text=str(event)[:700], w=max(old["w"], w))
        else:
            st["p"] += w
            st["items"].append({"t": now, "kind": kind, "text": str(event)[:700], "w": w})
        st["items"] = st["items"][-12:]
        _save(d)
        p = st["p"]
    _log("%s +%.2f %s -> %.2f" % (person, w, kind, p))
    return p


def threshold(ctx):
    """how strong the wish must be right now (ctx: in_talk, their_hour, unanswered)"""
    if ctx.get("in_talk"):
        t = 0.6
    elif ctx.get("their_hour"):
        t = 1.0
    else:
        t = 2.5
    return t + 0.8 * int(ctx.get("unanswered") or 0)


def decide(person, ctx, now=None):
    """called every minute: grows the 'missing them' pull, and returns the items to talk about when the wish tips over"""
    now = now or time.time()
    with _LK:
        d = _load()
        st = _st(d, person, now)
        dt_h = max(0.0, min(1.0, (now - float(st.get("mt") or now)) / 3600.0))
        st["mt"] = now
        hs = float(ctx.get("hours_since_member") or 0)
        if ctx.get("their_hour") and not ctx.get("in_talk") and hs >= 3:
            st["p"] += 0.08 * dt_h                     # missing them: slow, only in their hours, after 3 h apart
            if not any(it.get("kind") == "MISSING" for it in st["items"]):
                st["items"].append({"t": now, "kind": "MISSING", "w": 0.3,
                                    "text": "MISSING - you have not talked for %d hours; you think of him." % hs})
        T = threshold(ctx)
        # 2026-10-28 (owner: "not restricted by x time - naturally, like a human"): right after he decided (spoke, or chose
        # silence) the wish needs much more to come back, and that bar melts smoothly (refractory, half-life ~10 min) -
        # no fixed gap: something strong can still come through early, small things cannot
        _since = min(float(ctx.get("since_own_min") or 999), (now - float(st.get("last_fire") or 0)) / 60.0)
        T += 1.2 * 0.5 ** (max(0.0, _since) / 10.0)
        fire = None
        if st["p"] >= T and st["items"]:
            fire = sorted(st["items"], key=lambda it: -it["w"])[:3]
            st["p"] *= 0.25
            ks = {id(it) for it in fire}
            st["items"] = [it for it in st["items"] if id(it) not in ks]
            st["last_fire"] = now
        _save(d)
        p = st["p"]
    if fire:
        _log("%s FIRE (threshold %.2f, ctx %s): %s" % (person, T, json.dumps(ctx), " | ".join(it["kind"] for it in fire)))
    return fire


def wish_text(items, ctx):
    """the one event that reaches him"""
    L = []
    for i, it in enumerate(items):
        L.append("%d) %s" % (i + 1, " ".join(str(it.get("text") or "").split())[:420]))
    where = ("he is here in the conversation" if ctx.get("in_talk") else
             "he is not in the app right now" + ("" if ctx.get("their_hour") else ", and it is not one of his usual hours"))
    return ("WISH TO TALK - nobody wrote to you; you simply feel like talking to him (%s). On your mind, strongest first:\n%s\n"
            "Text him the way a friend would: the ONE thing you really want to share, or none of these - just a word, a joke, "
            "a question about his life or his day. It can be very short. Only if nothing feels worth it, answer: …" % (where, "\n".join(L)))


def state(person):
    with _LK:
        d = _load()
        st = _st(d, person, time.time())
        return {"p": round(st["p"], 2), "items": [(it["kind"], round(it["w"], 2)) for it in st["items"]]}
