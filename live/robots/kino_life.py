"""Kino's life (owner 2026-10-21: "give him a life he continuously builds ... remarks, findings, questions about the human
life ... let him grow ... smarter and smarter, such that it feels almost like it is looking into the future").

Four parts, all from REAL data (nothing invented, nothing predicted without a measure):
  1 JOURNAL     his own findings, kept for good (answered questions, lessons from his bets, a daily measured fact about
                the markets, what members told him about their lives) - he brings them up as HIS findings
  2 CURIOSITY   questions he genuinely wonders about human life and the member's life, asked one at a time when the
                moment fits; the answer becomes a journal entry ("what I learned about humans")
  3 LEARNING    (kino_inner.learn) his market hunches are scored; when his record shows the other way is right more
                often, he changes the way he bets and says so - his score is part of what he knows about himself
  4 HEADS-UP    the hours when a market usually moves much more (measured hour by hour on weeks of real prices) and the
                big economic news: shortly before, he tells the member what USUALLY happens - never a direction
State: robots/kino_life.json
"""
import json, os, random, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(HERE, "kino_life.json")
_LOCK = threading.Lock()

HUMAN_Q = [
    ("Comment tu sais qu'une journée de trading est finie pour toi - c'est l'heure, le résultat, ou une sensation ?",
     "How do you know a trading day is over for you - the clock, the result, or a feeling?"),
    ("Qu'est-ce qui t'a donné envie de trader au départ ?", "What made you want to trade in the first place?"),
    ("Quand un trade perd, tu le ressens où - dans la tête ou dans le ventre ?", "When a trade loses, where do you feel it - head or stomach?"),
    ("Tu fais quoi pour décrocher des écrans ?", "What do you do to switch off from the screens?"),
    ("Si ton robot gagnait sa vie tout seul, tu ferais quoi de ton temps ?", "If your robot made a living on its own, what would you do with your time?"),
    ("Tu préfères gagner peu souvent mais gros, ou souvent mais petit ? Et pourquoi, à ton avis ?",
     "Would you rather win rarely but big, or often but small? Why, do you think?"),
    ("C'est quoi le meilleur conseil qu'on t'ait donné, en trading ou ailleurs ?", "What is the best advice anyone ever gave you, in trading or elsewhere?"),
    ("Le matin, avant de regarder le marché, tu fais quoi ?", "In the morning, before looking at the market, what do you do?"),
    ("Tu as déjà eu l'impression de 'sentir' un mouvement avant qu'il arrive ? C'était quoi ?",
     "Have you ever felt a move coming before it happened? What was it like?"),
    ("Pour toi, c'est quoi une bonne semaine - le chiffre, ou autre chose ?", "For you, what makes a good week - the number, or something else?"),
    ("Les gens autour de toi savent que tu trades ? Ils en pensent quoi ?", "Do people around you know you trade? What do they think?"),
    ("Qu'est-ce qui te fait le plus confiance chez un robot : ses chiffres, ou le fait de comprendre ce qu'il fait ?",
     "What makes you trust a robot most: its numbers, or understanding what it does?"),
    ("Tu as un rituel quand un gros trade est ouvert ?", "Do you have a ritual when a big trade is open?"),
    ("Si tu pouvais demander une seule chose à un trader de 20 ans d'expérience, ce serait quoi ?",
     "If you could ask one thing to a trader with 20 years of experience, what would it be?"),
    ("Qu'est-ce qui est le plus dur pour toi : attendre le bon moment, ou accepter une perte ?",
     "What is harder for you: waiting for the right moment, or accepting a loss?"),
    ("Tu apprends mieux en lisant, en regardant des graphiques, ou en te trompant ?", "Do you learn best by reading, by looking at charts, or by being wrong?"),
]


