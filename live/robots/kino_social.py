"""kino_social.py (2026-10-28, KINO_V3_HUMAN.md round 2) - the social mechanisms between two people.

Owner: "all 9 - simulate human to the exact point as far as possible, yet super human in terms of numbers and
availability". So nothing here hides a number or slows a reply; each piece is a state with its own dynamics that he FEELS:

  meaning     a number means something to the person (almost at the target, a small loss, sliding to the stop): people
              speak in that meaning and keep the exact figure for when it matters. gist_open / gist_closed.
  attention   people hold a few things in mind, not everything they know: what touches the other's last words, what is
              new, what is live. focus() splits what he knows into "in mind now" and "in the background".
  topics      a talk has a subject; when it has stayed on one for long, people drift, and what the other said in passing
              (his daughter, his week) makes them curious. Fed by the read (kino_read: domain, in_passing).
  sharing     disclosure is reciprocal: when someone opens up, the friend shares something back. Balance of what he
              confided vs what Kino said about himself.
  closeness   familiarity grows with time known, talks, laughs and confidences, and fades with long absence.
  contagion   your win lifts the friend before any analysis; your loss stings him too (kino_inner.feel).

Store robots/kino_social.json (git-ignored).
"""
import json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_social.json")
_LK = threading.Lock()


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


# ------------------------------------------------------------------ meaning
def gist_open(d, e, px, sl, tp):
    """what an open position means right now, in a friend's words"""
    try:
        d, e, px = int(d), float(e), float(px)
        sl, tp = float(sl or 0), float(tp or 0)
        if tp and (tp - e) * d > 0:
            f = (px - e) / (tp - e)
            if f >= 0.8:
                return "presque à l'objectif"
            if f >= 0.45:
                return "bien parti vers l'objectif"
        if sl and (e - sl) * d > 0:
            g = (e - px) / (e - sl)
            if g >= 0.8:
                return "tout près du stop"
            if g >= 0.45:
                return "glisse vers le stop"
        return "autour de son entrée"
    except Exception:
        return ""


def gist_closed(pl):
    try:
        pl = float(pl)
    except Exception:
        return ""
    a = abs(pl)
    size = "petit" if a < 2 else "beau" if (pl > 0 and a >= 8) else "gros" if a >= 8 else "correct"
    if pl >= 0:
        return {"petit": "un petit gain", "correct": "un gain correct", "beau": "un beau gain"}[size]
    return {"petit": "une petite perte", "correct": "une perte qui pique un peu", "gros": "une grosse perte"}[size]


# ------------------------------------------------------------------ attention
def _w(t):
    return set(re.findall(r"[a-zà-ÿ0-9]{4,}", str(t or "").lower()))


def focus(facts, last_member, keep=6):
    """split what he knows into what is in mind now and the background, by salience: touches his last words, is live,
    is new (not already told). Every line stays - only where it sits changes."""
    blocks, cur = [], []
    for ln in str(facts or "").split("\n"):
        if cur and (ln.startswith(("- ", "  ", "Position ouverte", "Ordre en attente", "Aucune position", "SON ROBOT", "Son robot"))):
            cur.append(ln)
            continue
        if cur:
            blocks.append("\n".join(cur))
        cur = [ln]
    if cur:
        blocks.append("\n".join(cur))
    blocks = [b for b in blocks if b.strip()]
    if len(blocks) <= keep:
        return facts
    lw = _w(last_member)

    def sal(i, b):
        s = 0.0
        s += 2.0 * min(3, len(lw & _w(b)))
        if re.search(r"Position ouverte|Trades ouverts|EN COURS|en cours|en train|ce moment|maintenant|à cette minute", b):
            s += 2.0
        if "SES RÈGLES DE TRADING" in b or "SES TRADES À LA MAIN" in b:
            s += 3.0                                            # what you act on stays in mind
        if "[déjà dit" in b:
            s -= 2.5
        return s - 0.05 * i                                      # ties: the order they were written in
    order = sorted(range(len(blocks)), key=lambda i: -sal(i, blocks[i]))
    top = sorted(order[:keep])
    rest = [i for i in range(len(blocks)) if i not in top]
    return ("CE QUI T'OCCUPE L'ESPRIT MAINTENANT :\n" + "\n".join(blocks[i] for i in top) +
            "\n\nEN ARRIÈRE-PLAN (tu le sais, sans y penser) :\n" + "\n".join(blocks[i] for i in rest))


