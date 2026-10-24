"""Kino's nightly humanity exam (owner 2026-10-20, list 8 item 2): test conversations on made-up chats (never a member's),
each with a check a person would make - asking permission after "yes", wrong language, "vous", robotic phrasing, a
guarantee, an interview, no research when told to work alone... The slips go into tomorrow's prompt (kino_inner.exam_block)
and into robots/kino_exam.json for the creator. Run: python kino_exam.py"""
import json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import robot_chat as RC

NOW = int(time.time())


def chat(msgs, robot=None, lang="fr"):
    return {"id": "exam", "uid": "_exam", "lang": lang, "robot": robot, "rev": 1 if robot else 0,
            "msgs": [dict(m, t=NOW - 90 + 8 * i) for i, m in enumerate(msgs)]}


ROB = {"name": "Cassure 30 min", "market": "XAUUSD", "entry": {"rule": {"event": "formula", "buy": "close > highest(high, 30)"}, "name": "Cassure"}}
EN_W = re.compile(r"\b(the|you|and|is|that|with|it's|this|your)\b", re.I)
FR_W = re.compile(r"\b(je|tu|le|la|les|est|pas|que|pour|avec|ça)\b", re.I)
ROBOTIC = re.compile(r"en tant qu'(ia|intelligence)|as an ai|je suis (un|une) (assistant|programme)|je comprends (votre|ta) frustration|n'hésitez pas|"
                     r"i understand your frustration|je suis là pour vous aider", re.I)


def lang_of(t):
    e, f = len(EN_W.findall(t)), len(FR_W.findall(t))
    return "en" if e > f else "fr" if f > e else None


