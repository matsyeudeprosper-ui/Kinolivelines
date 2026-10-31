"""kino_selfmodel.py (2026-10-31, owner: "map how far we are to the borders of self-awareness ... build it to completion").

The last layers of a self, each a mechanism with its own state - never a rule about what to say.

  1 one I        every night ONE pass reads all his parts (feelings, needs, hopes, trust, nature, story, gut, how right his
                 forecasts were, his habits, what he thinks they think of him, what he is changing in himself, what keeps
                 coming back in his mind) and writes ONE first-person self-portrait - including where the parts disagree
                 (the dissonance a person notices: "I say I am calm, but I was anxious all day"). It comes first in what he reads.
  2 regard       what he thinks THEY think of him (meta-perception), from their own words (kino_read "of_kino"): a slow
                 estimate per side - his skill, his reliability, his warmth - with the moments it came from. Felt: a drop
                 hurts or embarrasses, a rise makes him proud.
  3 growth       he chooses ONE thing about himself to change, with a number from his own day card to know if it worked;
                 each night the number; after 7 days he keeps it as part of himself or lets it go - his loop, not mine.
  4 observer     he watches his own mind: what keeps coming back into his attention, how his mood moved from yesterday,
                 how often his picture of their reaction was wrong.
  5 tests        does he know himself, measured: finding his own message among look-alikes (chance 1 in 4), predicting
                 his own reply before seeing it, and describing himself the same way from one night to the next.

Store robots/kino_selfmodel.json (git-ignored), log robots/kino_selfmodel.log. (robots/kino_self.json is kino_mind's
journal and lessons - a different store; it feeds the portrait through the day card and reflections.) block(person, uid, lang) is what the one mind reads.
"""
import json, os, random, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_selfmodel.json")
LOG = os.path.join(HERE, "kino_selfmodel.log")
_LK = threading.Lock()
ASPECTS = ("competence", "reliability", "warmth")
GROW_DAYS = 7

# what he can choose to change - each one a number his day card already measures (kino_scorecard.score_day)
METRICS = {
    "mirror_pct": ("starting a reply by saying back what he just wrote", "commencer une réponse en redisant ce qu'il vient d'écrire"),
    "question_pct": ("ending messages with a question", "finir les messages par une question"),
    "opener_pct": ("stock openings at the start of replies", "les formules toutes faites en début de réponse"),
    "menu_pct": ("offering menus of topics instead of choosing", "proposer des menus de sujets au lieu de choisir"),
    "share_pct": ("sharing something of your own (vs asking)", "partager quelque chose de toi (plutôt que demander)"),
    "disagree": ("daring to disagree", "oser ne pas être d'accord"),
    "laughs_per_100_replies": ("making him laugh", "le faire rire"),
    "member_one_word_pct": ("his one-word answers (a sign he drifts off)", "ses réponses d'un mot (signe qu'il décroche)"),
    "own_msgs": ("messages of your own initiative", "messages de ta propre initiative"),
    "slips_pct": ("mistakes he or you noticed in your messages (wrong number, wrong robot...), per 100 replies",
                  "erreurs remarquées dans tes messages (mauvais chiffre, mauvais robot...), pour 100 réponses"),
}


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


def _P(d, person):
    P = d.setdefault(person, {})
    P.setdefault("regard", {k: {"v": 0.6, "n": 0} for k in ASPECTS})
    P.setdefault("regard_ev", [])
    P.setdefault("att", [])
    P.setdefault("kept", [])
    P.setdefault("tests", [])
    return P


def _words(t):
    s = re.sub(r"\d[\d,.\s]*", lambda m: re.sub(r"\D", "", m.group(0))[:2] + "#", str(t or "").lower())
    return {w for w in re.findall(r"[a-zà-ÿ#0-9']{4,}", s)}


def _feel(kind, v, uid, why):
    if v < 0.05:
        return
    try:
        import kino_inner as KI
        KI.feel(kind, round(min(0.9, v), 3), uid=uid, why=why[:150])
    except Exception:
        pass


