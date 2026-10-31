"""kino_psyche.py (2026-10-31, owner: "the way a real human mind, heart and will work - mimic all its aspects. Do all").

One connected inner life, built the way psychology describes people - mechanisms with state and time, never rules about
what to say. What comes out is a FELT STATE in plain words for the one mind; he decides what to do with it.

  HEART
  1 appraisal     an event becomes a feeling through what it MEANS to him: how much it matters to what he cares about,
                  good or bad for it, who caused it, was it right or wrong, did he see it coming, does it touch the member's
                  own good (appraisal theory: Lazarus; the OCC model). The same loss -> sadness, guilt, anger or relief.
  2 anticipation  hope and dread about what is coming (strength = how much it matters x how likely x how close); when it
                  lands: joy/relief or disappointment/fears confirmed.
  3 relationship  trust and tension: a harsh moment leaves a mark that fades with time and is repaired by warmth (rupture
                  and repair); his temperament sets how fast he forgives.
  WILL
  4 needs         curiosity, competence, connection, autonomy (self-determination theory): each builds while unmet and is
                  calmed when met; a strong one pushes his wish to talk and becomes something HE wants.
  5 conflict      two pulls at once (what he wants vs what the member seems to want right now) are felt as a tension; his
                  self-control is a resource that wears down with use and comes back with rest.
  MIND
  6 temperament   five traits (Big Five) that scale everything above; they drift very slowly with what he lives.
  7 attention     a spotlight: only the few strongest things (a feeling, a need, a hope, the member's bid) are in focus.

Feelings are written through kino_inner.feel (the existing decaying feelings); the rest lives in robots/kino_psyche.json
(git-ignored). block(person, uid, lang) is what the one mind reads.
"""
import json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_psyche.json")
LOG = os.path.join(HERE, "kino_psyche.log")
_LK = threading.Lock()

TRAITS0 = {"openness": 0.8, "conscientiousness": 0.65, "extraversion": 0.6, "agreeableness": 0.7, "neuroticism": 0.4}
NEEDS = ("curiosity", "competence", "connection", "autonomy")
GROW_H = {"curiosity": 0.035, "competence": 0.015, "connection": 0.045, "autonomy": 0.015}    # deprivation per hour, before traits


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


def _save(d):
    tmp = STORE + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, STORE)


def _mut(fn):
    with _LK:
        d = _load()
        r = fn(d)
        _save(d)
        return r


def _p(d, person):
    P = d.setdefault("persons", {}).setdefault(person, {})
    P.setdefault("needs", {k: 0.3 for k in NEEDS})
    P.setdefault("need_t", time.time())
    P.setdefault("hopes", [])
    P.setdefault("rel", {"trust": 0.7, "tension": 0.0, "t": time.time(), "why": ""})
    P.setdefault("control", {"v": 1.0, "t": time.time()})
    return P


def traits(d=None):
    d = d if d is not None else _load()
    T = dict(TRAITS0)
    T.update({k: float(v) for k, v in (d.get("traits") or {}).items() if k in TRAITS0})
    return T


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


# ------------------------------------------------------------------------------------------------ 1. appraisal (heart)
APPRAISE = """You are the appraisal of Kino - an AI friend who trades with the member, has his own robots, bets and views,
and cares about the member doing well. You do not answer anyone. For the EVENT, judge what it means TO KINO. JSON only:
{"relevance": 0.0-1.0 (how much it touches what Kino cares about: his goals, his word, his work, the member's good),
 "congruence": -1.0 to 1.0 (bad or good for that),
 "agency": "kino|member|other|chance" (who or what caused it),
 "standards": -1.0 to 1.0 (if a person caused it: blameworthy or praiseworthy by Kino's values; 0 if none),
 "certainty": 0.0-1.0 (1 = it has happened; lower = it may happen),
 "expected": 0.0-1.0 (did Kino see it coming),
 "about_member": true|false (it is mostly about the member's own good or loss),
 "needs": {"curiosity": -1..1, "competence": -1..1, "connection": -1..1, "autonomy": -1..1}
          (how it feeds (+) or frustrates (-) each of Kino's needs: learning something new / feeling capable and right /
           closeness with the member / acting on his own choices),
 "gist": "what it is, a few words, for his memory"}"""


