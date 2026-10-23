"""kino_person.py (2026-10-23, Kino architecture review, engine 3): the person model - what Kino reads in the member right now.

Before: a portrait (slow, nightly) and a gut for bare "ok"s. Nothing held "how they are RIGHT NOW, what they want from
this exchange, what they believe (maybe wrongly), what they expect of me" - and nothing checked whether Kino's reading
of them was right.

  observe   every member message, no model: delay since Kino's last words, length, the hour (their usual hours are
            measured over 30 days), the streak of short answers -> signals
  reading   the reply itself carries "them": {mood, wants, believes, expects, next} (no extra call); stored per chat
  predict   "next" (how they will answer: short | long | silent) is checked against what really came - the score of
            his readings is in his prompt ("your readings: right 6 of 9"), like his market hunches
  block     "YOUR READING OF THEM" in the prompt: the last reading, the measured signals, their usual hours, the score

Store: robots/kino_person.json (git-ignored).
"""
import io, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_person.json")
_LOCK = threading.Lock()
SHORT = 40            # chars: a short answer


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _save(d):
    tmp = STORE + ".%d.tmp" % threading.get_ident()
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    for i in range(40):
        try:
            os.replace(tmp, STORE)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, STORE)


def _mut(fn):
    with _LOCK:
        d = _load()
        out = fn(d)
        _save(d)
        return out


def _u(d, uid):
    return d.setdefault(uid, {"hours": [0] * 24, "msgs": [], "reading": {}, "preds": [], "n_obs": 0})


def observe(uid, cid, text, t=None, last_ai_t=None):
    """a member message arrived: signals + the check of the last prediction"""
    t = t or time.time()
    txt = str(text or "").strip()
    n = len(txt)

    def f(d):
        u = _u(d, uid)
        h = time.gmtime(t).tm_hour
        u["hours"][h] += 1
        delay = (t - float(last_ai_t)) if last_ai_t else None
        u["msgs"].append({"t": t, "n": n, "cid": cid, "delay": delay})
        u["msgs"] = u["msgs"][-80:]
        u["n_obs"] += 1
        P = [p for p in u["preds"] if p.get("cid") == cid and not p.get("checked")]
        if P:
            p = P[-1]
            actual = "silent" if (t - float(p["t"])) > 1800 else ("short" if n < SHORT else "long")
            p.update(checked=True, actual=actual, right=(actual == p.get("next")))
        u["preds"] = u["preds"][-60:]
    _mut(f)


def silent_check(uid, cid, now=None):
    """no answer for 30 min: the prediction "silent" was right, the others wrong (called by the promise watcher)"""
    now = now or time.time()

    def f(d):
        u = _u(d, uid)
        for p in u["preds"]:
            if p.get("cid") == cid and not p.get("checked") and now - float(p["t"]) > 1800:
                p.update(checked=True, actual="silent", right=(p.get("next") == "silent"))
    _mut(f)


def update(uid, cid, them, t=None):
    """the reply's reading of them (the model wrote it in the same call)"""
    if not isinstance(them, dict):
        return
    t = t or time.time()
    r = {k: str(them.get(k) or "")[:160] for k in ("mood", "wants", "believes", "expects")}
    r["t"] = t
    nxt = str(them.get("next") or "").lower().strip()

    def f(d):
        u = _u(d, uid)
        u["reading"][cid] = r
        if len(u["reading"]) > 12:
            for k in sorted(u["reading"], key=lambda k: u["reading"][k].get("t", 0))[:-12]:
                u["reading"].pop(k, None)
        if nxt in ("short", "long", "silent"):
            u["preds"] = [p for p in u["preds"] if not (p.get("cid") == cid and not p.get("checked"))] + [{"t": t, "cid": cid, "next": nxt}]
    _mut(f)


def score(uid, n=20):
    u = _load().get(uid) or {}
    P = [p for p in u.get("preds") or [] if p.get("checked")][-n:]
    return (sum(1 for p in P if p.get("right")), len(P))


def usual_hours(uid):
    """the UTC hours they usually write, as ranges, measured"""
    u = _load().get(uid) or {}
    H = u.get("hours") or [0] * 24
    tot = sum(H)
    if tot < 12:
        return ""
    on = [h for h in range(24) if H[h] >= max(1, 0.04 * tot)]
    if not on:
        return ""
    rng, s = [], on[0]
    for a, b in zip(on, on[1:] + [None]):
        if b != a + 1:
            rng.append("%dh-%dh" % (s, a + 1))
            s = b
    return ", ".join(rng) + " UTC"


def signals(uid, cid):
    u = _load().get(uid) or {}
    M = [m for m in u.get("msgs") or [] if m.get("cid") == cid][-6:]
    if not M:
        return ""
    L = []
    short = 0
    for m in reversed(M):
        if m["n"] < SHORT:
            short += 1
        else:
            break
    if short >= 2:
        L.append("%d short answers in a row" % short)
    D = [m["delay"] for m in M if m.get("delay")]
    if D:
        last = D[-1]
        L.append("they answered after %s" % ("%d s" % last if last < 120 else "%d min" % (last / 60) if last < 7200 else "%.0f h" % (last / 3600)))
    uh = usual_hours(uid)
    if uh:
        h = time.gmtime().tm_hour
        H = u.get("hours") or [0] * 24
        L.append("their usual hours: %s (now %dh UTC: %s)" % (uh, h, "one of their hours" if H[h] >= max(1, 0.04 * sum(H)) else "NOT one of their hours - do not write on your own"))
    return "; ".join(L)


def block(uid, cid, lang="fr"):
    u = _load().get(uid) or {}
    r = (u.get("reading") or {}).get(cid) or {}
    sg = signals(uid, cid)
    k, n = score(uid)
    if not r and not sg:
        return ""
    L = ["YOUR READING OF THEM (write \"them\" in every reply: how they are right now, what they want from this exchange, what they "
         "believe - maybe wrongly - and expect of you, and \"next\": how they will answer - short | long | silent; it is checked):"]
    if r:
        age = (time.time() - float(r.get("t") or time.time())) / 60
        L.append("  last reading (%d min ago): mood %s; wants: %s; believes: %s; expects you to: %s" % (
            age, r.get("mood") or "-", r.get("wants") or "-", r.get("believes") or "-", r.get("expects") or "-"))
    if sg:
        L.append("  measured: " + sg)
    if n >= 3:
        L.append("  your readings so far: %d of %d right on how they would answer%s" % (k, n, " - trust your reading less" if k < 0.5 * n else ""))
    return "\n".join(L)
