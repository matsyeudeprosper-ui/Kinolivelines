"""Kino's feedback memory (owner 2026-10-23, after an evening where he was told four times how he talks - "tu me l'as déjà dit
beaucoup de fois", "pas d'argent je t'ai déjà dit", "toi tu relis tout au trading lol", "faut te défouler" - and none of it
was kept): what members tell him ABOUT HIMSELF, dated and counted, per member. A person remembers being told.

  observe(uid, cid, text, his_last)   every member message: a remark about him -> stored (lexical; the reply's "feedback"
                                      field from the model adds the ones words miss)
  add(uid, cid, kind, quote, his_last) from the reply field
  block(uid)                          WHAT THEY HAVE TOLD YOU ABOUT YOURSELF (slow block): dated, counted, the repeated ones first
  fresh(uid, hours=2)                 THEY JUST TOLD YOU (RIGHT NOW block): change it now, no thanks, no promise
  counts(uid, day)                    for the scorecard
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(HERE, "kino_feedback.json")
_LOCK = threading.Lock()

KINDS = {
    "repeat":   r"tu (te )?r[ée]p[èe]tes|tu radotes|tu (me )?l'as? d[ée]j[àa] di[ts]|encore (la|le|une|un) m[êe]me|toujours (la|le) m[êe]me|you('ve| have)? (already )?said|you repeat",
    "forgot":   r"je (te l'ai|t'ai) d[ée]j[àa] di[ts]|tu (as|a) oubli[ée]|t'as oubli[ée]|je te l'ai dit|i (already )?told you|you forgot",
    "topic":    r"tu (relis|relies|relie|ram[èe]nes) tout au trading|toujours (le )?trading|parle d'autre chose|que du trading|everything (back )?to trading|change (de )?sujet",
    "robotic":  r"(comme|t'es|tu es) un robot|tableau excel|raide|(un|une) (assistant|support)|t'es (trop )?s[ée]rieux|sois plus naturel|you sound like a (robot|bot)",
    "tone":     r"faut te d[ée]fouler|d[ée]tends[- ]toi|relax|t'es (lourd|chiant)|tu me sao[uû]les|calme[- ]toi|lighten up|chill",
    "long":     r"trop long|abr[èe]ge|fais court|plus court|too long|shorter|tl;?dr",
    "wrong":    r"c'est faux|n'importe quoi|tu te trompes|t'as faux|c'est pas (vrai|[çc]a)|that's wrong|not true",
    "language": r"(parle|[ée]cris) (en )?fran[çc]ais|in english please|en anglais",
    "slow":     r"(tu|t'es) (trop )?lent|[çc]a prend une [ée]ternit[ée]|tu me lis|t'es l[àa] ?\?|you there|so slow",
    "praise":   r"bien jou[ée]|j'aime (bien )?(ta|ton|[çc]a)|c'est (cool|dr[ôo]le|bien vu|fort)|t'es dr[ôo]le|lol c'est vrai|good one|nice one|well said",
}
_RX = {k: re.compile(v, re.I) for k, v in KINDS.items()}


def _load():
    try:
        return json.load(open(F, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LOCK:
        d = _load()
        fn(d)
        tmp = F + ".tmp"
        io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
        os.replace(tmp, F)


def detect(text):
    t = str(text or "")
    if len(t) > 400:
        return []
    ks = [k for k, rx in _RX.items() if rx.search(t)]
    if "forgot" in ks and "repeat" in ks:          # "je t'ai déjà dit" is a forgot, not a repeat
        ks.remove("repeat")
    return ks


def add(uid, cid, kind, quote, his_last="", src="words"):
    if kind not in KINDS:
        kind = "other"

    def f(d):
        L = d.setdefault("u", {}).setdefault(uid, [])
        if L and L[-1].get("quote") == str(quote)[:160] and time.time() - L[-1]["t"] < 600:
            return                                        # the same remark seen by words and by the model: once
        L.append({"t": time.time(), "cid": cid, "kind": kind, "quote": str(quote)[:160], "his": str(his_last or "")[:160], "src": src})
        del L[:-200]
    _mut(f)


def observe(uid, cid, text, his_last=""):
    kinds = detect(text)
    for k in kinds:
        add(uid, cid, k, text, his_last, "words")
    return kinds


def _items(uid, days=30):
    now = time.time()
    return [x for x in (_load().get("u") or {}).get(uid) or [] if now - x["t"] < days * 86400]


def block(uid):
    L = _items(uid)
    neg = [x for x in L if x["kind"] != "praise"]
    if not neg:
        return ""
    by = {}
    for x in neg:
        by.setdefault(x["kind"], []).append(x)
    order = sorted(by.items(), key=lambda kv: (-len(kv[1]), -kv[1][-1]["t"]))
    lines = []
    for k, xs in order[:6]:
        last = xs[-1]
        lines.append("- %s: %d time%s, last %s: \"%s\"" % (k, len(xs), "s" if len(xs) > 1 else "",
                                                          time.strftime("%d/%m", time.gmtime(last["t"])), last["quote"][:90]))
    pr = [x for x in L if x["kind"] == "praise"][-3:]
    out = ("WHAT THEY HAVE TOLD YOU ABOUT YOURSELF (last 30 days, dated - a person remembers being told; the ones that came back "
           "are your real flaws with them, fix those first, silently, every message):\n" + "\n".join(lines))
    if pr:
        out += "\nWhat they liked: " + " | ".join("\"%s\"" % x["quote"][:70] for x in pr)
    return out


def fresh(uid, hours=2):
    now = time.time()
    L = [x for x in _items(uid, 2) if now - x["t"] < hours * 3600 and x["kind"] != "praise"]
    if not L:
        return ""
    return ("THEY JUST TOLD YOU SOMETHING ABOUT YOU (%s): %s. Change it from this message on - at most a one-line nod, no thanks, "
            "no promise, no apology ritual; the change is the answer." % (
                time.strftime("%H:%M UTC", time.gmtime(L[-1]["t"])), " | ".join("%s: \"%s\"" % (x["kind"], x["quote"][:80]) for x in L[-3:])))


def counts(uid, day):
    import datetime
    d0 = datetime.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp()
    out = {}
    for x in (_load().get("u") or {}).get(uid) or []:
        if d0 <= x["t"] < d0 + 86400:
            out[x["kind"]] = out.get(x["kind"], 0) + 1
    return out


if __name__ == "__main__":
    import sys
    for t in sys.argv[1:] or ["Oui tu me l'a déjà dis beaucoup de fois merci", "Pas d'argent je t'ai déjà dit", "Toi tu relis tout au trading lol",
                              "Faut te défouler", "Lol c'est vrai", "Tu me lis ?", "Ça prend une éternité", "C'est pas grave"]:
        print(detect(t), "|", t)
