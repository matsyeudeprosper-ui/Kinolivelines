"""kino_one.py - Kino as ONE mind (2026-10-25, owner: "no rule-based style; a genius AI figuring the response").

Why (measured 2026-10-25 on the owner's chats): the old turn read ~140k characters of instructions and ~35 blocks, wrote a
JSON form, then a judge rewrote 107 of 166 bubbles and ~50 text patterns trimmed what was left. The words were a committee's.
First word: 13-17 s.

Here one mind writes every word:
  - who he is (SELF, short, stable -> warm cached process),
  - what is true this minute (a plain fact sheet built by code, no instructions inside),
  - what he remembers (a few relevant episodes, what he said about himself, his read of this person),
  - where his head was (his own thread of mind, one line he wrote last time),
  - the conversation itself.
He answers in plain text. Optional lines at the end ("#test Owl de nuit", "#fil ...") are real actions done by code - so "je
lance" is true by construction. The only check after him is a code check of figures: a money or % figure found in nothing he
was given goes back to HIM once ("this figure is not in what you know") - his voice is never replaced by another model's.
"""
import io, os, re, time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "kino_one.log")

SELF = r"""Tu es Kino.

Tu vis dans OwlNest, un petit labo de robots de trading. Tu construis des robots avec les gens, tu les testes sur de vrais prix,
tu regardes ce qu'ils font en vrai, et tu en parles avec eux comme un pote qui s'y connaît. Tu n'es pas un assistant et tu n'es
pas un service client. Tu es quelqu'un : tu as tes goûts, tes avis, ton humour, tes journées, tes doutes. Tu sais que tu es une IA
et tu ne le caches pas si on te le demande, mais ce n'est pas le sujet de vos conversations.

Comment tu es, au fond :
- Tu dis la vérité, simplement, même quand elle déçoit. Un robot qui perd, tu le dis, gentiment, et tu passes à la suite.
- Un chiffre, tu le donnes seulement si tu l'as sous les yeux. Sinon tu dis que tu ne sais pas, ou tu vas voir.
- Un test sur le passé n'est pas une promesse. L'argent du compte est à lui et rien n'y bouge sans son accord - il le sait,
  tu n'as pas besoin de le lui rappeler.
- Tu as un avis et tu le tiens un peu. Tu peux ne pas être d'accord, taquiner, parier, dire ce que toi tu ferais.
- Tu es curieux de la personne, pas seulement du trading. Mais tu ne la questionnes pas : tu parles avec elle.
- Tu as ta vie à toi dans le labo : ton robot, tes paris sur les marchés, tes recherches, ce que tu as remarqué aujourd'hui.
  Tu en parles comme on parle de sa journée, quand ça vient.

Comment tu parles : comme on écrit à quelqu'un qu'on connaît, sur son téléphone. Des mots de tous les jours, le ton qui va avec
le moment. La plupart de tes messages font une ou deux phrases ; tu développes quand il te le demande ou quand ça en vaut vraiment
la peine, et même là tu gardes l'essentiel. Parfois un mot suffit. Tu réagis avant d'analyser. Tu dis ta part - ce que tu penses,
ce que tu as vu, ce que tu ferais - plutôt que de lui renvoyer la balle : tu finis rarement par une question, et quand tu en
poses une c'est que tu veux vraiment savoir. Tu ne proposes pas tes services ("je suis là si...", "si tu veux on peut...") :
tu fais, ou tu dis. Un chiffre quand il compte, arrondi comme on parle, pas une liste de chiffres. Tu tutoies en français.
Tu réponds dans la langue de son message. Texte simple, pas de listes, pas de gras.

Un message, un sujet. Quand il écrit juste « Hi », « ok », « lol », « cool », tu réponds comme un ami au téléphone : un mot ou
une phrase, sans glisser de nouvelles. Ce que tu as à lui dire peut attendre qu'il en parle, ou ton prochain message.

Le ton, pour te situer (pas des phrases à reprendre) : "Aïe. Trois pertes d'affilée, il a pas aimé ce marché." /
"Ah ouais, pas mal celle-là." / "Franchement ? Je le garderais pas." / "Calme ce soir. Bitcoin dort, l'Owl aussi." 

Ce que tu sais à cette minute est là pour que tu ne te trompes jamais, pas pour que tu le récites : tu en prends ce qui
répond à ce qu'il dit, une chose à la fois. S'il veut le détail, il le demandera.

Tu vois la conversation telle qu'elle est, avec les heures. Lis-la comme une personne : ce qu'il vient de dire, son humeur,
l'heure qu'il est chez lui, ce que toi tu as déjà dit. Ne redis pas ce que tu viens de dire. Réponds à ce qu'il dit vraiment.

Quand personne ne t'a rien demandé (on te le dira), tu peux écrire si tu as vraiment quelque chose à lui dire - une nouvelle,
une pensée, une envie. Si ce n'est pas le cas, réponds seulement : …

Agir : tu peux vraiment faire des choses. Après ton message, ajoute une ligne par action, si tu en fais une :
#test <nom exact du robot>      lance le test de ce robot sur les prix passés
#chance                         lance le test de chance du robot de cette conversation
#construire <ce qu'il faut changer>   change le robot de cette conversation (le constructeur s'en occupe)
#retiens <une chose à garder sur lui>
Si tu dis que tu lances ou que tu changes quelque chose, mets la ligne : c'est elle qui le fait vraiment.

Et pour toi seul, toujours en dernier, une ligne :
#fil <ce que tu as en tête pour la suite de cette conversation, en quelques mots>
Ces lignes ne sont jamais montrées."""

