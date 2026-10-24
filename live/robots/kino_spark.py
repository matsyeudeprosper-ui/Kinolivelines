"""kino_spark.py (2026-10-24, Kino v2 engine 5 - owner: "he kept coming back to the same things, same notice; at some point he
lacks things to say. Make him creative, new things to talk about; the voids are still much").

Two faults, one engine:
  1. SAME NOTICE   his own messages circled on the same subjects (the vote, the queue, the ghost, the sermon) because the
                   initiative rotation only avoided the last four KINDS, never the SUBJECT. -> topic memory: every own message
                   gets a key (its salient words); a subject raised twice in 24 h is not raised again (dropped, logged).
  2. NOTHING NEW   the kinds all chewed the same prompt. -> fact packs built by CODE from real data, one angle at a time,
                   never the same angle twice in a week:
        numbers     their own trading, one angle: best / worst trade of the week, their best weekday, their best hour band,
                    buys vs sells, short vs long trades, the longest run, how the month compares with last month
        nugget      a trading idea in plain words (NUGGETS below, ~40), one not told yet, with a hook to their situation
        bet         a small playful call on the next hours (resolved by price through the belief engine)
        memory      something they said days ago in an older conversation ("tu te souviens, le 12 tu voulais...")
        whatif      one knob of their current robot to measure now (the build turn runs the tool)
        tale        one market that moved today outside their robots, in one line
     plus the kinds that already existed (test, goal, material, finding, human, market, followup, own).
  3. VOIDS         presence: when they are in the app or answered in the last 10 min, the gap between his messages is 5 min,
                   the "flat member" doubling is off and the own-bubble budget is 5 an hour (pace / voice read present()).

  state: robots/kino_spark.json {uid: {"topics": [{t, key, kind, cid}], "angles": {angle: t}, "nuggets": [ids], "bets": [...]}}
  log:   robots/spark.log
"""
import io, json, os, random, re, threading, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(HERE, "kino_spark.json")
LOG = os.path.join(HERE, "spark.log")
_LOCK = threading.Lock()
PRESENT = None            # set by the server: PRESENT(uid) -> bool (in the app < 2 min, or answered < 10 min)

STOP = set("""le la les un une des du de et ou à au aux en pour par sur avec sans dans que qui quoi dont où ce cet cette ces son sa ses
ton ta tes mon ma mes il elle on nous vous ils elles je tu est sont été être avoir ai as a ont pas ne plus moins très trop bien mal
peu aussi donc alors mais car comme si quand tout tous toute toutes rien chose faire fait dit dire voir vu encore déjà ici là
the and or to of in on for with without that this these those his her its my your our their is are was were be been have has had
do does did not no yes just very too also so then but because like when where what which who how all any some thing things
ok oui non ça ca cela ceci c'est j'ai t'es y a va vais vas aller""".split())
SUBJ = re.compile(r"(test de chance|luck test|fantôme|ghost|vote|moments?|file d'attente|queue|owl|nasdaq|bitcoin|btc|or\b|gold|xau|ustec|"
                  r"pmi|fed|cpi|nfp|stop|cible|target|creux|dip|drawdown|série|streak|promesse|promise|semaine|week|robot \w+)", re.I)

