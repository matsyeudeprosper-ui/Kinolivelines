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
        # round 5: his intentions, your shared plans, what he gave you
        for key, fld in (("his_plans", "his_intention"), ("plans", "shared_plan"), ("gifts", "gave_kino")):
            v = " ".join(str(r.get(fld) or "").split())[:180]
            if len(v) >= 6 and not any(v[:40].lower() == str(x.get("text") or "")[:40].lower() for x in P.get(key) or []):
                P[key] = ((P.get(key) or []) + [{"t": now, "text": v}])[-15:]
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
    ago = lambda t: ("%d min" % ((now - t) / 60)) if now - t < 7200 else ("%.0f h" % ((now - t) / 3600)) if now - t < 2 * 86400 else ("%d jours" % ((now - t) / 86400))
    hp = [x for x in P.get("his_plans") or [] if now - float(x["t"]) < 7 * 86400][-3:]
    if hp:
        L.append("Ce qu'il a dit qu'il ferait, lui : " + " | ".join("%s (il y a %s)" % (x["text"], ago(float(x["t"]))) for x in hp) + ".")
    sp = [x for x in P.get("plans") or [] if now - float(x["t"]) < 14 * 86400][-3:]
    if sp:
        L.append("Vos projets à deux : " + " | ".join("%s (décidé il y a %s)" % (x["text"], ago(float(x["t"]))) for x in sp) + ".")
    gf = [x for x in P.get("gifts") or []][-5:]
    if gf:
        L.append("Ce qu'il t'a donné ou appris : " + " | ".join(x["text"] for x in gf) + ".")
    V = sorted(((w, v) for w, v in (P.get("words") or {}).items() if int(v[1]) >= 2), key=lambda x: -x[1][1])[:8]
    if V:
        L.append("Ses mots à lui (votre langage à vous deux) : %s." % ", ".join(w for w, _ in V))
    return " ".join(L)


def progress(trades):
    """his trading, recent vs before (last 30 closed trades: 15 vs 15): a friend notices growth or a dip, on real data"""
    T = [t for t in trades or [] if isinstance(t, dict) and t.get("p") is not None][:30]
    if len(T) < 12:
        return ""
    h = len(T) // 2
    rec, old = T[:h], T[h:]                       # newest first

    def st(X):
        w = sum(1 for t in X if float(t["p"]) > 0)
        L_ = [float(t["p"]) for t in X if float(t["p"]) < 0]
        return w / len(X), sum(float(t["p"]) for t in X) / len(X), (sum(L_) / len(L_)) if L_ else 0.0
    (wr1, av1, ls1), (wr0, av0, ls0) = st(rec), st(old)
    bits = []
    if abs(wr1 - wr0) >= 0.1:
        bits.append("plus de gagnants (%d %% contre %d %%)" % (wr1 * 100, wr0 * 100) if wr1 > wr0 else "moins de gagnants (%d %% contre %d %%)" % (wr1 * 100, wr0 * 100))
    if ls0 and ls1 and abs(ls1 - ls0) >= 0.5:
        bits.append("des pertes plus petites" if ls1 > ls0 else "des pertes plus grosses")
    if abs(av1 - av0) >= 0.5:
        bits.append("un meilleur résultat moyen par trade" if av1 > av0 else "un résultat moyen en baisse")
    return ("Sa progression (ses %d derniers trades contre les %d d'avant) : %s." % (len(rec), len(old), ", ".join(bits) if bits else "à peu près pareil"))


def concern(session_h, local_h, loss_streak, valence):
    """how much a friend would worry right now: long session, late, losses in a row, low mood - a feeling, not advice"""
    c = 0.0
    c += min(0.35, max(0.0, session_h - 3) * 0.07)
    c += 0.2 if (local_h >= 1 and local_h < 6) else 0.0
    c += min(0.35, 0.09 * max(0, loss_streak - 1))
    try:
        c += max(0.0, -float(valence)) * 0.3
    except Exception:
        pass
    return min(1.0, c)


def milestones(first_t, member_msgs, trades_together, done):
    """the shared history's round numbers - each one once"""
    now = time.time()
    out = []
    days = (now - float(first_t)) / 86400 if first_t else 0
    for d in (7, 14, 30, 60, 100, 365):
        if days >= d and ("days%d" % d) not in done:
            out.append(("days%d" % d, "ça fait %d jours que vous vous parlez" % d))
    for n in (100, 500, 1000, 2000, 5000):
        if member_msgs >= n and ("msgs%d" % n) not in done:
            out.append(("msgs%d" % n, "il t'a écrit son %de message" % n))
    for n in (10, 50, 100, 250):
        if trades_together >= n and ("tr%d" % n) not in done:
            out.append(("tr%d" % n, "vous en êtes à %d trades suivis ensemble" % n))
    return out[-1:] if out else []


ALWAYS = ("Ta lecture de lui", "Vous deux", "Toi, maintenant", "Ce que tu ressens", "Ce qu'il t'a demandé une fois pour toutes",
          "Ce qu'il t'a déjà dit sur ta façon", "Tu t'inquiètes", "Ce dont vous parlez", "Votre rythme", "TU ES EN MODE SEUL",
          "Ce que tu lui as dit que tu ferais", "Il ne peut plus t'écrire")