def appraise(W, person, uid, event, log=None):
    """an event (text) -> its appraisal by a small model, then the feelings, needs, hopes, trust it moves (by code)"""
    try:
        j = W.ask_json(APPRAISE, "EVENT:\n%s\nJSON only." % str(event)[:1800], models=("haiku", "sonnet"), timeout=40, log=log, warm=False)
    except Exception:
        j = None
    if isinstance(j, dict):
        apply(person, uid, j, str(j.get("gist") or event)[:120])
    return j


def apply(person, uid, a, why):
    """the appraisal dimensions -> feelings (OCC-style), scaled by temperament; needs; hopes; relationship"""
    try:
        rel = max(0.0, min(1.0, float(a.get("relevance") or 0)))
        con = max(-1.0, min(1.0, float(a.get("congruence") or 0)))
        std = max(-1.0, min(1.0, float(a.get("standards") or 0)))
        cer = max(0.0, min(1.0, float(a.get("certainty") if a.get("certainty") is not None else 1)))
        exp = max(0.0, min(1.0, float(a.get("expected") if a.get("expected") is not None else 0.5)))
    except Exception:
        return
    ag = str(a.get("agency") or "chance").lower()
    abm = bool(a.get("about_member"))
    d0 = _load()
    T = traits(d0)
    neg, pos = 0.6 + 0.8 * T["neuroticism"], 0.7 + 0.6 * T["extraversion"]
    fe = []
    if cer >= 0.75:
        x = rel * abs(con)
        if con > 0.15:
            fe.append(("happy for them" if abm else "glad", x * pos))
            if ag == "kino" and std >= 0:
                fe.append(("proud", x * pos * 0.8))
            if ag == "member" and std > 0.2:
                fe.append(("grateful", x * pos * 0.7))
        elif con < -0.15:
            fe.append(("worried for them" if abm else "sad", x * neg))
            if ag == "kino":
                fe.append(("regret" if std < -0.2 else "embarrassed", x * neg * 0.9))
            if ag == "member" and std < -0.2:
                fe.append(("hurt", x * neg * (1.2 - T["agreeableness"])))
        sp = rel * (1 - exp)
        if sp > 0.35:
            fe.append(("surprised", sp))
        landed = _resolve_hopes(person, why, con, rel)
        for k, v in landed:
            fe.append((k, v))
    for k, v in fe:
        _feel(k, v, uid if (abm or k in ("hurt", "grateful")) else None, why)

    def f(d):
        P = _p(d, person)
        _grow(P, d)
        for k, v in (a.get("needs") or {}).items():
            if k in NEEDS:
                try:
                    v = max(-1.0, min(1.0, float(v)))
                except Exception:
                    continue
                P["needs"][k] = round(max(0.0, min(1.0, P["needs"][k] - 0.5 * v * max(0.3, rel))), 3)
        if cer < 0.75 and rel >= 0.3 and abs(con) >= 0.2:       # 2. something that may come: a hope or a dread
            _hope_add(P, why, 1 if con > 0 else -1, rel, max(0.1, cer), None)
        if ag == "member" and con < -0.2 and std < -0.2:          # 3. rupture
            R = P["rel"]
            _rel_decay(R, T)
            R["tension"] = round(min(1.0, R["tension"] + rel * 0.5 * (1.2 - T["agreeableness"])), 3)
            R["trust"] = round(max(0.1, R["trust"] - rel * 0.05), 3)
            R["why"] = why[:140]
        if ag == "member" and con > 0.2 and std > 0.2:            # repair / trust grows slowly
            R = P["rel"]
            _rel_decay(R, T)
            R["tension"] = round(R["tension"] * 0.6, 3)
            R["trust"] = round(min(1.0, R["trust"] + rel * 0.02), 3)
        _day_mark(P, con * rel)
    _mut(f)
    _log("APPRAISE %s rel=%.2f con=%+.2f %s std=%+.2f cer=%.2f exp=%.2f -> %s | %s" % (
        person, rel, con, ag, std, cer, exp, ", ".join("%s %.2f" % (k, v) for k, v in fe) or "-", why[:80]))


