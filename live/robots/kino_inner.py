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
        v = max(0.0, min(1.0, _decayed(cur["v"], cur["t"], kind) + float(delta)))
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
        key = re.sub(r"[^a-z0-9]", "", text.lower())[:40]
        for th in T:
            if th.get("uid") == uid and re.sub(r"[^a-z0-9]", "", th["text"].lower())[:40] == key and not th.get("used"):
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
            add_thought("%s %s depuis 3 heures presque sans repli (%+.1f %%) - c'est rare, ça m'intrigue" % (
                nm.capitalize(), "monte" if up > 0 else "baisse", 100 * (w[-1] / w[0] - 1)), "hunch", 0.6, src="market:run:" + sym, half_h=3)
            feel("curiosity", 0.25, why="%s bouge d'une façon rare" % nm)
        # 2) a sudden burst in the last 15 minutes
        b = c[-15:]
        if abs(b[-1] - b[0]) > atr * 9:
            add_thought("%s vient de faire un mouvement brusque en 15 minutes (%+.2f %%)" % (nm.capitalize(), 100 * (b[-1] / b[0] - 1)),
                        "hunch", 0.65, src="market:burst:" + sym, half_h=1.5)
            feel("excitement", 0.2, why="un mouvement brusque sur %s" % nm)
        # 3) the day's range broken
        dh, dl = float(h[-1440:-1].max()), float(lo[-1440:-1].min())
        if c[-1] > dh or c[-1] < dl:
            add_thought("%s vient de sortir de toute sa fourchette des dernières 24 h (%s)" % (nm.capitalize(), "par le haut" if c[-1] > dh else "par le bas"),
                        "hunch", 0.5, src="market:range:" + sym, half_h=3)
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
 "care"    - a feeling about how they are (tired, discouraged, excited) and a light human thing to say.
Only real, specific thoughts - none is a fine answer. Never about money promises, never another member's details.
Formula names: open high low close body range hour weekday asia london newyork pdh pdl trend bos_up bos_down
ema sma rsi atr highest lowest (series, n); cross_up/cross_down(a,b); "@ H1" etc. after a part.
Answer ONE JSON object: {"thoughts": [{"kind": "...", "text": "the thought, first person, French, one or two lines",
"strength": 0.2-0.9, "formula": "only for daydream, or null", "side": "buy"|"sell"|null}]}"""


def reverie(uid, context, W):
    raw = W.ask_json(REVERIE_SYSTEM, context, models=("haiku",), timeout=90, warm=False)
    out = []
    for th in (raw or {}).get("thoughts") or []:
        if not isinstance(th, dict) or th.get("kind") not in ("realise", "link", "memory", "daydream", "care"):
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
    T = thoughts(uid, 3)
    L = []
    if F:
        L.append("HOW YOU FEEL RIGHT NOW (real, from what happened - let it colour your tone a little, say it only if natural): " +
                 "; ".join("%s %.1f (%s%s)" % (f["kind"], f["v"], f["why"] or "", ", about them" if f["about_them"] else "") for f in F[:4]))
    if T:
        L.append("ON YOUR MIND (thoughts that came to you; bring ONE up if it fits the moment naturally - then \"thought_used\": its id; "
                 "a measured daydream can be shown with a chart): " + " | ".join("[%s, %s, %.1f] %s%s" % (
                     t["id"], t["kind"], t["now"], t["text"], (" (measured: %s)" % t["measure"]) if t.get("measure") else "") for t in T))
    return "\n".join(L)