def memfocus(mem, cue, keep=12, gist=150):
    """round 6 (working memory): people recall what fits the moment; the rest is a vague awareness. What touches the
    moment (his words, the event) and what is always with him (his read of him, the two of them, his state) stay whole;
    the rest is kept as a short gist - nothing is lost, the exact data stays in what he knows of this minute."""
    blocks, cur = [], []
    for ln in str(mem or "").split("\n"):
        if cur and ln.startswith(("  ", "- ", "WHO YOU HAVE BECOME")):
            cur.append(ln)
            continue
        if cur:
            blocks.append("\n".join(cur))
        cur = [ln]
    if cur:
        blocks.append("\n".join(cur))
    blocks = [b for b in blocks if b.strip()]
    cw = _w(cue)
    sc = []
    for i, b in enumerate(blocks):
        s = 2.0 * min(4, len(cw & _w(b)))
        if b.startswith(ALWAYS):
            s += 10
        sc.append((s - 0.01 * i, i))
    top = set(i for _, i in sorted(sc, reverse=True)[:keep])
    out = []
    for i, b in enumerate(blocks):
        if i in top or len(b) <= gist:
            out.append(b)
        else:
            out.append(b[:gist].rsplit(" ", 1)[0] + " …")
    return "\n".join(out)


def setup_watch(feed, rules_text=""):
    """round 6: his method on the live chart, as a friend at his side would watch it. The top (pullback) chart's last
    candle sets the side; on the lower chart, the candle that made the move's extreme since then gives the level; a
    closed 1-minute candle beyond it is the signal. Returns None, or {key, side, level, dist, crossed, text}."""
    try:
        pb = (feed.get("pb") or {}).get("candles") or []
        m1 = feed.get("candles") or []
        px = float(feed.get("px") or 0)
        if len(pb) < 2 or len(m1) < 5 or not px:
            return None
        top = pb[-1]
        bull = float(top[4]) > float(top[1])
        side = "VENTE" if bull else "ACHAT"
        since = [c for c in m1 if int(c[0]) >= int(top[0])][-40:] or m1[-15:]
        if len(since) < 2:
            return None
        ext = max(since, key=lambda c: float(c[2])) if bull else min(since, key=lambda c: float(c[3]))
        level = float(ext[3]) if bull else float(ext[2])
        after = [c for c in since if int(c[0]) > int(ext[0])]
        crossed = next((c for c in after if (float(c[4]) < level if bull else float(c[4]) > level)), None)
        dist = abs(px - level)
        hm = lambda t: __import__("time").strftime("%H:%M", __import__("time").gmtime(int(t)))
        txt = ("graphique du haut : dernière bougie %s (depuis %s UTC) -> on attend une %s ; graphique du bas : la bougie qui a fait "
               "l'extrême du mouvement est celle de %s UTC (%s %.0f) ; une bougie 1 minute qui clôture %s %.0f serait le signal ; prix %.0f, "
               "à %.0f points" % ("haussière" if bull else "baissière", hm(top[0]), side.lower(), hm(ext[0]), "bas" if bull else "haut", level,
                                    "sous" if bull else "au-dessus de", level, px, dist))
        if crossed:
            txt += " - et la bougie de %s UTC vient de clôturer à %.0f, %s le niveau" % (hm(crossed[0]), float(crossed[4]), "sous" if bull else "au-dessus")
        return {"key": "%s:%d" % (int(top[0]), round(level)), "side": side, "level": level, "dist": dist, "crossed": bool(crossed),
                "ckey": ("%s:%d:%s" % (int(top[0]), round(level), int(crossed[0]))) if crossed else None, "text": txt}
    except Exception:
        return None


def patterns(trades):
    """round 6: what a friend notices in how he trades - after a loss, after a win, buys vs sells (last 30 trades)"""
    T = [t for t in trades or [] if isinstance(t, dict) and t.get("p") is not None][:30][::-1]     # oldest first
    if len(T) < 12:
        return ""
    out = []
    al = [(T[i - 1], T[i]) for i in range(1, len(T)) if float(T[i - 1]["p"]) < 0]
    aw = [(T[i - 1], T[i]) for i in range(1, len(T)) if float(T[i - 1]["p"]) > 0]
    if len(al) >= 4:
        up = sum(1 for a, b in al if float(b.get("lot") or 0) > float(a.get("lot") or 0))
        wr = sum(1 for a, b in al if float(b["p"]) > 0) / len(al)
        out.append("après une perte : lot augmenté %d fois sur %d, trade suivant gagnant %d %% du temps" % (up, len(al), wr * 100))
    if len(aw) >= 4:
        wr = sum(1 for a, b in aw if float(b["p"]) > 0) / len(aw)
        out.append("après un gain : trade suivant gagnant %d %% du temps" % (wr * 100))
    B = [t for t in T if str(t.get("dir")).upper().startswith(("A", "B"))]
    S = [t for t in T if str(t.get("dir")).upper().startswith(("V", "S"))]
    if len(B) >= 4 and len(S) >= 4:
        wb, ws = sum(1 for t in B if float(t["p"]) > 0) / len(B), sum(1 for t in S if float(t["p"]) > 0) / len(S)
        out.append("achats gagnants %d %%, ventes %d %%" % (wb * 100, ws * 100))
    return ("Ce que tu remarques dans sa façon de trader (ses %d derniers trades) : %s." % (len(T), " ; ".join(out))) if out else ""


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
