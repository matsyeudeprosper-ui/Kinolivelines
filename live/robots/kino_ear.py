"""kino_ear.py (2026-10-24, Kino v2 engine 4 - see KINO_V2_ENGINES.md): listen before speaking.

Tester points 9, 10, 11, 12: answered a different question ("j'ai un trade en cours ?" -> the best advice you ever got),
the restaurant and the jacket to someone who had just said he has no money, "ta phrase s'est coupée" four times in an
evening, French answers to English lines and back. One cause: the quick turn generated before anything had decided what
was asked, in which language, under which constraint of theirs. Here, with no model call (zero latency):

  read(text, prev_ai)       -> {"asked": one of ASKED or null, "question": bool, "lang": fr|en|null, "short": bool,
                                "refers": "own_prev"|null, "words": n}   stored on the member's message as "ear"
  ask_block(ear, lang)      -> one line for the fresh facts: WHAT THEY JUST ASKED, answer that first
  answer_check(ear, say, facts) -> the say with the asked figure put first when it is missing (open trade P&L, today,
                                week, balance) - they asked a number they are entitled to; it is in the facts; it goes first
  constraints               things they said about themselves that must never be contradicted ("pas d'argent", "sur
                                mobile", "pas le temps", "débutant"...): learned from their messages by regex, kept per
                                member in robots/kino_ear.json, printed as THEIR CONSTRAINTS in the fresh facts
  reply_lang(text, default) -> the language of THIS message when it is unambiguous and has 4+ words, else the default
                                (robot_chat.prompt uses it for the quick turn; his own messages keep the dominant language)
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(HERE, "kino_ear.json")
_LOCK = threading.Lock()

ASKED = {
    "open_trade_pnl": r"(trade (en cours|ouvert|actuel)|position (en cours|ouverte)|il (gagne|perd)|combien (il|ça) (gagne|perd|fait)|(how|what).{0,20}(open|current) (trade|position)|"
                      r"is (it|the trade) (winning|losing)|a gagné \?|ça a gagné)",
    "today": r"(aujourd'?hui|today|ce matin|this morning|en ce moment on a|on est à combien|on a combien|how much (are we|do we have)|where are we)",
    "week": r"(cette semaine|this week|la semaine|semaine passée|last week)",
    "balance": r"(solde|balance|le compte (est|fait)|combien j'ai|how much (do )?i have|what'?s my balance)",
    "robot_state": r"(il tourne|is it running|quel robot|which (bot|robot)|in (random|luck) test|test de chance (en cours|actuel)|what'?s (running|in the queue)|qu'est[- ]ce qui (tourne|est en cours))",
    "why_loss": r"(pourquoi.{0,30}(perdu|perte|pertes|loss|losses)|why.{0,30}(lost|loss|losses|losing)|(losses?|pertes?|perdu)\s+(why|pourquoi)|c'est quoi ce trade)",
    "where_vote": r"(où.{0,20}voter|where.{0,20}vote|je vois pas (de|le) (panel|panneau)|pas de tick|no tick|comment (je )?vote)",
    "when": r"(quand|when|combien de temps|how long|à quelle heure|what time|dans combien)",
    "explain": r"(explique|explain|c'est quoi|what is|what does|ça veut dire|comment ça marche|how does)",
}
CONSTRAINTS = {
    "no_money": (r"(pas d'argent|pas les moyens|j'ai pas de sous|fauché|no money|can't afford|broke)", "ils n'ont pas d'argent à dépenser (jamais de resto / vêtements / sorties à acheter)",
                 "they have no money to spend (never suggest a restaurant / clothes / outings to buy)"),
    "mobile": (r"(sur mobile|sur (mon|le) téléphone|on (my )?(phone|mobile)|depuis le téléphone)", "ils sont sur téléphone (pas de panneau latéral, tout est dans la conversation)",
               "they are on a phone (no side panel, everything is in the conversation)"),
    "no_time": (r"(pas le temps|j'ai pas le temps|no time|pressé|in a hurry)", "ils ont peu de temps (court, utile, pas de digression)", "they have little time (short, useful, no digression)"),
    "beginner": (r"(débutant|je débute|je connais rien|beginner|i'm new|je suis nul)", "ils débutent (mots simples, pas de jargon)", "they are a beginner (simple words, no jargon)"),
    "fear_loss": (r"(peur des pertes|j'ai peur de perdre|afraid of (losing|losses)|scared of losing)", "ils ont peur des pertes (le creux compte plus que le gain pour eux)",
                  "they fear losses (the dip matters more than the gain to them)"),
    "small_regular": (r"(petit et régulier|petit mais régulier|small and (regular|steady)|chaque semaine un peu)", "ils préfèrent petit et régulier (pas de gros pari)",
                      "they prefer small and regular (no big bet)"),
}
_EN_W = re.compile(r"\b(the|and|you|your|it|is|are|i'?m|i'?ll|now|with|that|this|here|again|right|when|what|how|why|do|does|can|should|we|be)\b", re.I)
_FR_W = re.compile(r"\b(le|la|les|et|tu|ton|ta|tes|est|sont|je|on|maintenant|avec|que|ce|cette|ici|encore|quand|quoi|pas|une|un|des|pour|comment|pourquoi|peux|peut|faut)\b", re.I)
CUTOFF = re.compile(r"(ta phrase s'est coupée|tu voulais dire quoi \?|la fin de ta phrase|your sentence (got )?cut|i lost the end of your sentence)", re.I)


def _load():
    try:
        return json.load(open(F, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LOCK:
        d = _load()
        fn(d)
        tmp = F + ".%d.tmp" % threading.get_ident()
        io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
        for _ in range(20):
            try:
                os.replace(tmp, F)
                return
            except PermissionError:
                time.sleep(0.05)


def reply_lang(text, default="fr"):
    t = str(text or "")
    if len(t.split()) < 4:
        return default
    e, f = len(_EN_W.findall(t)), len(_FR_W.findall(t))
    if e == 0 and f == 0 or abs(e - f) < 2:
        return default
    return "en" if e > f else "fr"


def read(text, prev_ai=""):
    t = str(text or "").strip()
    low = t.lower()
    asked = next((k for k, rx in ASKED.items() if re.search(rx, low)), None)
    words = len(re.findall(r"\w+", t))
    q = t.endswith("?") or bool(re.match(r"^(est[- ]ce|qu'est|quel|quelle|combien|pourquoi|comment|quand|où|who|what|when|where|why|how|is|are|do|does|can|could|should|will)\b", low))
    refers = "own_prev" if re.search(r"^(et (alors|donc)|and\??$|ok\. and|ça veut dire|tu veux dire|the last (message|one)|le dernier message|ça aide en quoi|what do you mean)", low) else None
    return {"asked": asked, "question": q, "lang": reply_lang(t, None), "short": words <= 2, "refers": refers, "words": words}


def learn_constraints(uid, text):
    low = str(text or "").lower()
    hit = [k for k, (rx, _, _) in CONSTRAINTS.items() if re.search(rx, low)]
    if not hit:
        return []
    now = time.time()

    def f(d):
        u = d.setdefault(str(uid), {})
        for k in hit:
            u[k] = {"t": now, "said": str(text)[:120]}
    _mut(f)
    return hit


def constraints_block(uid, lang="fr"):
    u = _load().get(str(uid)) or {}
    now = time.time()
    L = []
    for k, x in u.items():
        if k in CONSTRAINTS and now - float(x.get("t") or 0) < 30 * 86400:
            L.append(CONSTRAINTS[k][2 if lang == "en" else 1] + (" (« %s »)" % x["said"][:60] if x.get("said") else ""))
    if not L:
        return ""
    return ("CE QU'ILS T'ONT DIT D'EUX - à ne jamais contredire : " if lang != "en" else "WHAT THEY TOLD YOU ABOUT THEMSELVES - never contradict it: ") + " | ".join(L)


def ask_block(ear, lang="fr"):
    if not ear or not ear.get("asked"):
        return ""
    names = {"open_trade_pnl": ("le résultat du trade ouvert, le chiffre", "the open trade's result, the figure"),
             "today": ("le résultat d'aujourd'hui, le chiffre", "today's result, the figure"), "week": ("le résultat de la semaine, le chiffre", "the week's result, the figure"),
             "balance": ("le solde, le chiffre", "the balance, the figure"), "robot_state": ("quel robot tourne / où en est le test (ÉTAT RÉEL)", "which robot runs / where the test stands (REAL STATE)"),
             "why_loss": ("POURQUOI ces trades ont perdu - regarde-les (trade_explain / le graphique), ne dis pas 'je ne peux pas les isoler'", "WHY those trades lost - look at them (trade_explain / the chart), never 'I can't single them out'"),
             "where_vote": ("où voter : sous chaque moment, dans la conversation", "where to vote: under each moment, in the conversation"),
             "when": ("QUAND - une heure ou une durée", "WHEN - a time or a duration"), "explain": ("une explication simple", "a simple explanation")}
    n = names.get(ear["asked"])
    if not n:
        return ""
    return ("CE QU'ILS VIENNENT DE DEMANDER : %s - réponds à ÇA en premier, en une phrase, avant tout le reste." % n[0]) if lang != "en" else (
        "WHAT THEY JUST ASKED: %s - answer THAT first, in one sentence, before anything else." % n[1])


def answer_check(ear, say, nd, lang="fr"):
    """they asked a figure the facts hold and the say has no figure: the figure goes first"""
    if not ear or not say or not nd:
        return say
    a = ear.get("asked")
    if a not in ("open_trade_pnl", "today", "week", "balance"):
        return say
    if re.search(r"[+\-−]?\d+[.,]\d+ ?\$|\d+ ?\$", say):
        return say
    fr = lang != "en"
    line = None
    try:
        if a == "open_trade_pnl":
            ol = nd.get("open_list") or []
            if ol:
                x = ol[0]
                line = ("Le trade ouvert est à %+.2f $ pour l'instant (%s %s)." % (float(x.get("pl") or 0), "vente" if str(x.get("d")) == "V" else "achat", x.get("sym") or "BTCUSD")) if fr else \
                       ("The open trade is at %+.2f $ right now (%s %s)." % (float(x.get("pl") or 0), "sell" if str(x.get("d")) == "V" else "buy", x.get("sym") or "BTCUSD"))
            else:
                line = "Aucun trade ouvert en ce moment." if fr else "No open trade right now."
        elif a == "today":
            line = ("Aujourd'hui : %+.2f $." % float(nd.get("today") or 0)) if fr else ("Today: %+.2f $." % float(nd.get("today") or 0))
        elif a == "week":
            line = ("Cette semaine : %+.2f $." % float(nd.get("week") or 0)) if fr else ("This week: %+.2f $." % float(nd.get("week") or 0))
        elif a == "balance":
            line = ("Le solde est à %.2f $." % float(nd.get("balance") or 0)) if fr else ("The balance is %.2f $." % float(nd.get("balance") or 0))
    except Exception:
        line = None
    return (line + " " + say) if line else say


def cutoff_once(say, msgs, now=None):
    """'ta phrase s'est coupée' at most once an hour per chat: otherwise the sentence goes"""
    if not say or not CUTOFF.search(say):
        return say
    now = now or time.time()
    for m in reversed(msgs or []):
        if now - float(m.get("t") or 0) > 3600:
            break
        if m.get("role") == "ai" and CUTOFF.search(str(m.get("text") or "")):
            S = [s for s in re.split(r"(?<=[.!?])\s+", say.strip()) if not CUTOFF.search(s)]
            return " ".join(S).strip() or say
    return say