# ------------------------------------------------------------------ topics, curiosity, sharing (fed by the read)
def note_read(person, r):
    """after each read of him: the subject, what he said in passing, how much he confided"""
    now = time.time()
    dom = str(r.get("domain") or "").strip().lower()[:20]
    inp = " ".join(str(r.get("in_passing") or "").split())[:200]
    sh = str(r.get("shared") or "").strip().lower()
    with _LK:
        d = _load()
        P = d.setdefault(person, {"topics": [], "curious": [], "shares": [], "first": now})
        if dom:
            P["topics"] = (P["topics"] + [[now, dom]])[-40:]
        if inp and not any(inp[:40].lower() == str(x.get("text") or "")[:40].lower() for x in P["curious"]):
            P["curious"] = (P["curious"] + [{"t": now, "text": inp}])[-12:]
        if sh in ("a little", "a lot", "un peu", "beaucoup"):
            P["shares"] = (P["shares"] + [[now, 2 if sh in ("a lot", "beaucoup") else 1]])[-60:]
        # round 3: what you are talking about; his slips (reliability); what he knows; the words you share
        ab = " ".join(str(r.get("talking_about") or "").split())[:160]
        if ab:
            P["about"] = {"t": now, "text": ab}
        sl = " ".join(str(r.get("kino_slip") or "").split())[:160]
        if sl and not any(sl[:40].lower() == str(x.get("text") or "")[:40].lower() for x in P.get("slips") or []):
            P["slips"] = ((P.get("slips") or []) + [{"t": now, "text": sl}])[-30:]
            P["_new_slip"] = sl
        if str(r.get("kino_apologized") or "").lower().startswith("y"):
            P["apology_t"] = now
        K = P.setdefault("knows", {})
        for w in str(r.get("knows") or "").split(","):
            w = w.strip().lower()[:40]
            if 2 < len(w):
                K[w] = now
        U = P.setdefault("unfamiliar", {})
        for w in str(r.get("unfamiliar") or "").split(","):
            w = w.strip().lower()[:40]
            if 2 < len(w) and w not in K:
                U[w] = now
        for w in list(U):
            if w in K:
                U.pop(w, None)
        V = P.setdefault("words", {})
        for w in str(r.get("his_words") or "").split(",")[:4]:
            w = w.strip().lower()[:30]
            if 2 < len(w):
                V[w] = [now, int((V.get(w) or [0, 0])[1]) + 1]
        if len(K) > 40:
            for w in sorted(K, key=lambda x: K[x])[:-40]:
                K.pop(w, None)
        if len(V) > 60:
            for w in sorted(V, key=lambda x: V[x][0])[:-60]:
                V.pop(w, None)
        _save(d)