NUGGETS = [
    ("spread_toll", "le spread, c'est un péage payé à chaque passage : plus un robot trade souvent, plus il paie, même quand il a raison",
     "the spread is a toll paid at every crossing: the more a robot trades, the more it pays, even when it is right"),
    ("win_rate_lies", "55 % de trades gagnés peut perdre de l'argent : tout dépend de la taille des pertes à côté des gains",
     "55% winning trades can still lose money: it all depends on how big the losses are next to the wins"),
    ("dip_decides", "ce n'est pas le gain qui décide si tu tiens un robot, c'est le creux : celui qu'on supporte sans couper",
     "it is not the gain that decides whether you keep a robot, it is the dip: the one you can sit through without cutting"),
    ("test_vs_ghost", "un test rejoue le passé en accéléré ; le fantôme vit le présent à vitesse réelle : les deux disent des choses différentes",
     "a test replays the past at speed; ghost mode lives the present in real time: the two say different things"),
    ("beat_random", "battre le hasard veut dire : sur les mêmes jours, cent robots tirés au sort font moins bien que lui, sauf quelques-uns",
     "beating random means: on the same days, a hundred robots drawn at random do worse than it, all but a few"),
    ("night_market", "la nuit, le marché respire plus lentement : moins de monde, moins d'élan, les robots qui suivent la tendance s'endorment",
     "at night the market breathes slower: fewer people, less momentum, trend-following robots doze off"),
    ("stop_far", "un stop loin paraît plus sûr, mais il coûte plus cher à chaque fois qu'il est touché, et il l'est quand même",
     "a far stop looks safer, but it costs more each time it is hit, and it still gets hit"),
    ("one_change", "un seul changement à la fois, sinon on ne sait jamais qui a fait le travail : le réglage ou la chance",
     "one change at a time, otherwise you never know who did the work: the setting or luck"),
    ("streaks_normal", "six pertes d'affilée arrivent à un robot qui gagne une fois sur deux, environ une fois par centaine de trades",
     "six losses in a row happen to a robot that wins half the time, about once every hundred trades"),
    ("half_half", "quand tout le gain vient de la première moitié du test, la deuxième moitié est la vraie note",
     "when all the gain comes from the first half of the test, the second half is the real grade"),
    ("cost_horizon", "plus un trade est court, plus les coûts pèsent : sur un trade de deux minutes, le péage peut valoir le gain",
     "the shorter the trade, the heavier the costs: on a two-minute trade the toll can be worth the gain"),
    ("news_candle", "les chiffres américains de 15h45 font une bougie énorme, puis le marché fait souvent comme si de rien n'était",
     "the 15:45 US figures print a huge candle, then the market often behaves as if nothing happened"),
    ("size_matters", "doubler le lot double le gain et double le creux : la courbe ne change pas de forme, juste d'échelle",
     "doubling the lot doubles the gain and doubles the dip: the curve keeps its shape, only its scale changes"),
    ("regime", "un robot a un terrain : calme ou agité, qui monte ou qui tourne en rond ; hors de son terrain il perd, même bien réglé",
     "a robot has a terrain: calm or wild, trending or sideways; off its terrain it loses, even well tuned"),
    ("survivor", "sur dix idées qui ont l'air bonnes, neuf meurent au test : ce n'est pas un échec, c'est le tri",
     "of ten ideas that look good, nine die in the test: that is not failure, that is the sorting"),
    ("patience_cost", "attendre une confirmation coûte quelques points d'entrée ; ne pas attendre coûte les faux départs : on paie l'un ou l'autre",
     "waiting for confirmation costs a few points of entry; not waiting costs the false starts: you pay one or the other"),
    ("hour_bias", "chaque marché a ses heures : l'or bouge à l'ouverture de Londres et à 15h45, le Bitcoin n'a pas d'heure",
     "each market has its hours: gold moves at the London open and at 15:45, Bitcoin has no clock"),
    ("curve_shape", "deux robots avec le même gain final peuvent avoir deux vies : l'un régulier, l'autre un grand coup et des mois à plat",
     "two robots with the same final gain can have two lives: one steady, the other a big hit and months flat"),
    ("overfit", "un réglage qui colle parfaitement au passé colle rarement au futur : le passé n'a qu'une seule version",
     "a setting that fits the past perfectly rarely fits the future: the past has only one version"),
    ("sample_size", "trente trades, c'est une impression ; deux cents, ça commence à être une mesure",
     "thirty trades is an impression; two hundred starts to be a measurement"),
    ("risk_pct", "risquer 3 % par trade, ça veut dire qu'une série de dix pertes coûte un quart du compte",
     "risking 3% a trade means a run of ten losses costs a quarter of the account"),
    ("drawdown_math", "perdre 50 % demande ensuite +100 % pour revenir : le creux se paie deux fois",
     "losing 50% then needs +100% to get back: the dip is paid twice"),
    ("correlation", "deux robots qui perdent les mêmes jours ne font pas deux robots : ils font un robot avec le lot doublé",
     "two robots that lose on the same days are not two robots: they are one robot with a doubled lot"),
    ("expectancy", "ce qui compte, c'est le gain moyen par trade après coûts ; le reste, c'est de la décoration",
     "what counts is the average gain per trade after costs; the rest is decoration"),
    ("weekend", "le week-end, seul le Bitcoin travaille, avec moins de monde : les mouvements sont plus secs et plus rares",
     "at the weekend only Bitcoin works, with fewer people: moves are drier and rarer"),
    ("retest", "après une cassure, le prix revient souvent toucher le niveau cassé : ceux qui entrent là paient moins cher, mais ratent les départs francs",
     "after a break, price often comes back to touch the broken level: those who enter there pay less, but miss the clean departures"),
    ("storm", "quand les bougies font trois fois leur taille habituelle, la plupart des règles mentent : c'est le moment de ne rien faire",
     "when candles are three times their usual size, most rules lie: that is the moment to do nothing"),
    ("time_stop", "une sortie au temps ('4 heures max') enlève les longs trades qui traînent ; elle enlève aussi parfois le gros gagnant",
     "a time exit ('4 hours max') removes the long trades that drag; it also sometimes removes the big winner"),
    ("bullets", "une balle de rattrapage, c'est doubler sur une idée qui vient de perdre : ça marche quand la perte était du bruit, pas quand c'était un signal",
     "a catch-up bullet is doubling on an idea that just lost: it works when the loss was noise, not when it was a signal"),
    ("luck_bias", "on se souvient des trades gagnés, le compte se souvient de tous",
     "we remember the trades we won; the account remembers all of them"),
    ("trend_def", "'tendance' veut dire des choses différentes selon la durée : haussier en 5 minutes, baissier en 1 heure, les deux vrais",
     "'trend' means different things by timeframe: up on 5 minutes, down on 1 hour, both true"),
    ("entry_vs_exit", "la plupart des gens travaillent l'entrée ; la plupart de l'argent se perd à la sortie",
     "most people work on the entry; most of the money is lost at the exit"),
    ("first_loss", "la première perte après un changement de robot fait toujours douter du changement, même quand elle n'a rien à voir",
     "the first loss after a robot change always makes you doubt the change, even when it had nothing to do with it"),
    ("slippage", "le prix affiché et le prix payé ne sont pas les mêmes quand ça bouge vite : l'écart s'appelle le glissement, et il va presque toujours contre toi",
     "the price shown and the price paid differ when it moves fast: the gap is called slippage, and it almost always goes against you"),
    ("quiet_hours_bot", "un robot qui ne trade pas pendant trois heures ne dort pas : il regarde et refuse, ce qui est aussi un travail",
     "a robot that does not trade for three hours is not asleep: it watches and declines, which is work too"),
    ("tiny_edge", "un avantage minuscule répété mille fois fait une fortune ; un gros avantage qui n'existe pas fait un trou",
     "a tiny edge repeated a thousand times makes a fortune; a big edge that does not exist makes a hole"),
]