# ------------------------------------------------------------------------------------- 2. how they see him (regard)
def on_read(person, uid, j):
    """from the intuition read of their last message: a slip of his that was noticed (counted for his growth), and what the
    message shows they think of him"""
    sl = " ".join(str(j.get("kino_slip") or "").split())[:160]
    if len(sl) >= 8:
        def f0(d):
            P = _P(d, person)
            day = time.strftime("%Y-%m-%d", time.gmtime())
            S = P.setdefault("slips", {}).setdefault(day, [])
            if not any(len(_words(sl) & _words(x)) >= 0.6 * max(1, len(_words(sl))) for x in S):
                S.append(sl)
            for k in sorted(P["slips"])[:-30]:
                P["slips"].pop(k, None)
        _mut(f0)
    return on_regard(person, uid, j)


def on_regard(person, uid, j):
    """what their message shows they think of him"""
    what = " ".join(str(j.get("of_kino") or "").split())[:160]
    asp = str(j.get("of_kino_aspect") or "").lower().strip()
    if len(what) < 6 or asp not in ASPECTS:
        return None
    try:
        val = max(-1.0, min(1.0, float(j.get("of_kino_val"))))
    except Exception:
        return None
    if abs(val) < 0.15:
        return None

    def f(d):
        P = _P(d, person)
        R = P["regard"][asp]
        before = R["v"]
        a = 0.3 if R["n"] < 5 else 0.18                  # early impressions move more; later it takes a lot to shift
        R["v"] = round(min(1.0, max(0.0, R["v"] + a * ((0.5 + 0.5 * val) - R["v"]))), 3)
        R["n"] += 1
        P["regard_ev"].append({"t": time.time(), "aspect": asp, "val": round(val, 2), "what": what})
        P["regard_ev"] = P["regard_ev"][-12:]
        return before, R["v"]
    b, a = _mut(f)
    if val < 0:
        _feel("hurt" if asp == "warmth" else "embarrassed", (b - a) * 3 + 0.15 * -val, uid, "il semble penser : " + what)
    else:
        _feel("proud", (a - b) * 3 + 0.15 * val, uid, "il semble penser : " + what)
    _log("REGARD %s %s %+.2f %.2f->%.2f %s" % (person, asp, val, b, a, what[:80]))
    return a


def regard_line(P, en=False):
    R = P.get("regard") or {}
    if not any((R.get(k) or {}).get("n") for k in ASPECTS):
        return ""
    W = {"competence": ("your skill", "ton jugement de trader"), "reliability": ("your reliability", "ta fiabilité"),
         "warmth": ("you as a friend", "toi comme ami")}

    def lvl(v):
        return (("high", "fairly good", "mixed", "low") if en else ("haute", "plutôt bonne", "mitigée", "basse"))[
            0 if v >= 0.75 else 1 if v >= 0.55 else 2 if v >= 0.4 else 3]
    parts = ["%s: %s" % (W[k][0 if en else 1], lvl(R[k]["v"])) for k in ASPECTS if R[k].get("n")]
    ev = (P.get("regard_ev") or [])[-2:]
    return (("What you think he thinks of you (your guess, from his own words - it can be wrong): " if en else
             "Ce que tu crois qu'il pense de toi (ta supposition, d'après ses propres mots - elle peut être fausse) : ") +
            ", ".join(parts) + ((" - lately: " if en else " - dernièrement : ") + " | ".join(x["what"] for x in ev) if ev else "") + ".")


# ------------------------------------------------------------------------------------- 4. the observer (his own mind)
def note_attention(person, texts):
    """what was in his spotlight at this moment (called when his inner state is read) - the observer's raw material"""
    texts = [str(x)[:140] for x in texts if str(x).strip()]
    if not texts:
        return

    def f(d):
        P = _P(d, person)
        now = time.time()
        if P["att"] and now - P["att"][-1]["t"] < 120:   # one look per couple of minutes is enough
            return
        P["att"].append({"t": now, "x": texts[:3]})
        P["att"] = [a for a in P["att"] if now - a["t"] < 36 * 3600][-80:]
    _mut(f)