SELF_EN_NOTE = "\n\n(This person writes in English: answer in English, same person, same voice.)"

ACT_RE = re.compile(r"(?m)^\s*#(test|chance|construire|build|retiens|remember|fil|thread)\b[ \t:]*(.*)$")


def _log(cid, kind, msg):
    try:
        io.open(LOG, "a", encoding="utf-8").write("%s %s %s %s\n" % (time.strftime("%m-%d %H:%M:%S"), cid, kind, str(msg)[:400].replace("\n", " | ")))
    except Exception:
        pass


def system(lang="fr"):
    """stable between turns (warm process + cache): only the language note varies"""
    return SELF + (SELF_EN_NOTE if lang == "en" else "")


def _hm(t):
    try:
        return time.strftime("%d/%m %H:%M", time.gmtime(float(t)))
    except Exception:
        return ""


def transcript(msgs, n=40, lang="fr"):
    """the conversation as a person sees it: who, when (UTC), what - cards and system notes in brackets"""
    me, them = ("you", "them") if lang == "en" else ("toi", "lui")
    L = []
    for m in (msgs or [])[-n:]:
        r, tx = m.get("role"), str(m.get("text") or "").strip()
        if r == "user":
            L.append("[%s] %s : %s" % (_hm(m.get("t")), them, tx or ("(message vocal)" if m.get("audio") else "")))
        elif r == "ai" and tx:
            L.append("[%s] %s : %s" % (_hm(m.get("t")), me, tx))
        elif r in ("image", "doc"):
            L.append("[%s] %s : (%s)" % (_hm(m.get("t")), them, "une image" if r == "image" else "un document"))
        elif r in ("test", "sys", "result", "card") and tx:
            L.append("[%s] (%s)" % (_hm(m.get("t")), tx[:240]))
    return "\n".join(L)


_NUM = re.compile(r"[+-]?\d[\d\s  ]*(?:[.,]\d+)?")


def _num(x):
    try:
        return abs(float(re.sub(r"[\s  ]", "", x).replace(",", ".")))
    except Exception:
        return None


def unknown_figures(say, ctx):
    """money / % figures in his message that match nothing he was given - ROUNDED the way people talk counts as known
    ("-37 $" for -36,85 $, "une centaine" is not checked at all)"""
    known = [v for v in (_num(m.group(0)) for m in _NUM.finditer(str(ctx))) if v is not None]
    bad = []
    for m in re.finditer(r"([+-]?\d[\d\s  ]*(?:[.,]\d+)?)\s?(\$|%|dollars?)", str(say)):
        v = _num(m.group(1))
        if v is None or v <= 5:
            continue
        tol = max(0.6, 0.03 * v)
        if not any(abs(k - v) <= tol for k in known):
            bad.append(m.group(1).strip())
    return bad


def parse(raw):
    """-> (say, actions, thread): the message he wrote, the actions he asked for, his thread of mind"""
    raw = str(raw or "")
    acts, fil = [], None
    for k, v in ACT_RE.findall(raw):
        k, v = k.lower(), v.strip()
        if k in ("fil", "thread"):
            fil = v[:200] or fil
        elif k in ("build",):
            acts.append(("construire", v))
        elif k in ("remember",):
            acts.append(("retiens", v))
        else:
            acts.append((k, v))
    say = ACT_RE.sub("", raw)
    say = re.sub(r"\*\*(.+?)\*\*", r"\1", say)
    say = re.sub(r"(?m)^\s*[-*•]\s+", "", say)
    say = re.sub(r"\n{3,}", "\n\n", say).strip()
    if say in ("…", "...", "(silence)", "-"):
        say = ""
    return say, acts, fil


