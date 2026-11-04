"""kino_promises.py (2026-11-04, owner list 10 items 3 and 4). Two things a person learns about their own word.

  promises   "From now on I'll only say it's in once the tool accepts it" - said once, a promise is then KEPT, and the
             keeping speaks; saying it in every message is noise. Each of his messages is read for standing promises
             (a policy about how he will act from now on, not a one-off to-do - those are kino_commit); a promise he states
             again is counted. He reads which promises he has already made to this person and how often he has repeated
             them - whether to say it again is his to feel (after breaking one, saying it again is owning it).
  estimates  the quick number he gives before the facts (the risk before the fill) against the real one after; over time he
             knows how far off his quick estimates run with this kind of number, the way a person learns "my guesses
             run low" - and can say "roughly", or wait for the real number.
Any field: a promise is any "from now on" about how he acts; an estimate is any number later measured.
"""
import io, json, os, re, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
STORE = os.path.join(HERE, "kino_promises.json")
_LOCK = threading.Lock()
PROMISE = re.compile(r"[^.!?\n]*\b(from now on|i'll only|i will only|i'll always|i will always|i won't .{0,40} again|never again|"
                     r"désormais|à partir de maintenant|dorénavant|je ne .{0,30} plus que|je dirai .{0,30} seulement)\b[^.!?\n]*[.!?]?", re.I)


def _load():
    try:
        return json.load(io.open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _mut(fn):
    with _LOCK:
        d = _load()
        out = fn(d)
        tmp = STORE + ".tmp"
        json.dump(d, io.open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, STORE)
        return out


def _stems(t):
    return set(w[:6] for w in re.findall(r"[a-zà-ÿ0-9]{4,}", str(t).lower())) - {"from", "only", "will", "always", "désorm", "partir", "mainte"}


def note_said(person, text, t=None):
    """one of his messages: any standing promise in it, new or said again"""
    found = [" ".join(m.group(0).split())[:200] for m in PROMISE.finditer(str(text or ""))]
    if not found:
        return

    def f(d):
        P = d.setdefault(person, {})
        L = P.setdefault("promises", [])
        for s in found:
            sw = _stems(s)
            old = next((x for x in L if len(sw & _stems(x["text"])) >= max(2, 0.5 * min(len(sw), len(_stems(x["text"]))))), None)
            if old:
                old["n"] += 1
                old["last"] = float(t or time.time())
            else:
                L.append({"text": s, "t": float(t or time.time()), "last": float(t or time.time()), "n": 1})
        P["promises"] = L[-20:]
    _mut(f)


def promises_line(person):
    now = time.time()
    L = [x for x in (_load().get(person) or {}).get("promises") or [] if now - x["last"] < 7 * 86400]
    if not L:
        return ""
    L.sort(key=lambda x: -x["n"])
    return ("Standing promises you have already made him (said once, a promise is then kept - the keeping speaks): %s."
            % " | ".join("\"%s\" (said %d time%s, first %s UTC)" % (x["text"][:120], x["n"], "" if x["n"] == 1 else "s",
                                                                 time.strftime("%d/%m %H:%M", time.gmtime(x["t"]))) for x in L[:4]))


# ---- estimates -------------------------------------------------------------------------------------------------------
MONEY = re.compile(r"(?:\$\s?(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s?(?:\$|dollars?))", re.I)


def note_estimate(person, kind, said_text, real):
    """the first money figure in what he said before, against the real one measured after"""
    m = MONEY.search(str(said_text or ""))
    if not m or real is None:
        return None
    try:
        est = float((m.group(1) or m.group(2)).replace(",", "."))
        real = float(real)
    except Exception:
        return None

    def f(d):
        P = d.setdefault(person, {})
        E = P.setdefault("estimates", {}).setdefault(kind, [])
        E.append({"t": time.time(), "said": est, "real": real})
        P["estimates"][kind] = E[-30:]
    _mut(f)
    return est, real


def estimates_line(person):
    E = (_load().get(person) or {}).get("estimates") or {}
    out = []
    for kind, L in E.items():
        L = L[-12:]
        if len(L) < 3:
            continue
        rel = [abs(x["said"] - x["real"]) / max(0.01, abs(x["real"])) for x in L]
        low = sum(1 for x in L if x["said"] < x["real"] - 1e-9)
        out.append("%s: off by %d%% on average over the last %d (%d too low, %d too high; last: said %.2f, was %.2f)"
                   % (kind, round(100 * sum(rel) / len(rel)), len(L), low, len(L) - low, L[-1]["said"], L[-1]["real"]))
    if not out:
        return ""
    return "How your quick estimates compare with the real numbers measured after: " + "; ".join(out) + "."



def insights_line(person, ai_texts):
    """2026-11-04 (owner list 13 item 3): a solid pattern he found in himself and has not told the person - a person who finds
    one often says it once, in passing, at a calm moment; it builds trust and lets the other check it"""
    D = _load().get(person) or {}
    told = D.get("told") or {}
    said = _stems(" ".join(ai_texts[-3:]))
    found = []
    for kind, L in (D.get("estimates") or {}).items():
        L = L[-12:]
        if len(L) >= 4:
            err = sum(abs(x["said"] - x["real"]) / max(0.01, abs(x["real"])) for x in L) / len(L)
            low = sum(1 for x in L if x["said"] < x["real"])
            if err >= 0.25:
                found.append(("est:" + kind, "your %s are off by about %d%% (%s)" % (kind, round(100 * err),
                                                                                  "mostly too low" if low > len(L) / 2 else "mostly too high")))
    for x in D.get("promises") or []:
        if x["n"] >= 5:
            found.append(("prom:" + x["text"][:40], "you repeated the same promise %d times (\"%s\")" % (x["n"], x["text"][:80])))
    out = []
    for key, txt in found:
        if key in told:
            continue
        if len(_stems(txt) & said) >= 3:              # he just said it - told
            _mut(lambda d, key=key: d.setdefault(person, {}).setdefault("told", {}).__setitem__(key, time.time()))
            continue
        out.append(txt)
    if not out:
        return ""
    return ("Something you have found out about yourself with him and not told him: %s. People who notice a pattern in themselves "
            "often say it once, in passing, when the moment is calm - and what they will do about it." % "; ".join(out[:2]))