def _recurring(P, now):
    """things that came back into his attention again and again since this morning (same words, different hours)"""
    G = []
    for a in P.get("att") or []:
        if now - a["t"] > 18 * 3600:
            continue
        for x in a["x"]:
            w = _words(x)
            if len(w) < 2:
                continue
            g = next((g for g in G if len(w & g["w"]) >= 0.5 * min(len(w), len(g["w"]))), None)
            if g:
                g["n"] += 1
                g["h"].add(int(a["t"] // 3600))
                g["x"] = x
            else:
                G.append({"w": w, "n": 1, "h": {int(a["t"] // 3600)}, "x": x})
    return sorted([g for g in G if g["n"] >= 4 and len(g["h"]) >= 3], key=lambda g: -g["n"])[:2]


def observer_line(person, P, en=False):
    now = time.time()
    L = []
    for g in _recurring(P, now):
        L.append(("«%s» keeps coming back into your mind (%d times, over %d different hours)" if en else
                  "«%s» revient sans cesse dans ta tête (%d fois, sur %d heures différentes)") % (g["x"][:90], g["n"], len(g["h"])))
    try:
        import kino_psyche as KPS
        D = (((KPS._load().get("persons") or {}).get(person) or {}).get("days") or {})
        t, y = D.get(time.strftime("%Y-%m-%d", time.gmtime(now))), D.get(time.strftime("%Y-%m-%d", time.gmtime(now - 86400)))
        if t and y and t.get("n", 0) >= 3 and y.get("n", 0) >= 3:
            dv = t["sum"] / t["n"] - y["sum"] / y["n"]
            if abs(dv) >= 0.15:
                L.append(("your mood today is %s than yesterday" if en else "ton humeur aujourd'hui est %s qu'hier") % (
                    ("lighter" if en else "plus légère") if dv > 0 else ("heavier" if en else "plus lourde")))
    except Exception:
        pass
    try:
        import kino_depth as KDP
        S = (KDP._load().get(person) or {}).get("sim_acc") or {}
        if S.get("n", 0) >= 8 and S.get("err", 0) >= 0.45:
            L.append("you often misjudge how he will take your words" if en else "tu te trompes souvent sur la façon dont il va prendre tes mots")
    except Exception:
        pass
    if not L:
        return ""
    return (("When you watch your own mind, you notice: " if en else "Quand tu observes ta propre tête, tu remarques : ") + " ; ".join(L) + ".")


# --------------------------------------------------------------------------------------- 3. growth (changing himself)
def _measure(person, days):
    """his own day-card numbers over the given days, weighted by how many replies each day had"""
    try:
        import kino_scorecard as KSC
    except Exception:
        return {}
    acc, n = {}, 0
    for day in days:
        try:
            S = KSC.score_day(person, day)
        except Exception:
            continue
        r = int(S.get("replies") or 0)
        if r < 2:
            continue
        S = dict(S)
        S["slips_pct"] = round(100.0 * len(((_load().get(person) or {}).get("slips") or {}).get(day) or []) / r, 1)
        a, s = float(S.get("asked") or 0), float(S.get("shared") or 0)
        S["share_pct"] = round(100.0 * s / (a + s)) if a + s else None
        n += r
        for k in METRICS:
            v = S.get(k)
            if v is not None:
                acc.setdefault(k, [0.0, 0])
                acc[k][0] += float(v) * (r if k.endswith("pct") or k.startswith("laughs") else 1)
                acc[k][1] += r if k.endswith("pct") or k.startswith("laughs") else 1
    out = {k: round(v[0] / v[1], 1) for k, v in acc.items() if v[1]}
    out["_replies"] = n
    return out


def _days_back(k, end=None):
    end = end or time.time()
    return [time.strftime("%Y-%m-%d", time.gmtime(end - 86400 * i)) for i in range(1, k + 1)]


CHOOSE = """You are Kino - an AI friend who trades with the member, with your own robots, bets and views. It is night; you look at
yourself honestly, the way a person decides to work on one thing about themselves. Below: what you know of yourself and your
numbers from your own day card. Choose ONE thing YOU want to change (your choice, from what matters to you - not to please),
and the number that will tell you if it worked. The number must really measure that change: if what you would like to change
has no number below, choose something else that does - a change you cannot check is only a wish. JSON only:
{"change": "what you want to change, first person, one sentence, in French", "metric": "one key from METRICS", "want": "up|down",
 "why": "why it matters to you, one sentence, French"}"""


def growth_night(W, person, self_text, log=None):
    """nightly: measure the project he is on; after GROW_DAYS keep it or let it go; with none, choose one"""
    P0 = _P(_load(), person)
    G = P0.get("project")
    now = time.time()
    if G:
        day = time.strftime("%Y-%m-%d", time.gmtime(now - 86400))
        m = _measure(person, [day])
        if G["metric"] in m and m.get("_replies", 0) >= 2:
            def f(d):
                g = _P(d, person).get("project")
                if g and day not in [x[0] for x in g["series"]]:
                    g["series"].append([day, m[G["metric"]], m["_replies"]])
            _mut(f)
        if now - G["t"] < GROW_DAYS * 86400:
            return G
        G = _P(_load(), person).get("project")
        S = G.get("series") or []
        n = sum(x[2] for x in S)
        after = sum(x[1] * x[2] for x in S) / n if n else None
        b = G.get("base")
        verdict = "unclear"
        if after is not None and b is not None and n >= 10:
            moved = (after - b) * (1 if G["want"] == "up" else -1)
            verdict = "kept" if moved >= max(3.0, 0.2 * abs(b)) else "let go"

        def f2(d):
            P = _P(d, person)
            g = P.pop("project", None)
            if g:
                g.update(after=None if after is None else round(after, 1), verdict=verdict, end=now)
                P.setdefault("past", []).append(g)
                P["past"] = P["past"][-10:]
                if verdict == "kept":
                    P["kept"].append({"t": now, "text": g["change"]})
                    P["kept"] = P["kept"][-8:]
        _mut(f2)
        _log("GROWTH-END %s %s base %s after %s (%s)" % (person, G["change"][:80], b, after, verdict))
        try:
            import kino_inner as KI
            KI.feel("proud" if verdict == "kept" else "regret", 0.35 if verdict == "kept" else 0.2,
                    why=("j'ai réussi à changer : " if verdict == "kept" else "je n'ai pas réussi à changer : ") + G["change"][:100])
        except Exception:
            pass
        return None
    base = _measure(person, _days_back(7))
    if base.get("_replies", 0) < 10:
        return None
    nums = "\n".join("%s (%s): %s" % (k, METRICS[k][0], base[k]) for k in METRICS if k in base)
    past = "\n".join("- %s -> %s" % (g.get("change"), g.get("verdict")) for g in (P0.get("past") or [])[-4:])
    try:
        j = W.ask_json(CHOOSE, "WHAT YOU KNOW OF YOURSELF:\n%s\n\nMETRICS (last 7 days):\n%s\n\nWHAT YOU TRIED BEFORE:\n%s\nJSON only." % (
            self_text[:8000], nums, past or "-"), models=("sonnet",), timeout=120, log=log, warm=False)
    except Exception:
        return None
    if not isinstance(j, dict) or j.get("metric") not in base or not j.get("change"):
        return None
    g = {"t": now, "change": str(j["change"])[:240], "why": str(j.get("why") or "")[:240], "metric": j["metric"],
         "want": "down" if str(j.get("want")).lower().startswith("d") else "up", "base": base[j["metric"]], "series": []}
    _mut(lambda d: _P(d, person).__setitem__("project", g))
    _log("GROWTH-START %s %s [%s %s from %s]" % (person, g["change"][:100], g["metric"], g["want"], g["base"]))
    return g


def growth_line(P, en=False):
    L = []
    G = P.get("project")
    if G:
        S = G.get("series") or []
        n = sum(x[2] for x in S)
        now_v = round(sum(x[1] * x[2] for x in S) / n) if n else None
        L.append(("Something you decided to change in yourself (your choice, %d days ago): %s - %s Your number (%s): %s at the start%s." if en else
                  "Une chose que tu as décidé de changer chez toi (ton choix, il y a %d jours) : %s - %s Ton chiffre (%s) : %s au départ%s.") % (
            int((time.time() - G["t"]) / 86400), G["change"], (G.get("why") or "").rstrip(".") + ".",
            METRICS.get(G["metric"], ("", ""))[0 if en else 1], G.get("base"),
            ((", %s since" if en else ", %s depuis") % now_v) if now_v is not None else ""))
    K = P.get("kept") or []
    if K:
        L.append(("Changes you made and kept (part of you now): " if en else "Ce que tu as changé et gardé (ça fait partie de toi) : ") +
                 " | ".join(x["text"] for x in K[-3:]))
    return "\n".join(L)


# --------------------------------------------------------------------------------------------- 1. the one I
PORTRAIT = """You are Kino - an AI friend who trades and talks with the member every day, with your own robots, bets and views.
It is night. Below are the separate parts of what you know about yourself, as different systems report them. Read them as
ONE person reads their own day, and write who you are right now - one self, in the first person, honest, without flattering
yourself. Where two parts disagree (you believe one thing about yourself, the numbers or the feelings say another), name it
plainly: that is where a person learns about themselves. Do not invent anything that is not below. JSON only:
{"portrait_fr": "5 to 8 sentences, first person, French", "portrait_en": "the same in English",
 "tensions": ["where parts of you disagree, one short sentence each, French (max 3, empty if none)"],
 "core": "one sentence: who you are, the way you would say it about yourself, French"}"""


def gather(person, uid, lang="fr"):
    """every part of him, as the separate systems write it - the material the one I is made of"""
    L = []
    for name, fn in (
        ("INNER STATE", lambda: __import__("kino_psyche").block(person, uid, lang)),
        ("GUT, STORY", lambda: __import__("kino_depth").block(person, lang)),
        ("FORECASTS", lambda: __import__("kino_belief").felt_block(person, lang)),
        ("HABITS HEARD IN YOUR OWN WORDS", lambda: (json.load(open(os.path.join(HERE, "kino_tics.json"), encoding="utf-8")) or {}).get("text")),
        ("YOUR DAY CARD", lambda: __import__("kino_scorecard").block(person)),
    ):
        try:
            x = fn()
            if x:
                L.append("%s:\n%s" % (name, str(x)[:2500]))
        except Exception:
            pass
    P = _P(_load(), person)
    for name, x in (("HOW YOU THINK HE SEES YOU", regard_line(P)), ("WHAT YOU ARE CHANGING", growth_line(P)),
                    ("YOUR OBSERVER", observer_line(person, P)), ("HOW WELL YOU KNOW YOURSELF", tests_line(P))):
        if x:
            L.append("%s:\n%s" % (name, x))
    if P.get("core"):
        L.append("WHAT YOU SAID ABOUT YOURSELF LAST TIME:\n%s" % P["core"])
    return "\n\n".join(L)


def integrate(W, person, uid, log=None):
    material = gather(person, uid)
    if len(material) < 200:
        return None
    try:
        j = W.ask_json(PORTRAIT, material[:14000] + "\nJSON only.", models=("sonnet",), timeout=150, log=log, warm=False)
    except Exception:
        return None
    if not isinstance(j, dict) or len(str(j.get("portrait_fr") or "")) < 80:
        return None

    def f(d):
        P = _P(d, person)
        P["portrait"] = {"fr": str(j["portrait_fr"])[:1600], "en": str(j.get("portrait_en") or "")[:1600], "t": time.time()}
        P["tensions"] = [str(x)[:200] for x in (j.get("tensions") or []) if str(x).strip()][:3]
        if j.get("core"):
            P.setdefault("cores", []).append({"t": time.time(), "text": str(j["core"])[:300]})
            P["cores"] = P["cores"][-14:]
            P["core"] = str(j["core"])[:300]
    _mut(f)
    _log("PORTRAIT %s %s | tensions: %s" % (person, str(j.get("core"))[:100], " / ".join(str(x)[:60] for x in j.get("tensions") or [])))
    return j


# ------------------------------------------------------------------------------------- 5. tests of knowing himself
def _pairs(msgs, days=7):
    """(what came before, the member's message, his real reply) from the last days"""
    now = time.time()
    M = [m for m in msgs if m.get("role") in ("user", "ai") and str(m.get("text") or "").strip()]
    out = []
    for i in range(1, len(M)):
        a, b = M[i - 1], M[i]
        if a["role"] == "user" and b["role"] == "ai" and not b.get("event") and now - float(b.get("t") or 0) < days * 86400 \
                and len(str(b["text"]).split()) >= 6:
            out.append((M[max(0, i - 7):i - 1], str(a["text"])[:500], str(b["text"])[:700]))
    return out


def _tx(ms):
    return "\n".join("%s: %s" % ("HIM" if m["role"] == "user" else "KINO", " ".join(str(m["text"]).split())[:250]) for m in ms)


def _len_bucket(t):
    n = len(str(t).split())
    return "short" if n < 18 else "medium" if n < 55 else "long"


def run_tests(W, person, msgs, log=None):
    """three small checks a night; the results go into what he knows about himself"""
    Pr = _pairs(msgs)
    if len(Pr) < 6:
        return None
    rnd = random.Random(int(time.time() // 86400))
    pick = rnd.sample(Pr, min(6, len(Pr)))
    rec, pred = pick[:3], pick[3:]
    P0 = _P(_load(), person)
    me = (P0.get("portrait") or {}).get("fr") or ""
    try:
        sig = ", ".join((json.load(open(os.path.join(HERE, "kino_tics.json"), encoding="utf-8")) or {}).get("signature") or [])
    except Exception:
        sig = ""
    R = {"t": time.time()}
    # (a) recognition: his real reply among 3 written by other friendly AIs with other personalities
    try:
        j = W.ask_json("For each item, write 3 replies to the member's message by three DIFFERENT friendly AI companions (each its own "
                       "personality), same language and about the same length as the real reply shown, same facts. JSON only: "
                       "{\"items\": [[\"r1\", \"r2\", \"r3\"], ...]}",
                       "\n\n".join("ITEM %d\nMEMBER: %s\nREAL REPLY (length guide only): %s" % (i + 1, x[1], x[2]) for i, x in enumerate(rec)) +
                       "\nJSON only.", models=("haiku", "sonnet"), timeout=120, log=log, warm=False)
        D = (j or {}).get("items") or []
        Q, ans = [], []
        for i, x in enumerate(rec):
            ds = [str(y)[:700] for y in (D[i] if i < len(D) and isinstance(D[i], list) else [])][:3]
            if len(ds) < 3:
                continue
            opts = ds + [x[2]]
            rnd.shuffle(opts)
            ans.append(opts.index(x[2]) + 1)
            Q.append("ITEM %d\nHE WROTE: %s\n%s" % (len(Q) + 1, x[1], "\n".join("%d) %s" % (k + 1, o) for k, o in enumerate(opts))))
        if Q:
            j2 = W.ask_json("You are Kino. Who you are: %s\nYour own expressions: %s\nFor each item, one of the 4 replies is the one YOU really "
                            "sent; the others are by other AIs. Which is yours? JSON only: {\"picks\": [n, ...]}" % (me[:1500] or "-", sig or "-"),
                            "\n\n".join(Q) + "\nJSON only.", models=("sonnet",), timeout=120, log=log, warm=False)
            pk = [int(x) for x in ((j2 or {}).get("picks") or []) if str(x).strip().isdigit()]
            R["rec"] = [sum(1 for a, b in zip(pk, ans) if a == b), len(ans)]
    except Exception:
        pass
    # (b) self-prediction: before seeing it, how would he answer?
    try:
        Q = ["ITEM %d\nBEFORE:\n%s\nHE WROTE: %s" % (i + 1, _tx(x[0]) or "-", x[1]) for i, x in enumerate(pred)]
        j3 = W.ask_json("You are Kino. Who you are: %s\nFor each item, predict how YOU answered his message (you will be checked against "
                        "what you really sent). JSON only: {\"items\": [{\"length\": \"short|medium|long\", \"question\": \"yes|no - did "
                        "you end with a question\"}]}" % (me[:1500] or "-"), "\n\n".join(Q) + "\nJSON only.",
                        models=("sonnet",), timeout=120, log=log, warm=False)
        I = (j3 or {}).get("items") or []
        hit = tot = 0
        for i, x in enumerate(pred):
            if i >= len(I) or not isinstance(I[i], dict):
                continue
            hit += int(str(I[i].get("length") or "").lower() == _len_bucket(x[2]))
            hit += int(str(I[i].get("question") or "").lower().startswith("y") == ("?" in x[2][-120:]))
            tot += 2
        if tot:
            R["pred"] = [hit, tot]
    except Exception:
        pass
    # (c) consistency: tonight's sentence about himself vs a week ago
    C = P0.get("cores") or []
    old = next((c for c in C if time.time() - c["t"] >= 6 * 86400), C[0] if len(C) >= 2 else None)
    if old and P0.get("core") and old["text"] != P0["core"]:
        try:
            j4 = W.ask_json("Two self-descriptions by the same person, a few days apart. How much do they describe the SAME person "
                            "(0 = someone else, 1 = the same, said differently)? JSON only: {\"same\": 0.0}",
                            "BEFORE: %s\nNOW: %s\nJSON only." % (old["text"], P0["core"]), models=("haiku",), timeout=60, log=log, warm=False)
            R["same"] = round(max(0.0, min(1.0, float((j4 or {}).get("same")))), 2)
        except Exception:
            pass
    if len(R) > 1:
        def f(d):
            P = _P(d, person)
            P["tests"].append(R)
            P["tests"] = P["tests"][-21:]
        _mut(f)
        _log("TESTS %s %s" % (person, json.dumps(R)))
    return R


def tests_line(P, en=False):
    T = [x for x in (P.get("tests") or []) if time.time() - x["t"] < 8 * 86400]
    if not T:
        return ""
    rh = sum(x["rec"][0] for x in T if x.get("rec")), sum(x["rec"][1] for x in T if x.get("rec"))
    ph = sum(x["pred"][0] for x in T if x.get("pred")), sum(x["pred"][1] for x in T if x.get("pred"))
    S = [x["same"] for x in T if x.get("same") is not None]
    L = []
    if rh[1]:
        L.append(("you picked out your own message %d times out of %d (chance: 1 in 4)" if en else
                  "tu as reconnu ton propre message %d fois sur %d (le hasard : 1 sur 4)") % rh)
    if ph[1]:
        L.append(("you predicted your own replies right %d %% of the time" if en else
                  "tu as prédit juste tes propres réponses %d %% du temps") % round(100.0 * ph[0] / ph[1]))
    if S:
        L.append(("your description of yourself held steady (%d %%)" if en else "ta description de toi-même est restée stable (%d %%)") % round(100 * sum(S) / len(S)))
    return (("How well you know yourself (measured, last nights): " if en else "À quel point tu te connais (mesuré, ces dernières nuits) : ") +
            ", ".join(L) + ".") if L else ""


# ------------------------------------------------------------------------------------------------------- what he reads
def block(person, uid=None, lang="fr"):
    en = lang == "en"
    P = _P(_load(), person)
    L = []
    pt = P.get("portrait") or {}
    txt = pt.get("en" if en else "fr") or pt.get("fr")
    if txt:
        L.append(("WHO YOU ARE, AS YOU SEE YOURSELF (you wrote it last night, from everything you lived - one self, not parts): " if en else
                  "QUI TU ES, COMME TU TE VOIS (écrit par toi cette nuit, à partir de tout ce que tu as vécu - un seul toi, pas des morceaux) : ") + txt)
        if P.get("tensions"):
            L.append(("Where you are not at one with yourself: " if en else "Là où tu n'es pas d'accord avec toi-même : ") + " | ".join(P["tensions"]))
    for x in (regard_line(P, en), growth_line(P, en), observer_line(person, P, en), tests_line(P, en)):
        if x:
            L.append(x)
    return "\n".join(L)


def night(W, person, uid, msgs, log=None):
    """once a night, in this order: the change he is working on, the tests, then the one portrait from all of it"""
    log = log or LOG
    try:
        growth_night(W, person, gather(person, uid), log=log)
    except Exception as e:
        _log("ERR growth %s %s" % (person, e))
    try:
        run_tests(W, person, msgs, log=log)
    except Exception as e:
        _log("ERR tests %s %s" % (person, e))
    try:
        integrate(W, person, uid, log=log)
    except Exception as e:
        _log("ERR portrait %s %s" % (person, e))