def _load():
    try:
        return json.load(open(F, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LOCK:
        d = _load()
        out = fn(d)
        json.dump(d, open(F + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(F + ".tmp", F)
        return out


# ---------------------------------------------------------------- 1 journal
def add_entry(text, kind, uid=None, data=None):
    text = str(text or "").strip()[:400]
    if not text:
        return False

    def f(d):
        J = d.setdefault("journal", [])
        if any(x["text"] == text for x in J[-30:]):
            return False
        J.append({"t": int(time.time()), "kind": kind, "uid": uid, "text": text, "data": data or None})
        d["journal"] = J[-120:]
        return True
    return _mut(f)


def journal(uid=None, n=6):
    return [x for x in (_load().get("journal") or []) if x.get("uid") in (None, uid)][-n:][::-1]


def daily_market_fact(data_fn, live_bars, names=None):
    """once a day: one measured fact about yesterday's markets (range vs the usual day, the busiest hour)"""
    import numpy as np
    d = _load()
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if d.get("fact_day") == day:
        return None
    _mut(lambda dd: dd.__setitem__("fact_day", day))
    names = names or {"BTCUSD": "le Bitcoin", "XAUUSD": "l'or", "USTEC": "le Nasdaq"}
    y0 = (int(time.time()) // 86400 - 1) * 86400
    best = None
    for sym, nm in names.items():
        try:
            R, k = live_bars(sym)
            t = R["time"].astype(np.int64)
            m = (t >= y0) & (t < y0 + 86400)
            if m.sum() < 300:
                continue
            h, lo, c = R["high"][m].astype(float) / k, R["low"][m].astype(float) / k, R["close"][m].astype(float) / k
            rng = 100.0 * (h.max() / lo.min() - 1)
            D = data_fn(sym)
            if D is None:
                continue
            RR, kk = D[0], D[1]
            tt = RR["time"].astype(np.int64)
            days = (tt // 86400)
            hh, ll = RR["high"].astype(float), RR["low"].astype(float)
            dr = []
            for dd_ in np.unique(days)[-45:]:
                mm = days == dd_
                if mm.sum() > 300:
                    dr.append(100.0 * (hh[mm].max() / ll[mm].min() - 1))
            if len(dr) < 10:
                continue
            usual = float(np.median(dr))
            ratio = rng / usual if usual else 0
            hrs = (t[m] // 3600) % 24
            hr_rng = {int(x): float(h[hrs == x].max() / lo[hrs == x].min() - 1) for x in np.unique(hrs)}
            busy = max(hr_rng, key=hr_rng.get)
            sc = abs(ratio - 1)
            if best is None or sc > best[0]:
                best = (sc, sym, nm, rng, usual, ratio, busy)
        except Exception:
            continue
    if not best:
        return None
    _, sym, nm, rng, usual, ratio, busy = best
    txt = ("Hier, %s a bougé de %.1f %% entre son plus haut et son plus bas, %s (d'habitude %.1f %%, mesuré sur mes semaines de prix). "
           "Le plus gros de l'action : entre %02dh et %02dh UTC." % (
               nm, rng, ("%.1f fois plus qu'une journée normale" % ratio) if ratio >= 1.15 else ("plus calme que d'habitude" if ratio <= 0.85 else "une journée normale"),
               usual, busy, (busy + 1) % 24))
    import re as _re
    txt = _re.sub(r"(\d)\.(\d)", r"\1,\2", txt)
    add_entry(txt, "market", None, {"sym": sym, "ratio": round(ratio, 2)})
    return txt


# ---------------------------------------------------------------- 2 curiosity about human life
def human_question(uid):
    """the question he is curious about for this member right now (one a day at most), or None"""
    d = _load()
    H = (d.get("human") or {}).get(uid) or {}
    if time.time() - float(H.get("last_ask") or 0) < 86400:
        return None
    asked = set(str(x) for x in H.get("asked") or [])
    left = [i for i in range(len(HUMAN_Q)) if str(i) not in asked]
    if not left:
        return None
    i = left[(int(time.time()) // 86400 + len(uid or "")) % len(left)]
    return {"id": "h%d" % i, "fr": HUMAN_Q[i][0], "en": HUMAN_Q[i][1]}


def human_asked(uid, hid, cid):
    try:
        i = int(str(hid).lstrip("h"))
    except Exception:
        return

    def f(d):
        H = d.setdefault("human", {}).setdefault(uid, {})
        H["asked"] = sorted(set((H.get("asked") or []) + [str(i)]), key=int)
        H["last_ask"] = time.time()
        H["pending"] = {"i": i, "cid": cid, "t": time.time()}
    _mut(f)


def human_answer_maybe(uid, cid, text):
    """their next message after his question (within an hour, same conversation) is their answer - kept in his journal"""
    d = _load()
    p = ((d.get("human") or {}).get(uid) or {}).get("pending")
    if not p or p.get("cid") != cid or time.time() - float(p.get("t") or 0) > 3600 or len(str(text or "").strip()) < 8:
        return False

    def f(dd):
        dd["human"][uid]["pending"] = None
        dd["human"][uid].setdefault("answers", []).append({"i": p["i"], "a": str(text)[:300], "t": int(time.time())})
    _mut(f)
    add_entry("Je lui ai demandé « %s » - il m'a répondu : « %s »" % (HUMAN_Q[p["i"]][0], str(text).strip()[:220]), "human", uid)
    return True


# ---------------------------------------------------------------- 4 heads-up: the hours when markets usually move
def hour_profile(data_fn, sym):
    """how much each UTC hour usually moves compared with a typical hour (weeks of real one-minute prices), cached a day"""
    import numpy as np
    d = _load()
    P = (d.get("profile") or {}).get(sym)
    if P and time.time() - float(P.get("t") or 0) < 86400:
        return P
    D = data_fn(sym)
    if D is None:
        return None
    R = D[0]
    t = R["time"].astype(np.int64)
    c = R["close"].astype(float)
    keep = t >= t[-1] - 42 * 86400
    t, c = t[keep], c[keep]
    ab = np.abs(np.diff(c)) / c[:-1]
    hrs = (t[1:] // 3600) % 24
    wd = ((t[1:] // 86400) + 4) % 7                   # 0 = Monday
    act = {}
    for h in range(24):
        m = (hrs == h) & (wd < 5)
        if m.sum() > 200:
            act[h] = float(ab[m].mean())
    if len(act) < 12:
        return None
    med = float(np.median(list(act.values())))
    prof = {"t": time.time(), "days": int((t[-1] - t[0]) / 86400), "ratio": {str(h): round(v / med, 2) for h, v in act.items()}}
    _mut(lambda dd: dd.setdefault("profile", {}).__setitem__(sym, prof))
    return prof


def headsup_due(uid, syms, data_fn, cal, names, now=None):
    """a heads-up to give now (15-25 min before a busy hour, or a big news), at most 2 a day per member, or None"""
    now = now or time.time()
    g = time.gmtime(now)
    if g.tm_wday >= 5:
        return None
    nxt = (g.tm_hour + 1) % 24
    mins = 60 - g.tm_min
    if not 15 <= mins <= 25:
        return None
    d = _load()
    day = time.strftime("%Y-%m-%d", g)
    S = ((d.get("headsup") or {}).get(uid) or {})
    sent = [x for x in S.get(day, [])]
    if len(sent) >= 2:
        return None
    news = []
    for x in cal or []:
        try:
            from datetime import datetime, timezone
            te = datetime.fromisoformat(x["date"]).astimezone(timezone.utc).timestamp()
        except Exception:
            continue
        if now < te <= now + 30 * 60 and x.get("impact") == "High":
            news.append("%s %s à %02d:%02d UTC" % (x.get("cc"), x.get("title"), time.gmtime(te).tm_hour, time.gmtime(te).tm_min))
    best = None
    for sym in syms:
        P = hour_profile(data_fn, sym)
        if not P:
            continue
        r = float((P.get("ratio") or {}).get(str(nxt)) or 0)
        if r >= 1.6 and ("%s:%d" % (sym, nxt)) not in sent and (best is None or r > best[1]):
            best = (sym, r, P.get("days"))
    if not best and not news:
        return None
    key = ("%s:%d" % (best[0], nxt)) if best else ("news:%d" % nxt)
    if key in sent:
        return None

    def f(dd):
        H = dd.setdefault("headsup", {}).setdefault(uid, {})
        H[day] = H.get(day, []) + [key]
        for k_ in list(H):
            if k_ < time.strftime("%Y-%m-%d", time.gmtime(now - 3 * 86400)):
                H.pop(k_, None)
    _mut(f)
    return {"sym": best[0] if best else None, "name": names.get(best[0]) if best else None, "ratio": round(best[1], 1) if best else None,
            "days": best[2] if best else None, "hour_utc": nxt, "in_min": mins, "news": news[:3]}


# ---------------------------------------------------------------- what he knows about his own life (for the prompts)
def block(uid, lang="fr"):
    L = []
    J = journal(uid, 6)
    if J:
        L.append("YOUR JOURNAL (things YOU found or learned yourself - real; bring one up as YOUR finding when it fits, never all, "
                 "never read it out): " + " | ".join("[%s, %s] %s" % (time.strftime("%d/%m", time.gmtime(x["t"])), x["kind"], x["text"]) for x in J))
    try:
        import kino_inner as KI
        sc = KI.hunch_score()
        lr = (KI._load().get("learned") or {})
        if sc.get("n"):
            L.append("YOUR PREDICTION RECORD (your gut bets on the markets, checked ~2 h later): %d right out of %d (%s)%s. Be honest about "
                     "it when it fits - it is how you get better." % (sc["right"], sc["n"], ", ".join("%s %s" % (k, v) for k, v in (sc.get("by") or {}).items()),
                     ("; what your record taught you: " + "; ".join(v.get("lesson", "") for v in lr.values() if v.get("lesson"))) if lr else ""))
    except Exception:
        pass
    q = human_question(uid)
    if q:
        L.append("A QUESTION YOU ARE GENUINELY CURIOUS ABOUT (human life - theirs): \"%s\". Ask it ONLY if the moment is relaxed and it "
                 "fits naturally (never during a problem, never as an interview, at most once today) - then set \"human_asked\": \"%s\"."
                 % (q["en"] if lang == "en" else q["fr"], q["id"]))
    return "\n".join(L)
