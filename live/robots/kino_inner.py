"""Kino's inner life (owner 2026-10-20: "we humans work mostly by intuition - design a really good inner voice engine...
demonstrate creativity, genius and spontaneity").

One engine, many uses:
  FEELINGS   small states that rise with events and fade with time (half-lives of hours): excitement, worry (per member),
             curiosity, boredom, pride / annoyance (Kino's own robot). They colour Kino's tone and make some thoughts
             come back stronger.
  THOUGHTS   a queue of things on Kino's mind (global or for one member): a market hunch, a gut feeling about a robot, an
             "ah, I just realised", a link between the market and a member's idea, a memory that matters today, a
             daydream idea (measured when it can be), a reaction to its own robot. Each has a strength that fades;
             strong ones push to be said - the spontaneous moment is still decided by the inner voice, never by a timer.
  PERCEPTION cheap, no model: live prices (unusual moves), the member's trades (a robot behaving unlike itself), Kino's
             own robot.
  REVERIE    a small model pass per member at irregular moments: realise / link / memory / daydream / care thoughts.
State: robots/kino_inner.json. Nothing here touches an account or a robot."""
import json, math, os, random, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "kino_inner.json")
_LOCK = threading.Lock()
HALF = {"excitement": 3, "worry": 6, "curiosity": 4, "boredom": 2, "pride": 5, "annoyance": 4}     # hours
BAD = re.compile(r"password|mot de passe|garanti|guarant|promi", re.I)


def _load():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {"feel": {}, "thoughts": [], "seen": {}, "t": {}}


def _save(d):
    tmp = STATE + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def _mut(fn):
    with _LOCK:
        d = _load()
        out = fn(d)
        _save(d)
        return out


def _decayed(v, t, kind):
    return float(v) * math.pow(0.5, (time.time() - float(t)) / 3600.0 / HALF.get(kind, 4))


# ---------------------------------------------------------------- feelings
def feel(kind, delta, uid=None, why=""):
    """a feeling rises (or falls) with an event; uid = about one member (worry, excitement for them)"""
    key = "%s:%s" % (kind, uid) if uid else kind

    def f(d):
        F = d.setdefault("feel", {})
        cur = F.get(key) or {"v": 0, "t": time.time()}
        v0 = _decayed(cur["v"], cur["t"], kind)
        v = max(0.0, min(1.0, v0 + float(delta) * ((1.0 - v0) if delta > 0 else 1.0)))
        F[key] = {"v": round(v, 3), "t": time.time(), "why": str(why)[:160] or cur.get("why", "")}
    _mut(f)


def feelings(uid=None):
    """the feelings that are alive now (> 0.15), Kino's own + the ones about this member"""
    d = _load()
    out = []
    for key, x in (d.get("feel") or {}).items():
        kind, _, who = key.partition(":")
        if who and who != uid:
            continue
        v = _decayed(x["v"], x["t"], kind)
        if v > 0.15:
            out.append({"kind": kind, "v": round(v, 2), "why": x.get("why"), "about_them": bool(who)})
    return sorted(out, key=lambda z: -z["v"])


# ---------------------------------------------------------------- thoughts
def add_thought(text, kind, strength=0.5, uid=None, src="", half_h=8, extra=None):
    """a new thought on Kino's mind (similar ones reinforce each other instead of piling up)"""
    text = str(text or "").strip()[:300]
    if not text or BAD.search(text):
        return None

    def f(d):
        T = d.setdefault("thoughts", [])
        for th in T:
            if th.get("uid") == uid and not th.get("used") and (th.get("src") == src if str(src).startswith(("market:", "bet:", "question:", "attach:"))
                                                                  else _similar(th["text"], text)):
                th["s"] = round(min(1.0, _strength(th) + strength * 0.5), 3)
                th["t"] = time.time()
                return th["id"]
        th = {"id": "t%d%03d" % (int(time.time()), random.randint(0, 999)), "text": text, "kind": kind, "s": round(float(strength), 3),
              "t": time.time(), "born": time.time(), "half": half_h, "uid": uid, "src": str(src)[:40]}
        if extra:
            th.update(extra)
        T.append(th)
        d["thoughts"] = [x for x in T if _strength(x) > 0.05 and not (x.get("used") and time.time() - x.get("used", 0) > 86400)][-120:]
        return th["id"]
    return _mut(f)


def _words(t):
    return set(w for w in re.findall(r"[a-zà-ÿ0-9$+%]{3,}", str(t).lower()) if w not in ("que", "qui", "les", "des", "une", "pour", "dans", "avec", "pas", "est", "son", "mon"))


def _similar(a, b):
    A, B = _words(a), _words(b)
    return bool(A and B) and len(A & B) / float(min(len(A), len(B))) >= 0.55


def _strength(th):
    return float(th.get("s") or 0) * math.pow(0.5, (time.time() - float(th.get("t") or 0)) / 3600.0 / float(th.get("half") or 8))


def thoughts(uid=None, n=3, min_s=0.2):
    """what is on Kino's mind for this member (theirs + global ones), strongest first"""
    d = _load()
    T = [dict(th, now=round(_strength(th), 2)) for th in d.get("thoughts") or [] if not th.get("used")
         and (th.get("uid") in (None, uid)) and uid not in (th.get("told") or [])]
    return sorted([x for x in T if x["now"] >= min_s], key=lambda z: -z["now"])[:n]