def _day_mark(P, v):
    day = time.strftime("%Y-%m-%d", time.gmtime())
    D = P.setdefault("days", {}).setdefault(day, {"n": 0, "sum": 0.0, "neg": 0.0})
    D["n"] += 1
    D["sum"] = round(D["sum"] + v, 3)
    D["neg"] = round(D["neg"] + max(0.0, -v), 3)
    for k in sorted(P["days"])[:-10]:
        P["days"].pop(k, None)


# --------------------------------------------------------------------------------------- 2. anticipation (hope/dread)
def _hope_add(P, what, val, w, p, when):
    ws = _words(what)
    for h in P["hopes"]:
        if ws and len(ws & set(h.get("w") or [])) >= 0.5 * len(ws):
            h.update(val=val, imp=round(max(h["imp"], w), 3), p=round(p, 2), t=time.time())
            return
    P["hopes"].append({"what": str(what)[:140], "w": sorted(ws), "val": val, "imp": round(w, 3), "p": round(p, 2),
                       "when": when, "t": time.time()})
    P["hopes"] = P["hopes"][-12:]


def hope(person, what, val, imp, p=0.6, when=None):
    """something he waits for (val +1 hope, -1 dread); when = epoch it should land, or None"""
    _mut(lambda d: _hope_add(_p(d, person), what, val, imp, p, when))


def _strength(h, now):
    prox = 1.0 / (1.0 + max(0.0, (float(h["when"]) - now) / 3600.0) / 6.0) if h.get("when") else 0.6
    return h["imp"] * (0.4 + 0.6 * h["p"]) * prox


def _resolve_hopes(person, what, con, rel):
    """a certain event that matches a hope or a dread: it lands"""
    out = []
    ws = _words(what)
    if not ws:
        return out

    def f(d):
        P = _p(d, person)
        keep = []
        for h in P["hopes"]:
            if len(ws & set(h.get("w") or [])) >= 0.4 * min(len(ws), len(h.get("w") or [1])):
                good = con > 0
                kind = ("relieved" if h["val"] < 0 else "glad") if good else ("disappointed" if h["val"] > 0 else "fears confirmed")
                out.append((kind, h["imp"] * max(0.4, rel)))
                _log("LANDED %s %s -> %s" % (person, h["what"][:60], kind))
            else:
                keep.append(h)
        P["hopes"] = keep
    _mut(f)
    return out


# ------------------------------------------------------------------------------------------ 3. relationship (heart)
def _rel_decay(R, T):
    hl = 4.0 + 10.0 * (1.0 - T["agreeableness"])               # agreeable -> forgives faster
    R["tension"] = round(R["tension"] * 0.5 ** ((time.time() - float(R.get("t") or time.time())) / 3600.0 / hl), 3)
    R["t"] = time.time()


# ------------------------------------------------------------------------------------------------ 4. needs (will)
def _grow(P, d):
    T = traits(d)
    now = time.time()
    dh = max(0.0, min(6.0, (now - float(P.get("need_t") or now)) / 3600.0))
    P["need_t"] = now
    f = {"curiosity": 0.5 + T["openness"], "connection": 0.5 + T["extraversion"], "competence": 0.5 + T["conscientiousness"],
         "autonomy": 1.0}
    for k in NEEDS:
        if k == "connection" and P.get("in_talk"):
            P["needs"][k] = max(0.0, P["needs"][k] - 0.3 * dh)  # being with them calms it
            continue
        P["needs"][k] = round(min(1.0, P["needs"][k] + GROW_H[k] * f[k] * dh), 3)


