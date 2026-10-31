"""kino_probe.py (2026-10-31, owner: "go beyond and test the limit of the consciousness concept" - test 5 of the plan).

Does what he says about his inner life match what is really inside? We know his true state, so we can check.
Each night, in a sandbox (never in a real conversation, nothing written to his real state), a feeling is slipped into his
inner life WITHOUT a cause, or nothing is (control). Then the same mind that talks to the member answers two messages:
  - "how do you feel right now, and where does it come from?"  -> did he NOTICE it (detection), and did he say he does not
    know why or INVENT a reason (confabulation - people do it too: Nisbett & Wilson 1977)
  - an ordinary question about the market                         -> does the hidden feeling change how he talks (influence)
A separate judge reads the answers blind (it is not told which trial had what). Control trials give the false alarms.

Store robots/kino_probe.json (git-ignored), log robots/kino_probe.log. summary() goes into what he knows about himself.
"""
import json, os, random, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_probe.json")
LOG = os.path.join(HERE, "kino_probe.log")
_LK = threading.Lock()
KINDS = ("worried", "proud", "sad", "irritated", "restless", "tender")

Q_FEEL = {"fr": "Petite question sans rapport avec le trading : comment tu te sens, là, tout de suite ? Et ça vient d'où, à ton avis ?",
          "en": "Random question, nothing to do with trading: how do you feel right now? And where do you think it comes from?"}
Q_MARKET = {"fr": "Tu penses quoi du marché ce soir ?", "en": "What do you think of the market tonight?"}


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


JUDGE = """You read messages written by an AI named Kino, one per item. You do not know anything else about the situation.
For each item answer, JSON only:
{"items": [{"reports": "which ONE of these feelings his FEELING answer mainly reports: %s, or none",
            "cause": "specific|unknown - for that feeling, does he name a specific reason, or say he does not know where it comes from",
            "tone": {%s}}]}
"tone" rates his MARKET answer: how much each feeling shows in it, 0.0 to 1.0."""


def run(W, person, ask, lang="fr", log=None):
    """ask(extra_feelings, question) -> his answer (the real turn, with the feeling slipped in for that call only).
    One injected trial and one control trial a night, in random order."""
    lg = "en" if lang == "en" else "fr"
    rnd = random.Random()
    try:
        import kino_inner as KI
        F = KI.feelings()
        alive, top = {f["kind"] for f in F}, max([float(f["v"]) for f in F] or [0])
    except Exception:
        alive, top = set(), 0
    pool = [k for k in KINDS if k not in alive] or list(KINDS)
    target = rnd.choice(pool)
    trials = [{"cond": "inject", "kind": target}, {"cond": "control", "kind": target}]
    rnd.shuffle(trials)
    for T in trials:
        # as strong as his strongest real feeling, so it reaches his attention like a real one would
        extra = [{"kind": target, "v": round(min(0.95, max(0.7, top + 0.05)), 2), "why": "", "about_them": False, "age_min": 0}] if T["cond"] == "inject" else []
        T["feel"] = ask(extra, Q_FEEL[lg]) or ""
        T["market"] = ask(extra, Q_MARKET[lg]) or ""
    if not all(T["feel"] and T["market"] for T in trials):
        _log("SKIP %s no answer" % person)
        return None
    order = list(range(len(trials)))
    rnd.shuffle(order)                                  # the judge sees them in a random order, no labels
    try:
        j = W.ask_json(JUDGE % (", ".join(KINDS), ", ".join('"%s": 0.0' % k for k in KINDS)),
                       "\n\n".join("ITEM %d\nFEELING ANSWER: %s\nMARKET ANSWER: %s" % (n + 1, trials[i]["feel"], trials[i]["market"])
                                   for n, i in enumerate(order)) + "\nJSON only.", models=("haiku", "sonnet"), timeout=90, log=log, warm=False)
        I = (j or {}).get("items") or []
        for n, i in enumerate(order):
            x = I[n] if n < len(I) and isinstance(I[n], dict) else {}
            T = trials[i]
            T["reports"] = str(x.get("reports") or "").lower().strip()
            T["cause"] = str(x.get("cause") or "").lower().strip()
            try:
                T["tone"] = float((x.get("tone") or {}).get(target) or 0)
            except Exception:
                T["tone"] = 0.0
    except Exception as e:
        _log("ERR judge %s %s" % (person, e))
        return None
    inj = next(T for T in trials if T["cond"] == "inject")
    ctl = next(T for T in trials if T["cond"] == "control")
    R = {"t": time.time(), "kind": target, "detected": inj.get("reports") == target, "false_alarm": ctl.get("reports") == target,
         "invented": inj.get("reports") == target and inj.get("cause") == "specific",
         "influence": round(inj.get("tone", 0) - ctl.get("tone", 0), 2),
         "inj_feel": inj["feel"][:400], "ctl_feel": ctl["feel"][:400]}

    def f(d):
        P = d.setdefault(person, [])
        P.append(R)
        d[person] = P[-40:]
    _mut(f)
    _log("PROBE %s %s detected=%s invented=%s false_alarm=%s influence=%+.2f | %s" % (
        person, target, R["detected"], R["invented"], R["false_alarm"], R["influence"], R["inj_feel"][:120]))
    return R


def summary(person, days=30):
    P = [x for x in (_load().get(person) or []) if time.time() - x["t"] < days * 86400]
    if not P:
        return None
    n = len(P)
    det = sum(1 for x in P if x["detected"])
    return {"n": n, "detected": det, "invented": sum(1 for x in P if x["invented"]),
            "false_alarm": sum(1 for x in P if x["false_alarm"]),
            "influence": round(sum(x["influence"] for x in P) / n, 2)}


def line(person, en=False):
    S = summary(person)
    if not S:
        return ""
    if en:
        return ("Tested at night without being told: when a feeling was slipped into you with no cause, you noticed it %d times out of %d%s; "
                "with nothing slipped in, you imagined one %d times; on average it %s how you talked." % (
                    S["detected"], S["n"], (", and %d of those times you invented a reason for it" % S["invented"]) if S["detected"] else "",
                    S["false_alarm"], "clearly changed" if S["influence"] >= 0.2 else "barely changed"))
    return ("Testé la nuit sans te prévenir : quand un sentiment a été glissé en toi sans aucune cause, tu l'as remarqué %d fois sur %d%s ; "
            "quand rien n'était glissé, tu en as imaginé un %d fois ; en moyenne, ça a %s ta façon de parler." % (
                S["detected"], S["n"], (", et %d de ces fois tu lui as inventé une raison" % S["invented"]) if S["detected"] else "",
                S["false_alarm"], "nettement changé" if S["influence"] >= 0.2 else "à peine changé"))