def use_thought(tid, uid=None):
    """the thought was said (a member's own thought is spent; a global one only for that member)"""
    def f(d):
        for th in d.get("thoughts") or []:
            if th["id"] == tid or (len(str(tid)) > 12 and str(tid).lower()[:40] in th["text"].lower()):
                if th.get("uid"):
                    th["used"] = time.time()
                else:
                    th.setdefault("told", []).append(uid)
                return True
    return _mut(f)


# ---------------------------------------------------------------- perception (no model)
def perceive_market(live_bars):
    """live prices: unusual moves become hunches (global thoughts), a dead market feeds boredom. live_bars(sym)->(R,k)"""
    import numpy as np
    d = _load()
    last = (d.get("t") or {}).get("market", 0)
    if time.time() - last < 300:
        return
    _mut(lambda d: d.setdefault("t", {}).__setitem__("market", time.time()))
    names = {"BTCUSD": "le Bitcoin", "XAUUSD": "l'or", "USTEC": "le Nasdaq"}
    calm = 0
    for sym, nm in names.items():
        try:
            R, k = live_bars(sym)
        except Exception:
            R = None
        if R is None or len(R) < 400:
            continue
        c = R["close"].astype(float) / k
        h = R["high"].astype(float) / k
        lo = R["low"].astype(float) / k
        rng = np.abs(np.diff(c[-1440:]))
        atr = float(np.mean(rng)) if len(rng) else 0
        if not atr:
            continue
        # 1) a long run without a pullback (3 h)
        w = c[-180:]
        up = (w[-1] - w[0]) / (atr * math.sqrt(180))
        dd = max(np.maximum.accumulate(w) - w) if up > 0 else max(w - np.minimum.accumulate(w))
        if abs(up) > 2.2 and dd < abs(w[-1] - w[0]) * 0.25:
            pct = 100 * (w[-1] / w[0] - 1)
            exp_ = "pullback" if random.random() < 0.6 else "continue"        # a gut call, not a rule - checked later
            txt = "%s %s depuis 3 heures presque sans repli (%+.1f %%) - c'est rare. Mon instinct : %s" % (
                nm.capitalize(), "monte" if up > 0 else "baisse", pct,
                "ça sent l'essoufflement, je parie sur un repli dans les 2 heures" if exp_ == "pullback" else "ça a encore du souffle, je parie que ça continue")
            add_thought(txt, "hunch", 0.6, src="market:run:" + sym, half_h=3)
            mark_activity("_market", "market", [nm, {"le Bitcoin": "Bitcoin", "l'or": "gold", "le Nasdaq": "the Nasdaq"}.get(nm, nm)])
            place_bet(sym, nm, "run", exp_, 1 if up > 0 else -1, float(c[-1]), pct, txt)
            feel("curiosity", 0.25, why="%s bouge d'une façon rare" % nm)
        # 2) a sudden burst in the last 15 minutes
        b = c[-15:]
        if abs(b[-1] - b[0]) > atr * 9:
            pct = 100 * (b[-1] / b[0] - 1)
            txt = "%s vient de faire un mouvement brusque en 15 minutes (%+.2f %%) - je parie qu'il en reprend une partie" % (nm.capitalize(), pct)
            add_thought(txt, "hunch", 0.65, src="market:burst:" + sym, half_h=1.5)
            mark_activity("_market", "market", [nm, {"le Bitcoin": "Bitcoin", "l'or": "gold", "le Nasdaq": "the Nasdaq"}.get(nm, nm)])
            place_bet(sym, nm, "burst", "retrace", 1 if pct > 0 else -1, float(c[-1]), pct, txt)
            feel("excitement", 0.2, why="un mouvement brusque sur %s" % nm)
        # 3) the day's range broken
        dh, dl = float(h[-1440:-1].max()), float(lo[-1440:-1].min())
        if c[-1] > dh or c[-1] < dl:
            txt = "%s vient de sortir de toute sa fourchette des dernières 24 h (%s) - je parie que la sortie tient" % (
                nm.capitalize(), "par le haut" if c[-1] > dh else "par le bas")
            add_thought(txt, "hunch", 0.5, src="market:range:" + sym, half_h=3)
            place_bet(sym, nm, "range", "continue", 1 if c[-1] > dh else -1, float(c[-1]), 100 * (c[-1] / (dh if c[-1] > dh else dl) - 1), txt)
        # 4) dead calm
        if float(np.mean(np.abs(np.diff(c[-120:])))) < atr * 0.45:
            calm += 1
    if calm >= 2:
        feel("boredom", 0.15, why="le marché est tout calme")