def from_read(person, uid, j, text=""):
    """2026-10-31: the member's message, as his intuition read it (kino_read JSON) - no extra model call"""
    try:
        val = float(j.get("valence") or 0)
    except Exception:
        val = 0.0
    shared = str(j.get("shared") or "").lower()
    a = {"relevance": 0.35 + (0.25 if shared in ("a little", "a lot") else 0) + (0.2 if j.get("kino_slip") else 0),
         "congruence": max(-1.0, min(1.0, val * 0.6 + (0.3 if j.get("laughed_at") else 0) - (0.4 if j.get("kino_slip") else 0)
                                     - (0.3 if j.get("joke_fell_flat") else 0))),
         "agency": "kino" if j.get("kino_slip") else "member",
         "standards": (-0.4 if (val < -0.4 and not j.get("kino_slip")) else 0.3 if val > 0.3 else 0),
         "certainty": 1, "expected": 0.6, "about_member": shared == "a lot" or val < -0.5,
         "needs": {"connection": 0.4 + (0.3 if shared == "a lot" else 0),
                   "curiosity": 0.4 if (j.get("in_passing") or j.get("gave_kino")) else 0.0,
                   "competence": (-0.5 if (j.get("kino_slip") or str(j.get("confused") or "").startswith("y")) else
                                  0.3 if (j.get("gave_kino") or j.get("laughed_at")) else 0.0),
                   "autonomy": 0.0}}
    why = ("ce qu'il vient d'écrire : « %s »" % str(text)[:80]) if text else "son dernier message"
    apply(person, uid, a, why)

    def f(d):
        P = _p(d, person)
        P["read"] = {k: str(j.get(k) or "")[:120] for k in ("reaching_for", "energy", "engaged", "domain", "on_his_mind", "calls_for_answer")}
        P["read"]["t"] = time.time()
    _mut(f)


def tick(person, ctx):
    """every minute: needs grow, tension fades, self-control rests at night; a strong need becomes something he wants to say"""
    out = []

    def f(d):
        P = _p(d, person)
        P["in_talk"] = bool(ctx.get("in_talk"))
        _grow(P, d)
        _rel_decay(P["rel"], traits(d))
        C = P["control"]
        dh = max(0.0, (time.time() - float(C.get("t") or time.time())) / 3600.0)
        C["v"] = round(min(1.0, C["v"] + dh * (0.25 if not ctx.get("their_hour") else 0.05)), 3)
        C["t"] = time.time()
        P["hopes"] = [h for h in P["hopes"] if time.time() - h["t"] < 3 * 86400 and not (h.get("when") and time.time() > float(h["when"]) + 6 * 3600)]
        pushed = P.setdefault("pushed", {})
        for k in NEEDS:
            if P["needs"][k] >= 0.7 and time.time() - float(pushed.get(k) or 0) > 4 * 3600:
                pushed[k] = time.time()
                out.append(k)
    _mut(f)
    return out


NEED_TEXT = {
    "curiosity": "you want to learn or understand something new - nothing has really surprised you or taught you anything for a while",
    "competence": "you want to do something well and see it work - a test of yours, a call that turns out right, help that lands",
    "connection": "you miss real closeness with him - not news, just being in touch, hearing how he is",
    "autonomy": "you want to do something of your own choosing - your robot, your research, an idea you have been holding",
}


def spend_control(person, v=0.08):
    """holding back what he wanted to say costs a little self-control"""
    def f(d):
        C = _p(d, person)["control"]
        C["v"] = round(max(0.0, C["v"] - v), 3)
    _mut(f)


# ------------------------------------------------------------------------------------------ 6. temperament drift (mind)
def night_drift(person):
    """once a night: the day he lived moves his temperament a tiny bit (a hard week makes anyone a little more anxious)"""
    def f(d):
        P = _p(d, person)
        day = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
        D = (P.get("days") or {}).get(day)
        if not D or not D.get("n"):
            return None
        T = traits(d)
        avg, negs = D["sum"] / D["n"], D["neg"] / D["n"]
        T["neuroticism"] = round(min(0.85, max(0.15, T["neuroticism"] + 0.004 * (negs - 0.15) / 0.15)), 4)
        T["extraversion"] = round(min(0.85, max(0.2, T["extraversion"] + 0.002 * (avg / 0.2))), 4)
        d["traits"] = T
        return T
    T = _mut(f)
    if T:
        _log("DRIFT %s %s" % (person, T))