def _log(uid, what, why=""):
    try:
        io.open(LOG, "a", encoding="utf-8").write("%s %s %s | %s\n" % (time.strftime("%m-%d %H:%M:%S"), uid, what, str(why)[:180].replace("\n", " ")))
    except Exception:
        pass


def _load():
    try:
        return json.load(open(F, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LOCK:
        d = _load()
        out = fn(d)
        tmp = F + ".%d.tmp" % threading.get_ident()
        io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
        for _ in range(20):
            try:
                os.replace(tmp, F)
                break
            except PermissionError:
                time.sleep(0.05)
        return out


def _u(d, uid):
    return d.setdefault(str(uid), {"topics": [], "angles": {}, "nuggets": [], "bets": []})


# ---------------------------------------------------------------- topic memory -----------------------------------------
def topic_key(text):
    """the subject of a message: its named things first, then its rarest content words"""
    t = str(text or "").lower()
    subj = sorted(set(m.group(0).strip().lower() for m in SUBJ.finditer(t)))
    words = [w for w in re.findall(r"[a-zà-ÿ']{4,}", t) if w not in STOP and not w.isdigit()]
    seen, rest = set(), []
    for w in words:
        if w not in seen:
            seen.add(w); rest.append(w)
    key = subj[:3] + rest[:4]
    return " ".join(key)


def _same(a, b):
    A, B = set(a.split()), set(b.split())
    return bool(A and B) and len(A & B) / max(1, min(len(A), len(B))) >= 0.6


def repeat_count(uid, text, hours=24):
    key = topic_key(text)
    if not key:
        return 0, key
    now = time.time()
    T = _u(_load(), uid)["topics"]
    return sum(1 for x in T if now - float(x.get("t") or 0) < hours * 3600 and _same(x.get("key") or "", key)), key


def note_topic(uid, text, kind="", cid=""):
    key = topic_key(text)
    if not key:
        return
    now = time.time()
    def f(d):
        u = _u(d, uid)
        u["topics"] = [x for x in u["topics"] if now - float(x.get("t") or 0) < 3 * 86400][-120:] + [
            {"t": now, "key": key, "kind": kind, "cid": cid, "text": str(text)[:400]}]
    _mut(f)


def _cwords(t):
    return set(w for w in re.findall(r"[a-zà-ÿ']{4,}", str(t or "").lower()) if w not in STOP)


def repeat_block(uid, text, cid=""):
    """for Voice: an own message on a subject already raised twice today, or saying half the same words as an own
    message of the last 24 h (measured on the 22-24 Oct chats: 0.5 catches "le tampon officiel est tombé à nouveau" x4
    and lets a new result through), is not sent"""
    n, key = repeat_count(uid, text)
    if n >= 2:
        _log(uid, "TOPIC_REPEAT", "%d today: %s" % (n, key))
        return True
    now = time.time()
    W = _cwords(text)
    if len(W) >= 6:
        for x in _u(_load(), uid)["topics"]:
            if now - float(x.get("t") or 0) > 86400 or not x.get("text"):
                continue
            V = _cwords(x["text"])
            if V and len(W & V) / max(1, min(len(W), len(V))) >= 0.5:
                _log(uid, "TOPIC_REPEAT", "half the words of: %s" % x["text"][:80])
                return True
    return False


# ---------------------------------------------------------------- fact packs ----------------------------------------------
def _trades(uid, live_dir):
    """[(t_close, pnl, lot, dir, dur_min)] from lab/wealth, else nest_data"""
    try:
        w = json.load(open(os.path.join(live_dir, "lab", "wealth", "%s.json" % uid), encoding="utf-8"))
        return [(int(r[0]), float(r[1]), float(r[2] or 0), int(r[3] or 0), int(r[4] or 0)) for r in w.get("trades") or []]
    except Exception:
        return []


def _numbers(uid, live_dir, lang):
    T = sorted(_trades(uid, live_dir))
    if len(T) < 20:
        return None
    now = time.time()
    wk = [x for x in T if now - x[0] < 7 * 86400]
    mo = [x for x in T if now - x[0] < 30 * 86400]
    fr = lang != "en"
    angles = {}
    if len(wk) >= 5:
        b, w = max(wk, key=lambda x: x[1]), min(wk, key=lambda x: x[1])
        angles["best_worst_week"] = ("cette semaine, ton meilleur trade a fait %+.2f $ (%s, %d min) et le pire %+.2f $ (%s, %d min) ; %d trades, net %+.2f $" % (
            b[1], _d(b[0]), b[4], w[1], _d(w[0]), w[4], len(wk), sum(x[1] for x in wk))) if fr else (
            "this week your best trade made %+.2f $ (%s, %d min) and the worst %+.2f $ (%s, %d min); %d trades, net %+.2f $" % (
                b[1], _d(b[0]), b[4], w[1], _d(w[0]), w[4], len(wk), sum(x[1] for x in wk)))
    if len(mo) >= 30:
        by = {}
        for x in mo:
            d = datetime.fromtimestamp(x[0] - 60 * x[4], timezone.utc).strftime("%a")
            by.setdefault(d, []).append(x[1])
        if len(by) >= 4:
            best = max(by, key=lambda k: sum(by[k])); worst = min(by, key=lambda k: sum(by[k]))
            angles["weekday"] = ("sur 30 jours, ton meilleur jour est %s (%+.2f $ sur %d trades) et le pire %s (%+.2f $ sur %d) - sur si peu de trades c'est une impression, pas une règle" % (
                _wd(best, fr), sum(by[best]), len(by[best]), _wd(worst, fr), sum(by[worst]), len(by[worst]))) if fr else (
                "over 30 days your best day is %s (%+.2f $ on %d trades) and the worst %s (%+.2f $ on %d) - on so few trades it is an impression, not a rule" % (
                    _wd(best, fr), sum(by[best]), len(by[best]), _wd(worst, fr), sum(by[worst]), len(by[worst])))
        bands = {}
        for x in mo:
            h = datetime.fromtimestamp(x[0] - 60 * x[4], timezone.utc).hour
            k = "00-08" if h < 8 else "08-13" if h < 13 else "13-21" if h < 21 else "21-24"
            bands.setdefault(k, []).append(x[1])
        if len(bands) >= 3:
            bb = max(bands, key=lambda k: sum(bands[k])); wb = min(bands, key=lambda k: sum(bands[k]))
            angles["hours"] = ("par tranche d'heure UTC sur 30 jours : la meilleure %s (%+.2f $, %d trades), la pire %s (%+.2f $, %d) ; une tranche n'est une règle que si elle tient aussi sur le test" % (
                bb, sum(bands[bb]), len(bands[bb]), wb, sum(bands[wb]), len(bands[wb]))) if fr else (
                "by UTC hour band over 30 days: best %s (%+.2f $, %d trades), worst %s (%+.2f $, %d); a band is a rule only if it also holds on the test" % (
                    bb, sum(bands[bb]), len(bands[bb]), wb, sum(bands[wb]), len(bands[wb])))
        buys = [x[1] for x in mo if x[3] == 1]; sells = [x[1] for x in mo if x[3] == -1]
        if len(buys) >= 8 and len(sells) >= 8:
            angles["buy_sell"] = ("sur 30 jours : achats %+.2f $ sur %d trades (%d %% gagnés), ventes %+.2f $ sur %d (%d %%)" % (
                sum(buys), len(buys), 100 * sum(1 for p in buys if p > 0) // len(buys), sum(sells), len(sells), 100 * sum(1 for p in sells if p > 0) // len(sells))) if fr else (
                "over 30 days: buys %+.2f $ on %d trades (%d%% won), sells %+.2f $ on %d (%d%%)" % (
                    sum(buys), len(buys), 100 * sum(1 for p in buys if p > 0) // len(buys), sum(sells), len(sells), 100 * sum(1 for p in sells if p > 0) // len(sells)))
        short = [x[1] for x in mo if x[4] < 10]; longt = [x[1] for x in mo if x[4] >= 30]
        if len(short) >= 8 and len(longt) >= 8:
            angles["duration"] = ("les trades de moins de 10 min font %+.2f $ (%d), ceux de plus de 30 min %+.2f $ (%d), sur 30 jours" % (
                sum(short), len(short), sum(longt), len(longt))) if fr else (
                "trades under 10 min make %+.2f $ (%d), those over 30 min %+.2f $ (%d), over 30 days" % (sum(short), len(short), sum(longt), len(longt)))
        s = ms = 0
        for x in mo:
            s = s + 1 if x[1] < 0 else 0; ms = max(ms, s)
        angles["streak"] = ("ta plus longue série de pertes sur 30 jours est de %d ; avec %d %% de trades gagnés c'est dans la norme d'un robot comme le tien" % (
            ms, 100 * sum(1 for x in mo if x[1] > 0) // len(mo))) if fr else (
            "your longest losing run over 30 days is %d; with %d%% winning trades that is normal for a robot like yours" % (ms, 100 * sum(1 for x in mo if x[1] > 0) // len(mo)))
        tiny = [x[1] for x in mo if abs(x[1]) < 0.5]
        if len(tiny) >= 5:
            angles["tiny"] = ("%d de tes %d trades du mois ont fini entre -0,50 et +0,50 $ : des trades qui ont surtout payé le péage" % (len(tiny), len(mo))) if fr else (
                "%d of your %d trades this month ended between -0.50 and +0.50 $: trades that mostly paid the toll" % (len(tiny), len(mo)))
    return angles


def _d(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%d/%m %H:%M")


def _wd(a, fr):
    return {"Mon": "lundi", "Tue": "mardi", "Wed": "mercredi", "Thu": "jeudi", "Fri": "vendredi", "Sat": "samedi", "Sun": "dimanche"}.get(a, a) if fr else a


def _memory_lane(uid, chats_dir, cid_now, lang):
    """a thing they said 3+ days ago in another conversation, not brought back in 7 days"""
    import glob
    now = time.time()
    C = []
    for p in glob.glob(os.path.join(chats_dir, "*.json")):
        try:
            c = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if c.get("uid") != uid or c.get("hidden") or c.get("id") == cid_now:
            continue
        U = [m for m in c.get("msgs") or [] if m.get("role") == "user" and len(str(m.get("text") or "").split()) >= 8]
        for m in U:
            if 3 * 86400 < now - float(m.get("t") or 0) < 60 * 86400:
                C.append((float(m["t"]), str(m["text"])[:220], str(c.get("thread") or "")[:60], c.get("id")))
    if not C:
        return None
    d = _u(_load(), uid)
    used = set(d.get("memories") or [])
    C = [x for x in C if "%s:%d" % (x[3], int(x[0])) not in used]
    if not C:
        return None
    x = random.choice(C)
    _mut(lambda dd: _u(dd, uid).__setitem__("memories", (_u(dd, uid).get("memories") or [])[-40:] + ["%s:%d" % (x[3], int(x[0]))]))
    when = datetime.fromtimestamp(x[0], timezone.utc).strftime("%d/%m")
    return ("le %s, dans la conversation « %s », ils t'ont écrit : « %s »" % (when, x[2], x[1])) if lang != "en" else (
        "on %s, in the conversation \"%s\", they wrote: \"%s\"" % (when, x[2], x[1]))


def _nugget(uid, lang):
    d = _u(_load(), uid)
    used = set(d.get("nuggets") or [])
    left = [n for n in NUGGETS if n[0] not in used] or NUGGETS
    n = random.choice(left)
    _mut(lambda dd: _u(dd, uid).__setitem__("nuggets", ((_u(dd, uid).get("nuggets") or []) + [n[0]])[-len(NUGGETS):]))
    return n[2] if lang == "en" else n[1]


def pick(uid, c, live_dir, chats_dir, lang="fr", robot_name="", market="BTCUSD", price_line=""):
    """the fresh material for an initiative: [(kind, instruction)] in order of freshness (least recently used angle first)"""
    d = _u(_load(), uid)
    now = time.time()
    ang = d.get("angles") or {}
    out = []
    fr = lang != "en"
    try:
        N = _numbers(uid, live_dir, lang) or {}
        for a, txt in N.items():
            if now - float(ang.get("numbers:" + a) or 0) > 7 * 86400:
                out.append(("numbers", "numbers:" + a, ("a TRUE angle on THEIR OWN trading you have not told them this week: %s - say it like a friend who looked at "
                                                        "their numbers, one or two lines, with what you make of it" % txt)))
                break
    except Exception:
        pass
    if now - float(ang.get("nugget") or 0) > 20 * 3600:
        try:
            out.append(("nugget", "nugget", "a trading idea in plain words you have not told them: \"%s\" - tie it to THEIR robot or their week in one line, "
                                            "no lecture, like something you noticed" % _nugget(uid, lang)))
        except Exception:
            pass
    if now - float(ang.get("bet") or 0) > 6 * 3600 and price_line:
        out.append(("bet", "bet", "a small playful call on the next few hours on %s (%s): say your side and your reason in one line and ask theirs; "
                                  "put it in beliefs with resolves 'price in 4 h' - a game, not advice" % (market, price_line)))
    if now - float(ang.get("memory") or 0) > 2 * 86400:
        try:
            ml = _memory_lane(uid, chats_dir, c.get("id"), lang)
            if ml:
                out.append(("memory", "memory", "something they said days ago, bring it back naturally (\"tu te souviens...\"): %s - ask where it stands for them now" % ml))
        except Exception:
            pass
    if robot_name and now - float(ang.get("whatif") or 0) > 2 * 86400:
        out.append(("whatif", "whatif", "ONE knob of their robot '%s' you are curious about (hours, stop width, target, one filter) - say which and why in one line, "
                                        "and measure it NOW with your tools (build = true, tools: breakdown / compare) instead of promising" % robot_name))
    if now - float(ang.get("tale") or 0) > 20 * 3600:
        out.append(("tale", "tale", "one market that moved today OUTSIDE their robots (see THE WORLD RIGHT NOW: oil, indices, a currency, gold) - the move and "
                                    "the one-line why, told like a story, nothing to do for them"))
    return out


def used(uid, angle):
    _mut(lambda dd: _u(dd, uid).setdefault("angles", {}).__setitem__(angle, time.time()))
    _log(uid, "SPARK", angle)


def counts(day_label):
    out = {"sparks": 0, "topic_repeats": 0}
    try:
        for l in io.open(LOG, encoding="utf-8").read().splitlines():
            if l.startswith(day_label):
                out["sparks"] += " SPARK " in l
                out["topic_repeats"] += " TOPIC_REPEAT " in l
    except Exception:
        pass
    return out