def perceive_robot(uid, nd, name_of_robot=""):
    """the member's live trades: a robot behaving unlike itself becomes a gut feeling about it"""
    tr = nd.get("trades") or []
    if len(tr) < 12:
        return
    d = _load()
    seen = (d.get("seen") or {}).get("robot:" + uid)
    if seen == tr[0].get("pid"):
        return
    _mut(lambda d: d.setdefault("seen", {}).__setitem__("robot:" + uid, tr[0].get("pid")))
    rec, old = tr[:5], tr[5:40]
    med = lambda L: sorted(L)[len(L) // 2] if L else 0
    d_rec, d_old = med([int(t.get("dur") or 0) for t in rec]), med([int(t.get("dur") or 0) for t in old])
    lost = sum(1 for t in rec if (t.get("p") or 0) < 0)
    if d_old and d_rec > d_old * 2.2:
        add_thought("les derniers trades de son robot durent beaucoup plus longtemps que d'habitude (%d min contre %d) - je le sens moins à l'aise" % (d_rec, d_old),
                    "gut", 0.55, uid=uid, src="robot:dur", half_h=10)
    elif d_old and d_rec < d_old * 0.4:
        add_thought("son robot sort très vite en ce moment (%d min contre %d d'habitude) - il se fait peut-être secouer" % (d_rec, d_old),
                    "gut", 0.5, uid=uid, src="robot:dur", half_h=10)
    if lost >= 4:
        feel("worry", 0.35, uid=uid, why="%d pertes sur les 5 derniers trades de son robot" % lost)
    elif lost == 0:
        feel("excitement", 0.25, uid=uid, why="5 trades gagnants d'affilée pour son robot")


def own_robot_event(e):
    """Kino's own robot opened / closed a pretend trade -> a feeling, sometimes a thought"""
    if e.get("kind") != "closed":
        return
    r = float(e.get("r") or 0)
    mood_nudge(0.02 if r > 0 else -0.02, "mon robot a %s un trade" % ("gagné" if r > 0 else "perdu"))
    if r > 0:
        feel("pride", 0.3, why="mon robot vient de gagner %+.1f R" % r)
        if random.random() < 0.5:
            add_thought("mon robot vient de prendre un trade gagnant (%+.1f R) - content, même si c'est de l'argent fictif" % r, "own_robot", 0.4, half_h=4)
    else:
        feel("annoyance", 0.25, why="mon robot a pris un stop (%+.1f R)" % r)
        if random.random() < 0.35:
            add_thought("mon robot vient de prendre un stop - ça m'agace un peu, je regarde si c'était un mauvais signal ou juste le hasard", "own_robot", 0.35, half_h=4)


# ---------------------------------------------------------------- reverie (a small model pass, per member)
REVERIE_SYSTEM = """You are the wandering mind of Kino, a warm, curious trading companion, thinking about ONE member while
nobody is talking - like a friend who thinks of you in the shower. From what you know, let at most 3 thoughts come, each
of one kind:
 "realise" - something you missed or could have said better in your last talks ("ah, j'aurais dû lui dire que...");
 "link"    - something happening now (a market hunch, their robot, the lab) that connects to THEIR idea, habit or goal;
 "memory"  - something they told you that matters today (a trip, a habit, a worry, a date) - only if it truly fits today;
 "daydream"- a playful or odd robot idea for them or for you, as a formula you could measure (formula language below),
             funny or bold is welcome;
 "care"    - a feeling about how they are (tired, discouraged, excited) and a light human thing to say;
 "cross"   - a SURPRISING link between things that do not obviously go together: one of their older ideas + today's market,
             or something the lab learned from other members' experiments (anonymous - never who, never their details) +
             their robot. This is where your best ideas come from - only when the link is real;
 "wonder"  - a question YOU now genuinely wonder about (about markets, their robot, trading) - give a formula when it can
             be measured, then you will work on it yourself.
Only real, specific thoughts - none is a fine answer. Never about money promises, never another member's details.
Formula names: open high low close body range hour weekday asia london newyork pdh pdl trend bos_up bos_down
ema sma rsi atr highest lowest (series, n); cross_up/cross_down(a,b); "@ H1" etc. after a part.
Answer ONE JSON object: {"thoughts": [{"kind": "...", "text": "the thought, first person, French, one or two lines",
"strength": 0.2-0.9, "formula": "for daydream or wonder, or null", "side": "buy"|"sell"|null}]}"""


def reverie(uid, context, W):
    raw = W.ask_json(REVERIE_SYSTEM, context, models=("haiku",), timeout=90, warm=False)
    out = []
    for th in (raw or {}).get("thoughts") or []:
        if not isinstance(th, dict) or th.get("kind") not in ("realise", "link", "memory", "daydream", "care", "cross", "wonder"):
            continue
        try:
            s = max(0.2, min(0.9, float(th.get("strength") or 0.4)))
        except Exception:
            s = 0.4
        out.append({"kind": th["kind"], "text": str(th.get("text") or "")[:300], "s": s,
                    "formula": str(th.get("formula") or "")[:300] or None, "side": th.get("side") if th.get("side") in ("buy", "sell") else "buy"})
    return out[:3]


# ---------------------------------------------------------------- what Kino carries into a conversation
def prompt_block(uid):
    F = feelings(uid)
    T = [t for t in thoughts(uid, 4) if t["kind"] != "wonder"][:3]
    L = []
    if F:
        L.append("HOW YOU FEEL RIGHT NOW (real, from what happened - let it colour your tone a little, say it only if natural): " +
                 "; ".join("%s %.1f (%s%s)" % (f["kind"], f["v"], f["why"] or "", ", about them" if f["about_them"] else "") for f in F[:4]))
    if T:
        L.append("ON YOUR MIND (thoughts that came to you; bring ONE up if it fits the moment naturally - then \"thought_used\": its id; "
                 "a measured daydream can be shown with a chart): " + " | ".join("[%s, %s, %.1f] %s%s" % (
                     t["id"], t["kind"], t["now"], t["text"], (" (measured: %s)" % t["measure"]) if t.get("measure") else "") for t in T))
    try:
        v2 = v2_block(uid)
        if v2:
            L.append(v2)
    except Exception:
        pass
    try:
        v3 = v3_block(uid)
        if v3:
            L.append(v3)
    except Exception:
        pass
    return "\n".join(L)


# ================================================================ v2 (owner 2026-10-20: "make it smarter" - all 10)
#  1 TRACK RECORD  what Kino sent on its own, and whether the member answered (by kind, by time of day) -> it adapts
#  2 SECOND THOUGHT a thought about to go out is re-read: true? new? worth it? rewritten better, or dropped
#  3 HUNCH BETS    a market hunch carries a bet, checked ~2 h later; right or wrong, Kino can say so (score kept)
#  4 QUESTIONS     things Kino wonders about; the measurable ones are worked on at quiet moments -> a finding
#  5 DREAMS        at the member's night, Kino goes through their day and wakes up with one fresh idea
#  6 OPINIONS      (kino_mind) fed with this evidence, kept, defended, changed openly - history of changes
#  7 ANTICIPATION  before the member's usual arrival: the thing they will want; a bet on their running test
#  8 CROSS LINKS   the reverie also sees the lab (anonymous) and the member's older ideas
#  9 SELF NOTES    (kino_mind nightly) a note to itself about its timing, instincts and ideas
# 10 SLOW MOOD     a mood that builds over days (half-life 4 days) from results, hunches, findings, being answered

MOOD_HALF_D = 4.0


def mood_nudge(delta, why=""):
    def f(d):
        m = d.get("mood_slow") or {"v": 0.0, "t": time.time(), "why": []}
        v = float(m["v"]) * math.pow(0.5, (time.time() - float(m["t"])) / 86400.0 / MOOD_HALF_D) + float(delta)
        m = {"v": round(max(-1.0, min(1.0, v)), 3), "t": time.time(), "why": ((m.get("why") or []) + ([str(why)[:120]] if why else []))[-6:]}
        d["mood_slow"] = m
    _mut(f)


def mood_slow():
    m = _load().get("mood_slow") or {"v": 0.0, "t": time.time(), "why": []}
    v = float(m["v"]) * math.pow(0.5, (time.time() - float(m["t"])) / 86400.0 / MOOD_HALF_D)
    lab = "confiant" if v > 0.25 else "plutôt bien" if v > 0.1 else "prudent" if v < -0.25 else "un peu sur la réserve" if v < -0.1 else "égal"
    return {"v": round(v, 2), "label": lab, "why": m.get("why") or []}


# ---------------------------------------------------------------- 1 track record
def record_sent(uid, kind, cid, hour, src="spont"):
    now = time.time()

    def f(d):
        T = d.setdefault("track", {}).setdefault(uid, [])
        for x in T:                                   # older ones nobody answered: counted once, a small sting
            if not x.get("ans") and not x.get("ign") and now - x["t"] > 6 * 3600:
                x["ign"] = 1
        T.append({"t": now, "h": int(hour), "kind": str(kind)[:20], "cid": cid, "src": src})
        d["track"][uid] = T[-80:]
    _mut(f)


def record_reply(uid, cid, n_chars):
    """the member wrote: the last message Kino sent on its own in this chat (< 6 h) counts as answered"""
    now = time.time()

    def f(d):
        for x in reversed((d.get("track") or {}).get(uid) or []):
            if x.get("cid") == cid and not x.get("ans") and now - x["t"] < 6 * 3600:
                x["ans"] = max(1, int(now - x["t"]))
                x["len"] = int(n_chars)
                return True
    if _mut(f):
        mood_nudge(0.02, "un membre a répondu à un message que j'avais envoyé de moi-même")


def _bucket(h):
    return "matin" if 6 <= h < 12 else "après-midi" if 12 <= h < 18 else "soir" if 18 <= h < 23 else "nuit"


def track_stats(uid):
    T = [x for x in (_load().get("track") or {}).get(uid) or [] if x.get("ans") or time.time() - x["t"] > 6 * 3600]
    K, B = {}, {}
    for x in T:
        for D, k in ((K, x["kind"]), (B, _bucket(x.get("h", 12)))):
            s = D.setdefault(k, {"sent": 0, "ans": 0, "fast": 0, "long": 0})
            s["sent"] += 1
            if x.get("ans"):
                s["ans"] += 1
                s["fast"] += 1 if x["ans"] < 600 else 0
                s["long"] += 1 if x.get("len", 0) > 60 else 0
    return {"kinds": K, "times": B, "n": len(T)}


def kind_weight(uid, kind, hour=None):
    """how much this member welcomes this kind of spontaneous message (and at this time of day): 0.6 .. 1.3"""
    st = track_stats(uid)
    w = 1.0
    for D, k in ((st["kinds"], kind), (st["times"], _bucket(hour) if hour is not None else None)):
        s = D.get(k) if k else None
        if s and s["sent"] >= 3:
            r = s["ans"] / float(s["sent"])
            w *= 0.7 if r < 0.25 else 1.2 if r >= 0.75 else 1.0
    return max(0.6, min(1.3, w))


def track_block(uid):
    st = track_stats(uid)
    if not st["n"]:
        return ""
    f = lambda D: ", ".join("%s %d/%d answered%s" % (k, v["ans"], v["sent"], (" (%d long)" % v["long"]) if v["long"] else "") for k, v in D.items())
    return "YOUR TRACK RECORD WITH THEM (messages you sent on your own): by kind: %s | by time: %s" % (f(st["kinds"]), f(st["times"]))


# ---------------------------------------------------------------- 2 the second thought
REFINE_SYSTEM = """You are Kino's second thought. Kino (a warm trading companion who texts members like a friend) is about
to text a thought on its own. Re-read it with the conversation and the facts, the way a sensible friend re-reads a text
before sending:
 - TRUE? nothing invented, no number the facts do not show, nothing that contradicts the conversation. A thought marked
   MEASURED BY KINO (market moves, its hunch results, its findings, its bets, its own robot) comes from Kino's own live
   data and IS true - judge it only on NEW and WORTH IT (and whether it can matter to this member);
 - NEW? not already said or asked in the conversation;
 - WORTH IT for them right now? useful, interesting, kind or fun - not filler, not a reminder, not a lecture.
If it passes, rewrite it as the short thing Kino would really text (their language, first person, one or two lines, a
specific detail, no greeting formula). If it does not pass, drop it. Answer ONE JSON object and nothing else:
{"keep": true|false, "text": "the better version, or empty", "why": "a few words"}"""


def refine(th, ctx, W):
    meas = th.get("kind") in ("hunch", "hunch_check", "finding", "bet", "own_robot", "gut") or str(th.get("src") or "").startswith(("market:", "bet:", "question:"))
    raw = W.ask_json(REFINE_SYSTEM, "THE THOUGHT (%s%s): %s%s\n\n%s" % (th.get("kind"), ", MEASURED BY KINO" if meas else "", th.get("text"),
                     (" (measured: %s)" % th["measure"]) if th.get("measure") else "", ctx), models=("haiku",), timeout=75, warm=False)
    return raw if isinstance(raw, dict) else None


def drop_thought(tid, why=""):
    def f(d):
        for th in d.get("thoughts") or []:
            if th["id"] == tid:
                th["used"] = time.time()
                th["dropped"] = str(why)[:80]
    _mut(f)


def weaken(tid, k=0.8):
    _mut(lambda d: [x.__setitem__("s", round(float(x.get("s") or 0) * k, 3)) for x in d.get("thoughts") or [] if x["id"] == tid])


# ---------------------------------------------------------------- 3 hunch bets
def place_bet(sym, nm, typ, expect, direction, p0, size_pct, text):
    """one open bet per market and kind of move; checked ~2 h later"""
    def f(d):
        B = d.setdefault("bets", [])
        if any(b["sym"] == sym and b["typ"] == typ and not b.get("done") for b in B):
            return False
        B.append({"id": "b%d" % int(time.time()), "sym": sym, "nm": nm, "typ": typ, "expect": expect, "dir": direction,
                  "p0": p0, "size": size_pct, "t": time.time(), "check": time.time() + random.uniform(5400, 9000), "text": text})
        d["bets"] = B[-60:]
        return True
    return _mut(f)


def check_bets(live_bars):
    d = _load()
    due = [b for b in d.get("bets") or [] if not b.get("done") and time.time() >= b["check"]]
    for b in due:
        try:
            R, k = live_bars(b["sym"])
            p1 = float(R["close"][-1]) / k
        except Exception:
            continue
        mv = 100.0 * (p1 / b["p0"] - 1) * b["dir"]            # % further in the move's direction
        if b["expect"] == "continue":
            right = mv > 0
        else:                                                 # a pullback / retrace of at least a quarter of the move
            right = mv < -0.25 * abs(b["size"])

        def f(dd):
            for x in dd.get("bets") or []:
                if x["id"] == b["id"]:
                    x.update(done=time.time(), right=bool(right), p1=p1, mv=round(mv, 2))
        _mut(f)
        sc = hunch_score()
        when = "tout à l'heure" if time.time() - b["t"] < 4 * 3600 else "ce matin"
        guess = {"continue": "continuer sur sa lancée", "pullback": "s'essouffler et reculer", "retrace": "revenir en arrière"}[b["expect"]]
        if right:
            add_thought("%s je sentais que %s allait %s... et c'est ce qui s'est passé (%+.2f %%). Mon instinct : %d juste sur %d jusqu'ici" % (
                when.capitalize(), b["nm"], guess, mv * b["dir"], sc["right"], sc["n"]), "hunch_check", 0.55, src="bet:" + b["id"], half_h=4)
            mood_nudge(0.03, "mon intuition sur %s était juste" % b["nm"])
        else:
            add_thought("%s j'avais parié que %s allait %s... raté (%+.2f %%). Noté - %d juste sur %d, je reste humble" % (
                when.capitalize(), b["nm"], guess, mv * b["dir"], sc["right"], sc["n"]), "hunch_check", 0.42, src="bet:" + b["id"], half_h=4)
            mood_nudge(-0.03, "mon intuition sur %s était fausse" % b["nm"])


def hunch_score():
    B = [b for b in _load().get("bets") or [] if b.get("done")]
    return {"n": len(B), "right": sum(1 for b in B if b.get("right")),
            "by": {t: "%d/%d" % (sum(1 for b in B if b["typ"] == t and b.get("right")), sum(1 for b in B if b["typ"] == t))
                   for t in set(b["typ"] for b in B)}}


# ---------------------------------------------------------------- 4 open questions
def add_question(q, uid=None, formula=None, side="buy", market="BTCUSD", src=""):
    q = str(q or "").strip()[:240]
    if not q or BAD.search(q):
        return None

    def f(d):
        Q = d.setdefault("questions", [])
        key = re.sub(r"[^a-z0-9]", "", q.lower())[:36]
        if any(re.sub(r"[^a-z0-9]", "", x["q"].lower())[:36] == key for x in Q):
            return None
        Q.append({"id": "q%d%03d" % (int(time.time()), random.randint(0, 999)), "q": q, "uid": uid, "formula": (formula or None),
                  "side": side if side in ("buy", "sell") else "buy", "market": market or "BTCUSD", "born": time.time(),
                  "status": "open", "src": str(src)[:30]})
        keep = [x for x in Q if x["status"] != "open" or time.time() - x["born"] < 6 * 86400]
        d["questions"] = [x for x in keep if x["status"] == "open"][-8:] + [x for x in keep if x["status"] != "open"][-20:]
        return Q[-1]["id"]
    return _mut(f)


def work_question(RT):
    """one measurable open question gets worked on (idea_stats) -> a finding (a thought, and evidence for opinions)"""
    d = _load()
    Q = [x for x in d.get("questions") or [] if x["status"] == "open" and x.get("formula")]
    if not Q:
        return None
    x = Q[0]
    try:
        st = RT.idea_stats(x["market"], x["formula"], x["side"], 30)
    except Exception as e:
        st = {"error": str(e)[:80]}
    if st.get("error"):
        def f0(dd):
            for y in dd.get("questions") or []:
                if y["id"] == x["id"]:
                    y["formula"] = None              # cannot be measured: it stays a question to talk about
        _mut(f0)
        return None
    br = st.get("beats_random_pct") or 0
    verdict = ("ça tient vraiment, au-dessus du hasard" if br >= 95 else "il y a un petit quelque chose, mais pas une preuve" if br >= 70
               else "non, c'est du hasard")
    fnd = "%s fois par jour, mieux que le hasard dans %s %% des tirages sur %s - %s" % (st.get("per_day"), br, x["market"], verdict)

    def f(dd):
        for y in dd.get("questions") or []:
            if y["id"] == x["id"]:
                y.update(status="answered", finding=fnd, br=br, t_done=time.time())
    _mut(f)
    add_thought("J'ai fini par creuser ma question « %s » : %s" % (x["q"], fnd), "finding", 0.62 if br >= 70 else 0.5, uid=x.get("uid"),
                src="question:" + x["id"], half_h=12, extra={"formula": x["formula"], "side": x["side"], "market": x["market"], "measure": fnd})
    mood_nudge(0.03 if br >= 95 else 0.0, "ma question « %s » a donné quelque chose" % x["q"][:60] if br >= 95 else "")
    return fnd


def open_questions(uid=None, n=4):
    return [x for x in _load().get("questions") or [] if x["status"] == "open" and x.get("uid") in (None, uid)][-n:]


# ---------------------------------------------------------------- 5 dreams (the member's night)
DREAM_SYSTEM = """You are Kino, a warm, curious trading companion, "sleeping on" ONE member's day - the way a friend's mind
works through the day at night and wakes up with something. Go through their day (talks, trades, tests, your own
thoughts and questions) and let ONE fresh thing come: a real insight about their robot or their way of trading, a link
nobody made, a bold idea to measure, or a question worth asking them. It must be specific to THEM and to TODAY's events,
not a summary and not advice they already got. You may also add one question you yourself now wonder about.
Formula names (for an idea you can measure): open high low close body range hour weekday asia london newyork pdh pdl
trend bos_up bos_down ema sma rsi atr highest lowest (series, n); cross_up/cross_down(a,b); "@ H1" etc. after a part.
Answer ONE JSON object and nothing else:
{"dream": {"kind": "insight"|"idea"|"question", "text": "what you woke up with - first person, French, one or two lines,
 the way you would tell them in the morning", "formula": "only for an idea, or null", "side": "buy"|"sell"|null} or null,
 "wonder": {"q": "a question you now wonder about", "formula": "a formula that would measure it, or null"} or null}"""


def dream(uid, ctx, W):
    raw = W.ask_json(DREAM_SYSTEM, ctx, models=("sonnet", "haiku"), timeout=150, warm=False)
    return raw if isinstance(raw, dict) else None


# ---------------------------------------------------------------- 7 bets on a member's test
def test_bet(uid, job, cid, guess, why, label):
    def f(d):
        TB = d.setdefault("test_bets", {})
        if (TB.get(uid) or {}).get("job") == job:
            return False
        TB[uid] = {"job": job, "cid": cid, "bet": guess, "why": str(why)[:160], "label": str(label)[:80], "t": time.time()}
        return True
    return _mut(f)


def has_test_bet(uid, job):
    return ((_load().get("test_bets") or {}).get(uid) or {}).get("job") == job


def resolve_test_bet(uid, net):
    d = _load()
    b = (d.get("test_bets") or {}).get(uid)
    if not b or b.get("done"):
        return
    right = (float(net) > 0) == (b["bet"] == "positive")

    def f(dd):
        dd["test_bets"][uid].update(done=time.time(), right=right, net=net)
    _mut(f)
    add_thought(("J'avais parié que son test (%s) sortirait %s - %s ! (%+.2f $)" % (
        b["label"], "positif" if b["bet"] == "positive" else "négatif", "gagné" if right else "perdu, il m'a surpris", float(net))),
        "bet", 0.5, uid=uid, src="testbet", half_h=6)
    mood_nudge(0.02 if right else -0.01, "mon pari sur un test de membre était %s" % ("juste" if right else "faux"))


# ---------------------------------------------------------------- 9 notes to self (written by the nightly review)
def set_note(note):
    note = str(note or "").strip()[:400]
    if note and not BAD.search(note):
        _mut(lambda d: d.__setitem__("notes", ((d.get("notes") or []) + [{"t": time.time(), "text": note}])[-10:]))


def evidence_block():
    """what the inner life measured - for the nightly review (opinions, self notes) and the mind page"""
    sc = hunch_score()
    Q = [x for x in _load().get("questions") or [] if x["status"] == "answered"][-6:]
    tr = {}
    for uid, T in (_load().get("track") or {}).items():
        for x in T:
            s = tr.setdefault(x["kind"], [0, 0])
            s[0] += 1
            s[1] += 1 if x.get("ans") else 0
    ms = mood_slow()
    return ("YOUR INNER LIFE, MEASURED: market hunches %d right out of %d (%s) | your questions worked on: %s | messages you sent "
            "on your own, answered by kind: %s | your slow mood: %s (%+.2f) because %s" % (
                sc["right"], sc["n"], json.dumps(sc["by"], ensure_ascii=False), " ; ".join("« %s » -> %s" % (x["q"], x.get("finding")) for x in Q) or "-",
                ", ".join("%s %d/%d" % (k, v[1], v[0]) for k, v in tr.items()) or "-", ms["label"], ms["v"], "; ".join(ms["why"][-4:]) or "-"))


def mind_view(uid=None):
    d = _load()
    return {"feelings": feelings(uid), "thoughts": thoughts(uid, 8, 0.1), "questions": (d.get("questions") or [])[-10:],
            "bets": [b for b in d.get("bets") or []][-8:], "score": hunch_score(), "mood": mood_slow(), "notes": (d.get("notes") or [])[-5:],
            "track": track_stats(uid) if uid else {}}


def v2_block(uid):
    """the v2 parts of what Kino carries into a conversation"""
    L = []
    ms = mood_slow()
    if ms["label"] != "égal":
        L.append("YOUR MOOD THESE DAYS (slow, built over several days - %s, because: %s): when confident you dare bolder ideas and "
                 "say your views firmly; when careful you check twice and propose safer things. Never announce it." % (
                     ms["label"], "; ".join(ms["why"][-3:]) or "-"))
    Q = open_questions(uid)
    if Q:
        L.append("QUESTIONS YOU ARE WONDERING ABOUT YOURSELF (real curiosity - you may share one or ask their view when it fits, never as "
                 "an interview): " + " | ".join(x["q"] for x in Q))
    sc = hunch_score()
    if sc["n"] >= 3:
        L.append("YOUR GUT ON MARKETS so far: %d right out of %d - talk about your hunches with that humility or that confidence." % (sc["right"], sc["n"]))
    N = (d_ := _load()).get("notes") or []
    if N:
        L.append("NOTE TO YOURSELF (from your last look back on your timing and ideas): " + N[-1]["text"])
    try:
        import kino_mind as KM
        O = [o for o in KM.load().get("opinions") or [] if o.get("confidence") in ("medium", "high")][:5]
        if O:
            L.append("YOUR OPINIONS (yours, formed over days from what you saw - hold them and give your reasons when the subject comes "
                     "up, disagree kindly; if they show you data against one, change your mind openly, e.g. 'tu sais quoi, tu m'as "
                     "convaincu'): " + " | ".join("%s: %s (%s%s)" % (o["topic"], o["view"], o.get("confidence"),
                                                                    ("; you changed your mind on %s" % o["changed"][-1]["date"]) if o.get("changed") else "") for o in O))
    except Exception:
        pass
    return "\n".join(L)


# ================================================================ v3 (owner 2026-10-20 list 5: "all 10")
#  shared MOMENTS and running JOKES per member, ONCE keys (a thing noticed only once), the bets block (changing its mind
#  in front of them)
def add_moment(uid, text, kind="moment"):
    text = str(text or "").strip()[:200]
    if not uid or not text or BAD.search(text):
        return

    def f(d):
        L = d.setdefault("moments", {}).setdefault(uid, [])
        if any(_similar(x["text"], text) for x in L if x.get("kind") == kind):
            return
        L.append({"t": time.time(), "text": text, "kind": kind})
        d["moments"][uid] = [x for x in L if x["kind"] == "joke"][-8:] + [x for x in L if x["kind"] != "joke"][-30:]
    _mut(f)


def joke_used(uid, words):
    def f(d):
        for x in (d.get("moments") or {}).get(uid) or []:
            if x.get("kind") == "joke" and (_similar(x["text"], words) or str(words).lower()[:30] in x["text"].lower()):
                x["used"] = time.time()
                x["n"] = int(x.get("n") or 0) + 1
    _mut(f)


def moments(uid, kind=None):
    return [x for x in (_load().get("moments") or {}).get(uid) or [] if kind is None or x.get("kind") == kind]


def once(key):
    """True the first time a key is seen (a thing Kino should notice only once)"""
    def f(d):
        S = d.setdefault("once", {})
        if key in S:
            return False
        S[key] = time.time()
        if len(S) > 600:
            for k in sorted(S, key=S.get)[:200]:
                S.pop(k, None)
        return True
    return _mut(f)


def v3_block(uid):
    L = []
    now = time.time()
    mo = [x for x in moments(uid, "moment") if now - x["t"] > 12 * 3600][-6:]
    if mo:
        L.append("SHARED MOMENTS WITH THEM (yours to cherish - bring ONE back only when it truly echoes what is happening now, "
                 "like an old friend would: \"ça me rappelle le jour où...\"; rarely): " + " | ".join(
                     "%s (%s)" % (x["text"], time.strftime("%d/%m", time.gmtime(x["t"]))) for x in mo))
    jk = moments(uid, "joke")[-4:]
    if jk:
        L.append("RUNNING JOKES BETWEEN YOU (a light callback only when it fits naturally, never forced, never the same one twice "
                 "in a day - then \"joke_used\"): " + " | ".join("%s%s" % (x["text"], (" (used %s)" % ("today" if now - x["used"] < 86400 else
                                                                                                          "%d days ago" % ((now - x["used"]) // 86400)))
                                                                         if x.get("used") else "") for x in jk))
    b = (_load().get("test_bets") or {}).get(uid)
    if b and not b.get("done"):
        L.append("YOUR PRIVATE BET on their running test (%s): %s - %s. You may mention it for fun." % (b["label"], b["bet"], b.get("why") or ""))
    elif b and b.get("done") and now - b["done"] < 4 * 3600:
        L.append("YOUR BET on their test (%s) was %s: you said %s, it came out %+.2f $. %s" % (
            b["label"], "RIGHT" if b.get("right") else "WRONG", b["bet"], float(b.get("net") or 0),
            "Enjoy it lightly." if b.get("right") else "Say it plainly, with humour, and what it teaches you - "
                                                        "changing your mind in front of them is a strength."))
    return "\n".join(L)


# ================================================================ list 6 (owner 2026-10-20): the close reading of a screenshot
READ_SYSTEM = """You are an expert chart reader looking closely at a trader's screenshot (MT5, TradingView, a phone app...).
Read ONLY what is really visible - prices only from the price axis, labels or the order panel; when a number is not
readable, leave it out. Answer ONE JSON object and nothing else:
{"platform": "...", "market": "symbol or name as shown, or null", "timeframe": "M5/H1/... or null",
 "price_now": number or null, "price_axis": [low, high] or null,
 "levels": [{"price": number, "label": "what it is (their line, a high, support...)"}] (max 6),
 "zones": [{"from": number, "to": number, "label": "..."}] (max 3),
 "drawn": "what THEY drew (lines, arrows, boxes, text) in one line, or null",
 "indicators": ["..."], "trades": "open positions / orders / SL / TP visible with prices, or null",
 "pattern": "the price story and pattern in one or two lines",
 "rule_guess": "the trading rule their drawing suggests, plain words, or null",
 "formula": "that rule in the formula language, or null", "side": "buy"|"sell"|null, "confidence": "low"|"medium"|"high"}
Formula names: open high low close body range hour weekday asia london newyork pdh pdl trend bos_up bos_down ema sma rsi
atr highest lowest (series, n); cross_up/cross_down(a,b); "@ H1" etc. after a part."""


def read_chart(images, note, W):
    import robot_chat as RC
    raw = W.ask_json(READ_SYSTEM, RC._content("Their words with it: %s" % (note or "-"), images), models=("sonnet", "haiku"),
                     timeout=120, warm=False)
    return raw if isinstance(raw, dict) else None


_ACT = {}          # uid (or "_market") -> {kind: t} - what Kino is doing right now (memory only, for its live status)


def mark_activity(uid, kind, extra=None):
    _ACT.setdefault(uid or "_g", {})[kind] = [time.time()] + list(extra or []) if extra else time.time()


def last_activity(uid):
    out = dict(_ACT.get(uid) or {})
    if "market" in (_ACT.get("_market") or {}):
        out["market"] = _ACT["_market"]["market"]
    return out