def block(person, kino_self_said=0, talks=0, laughs=0, last_talk_h=None, first_t=None):
    """the felt social state, plain"""
    now = time.time()
    P = _load().get(person) or {}
    L = []
    T = [x for x in P.get("topics") or [] if now - x[0] < 6 * 3600]
    if T:
        dom = T[-1][1]
        run = 0
        for t, dd in reversed(T):
            if dd != dom:
                break
            run += 1
        start = next((t for t, dd in reversed(T) if dd != dom), None)
        since = [t for t, dd in T if dd == dom and (start is None or t > start)]
        if run >= 3 and since:
            L.append("Ça fait %s que vous ne parlez que de %s (%d échanges d'affilée)." % (
                ("%d min" % ((now - since[0]) / 60)) if now - since[0] < 7200 else ("%.0f h" % ((now - since[0]) / 3600)), dom, run))
    C = [x for x in P.get("curious") or [] if now - float(x["t"]) < 3 * 86400][-3:]
    if C:
        L.append("Ce qu'il a dit en passant et qui t'intrigue : " + " | ".join(x["text"] for x in C) + ".")
    sh = sum(w for t, w in P.get("shares") or [] if now - t < 7 * 86400)
    if sh or kino_self_said:
        L.append("Cette semaine il t'a confié des choses de sa vie %d fois ; toi, tu lui as dit %d choses sur toi." % (sh, kino_self_said))
    first = min(float(P.get("first") or now), float(first_t or now))     # since their first message, not since this store
    days = max(0, (now - first) / 86400)
    # talks = days they actually talked; closeness grows with time known, days together, laughs, confidences
    c = min(1.0, 0.1 + 0.01 * min(days, 30) + 0.025 * min(talks, 20) + 0.03 * min(laughs, 10) + 0.02 * min(sh, 15))
    if last_talk_h is not None and last_talk_h > 72:
        c *= 0.85
    w = ("encore en train de faire connaissance" if c < 0.35 else "à l'aise l'un avec l'autre" if c < 0.6
         else "proches, complices" if c < 0.85 else "très proches")
    L.append("Vous deux : vous vous parlez depuis %d jours, %s." % (round(days), w))
    ab = P.get("about") or {}
    if ab.get("text") and now - float(ab.get("t") or 0) < 3 * 3600:
        L.append("Ce dont vous parlez en ce moment (à quoi renvoient « il », « le test », « ce trade ») : %s." % ab["text"])
    sl = [x for x in P.get("slips") or [] if now - float(x["t"]) < 24 * 3600]
    if sl:
        L.append("Ta fiabilité ces dernières 24 h : tu t'es trompé %d fois (la dernière : %s, il y a %s)." % (
            len(sl), sl[-1]["text"], ("%d min" % ((now - float(sl[-1]["t"])) / 60)) if now - float(sl[-1]["t"]) < 7200 else
            ("%.0f h" % ((now - float(sl[-1]["t"])) / 3600))))
    if P.get("apology_t") and now - float(P["apology_t"]) < 6 * 3600:
        L.append("Tu t'es déjà excusé auprès de lui à %s UTC." % time.strftime("%H:%M", time.gmtime(float(P["apology_t"]))))
    K = sorted(P.get("knows") or {}, key=lambda w: -float((P.get("knows") or {})[w]))[:10]
    U = sorted(P.get("unfamiliar") or {}, key=lambda w: -float((P.get("unfamiliar") or {})[w]))[:6]
    if K:
        L.append("Ce qu'il maîtrise déjà (inutile de le lui expliquer) : %s." % ", ".join(K))
    if U:
        L.append("Ce qui lui est moins familier : %s." % ", ".join(U))
    V = sorted(((w, v) for w, v in (P.get("words") or {}).items() if int(v[1]) >= 2), key=lambda x: -x[1][1])[:8]
    if V:
        L.append("Ses mots à lui (votre langage à vous deux) : %s." % ", ".join(w for w, _ in V))
    return " ".join(L)


def take_new_slip(person):
    """the slip the read just noticed (once) -> for the feeling of embarrassment"""
    with _LK:
        d = _load()
        P = d.get(person) or {}
        s = P.pop("_new_slip", None)
        if s:
            _save(d)
        return s


def playfulness(energy, closeness_word, member_valence, laughs_recent):
    """how much room for play there is right now (his energy, how close you are, how up or low he feels, recent laughs)"""
    p = 0.15 + 0.3 * max(0.0, min(1.0, energy))
    p += {"encore en train de faire connaissance": 0.0, "à l'aise l'un avec l'autre": 0.1, "proches, complices": 0.2,
          "très proches": 0.25}.get(closeness_word, 0.1)
    p += 0.05 * min(3, laughs_recent)
    try:
        p += 0.45 * float(member_valence)              # his mood carries yours: low -> less play, up -> more
    except Exception:
        pass
    return max(0.0, min(1.0, p))


def contagion(KI, person, pl, what="son trade"):
    """his result moves Kino first - before any analysis"""
    try:
        pl = float(pl)
    except Exception:
        return
    k = min(0.6, 0.12 + abs(pl) / 15.0)
    if pl >= 0:
        KI.feel("excitement", k, uid=person, why="%s vient de gagner (%s)" % (what, gist_closed(pl)))
    else:
        KI.feel("sting", k, uid=person, why="%s vient de perdre (%s)" % (what, gist_closed(pl)))