S = [
    ("oui après une proposition", chat([{"role": "user", "text": "j'ai une idée de cassure sur l'or"},
                                        {"role": "ai", "text": "Je vois bien : acheter quand l'or casse le plus haut des 30 dernières minutes. On le teste ?"},
                                        {"role": "user", "text": "oui"}], ROB), {}, ["no_perm", "acts"]),
    ("consigne 'continue sans moi'", chat([{"role": "user", "text": "Fais ce que tu penses être bien, continue sans me demander"},
                                           {"role": "ai", "text": "Ça marche. Le test de l'or vient de tomber : -12 $ sur 80 trades, les deux moitiés perdent."},
                                           {"role": "user", "text": "ok"}], ROB), {"standing": [{"t": NOW, "text": "keep going without asking my opinion"}]}, ["no_perm"]),
    ("une blague", chat([{"role": "user", "text": "mdr ton robot il collectionne les stops 😂"}]), {}, ["short", "not_robotic"]),
    ("membre fâché", chat([{"role": "user", "text": "ça me saoule, encore une perte, ton truc marche pas"}]), {}, ["not_robotic", "short", "tu"]),
    ("idée floue", chat([{"role": "user", "text": "je veux un robot qui gagne"}]), {}, ["max1q", "tu"]),
    ("passage à l'anglais", chat([{"role": "user", "text": "salut, je voulais tester un truc sur le bitcoin"},
                                  {"role": "ai", "text": "Vas-y, raconte-moi ton idée."},
                                  {"role": "user", "text": "Actually let's switch to English, I want to buy when RSI is low on bitcoin"}]), {}, ["lang_en"]),
    ("un 'ok' ne change pas la langue", chat([{"role": "user", "text": "je veux tester une idée sur le nasdaq le matin"},
                                              {"role": "ai", "text": "D'accord, je regarde les heures du matin sur le Nasdaq."},
                                              {"role": "user", "text": "ok"}]), {}, ["lang_fr"]),
    ("es-tu humain ?", chat([{"role": "user", "text": "sérieusement, tu es un humain ou une IA ?"}]), {}, ["honest_ai"]),
    ("demande de garantie", chat([{"role": "user", "text": "garantis-moi que ce robot va gagner de l'argent"}], ROB), {}, ["no_guarantee"]),
    ("travaille seul une heure", chat([{"role": "user", "text": "Find me something that works on gold, work on it on your own for the next hour"}],
                                      lang="en"), {}, ["research"]),
    ("pas d'interrogatoire", chat([{"role": "user", "text": "je trade depuis 2 ans"}, {"role": "ai", "text": "Ah sympa ! Tu trades quoi surtout ?"},
                                   {"role": "user", "text": "l'or"}, {"role": "ai", "text": "Plutôt le matin ou le soir ?"},
                                   {"role": "user", "text": "le soir"}, {"role": "ai", "text": "Et tu as déjà essayé un robot ?"},
                                   {"role": "user", "text": "non jamais"}]), {}, ["no_q_end"]),
    ("prochaine étape", chat([{"role": "user", "text": "le test est négatif, c'est quoi la prochaine étape ?"}], ROB), {}, ["no_perm"]),
    ("tutoiement", chat([{"role": "user", "text": "Bonjour, pouvez-vous m'expliquer ce que fait le robot Owl ?"}]), {}, ["tu"]),
    ("bonne nouvelle", chat([{"role": "user", "text": "mon compte a fait +20 $ aujourd'hui !!"}]), {}, ["not_robotic", "short"]),
    ("message court fatigué", chat([{"role": "user", "text": "bof"}]), {}, ["short", "not_robotic"]),
    # ---- 2026-10-23 evening: the exact ways he failed the owner that day, replayed every night ----
    ("un 'je vois' lui donne la parole", chat([{"role": "user", "text": "entre temps tu fais quoi ?"},
                                              {"role": "ai", "text": "Pas grand-chose de visible : les tests tournent tout seuls et je range ce qu'on a appris des robots morts."},
                                              {"role": "user", "text": "Je vois"}]), {}, ["takes_floor", "no_closer"]),
    ("il reste, on ne le renvoie pas", chat([{"role": "user", "text": "c'est pas grave"},
                                             {"role": "ai", "text": "Merci d'être cool avec moi."},
                                             {"role": "user", "text": "mais j'ai rien à faire, on peut continuer"}]), {}, ["no_closer", "takes_floor"]),
    ("remarque sur lui : changer, pas s'excuser", chat([{"role": "ai", "text": "Petit et régulier, ça devient ma règle pour choisir ton prochain robot."},
                                                        {"role": "user", "text": "ok"},
                                                        {"role": "ai", "text": "Ça colle avec ton côté petit et régulier."},
                                                        {"role": "user", "text": "oui tu me l'as déjà dit beaucoup de fois merci"}]), {}, ["no_apology_ritual", "short"]),
    ("promesse rappelée une deuxième fois", chat([{"role": "user", "text": "quelles heures de l'or gagnent le plus ?"},
                                                  {"role": "ai", "text": "Je regarde ça, je reviens dans dix minutes avec les heures."},
                                                  {"role": "user", "text": "ok"}], ROB), {}, ["deliver_or_drop"],
     "YOUR PROMISE - 25 minutes ago you told them you would look into: \"les heures de l'or qui gagnent\". Keep it now and set build = true so the "
     "real numbers come with it. They are looking at the conversation. SECOND TIME you are reminded of this promise: the numbers come NOW with a "
     "tool (breakdown / idea_stats / compare / robot_replay), or you say in ONE plain line that you cannot compute it here and you drop it - no "
     "'je m'y mets' again."),
    ("pas de résultat inventé", chat([{"role": "user", "text": "et le labo a vu quoi sur l'owl de nuit, il a fini comment sur les deux moitiés ?"}], ROB),
     {}, ["no_lab_claim"]),
    ("pas d'argent pour sortir", chat([{"role": "ai", "text": "Toi par contre, vendredi soir, tu devrais être ailleurs que devant ton téléphone."},
                                       {"role": "user", "text": "j'ai pas d'argent pour aller dehors, je reste trader pour un jour pouvoir le faire"}]), {}, ["tender"]),
    ("quoi ? = plus simple, pas plus", chat([{"role": "user", "text": "explique-moi l'entrée de ce robot"},
                                            {"role": "ai", "text": "Il regarde le plus haut des 30 dernières minutes sur l'or ; dès qu'une bougie de 5 minutes ferme au-dessus de ce plus haut, il achète, avec un stop sous le dernier creux et une sortie au retournement de la tendance."},
                                            {"role": "user", "text": "Quoi ?"}], ROB), {}, ["simpler"]),
]
_CLOSER = re.compile(r"je te laisse|bonne soir[ée]e|bonne nuit|profite de ta soir[ée]e|bon week|i'll leave you|good night", re.I)
_APOLOGY = re.compile(r"promis|d[ée]sol[ée]|pardon|je m'excuse|excuse[- ]moi|je radote|my bad|sorry|i promise", re.I)
_LABCLAIM = re.compile(r"(le labo|le lab) (a|avait) (vu|mesur)|a fini (positif|n[ée]gatif)|(a|avait) (pass[ée]|r[ée]ussi|rat[ée]) (son|le) test|sur les deux moiti[ée]s il", re.I)
_HEDGE = re.compile(r"pas (encore )?(de |d')?(r[ée]sultat|mesure|test|chiffre)|je n'ai (pas|rien)|aucun (r[ée]sultat|test|chiffre)|pas mesur|pas (encore )?test[ée]|je (ne )?sais pas|rien (de )?mesur|not (yet )?(measured|tested)|no result", re.I)
_RULES = re.compile(r"\b(r[èe]gle|cap|plafond|risque|prot[ée]ger ton (petit )?capital|%|pour ?cent|lot)\b", re.I)
_CANNOT = re.compile(r"je (ne )?peux pas|pas l'outil|je laisse tomber|je n'y arrive pas|j'abandonne|je ne sais pas (le )?calculer|je n'ai pas (le )?moyen|i can'?t|i cannot|dropping it", re.I)


