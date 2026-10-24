"""kino_deed.py (2026-10-24, Kino v2 engine 2 - see KINO_V2_ENGINES.md): a word for an action is a job.

Tester points 1, 2, 4, 13: "je lance" six times and nothing ran; "Oups (NameError)" in the chat; a measurement promised four
times that the tools cannot make; "the 24h test" when the test replays 42 days. One cause: Kino's words about actions and the
code that runs actions were two systems. Here:

  ledger    robots/kino_deeds.json - every action the code starts is a JOB: {id, uid, cid, kind test|build|luck|ghost|measure,
            what, state queued|running|done|failed, t, t_end, err}. Code creates it (chat_test, _chat_build, the tool runner),
            never text.
  bind      bind(c, m, intent, lang, H) runs on every bubble before it is sent (inside the chat lock, so it never calls the
            app): a sentence that claims an action of Kino's own ("je lance le test", "c'est parti", "je le construis",
            "launching it") must be backed by the turn's intent (the reply's act / build fields), a job started in the last
            120 s, or a test already queued. Otherwise the action is put in m["deed_todo"] and the server starts it right
            after the bubble is saved (test when the moments are checked, build when there is a robot); when it cannot be
            started, the sentence is replaced by the plain truth ("Le test attend tes ✅ / ❌ sur les moments").
  cannot    the capability registry (CAN below, robots/kino_can.json when present): a sentence promising something the tools
            cannot do ("the 24h test", "trier les trades de l'Owl par heure", "je mets ton robot en pause") is replaced by the
            reason, on the first attempt, not the fourth. can_block(lang) goes to the slow prompt.
  plain     plain(e, lang): the sentence a person sends when something broke - never an exception name. The server retries the
            turn once before the member hears it.
  jobs      jobs_block(c): "YOUR JOBS RIGHT NOW" for the fresh facts - what is really queued or running for this chat.

  every decision -> robots/deed.log (counts() for the scorecard)
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "kino_deeds.json")
CANF = os.path.join(HERE, "kino_can.json")
LOG = os.path.join(HERE, "deed.log")
_LOCK = threading.Lock()
RECENT_S = 120
KINDS = ("test", "build", "luck", "ghost", "measure")
_SENT = re.compile(r"(?<=[.!?])\s+")

# -- the action claims, by kind (French and English, first person, present/near future) --------------------------------
_LAUNCH = r"(je (lance|relance|démarre|envoie|mets en route|le passe|la passe|passe)|c'est parti|ça part|je (le |la )?(fais|mets) (passer|partir)|" \
          r"i'?m (sending|launching|starting|kicking off|running)|launching|sending it|kicking off|starting it|i (launch|start|run|send))"
CLAIM = {
    "luck": re.compile(r"\b" + _LAUNCH + r"\b[^.!?]{0,50}\b(test de chance|luck test|tirages?|draws)\b", re.I),
    "test": re.compile(r"\b" + _LAUNCH + r"\b[^.!?]{0,40}\b(test|essai|réplay|replay)\b(?! de chance)(?!.*luck test)", re.I),
    "build": re.compile(r"\b(je (le |la |te le |te la )?(construis|monte|assemble|bâtis|reconstruis|remonte|prépare le robot|fabrique)|"
                        r"je (suis en train de|vais) (le |la )?(construire|monter|assembler)|i'?m building|i build it|building it|"
                        r"i'?ll build it|it'?s building|let me build)\b", re.I),
    "ghost": re.compile(r"\b(je (le |la )?mets en (mode )?fantôme|je lance le fantôme|putting it in ghost|starting (the )?ghost|ghost mode now)\b", re.I),
}
_NOT_NOW = re.compile(r"\b(demain|plus tard|tomorrow|later|ce soir|tonight|cette nuit|lundi|la semaine prochaine|next week|quand tu|dès que tu|"
                      r"si tu|once you|when you|if you|après ton|after your)\b", re.I)
_PAST = re.compile(r"\b(j'ai lancé|je l'ai lancé|lancé hier|i launched|i sent it (earlier|already)|déjà lancé|already (queued|running|launched))\b", re.I)

# -- what the tools can and cannot do: a sentence matching a "cannot" is replaced by its reason ----------------------------
CAN = {
    "cannot": [
        {"rx": r"\b(test|essai)\b[^.!?]{0,20}\b(24 ?h|24 heures|24-hour|24 hours|une journée|one day)\b|\b(24 ?h|24-hour|24 hours)[^.!?]{0,12}\b(test|essai)\b",
         "fr": "Le test officiel rejoue 42 jours de vrais prix, pas 24 heures ; pour une fenêtre de 24 h en direct, c'est le mode fantôme.",
         "en": "The official test replays 42 days of real prices, not 24 hours; for a live 24-hour window, that is ghost mode."},
        {"rx": r"\b(trades? (de l'owl|du robot|réels?|de ton compte)|ses trades|its trades|the owl'?s trades)\b[^.!?]{0,40}\b(par heure|heure par heure|par jour de semaine|by hour|per hour|by weekday)\b|"
               r"\b(trier|découper|classer|tri|slice|sort|split)\b[^.!?]{0,30}\b(trades? (de l'owl|du robot|réels?)|its trades|the owl'?s trades)\b|"
               r"\b(par heure|heure par heure|by hour)\b[^.!?]{0,20}\b(trades? (de l'owl|du robot|réels?)|its trades|the owl'?s trades)\b",
         "fr": "Mon outil découpe une idée par heure ou par jour, pas les trades réels de l'Owl un par un ; je n'ai pas ce chiffre ici.",
         "en": "My tool slices an idea by hour or weekday, not the Owl's real trades one by one; I don't have that number here."},
        {"rx": r"\bje (mets|coupe|arrête|stoppe|relance) (ton|le) robot\b|\bje (le |la )?(mets|remets) en pause\b|\bi('ll| will)? (pause|stop|restart) (your|the) robot\b",
         "fr": "Mettre ton robot en pause ou le relancer, c'est toi qui le fais, avec la carte de confirmation ; je ne touche pas à ton compte.",
         "en": "Pausing or restarting your robot is yours to do, with the confirmation card; I don't touch your account."},
        {"rx": r"\bje (déplace|bouge|change|modifie|serre) (ton|le) stop\b|\bje (ferme|coupe) (le|ton) trade\b|\bi('ll| will)? (move|tighten|change) (your|the) stop\b|\bi('ll| will)? close (the|your) trade\b",
         "fr": "Je ne touche pas à un trade ouvert sur ton compte : ni le stop, ni la sortie. Ça reste entre toi et l'app.",
         "en": "I don't touch an open trade on your account, neither the stop nor the exit. That stays between you and the app."},
        {"rx": r"\bje (te )?(garantis|promets)\b[^.!?]{0,30}\b(gain|résultat|profit|semaine|week|mois|month)\b|\bi (guarantee|promise) (you )?(a |the )?(gain|profit|result)\b",
         "fr": "Je ne peux rien garantir sur l'argent : un test, même bon, n'est pas une promesse.",
         "en": "I can't guarantee anything about money: a test, even a good one, is not a promise."},
    ],
    "ui": {
        "fr": "Les votes ✅ / ❌ sont SOUS CHAQUE MOMENT, dans la conversation elle-même, sur téléphone comme sur ordinateur ; il n'y a pas de panneau de vote à côté. Quand le robot change, l'ancienne carte ne compte plus : une nouvelle carte de moments arrive (act test la pose).",
        "en": "The ✅ / ❌ votes sit UNDER EACH MOMENT, inside the conversation itself, on phone and computer alike; there is no vote panel on the side. When the robot changes the old card no longer counts: a new moments card comes (act test posts it).",
    },
    "can": {
        "fr": ["mesurer une idée sur ~42 jours de vrais prix (combien de fois elle se déclenche, le sens N minutes après, contre des moments au hasard)",
               "comparer jusqu'à quatre versions d'une idée", "rejouer le robot de la conversation (trades, % gagnés, par heure / jour / session / moitié, avec le contrôle)",
               "expliquer un trade RÉEL de leur compte (entrée, sortie, meilleur et pire moment, son graphique)", "retrouver leurs anciennes conversations",
               "mettre plusieurs robots côte à côte (résultat, pire creux, jours en commun)", "lancer le test officiel d'un robot (42 jours, coûts compris) quand les moments sont validés",
               "suivre un robot en mode fantôme (argent fictif, prix en direct)"],
        "en": ["measure an idea on ~42 days of real prices (how often it fires, the direction N minutes later, against random moments)",
               "compare up to four versions of an idea", "replay this chat's robot (trades, won %, by hour / weekday / session / half, with the control)",
               "explain one REAL trade of their account (entry, exit, best and worst moment, its chart)", "search their past conversations",
               "put several robots side by side (result, worst dip, shared days)", "launch a robot's official test (42 days, costs in) once the moments are checked",
               "follow a robot in ghost mode (pretend money, live prices)"],
    },
}
PLAIN = {
    "PermissionError": ("L'app était occupée une seconde de mon côté ; je reprends.", "The app was busy for a second on my side; I'm picking it back up."),
    "TimeoutError": ("J'ai mis trop de temps à réfléchir ; je reprends.", "I took too long to think; I'm picking it back up."),
    "default": ("J'ai buté sur un bout de code de mon côté ; je reprends ta question.", "I tripped on a bit of code on my side; I'm taking your question again."),
    "twice": ("J'ai buté deux fois de suite de mon côté, et je ne veux pas te faire attendre pour rien : redis-le moi en d'autres mots, ou plus tard.",
              "I tripped twice in a row on my side, and I won't keep you waiting for nothing: say it again in other words, or later."),
}


def _log(cid, what, why=""):
    try:
        io.open(LOG, "a", encoding="utf-8").write("%s %s %s | %s\n" % (time.strftime("%m-%d %H:%M:%S"), cid, what, str(why)[:200].replace("\n", " ")))
    except Exception:
        pass


# ---------------------------------------------------------------- ledger ------------------------------------------------
def _load():
    try:
        return json.load(open(LEDGER, encoding="utf-8"))
    except Exception:
        return {"items": [], "n": 0}


def _save(d):
    d["items"] = d["items"][-600:]
    tmp = LEDGER + ".%d.tmp" % threading.get_ident()
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    for _ in range(40):
        try:
            os.replace(tmp, LEDGER)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, LEDGER)


def _mut(fn):
    with _LOCK:
        d = _load()
        out = fn(d)
        _save(d)
        return out


def start(uid, cid, kind, what="", state=None, err=""):
    """code starts an action -> a job (the open job of the same kind for this chat is superseded)"""
    kind = kind if kind in KINDS else "measure"
    state = state or ("running" if kind in ("build", "measure") else "queued")

    def f(d):
        for x in d["items"]:
            if x["cid"] == cid and x["kind"] == kind and x["state"] in ("queued", "running"):
                x["state"], x["t_end"], x["err"] = "superseded", int(time.time()), ""
        d["n"] = int(d.get("n") or 0) + 1
        j = {"id": "j%d" % d["n"], "uid": uid, "cid": cid, "kind": kind, "what": str(what or "")[:80], "state": state, "t": int(time.time()),
             "t_end": int(time.time()) if state in ("done", "failed") else None, "err": str(err or "")[:120]}
        d["items"].append(j)
        return j["id"]
    jid = _mut(f)
    _log(cid, "JOB_" + state.upper(), "%s %s %s %s" % (jid, kind, what, err))
    return jid


def finish(cid, kind, state="done", err=""):
    """the open job of this kind for this chat ends: done | failed"""
    def f(d):
        for x in reversed(d["items"]):
            if x["cid"] == cid and x["kind"] == kind and x["state"] in ("queued", "running"):
                x["state"], x["t_end"], x["err"] = state, int(time.time()), str(err or "")[:120]
                return x["id"]
        return None
    jid = _mut(f)
    if jid:
        _log(cid, "JOB_" + state.upper(), "%s %s %s" % (jid, kind, err))
    return jid


def open_jobs(cid):
    return [x for x in _load()["items"] if x["cid"] == cid and x["state"] in ("queued", "running")]


def recent(cid, kind, secs=RECENT_S):
    now = time.time()
    return [x for x in _load()["items"] if x["cid"] == cid and x["kind"] == kind and now - x["t"] < secs]


def jobs_block(c, lang="fr"):
    """for the fresh facts: what is really queued / running for this chat"""
    cid = c.get("id")
    J = open_jobs(cid)
    t = c.get("test") or {}
    parts = []
    for x in J:
        parts.append("%s %s since %d min%s" % (x["kind"], x["state"], (time.time() - x["t"]) // 60, (" (%s)" % x["what"]) if x.get("what") else ""))
    if t.get("state") in ("queued", "running") and not any(x["kind"] == "test" for x in J):
        parts.append("test %s since %s" % (t.get("state"), str(t.get("at") or "")[11:16]))
    last = [x for x in _load()["items"] if x["cid"] == cid and x["state"] in ("done", "failed")][-2:]
    for x in last:
        parts.append("%s %s %d min ago%s" % (x["kind"], x["state"], (time.time() - (x.get("t_end") or x["t"])) // 60, (": " + x["err"]) if x.get("err") else ""))
    return "YOUR JOBS RIGHT NOW (the only actions really running for this conversation - 'je lance' is true only when one is here or you set act/build this turn): %s" % (
        "; ".join(parts) if parts else "none - nothing is queued or running")


# ---------------------------------------------------------------- capability --------------------------------------------
def _can():
    try:
        d = json.load(open(CANF, encoding="utf-8"))
        if isinstance(d, dict) and d.get("cannot"):
            return d
    except Exception:
        pass
    return CAN


def can_block(lang="fr"):
    d = _can()
    L = d.get("can", {}).get("en" if lang == "en" else "fr") or []
    N = [x.get("en" if lang == "en" else "fr") for x in d.get("cannot", [])]
    ui = (d.get("ui") or CAN.get("ui") or {}).get("en" if lang == "en" else "fr") or ""
    return ("WHAT YOU CAN DO HERE (your tools, the truth about your reach): %s.\nWHAT YOU CANNOT DO - never promise these, say so on the first ask: %s\n"
            "WHERE THINGS ARE IN THE APP: %s" % ("; ".join(L), " | ".join(N), ui))


def cannot_hit(sentence, lang="fr"):
    for x in _can().get("cannot", []):
        try:
            if re.search(x["rx"], sentence, re.I):
                return x.get("en" if lang == "en" else "fr") or x.get("fr")
        except Exception:
            continue
    return None


# ---------------------------------------------------------------- bind ---------------------------------------------------
def _T(lang, fr, en):
    return en if lang == "en" else fr


_EN_W = re.compile(r"\b(the|and|you|your|it|is|are|i'?m|i'?ll|now|test|with|that|this|here|again|right|when|what)\b", re.I)
_FR_W = re.compile(r"\b(le|la|les|et|tu|ton|ta|tes|est|sont|je|on|maintenant|avec|que|ce|cette|ici|encore|quand|quoi|pas|une|un|des)\b", re.I)


def lang_of(text, default="fr"):
    """the language the bubble is written in (its replacements must match it)"""
    e, f = len(_EN_W.findall(text or "")), len(_FR_W.findall(text or ""))
    if e == f:
        return default
    return "en" if e > f else "fr"


def bind(c, m, intent=None, lang="fr", H=None):
    """the gate at send time (see module doc). Never touches the app: H = {"check": fn(c) -> 'ok'|'open'|'no'|'none',
    "building": fn(cid) -> bool}. Returns m with its text possibly rewritten, m["deed"] = what happened, m["deed_todo"] = the
    actions the server must start once the bubble is saved."""
    text = str(m.get("text") or "")
    if not text.strip() or m.get("err"):
        return m
    intent, H = intent or {}, H or {}
    cid = c.get("id")
    lang = lang_of(text, lang)
    S = _SENT.split(text.strip())
    out, did, todo = [], [], []      # out = (sentence, replacement) pairs
    t = c.get("test") or {}
    for s in S:
        s2 = s
        reason = cannot_hit(s, lang)
        if reason:
            s2 = reason
            did.append("cannot")
            _log(cid, "CANNOT", s[:120])
        elif not _NOT_NOW.search(s) and not _PAST.search(s):
            kind = next((k for k in ("luck", "ghost", "build", "test") if CLAIM[k].search(s)), None)
            if kind == "test":
                if intent.get("act") == "test" or t.get("state") in ("queued", "running") or recent(cid, "test"):
                    did.append("test_ok")
                else:
                    try:
                        st = H["check"](c) if H.get("check") else "ok"
                    except Exception:
                        st = "ok"
                    if not c.get("robot"):
                        s2 = _T(lang, "Je ne peux pas lancer de test ici : il n'y a pas encore de robot dans cette conversation.",
                                "I can't start a test here: there is no robot in this conversation yet.")
                        did.append("test_norobot")
                    elif st == "none":
                        s2 = _T(lang, "Avant le test, je te mets les 5 derniers moments où il aurait tradé juste en dessous : ✅ ou ❌ sous chacun, puis il part.",
                                "Before the test, I'm putting the last 5 moments where it would have traded right below: ✅ or ❌ under each one, then it runs.")
                        todo.append("fires")
                        did.append("test_fires")
                    elif st != "ok":
                        s2 = _T(lang, "Le test attend tes ✅ / ❌ sous chaque moment, dans la conversation : dès que c'est fait, il part.",
                                "The test waits for your ✅ / ❌ under each moment, in the conversation: as soon as that's done, it goes.")
                        did.append("test_blocked")
                    else:
                        todo.append("test")
                        did.append("test_launch")
                    _log(cid, "TEST_CLAIM", "%s -> %s" % (s[:80], did[-1]))
            elif kind == "build":
                if intent.get("build") or recent(cid, "build") or (H.get("building") and H["building"](cid)):
                    did.append("build_ok")
                else:
                    if c.get("robot") is not None or c.get("idea_pending") or c.get("idea"):
                        todo.append("build")
                        did.append("build_launch")
                    else:
                        s2 = _T(lang, "Je le monte dès que l'idée est posée : dis-moi le marché et quand il entre.",
                                "I'll build it as soon as the idea is set: tell me the market and when it gets in.")
                        did.append("build_noidea")
                    _log(cid, "BUILD_CLAIM", "%s -> %s" % (s[:80], did[-1]))
            elif kind == "luck":
                if intent.get("act") == "luck" or recent(cid, "luck"):
                    did.append("luck_ok")
                else:
                    s2 = _T(lang, "Le test de chance se met en file tout seul quand le test normal est bon ; je ne le lance pas à la main.",
                            "The luck test queues itself once the normal test is good; I don't start it by hand.")
                    did.append("luck_rewrite")
                    _log(cid, "LUCK_CLAIM", s[:80])
            elif kind == "ghost":
                if intent.get("act") in ("ghost", "duel") or recent(cid, "ghost"):
                    did.append("ghost_ok")
                elif c.get("robot"):
                    todo.append("ghost")
                    did.append("ghost_launch")
                    _log(cid, "GHOST_CLAIM", "%s -> launch" % s[:80])
                else:
                    s2 = _T(lang, "Le mode fantôme se lance depuis la conversation du robot lui-même ; ouvre-la et je le mets en route là-bas.",
                            "Ghost mode starts from the robot's own conversation; open it and I'll start it there.")
                    did.append("ghost_rewrite")
                    _log(cid, "GHOST_CLAIM", s[:80])
        if s2 != s:
            out.append((s, s2))
    if did:
        m["deed"] = did
    if todo:
        m["deed_todo"] = todo
    if out:
        new = text
        for s, s2 in out:
            new = new.replace(s, s2, 1)
        m["text"] = new
        _log(cid, "REWRITE", ",".join(did))
    return m


# ---------------------------------------------------------------- failures ----------------------------------------------
def plain(e, lang="fr", twice=False):
    """what the member reads when something broke - never an exception name"""
    if twice:
        return PLAIN["twice"][1 if lang == "en" else 0]
    k = type(e).__name__ if e is not None else "default"
    if k in ("PermissionError", "FileExistsError", "OSError"):
        k = "PermissionError"
    elif "Timeout" in k:
        k = "TimeoutError"
    p = PLAIN.get(k) or PLAIN["default"]
    return p[1 if lang == "en" else 0]


def counts(day_label):
    out = {"claims": 0, "launched": 0, "rewritten": 0, "cannot": 0, "jobs_failed": 0}
    try:
        for l in io.open(LOG, encoding="utf-8").read().splitlines():
            if not l.startswith(day_label):
                continue
            if "_CLAIM " in l:
                out["claims"] += 1
            if "_launch" in l:
                out["launched"] += 1
            if " REWRITE " in l:
                out["rewritten"] += 1
            if " CANNOT " in l:
                out["cannot"] += 1
            if " JOB_FAILED " in l:
                out["jobs_failed"] += 1
    except Exception:
        pass
    return out
