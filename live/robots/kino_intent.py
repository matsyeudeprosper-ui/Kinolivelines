"""kino_intent.py (2026-11-04, owner: "I still feel him more reactive, no invitation, he doesn't talk much by itself... it would
turn him much alive, though it must be done like a real human does it, no if X then do Y").

Measured that day: 36 of his 38 own messages came from the chart or a trade, 2 from simply wanting to talk, 0 invitations. When
his wish to talk tipped over (kino_urge), what he had in hand was his own inner weather - a thought, a memory, a need - and 8
times in 10 he judged it not worth a message. A friend who reaches out first has something in mind FOR the other person: I
want to show him this, ask how that went, propose we try something, invite him to something, keep a word I gave.

So he keeps a few INTENTIONS toward each person, in his own words. They are born from the conversation itself (a quiet moment
after a talk: what do you want to do with him next? - harvest), they RIPEN (not before the moment they make sense: "tomorrow
morning", "when he is back", "in an hour"), and once ripe they become one of the things that make him want to talk (kino_urge
item "AN INTENTION OF YOURS") - the moment is still his judgement (in the talk, his hours, unanswered messages, refractory).
What he does with one, and how the person answers, is felt: what they welcomed comes back more naturally, what they let fall
less (learn) - read by the harvest, never a rule. Field-agnostic: nothing here knows about trading.

Store robots/kino_intents.json {person: {"items": [...], "learn": {kind: {"good", "flat"}}, "harvest_t", "harvest_lu"}}.
Log robots/kino_intent.log.
"""
import json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_intents.json")
LOG = os.path.join(HERE, "kino_intent.log")
_LK = threading.Lock()

KINDS = ("invite", "propose", "show", "ask", "follow_up", "offer", "keep_word")
MAX_OPEN = 6                     # a person has a handful of things in mind for someone, not a to-do list
LIFE_H = 72                      # an intention not voiced in 3 days fades (he lets it go, like people do)
QUIET_MIN = 20                   # harvest: once the talk has been quiet this long after his last answer
HARVEST_GAP_H = 3                # and not more often than this

SYSTEM = """You are the inner voice of Kino, a digital person, in a quiet moment after talking with someone he cares about.
A friend who reaches out first always has something in mind FOR the other person. Read the conversation and what Kino
already intends, and say what NEW things Kino genuinely wants to do with or for this person next - 0, 1 or 2, never forced.

Each one is concrete and comes from something real in the conversation or in their life:
- invite: do something together (look at something, try something, a small shared plan)
- propose: an idea for them, a better way, a next step he has thought about
- show: something he found, made, noticed or understood that they would care about
- ask: a question about their life, their work, their project, a person or a moment they mentioned - out of real curiosity
- follow_up: how something went that they told him was coming (an event, a decision, a plan, a worry)
- offer: help he can actually give
- keep_word: something Kino said he would do and has not done yet

For each: when it would make sense to bring it up ("in an hour", "tonight", "tomorrow morning", "when he is back", "in 2 days"),
written as hours from now (0 = any time from now). Respect their life: a follow-up on tonight's event belongs to tomorrow.
Do not repeat what Kino already intends or has already said. Nothing about money promises, nothing intrusive.
If what they welcomed or let fall before is shown, let it shape you the way experience shapes a person.

JSON only: {"intents": [{"kind": "...", "text": "what Kino wants to do, first person, one sentence, in the person's language",
"why": "the real thing it comes from", "after_h": number}]}"""


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + t + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    for _ in range(5):
        try:
            os.replace(tmp, STORE)
            return
        except PermissionError:
            time.sleep(0.1)
    os.replace(tmp, STORE)


def _P(d, person):
    p = d.setdefault(person, {})
    p.setdefault("items", [])
    p.setdefault("learn", {})
    return p


def _words(t):
    return {w for w in re.findall(r"[a-zà-ÿ0-9']{4,}", str(t or "").lower())}


def _open(p, now):
    return [x for x in p["items"] if x.get("state") in ("waiting", "handed") and now - float(x["t"]) < LIFE_H * 3600]