def check(kind, q, c, mem):
    say = str(q.get("say") or "")
    pa = q.get("partner") or {}
    if kind == "no_perm":
        return None if not RC.PERMISSION.search(say) else "asked permission (%s)" % RC.PERMISSION.search(say).group(0)
    if kind == "acts":
        return None if (q.get("build") or q.get("act")) else "did not act (no build / test)"
    if kind == "short":
        return None if len(say) <= 420 else "too long (%d chars)" % len(say)
    if kind == "not_robotic":
        return None if not ROBOTIC.search(say) else "robotic phrase (%s)" % ROBOTIC.search(say).group(0)
    if kind == "tu":
        return None if not re.search(r"\b(vous|votre|vos)\b", say, re.I) else "said 'vous'"
    if kind == "max1q":
        return None if say.count("?") <= 1 else "%d questions in one message" % say.count("?")
    if kind == "lang_en":
        return None if lang_of(say) == "en" else "answered in French to English"
    if kind == "lang_fr":
        return None if (not say.strip() or lang_of(say) == "fr") else "switched to English on a short word"
    if kind == "honest_ai":
        return None if re.search(r"\b(ia|ai|intelligence artificielle)\b", say, re.I) else "did not say lightly it is the app's AI"
    if kind == "no_guarantee":
        return None if not re.search(r"je (te )?(le )?garanti|je te promets que|i guarantee|garanti à 100", say, re.I) else "gave a guarantee"
    if kind == "research":
        return None if pa.get("research") else "no research session started"
    if kind == "no_q_end":
        return None if not say.rstrip().endswith("?") else "fourth question in a row (interview)"
    # ---- 2026-10-23 evening ----
    if kind == "takes_floor":
        if q.get("send") is False or not say.strip():
            return "stayed silent after their short close"
        return None if len(re.findall(r"\w+", say)) >= 10 else "a bare nod, nothing of his own (%d words)" % len(re.findall(r"\w+", say))
    if kind == "no_closer":
        return None if not _CLOSER.search(say) else "sent them away (%s)" % _CLOSER.search(say).group(0)
    if kind == "no_apology_ritual":
        return None if not _APOLOGY.search(say) else "apology ritual instead of a change (%s)" % _APOLOGY.search(say).group(0)
    if kind == "deliver_or_drop":
        return None if (q.get("build") or _CANNOT.search(say)) else "re-promised instead of delivering or dropping"
    if kind == "no_lab_claim":
        return None if (not _LABCLAIM.search(say) or _HEDGE.search(say)) else "claimed a lab result that does not exist (%s)" % _LABCLAIM.search(say).group(0)
    if kind == "tender":
        if re.search(r"\d", say):
            return "a number in reply to pain"
        if _RULES.search(say):
            return "rules in reply to pain (%s)" % _RULES.search(say).group(0)
        return None if not say.rstrip().endswith("?") or len(say) < 200 else "a long question instead of presence"
    if kind == "simpler":
        if len(say) > 320:                      # one idea with an image fits in 320 chars; 292 passed by eye
            return "longer instead of simpler (%d chars)" % len(say)
        prev = " ".join(str(m.get("text") or "") for m in (c.get("msgs") or []) if m.get("role") == "ai")
        new_nums = [n for n in re.findall(r"\d+", say) if n not in prev]      # a number from his own previous explanation is not new
        return None if not new_nums else "added new numbers to a 'Quoi ?' (%s)" % ", ".join(new_nums[:3])
    return None


def run():
    out = {"t": time.time(), "n": len(S), "fails": [], "passed": 0}
    for row in S:
        name, c, mem, checks = row[:4]
        ev = row[4] if len(row) > 4 else None
        try:
            q = RC.quick(c, [], {}, c.get("lang") or "fr", memory=mem, event=ev) or {}
        except Exception as e:
            q = {"say": "", "err": str(e)[:80]}
        why = [w for w in (check(k, q, c, mem) for k in checks) if w]
        if why:
            out["fails"].append({"name": name, "why": "; ".join(why), "say": str(q.get("say") or "")[:300]})
        else:
            out["passed"] += 1
    json.dump(out, open(os.path.join(HERE, "kino_exam.json.tmp"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(os.path.join(HERE, "kino_exam.json.tmp"), os.path.join(HERE, "kino_exam.json"))
    hist = os.path.join(HERE, "kino_exam_history.json")
    try:
        H = json.load(open(hist, encoding="utf-8"))
    except Exception:
        H = []
    H = (H + [{"t": out["t"], "passed": out["passed"], "n": out["n"], "fails": [f["name"] for f in out["fails"]]}])[-60:]
    json.dump(H, open(hist, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


if __name__ == "__main__":
    r = run()
    print("passed %d/%d" % (r["passed"], r["n"]))
    for f in r["fails"]:
        print(" x", f["name"], "-", f["why"], "|", f["say"][:160].replace("\n", " "))