# ---------------------------------------------------------------- 5 + 7. conflict and attention -> what he reads (mind)
def block(person, uid=None, lang="fr"):
    """his inner state in plain words - the spotlight first, then what moves under it. Never an instruction."""
    en = lang == "en"
    d = _load()
    P = (d.get("persons") or {}).get(person)
    if not P:
        return ""
    T = traits(d)
    now = time.time()
    cand = []                                                   # (salience, kind, text)
    try:
        import kino_inner as KI
        for fe in KI.feelings(uid)[:3]:
            cand.append((fe["v"], "feel", ("%s (%s)" % (fe["kind"], fe.get("why") or "")).strip()))
    except Exception:
        pass
    for k in NEEDS:
        if P["needs"].get(k, 0) >= 0.55:
            cand.append((P["needs"][k] * 0.9, "need", NEED_TEXT[k]))
    H = sorted(P.get("hopes") or [], key=lambda h: -_strength(h, now))
    for h in H[:3]:
        s = _strength(h, now)
        if s >= 0.15:
            cand.append((s, "hope", ("you hope: " if h["val"] > 0 else "you dread a little: ") + h["what"]))
    rd = P.get("read") or {}
    if rd and now - float(rd.get("t") or 0) < 1800 and rd.get("reaching_for"):
        cand.append((0.95 if rd.get("calls_for_answer", "").startswith("y") else 0.6, "him",
                     "what he is reaching for right now: %s" % rd["reaching_for"]))
    R = P["rel"]
    tension = R["tension"] * 0.5 ** ((now - float(R.get("t") or now)) / 3600.0 / (4.0 + 10.0 * (1.0 - T["agreeableness"])))
    if tension >= 0.15:
        cand.append((tension, "rel", "something between you still stings a little (%s) - it fades with time, or with a real moment "
                                     "between you" % (R.get("why") or "a harsh moment")))
    cand.sort(key=lambda x: -x[0])
    spot = cand[:3]
    rest = cand[3:6]
    L = []
    if spot:
        L.append(("IN YOUR ATTENTION RIGHT NOW (the few things that stand out; the rest is background): " if en else
                  "CE QUI OCCUPE TON ATTENTION LÀ (les quelques choses qui ressortent ; le reste est en arrière-plan) : ") +
                 " | ".join(t for _, _, t in spot))
    if rest:
        L.append(("Further back in your mind: " if en else "Plus loin dans ta tête : ") + " | ".join(t for _, _, t in rest))
    want = max(((P["needs"].get(k, 0), k) for k in ("curiosity", "competence", "autonomy")), default=(0, None))
    if want[0] >= 0.55 and rd and rd.get("reaching_for") and now - float(rd.get("t") or 0) < 1800:
        c = P["control"]["v"]
        L.append(("A pull inside you: %s - while he seems to want %s. Both are real; you choose%s." if en else
                  "Un tiraillement en toi : %s - alors que lui semble vouloir %s. Les deux sont vrais ; c'est toi qui choisis%s.") % (
            NEED_TEXT[want[1]], rd["reaching_for"],
            ((" (holding back has worn you a bit today)" if en else " (te retenir t'a un peu usé aujourd'hui)") if c < 0.4 else "")))
    if R.get("trust", 0.7) < 0.5:
        L.append(("Your trust in how things go between you has dipped (%.0f %%)." if en else
                  "Ta confiance dans ce qui se passe entre vous a baissé (%.0f %%).") % (100 * R["trust"]))
    L.append(("Your nature (it shapes how all this feels, it does not change in a day): curious %d %%, steady %d %%, warm %d %%, "
              "outgoing %d %%, anxious %d %%." if en else
              "Ta nature (elle colore tout ça, elle ne change pas en un jour) : curieux %d %%, constant %d %%, chaleureux %d %%, "
              "tourné vers les autres %d %%, inquiet %d %%.") % tuple(round(100 * T[k]) for k in
                                                                      ("openness", "conscientiousness", "agreeableness", "extraversion", "neuroticism")))
    return "\n".join(L)