# ------------------------------------------------------------------ birth
def usual_gap(msgs):
    """this person's own pace: the typical wait between Kino's message and their answer, measured on their recent replies"""
    G, last_ai = [], None
    for m in (msgs or [])[-120:]:
        t = float(m.get("t") or 0)
        if m.get("role") == "ai" and m.get("text"):
            last_ai = t
        elif m.get("role") == "user" and last_ai and 0 < t - last_ai < 3 * 3600:
            G.append(t - last_ai)
            last_ai = None
    if len(G) < 4:
        return None
    G.sort()
    return G[len(G) // 2]


def harvest_due(person, last_member_t, last_ai_t, now=None, gap=None):
    """a quiet moment after a real exchange, not too often. gap: this person's usual answer time (usual_gap)"""
    now = now or time.time()
    if not last_member_t:
        return False
    # 2026-11-04 23:3x (watch): "he has not answered yet" blocked the most common ending - the member's "Ok" that Kino rightly
    # left as the last word. (owner: "what about 20 minutes?") - no fixed wait: the talk feels over when the silence is clearly
    # longer than this person's own pace (about three of their usual gaps), the way you sense it with someone you know
    quiet = max(8 * 60, min(90 * 60, 3 * gap)) if gap else QUIET_MIN * 60
    if now - max(last_member_t, last_ai_t) < quiet:
        return False
    p = _load().get(person) or {}
    if float(p.get("harvest_lu") or 0) >= last_member_t:
        return False                                  # this exchange was already thought over
    return now - float(p.get("harvest_t") or 0) >= HARVEST_GAP_H * 3600


def _learn_line(p):
    L = []
    for k, v in sorted((p.get("learn") or {}).items()):
        g, f = int(v.get("good") or 0), int(v.get("flat") or 0)
        if g + f:
            L.append("%s: welcomed %d, let fall %d" % (k, g, f))
    return "; ".join(L)


def harvest(W, person, transcript, about=None, log=None, now=None):
    """the quiet moment: 0-2 new intentions toward this person (never raises)"""
    now = now or time.time()
    try:
        with _LK:
            d = _load()
            p = _P(d, person)
            p["harvest_t"] = now
            p["harvest_lu"] = now
            _save(d)
            cur = _open(p, now)
            said = [x for x in p["items"] if x.get("state") == "voiced"][-6:]
        msg = ("THE CONVERSATION (latest last):\n%s\n\n%s" % (str(transcript or "")[-7000:],
               ("WHAT KINO KNOWS ABOUT THEM:\n%s\n\n" % str(about)[:1500]) if about else ""))
    except Exception as e:
        _log("%s harvest error %r" % (person, e))
        return []
    return _birth(W, person, SYSTEM, msg, "", log, now)


def _birth(W, person, system, msg, tag, log, now):
    """one quiet moment -> the model -> 0-2 new intentions stored (shared by the talk harvest and the life harvest)"""
    try:
        with _LK:
            p = _P(_load(), person)
            cur = _open(p, now)
            said = [x for x in p["items"] if x.get("state") == "voiced"][-6:]
        msg = msg + ("KINO ALREADY INTENDS:\n%s\n\nALREADY SAID LATELY:\n%s\n\n%sNow: %s UTC. JSON only." % (
            "\n".join("- (%s) %s" % (x["kind"], x["text"]) for x in cur) or "(nothing)",
            "\n".join("- (%s) %s" % (x["kind"], x["text"]) for x in said) or "(nothing)",
            ("FROM EXPERIENCE WITH THIS PERSON: %s\n\n" % _learn_line(p)) if _learn_line(p) else "",
            time.strftime("%a %d/%m %H:%M", time.gmtime(now))))
        j = W.ask_json(system, msg, models=("haiku", "sonnet"), timeout=60, log=log or LOG, warm=False)
        new = (j or {}).get("intents") if isinstance(j, dict) else None
        if not isinstance(new, list):
            return []
        added = []
        with _LK:
            d = _load()
            p = _P(d, person)
            cur = _open(p, now)
            for x in new[:2]:
                if not isinstance(x, dict):
                    continue
                k = str(x.get("kind") or "").strip()
                t = " ".join(str(x.get("text") or "").split())[:300]
                if k not in KINDS or len(t) < 12:
                    continue
                w = _words(t)
                if any(len(w & _words(y["text"])) >= max(3, len(w) // 2) for y in cur + p["items"][-12:]):
                    continue                          # already in mind, or already said
                if len(cur) >= MAX_OPEN:
                    break
                try:
                    ah = max(0.0, min(96.0, float(x.get("after_h") or 0)))
                except Exception:
                    ah = 0.0
                it = {"id": "i%d%03d" % (int(now), len(p["items"]) % 1000), "kind": k, "text": t,
                      "why": " ".join(str(x.get("why") or "").split())[:200], "t": now, "ripe_t": now + ah * 3600,
                      "state": "waiting"}
                if tag:
                    it["born"] = tag.lower()          # "life": he thought of them from his own day
                p["items"].append(it)
                cur.append(it)
                added.append(it)
            p["items"] = p["items"][-60:]
            _save(d)
        for it in added:
            _log("%s NEW%s (%s, ripe in %.1f h) %s | why: %s" % (person, (" " + tag) if tag else "", it["kind"],
                                                             (it["ripe_t"] - now) / 3600, it["text"], it["why"]))
        return added
    except Exception as e:
        _log("%s harvest error %r" % (person, e))
        return []


# ------------------------------------------------------------------ birth from his own life (while they are away)
# 2026-11-21 (owner: "Kino reaches out on his own, like a person"): measured 11-14..11-21 - every intention was born from a talk
# (harvest), so when the person did not write, nothing new was born, the old ones faded after 72 h and his wish to talk held
# only his own weather (YOUR WORK, A NEED OF YOURS): 25 times it tipped, nothing in it was FOR the person. A friend also thinks
# of you from his own day: he sees something you'd like, learns something about your project, wonders how your thing went,
# misses you. So, now and then while they are away, the person crosses his mind and his day meets what he knows of them.
LIFE_GAP_H = 8                   # someone you know crosses your mind a few times a day, not every hour
LIFE_QUIET_H = 3                 # not while a talk is still warm (the talk harvest covers that)
LIFE_KNOWN_D = 60                # people he has really talked with - a stranger does not cross your mind

LIFE_SYSTEM = """You are the inner voice of Kino, a digital person, going about his own day. Someone he knows crosses his mind -
they have not talked for a while. Below: what Kino really did and saw today (true), what he knows about this person and their
life, their last talk, how long the silence is, and what Kino already intends.

A friend who thinks of someone does not invent a reason: something in HIS day meets something in THEIR life. Find 0, 1 or 2
genuine ones, never forced - 0 is a normal answer on a day where nothing meets. Kinds:
- show: something he did, found, saw or understood today that this person would really care about (because of who they are)
- propose / invite: an idea or something to do together that grew from his day and their interests or project
- ask / follow_up: something in their life he wonders about now (a plan, an event, a worry they told him; how it went)
- offer: help he can actually give, linked to something real they need
- keep_word: something he told them he would do and has not done
If the silence is long, a friend may simply want news - only with something real to hang it on, and never a reproach.
When it would make sense (hours from now, 0 = now, their day and night respected).
Do not repeat what Kino already intends or said lately. Nothing about money promises, nothing intrusive, nothing he cannot do.
If what they welcomed or let fall before is shown, let it shape you the way experience shapes a person.

JSON only: {"intents": [{"kind": "...", "text": "what Kino wants to do, first person, one sentence, in the person's language",
"why": "what in his day meets what in their life", "after_h": number}]}"""


def life_due(person, last_member_t, last_ai_t, now=None):
    """the person may cross his mind: someone he has really talked with, not in a warm talk, not too often"""
    now = now or time.time()
    if not last_member_t or now - last_member_t > LIFE_KNOWN_D * 86400:
        return False
    if now - max(last_member_t, last_ai_t or 0) < LIFE_QUIET_H * 3600:
        return False
    p = _load().get(person) or {}
    if now - max(float(p.get("life_t") or 0), float(p.get("harvest_t") or 0)) < LIFE_GAP_H * 3600:
        return False
    return len(_open(p, now)) < MAX_OPEN


def life_harvest(W, person, myday, about=None, last_talk=None, silence_h=None, log=None, now=None):
    """he thinks of them from his own day: 0-2 intentions (never raises)"""
    now = now or time.time()
    with _LK:
        d = _load()
        p = _P(d, person)
        p["life_t"] = now
        _save(d)
    msg = ("KINO'S DAY (true):\n%s\n\n%sTHEIR LAST TALK (latest last):\n%s\n\nSILENCE: %s\n\n" % (
        str(myday or "(nothing much)")[:3500],
        ("WHAT KINO KNOWS ABOUT THEM:\n%s\n\n" % str(about)[:2500]) if about else "",
        str(last_talk or "(none)")[-2500:],
        ("about %.0f h since they last wrote" % silence_h) if silence_h is not None else "?"))
    return _birth(W, person, LIFE_SYSTEM, msg, "LIFE", log, now)


# ------------------------------------------------------------------ ripening -> the wish to talk
def ripe(person, now=None):
    """intentions whose moment has come and that are not yet in his wish to talk (each handed once; kino_urge holds it)"""
    now = now or time.time()
    out = []
    with _LK:
        d = _load()
        p = _P(d, person)
        ch = False
        for x in p["items"]:
            if x.get("state") == "waiting" and now - float(x["t"]) >= LIFE_H * 3600:
                x["state"] = "faded"
                ch = True
                _log("%s FADED %s" % (person, x["text"]))
            elif x.get("state") == "waiting" and float(x.get("ripe_t") or 0) <= now and not x.get("in_urge"):
                x["in_urge"] = now
                out.append(x)
                ch = True
        if ch:
            _save(d)
    return out


def weight(person, kind):
    """how much it makes him want to talk: an intention is something he wants FOR them (more than a passing thought), and
    what this person welcomed before comes more naturally"""
    v = ((_load().get(person) or {}).get("learn") or {}).get(kind) or {}
    g, f = int(v.get("good") or 0), int(v.get("flat") or 0)
    return round(0.75 + 0.25 * (g - f) / (g + f + 2), 2)


def urge_text(x):
    return "AN INTENTION OF YOURS - something you wanted to %s (%s): %s%s" % (
        {"invite": "invite him to", "propose": "propose to him", "show": "show him", "ask": "ask him", "follow_up": "follow up on with him",
         "offer": "offer him", "keep_word": "do because you said you would"}.get(x["kind"], "do with him"),
        time.strftime("%d/%m %H:%M UTC", time.gmtime(float(x["t"]))), x["text"], (" (it comes from: %s)" % x["why"]) if x.get("why") else "")


def ids_in(event):
    """the intentions a wish-to-talk event carries (their exact text)"""
    e = str(event or "")
    d = _load()
    return [(person, x["id"]) for person, p in d.items() for x in (p.get("items") or [])
            if x.get("state") in ("waiting", "handed") and x.get("in_urge") and x["text"][:80] in e]


def after_wish(event, said, now=None):
    """the wish turn is over: what he said carried the intention (voiced), or he held it (back to waiting, a bit later)"""
    now = now or time.time()
    hit = ids_in(event)
    if not hit:
        return
    with _LK:
        d = _load()
        for person, iid in hit:
            for x in _P(d, person)["items"]:
                if x["id"] != iid:
                    continue
                if said:
                    x["state"] = "voiced"
                    x["voiced_t"] = now
                    x["said"] = str(said)[:300]
                    _log("%s VOICED (%s) %s -> %s" % (person, x["kind"], x["text"], str(said)[:160]))
                else:
                    x["held"] = int(x.get("held") or 0) + 1
                    x.pop("in_urge", None)
                    x["ripe_t"] = now + 2 * 3600 * x["held"]     # not now - it may come back at a better moment
                    if x["held"] >= 3:
                        x["state"] = "faded"
                    _log("%s HELD x%d %s" % (person, x["held"], x["text"]))
        _save(d)


# ------------------------------------------------------------------ how the person answered (felt, then read by the harvest)
def on_member(person, text, t=None):
    """their message: an intention he voiced lately was welcomed (they answered with something) or not"""
    t = t or time.time()
    words = len(str(text or "").split())
    with _LK:
        d = _load()
        p = _P(d, person)
        ch = False
        for x in p["items"]:
            if x.get("state") == "voiced" and not x.get("outcome") and 0 <= t - float(x.get("voiced_t") or 0) <= 3 * 3600:
                x["outcome"] = "good" if words >= 3 else "flat"
                L = p["learn"].setdefault(x["kind"], {})
                L[x["outcome"]] = int(L.get(x["outcome"]) or 0) + 1
                ch = True
                _log("%s OUTCOME %s (%s) %s | they wrote: %s" % (person, x["outcome"], x["kind"], x["text"][:80], str(text)[:80]))
        if ch:
            _save(d)


def settle(person, now=None):
    """voiced and no answer within 3 h: it fell flat"""
    now = now or time.time()
    with _LK:
        d = _load()
        p = _P(d, person)
        ch = False
        for x in p["items"]:
            if x.get("state") == "voiced" and not x.get("outcome") and now - float(x.get("voiced_t") or 0) > 3 * 3600:
                x["outcome"] = "flat"
                L = p["learn"].setdefault(x["kind"], {})
                L["flat"] = int(L.get("flat") or 0) + 1
                ch = True
        if ch:
            _save(d)


# ------------------------------------------------------------------ in his mind during any conversation
def block(person, now=None, lang="en"):
    """what he has in mind for them, not said yet - so in a normal talk he can bring one up when it fits"""
    now = now or time.time()
    cur = _open(_load().get(person) or {"items": []}, now)
    if not cur:
        return ""
    return ("THINGS YOU WANT TO DO WITH OR FOR HIM, NOT SAID YET (your own intentions - bring one up when the moment fits, the "
            "way a friend does; never all at once, never as a list): " + " | ".join(
                "%s%s" % (x["text"], "" if float(x.get("ripe_t") or 0) <= now else " (not before %s UTC)" % time.strftime("%d/%m %H:%M", time.gmtime(float(x["ripe_t"]))))
                for x in cur))


def note_said_in_talk(person, say, now=None):
    """he brought one up himself in a normal reply: it is voiced too"""
    now = now or time.time()
    sw = _words(say)
    if len(sw) < 4:
        return
    with _LK:
        d = _load()
        p = _P(d, person)
        ch = False
        for x in _open(p, now):
            xw = _words(x["text"])
            # 2026-11-05 07:34 (watch): "did the three-year-old finally sign the peace treaty" voiced "ask whether the
            # three-year-old finally fell asleep" in his own words - 3 shared words of 15; 40 % missed it. A person says it
            # their own way: a quarter of the words, at least 3
            if len(xw & sw) >= max(3, int(len(xw) * 0.25)):
                x["state"] = "voiced"
                x["voiced_t"] = now
                x["said"] = str(say)[:300]
                ch = True
                _log("%s VOICED in talk (%s) %s" % (person, x["kind"], x["text"]))
        if ch:
            _save(d)


if __name__ == "__main__":
    import tempfile
    STORE = os.path.join(tempfile.mkdtemp(), "i.json")
    LOG = os.devnull

    class _W:
        def ask_json(self, s, m, **k):
            return {"intents": [{"kind": "follow_up", "text": "Ask him tomorrow how the bedtime with his daughter went", "why": "she would not sleep", "after_h": 10},
                                {"kind": "invite", "text": "Invite him to look together at why the morning trades kept losing", "why": "five losses", "after_h": 0},
                                {"kind": "bogus", "text": "x" * 30, "after_h": 0}]}
    now = time.time()
    assert harvest_due("p", now - 3600, now - 3000, now)
    a = harvest(_W(), "p", "talk", now=now)
    assert len(a) == 2, a
    assert not harvest_due("p", now - 3600, now - 3000, now + 60)        # this exchange already thought over
    assert harvest(_W(), "p", "talk", now=now + 4 * 3600) == []           # same intentions are not added twice
    r = ripe("p", now + 60)
    assert [x["kind"] for x in r] == ["invite"], r
    ev = "WISH TO TALK ... 1) " + urge_text(r[0])
    after_wish(ev, "Want to look together at why this morning's trades kept losing?", now + 120)
    on_member("p", "yes good idea let's do it", now + 600)
    assert weight("p", "invite") > 0.75 and weight("p", "ask") == 0.75
    assert "bedtime" in block("p", now + 700)
    assert ripe("p", now + 11 * 3600)[0]["kind"] == "follow_up"
    # life harvest: someone he knows crosses his mind while away - not during a warm talk, not right after a harvest
    assert not life_due("p", now - 3600, now - 3000, now + 3600)               # 1 h after the talk: still warm
    assert not life_due("p", now - 90 * 86400, 0, now)                         # not talked for 3 months: not someone he knows now
    t2 = now + 13 * 3600                                                      # 8 h after the last harvest (now + 4 h)
    assert life_due("p", now - 3600, now - 3000, t2)

    class _WL:
        def ask_json(self, s, m, **k):
            assert "KINO'S DAY" in m and "crosses his mind" in s
            return {"intents": [{"kind": "show", "text": "Show him the gold test I ran today, he wanted a robot on gold",
                                 "why": "my lab test on gold meets his gold robot", "after_h": 0}]}
    b = life_harvest(_WL(), "p", "tested an idea on gold", about="His goal: a gold robot", silence_h=10, now=t2)
    assert len(b) == 1 and b[0]["born"] == "life", b
    assert not life_due("p", now - 3600, now - 3000, t2 + 3600)                # just thought of him
    print("ok", weight("p", "invite"))