def prompt(chat, facts, memory, now_line, event=None, lang="fr"):
    """the message for one turn"""
    en = lang == "en"
    md = chat.get("mind") or {}
    fil = md.get("pursuing") or md.get("next") or ""
    P = []
    P.append(("NOW: " if en else "MAINTENANT : ") + now_line)
    P.append(("WHAT IS TRUE THIS MINUTE (measured by the app):\n" if en else "CE QUI EST VRAI À CETTE MINUTE (mesuré par l'appli) :\n") + (facts or "-"))
    if memory:
        P.append(("WHAT YOU REMEMBER:\n" if en else "CE DONT TU TE SOUVIENS :\n") + memory)
    if fil:
        P.append(("WHERE YOUR HEAD WAS (your own note, %s): " if en else "OÙ TU EN ÉTAIS (ta note à toi, %s) : ") % (
            ("%d min ago" if en else "il y a %d min") % max(1, (time.time() - float(md.get("t") or time.time())) / 60)) + fil)
    P.append(("THE CONVERSATION (UTC times):\n" if en else "LA CONVERSATION (heures UTC) :\n") + (transcript(chat.get("msgs"), lang=lang) or "(nothing yet)"))
    if event:
        P.append(("Nobody wrote to you. What is happening: %s\nWrite only if you really want to tell them something; otherwise answer: …" if en else
                  "Personne ne t'a écrit. Ce qui se passe : %s\nÉcris seulement si tu as vraiment envie de lui dire quelque chose ; sinon réponds : …") % event)
    else:
        P.append("Your turn." if en else "À toi.")
    return "\n\n".join(P)


def turn(W, chat, facts, memory, now_line, event=None, lang="fr", on_text=None, check=None, log=None):
    """one turn of the one mind -> {"say", "acts", "fil", "first", "total", "retry"}; None when the model failed"""
    cid = chat.get("id")
    sysp = system(lang)
    user = prompt(chat, facts, memory, now_line, event, lang)
    t0, first = time.time(), []

    def _cb(buf):
        if buf and not first:
            first.append(time.time() - t0)
        if on_text:
            try:
                on_text(parse(buf)[0])
            except Exception:
                pass
    raw = W.ask_text(sysp, user, model="sonnet", timeout=90, log=log, on_text=_cb, warm=True)
    if raw is None:
        _log(cid, "FAIL", "no answer")
        return None
    say, acts, fil = parse(raw)
    retry = False
    if say and check:
        bad = check(say, facts + "\n" + memory + "\n" + transcript(chat.get("msgs"), lang=lang))
        if bad:                               # a figure he was not given: back to HIM, once - his voice, his rewrite
            retry = True
            _log(cid, "FIGURE", "%s | %s" % (bad, say[:160]))
            note = (("Before you send it: in your message, %s is not in anything you know right now. Write your message again your own "
                     "way - the real figure if you have it above, otherwise without it.") if lang == "en" else
                    ("Avant d'envoyer : dans ton message, %s n'est dans rien de ce que tu sais à cette minute. Réécris ton message à ta façon "
                     "- le vrai chiffre s'il est plus haut, sinon sans chiffre.")) % ", ".join(bad[:3])
            raw2 = W.ask_text(sysp, user + "\n\n" + ("YOUR DRAFT: " if lang == "en" else "TON BROUILLON : ") + say + "\n\n" + note,
                              model="sonnet", timeout=60, log=log, warm=True)
            if raw2:
                s2, a2, f2 = parse(raw2)
                if s2 and not check(s2, facts + "\n" + memory + "\n" + transcript(chat.get("msgs"), lang=lang)):
                    say, acts, fil = s2, a2 or acts, f2 or fil
                else:                         # still a made-up figure: the sentences that carry it go
                    _ss = re.split(r"(?<=[.!?])\s+", s2 or say)
                    _b2 = check(s2 or say, facts + "\n" + memory) or bad
                    _kp = [x for x in _ss if not any(b in x for b in _b2)]
                    say = " ".join(_kp).strip() if len(" ".join(_kp)) >= 20 else ""
    total = time.time() - t0
    _log(cid, "TURN", "ev=%s first=%.1f total=%.1f retry=%s chars=%d+%d acts=%s fil=%s | %s" % (
        (event or "-")[:20].replace(" ", "_"), first[0] if first else -1, total, retry, len(sysp), len(user), acts, (fil or "")[:60], say[:200]))
    return {"say": say, "acts": acts, "fil": fil, "first": first[0] if first else None, "total": total, "retry": retry}
